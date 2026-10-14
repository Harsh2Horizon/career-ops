from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pypdf import PdfReader

from career_ops.common.io import CareerOpsError, atomic_write, digest, slug, write_json
from career_ops.models.contracts import CandidateProfile, GeneratedDocument, TailoredResume
from career_ops.resume.tailoring import validate_claims

SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape(text: object) -> str:
    value = unicodedata.normalize("NFC", str(text or ""))
    value = value.replace("\x00", "").replace("\r", " ").replace("\n", " ")
    return "".join(SPECIAL.get(c, c) for c in value)


def safe_link(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"https", "http", "mailto"}
        or parsed.username
        or parsed.password
        or any(ord(c) < 32 for c in value)
    ):
        raise CareerOpsError(
            "unsafe_document_link", "Only HTTP(S) and email document links are allowed"
        )
    # Escape URL metacharacters too: profile content cannot inject TeX commands.
    return escape(value)


def engine() -> tuple[str, str]:
    if shutil.which("latexmk"):
        for option, executable in (("-xelatex", "xelatex"), ("-lualatex", "lualatex")):
            if shutil.which(executable):
                return "latexmk", option
        if shutil.which("pdflatex"):
            return "latexmk", "-pdf"
    for name in ("tectonic", "xelatex", "lualatex", "pdflatex"):
        if shutil.which(name):
            return name, ""
    raise CareerOpsError(
        "latex_missing",
        "Install Tectonic (brew install tectonic) or TeX Live with latexmk and XeLaTeX; install Poppler for PDF inspection",
    )


def render_tex(
    resume: TailoredResume,
    template_dir: Path,
    template: str = "professional",
    compact: bool = False,
) -> str:
    if template not in {"professional", "compact", "modern"}:
        raise CareerOpsError("unknown_template", "Choose professional, compact, or modern")
    environment = Environment(
        loader=FileSystemLoader(template_dir),
        undefined=StrictUndefined,
        autoescape=False,
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
    )
    environment.filters.update(tex=escape, link=safe_link)
    return environment.get_template(f"{template}.tex").render(
        resume=resume,
        compact=compact,
        font="Times New Roman"
        if Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf").exists()
        else "Latin Modern Roman",
    )


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def expected_text(resume: TailoredResume) -> list[str]:
    values = [v.text for v in resume.contact.values()]
    for name in ("education", "experience", "projects"):
        for item in getattr(resume, name):
            values += [
                v for v in (item.name, item.role, item.duration, item.location, item.grade) if v
            ]
            values += [b.text for b in item.bullets]
    values += [s.text for group in resume.skills.values() for s in group]
    return values


def validate_pdf(path: Path, resume: TailoredResume, log: str = "", max_pages: int = 2) -> dict:
    if not path.is_file() or path.stat().st_size < 1000:
        raise CareerOpsError("pdf_missing", "Compilation produced no readable PDF")
    try:
        reader = PdfReader(path)
        page_text = [p.extract_text() or "" for p in reader.pages]
    except Exception as exc:
        raise CareerOpsError("pdf_unreadable", "Unable to read generated PDF") from exc
    extracted = "\n".join(page_text)
    if not extracted.strip():
        raise CareerOpsError("pdf_no_text", "PDF text is not extractable")
    if not 1 <= len(reader.pages) <= max_pages:
        raise CareerOpsError(
            "page_overflow",
            f"Resume has {len(reader.pages)} pages; configured maximum is {max_pages}",
        )
    required = [
        (resume.education, "Education"),
        (resume.experience, "Professional Experience"),
        (resume.projects, "Projects"),
        (resume.skills, "Technical Skills"),
    ]
    missing_sections = [title for items, title in required if items and title not in extracted]
    missing = [
        v for v in expected_text(resume) if normalized_text(v) not in normalized_text(extracted)
    ]
    if missing_sections or missing:
        raise CareerOpsError(
            "pdf_truncated",
            f"PDF omitted {len(missing)} content items or required sections: {missing_sections}",
        )
    actual_links = []
    for page in reader.pages:
        for annotation in page.get("/Annots", []):
            action = annotation.get_object().get("/A")
            if action and action.get("/URI"):
                actual_links.append(str(action["/URI"]))
    expected_links = [i.link for i in resume.projects if i.link]
    expected_links += [
        v.text for k, v in resume.contact.items() if k in {"linkedin", "github", "portfolio"}
    ]
    if "email" in resume.contact:
        expected_links.append("mailto:" + resume.contact["email"].text)
    if any(link not in actual_links for link in expected_links):
        raise CareerOpsError("pdf_links_missing", "Generated PDF lost an expected clickable link")
    if re.search(r"Overfull \\[hv]box", log):
        raise CareerOpsError(
            "layout_overflow",
            "LaTeX reported overflowing content; shorten selected content or adjust the template",
        )
    bounding_checked = False
    if shutil.which("pdftotext"):
        result = subprocess.run(
            ["pdftotext", "-bbox", str(path), "-"], capture_output=True, text=True, timeout=30
        )
        if result.returncode:
            raise CareerOpsError(
                "pdf_text_tool_failed", "Poppler could not inspect PDF text positions"
            )
        tree = ET.fromstring(result.stdout)
        for page in tree.findall(".//{*}page"):
            width, height = float(page.attrib["width"]), float(page.attrib["height"])
            for word in page.findall(".//{*}word"):
                if (
                    float(word.attrib["xMin"]) < 10
                    or float(word.attrib["yMin"]) < 10
                    or float(word.attrib["xMax"]) > width - 10
                    or float(word.attrib["yMax"]) > height - 10
                ):
                    raise CareerOpsError(
                        "layout_overflow", "Text crosses the printable page safety boundary"
                    )
        bounding_checked = True
    return {
        "pages": len(reader.pages),
        "extractable_text": True,
        "all_content_present": True,
        "links": actual_links,
        "bounding_boxes_checked": bounding_checked,
        "visual_review_required": True,
        "text_characters": len(extracted),
    }


def document_fingerprint(
    resume: TailoredResume,
    templates: Path,
    template: str,
    preferred_pages: int = 1,
    max_pages: int = 2,
) -> str:
    return digest(
        [
            "document-v2",
            resume.model_dump(mode="json"),
            template,
            preferred_pages,
            max_pages,
            *(p.read_bytes().hex() for p in sorted(templates.glob("*.tex"))),
        ]
    )


def compile_resume(
    resume: TailoredResume,
    profile: CandidateProfile,
    output: Path,
    templates: Path,
    template: str = "professional",
    preferred_pages: int = 1,
    max_pages: int = 2,
) -> GeneratedDocument:
    validate_claims(resume, profile)
    executable, option = engine()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Compile in a temporary directory and publish only fully validated documents.
    with tempfile.TemporaryDirectory(prefix=".build-", dir=output) as temporary:
        folder = Path(temporary)
        log = ""
        for compact in (False, True):
            tex = render_tex(resume, templates, template, compact)
            atomic_write(folder / "resume.tex", tex)
            if executable == "latexmk":
                command = [
                    executable,
                    option,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-no-shell-escape",
                    "-outdir=" + str(folder),
                    str(folder / "resume.tex"),
                ]
            elif executable == "tectonic":
                command = [
                    executable,
                    "--untrusted",
                    "--keep-logs",
                    "--outdir",
                    str(folder),
                    str(folder / "resume.tex"),
                ]
            else:
                command = [
                    executable,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-no-shell-escape",
                    "-output-directory=" + str(folder),
                    str(folder / "resume.tex"),
                ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    cwd=folder,
                    env={
                        **os.environ,
                        "SOURCE_DATE_EPOCH": os.environ.get("SOURCE_DATE_EPOCH", "946684800"),
                        "TECTONIC_CACHE_DIR": os.environ.get(
                            "TECTONIC_CACHE_DIR",
                            str(
                                next((p for p in output.parents if p.name == "resumes"), output)
                                / ".tectonic-cache"
                            ),
                        ),
                    },
                )
            except subprocess.TimeoutExpired as exc:
                raise CareerOpsError(
                    "latex_timeout",
                    "LaTeX compilation timed out; verify the local TeX bundle/cache",
                ) from exc
            log = (
                result.stdout
                + result.stderr
                + (
                    (folder / "resume.log").read_text(errors="replace")
                    if (folder / "resume.log").exists()
                    else ""
                )
            )
            if result.returncode:
                atomic_write(output / "compile-error.log", log)
                raise CareerOpsError(
                    "latex_failed",
                    f"LaTeX failed; inspect {output / 'compile-error.log'}. Install/cache the required TeX packages when offline.",
                )
            pages = len(PdfReader(folder / "resume.pdf").pages)
            if pages <= preferred_pages or compact:
                break
        validation = validate_pdf(folder / "resume.pdf", resume, log, max_pages)
        atomic_write(output / "resume.tex", tex)
        atomic_write(output / "resume.pdf", (folder / "resume.pdf").read_bytes())
    name = resume.contact.get("full_name")
    upload = output / ((slug(name.text).replace("-", "_") if name else "Candidate") + "_Resume.pdf")
    atomic_write(upload, (output / "resume.pdf").read_bytes())
    document = GeneratedDocument(
        job_id=resume.job_id,
        input_hash=document_fingerprint(resume, templates, template, preferred_pages, max_pages),
        profile_hash=resume.profile_hash,
        pdf_path=str(output / "resume.pdf"),
        tex_path=str(output / "resume.tex"),
        upload_path=str(upload),
        sha256=digest(upload.read_bytes()),
        template=template,
        pages=validation["pages"],
        validated=True,
        validation=validation,
    )
    write_json(output / "document.json", document)
    preview_pdf(output / "resume.pdf", output)
    return document


def preview_pdf(pdf: Path, output: Path) -> list[Path]:
    if not shutil.which("pdftoppm"):
        return []
    result = subprocess.run(
        ["pdftoppm", "-scale-to", "1400", "-png", str(pdf), str(output / "preview")],
        capture_output=True,
        timeout=60,
    )
    if result.returncode:
        raise CareerOpsError("pdf_render_failed", "Poppler could not render the resume preview")
    return sorted(output.glob("preview-*.png"))

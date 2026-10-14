from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from career_ops.common.config import Preferences, Workspace
from career_ops.common.io import (
    CareerOpsError,
    artifact_lock,
    atomic_write,
    digest,
    slug,
    write_json,
)
from career_ops.common.logging import log_event
from career_ops.common.security import canonical_url
from career_ops.matching.analysis import analyze, mentions, tech_set
from career_ops.matching.scoring import match
from career_ops.models.contracts import (
    CandidateProfile,
    Fact,
    GeneratedDocument,
    JobAnalysis,
    JobListing,
    MatchResult,
    Provenance,
    Status,
    TailoredResume,
)
from career_ops.resume.documents import compile_resume, document_fingerprint
from career_ops.resume.profile import read_profile
from career_ops.resume.tailoring import tailor
from career_ops.search.providers import (
    Fetcher,
    PublicBoardProvider,
    board_from_url,
    normalize,
    structured_jobs,
)
from career_ops.storage.repository import Repository


def filters(
    job: JobListing, preferences: Preferences, analysis: JobAnalysis | None = None
) -> list[str]:
    analysis = analysis or analyze(job)
    reasons = []
    if any(role.lower() in job.title.lower() for role in preferences.excluded_roles):
        reasons.append("Excluded role")
    if preferences.target_roles and not any(
        role.lower() in job.title.lower() for role in preferences.target_roles
    ):
        reasons.append("Title outside configured target roles; manual review recommended")
    if analysis.seniority in preferences.excluded_seniorities:
        reasons.append("Excluded seniority: " + analysis.seniority)
    if (
        preferences.seniority_levels
        and analysis.seniority
        and analysis.seniority not in preferences.seniority_levels
    ):
        reasons.append("Seniority outside preference")
    for values, actual, label in [
        (preferences.preferred_countries, job.country, "Country"),
        (preferences.industries, job.industry, "Industry"),
        (preferences.company_sizes, job.company_size, "Company size"),
    ]:
        if values and actual and actual.casefold() not in [v.casefold() for v in values]:
            reasons.append(label + " outside preference")
    maximum = preferences.experience.get("maximum_years")
    if (
        maximum is not None
        and analysis.minimum_years is not None
        and analysis.minimum_years > maximum
    ):
        reasons.append(
            f"Experience minimum {analysis.minimum_years:g} exceeds preference {maximum:g}"
        )
    if job.date_posted:
        from career_ops.common.io import now

        if (now() - job.date_posted).days > preferences.job_recency_days:
            reasons.append("Older than configured posting recency")
    if job.company in preferences.excluded_companies:
        reasons.append("Excluded company")
    if (
        preferences.locations
        and job.location
        and not any(v.lower() in job.location.lower() for v in preferences.locations)
    ):
        reasons.append("Location outside preference")
    if (
        preferences.work_modes
        and job.work_mode
        and job.work_mode.lower() not in [s.lower() for s in preferences.work_modes]
    ):
        reasons.append("Work mode outside preference")
    found = tech_set(job.description)
    if any(
        tech_set(s) & found or mentions(job.description, s)
        for s in preferences.excluded_technologies
    ):
        reasons.append("Excluded technology")
    return reasons


def search_queries(preferences: Preferences) -> list[dict]:
    roles = preferences.target_roles[:5] or ["Software Engineer"]
    tech = preferences.preferred_technologies[:5]
    return [
        {
            "source": source,
            "query": f'site:{domain} "{role}" '
            + " ".join(tech[:2])
            + " "
            + (" ".join(preferences.locations) if preferences.locations else ""),
        }
        for source, domain in [
            ("linkedin", "linkedin.com/jobs"),
            ("indeed", "indeed.com"),
            ("wellfound", "wellfound.com"),
            ("glassdoor", "glassdoor.com"),
            ("google", "jobs"),
            ("ycombinator", "workatastartup.com"),
            ("company", "careers"),
            ("workday", "myworkdayjobs.com"),
        ]
        for role in roles
    ]


class Workflow:
    def __init__(self, workspace: Workspace, repository: Repository | None = None):
        self.workspace = workspace
        workspace.initialize()
        self.repository = repository or Repository(workspace.db)

    def profile(self) -> CandidateProfile:
        profile = read_profile(self.workspace.profile_path)
        for proposal in self.repository.approved_facts():
            if proposal["field"].startswith("answer:"):
                continue
            field = proposal["field"]
            fact = Fact(
                fact_id=proposal["proposal_id"],
                text=proposal["value"],
                kind="approved",
                provenance=Provenance(
                    source=str(self.workspace.db),
                    pointer="/fact_proposals/" + proposal["proposal_id"],
                    evidence=proposal["evidence"],
                ),
            )
            if field.startswith("contact."):
                profile.contact[field[8:]] = fact
            else:
                profile.approved_facts.append(fact)
                if field == "skill":
                    profile.skills.setdefault("Approved Knowledge", []).append(fact)
                elif field.startswith(("work:", "project:")):
                    kind, item_id = field.split(":", 1)
                    collection = profile.experience if kind == "work" else profile.projects
                    item = next((i for i in collection if i.item_id == item_id), None)
                    if item is None:
                        raise CareerOpsError(
                            "stale_fact_target",
                            "Approved fact refers to a missing profile item; review its evidence",
                        )
                    fact.kind = "professional" if kind == "work" else "project"
                    item.bullets.append(fact)
        self.repository.put_artifact(
            "candidate_profile_references",
            profile.profile_id,
            digest(profile.model_dump(mode="json")),
            {
                "source_path": profile.source_path,
                "source_hash": profile.source_hash,
                "approved_fact_ids": [f.fact_id for f in profile.approved_facts],
            },
        )
        return profile

    def import_job(self, raw: dict, source: str = "manual") -> JobListing:
        job = normalize(raw, source)
        board = board_from_url(job.source_url)
        self.repository.register_board(board.pop("url"), **board)
        job.filtered_reasons = filters(job, self.workspace.preferences())
        job, _ = self.repository.put_job(job)
        write_json(self.workspace.data / "jobs" / job.job_id / "job.json", job)
        return job

    def assist_url(self, url: str, access_permitted: bool = False) -> JobListing:
        board = board_from_url(url)
        self.repository.register_board(board["url"], board["provider"], board=board.get("board"))
        if board["provider"] in {"greenhouse", "lever", "ashby"}:
            jobs = PublicBoardProvider(Fetcher()).discover(board)
            canonical = canonical_url(url)
            listing = next(
                (j for j in jobs if j.source_url == canonical or j.application_url == canonical),
                None,
            )
            if listing is None:
                raise CareerOpsError(
                    "job_not_in_feed",
                    "Provided link did not match an active public posting; import its verified description",
                )
            self.repository.put_job(listing)
            return listing
        jobs = structured_jobs(Fetcher().permitted_html(url, access_permitted), url)
        if len(jobs) != 1:
            raise CareerOpsError(
                "structured_job_missing",
                "No unique structured JobPosting found; use Codex browser/web tools and import the verified description",
            )
        self.repository.put_job(jobs[0])
        return jobs[0]

    def search(
        self, preferences: Preferences | None = None, required_technologies: list[str] | None = None
    ) -> dict:
        preferences = preferences or self.workspace.preferences()
        sources = (
            self.workspace.yaml("search_sources.yaml").get("sources", [])
            + self.repository.list_boards()
        )
        enabled = [s for s in sources if s.get("enabled")]
        errors, discovered = [], []

        def discover(source):
            if source["provider"] == "structured":
                return structured_jobs(
                    Fetcher().permitted_html(source["url"], source.get("access_permitted", False)),
                    source["url"],
                )
            return PublicBoardProvider(Fetcher()).discover(source)

        with ThreadPoolExecutor(max_workers=preferences.concurrency) as pool:
            tasks = {pool.submit(discover, s): s for s in enabled}
            for future in as_completed(tasks):
                source = tasks[future]
                try:
                    for job in future.result():
                        job.filtered_reasons = filters(job, preferences)
                        if required_technologies and not any(
                            tech_set(t) & tech_set(job.description) or mentions(job.description, t)
                            for t in required_technologies
                        ):
                            job.filtered_reasons.append(
                                "Outside explicitly requested technology filter"
                            )
                        applied = self.repository.application(job.job_id)
                        if applied and applied.status in {
                            Status.SUBMITTED,
                            Status.SUBMISSION_UNVERIFIED,
                        }:
                            job.filtered_reasons.append(
                                "Already applied or submission outcome unresolved"
                            )
                        job, _ = self.repository.put_job(job)
                        write_json(self.workspace.data / "jobs" / job.job_id / "job.json", job)
                        discovered.append(job.job_id)
                except CareerOpsError as exc:
                    errors.append(
                        {
                            "source": source.get("board", source.get("url")),
                            "code": exc.code,
                            "message": str(exc),
                        }
                    )
                except (ValueError, KeyError, TypeError) as exc:
                    errors.append(
                        {
                            "source": source.get("board"),
                            "code": "provider_schema_changed",
                            "message": type(exc).__name__,
                        }
                    )
        ranked = []
        for job_id in set(discovered):
            job = self.repository.job(job_id)
            if not job.filtered_reasons:
                relevance = sum(
                    bool(tech_set(t) & tech_set(job.description)) or mentions(job.description, t)
                    for t in preferences.preferred_technologies
                )
                ranked.append(
                    {
                        "job_id": job_id,
                        "discovery_relevance": relevance,
                        "posting_recency_verified": job.date_posted is not None,
                    }
                )
        ranked.sort(key=lambda r: (-r["discovery_relevance"], r["job_id"]))
        result = {
            "job_ids": [r["job_id"] for r in ranked],
            "ranked_results": ranked,
            "all_discovered_job_ids": sorted(set(discovered)),
            "errors": errors,
            "assisted_queries": search_queries(preferences),
            "note": "Assisted queries use Codex web/browser tools. No unsupported source scraping is performed.",
        }
        write_json(self.workspace.data / "jobs" / "search_result.json", result)
        write_json(
            self.workspace.data / "jobs" / "filtered_jobs.json",
            self.repository.list_jobs(filtered=True),
        )
        return result

    def analyze(self, job_id: str) -> JobAnalysis:
        job = self.repository.job(job_id)
        result = analyze(job)
        cached = self.repository.artifact("job_analyses", job_id, result.input_hash)
        if cached:
            return JobAnalysis.model_validate(cached)
        self.repository.put_artifact("job_analyses", job_id, result.input_hash, result)
        if job.status == Status.DISCOVERED:
            self.repository.set_job_status(job_id, Status.ANALYZED)
        write_json(self.workspace.data / "jobs" / job_id / "job_analysis.json", result)
        return result

    def match(self, job_id: str) -> MatchResult:
        analysis = self.analyze(job_id)
        job = self.repository.job(job_id)
        result = match(self.profile(), job, analysis, self.workspace.preferences())
        self.repository.put_artifact("job_matches", job_id, result.input_hash, result)
        if job.status == Status.ANALYZED:
            self.repository.set_job_status(job_id, Status.MATCHED)
        write_json(self.workspace.data / "jobs" / job_id / "match_result.json", result)
        return result

    def shortlist(self, minimum: float) -> list[str]:
        selected = []
        for job in self.repository.list_jobs():
            matching = self.match(job.job_id)
            if matching.overall_score >= minimum and not matching.blocking_requirements:
                if self.repository.job(job.job_id).status == Status.MATCHED:
                    self.repository.set_job_status(job.job_id, Status.SHORTLISTED)
                selected.append(job.job_id)
        return selected

    def tailor(self, job_id: str) -> TailoredResume:
        analysis, matching = self.analyze(job_id), self.match(job_id)
        job, profile = self.repository.job(job_id), self.profile()
        result, report = tailor(profile, job, analysis, matching)
        base = self.workspace.data / "resumes" / slug(job.company or "unknown") / job_id
        output = base / "content-versions" / result.input_hash[:16]
        write_json(output / "tailored_resume.json", result)
        atomic_write(output / "tailoring_report.md", report)
        write_json(base / "tailored_resume.json", result)
        atomic_write(base / "tailoring_report.md", report)
        return result

    def resume(
        self, job_id: str, template: str | None = None
    ) -> tuple[TailoredResume, GeneratedDocument]:
        with artifact_lock(self.workspace.data / "locks" / ("resume-" + slug(job_id) + ".lock")):
            return self._resume(job_id, template)

    def current_document(self, job_id: str) -> GeneratedDocument:
        job = self.repository.job(job_id)
        path = (
            self.workspace.data
            / "resumes"
            / slug(job.company or "unknown")
            / job_id
            / "document.json"
        )
        if not path.is_file():
            raise CareerOpsError("resume_missing", "Run careerops resume build JOB_ID first")
        return GeneratedDocument.model_validate_json(path.read_text())

    def _publish_document(self, base: Path, output: Path, document: GeneratedDocument) -> None:
        for filename in (
            "tailored_resume.json",
            "tailoring_report.md",
            "resume.tex",
            "resume.pdf",
            "document.json",
            Path(document.upload_path).name,
        ):
            link = base / filename
            temporary = base / (".link-" + filename)
            if temporary.exists() or temporary.is_symlink():
                temporary.unlink()
            temporary.symlink_to((output / filename).relative_to(base))
            os.replace(temporary, link)

    def _resume(
        self, job_id: str, template: str | None = None
    ) -> tuple[TailoredResume, GeneratedDocument]:
        analysis = self.analyze(job_id)
        matching = self.match(job_id)
        job, profile = self.repository.job(job_id), self.profile()
        preferences = self.workspace.preferences()
        tailored, report = tailor(profile, job, analysis, matching)
        base = self.workspace.data / "resumes" / slug(job.company or "unknown") / job_id
        templates = self.workspace.root / "templates"
        chosen = template or preferences.resume.get("default_template", "professional")
        fingerprint = document_fingerprint(
            tailored,
            templates,
            chosen,
            preferences.resume.get("preferred_pages", 1),
            preferences.resume.get("max_pages", 2),
        )
        cached = self.repository.artifact("resumes", job_id, fingerprint)
        if cached:
            doc = GeneratedDocument.model_validate(cached)
            if (
                Path(doc.pdf_path).is_file()
                and digest(Path(doc.pdf_path).read_bytes()) == doc.sha256
            ):
                self._publish_document(base, Path(doc.pdf_path).parent, doc)
                return tailored, doc
        output = base / "versions" / fingerprint[:16]
        write_json(output / "tailored_resume.json", tailored)
        atomic_write(output / "tailoring_report.md", report)
        document = compile_resume(
            tailored,
            profile,
            output,
            templates,
            chosen,
            preferences.resume.get("preferred_pages", 1),
            preferences.resume.get("max_pages", 2),
        )
        self.repository.put_artifact("resumes", job_id, document.input_hash, document)
        if self.repository.job(job_id).status in {Status.MATCHED, Status.SHORTLISTED}:
            self.repository.set_job_status(job_id, Status.RESUME_GENERATED)
        self._publish_document(base, output, document)
        return tailored, document

    def run(self, mode: str, mock: bool = False) -> dict:
        failures, completed = [], []
        if mode == "search-and-rank":
            search_result = self.search()
            job_ids = search_result["job_ids"]
            task = self.match
            failures += search_result["errors"]
        elif mode == "generate-resumes":
            job_ids = [
                j.job_id
                for j in self.repository.list_jobs()
                if j.status in {Status.SHORTLISTED, Status.RESUME_GENERATED}
            ]

            def task(job_id):
                return self.resume(job_id)[1]
        elif mode == "prepare-shortlisted":
            job_ids = [
                j.job_id
                for j in self.repository.list_jobs()
                if j.status
                in {
                    Status.SHORTLISTED,
                    Status.RESUME_GENERATED,
                    Status.APPLICATION_STARTED,
                    Status.NEEDS_INFORMATION,
                    Status.FAILED,
                }
            ]
            # Browser workflows are deliberately sequential; PDFs/analysis may run concurrently.
            from career_ops.applications.service import ApplicationService

            def task(job_id):
                resume, document = self.resume(job_id)
                return ApplicationService(self.workspace, self.repository).prepare(
                    self.repository.job(job_id), self.profile(), resume, document, mock
                )
        else:
            raise CareerOpsError(
                "unknown_mode", "Use search-and-rank, generate-resumes, or prepare-shortlisted"
            )

        def handle(job_id):
            try:
                result = task(job_id)
                return {
                    "job_id": job_id,
                    "result": result.model_dump(
                        mode="json", exclude={"form"} if hasattr(result, "form") else set()
                    ),
                }
            except CareerOpsError as exc:
                log_event(
                    self.workspace.data / "logs", "workflow_failed", job_id=job_id, code=exc.code
                )
                return {"job_id": job_id, "error": {"code": exc.code, "message": str(exc)}}

        if mode in {"search-and-rank", "generate-resumes"}:
            with ThreadPoolExecutor(max_workers=self.workspace.preferences().concurrency) as pool:
                results = list(pool.map(handle, job_ids))
        else:
            results = [handle(job_id) for job_id in job_ids]
        for result in results:
            (failures if "error" in result else completed).append(result)
        return {"completed": completed, "failures": failures, "mode": mode}

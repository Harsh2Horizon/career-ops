from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pypdf import PdfReader
from typer.testing import CliRunner

from career_ops.applications.service import ApplicationService
from career_ops.cli.main import app
from career_ops.common.io import CareerOpsError
from career_ops.models.contracts import Status
from career_ops.search.providers import Fetcher, PublicBoardProvider, structured_jobs


@pytest.mark.parametrize(
    "provider,payload",
    [
        (
            "greenhouse",
            {
                "jobs": [
                    {
                        "id": 1,
                        "title": "Backend Engineer",
                        "location": {"name": "Remote"},
                        "absolute_url": "https://boards.greenhouse.io/example/jobs/1",
                        "content": "<h2>Requirements</h2><p>Go required.</p>",
                        "updated_at": "2026-01-01T00:00:00Z",
                    }
                ]
            },
        ),
        (
            "lever",
            [
                {
                    "id": "2",
                    "text": "Backend Engineer",
                    "categories": {"location": "Remote", "commitment": "Full-time"},
                    "hostedUrl": "https://jobs.lever.co/example/2",
                    "applyUrl": "https://jobs.lever.co/example/2/apply",
                    "descriptionPlain": "Build APIs.",
                    "lists": [{"text": "Requirements", "content": "<li>Go required.</li>"}],
                }
            ],
        ),
        (
            "ashby",
            {
                "jobs": [
                    {
                        "id": "3",
                        "title": "Backend Engineer",
                        "location": "Remote",
                        "jobUrl": "https://jobs.ashbyhq.com/example/3",
                        "applyUrl": "https://jobs.ashbyhq.com/example/3/application",
                        "descriptionPlain": "Requirements\nGo required.",
                        "publishedAt": "2026-10-01T00:00:00Z",
                        "isListed": True,
                    }
                ]
            },
        ),
    ],
)
def test_public_provider_normalization(provider, payload):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    result = PublicBoardProvider(Fetcher(client, resolve=False)).discover(
        {"provider": provider, "board": "example", "company": "Example"}
    )
    assert len(result) == 1 and result[0].company == "Example"
    assert result[0].ats_id is not None and result[0].provenance
    if provider == "greenhouse":
        assert result[0].date_posted is None  # updated_at is not date posted
    if provider == "ashby":
        assert result[0].date_posted is not None


def test_jsonld_graph():
    html = (
        '<script type="application/ld+json">'
        + json.dumps(
            {
                "@graph": [
                    {
                        "@type": "JobPosting",
                        "title": "Engineer",
                        "hiringOrganization": {"name": "Example"},
                        "description": "<p>Go required.</p>",
                        "datePosted": "2026-10-01",
                        "url": "/jobs/1",
                    }
                ]
            }
        )
        + "</script>"
    )
    result = structured_jobs(html, "https://example.com/careers")
    assert result[0].source_url == "https://example.com/jobs/1"
    assert result[0].description == "Go required."


def test_redirect_private_blocked():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    with pytest.raises(CareerOpsError):
        Fetcher(httpx.Client(transport=httpx.MockTransport(handler)), resolve=False).get(
            "https://example.com/jobs"
        )


def test_robots_denial():
    def handler(request):
        return httpx.Response(
            200,
            text="User-agent: *\nDisallow: /jobs"
            if request.url.path == "/robots.txt"
            else "should not be fetched",
        )

    fetcher = Fetcher(httpx.Client(transport=httpx.MockTransport(handler)), resolve=False)
    with pytest.raises(CareerOpsError, match="robots"):
        fetcher.permitted_html("https://example.com/jobs", True)


@pytest.mark.pdf
@pytest.mark.parametrize("template", ["professional", "compact", "modern"])
def test_pdf_pipeline(flow, job, template):
    original = flow.workspace.profile_path.read_bytes()
    resume, document = flow.resume(job.job_id, template)
    reader = PdfReader(document.pdf_path)
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "Test Candidate" in text and "Associate Developer" in text
    assert "7.71" in text and "6x" in text and document.pages <= 2
    assert list(Path(document.pdf_path).parent.glob("preview-*.png"))
    assert flow.workspace.profile_path.read_bytes() == original
    same = flow.resume(job.job_id, template)[1]
    assert same.pdf_path == document.pdf_path and same.sha256 == document.sha256
    assert flow.repository.job(job.job_id).status == Status.RESUME_GENERATED


class MemoryBrowser:
    """Deterministic driver contract test double; does not test a real browser."""

    def __init__(self, state):
        self.state = state
        self.step = 0

    def open(self, config):
        self.url = config["url"]
        return self.snapshot()

    def snapshot(self):
        fields = (
            [
                {
                    "field_id": "0:name",
                    "label": "Full name",
                    "control": "text",
                    "required": True,
                    "step": 0,
                },
                {
                    "field_id": "0:email",
                    "label": "Email",
                    "control": "email",
                    "required": True,
                    "step": 0,
                },
                {
                    "field_id": "0:resume",
                    "label": "Resume",
                    "control": "file",
                    "required": True,
                    "step": 0,
                },
            ]
            if self.step == 0
            else [
                {
                    "field_id": "1:auth",
                    "label": "Are you authorized to work in this country?",
                    "control": "select",
                    "required": True,
                    "options": ["Yes", "No"],
                    "step": 1,
                },
                {
                    "field_id": "1:consent",
                    "label": "I certify these test answers are accurate",
                    "control": "checkbox",
                    "required": True,
                    "step": 1,
                },
            ]
        )
        return {
            "fields": fields,
            "buttons": ["Next"] if self.step == 0 else ["Submit application"],
            "errors": [],
            "url": self.url,
        }

    def fill(self, field_id, control, value):
        self.state.setdefault("filled", {})[field_id] = value
        if control == "file":
            assert Path(value).read_bytes().startswith(b"%PDF")
            self.state["upload"] = Path(value).name

    def next(self):
        self.step += 1
        return self.snapshot()

    def submit(self):
        self.state["submissions"] = self.state.get("submissions", 0) + 1
        if self.state.get("fail_click"):
            raise CareerOpsError("network_failed", "Ambiguous response after click")
        return {
            "confirmed": True,
            "reference": "MOCK-APPLICATION-001",
            "evidence": "Application submitted. Application ID: MOCK-APPLICATION-001",
            "url": self.url,
        }

    def close(self):
        pass


@pytest.mark.pdf
def test_mock_driver_end_to_end_checkpoint(flow, job):
    job.application_url = "http://127.0.0.1:9999/apply"
    flow.repository.put_job(job)
    resume, document = flow.resume(job.job_id)
    profile = flow.profile()
    state = {}
    service = ApplicationService(flow.workspace, flow.repository, lambda: MemoryBrowser(state))
    incomplete = service.prepare(job, profile, resume, document, mock=True)
    assert incomplete.status == Status.NEEDS_INFORMATION and state.get("submissions", 0) == 0
    answers = {
        "Are you authorized to work in this country?": "Yes",
        "I certify these test answers are accurate": "true",
    }
    ready = service.prepare(job, profile, resume, document, mock=True, overrides=answers)
    assert ready.status == Status.READY_FOR_REVIEW and state.get("submissions", 0) == 0
    with pytest.raises(CareerOpsError):
        service.submit(job, profile, resume, document, mock=True, overrides=answers)
    flow.repository.approve(job.job_id, ready.form.review_digest)
    complete = service.submit(job, profile, resume, document, mock=True, overrides=answers)
    assert (
        complete.status == Status.SUBMITTED
        and complete.confirmation_reference == "MOCK-APPLICATION-001"
    )
    assert state["submissions"] == 1 and state["upload"] == "Test_Candidate_Resume.pdf"
    with pytest.raises(CareerOpsError):
        service.submit(job, profile, resume, document, mock=True, overrides=answers)
    assert state["submissions"] == 1
    assert len(flow.repository.history(complete.application_id)) >= 6


@pytest.mark.pdf
def test_ambiguous_submission_never_retried(flow, job):
    job.application_url = "http://127.0.0.1:9999/apply"
    flow.repository.put_job(job)
    resume, document = flow.resume(job.job_id)
    profile = flow.profile()
    state = {"fail_click": True}
    service = ApplicationService(flow.workspace, flow.repository, lambda: MemoryBrowser(state))
    answers = {
        "Are you authorized to work in this country?": "Yes",
        "I certify these test answers are accurate": "true",
    }
    ready = service.prepare(job, profile, resume, document, mock=True, overrides=answers)
    flow.repository.approve(job.job_id, ready.form.review_digest)
    with pytest.raises(CareerOpsError):
        service.submit(job, profile, resume, document, mock=True, overrides=answers)
    assert flow.repository.application(job.job_id).status == Status.SUBMISSION_UNVERIFIED
    with pytest.raises(CareerOpsError):
        service.prepare(job, profile, resume, document, mock=True, overrides=answers)
    assert state["submissions"] == 1


def test_cli_commands(flow, job):
    runner = CliRunner()
    for args in [
        ["init"],
        ["analyze", job.job_id],
        ["match", job.job_id],
        ["jobs", "show", job.job_id],
        ["jobs", "list"],
        ["sources", "list"],
        ["report", "--kind", "highest-matching"],
        ["applications", "export", "--format", "csv"],
    ]:
        result = runner.invoke(app, ["--workspace", str(flow.workspace.root), *args])
        assert result.exit_code == 0, result.output
        json.loads(result.output)


def test_no_enabled_sources_reports_assisted_queries(flow):
    result = flow.search()
    assert result["job_ids"] == [] and result["assisted_queries"] and not result["errors"]


@pytest.mark.pdf
def test_document_and_form_drift_block_submission(flow, job):
    job.application_url = "http://127.0.0.1:9999/apply"
    flow.repository.put_job(job)
    resume, document = flow.resume(job.job_id)
    profile = flow.profile()
    state = {}
    service = ApplicationService(flow.workspace, flow.repository, lambda: MemoryBrowser(state))
    answers = {
        "Are you authorized to work in this country?": "Yes",
        "I certify these test answers are accurate": "true",
    }
    review = service.prepare(job, profile, resume, document, mock=True, overrides=answers)
    flow.repository.approve(job.job_id, review.form.review_digest)
    with pytest.raises(CareerOpsError, match="changed"):
        service.submit(
            job,
            profile,
            resume,
            document,
            mock=True,
            overrides={**answers, "Are you authorized to work in this country?": "No"},
        )
    assert state.get("submissions", 0) == 0
    original = Path(document.upload_path).read_bytes()
    Path(document.upload_path).write_bytes(original + b"changed")
    with pytest.raises(CareerOpsError, match="changed"):
        service.submit(job, profile, resume, document, mock=True, overrides=answers)
    assert state.get("submissions", 0) == 0


@pytest.mark.pdf
def test_cached_template_updates_stable_document(flow, job):
    professional = flow.resume(job.job_id, "professional")[1]
    modern = flow.resume(job.job_id, "modern")[1]
    assert flow.current_document(job.job_id).template == "modern"
    again = flow.resume(job.job_id, "professional")[1]
    assert again.sha256 == professional.sha256
    assert flow.current_document(job.job_id).template == "professional"
    assert Path(modern.pdf_path).is_file()


@pytest.mark.pdf
def test_missing_contact_never_ready(flow, job):
    proposal_profile = flow.profile()
    proposal_profile.contact.clear()
    # Build matching content from a canonical profile without contact data.
    raw = flow.workspace.profile_path.read_text()
    import yaml

    parsed = yaml.safe_load(raw)
    parsed["resume"].pop("contact")
    flow.workspace.profile_path.write_text(yaml.safe_dump(parsed))
    job.application_url = "http://127.0.0.1:9999/apply"
    flow.repository.put_job(job)
    resume, document = flow.resume(job.job_id)
    state = {}
    service = ApplicationService(flow.workspace, flow.repository, lambda: MemoryBrowser(state))
    result = service.prepare(job, flow.profile(), resume, document, mock=True)
    assert result.status == Status.NEEDS_INFORMATION
    assert "Missing verified contact: email" in result.form.unresolved


@pytest.mark.pdf
def test_prechecked_declaration_requires_verification(flow, job):
    job.application_url = "http://127.0.0.1:9999/apply"
    flow.repository.put_job(job)
    resume, document = flow.resume(job.job_id)

    class PrecheckedBrowser(MemoryBrowser):
        def snapshot(self):
            current = super().snapshot()
            if self.step == 1:
                current["fields"].append(
                    {
                        "field_id": "1:terms",
                        "label": "Accept terms",
                        "control": "checkbox",
                        "checked": True,
                        "required": False,
                        "step": 1,
                    }
                )
            return current

    state = {}
    service = ApplicationService(flow.workspace, flow.repository, lambda: PrecheckedBrowser(state))
    answers = {
        "Are you authorized to work in this country?": "Yes",
        "I certify these test answers are accurate": "true",
    }
    result = service.prepare(job, flow.profile(), resume, document, mock=True, overrides=answers)
    assert result.status == Status.NEEDS_INFORMATION and "Accept terms" in result.form.unresolved

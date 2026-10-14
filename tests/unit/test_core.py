from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from career_ops.applications.forms import map_field
from career_ops.applications.service import review_digest
from career_ops.common.config import Preferences
from career_ops.common.io import CareerOpsError
from career_ops.common.security import canonical_url, validate_url
from career_ops.matching.analysis import analyze, tech_set
from career_ops.matching.scoring import evidence, match
from career_ops.models.contracts import (
    ApplicationAnswer,
    ApplicationForm,
    FormField,
    Status,
)
from career_ops.resume.documents import escape, render_tex, safe_link
from career_ops.resume.profile import professional_years, read_profile
from career_ops.resume.tailoring import tailor, validate_claims
from career_ops.storage.repository import Repository, validate_transition


def test_nonstandard_profile(workspace):
    p = read_profile(workspace.profile_path)
    assert len(p.projects) == 1
    assert p.experience[0].bullets[0].text.startswith("Migrated")
    assert p.education[0].grade == "7.71"
    assert p.source_fields["resume"]["unfamiliar_field"]["preserve"]
    assert professional_years(p, date(2026, 10, 13)) == 1.0


def test_actual_canonical_schema():
    path = Path(__file__).resolve().parents[2] / "resume.yaml"
    if not path.exists():
        pytest.skip("User-controlled canonical profile not installed")
    p = read_profile(path)
    assert p.experience and p.projects
    assert all(i.name for i in p.projects)
    assert len(p.source_hash) == 64


def test_dedupe_preserves_distinct_positions(flow, job):
    raw = job.model_dump(mode="json")
    raw["source_url"] += "?utm_source=linkedin"
    same = flow.import_job(raw)
    assert same.job_id == job.job_id
    other = raw.copy()
    other["source_url"] = "https://example.com/careers/backend-002"
    different = flow.import_job(other)
    assert different.job_id != job.job_id
    assert len(flow.repository.list_jobs(None)) == 2


def test_api_id_dedupe_preserves_history(flow, job):
    job.ats_id = "abc"
    flow.repository.put_job(job)
    # Source-specific IDs are used only with consistent source/company provenance.
    raw = job.model_copy(update={"job_id": "other", "source_url": "https://example.com/other"})
    flow.repository.put_job(raw)
    # Learning the ATS ID on refresh lets canonical aliases merge safely.
    assert len(flow.repository.list_jobs(None)) == 1


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "javascript:alert(1)", "https://user:secret@example.com/job"]
)
def test_unsafe_urls(url):
    with pytest.raises(CareerOpsError):
        canonical_url(url)


def test_navigation_policy():
    with pytest.raises(CareerOpsError):
        validate_url("http://example.com/job", resolve=False)
    with pytest.raises(CareerOpsError):
        validate_url("https://other.com/job", allowed_hosts=["example.com"], resolve=False)
    with pytest.raises(CareerOpsError):
        validate_url("https://example.com/job", mock=True)
    assert validate_url("http://127.0.0.1:1234/job", mock=True)


@pytest.mark.parametrize(
    "bad",
    [
        {"technical": 35},
        {"technical": -1, "experience": 25, "domain": 20, "location": 10, "other": 10},
    ],
)
def test_invalid_weights(bad):
    with pytest.raises(ValueError):
        Preferences(weights=bad)


def test_analysis_preference_not_hard(job):
    result = analyze(job)
    assert result.minimum_years == 0
    assert "Apache Flink" in result.ats_terminology
    assert any("PostgreSQL" in r.technologies for r in result.preferred_qualifications)
    assert not any("PostgreSQL" in r.technologies for r in result.required_qualifications)


def test_unknown_years_null(job):
    job.description = "We build interesting software."
    result = analyze(job)
    assert result.minimum_years is None and result.uncertainties


def test_tech_boundaries():
    assert "C" not in tech_set("CDC, C++20, caching")
    assert "Go" not in tech_set("Google")
    assert "C++" in tech_set("C++20")


def test_professional_project_listed_distinction(workspace, job):
    p = read_profile(workspace.profile_path)
    e = evidence(p)
    assert e["C++"].level == "project"
    assert e["MySQL"].level == "professional"
    assert e["LLMs"].level == "listed"
    job.description = "Requirements\nMust have production experience with LLMs and PyTorch.\nPreferred qualifications\nKafka is a plus."
    result = match(p, job, analyze(job), Preferences())
    assert result.blocking_requirements
    assert "Kafka" in result.missing_preferred_skills
    assert result.recommendation == "Poor Match"


def test_seniority_and_experience_blockers(workspace, job):
    job.title = "Senior Backend Engineer"
    job.description = "Requirements\nAt least 5 years of engineering experience."
    result = match(read_profile(workspace.profile_path), job, analyze(job), Preferences())
    assert len(result.blocking_requirements) >= 2
    assert result.experience_score < 100


def test_sensitive_eligibility_separate(workspace, job):
    job.description = (
        "Requirements\nMust have work authorization in the United States.\nMySQL and SQL required."
    )
    result = match(read_profile(workspace.profile_path), job, analyze(job), Preferences())
    assert result.unresolved_eligibility


def test_tailoring_provenance_and_original_preserved(workspace, job):
    before = workspace.profile_path.read_bytes()
    p = read_profile(workspace.profile_path)
    a = analyze(job)
    m = match(p, job, a, Preferences())
    tailored, report = tailor(p, job, a, m)
    validate_claims(tailored, p)
    assert workspace.profile_path.read_bytes() == before
    assert "LLMs" not in str(tailored.skills)
    assert "AI Applications" not in str(tailored.skills)
    assert tailored.experience[0].role == "Associate Developer"
    assert "Profile SHA256" in report
    tailored.projects[0].bullets[0].text += " Increased revenue by 90%."
    with pytest.raises(CareerOpsError, match="rewrites"):
        validate_claims(tailored, p)


def test_identity_cannot_change(workspace, job):
    p = read_profile(workspace.profile_path)
    a = analyze(job)
    tailored, _ = tailor(p, job, a, match(p, job, a, Preferences()))
    tailored.experience[0].role = "Senior Engineer"
    with pytest.raises(CareerOpsError, match="title"):
        validate_claims(tailored, p)


def test_latex_escaping():
    assert (
        escape("A&B 99% #1 $x_{y} \\ ~ ^")
        == r"A\&B 99\% \#1 \$x\_\{y\} \textbackslash{} \textasciitilde{} \textasciicircum{}"
    )
    assert escape("José") == "José"
    with pytest.raises(CareerOpsError):
        safe_link("javascript:alert(1)")


@pytest.mark.parametrize("template", ["professional", "compact", "modern"])
def test_templates(workspace, job, template):
    p = read_profile(workspace.profile_path)
    a = analyze(job)
    r, _ = tailor(p, job, a, match(p, job, a, Preferences()))
    rendered = render_tex(r, workspace.root / "templates", template)
    assert "\\documentclass[a4paper,10pt]" in rendered
    assert "<%" not in rendered and "Associate Developer" in rendered


def ready_record(flow, job):
    flow.analyze(job.job_id)
    flow.match(job.job_id)
    flow.repository.set_job_status(job.job_id, Status.RESUME_GENERATED)
    r = flow.repository.start_application(job.job_id)
    r.form = ApplicationForm(
        job_id=job.job_id,
        url=job.application_url,
        fields=[],
        answers=[],
        resume_sha256="a" * 64,
        profile_hash="b" * 64,
    )
    r.form.review_digest = review_digest(r.form)
    return flow.repository.update_application(r, Status.READY_FOR_REVIEW, "Prepared mock review")


def test_approval_and_submission_idempotency(flow, job):
    r = ready_record(flow, job)
    with pytest.raises(CareerOpsError):
        flow.repository.claim_submission(job.job_id, r.form.review_digest)
    with pytest.raises(CareerOpsError):
        flow.repository.approve(job.job_id, "wrong")
    flow.repository.approve(job.job_id, r.form.review_digest)
    flow.repository.claim_submission(job.job_id, r.form.review_digest)
    with pytest.raises(CareerOpsError):
        flow.repository.claim_submission(job.job_id, r.form.review_digest)
    assert flow.repository.application(job.job_id).status == Status.SUBMISSION_UNVERIFIED
    with pytest.raises(CareerOpsError):
        flow.repository.start_application(job.job_id)


def test_immutable_events_and_migrations(flow, job):
    r = ready_record(flow, job)
    history = flow.repository.history(r.application_id)
    with pytest.raises(sqlite3.IntegrityError):
        with flow.repository.connection(write=True) as c:
            c.execute("DELETE FROM application_events")
    reopened = Repository(flow.workspace.db)
    assert reopened.history(r.application_id) == history


def test_invalid_transition():
    with pytest.raises(CareerOpsError):
        validate_transition(Status.DISCOVERED, Status.SUBMITTED)
    validate_transition(Status.SUBMITTED, Status.INTERVIEW)


def test_sensitive_answers_never_guessed(workspace, job):
    p = read_profile(workspace.profile_path)
    mapping = workspace.yaml("field_mappings.yaml")
    f = FormField(
        field_id="1",
        label="Are you authorized to work in this country?",
        control="select",
        required=True,
        options=["Yes", "No"],
    )
    assert map_field(f, p, job, mapping, {}, "/resume.pdf").value is None
    assert map_field(f, p, job, mapping, {f.label: "Yes"}, "/resume.pdf").explicitly_verified
    with pytest.raises(ValueError):
        ApplicationAnswer(
            field_id="1", label=f.label, value="Yes", sensitive=True, source_fact_ids=["x"]
        )


def test_semantic_mapping(workspace, job):
    p = read_profile(workspace.profile_path)
    mapping = workspace.yaml("field_mappings.yaml")
    name = FormField(field_id="1", label="Full name", control="text")
    assert map_field(name, p, job, mapping, {}, "/resume.pdf").value == "Test Candidate"
    upload = FormField(field_id="2", label="Resume", control="file")
    assert map_field(upload, p, job, mapping, {}, "/resume.pdf").value == "/resume.pdf"
    current = FormField(field_id="3", label="Current employer", control="text")
    assert map_field(current, p, job, mapping, {}, "/resume.pdf").value is None


def test_factual_overlay_requires_explicit_verification(flow):
    before = flow.workspace.profile_path.read_bytes()
    proposal = flow.repository.propose_fact(
        "contact.linkedin", "https://example.com/linkedin", "User confirmed"
    )
    assert "linkedin" not in flow.profile().contact
    flow.repository.approve_fact(proposal)
    assert flow.profile().contact["linkedin"].text == "https://example.com/linkedin"
    assert flow.workspace.profile_path.read_bytes() == before

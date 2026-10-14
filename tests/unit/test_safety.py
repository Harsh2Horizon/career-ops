from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from career_ops.applications.service import review_digest
from career_ops.common.config import Preferences
from career_ops.common.io import CareerOpsError, now
from career_ops.common.workflow import filters
from career_ops.models.contracts import ApplicationForm, Status


def ready(flow, job):
    flow.match(job.job_id)
    flow.repository.set_job_status(job.job_id, Status.RESUME_GENERATED)
    record = flow.repository.start_application(job.job_id)
    record.form = ApplicationForm(
        job_id=job.job_id,
        url=job.application_url,
        fields=[],
        answers=[],
        profile_hash="p",
        resume_sha256="r",
    )
    record.form.review_digest = review_digest(record.form)
    return flow.repository.update_application(record, Status.READY_FOR_REVIEW, "Test review")


def test_expired_approval_cannot_claim(flow, job):
    record = ready(flow, job)
    record = flow.repository.approve(job.job_id, record.form.review_digest)
    record.approval_expires_at = now() - timedelta(seconds=1)
    flow.repository.update_application(record, Status.APPROVED, "Test expired approval")
    with pytest.raises(CareerOpsError, match="expired"):
        flow.repository.claim_submission(job.job_id, record.form.review_digest)


def test_concurrent_submit_reservation_only_one(flow, job):
    record = ready(flow, job)
    flow.repository.approve(job.job_id, record.form.review_digest)

    def claim(_):
        try:
            flow.repository.claim_submission(job.job_id, record.form.review_digest)
            return True
        except CareerOpsError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(claim, range(4)))
    assert outcomes.count(True) == 1


def test_unknown_sensitive_answer_blocks_approval(flow, job):
    record = ready(flow, job)
    record.form.unresolved = ["Citizenship"]
    record.form.review_digest = review_digest(record.form)
    flow.repository.update_application(record, Status.READY_FOR_REVIEW, "Test unresolved")
    with pytest.raises(CareerOpsError):
        flow.repository.approve(job.job_id, record.form.review_digest)


def test_approval_not_transferable_to_other_job(flow, job):
    record = ready(flow, job)
    raw = job.model_dump(mode="json")
    raw["source_url"] = "https://example.com/careers/second"
    other = flow.import_job(raw)
    other_record = ready(flow, other)
    with pytest.raises(CareerOpsError):
        flow.repository.approve(other.job_id, record.form.review_digest)
    assert other_record.form.review_digest != record.form.review_digest


def test_reprepare_invalidates_approval(flow, job):
    record = ready(flow, job)
    record = flow.repository.approve(job.job_id, record.form.review_digest)
    flow.repository.update_application(
        record, Status.APPLICATION_STARTED, "User resumed preparation"
    )
    with pytest.raises(CareerOpsError):
        flow.repository.claim_submission(job.job_id, record.form.review_digest)


def test_filtered_jobs_retained(flow, job):
    job.title = "Senior Software Engineer"
    job.description = "Requirements\nAt least 8 years required."
    raw = job.model_dump(mode="json")
    raw["source_url"] = "https://example.com/careers/senior"
    result = flow.import_job(raw)
    assert result.filtered_reasons
    assert result.job_id in [j.job_id for j in flow.repository.list_jobs(True)]
    assert result.job_id not in [j.job_id for j in flow.repository.list_jobs()]


def test_unknown_recency_not_invented(job):
    job.date_posted = None
    assert not any("recency" in r for r in filters(job, Preferences()))


def test_approval_cannot_be_disabled():
    with pytest.raises(ValueError):
        Preferences(applications={"require_submission_approval": False})


def test_maximum_two_pages():
    with pytest.raises(ValueError):
        Preferences(resume={"max_pages": 3})


def test_approved_skill_added_without_yaml_change(flow, job):
    original = flow.workspace.profile_path.read_bytes()
    proposed = flow.repository.propose_fact("skill", "REST APIs", "Explicitly confirmed by user")
    flow.repository.approve_fact(proposed)
    resume = flow.tailor(job.job_id)
    assert any(c.text == "REST APIs" for g in resume.skills.values() for c in g)
    assert flow.workspace.profile_path.read_bytes() == original


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"title": "Backend Engineer", "source_url": "https://example.com/job", "description": None},
        {"title": "", "description": "Go required.", "source_url": "https://example.com/job"},
    ],
)
def test_invalid_job_import_structured(raw, flow):
    with pytest.raises(CareerOpsError, match="required"):
        flow.import_job(raw)


def test_corrupt_review_rejected(flow, job):
    record = ready(flow, job)
    original_digest = record.form.review_digest
    record.form.url = "https://example.com/other"
    flow.repository.update_application(record, Status.READY_FOR_REVIEW, "Test corrupted review")
    with pytest.raises(CareerOpsError, match="digest"):
        flow.repository.approve(job.job_id, original_digest)


def test_wrong_job_resume_cannot_override(workspace, job):
    from career_ops.applications.forms import map_field
    from career_ops.models.contracts import FormField
    from career_ops.resume.profile import read_profile

    field = FormField(field_id="resume", label="Resume", control="file")
    with pytest.raises(CareerOpsError, match="job-specific"):
        map_field(
            field,
            read_profile(workspace.profile_path),
            job,
            workspace.yaml("field_mappings.yaml"),
            {"Resume": "/different.pdf"},
            "/correct.pdf",
        )


def test_historical_tracking_with_verified_evidence_is_idempotent(flow, job):
    evidence = {"manual_verification": "User verified prior application receipt MOCK-OLD-001"}
    first = flow.repository.record_external_submission(
        job.job_id, evidence, reference="MOCK-OLD-001"
    )
    second = flow.repository.record_external_submission(
        job.job_id, evidence, reference="MOCK-OLD-001"
    )
    assert first.application_id == second.application_id
    assert len(flow.repository.history(first.application_id)) == 1
    assert first.status == Status.SUBMITTED
    with pytest.raises(CareerOpsError):
        flow.repository.record_external_submission(job.job_id, {})


def test_analysis_cache_refreshes_with_description_and_vocabulary(flow, job, monkeypatch):
    from career_ops.matching.analysis import VOCABULARY

    first = flow.analyze(job.job_id)
    job.description += "\nNovelTech required."
    flow.repository.put_job(job)
    second = flow.analyze(job.job_id)
    assert first.input_hash != second.input_hash
    monkeypatch.setitem(VOCABULARY["Frameworks"], "NovelTech", ["noveltech"])
    third = flow.analyze(job.job_id)
    assert third.input_hash != second.input_hash
    assert "NovelTech" in third.ats_terminology

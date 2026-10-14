from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from career_ops.applications.service import ApplicationService
from career_ops.browser.adapter import PlaywrightDriver
from career_ops.common.io import CareerOpsError
from career_ops.models.contracts import Status


@pytest.mark.browser
@pytest.mark.pdf
def test_real_playwright_local_mock(flow, job):
    spec = importlib.util.spec_from_file_location(
        "mock_ats", Path(__file__).parents[1] / "fixtures/mock_ats.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        with module.serve() as url:
            job.application_url = url
            flow.repository.put_job(job)
            resume, document = flow.resume(job.job_id)
            profile = flow.profile()
            service = ApplicationService(flow.workspace, flow.repository, PlaywrightDriver)
            unknown = service.prepare(job, profile, resume, document, mock=True)
            assert unknown.status == Status.NEEDS_INFORMATION
            assert "Are you authorized to work in this country?" in unknown.form.unresolved
            overrides = {
                "Are you authorized to work in this country?": "Yes",
                "I certify these test answers are accurate": "true",
            }
            review = service.prepare(job, profile, resume, document, mock=True, overrides=overrides)
            assert review.status == Status.READY_FOR_REVIEW
            assert flow.repository.application(job.job_id).status == Status.READY_FOR_REVIEW
            flow.repository.approve(job.job_id, review.form.review_digest)
            result = service.submit(job, profile, resume, document, mock=True, overrides=overrides)
            assert result.status == Status.SUBMITTED
            assert result.confirmation_reference == "MOCK-APPLICATION-001"
            with pytest.raises(CareerOpsError):
                service.submit(job, profile, resume, document, mock=True, overrides=overrides)
    except PermissionError as exc:
        pytest.skip(f"Environment blocks local mock HTTP server: {exc}")

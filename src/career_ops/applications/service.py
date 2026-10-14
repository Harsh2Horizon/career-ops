from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from career_ops.applications.forms import map_field
from career_ops.browser.adapter import BrowserDriver, PlaywrightDriver
from career_ops.common.config import Workspace
from career_ops.common.io import CareerOpsError, digest, within, write_json
from career_ops.common.security import validate_url
from career_ops.matching.analysis import analyze
from career_ops.matching.scoring import match
from career_ops.models.contracts import (
    ApplicationForm,
    ApplicationRecord,
    CandidateProfile,
    FormField,
    GeneratedDocument,
    JobListing,
    Status,
    TailoredResume,
)
from career_ops.resume.documents import validate_pdf
from career_ops.resume.tailoring import validate_claims
from career_ops.storage.repository import Repository


def review_digest(form: ApplicationForm) -> str:
    return digest(form.model_dump(mode="json", exclude={"review_digest"}))


class ApplicationService:
    def __init__(
        self,
        workspace: Workspace,
        repository: Repository,
        driver_factory: Callable[[], BrowserDriver] = PlaywrightDriver,
    ):
        self.workspace, self.repository, self.driver_factory = workspace, repository, driver_factory

    def document_check(
        self, document: GeneratedDocument, resume: TailoredResume, profile: CandidateProfile
    ) -> Path:
        validate_claims(resume, profile)
        if document.job_id != resume.job_id or document.profile_hash != digest(
            profile.model_dump(mode="json")
        ):
            raise CareerOpsError(
                "document_mismatch", "Resume belongs to a different job or stale candidate profile"
            )
        path = within(Path(document.upload_path), self.workspace.data / "resumes")
        if (
            not path.is_file()
            or not document.validated
            or digest(path.read_bytes()) != document.sha256
        ):
            raise CareerOpsError(
                "document_changed", "Upload resume is missing, changed, or unvalidated"
            )
        validate_pdf(path, resume)
        return path

    def fill(
        self,
        driver: BrowserDriver,
        job: JobListing,
        profile: CandidateProfile,
        document: GeneratedDocument,
        mock: bool = False,
        overrides: dict[str, str] | None = None,
        supporting_documents: dict[str, str] | None = None,
    ) -> ApplicationForm:
        defaults = self.workspace.yaml("application_defaults.yaml")
        url = validate_url(
            job.application_url,
            allowed_hosts=defaults.get("allowed_application_hosts", []),
            mock=mock,
        )
        answers_config = defaults.get("verified_answers", {}).copy()
        for fact in self.repository.approved_facts():
            if fact["field"].startswith("answer:"):
                answers_config[fact["field"][7:]] = fact["value"]
        answers_config.update(overrides or {})
        for path in (supporting_documents or {}).values():
            uploaded = within(Path(path), self.workspace.data / "resumes")
            if not uploaded.is_file() or uploaded.suffix.lower() != ".pdf":
                raise CareerOpsError(
                    "invalid_supporting_document",
                    "Supporting documents must be verified PDFs in data/resumes",
                )
        snapshot = driver.open(
            dict(
                url=url,
                mock=mock,
                allowedHosts=defaults.get("allowed_application_hosts", []),
                resourceHosts=defaults.get("allowed_resource_hosts", []),
                timeoutMs=defaults.get("browser_timeout_ms", 15000),
            )
        )
        fields, answers, unresolved, errors = [], [], [], []
        upload_hashes = {}
        for field in ("full_name", "email"):
            if field not in profile.contact:
                unresolved.append("Missing verified contact: " + field)
        for _ in range(defaults.get("max_form_steps", 8)):
            validate_url(
                snapshot["url"],
                allowed_hosts=defaults.get("allowed_application_hosts", []),
                mock=mock,
            )
            current = [FormField.model_validate(f) for f in snapshot["fields"]]
            for field in current:
                answer = map_field(
                    field,
                    profile,
                    job,
                    self.workspace.yaml("field_mappings.yaml"),
                    answers_config,
                    document.upload_path,
                    supporting_documents,
                )
                if field.control == "file" and answer.value is not None:
                    upload = within(Path(answer.value), self.workspace.data / "resumes")
                    if (
                        not upload.is_file()
                        or upload.suffix.lower() != ".pdf"
                        or upload.stat().st_size > 20_000_000
                    ):
                        raise CareerOpsError(
                            "unsafe_upload",
                            "Uploads must be existing PDFs under data/resumes, no larger than 20 MB",
                        )
                    try:
                        if not PdfReader(upload).pages:
                            raise PdfReadError("Empty PDF")
                    except PdfReadError as exc:
                        raise CareerOpsError(
                            "invalid_upload_pdf", "Supporting document is not a readable PDF"
                        ) from exc
                    upload_hashes[field.field_id] = digest(upload.read_bytes())
                if answer.value is not None:
                    try:
                        driver.fill(field.field_id, field.control, answer.value)
                    except CareerOpsError as exc:
                        errors.append(f"{field.label}: {exc.code}")
                elif field.required or (answer.sensitive and field.checked):
                    unresolved.append(field.label)
                elif answer.sensitive:
                    # Voluntary sensitive fields remain visibly skipped in the review.
                    pass
                fields.append(field)
                answers.append(answer)
            errors.extend(snapshot.get("errors", []))
            final_buttons = {"submit", "submit application", "apply", "send application"}
            button_labels = {s.strip().lower() for s in snapshot.get("buttons", [])}
            if button_labels & final_buttons:
                break
            if unresolved or errors:
                break
            if button_labels & {"next", "continue", "review"}:
                snapshot = driver.next()
            else:
                errors.append(
                    "No supported final submit or next-step control; use computer-use/manual adapter"
                )
                break
        else:
            errors.append("Maximum form steps exceeded")
        matching = match(profile, job, analyze(job), self.workspace.preferences())
        form = ApplicationForm(
            job_id=job.job_id,
            company=job.company,
            job_title=job.title,
            job_description_hash=digest(job.description),
            url=url,
            fields=fields,
            answers=answers,
            unresolved=sorted(set(unresolved)),
            errors=errors,
            upload_hashes=upload_hashes,
            concerns=matching.blocking_requirements
            + matching.unresolved_eligibility
            + [
                "Unsupported required skill: " + skill for skill in matching.missing_required_skills
            ],
            resume_sha256=document.sha256,
            profile_hash=digest(profile.model_dump(mode="json")),
        )
        form.review_digest = review_digest(form)
        return form

    def prepare(
        self,
        job: JobListing,
        profile: CandidateProfile,
        resume: TailoredResume,
        document: GeneratedDocument,
        mock: bool = False,
        overrides: dict[str, str] | None = None,
    ) -> ApplicationRecord:
        self.document_check(document, resume, profile)
        record = self.repository.start_application(job.job_id)
        if record.status != Status.APPLICATION_STARTED:
            record = self.repository.update_application(
                record,
                Status.APPLICATION_STARTED,
                "Preparation resumed; prior approval invalidated",
            )
        record.approval_digest = None
        record.approval_expires_at = None
        driver = self.driver_factory()
        try:
            form = self.fill(driver, job, profile, document, mock, overrides)
            record.form, record.document = form, document
            target = (
                Status.NEEDS_INFORMATION
                if form.unresolved or form.errors
                else Status.READY_FOR_REVIEW
            )
            record = self.repository.update_application(
                record, target, "Form prepared; final submission not performed"
            )
        except CareerOpsError:
            self.repository.update_application(
                record, Status.FAILED, "Browser preparation failed; manual recovery may be required"
            )
            raise
        finally:
            driver.close()
        write_json(
            self.workspace.data / "applications" / record.application_id / "review.json", record
        )
        return record

    def submit(
        self,
        job: JobListing,
        profile: CandidateProfile,
        resume: TailoredResume,
        document: GeneratedDocument,
        mock: bool = False,
        overrides: dict[str, str] | None = None,
    ) -> ApplicationRecord:
        self.document_check(document, resume, profile)
        record = self.repository.application(job.job_id)
        if not record or record.status != Status.APPROVED or not record.form:
            raise CareerOpsError(
                "approval_required",
                "Review and explicitly approve this application before submitting",
            )
        driver = self.driver_factory()
        try:
            current = self.fill(driver, job, profile, document, mock, overrides)
            if (
                current.review_digest != record.approval_digest
                or current.unresolved
                or current.errors
            ):
                raise CareerOpsError(
                    "review_changed",
                    "Live form, answers, or resume changed; prepare and approve again",
                )
            record = self.repository.claim_submission(job.job_id, current.review_digest)
            outcome = (
                driver.submit()
            )  # never retried; uncertain outcome remains submission_unverified
            if outcome.get("confirmed") and outcome.get("evidence"):
                record.confirmation_reference = outcome.get("reference")
                record.confirmation_evidence = {
                    "url": outcome.get("url", ""),
                    "message": outcome["evidence"],
                }
                from career_ops.common.io import now

                record.submitted_at = now()
                record = self.repository.update_application(
                    record,
                    Status.SUBMITTED,
                    "Application confirmation evidence captured",
                    expected=Status.SUBMISSION_UNVERIFIED,
                )
            write_json(
                self.workspace.data / "applications" / record.application_id / "outcome.json",
                record,
            )
            return record
        finally:
            driver.close()

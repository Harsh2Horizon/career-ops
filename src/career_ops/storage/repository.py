from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

from career_ops.common.io import CareerOpsError, digest, now
from career_ops.models.contracts import ApplicationEvent, ApplicationRecord, JobListing, Status

ARTIFACT_TABLES = {"job_analyses", "job_matches", "resumes", "candidate_profile_references"}
TRANSITIONS: dict[Status, set[Status]] = {
    Status.DISCOVERED: {Status.ANALYZED},
    Status.ANALYZED: {Status.MATCHED},
    Status.MATCHED: {Status.SHORTLISTED, Status.RESUME_GENERATED},
    Status.SHORTLISTED: {Status.RESUME_GENERATED},
    Status.RESUME_GENERATED: {Status.APPLICATION_STARTED},
    Status.APPLICATION_STARTED: {Status.NEEDS_INFORMATION, Status.READY_FOR_REVIEW, Status.FAILED},
    Status.NEEDS_INFORMATION: {Status.APPLICATION_STARTED, Status.WITHDRAWN},
    Status.READY_FOR_REVIEW: {Status.APPROVED, Status.APPLICATION_STARTED, Status.WITHDRAWN},
    Status.APPROVED: {Status.SUBMISSION_UNVERIFIED, Status.APPLICATION_STARTED, Status.WITHDRAWN},
    Status.SUBMISSION_UNVERIFIED: {Status.SUBMITTED, Status.FAILED},
    Status.FAILED: {Status.APPLICATION_STARTED, Status.WITHDRAWN},
    Status.SUBMITTED: {Status.INTERVIEW, Status.REJECTED, Status.WITHDRAWN},
    Status.INTERVIEW: {Status.OFFER, Status.REJECTED, Status.WITHDRAWN},
    Status.OFFER: {Status.WITHDRAWN},
    Status.REJECTED: set(),
    Status.WITHDRAWN: set(),
}


def validate_transition(previous: Status, target: Status) -> None:
    if previous != target and target not in TRANSITIONS[previous]:
        raise CareerOpsError("invalid_transition", f"Cannot transition {previous} to {target}")


def encode(value: Any) -> str:
    return json.dumps(value.model_dump(mode="json") if hasattr(value, "model_dump") else value)


class Repository:
    """SQLite repository: WAL, migrations, transactional CAS, and immutable events."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        self.migrate()
        path.chmod(0o600)

    @contextmanager
    def connection(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        try:
            if write:
                c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def migrate(self) -> None:
        with self.connection() as c:
            c.execute("PRAGMA journal_mode=WAL")
        with self.connection(write=True) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            latest = c.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[
                0
            ]
            if latest > 1:
                raise CareerOpsError(
                    "newer_database", "Database requires a newer CareerOps version"
                )
            if latest < 1:
                statements = [
                    "CREATE TABLE jobs(job_id TEXT PRIMARY KEY,canonical_url TEXT UNIQUE NOT NULL,ats_key TEXT UNIQUE,status TEXT NOT NULL,score REAL,data TEXT NOT NULL)",
                    "CREATE TABLE applications(application_id TEXT PRIMARY KEY,job_id TEXT UNIQUE NOT NULL REFERENCES jobs(job_id),status TEXT NOT NULL,data TEXT NOT NULL)",
                    "CREATE TABLE application_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,application_id TEXT NOT NULL REFERENCES applications(application_id),data TEXT NOT NULL)",
                    "CREATE TABLE application_questions(application_id TEXT NOT NULL REFERENCES applications(application_id),field_id TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(application_id,field_id))",
                    "CREATE TABLE job_boards(board_id TEXT PRIMARY KEY,url TEXT UNIQUE NOT NULL,data TEXT NOT NULL)",
                    "CREATE TABLE fact_proposals(proposal_id TEXT PRIMARY KEY,data TEXT NOT NULL,approved INTEGER NOT NULL DEFAULT 0)",
                ]
                statements += [
                    f"CREATE TABLE {t}(job_id TEXT NOT NULL,input_hash TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(job_id,input_hash))"
                    for t in sorted(ARTIFACT_TABLES)
                ]
                statements += [
                    f"CREATE TRIGGER immutable_events_{op.lower()} BEFORE {op} ON application_events BEGIN SELECT RAISE(ABORT,'application events are immutable'); END"
                    for op in ("UPDATE", "DELETE")
                ]
                for statement in statements:
                    c.execute(statement)
                c.execute("INSERT INTO schema_migrations VALUES(1,?)", (now().isoformat(),))

    def put_job(self, job: JobListing) -> tuple[JobListing, bool]:
        ats_key = f"{job.source}:{job.company}:{job.ats_id}" if job.ats_id else None
        with self.connection(write=True) as c:
            row = c.execute(
                "SELECT data FROM jobs WHERE canonical_url=? OR (ats_key IS NOT NULL AND ats_key=?)",
                (job.source_url, ats_key),
            ).fetchone()
            if row:
                old = JobListing.model_validate_json(row[0])
                refreshed = job.model_copy(
                    update={
                        "job_id": old.job_id,
                        "date_discovered": old.date_discovered,
                        "status": old.status,
                    }
                )
                c.execute(
                    "UPDATE jobs SET data=?,ats_key=COALESCE(ats_key,?) WHERE job_id=?",
                    (encode(refreshed), ats_key, old.job_id),
                )
                return refreshed, False
            c.execute(
                "INSERT INTO jobs(job_id,canonical_url,ats_key,status,data) VALUES(?,?,?,?,?)",
                (job.job_id, job.source_url, ats_key, job.status.value, encode(job)),
            )
        return job, True

    def job(self, job_id: str) -> JobListing:
        with self.connection() as c:
            row = c.execute("SELECT data FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise CareerOpsError("job_not_found", f"Unknown job: {job_id}")
        return JobListing.model_validate_json(row[0])

    def list_jobs(self, filtered: bool | None = False) -> list[JobListing]:
        with self.connection() as c:
            result = [
                JobListing.model_validate_json(row[0])
                for row in c.execute("SELECT data FROM jobs ORDER BY score DESC,job_id")
            ]
        return [j for j in result if filtered is None or bool(j.filtered_reasons) == filtered]

    def set_job_status(self, job_id: str, target: Status) -> None:
        with self.connection(write=True) as c:
            row = c.execute("SELECT data FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                raise CareerOpsError("job_not_found", f"Unknown job: {job_id}")
            job = JobListing.model_validate_json(row[0])
            validate_transition(job.status, target)
            job.status = target
            c.execute(
                "UPDATE jobs SET status=?,data=? WHERE job_id=?",
                (target.value, encode(job), job_id),
            )

    def put_artifact(self, kind: str, job_id: str, input_hash: str, data: Any) -> None:
        if kind not in ARTIFACT_TABLES:
            raise ValueError("Unknown artifact table")
        with self.connection(write=True) as c:
            c.execute(
                f"INSERT OR IGNORE INTO {kind} VALUES(?,?,?,?)",
                (job_id, input_hash, encode(data), now().isoformat()),
            )
            if kind == "job_matches":
                c.execute("UPDATE jobs SET score=? WHERE job_id=?", (data.overall_score, job_id))

    def artifact(self, kind: str, job_id: str, input_hash: str | None = None) -> dict | None:
        if kind not in ARTIFACT_TABLES:
            raise ValueError("Unknown artifact table")
        query, params = f"SELECT data FROM {kind} WHERE job_id=?", [job_id]
        if input_hash:
            query += " AND input_hash=?"
            params.append(input_hash)
        with self.connection() as c:
            row = c.execute(query + " ORDER BY created_at DESC LIMIT 1", params).fetchone()
        return json.loads(row[0]) if row else None

    def application(self, identifier: str) -> ApplicationRecord | None:
        with self.connection() as c:
            row = c.execute(
                "SELECT data FROM applications WHERE job_id=? OR application_id=?",
                (identifier, identifier),
            ).fetchone()
        return ApplicationRecord.model_validate_json(row[0]) if row else None

    def _save(
        self, c: sqlite3.Connection, record: ApplicationRecord, previous: Status | None, reason: str
    ) -> None:
        record.updated_at = now()
        c.execute(
            "INSERT INTO applications VALUES(?,?,?,?) ON CONFLICT(application_id) DO UPDATE SET status=excluded.status,data=excluded.data",
            (record.application_id, record.job_id, record.status.value, encode(record)),
        )
        job = JobListing.model_validate_json(
            c.execute("SELECT data FROM jobs WHERE job_id=?", (record.job_id,)).fetchone()[0]
        )
        job.status = record.status
        c.execute(
            "UPDATE jobs SET status=?,data=? WHERE job_id=?",
            (job.status.value, encode(job), job.job_id),
        )
        entry = ApplicationEvent(
            event_id=str(uuid.uuid4()),
            application_id=record.application_id,
            previous_status=previous,
            status=record.status,
            reason=reason,
        )
        c.execute(
            "INSERT INTO application_events(event_id,application_id,data) VALUES(?,?,?)",
            (entry.event_id, entry.application_id, encode(entry)),
        )
        if record.form:
            c.execute(
                "DELETE FROM application_questions WHERE application_id=?", (record.application_id,)
            )
            c.executemany(
                "INSERT INTO application_questions VALUES(?,?,?)",
                [(record.application_id, a.field_id, encode(a)) for a in record.form.answers],
            )

    def start_application(self, job_id: str) -> ApplicationRecord:
        with self.connection(write=True) as c:
            row = c.execute("SELECT data FROM applications WHERE job_id=?", (job_id,)).fetchone()
            if row:
                record = ApplicationRecord.model_validate_json(row[0])
                if record.status in {
                    Status.SUBMITTED,
                    Status.SUBMISSION_UNVERIFIED,
                    Status.INTERVIEW,
                    Status.OFFER,
                    Status.WITHDRAWN,
                    Status.REJECTED,
                }:
                    raise CareerOpsError(
                        "duplicate_or_uncertain",
                        f"Application is {record.status}; reconcile manually before retrying",
                    )
                return record
            row = c.execute("SELECT data FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                raise CareerOpsError("job_not_found", f"Unknown job: {job_id}")
            validate_transition(
                JobListing.model_validate_json(row[0]).status, Status.APPLICATION_STARTED
            )
            record = ApplicationRecord(
                application_id=str(uuid.uuid4()), job_id=job_id, status=Status.APPLICATION_STARTED
            )
            self._save(c, record, None, "Application preparation started")
            return record

    def update_application(
        self,
        record: ApplicationRecord,
        target: Status,
        reason: str,
        expected: Status | None = None,
        expected_review_digest: str | None = None,
    ) -> ApplicationRecord:
        with self.connection(write=True) as c:
            row = c.execute(
                "SELECT data FROM applications WHERE application_id=?", (record.application_id,)
            ).fetchone()
            if not row:
                raise CareerOpsError("application_not_found", "Prepare an application first")
            current = ApplicationRecord.model_validate_json(row[0])
            if expected is not None and current.status != expected:
                raise CareerOpsError(
                    "concurrent_change", f"Application changed to {current.status}"
                )
            if expected_review_digest is not None and (
                current.form is None or current.form.review_digest != expected_review_digest
            ):
                raise CareerOpsError(
                    "concurrent_review_change",
                    "Review changed before the state transaction completed",
                )
            if target == Status.SUBMISSION_UNVERIFIED and expected_review_digest is not None:
                if (
                    current.approval_digest != expected_review_digest
                    or not current.approval_expires_at
                    or now() > current.approval_expires_at
                ):
                    raise CareerOpsError(
                        "approval_expired",
                        "Approval changed or expired before submission reservation",
                    )
            validate_transition(current.status, target)
            record.status = target
            self._save(c, record, current.status, reason)
        return record

    def approve(self, job_id: str, review_digest: str) -> ApplicationRecord:
        record = self.application(job_id)
        if not record or record.status != Status.READY_FOR_REVIEW or not record.form:
            raise CareerOpsError(
                "not_ready", "Prepare and resolve required questions before approval"
            )
        if (
            digest(record.form.model_dump(mode="json", exclude={"review_digest"}))
            != record.form.review_digest
        ):
            raise CareerOpsError(
                "review_corrupt", "Stored review does not match its digest; prepare again"
            )
        if (
            record.form.unresolved
            or record.form.errors
            or review_digest != record.form.review_digest
        ):
            raise CareerOpsError(
                "review_mismatch",
                "Approval must match this application's exact current review digest",
            )
        record.approval_digest = review_digest
        record.approval_expires_at = now() + timedelta(hours=1)
        return self.update_application(
            record,
            Status.APPROVED,
            "Explicit application-specific approval recorded",
            expected=Status.READY_FOR_REVIEW,
            expected_review_digest=review_digest,
        )

    def claim_submission(self, job_id: str, review_digest: str) -> ApplicationRecord:
        record = self.application(job_id)
        if not record or record.status != Status.APPROVED or not record.form:
            raise CareerOpsError(
                "approval_required", "Explicit approval for this application is required"
            )
        if (
            record.approval_digest != review_digest
            or not record.approval_expires_at
            or now() > record.approval_expires_at
        ):
            raise CareerOpsError(
                "approval_expired", "Approval expired or review changed; prepare and review again"
            )
        return self.update_application(
            record,
            Status.SUBMISSION_UNVERIFIED,
            "Submission attempt reserved; confirmation pending",
            expected=Status.APPROVED,
            expected_review_digest=review_digest,
        )

    def record_external_submission(
        self, job_id: str, evidence: dict[str, str], submitted_at=None, reference: str | None = None
    ) -> ApplicationRecord:
        if not evidence or not any(value.strip() for value in evidence.values()):
            raise CareerOpsError(
                "confirmation_required",
                "Historical applications require user-verified confirmation evidence",
            )
        with self.connection(write=True) as c:
            existing = c.execute(
                "SELECT data FROM applications WHERE job_id=?", (job_id,)
            ).fetchone()
            if existing:
                record = ApplicationRecord.model_validate_json(existing[0])
                if record.status in {
                    Status.SUBMITTED,
                    Status.INTERVIEW,
                    Status.REJECTED,
                    Status.OFFER,
                    Status.WITHDRAWN,
                }:
                    return record
                raise CareerOpsError(
                    "existing_application",
                    "Existing workflow must be reconciled or completed instead of overwritten",
                )
            if not c.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone():
                raise CareerOpsError(
                    "job_not_found", "Import the historical job before its application record"
                )
            record = ApplicationRecord(
                application_id=str(uuid.uuid4()),
                job_id=job_id,
                status=Status.SUBMITTED,
                submitted_at=submitted_at,
                confirmation_reference=reference,
                confirmation_evidence=evidence,
            )
            self._save(
                c,
                record,
                None,
                "User imported a previously submitted application with verified evidence; no browser submission performed",
            )
            return record

    def list_applications(self) -> list[ApplicationRecord]:
        with self.connection() as c:
            return [
                ApplicationRecord.model_validate_json(row[0])
                for row in c.execute("SELECT data FROM applications")
            ]

    def history(self, application_id: str) -> list[dict]:
        with self.connection() as c:
            return [
                json.loads(row[0])
                for row in c.execute(
                    "SELECT data FROM application_events WHERE application_id=? ORDER BY sequence",
                    (application_id,),
                )
            ]

    def register_board(self, url: str, provider: str = "assisted", **details) -> None:
        with self.connection(write=True) as c:
            c.execute(
                "INSERT OR IGNORE INTO job_boards VALUES(?,?,?)",
                (
                    str(uuid.uuid4()),
                    url,
                    encode({"provider": provider, "url": url, "enabled": False, **details}),
                ),
            )

    def list_boards(self) -> list[dict]:
        with self.connection() as c:
            return [json.loads(row[0]) for row in c.execute("SELECT data FROM job_boards")]

    def propose_fact(self, field: str, value: str, evidence: str) -> str:
        proposal_id = str(uuid.uuid4())
        with self.connection(write=True) as c:
            c.execute(
                "INSERT INTO fact_proposals VALUES(?,?,0)",
                (
                    proposal_id,
                    encode(
                        {
                            "field": field,
                            "value": value,
                            "evidence": evidence,
                            "proposed_at": now().isoformat(),
                        }
                    ),
                ),
            )
        return proposal_id

    def fact_proposal(self, proposal_id: str) -> dict:
        with self.connection() as c:
            row = c.execute(
                "SELECT data FROM fact_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        if not row:
            raise CareerOpsError("proposal_not_found", "Fact proposal does not exist")
        return json.loads(row[0])

    def approve_fact(self, proposal_id: str) -> None:
        self.fact_proposal(proposal_id)
        with self.connection(write=True) as c:
            c.execute("UPDATE fact_proposals SET approved=1 WHERE proposal_id=?", (proposal_id,))

    def approved_facts(self) -> list[dict]:
        with self.connection() as c:
            return [
                {"proposal_id": row[0], **json.loads(row[1])}
                for row in c.execute("SELECT proposal_id,data FROM fact_proposals WHERE approved=1")
            ]

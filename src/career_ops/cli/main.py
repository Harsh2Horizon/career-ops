from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console

from career_ops.applications.service import ApplicationService
from career_ops.common.config import Workspace
from career_ops.common.io import CareerOpsError, atomic_write, read_json, write_json
from career_ops.common.workflow import Workflow
from career_ops.models.contracts import Status
from career_ops.resume.documents import preview_pdf

app = typer.Typer(
    help="CareerOps: discover, rank, tailor, prepare, review, and track applications.",
    no_args_is_help=True,
)
console = Console()
jobs_app = typer.Typer(no_args_is_help=True, help="Job discovery and inspection")
resume_app = typer.Typer(no_args_is_help=True, help="Resume content, LaTeX, and previews")
apply_app = typer.Typer(
    no_args_is_help=True, help="Application preparation, approval, and submission"
)
applications_app = typer.Typer(no_args_is_help=True, help="Application history and exports")
profile_app = typer.Typer(
    no_args_is_help=True, help="Verified candidate profile and factual overlays"
)
sources_app = typer.Typer(no_args_is_help=True, help="Public feeds and assisted sources")
for group, subapp in [
    ("jobs", jobs_app),
    ("resume", resume_app),
    ("apply", apply_app),
    ("applications", applications_app),
    ("profile", profile_app),
    ("sources", sources_app),
]:
    app.add_typer(subapp, name=group)


@app.callback()
def setup(
    ctx: typer.Context,
    workspace: Annotated[
        Path, typer.Option("--workspace", help="CareerOps repository root")
    ] = Path("."),
):
    ctx.obj = Workspace(workspace)


def workflow(ctx: typer.Context) -> Workflow:
    return Workflow(ctx.obj)


def emit(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    console.print_json(json.dumps(value, default=str, ensure_ascii=False))


@app.command()
def init(ctx: typer.Context):
    """Initialize local storage; never overwrite the canonical resume or configuration."""
    flow = workflow(ctx)
    emit(
        {
            "database": str(flow.workspace.db),
            "profile": str(flow.workspace.profile_path),
            "profile_exists": flow.workspace.profile_path.is_file(),
        }
    )


@app.command()
def search(
    ctx: typer.Context,
    role: Annotated[str | None, typer.Option(help="Override target role for this search")] = None,
    technology: Annotated[
        list[str] | None, typer.Option(help="Preferred technology (repeatable)")
    ] = None,
    days: Annotated[int | None, typer.Option(min=1)] = None,
    experience_max: Annotated[float | None, typer.Option(min=0)] = None,
):
    """Search configured public feeds and produce assisted queries for other boards."""
    flow = workflow(ctx)
    preferences = flow.workspace.preferences()
    if role:
        preferences.target_roles = [role]
    if technology:
        preferences.preferred_technologies = technology
    if days:
        preferences.job_recency_days = days
    if experience_max is not None:
        preferences.experience["maximum_years"] = experience_max
    result = flow.search(preferences, required_technologies=technology)
    emit(result)
    if result["errors"]:
        raise typer.Exit(3)


@jobs_app.command("import")
def import_job(
    ctx: typer.Context,
    file: Annotated[
        Path, typer.Argument(exists=True, help="Verified normalized job JSON (or array)")
    ],
):
    """Import job descriptions obtained through authorized web/browser tools."""
    raw = read_json(file)
    flow = workflow(ctx)
    emit([flow.import_job(j).job_id for j in (raw if isinstance(raw, list) else [raw])])


@jobs_app.command("add")
def add(
    ctx: typer.Context,
    url: str,
    description_file: Annotated[Path | None, typer.Option(exists=True)] = None,
    title: str | None = None,
    company: str | None = None,
    access_permitted: bool = False,
):
    """Assist with a custom link and register its job board in SQLite."""
    flow = workflow(ctx)
    if description_file:
        if not title:
            raise CareerOpsError("title_required", "Provide the verified job title with --title")
        result = flow.import_job(
            {
                "title": title,
                "company": company,
                "description": description_file.read_text(),
                "source_url": url,
            }
        )
    else:
        result = flow.assist_url(url, access_permitted)
    emit(result)


@jobs_app.command("list")
def list_jobs(ctx: typer.Context, filtered: bool = False, all_jobs: bool = False):
    """List retained jobs; --filtered shows those set aside for manual re-verification."""
    emit(
        [
            j.model_dump(mode="json")
            for j in workflow(ctx).repository.list_jobs(None if all_jobs else filtered)
        ]
    )


@jobs_app.command("show")
def show_job(ctx: typer.Context, job_id: str):
    emit(workflow(ctx).repository.job(job_id))


@app.command()
def analyze(ctx: typer.Context, job_id: str):
    """Extract requirements, ATS terminology, seniority, and uncertainties."""
    emit(workflow(ctx).analyze(job_id))


@app.command("match")
def match_job(ctx: typer.Context, job_id: str):
    """Produce an evidence-weighted match report; eligibility remains separate."""
    emit(workflow(ctx).match(job_id))


@app.command()
def shortlist(ctx: typer.Context, min_score: float = typer.Option(70, min=0, max=100)):
    emit({"job_ids": workflow(ctx).shortlist(min_score)})


@resume_app.command("tailor")
def tailor_resume(ctx: typer.Context, job_id: str):
    """Select verified content and write the tailoring report without requiring LaTeX."""
    emit(workflow(ctx).tailor(job_id))


@resume_app.command("build")
def build(ctx: typer.Context, job_id: str, template: str | None = None):
    """Tailor, compile, extract, inspect, and render the job-specific LaTeX PDF."""
    _, document = workflow(ctx).resume(job_id, template)
    emit(document)


@resume_app.command("preview")
def preview(ctx: typer.Context, job_id: str):
    flow = workflow(ctx)
    document = flow.current_document(job_id)
    emit(
        {
            "previews": [
                str(p) for p in preview_pdf(Path(document.pdf_path), Path(document.pdf_path).parent)
            ]
        }
    )


@apply_app.command("prepare")
def prepare(ctx: typer.Context, job_id: str, mock: bool = False):
    """Fill and upload, persist review, and stop before irreversible submission."""
    flow = workflow(ctx)
    resume, document = flow.resume(job_id)
    record = ApplicationService(flow.workspace, flow.repository).prepare(
        flow.repository.job(job_id), flow.profile(), resume, document, mock
    )
    emit(
        {
            "application_id": record.application_id,
            "status": record.status,
            "review_path": str(
                flow.workspace.data / "applications" / record.application_id / "review.json"
            ),
            "unresolved": record.form.unresolved if record.form else [],
        }
    )


@apply_app.command("review")
def review(ctx: typer.Context, job_id: str, show_sensitive: bool = False):
    """Display company, role, URL, resume, answers, questions, and exact review digest."""
    flow = workflow(ctx)
    record = flow.repository.application(job_id)
    if not record or not record.form:
        raise CareerOpsError("review_missing", "Prepare the application first")
    job = flow.repository.job(job_id)
    data = record.model_dump(mode="json")
    if not show_sensitive:
        for answer in data["form"]["answers"]:
            if answer["sensitive"] and answer["value"] is not None:
                answer["value"] = "[redacted; use --show-sensitive for local review]"
    emit(
        {
            "company": job.company,
            "title": job.title,
            "url": job.application_url,
            "resume": record.document.upload_path if record.document else None,
            **data,
        }
    )


@apply_app.command("approve")
def approve(
    ctx: typer.Context,
    job_id: str,
    review_digest: Annotated[
        str, typer.Option("--review-digest", help="Digest shown by apply review")
    ],
    yes: Annotated[
        bool, typer.Option("--yes", help="Explicitly approve only this application")
    ] = False,
):
    """Record explicit, one-hour approval tied to one unchanged review."""
    flow = workflow(ctx)
    if not yes:
        confirm = typer.confirm(
            f"Approve submission of application {job_id} with review digest {review_digest}?"
        )
        if not confirm:
            raise typer.Exit(1)
    record = flow.repository.approve(job_id, review_digest)
    emit(record.model_dump(mode="json", exclude={"form"}))


@apply_app.command("submit")
def submit(ctx: typer.Context, job_id: str, mock: bool = False):
    """Require prior exact approval, replay/verify the live form, and submit once."""
    flow = workflow(ctx)
    record = flow.repository.application(job_id)
    if not record or record.status != Status.APPROVED:
        raise CareerOpsError(
            "approval_required", "Run apply review, then apply approve for this application"
        )
    resume, document = flow.resume(job_id)
    outcome = ApplicationService(flow.workspace, flow.repository).submit(
        flow.repository.job(job_id), flow.profile(), resume, document, mock
    )
    emit(outcome.model_dump(mode="json", exclude={"form"}))
    if outcome.status != Status.SUBMITTED:
        raise typer.Exit(4)


@applications_app.command("import")
def import_historical(ctx: typer.Context, file: Annotated[Path, typer.Argument(exists=True)]):
    """Track a previously submitted application with user-verified receipt evidence."""
    raw = read_json(file)
    if (
        not isinstance(raw, dict)
        or not raw.get("job_id")
        or not isinstance(raw.get("confirmation_evidence"), dict)
    ):
        raise CareerOpsError(
            "invalid_historical_application",
            "Provide job_id and confirmation_evidence in the import JSON",
        )
    flow = workflow(ctx)
    emit(
        flow.repository.record_external_submission(
            raw["job_id"],
            raw["confirmation_evidence"],
            raw.get("submitted_at"),
            raw.get("confirmation_reference"),
        )
    )


@applications_app.command("list")
def list_applications(ctx: typer.Context, status: Status | None = None):
    emit(
        [
            a.model_dump(mode="json", exclude={"form"})
            for a in workflow(ctx).repository.list_applications()
            if status is None or a.status == status
        ]
    )


@applications_app.command("show")
def show_application(ctx: typer.Context, application_id: str):
    flow = workflow(ctx)
    record = flow.repository.application(application_id)
    if not record:
        raise CareerOpsError("application_not_found", "Unknown application")
    emit(
        {
            "application": record.model_dump(mode="json", exclude={"form"}),
            "history": flow.repository.history(record.application_id),
        }
    )


@applications_app.command("update")
def update_status(ctx: typer.Context, application_id: str, status: Status, note: str):
    """Record interview/rejection/offer or reconcile an ambiguous submission with evidence."""
    flow = workflow(ctx)
    record = flow.repository.application(application_id)
    if not record:
        raise CareerOpsError("application_not_found", "Unknown application")
    if status == Status.SUBMITTED:
        raise CareerOpsError(
            "confirmation_required",
            "Use applications reconcile with verified confirmation evidence",
        )
    if record.status == Status.SUBMISSION_UNVERIFIED and status == Status.FAILED:
        raise CareerOpsError(
            "reconciliation_required",
            "Do not retry ambiguous submission; use applications reconcile --not-submitted",
        )
    record.notes.append(note)
    emit(flow.repository.update_application(record, status, "User recorded status update"))


@applications_app.command("reconcile")
def reconcile(
    ctx: typer.Context,
    application_id: str,
    evidence: str,
    not_submitted: bool = False,
    yes: bool = False,
):
    """Record user-verified receipt or verified absence of an ambiguous submission."""
    flow = workflow(ctx)
    record = flow.repository.application(application_id)
    if not record or record.status != Status.SUBMISSION_UNVERIFIED or not evidence.strip():
        raise CareerOpsError(
            "reconciliation_required",
            "Only ambiguous submissions with explicit verification evidence can be reconciled",
        )
    if not yes and not typer.confirm("Record this manually verified submission outcome?"):
        raise typer.Exit(1)
    record.confirmation_evidence = {"manual_verification": evidence}
    emit(
        flow.repository.update_application(
            record,
            Status.FAILED if not_submitted else Status.SUBMITTED,
            "User explicitly reconciled submission evidence",
            expected=Status.SUBMISSION_UNVERIFIED,
        )
    )


@applications_app.command("export")
def export_applications(ctx: typer.Context, format: str = "csv", output: Path | None = None):
    """Export tracking metadata; exclude personal answers and browser session details."""
    flow = workflow(ctx)
    rows = []
    for record in flow.repository.list_applications():
        job = flow.repository.job(record.job_id)
        rows.append(
            dict(
                application_id=record.application_id,
                job_id=job.job_id,
                company=job.company,
                role=job.title,
                location=job.location,
                source=job.source,
                url=job.source_url,
                application_url=job.application_url,
                status=record.status.value,
                discovered=job.date_discovered.isoformat(),
                date_posted=str(job.date_posted or ""),
                match_score=(flow.repository.artifact("job_matches", job.job_id) or {}).get(
                    "overall_score"
                ),
                resume=record.document.upload_path if record.document else "",
                applied=str(record.submitted_at or ""),
                confirmation=record.confirmation_reference or "",
                outstanding_questions="; ".join(record.form.unresolved) if record.form else "",
                updated=record.updated_at.isoformat(),
            )
        )
    target = output or flow.workspace.data / "applications" / f"export.{format}"
    if format == "json":
        write_json(target, rows)
    elif format == "csv":
        stream = io.StringIO()
        fields = list(rows[0]) if rows else ["application_id", "job_id", "status"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        # Prevent spreadsheet formula execution when exports contain untrusted employer text.
        writer.writerows(
            [
                {
                    k: ("'" + str(v) if str(v).startswith(("=", "+", "-", "@")) else v)
                    for k, v in row.items()
                }
                for row in rows
            ]
        )
        atomic_write(target, stream.getvalue())
    else:
        raise CareerOpsError("unsupported_export", "Use csv or json")
    emit({"path": str(target), "records": len(rows)})


@app.command()
def report(ctx: typer.Context, kind: str = "highest-matching"):
    """Report today, highest-matching, needing-application, awaiting-approval, submitted, manual, interview, rejected, or offer."""
    flow = workflow(ctx)
    if kind in {"today", "highest-matching", "needing-application"}:
        from career_ops.common.io import now

        jobs = flow.repository.list_jobs(None)
        if kind == "today":
            jobs = [j for j in jobs if j.date_discovered.date() == now().date()]
        elif kind == "needing-application":
            jobs = [j for j in jobs if j.status in {Status.SHORTLISTED, Status.RESUME_GENERATED}]
        emit(
            [
                {
                    "job_id": j.job_id,
                    "company": j.company,
                    "title": j.title,
                    "status": j.status,
                    "match": flow.repository.artifact("job_matches", j.job_id),
                }
                for j in jobs
            ]
        )
    else:
        statuses = {
            "awaiting-approval": {Status.READY_FOR_REVIEW},
            "submitted": {Status.SUBMITTED},
            "manual": {Status.NEEDS_INFORMATION, Status.FAILED, Status.SUBMISSION_UNVERIFIED},
            "interview": {Status.INTERVIEW},
            "rejected": {Status.REJECTED},
            "offer": {Status.OFFER},
        }
        if kind not in statuses:
            raise CareerOpsError(
                "unknown_report", "Unknown report kind; see careerops report --help"
            )
        emit(
            [
                a.model_dump(mode="json", exclude={"form"})
                for a in flow.repository.list_applications()
                if a.status in statuses[kind]
            ]
        )


@profile_app.command("show")
def show_profile(ctx: typer.Context):
    """Display normalized local candidate data and preserved source fields."""
    emit(workflow(ctx).profile())


@profile_app.command("propose")
def propose(ctx: typer.Context, field: str, value: str, evidence: str):
    """Propose a fact, contact.FIELD, or answer:EXACT QUESTION; does not verify it."""
    emit(
        {
            "proposal_id": workflow(ctx).repository.propose_fact(field, value, evidence),
            "approved": False,
        }
    )


@profile_app.command("approve")
def approve_fact(ctx: typer.Context, proposal_id: str, yes: bool = False):
    """Explicitly verify one factual addition; canonical YAML stays unchanged."""
    flow = workflow(ctx)
    emit(flow.repository.fact_proposal(proposal_id))
    if not yes and not typer.confirm("Verify this factual detail as accurate?"):
        raise typer.Exit(1)
    flow.repository.approve_fact(proposal_id)
    emit({"proposal_id": proposal_id, "approved": True})


@sources_app.command("list")
def sources(ctx: typer.Context):
    flow = workflow(ctx)
    emit(
        {
            "configured": flow.workspace.yaml("search_sources.yaml"),
            "registered": flow.repository.list_boards(),
        }
    )


@app.command()
def run(ctx: typer.Context, mode: str = typer.Option("search-and-rank"), mock: bool = False):
    """Run checkpointed partial workflows. Never batch-submit applications."""
    result = workflow(ctx).run(mode, mock)
    emit(result)
    if result["failures"]:
        raise typer.Exit(3)


def main():
    try:
        app()
    except CareerOpsError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": str(exc)}}), file=sys.stderr)
        raise SystemExit(2) from exc
    except ValidationError as exc:
        # Omit input_value, which may contain sensitive candidate data.
        print(
            json.dumps(
                {
                    "error": {
                        "code": "validation_failed",
                        "fields": [".".join(map(str, e["loc"])) for e in exc.errors()],
                    }
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(
            json.dumps({"error": {"code": "io_failed", "message": type(exc).__name__}}),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()

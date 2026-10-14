from __future__ import annotations

import re

from career_ops.common.io import CareerOpsError
from career_ops.models.contracts import ApplicationAnswer, CandidateProfile, FormField, JobListing


def label_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def map_field(
    field: FormField,
    profile: CandidateProfile,
    job: JobListing,
    mapping: dict,
    exact_answers: dict[str, str],
    resume_path: str,
    supporting_documents: dict[str, str] | None = None,
) -> ApplicationAnswer:
    normalized = label_key(field.label)
    sensitive = field.control == "checkbox" or any(
        term.lower() in field.label.lower() for term in mapping.get("sensitive_terms", [])
    )
    params = dict(
        field_id=field.field_id,
        label=field.label,
        sensitive=sensitive,
        value=None,
        source_fact_ids=[],
        explicitly_verified=False,
    )
    is_resume = normalized in [label_key(a) for a in mapping.get("fields", {}).get("resume", [])]
    if (
        is_resume
        and field.control == "file"
        and field.label in exact_answers
        and str(exact_answers[field.label]) != resume_path
    ):
        raise CareerOpsError(
            "resume_override_forbidden", "A resume upload must use this job-specific validated PDF"
        )
    if field.label in exact_answers:
        params.update(value=str(exact_answers[field.label]), explicitly_verified=True)
    elif not sensitive:
        name = next(
            (
                key
                for key, aliases in mapping.get("fields", {}).items()
                if normalized in [label_key(a) for a in aliases]
            ),
            None,
        )
        contact = profile.contact.get(name)
        if contact:
            params.update(value=contact.text, source_fact_ids=[contact.fact_id])
        elif name in {"first_name", "last_name"} and profile.contact.get("full_name"):
            # Names are not safely decomposable across naming conventions; explicit separate facts.
            pass
        elif name == "previous_company" and profile.experience:
            item = profile.experience[-1]
            params.update(value=item.name, source_fact_ids=[item.item_id])
        elif name == "current_company":
            active = [
                i
                for i in profile.experience
                if re.search(r"present|current", i.duration or "", re.I)
            ]
            if len(active) == 1:
                params.update(value=active[0].name, source_fact_ids=[active[0].item_id])
        elif name == "education" and profile.education:
            params.update(
                value=profile.education[0].role, source_fact_ids=[profile.education[0].item_id]
            )
        elif name == "resume" and field.control == "file":
            params.update(value=resume_path, explicitly_verified=True)
        elif (
            name == "cover_letter"
            and field.control == "file"
            and supporting_documents
            and supporting_documents.get("cover_letter")
        ):
            params.update(value=supporting_documents["cover_letter"], explicitly_verified=True)
    if (
        params["value"] is not None
        and field.control == "select"
        and params["value"] not in field.options
    ):
        # Do not guess which option is equivalent, especially for legal questions.
        params["value"] = None
    if field.control == "checkbox" and params["value"] not in (None, "true", "false"):
        params["value"] = None
    return ApplicationAnswer(**params)

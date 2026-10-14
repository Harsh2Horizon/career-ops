from __future__ import annotations

import re

from career_ops.common.io import CareerOpsError, digest
from career_ops.matching.analysis import tech_set
from career_ops.models.contracts import (
    CandidateProfile,
    JobAnalysis,
    JobListing,
    MatchResult,
    ResumeClaim,
    ResumeSectionItem,
    TailoredResume,
)
from career_ops.resume.profile import all_facts

# Deterministic edits correct known spelling/spacing without introducing claims.
CORRECTIONS = {
    "indexex": "indexes",
    "comapaction": "compaction",
    "utilisation": "utilization",
    "optimising": "optimizing",
    "optimisation": "optimization",
    "Starrocks": "StarRocks",
    "MYSQL": "MySQL",
}


def polish(text: str) -> str:
    for old, new in CORRECTIONS.items():
        text = re.sub(r"\b" + re.escape(old) + r"\b", new, text)
    return re.sub(r"\s+", " ", re.sub(r"\s+([,.;])", r"\1", text)).strip()


def tailor(
    profile: CandidateProfile, job: JobListing, analysis: JobAnalysis, matching: MatchResult
) -> tuple[TailoredResume, str]:
    relevant = set(analysis.ats_terminology)

    def relevance(text: str) -> int:
        return len(tech_set(text) & relevant)

    changes = []

    def convert(item, limit: int) -> ResumeSectionItem:
        selected = sorted(enumerate(item.bullets), key=lambda p: (-relevance(p[1].text), p[0]))[
            :limit
        ]
        claims = []
        for _, bullet in selected:
            rewritten = polish(bullet.text)
            claims.append(ResumeClaim(text=rewritten, fact_ids=[bullet.fact_id]))
            if rewritten != bullet.text:
                changes.append(
                    f"- {item.name}: `{bullet.fact_id}` grammar/spacing corrected.\n  Source: {bullet.text}\n  Output: {rewritten}"
                )
        return ResumeSectionItem(
            item_id=item.item_id,
            name=item.name,
            role=item.role,
            duration=item.duration,
            location=item.location,
            grade=item.grade,
            link=item.link,
            technologies=item.technologies,
            bullets=claims,
        )

    projects = sorted(
        enumerate(profile.projects),
        key=lambda p: (
            -relevance(
                p[1].name
                + " "
                + " ".join(b.text for b in p[1].bullets)
                + " ".join(p[1].technologies)
            ),
            p[0],
        ),
    )
    skills = {}
    seen_skills: set[str] = set()
    covered_technologies: set[str] = set()
    for category, facts in profile.skills.items():
        if any(
            term in category.casefold() for term in ("artificial", "agentic")
        ) and not analysis.technologies.get("AI and Machine Learning"):
            continue
        chosen = [f for f in facts if tech_set(f.text) & relevant]
        chosen.sort(key=lambda f: -relevance(f.text))
        unique = []
        for fact in chosen:
            identity = fact.text.casefold()
            matched_technologies = tech_set(fact.text) & relevant
            if identity not in seen_skills and matched_technologies - covered_technologies:
                unique.append(fact)
                seen_skills.add(identity)
                covered_technologies.update(matched_technologies)
        chosen = unique
        if chosen:
            skills[category.replace("_", " ").title()] = [
                ResumeClaim(text=f.text, fact_ids=[f.fact_id]) for f in chosen[:7]
            ]
    # Bound resume length without appending unrelated skill inventories.
    remaining, bounded = 24, {}
    for category, values in sorted(
        skills.items(), key=lambda p: -sum(relevance(v.text) for v in p[1])
    ):
        if remaining:
            bounded[category] = values[:remaining]
            remaining -= len(bounded[category])
    result = TailoredResume(
        job_id=job.job_id,
        company=job.company,
        input_hash=digest(
            ["tailor-v2", profile.model_dump(mode="json"), analysis.model_dump(mode="json")]
        ),
        profile_hash=digest(profile.model_dump(mode="json")),
        contact={
            k: ResumeClaim(text=f.text, fact_ids=[f.fact_id]) for k, f in profile.contact.items()
        },
        education=[convert(i, 2) for i in profile.education],
        experience=[convert(i, 4) for i in profile.experience],
        projects=[convert(i, 3) for _, i in projects[:2]],
        skills=bounded,
        unsupported_requirements=matching.missing_required_skills + matching.blocking_requirements,
        needs_confirmation=[
            f"Missing contact field: {k}"
            for k in ("full_name", "email")
            if k not in profile.contact
        ]
        + matching.unresolved_eligibility,
    )
    validate_claims(result, profile)
    report = "\n".join(
        [
            f"# Tailoring report: {job.title}",
            f"Job: {job.job_id}",
            f"Profile SHA256: {profile.source_hash}",
            "\n## Prioritized experience and projects",
            *[f"- {i.name} ({i.item_id})" for i in result.experience + result.projects],
            "\n## Selected technical knowledge",
            *[
                f"- {k}: " + ", ".join(v.text for v in values)
                for k, values in result.skills.items()
            ],
            "Skills are listed knowledge; employment/project claims retain their original evidence.",
            "\n## Rewritten bullets",
            *(changes or ["No wording changed."]),
            "\n## Unsupported requirements",
            *([f"- {s}" for s in result.unsupported_requirements] or ["None identified."]),
            "\n## Confirmation needed",
            *[f"- {s}" for s in result.needs_confirmation],
            "Suggest additional details with `careerops profile propose`; approval stores a separate overlay. The original YAML is unchanged.",
        ]
    )
    return result, report + "\n"


def validate_claims(resume: TailoredResume, profile: CandidateProfile) -> None:
    if resume.profile_hash != digest(profile.model_dump(mode="json")):
        raise CareerOpsError(
            "profile_changed", "Tailored resume does not match the current verified profile"
        )
    facts = all_facts(profile)
    claims = (
        list(resume.contact.values())
        + [s for values in resume.skills.values() for s in values]
        + [
            b
            for item in resume.experience + resume.projects + resume.education
            for b in item.bullets
        ]
    )
    for claim in claims:
        if any(i not in facts or not facts[i].provenance.verified for i in claim.fact_ids):
            raise CareerOpsError(
                "unverified_claim", "Resume claim has missing or unverified candidate provenance"
            )
        # Only exact facts or deterministic corrections are accepted by the renderer.
        if claim.text not in {facts[i].text for i in claim.fact_ids} | {
            polish(facts[i].text) for i in claim.fact_ids
        }:
            raise CareerOpsError(
                "unsupported_rewrite",
                "Free-text factual rewrites require explicit profile approval",
            )
    original = {i.item_id: i for i in profile.experience + profile.projects + profile.education}
    for item in resume.experience + resume.projects + resume.education:
        source = original.get(item.item_id)
        if (
            not source
            or any(
                getattr(source, field) != getattr(item, field)
                for field in ("name", "role", "duration", "location", "grade", "link")
            )
            or item.technologies != source.technologies
        ):
            raise CareerOpsError(
                "altered_identity",
                "Resume changed an employer, title, date, project, qualification, or stack",
            )

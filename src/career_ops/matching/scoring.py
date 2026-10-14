from __future__ import annotations

from career_ops.common.config import Preferences
from career_ops.common.io import digest
from career_ops.matching.analysis import mentions, tech_set
from career_ops.models.contracts import (
    CandidateProfile,
    JobAnalysis,
    JobListing,
    MatchResult,
    SkillEvidence,
)
from career_ops.resume.profile import professional_years

LEVEL_WEIGHT = {"professional": 1.0, "project": 0.8, "listed": 0.45, "approved": 0.45}


def evidence(profile: CandidateProfile) -> dict[str, SkillEvidence]:
    found: dict[str, SkillEvidence] = {}

    def add(text: str, level: str, fact_ids: list[str]):
        for skill in tech_set(text):
            old = found.get(skill)
            if old is None or LEVEL_WEIGHT[level] > LEVEL_WEIGHT[old.level]:
                found[skill] = SkillEvidence(skill=skill, level=level, fact_ids=fact_ids)
            elif old.level == level:
                old.fact_ids = sorted(set(old.fact_ids + fact_ids))

    for item in profile.experience + profile.projects:
        for bullet in item.bullets:
            add(bullet.text, item.kind, [bullet.fact_id])
        # A project's declared stack establishes project use, not employment use.
        for skill in item.technologies:
            add(skill, item.kind, [item.item_id])
    for values in profile.skills.values():
        for fact in values:
            add(fact.text, "listed", [fact.fact_id])
    for fact in profile.approved_facts:
        add(fact.text, "approved", [fact.fact_id])
    return found


def match(
    profile: CandidateProfile, job: JobListing, analysis: JobAnalysis, preferences: Preferences
) -> MatchResult:
    available = evidence(profile)
    required = {s for r in analysis.required_qualifications for s in r.technologies}
    preferred = {s for r in analysis.preferred_qualifications for s in r.technologies}
    wanted = required or set(analysis.ats_terminology)
    skill_score = (
        100 * sum(LEVEL_WEIGHT[available[s].level] for s in wanted if s in available) / len(wanted)
        if wanted
        else 50
    )
    years = professional_years(profile)
    minimum = analysis.minimum_years
    experience_score = (
        50
        if years is None or minimum is None
        else min(100, 100 * years / minimum)
        if minimum > 0
        else 100
    )
    blockers = []
    if years is not None and minimum is not None and years < minimum:
        blockers.append(
            f"Required {minimum:g} years; dated professional experience supports approximately {years:g}"
        )
    if analysis.seniority in {"senior", "staff", "principal"}:
        blockers.append(f"Seniority mismatch: {analysis.seniority}")
    professional_text = " ".join(b.text for item in profile.experience for b in item.bullets)
    for r in analysis.required_qualifications:
        if "production" in r.text.lower() or "professional experience" in r.text.lower():
            unsupported = [
                s
                for s in r.technologies
                if s not in available or available[s].level != "professional"
            ]
            if unsupported:
                blockers.append(
                    "Required professional/production evidence missing: " + ", ".join(unsupported)
                )
    title_words = set(job.title.lower().replace("-", " ").split()) - {
        "engineer",
        "engineering",
        "software",
        "development",
        "and",
        "the",
    }
    source = " ".join(
        [professional_text]
        + [i.name + " " + " ".join(b.text for b in i.bullets) for i in profile.projects]
    ).lower()
    domain_words = [w for w in title_words if len(w) > 2]
    domain_score = (
        100 * sum(mentions(source, w) for w in domain_words) / len(domain_words)
        if domain_words
        else 75
    )
    location_score = 100 if not preferences.locations and not preferences.work_modes else 50
    if preferences.locations and job.location:
        if any(p.lower() in job.location.lower() for p in preferences.locations):
            location_score = 100
        else:
            location_score = 0
            blockers.append("Location does not match configured preference")
    if preferences.work_modes and job.work_mode:
        if job.work_mode.lower() not in [p.lower() for p in preferences.work_modes]:
            location_score = 0
            blockers.append("Work mode does not match configured preference")
    preference_score = 100
    if preferences.preferred_companies:
        preference_score = 100 if job.company in preferences.preferred_companies else 50
    if job.company in preferences.excluded_companies:
        blockers.append("Company excluded by preferences")
        preference_score = 0
    unresolved = [r.text for r in analysis.eligibility_requirements]
    if preferences.visa_sponsorship_required is not None:
        unresolved.append(
            "Verify visa sponsorship against candidate eligibility and employer policy"
        )
    if analysis.education_requirements:
        unresolved += [
            "Education requirement needs explicit review: " + r
            for r in analysis.education_requirements
        ]
    dims = dict(
        technical=skill_score,
        experience=experience_score,
        domain=domain_score,
        location=location_score,
        other=preference_score,
    )
    score = round(
        sum(dims[k] * w for k, w in preferences.weights.items())
        / sum(preferences.weights.values()),
        2,
    )
    recommendation = (
        "Poor Match"
        if blockers
        else "Strong Match"
        if score >= 85
        else "Good Match"
        if score >= 65
        else "Stretch Opportunity"
        if score >= 45
        else "Poor Match"
    )
    missing = sorted(required - available.keys())
    transferable = []
    for target, alternatives in {
        "Kafka": {"Apache Flink", "Change Data Capture"},
        "AWS": {"Azure"},
        "PostgreSQL": {"MySQL"},
    }.items():
        if target in missing and alternatives & available.keys():
            transferable.append(
                f"{target}: adjacent experience with {', '.join(sorted(alternatives & available.keys()))}; direct skill remains missing"
            )
    return MatchResult(
        job_id=job.job_id,
        input_hash=digest(
            [
                "matcher-v1",
                profile.model_dump(mode="json"),
                analysis.model_dump(mode="json"),
                preferences.model_dump(),
                job.location,
                job.work_mode,
                job.company,
            ]
        ),
        overall_score=score,
        skill_score=round(skill_score, 2),
        experience_score=round(experience_score, 2),
        domain_score=round(domain_score, 2),
        location_score=location_score,
        preference_score=preference_score,
        matched_skills=[available[s] for s in sorted(wanted & available.keys())],
        transferable_skills=transferable,
        missing_required_skills=missing,
        missing_preferred_skills=sorted(preferred - available.keys()),
        blocking_requirements=blockers,
        unresolved_eligibility=unresolved,
        recommendation=recommendation,
        reasoning_summary=f"Heuristic score {score}/100; evidence weights: professional 1, project 0.8, listed/approved knowledge 0.45. Missing required skills: {', '.join(missing) or 'none'}. Eligibility is reviewed separately. This score is not an interview probability.",
    )

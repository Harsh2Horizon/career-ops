from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from career_ops.common.io import CareerOpsError, digest
from career_ops.models.contracts import CandidateProfile, Fact, ProfileItem, Provenance


def key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def pick(mapping: dict, *names: str) -> Any:
    wanted = {key(n) for n in names}
    return next((v for k, v in mapping.items() if key(k) in wanted and v is not None), None)


def lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [
            s
            for _, v in sorted(
                value.items(),
                key=lambda kv: (
                    int(re.search(r"\d+", str(kv[0])).group())
                    if re.search(r"\d+", str(kv[0]))
                    else 999,
                    str(kv[0]),
                ),
            )
            for s in lines(v)
        ]
    if isinstance(value, list):
        return [s for item in value for s in lines(item)]
    return [str(value).strip()] if str(value).strip() else []


def text(value: Any) -> str | None:
    return " ".join(lines(value)) or None


def read_profile(path: Path) -> CandidateProfile:
    if not path.is_file():
        raise CareerOpsError("missing_profile", f"Candidate profile missing: {path}")
    raw = path.read_bytes()
    source = yaml.safe_load(raw)
    if not isinstance(source, dict):
        raise CareerOpsError("invalid_profile", "resume.yaml must contain a mapping")
    body = pick(source, "resume") or source
    if not isinstance(body, dict):
        raise CareerOpsError("invalid_profile", "resume must contain a mapping")
    source_hash = digest(raw)

    def fact(value: str, pointer: str, kind: str) -> Fact:
        return Fact(
            fact_id=digest([source_hash, pointer, value])[:24],
            text=value,
            kind=kind,
            provenance=Provenance(source=str(path.resolve()), pointer=pointer, evidence=value),
        )

    def items(section: Any, kind: str) -> list[ProfileItem]:
        result = []
        if isinstance(section, dict):
            section = list(section.values())
        for i, item in enumerate(section or []):
            if not isinstance(item, dict):
                continue
            name = text(pick(item, "school", "company", "name", "project name"))
            if not name:
                continue
            pointer = f"/{kind}/{i}"
            descriptions = lines(pick(item, "description", "work description", "bullets"))
            result.append(
                ProfileItem(
                    item_id=digest([source_hash, pointer])[:24],
                    kind=kind,
                    name=name,
                    role=text(pick(item, "role", "degree", "title")),
                    duration=text(pick(item, "duration", "dates")),
                    grade=text(pick(item, "grade", "cpi", "gpa")),
                    location=text(pick(item, "location")),
                    link=text(pick(item, "link", "url")),
                    technologies=lines(pick(item, "Technology used", "technologies")),
                    bullets=[
                        fact(s, f"{pointer}/description/{j}", kind)
                        for j, s in enumerate(descriptions)
                    ],
                    source_fields=item,
                )
            )
        return result

    skills = pick(body, "technical_skills", "skills") or {}
    if isinstance(skills, list):
        skills = {"Skills": skills}
    contact_raw = pick(body, "contact", "personal information", "contact information") or {}
    contact = {}
    for name, aliases in {
        "full_name": ("full name", "name"),
        "email": ("email",),
        "phone": ("phone", "mobile"),
        "location": ("location",),
        "github": ("github",),
        "linkedin": ("linkedin",),
        "portfolio": ("portfolio", "website"),
    }.items():
        value = text(pick(contact_raw, name, *aliases)) or text(pick(body, name, *aliases))
        if value:
            contact[name] = fact(value, f"/contact/{name}", "contact")
    return CandidateProfile(
        profile_id=source_hash[:24],
        source_path=str(path.resolve()),
        source_hash=source_hash,
        contact=contact,
        education=items(pick(body, "education"), "education"),
        experience=items(pick(body, "work experience", "experience"), "professional"),
        projects=items(pick(body, "projects"), "project"),
        skills={
            category: [
                fact(s, f"/technical_skills/{category}/{i}", "listed")
                for i, s in enumerate(lines(values))
            ]
            for category, values in skills.items()
        },
        source_fields=source,
    )


def all_facts(profile: CandidateProfile) -> dict[str, Fact]:
    facts = list(profile.contact.values()) + profile.approved_facts
    facts += [
        b
        for item in profile.experience + profile.projects + profile.education
        for b in item.bullets
    ]
    facts += [s for values in profile.skills.values() for s in values]
    return {f.fact_id: f for f in facts}


def professional_years(profile: CandidateProfile, today: date | None = None) -> float | None:
    """Union month intervals so overlapping jobs never double-count experience."""
    today = today or date.today()
    months: set[int] = set()
    for item in profile.experience:
        duration = item.duration or ""
        tokens = re.findall(r"([A-Za-z]+)\s+(20\d{2})", duration)
        starts = []
        for month, year in tokens:
            try:
                from datetime import datetime

                number = datetime.strptime(month[:3], "%b").month
                starts.append(int(year) * 12 + number - 1)
            except ValueError:
                continue
        if len(starts) == 1 and re.search(r"present|current", duration, re.I):
            starts.append(today.year * 12 + today.month - 1)
        if len(starts) >= 2 and starts[1] >= starts[0]:
            end = min(starts[1], today.year * 12 + today.month - 1)
            months.update(range(starts[0], end + 1))
    return round(len(months) / 12, 2) if months else None

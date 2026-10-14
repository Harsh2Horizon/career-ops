from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from career_ops.common.io import CareerOpsError


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_roles: list[str] = Field(default_factory=list)
    experience: dict[str, float] = Field(default_factory=dict)
    preferred_domains: list[str] = Field(default_factory=list)
    preferred_technologies: list[str] = Field(default_factory=list)
    excluded_technologies: list[str] = Field(default_factory=list)
    excluded_roles: list[str] = Field(default_factory=list)
    seniority_levels: list[str] = Field(default_factory=list)
    excluded_seniorities: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    work_modes: list[str] = Field(default_factory=list)
    preferred_countries: list[str] = Field(default_factory=list)
    preferred_companies: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    company_sizes: list[str] = Field(default_factory=list)
    salary: dict[str, Any] | None = None
    visa_sponsorship_required: bool | None = None
    job_recency_days: int = Field(default=14, ge=1)
    minimum_match_score: float = Field(default=65, ge=0, le=100)
    weights: dict[str, float] = Field(
        default_factory=lambda: dict(technical=35, experience=25, domain=20, location=10, other=10)
    )
    resume: dict[str, Any] = Field(
        default_factory=lambda: dict(
            default_template="professional", preferred_pages=1, max_pages=2
        )
    )
    applications: dict[str, Any] = Field(default_factory=dict)
    concurrency: int = Field(default=4, ge=1, le=16)

    @model_validator(mode="after")
    def safe(self) -> Preferences:
        if (
            set(self.weights) != {"technical", "experience", "domain", "location", "other"}
            or any(v < 0 for v in self.weights.values())
            or sum(self.weights.values()) <= 0
        ):
            raise ValueError("Provide five nonnegative matching weights with a positive total")
        if self.applications.get("require_submission_approval", True) is not True:
            raise ValueError("Submission approval cannot be disabled")
        if self.resume.get("preferred_pages", 1) not in (1, 2) or self.resume.get(
            "max_pages", 2
        ) not in (1, 2):
            raise ValueError("Resume page limits must be one or two")
        return self


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.data = self.root / "data"
        self.db = self.data / "career_ops.sqlite"
        configured = os.environ.get("CAREEROPS_PROFILE")
        self.profile_path = (
            Path(configured).expanduser().resolve() if configured else self.root / "resume.yaml"
        )

    def yaml(self, name: str) -> dict[str, Any]:
        path = self.root / "config" / name
        if not path.is_file():
            raise CareerOpsError(
                "missing_config", f"Missing {path}; run careerops init from the repository"
            )
        result = yaml.safe_load(path.read_text()) or {}
        if not isinstance(result, dict):
            raise CareerOpsError("invalid_config", f"{path} must contain a YAML mapping")
        return result

    def preferences(self) -> Preferences:
        return Preferences.model_validate(
            self.yaml("preferences.yaml").get("candidate_preferences", {})
        )

    def initialize(self) -> None:
        for folder in ("jobs", "applications", "resumes", "logs", "profiles"):
            (self.data / folder).mkdir(parents=True, exist_ok=True, mode=0o700)

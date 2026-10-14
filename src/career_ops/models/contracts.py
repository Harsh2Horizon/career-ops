from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from career_ops.common.io import now


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    schema_version: Literal[1] = 1


class Provenance(Artifact):
    source: str
    pointer: str
    evidence: str
    verified: bool = True


class Fact(Artifact):
    fact_id: str
    text: str
    kind: Literal["professional", "project", "education", "listed", "approved", "contact"]
    provenance: Provenance


class ProfileItem(Artifact):
    item_id: str
    kind: Literal["professional", "project", "education"]
    name: str
    role: str | None = None
    duration: str | None = None
    location: str | None = None
    grade: str | None = None
    link: str | None = None
    technologies: list[str] = Field(default_factory=list)
    bullets: list[Fact] = Field(default_factory=list)
    source_fields: dict[str, Any] = Field(default_factory=dict)


class CandidateProfile(Artifact):
    profile_id: str
    source_path: str
    source_hash: str
    contact: dict[str, Fact] = Field(default_factory=dict)
    education: list[ProfileItem] = Field(default_factory=list)
    experience: list[ProfileItem] = Field(default_factory=list)
    projects: list[ProfileItem] = Field(default_factory=list)
    skills: dict[str, list[Fact]] = Field(default_factory=dict)
    approved_facts: list[Fact] = Field(default_factory=list)
    source_fields: dict[str, Any] = Field(default_factory=dict)


class Status(StrEnum):
    DISCOVERED = "discovered"
    ANALYZED = "analyzed"
    MATCHED = "matched"
    SHORTLISTED = "shortlisted"
    RESUME_GENERATED = "resume_generated"
    APPLICATION_STARTED = "application_started"
    NEEDS_INFORMATION = "needs_information"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    SUBMISSION_UNVERIFIED = "submission_unverified"
    FAILED = "failed"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected"
    INTERVIEW = "interview"
    OFFER = "offer"


class JobListing(Artifact):
    job_id: str
    title: str
    company: str | None = None
    location: str | None = None
    work_mode: str | None = None
    country: str | None = None
    industry: str | None = None
    company_size: str | None = None
    employment_type: str | None = None
    seniority: str | None = None
    experience_required: str | None = None
    salary: dict[str, Any] | None = None
    description: str
    requirements: list[str] = Field(default_factory=list)
    preferred_qualifications: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    source: str
    source_url: str
    application_url: str
    ats_id: str | None = None
    date_posted: datetime | None = None
    date_discovered: datetime = Field(default_factory=now)
    last_verified: datetime = Field(default_factory=now)
    status: Status = Status.DISCOVERED
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    filtered_reasons: list[str] = Field(default_factory=list)
    uncertain_fields: list[str] = Field(default_factory=list)

    @field_validator("title", "description")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A verified title and full description are required")
        return value.strip()


class Requirement(Artifact):
    text: str
    category: str
    technologies: list[str] = Field(default_factory=list)
    evidence: str
    hard: bool = False


class JobAnalysis(Artifact):
    job_id: str
    input_hash: str
    required_qualifications: list[Requirement] = Field(default_factory=list)
    preferred_qualifications: list[Requirement] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    technologies: dict[str, list[str]] = Field(default_factory=dict)
    ats_terminology: list[str] = Field(default_factory=list)
    minimum_years: float | None = None
    maximum_years: float | None = None
    experience_evidence: str | None = None
    seniority: str | None = None
    education_requirements: list[str] = Field(default_factory=list)
    eligibility_requirements: list[Requirement] = Field(default_factory=list)
    emphasis_areas: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class SkillEvidence(Artifact):
    skill: str
    level: Literal["professional", "project", "listed", "approved", "unverified"]
    fact_ids: list[str] = Field(default_factory=list)


class MatchResult(Artifact):
    job_id: str
    input_hash: str
    overall_score: float = Field(ge=0, le=100)
    skill_score: float = Field(ge=0, le=100)
    experience_score: float = Field(ge=0, le=100)
    domain_score: float = Field(ge=0, le=100)
    location_score: float = Field(ge=0, le=100)
    preference_score: float = Field(ge=0, le=100)
    matched_skills: list[SkillEvidence] = Field(default_factory=list)
    transferable_skills: list[str] = Field(default_factory=list)
    missing_required_skills: list[str] = Field(default_factory=list)
    missing_preferred_skills: list[str] = Field(default_factory=list)
    blocking_requirements: list[str] = Field(default_factory=list)
    unresolved_eligibility: list[str] = Field(default_factory=list)
    recommendation: Literal["Strong Match", "Good Match", "Stretch Opportunity", "Poor Match"]
    reasoning_summary: str


class ResumeClaim(Artifact):
    text: str
    fact_ids: list[str] = Field(min_length=1)


class ResumeSectionItem(Artifact):
    item_id: str
    name: str
    role: str | None = None
    duration: str | None = None
    location: str | None = None
    grade: str | None = None
    link: str | None = None
    technologies: list[str] = Field(default_factory=list)
    bullets: list[ResumeClaim] = Field(default_factory=list)


class TailoredResume(Artifact):
    job_id: str
    company: str | None
    input_hash: str
    profile_hash: str
    contact: dict[str, ResumeClaim] = Field(default_factory=dict)
    education: list[ResumeSectionItem] = Field(default_factory=list)
    experience: list[ResumeSectionItem] = Field(default_factory=list)
    projects: list[ResumeSectionItem] = Field(default_factory=list)
    skills: dict[str, list[ResumeClaim]] = Field(default_factory=dict)
    unsupported_requirements: list[str] = Field(default_factory=list)
    needs_confirmation: list[str] = Field(default_factory=list)


class GeneratedDocument(Artifact):
    job_id: str
    input_hash: str
    profile_hash: str
    pdf_path: str
    tex_path: str
    upload_path: str
    sha256: str
    template: str
    pages: int = Field(ge=1, le=2)
    validated: bool
    validation: dict[str, Any]


class FormField(Artifact):
    field_id: str
    label: str
    control: str
    required: bool = False
    options: list[str] = Field(default_factory=list)
    step: int = 0
    checked: bool | None = None


class ApplicationAnswer(Artifact):
    field_id: str
    label: str
    value: str | None = None
    source_fact_ids: list[str] = Field(default_factory=list)
    sensitive: bool = False
    explicitly_verified: bool = False

    @model_validator(mode="after")
    def evidence_required(self) -> ApplicationAnswer:
        if self.value is not None and not (self.source_fact_ids or self.explicitly_verified):
            raise ValueError("Answers need candidate evidence or exact explicit verification")
        if self.sensitive and self.value is not None and not self.explicitly_verified:
            raise ValueError("Sensitive answers need exact explicit verification")
        return self


class ApplicationForm(Artifact):
    job_id: str
    company: str | None = None
    job_title: str | None = None
    job_description_hash: str | None = None
    url: str
    fields: list[FormField]
    answers: list[ApplicationAnswer]
    unresolved: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    upload_hashes: dict[str, str] = Field(default_factory=dict)
    resume_sha256: str
    profile_hash: str
    review_digest: str = ""


class ApplicationRecord(Artifact):
    application_id: str
    job_id: str
    status: Status
    form: ApplicationForm | None = None
    document: GeneratedDocument | None = None
    approval_digest: str | None = None
    approval_expires_at: datetime | None = None
    submitted_at: datetime | None = None
    confirmation_reference: str | None = None
    confirmation_evidence: dict[str, str] | None = None
    notes: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=now)


class ApplicationEvent(Artifact):
    event_id: str
    application_id: str
    previous_status: Status | None
    status: Status
    timestamp: datetime = Field(default_factory=now)
    reason: str

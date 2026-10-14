# Artifact contracts

Load this reference for skill boundaries and persisted state. All major models are in `src/career_ops/models/contracts.py`; JSON Schemas are in `schemas/v1/`. Regenerate schemas with `python scripts/export_schemas.py` after model changes. All artifacts declare `schema_version: 1`; unsupported versions and unexpected keys fail validation.

| Artifact | Producer → consumer | Persisted location |
|---|---|---|
| CandidateProfile | profile reader → matcher/tailor/form mapper | source YAML, approved SQLite overlays, profile references |
| JobListing | discovery/import → analysis/tracker | SQLite Jobs, data/jobs/JOB_ID/job.json |
| JobAnalysis | analyzer → matcher/tailor | SQLite JobAnalyses, job_analysis.json |
| MatchResult | matcher → shortlist/tailor | SQLite JobMatches, match_result.json |
| TailoredResume | tailor → builder | job resume folder, content/revision JSON |
| GeneratedDocument | builder → application | SQLite Resumes, document.json, matching PDF/TeX |
| ApplicationForm / ApplicationAnswer | browser/mapping → review/approval | private review.json and SQLite questions |
| ApplicationRecord | application service → tracker | SQLite Applications, review/outcome files |
| ApplicationEvent | repository → tracker | immutable SQLite event sequence |

Job fields without verified data remain null. Each extracted field has source URL, pointer and evidence. Job description evidence belongs to the employer, not the candidate.

Each candidate bullet and listed skill has a stable fact ID, evidence text, source path and normalized pointer. ProfileItem preserves its original source_fields, so item identities, dates, employers, roles, technologies and educational details remain traceable. CandidateProfile also preserves the entire original source object. Empty project entries are skipped. Listed knowledge has a weaker matching weight than project or professional evidence; approved generic knowledge never becomes production experience automatically.

The deterministic renderer accepts exact source claims or the small maintained correction vocabulary. Adding arbitrary claims requires the separate explicit factual approval mechanism. Proposed facts are not available until verified with profile approve. Exact sensitive question answers use `answer:EXACT LABEL`. Contact additions use `contact.FIELD`. The original YAML is not rewritten.

Application form answers require source fact IDs or explicit verification. Sensitive answers require explicit verification. Review digests bind the entire form except the digest itself. Generated documents bind profile and job IDs plus SHA256 of actual PDF bytes. PDFs are checked again before upload.

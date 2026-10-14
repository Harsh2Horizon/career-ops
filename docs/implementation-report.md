# CareerOps implementation report

Implemented in `/Users/harshkumar/jobsearch/career-ops` on 2026-10-13. The repository contains working skills, Python modules, schemas, CLI commands, LaTeX templates, browser code, persistence, fixtures and automated tests. This is a usable local implementation with explicitly documented browser/network limits; live ATS compatibility is not certified.

## Features implemented

- Eight repository-scoped skills with valid YAML frontmatter, executable shared launchers, references, and generated `agents/openai.yaml` UI metadata.
- Strict version-1 Pydantic contracts and exported JSON Schemas for candidate/job/analysis/match/resume/document/application artifacts.
- Robust parsing of the existing mixed-case/spaced-key YAML, ordered line1/line2 description maps, empty projects and extensive skill inventories. Original/unrecognized fields are retained.
- A user-controlled canonical profile, separate proposed/approved fact overlays, and source-linked resume claims. Employers, job titles, dates, grades and metrics stay faithful to the actual YAML.
- Documented public Greenhouse, Lever and Ashby discovery implementations; permitted Beautiful Soup/JSON-LD company-page extraction; assisted queries/import for LinkedIn, Indeed, Wellfound, Glassdoor, Google Jobs, Workday, YC and other/custom links. Custom links register their source board in SQLite. Restricted source scraping is not implemented.
- Canonical URL/ATS identity deduplication, configurable filters and discovery relevance ranking, retained excluded jobs for manual review, separate uncertainty/provenance fields, bounded GET retries/timeouts and independent source errors.
- Employer requirement classification, ATS terminology, seniority/experience extraction and explicit uncertainties. Explainable five-dimension matching distinguishes professional evidence, projects, listed knowledge and approved generic knowledge. Eligibility concerns are separate from score.
- Factual resume selection, skill/project prioritization, restrained spelling/spacing corrections, provenance checks, unsupported-requirement reports, and immutable version directories with stable upload aliases.
- Professional, compact and modern single-column A4 LaTeX templates. Engine detection prefers latexmk with installed engines and falls back to Tectonic. Special characters/URLs are escaped and shell execution is disabled. Fonts remain readable; layout permits one or two pages.
- Actual PDF compilation, text/essential-content/link checks, page counts, overfull-box checks, Poppler word-boundary inspection and PNG previews. Deterministic PDF metadata timestamps and content-aware caching are implemented.
- A replaceable BrowserDriver and isolated Node Playwright adapter using installed capabilities. Semantic field mapping, native text/select/file controls, verified upload bytes, exact user-approved sensitive answers, review snapshots, and submission evidence handling are implemented.
- Review digests bind job/company/title/description, URL, fields/options, answers, current profile, resume bytes and all uploaded document hashes. Approval expires after one hour and is checked transactionally. Reserve-before-click prevents duplicate or blind-retry submissions; ambiguous outcomes remain submission_unverified.
- SQLite WAL storage, ordered migrations, validated transitions, immutable application-event triggers, questions, profile references, historical-application import, metadata-only CSV/JSON exports, safe operational logs and reports.
- Individual commands plus checkpointed search/rank, bounded batch resume generation and sequential preparation workflows. No mass submission mode.

## Skills created

`job-search`, `job-description-analyzer`, `job-matcher`, `resume-tailor`, `latex-resume-builder`, `job-application`, `application-tracker`, `career-orchestrator`.

All eight passed the installed skill-creator `quick_validate.py`. UI descriptions/default prompts and referenced resources were additionally checked with `scripts/validate_skills.py`. Launch Codex inside this repository for discovery; each launcher invokes the same tested CLI and shared package.

## Source files

The complete list is in [file-inventory.txt](file-inventory.txt). Core groups:

- `src/career_ops/models/`, `common/`, `storage/`: contracts, configuration, safe I/O/URLs/logging, coordination and SQLite state.
- `src/career_ops/search/`, `matching/`: public integrations, normalization, structured extraction, analysis and scoring.
- `src/career_ops/resume/`, `templates/`: profile parsing, selection/provenance, LaTeX/PDF generation and three templates sharing one base.
- `src/career_ops/browser/`, `applications/`: Playwright protocol/driver, semantic mapping, upload validation, review/approval and submission.
- `src/career_ops/cli/`, `__main__.py`: executable command interface.
- `.agents/skills/`: eight manifests, UI metadata and linked shared scripts/references/assets.
- `schemas/v1/`: 18 exported artifact schemas.
- `tests/unit/`, `integration/`, `browser/`, `fixtures/`: deterministic tests, synthetic profile/job, mock driver and actual local mock HTML/server.
- `scripts/`: offline dependency reuse, skill launch/creation/validation and schema export.
- `config/`, `.env.example`, `.gitignore`, `pyproject.toml`, `AGENTS.md`, `README.md`, `docs/`: configuration, packaging, privacy and operating guidance.

## CLI inventory

`careerops init`; `search --role/--technology/--days/--experience-max`; `jobs import/add/list/show`; `analyze`; `match`; `shortlist`; `resume tailor/build/preview`; `apply prepare/review/approve/submit`; `applications import/list/show/update/reconcile/export`; `profile show/propose/approve`; `sources list`; `report`; `run --mode search-and-rank|generate-resumes|prepare-shortlisted`.

Every application needs its own exact approval. `apply submit` without approval was executed and correctly returned exit code 2 with structured error code approval_required. Other structured failures use exit 2, partial workflow failures use 3, and unverified submission uses 4. Typer provides help and usage errors.

## Verification actually executed

```sh
.venv/bin/python -m pytest -q -rs --junitxml=data/logs/test-results.xml
.venv/bin/python -m ruff check src scripts tests
.venv/bin/python -m ruff format --check src scripts tests
.venv/bin/python -m compileall -q src scripts
.venv/bin/python scripts/validate_skills.py
node --check src/career_ops/browser/playwright_driver.mjs
.venv/bin/careerops init
.venv/bin/careerops jobs import tests/fixtures/sample_job.json
.venv/bin/careerops analyze ee477307a0b449e9be92
.venv/bin/careerops match ee477307a0b449e9be92
.venv/bin/careerops resume build ee477307a0b449e9be92
.venv/bin/careerops resume preview ee477307a0b449e9be92
.venv/bin/careerops applications export --format json
.venv/bin/careerops run --mode search-and-rank
.venv/bin/careerops run --mode generate-resumes
```

Result: **62 tests passed; one actual-browser test skipped**. Lint and formatting passed. All eight skills passed official structural validation. CLI and skill launchers were exercised. PDF tests actually compiled all three templates and validated extraction, required content, links, bounds, previews and cached reuse. Tests also cover factual provenance, eligibility, filtered retention, migrations, immutable history, interrupted/reprepared workflows, approval expiry, concurrent reservation, changed answers/files, wrong resume overrides and duplicate prevention.

The deterministic BrowserDriver integration test completed the full profile → analysis → match → tailored content → LaTeX PDF → field mapping/uploaded PDF bytes → stopped review → explicit test approval → one mock submission → confirmation → persistent SQLite sequence. The ambiguous-click test confirmed that an uncertain attempt cannot be retried. These use a test double and are not claimed as executed real Playwright website tests.

The actual Playwright/local HTTP mock test attempted to host the fixture but was skipped because the sandbox denied binding 127.0.0.1 with EPERM. An independent browser launch smoke test also attempted the installed Chromium executable and failed with `browserType.launch: Target page, context or browser has been closed`. Native Chrome was visible through computer-use, but no mock form was submitted through it. No real applications were submitted.

## Example PDF

Stable path: `data/resumes/CareerOps-Mock-Systems/ee477307a0b449e9be92/resume.pdf`. The chosen immutable version and actual upload path are in its document.json and `data/logs/example-document.json`.

Compiled with Tectonic; A4; one page; extractable/selectable text; expected content and clickable project links preserved; Poppler boundary checks passed. The latest PNG preview was visually inspected for wrapping, alignment, overlap and clipping. The actual canonical file's source hash was compared with the first tailoring report and remains unchanged.

No name/email were invented. Because the actual source lacks contact data, the example omits it and uses Candidate_Resume.pdf. It needs verified contact details before real application use.

## Environmental requirements and known limits

- Registry DNS and escalated dependency installation were blocked by the current sandbox/approval policy. The working Python 3.13 environment reused 29 already installed distributions. Normal setup uses uv sync; dependency locking requires registry access and no portable uv.lock is claimed.
- Local HTTP bind and isolated Chromium launch are blocked here. Run the browser test in an environment allowing loopback hosting and Chromium before relying on CLI browser automation.
- Feed normalization was exercised with HTTP fixtures, not live network calls. Configure verified company board slugs/company names and run live checks in a permitted network environment.
- Aggregators/YC/Workday require authorized assisted discovery/import; there is no claimed private scraping API. Generic real multi-step navigation, authenticated replay, radios, custom selects, iframes, unusual file controls and website save-progress actions require a verified adapter or computer-use/manual handling.
- The analyzer is conservative and dictionary/headings based; novel wording/vocabulary remains uncertain. Salary currency/period and visa/authorization requirements need manual verification; optional country/industry/company-size filters apply only to verified metadata.
- PDF validation and previews do not certify every commercial ATS. Inspect rendered output before real upload; configure an installed Unicode font and cached TeX packages when offline.
- SQLite is protected locally but not encrypted at rest. Keep candidate data, reviews, browser secrets and PDFs out of version control and protect local storage/backups.

For real websites, configure exact approved application/resource hosts, complete verified contact and exact sensitive question answers, use the appropriate adapter/manual route, inspect the resume/review, and provide separate explicit submission approval for each application.

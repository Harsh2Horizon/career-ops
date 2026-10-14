# Workflows and skill discovery

Start Codex from `career-ops/`. Skills are in `.agents/skills/NAME/SKILL.md` with UI metadata at `agents/openai.yaml`. The official skill convention uses metadata for discovery and loads detailed instructions/resources only when selected. See [official Codex skill guidance](https://learn.chatgpt.com/docs/build-skills). Automatic invocation remains enabled. Explicit examples:

- `$job-search Find recent backend roles requiring 0-2 years.`
- `$job-description-analyzer Analyze JOB_ID.`
- `$job-matcher Explain how my actual experience matches JOB_ID.`
- `$resume-tailor Emphasize relevant storage projects for JOB_ID.`
- `$latex-resume-builder Generate and inspect JOB_ID's PDF.`
- `$job-application Prepare JOB_ID and stop before submission.`
- `$application-tracker Show applications awaiting approval.`
- `$career-orchestrator Search, rank, and prepare selected jobs for review.`

Launchers expose the same CLI without copying shared business logic. Skills depend on this repository's shared package; copying one folder alone does not include the Python implementation. Each is independently executable from an initialized repository.

## End-to-end example

```sh
careerops init
careerops search --role "Backend Engineer" --days 7
careerops search --technology "C++" --experience-max 2
careerops jobs import tests/fixtures/sample_job.json
careerops jobs list
careerops analyze ee477307a0b449e9be92
careerops match ee477307a0b449e9be92
careerops resume tailor ee477307a0b449e9be92
careerops resume build ee477307a0b449e9be92 --template professional
careerops resume preview ee477307a0b449e9be92
```

The sample job is synthetic and points to example.com, not a real application target. These commands were executed successfully with the real local resume. Output includes a stable job ID, explainable score, job-specific content/report, a validated one-page PDF and PNG preview. Missing contact details were left absent.

For a real selected job, after verifying source/destination access rules and candidate facts:

```sh
careerops jobs add 'CANONICAL_JOB_URL' --description-file jd.txt --title 'VERIFIED TITLE' --company 'VERIFIED COMPANY'
careerops analyze JOB_ID
careerops match JOB_ID
careerops resume build JOB_ID
careerops apply prepare JOB_ID
careerops apply review JOB_ID
```

Prepare uploads the matching validated document and fills only verified answers. No final submit is clicked. Inspect the previews and review; resolve required/ambiguous questions with verified facts, then prepare again. Review shows the company's role/URL, actual resume filename, entered values, unresolved fields and review digest. Sensitive values are redacted unless you explicitly request `--show-sensitive` for local review.

Only after explicit approval for this exact application:

```sh
careerops apply approve JOB_ID --review-digest CURRENT_DIGEST
careerops apply submit JOB_ID
careerops applications list
careerops applications export --format csv
```

Interactive approval asks for confirmation. `--yes` represents explicit noninteractive user authorization for this one ID/digest; Codex must never invent that authorization. The submit command refuses unapproved, expired, changed or already-attempted applications. Each application needs its own approval. The CLI reopens an isolated browser and replays current verified answers, compares the live form digest, reserves the attempt, submits once and verifies evidence. Session-dependent forms may require the computer-use/manual route.

## Partial and batch workflows

`search`, `analyze`, `match`, `resume tailor`, `resume build`, `apply prepare`, and tracker commands are independently usable. `run --mode search-and-rank` searches and matches new jobs with bounded concurrency. `shortlist --min-score 70` selects suitable scores without known blockers. `run --mode generate-resumes` builds shortlisted documents with bounded concurrency. `run --mode prepare-shortlisted` prepares independent applications sequentially and stops for review. Failed jobs produce separate structured results. There is no batch submission mode.

To resume interrupted preparation, invoke prepare again. Completed analysis/documents are reused when their current input hashes match. A new preparation invalidates old approval. If an attempt is submission_unverified, stop and verify the outcome manually:

```sh
careerops applications reconcile APPLICATION_ID --evidence 'Verified confirmation page and application reference'
# Only when absence of submission has actually been verified:
careerops applications reconcile APPLICATION_ID --not-submitted --evidence 'Verified no application was accepted'
```

Track later outcomes with `applications update APPLICATION_ID --status interview --note 'Verified interview invitation'` or rejection/offer transitions. Reports include today, highest-matching, needing-application, awaiting-approval, submitted, manual, interview, rejected and offer.

## Local mock

`tests/fixtures/mock_application.html` includes text/email fields, file upload, dropdown, required certification, voluntary question, multi-step navigation, validation errors and an explicit confirmation ID. It makes no external requests. `tests/fixtures/mock_ats.py` serves it on loopback for `tests/browser/test_mock_browser.py`. The browser test uses synthetic candidate data and explicit test-only answers, proves the approval checkpoint, submits only to the mock, captures its receipt and tests duplicate prevention.

```sh
.venv/bin/python -m pytest tests/browser/test_mock_browser.py -v -rs
```

A loopback-hosting permission is required. This task environment prohibits bind, so the actual Playwright test was skipped with the precise reason. The separate integration test uses a deterministic BrowserDriver test double and passed the full PDF → form mapping/upload bytes → review → approval → one submit → confirmation → SQLite sequence. It is not represented as a real browser test.

## Importing previous applications

Import a verified historical job first. Then use `careerops applications import historical.json` with `job_id`, `confirmation_evidence` (a mapping of user-verified receipt details), optional `submitted_at` in ISO format, and optional `confirmation_reference`. This records historical state and one immutable import event; it never submits a browser form and never overwrites an active workflow. Reimporting the same job is idempotent.

## Supporting documents

An existing cover letter or other PDF can be approved as an exact field answer using `profile propose --field 'answer:EXACT UPLOAD LABEL' --value '/absolute/path/in/data/resumes/document.pdf' --evidence 'User approved this document'`, followed by profile approve. Preparation validates file boundaries/PDF readability and binds every uploaded document's bytes to the review digest. A changed supporting document requires a new review and approval. Resume controls always use the selected job's validated PDF and cannot be overridden.

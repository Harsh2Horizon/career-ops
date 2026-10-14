# CareerOps

Composable Codex skills backed by working Python modules, SQLite checkpoints, LaTeX resumes, and an approval-gated application workflow.

```sh
uv sync --extra dev
uv run careerops init
uv run careerops jobs import tests/fixtures/sample_job.json
uv run careerops analyze ee477307a0b449e9be92
uv run careerops match ee477307a0b449e9be92
uv run careerops resume build ee477307a0b449e9be92
```

In the current restricted environment, dependencies are already available in `.venv`; use `.venv/bin/careerops` or `.venv/bin/python -m career_ops` instead of a network install.

Eight independent skills live in `.agents/skills`: job-search, job-description-analyzer, job-matcher, resume-tailor, latex-resume-builder, job-application, application-tracker, and career-orchestrator. Launch Codex from this directory to discover them. They share structured contracts and reusable code rather than duplicating business logic.

Features include public Greenhouse/Lever/Ashby feed normalization, authorized JSON-LD company pages, assisted aggregator/YC/custom-link discovery, retained filtered jobs, evidence-level matching, legacy resume YAML parsing, traceable tailored claims, three ATS-conscious single-column templates, actual LaTeX compilation/PDF checks, semantic form mapping, isolated Playwright browser sessions, exact per-application approval, safe ambiguous-submission handling, immutable events, and metadata exports.

The original profile is user-controlled and ignored by Git. This workspace links its existing `../resume.yaml`; absent contact/eligibility details remain unknown. No real applications were submitted during testing.

Read [setup](docs/setup.md), [workflows](docs/workflows.md), [architecture](docs/architecture.md), [contracts](docs/contracts.md), [browser integration](docs/browser.md), [security](docs/security.md), and [troubleshooting](docs/troubleshooting.md). The [implementation report](docs/implementation-report.md) records actual tests and environmental limits.

Run `careerops --help` and subgroup help for all commands. `apply prepare` stops before submission. `apply approve` requires explicit approval for one exact review. `apply submit` refuses unapproved or already-attempted applications. There is no automatic mass-submission mode.

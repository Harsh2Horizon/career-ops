---
name: resume-tailor
description: Select and tailor verified resume.yaml achievements, projects, and skills for a CareerOps job, preserving titles, employers, dates, metrics, and fact provenance. Use for job-specific resume content and tailoring reports.
---

# Purpose
Produce accurate structured resume content with a transparent selection/rewrite report.

# Trigger conditions
Tailor my resume to this backend role. Emphasize AegisDB for a C++ database role.

# Inputs and outputs
Inputs: Canonical resume.yaml; stored job analysis and match; approved factual overlays.

Outputs: data/resumes/COMPANY/JOB_ID/tailored_resume.json and tailoring_report.md, with immutable versions.

# Workflow
Load the actual YAML, including mixed keys and empty projects. Tailor with resume tailor; inspect provenance and unsupported requirements. Scripts select/reorder and make deterministic spelling/spacing corrections. Additional factual rewrites require a profile proposal and explicit user verification before inclusion. Preserve original titles and dates. Load the profile schema reference only for parser issues.

# Scripts
Run from the CareerOps root (the launcher also resolves the workspace):

```sh
python .agents/skills/resume-tailor/scripts/run.py resume tailor JOB_ID
python .agents/skills/resume-tailor/scripts/run.py profile propose --field contact.email --value VALUE --evidence "User confirmed"
python .agents/skills/resume-tailor/scripts/run.py profile approve PROPOSAL_ID
```

# References
Read [references/contracts.md](references/contracts.md) for artifact/schema or state-boundary questions. 

# Failure handling
Insufficient contact/eligibility facts appear as confirmation needs. Free-text unsupported rewrites are rejected. Keep suggestions outside verified content.

# Security
Do not fabricate facts, metrics, employers, dates, skills, or projects. Do not modify the canonical YAML.

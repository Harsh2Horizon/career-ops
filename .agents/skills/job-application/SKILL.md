---
name: job-application
description: Prepare a selected CareerOps job application using verified candidate facts and the matching validated PDF, inspect unresolved questions, and submit only after explicit application-specific approval. Use for application assistance, preparation, review, or safe resumption.
---

# Purpose
Prepare one application, stop for review, and verify the final submission outcome.

# Trigger conditions
Prepare this application and stop for review. Assist with this job link. Resume JOB_ID without submitting.

# Inputs and outputs
Inputs: Selected job, current profile, matching validated resume PDF, authorized exact application host, and user-verified question answers.

Outputs: ApplicationForm/review.json, SQLite questions/events/status, and verified confirmation or submission_unverified.

# Workflow
Prefer the supported Codex computer-use/browser integration when available; see browser reference for bridging review records. CLI uses replaceable isolated Node Playwright. Prepare and inspect the exact job, PDF, answers, skipped sensitive fields, unresolved questions, and errors. Ask the user for unknown legally significant answers. Only after explicit approval for this job may approval be recorded. Submit once, require confirmation evidence, and persist it. An ambiguous attempt remains submission_unverified; do not retry it. Reprepare invalidates approval.

# Scripts
Run from the CareerOps root (the launcher also resolves the workspace):

```sh
python .agents/skills/job-application/scripts/run.py apply prepare JOB_ID
python .agents/skills/job-application/scripts/run.py apply review JOB_ID
python .agents/skills/job-application/scripts/run.py apply approve JOB_ID --review-digest DIGEST
python .agents/skills/job-application/scripts/run.py apply submit JOB_ID
```

# References
Read [references/contracts.md](references/contracts.md) for artifact/schema or state-boundary questions. Read [references/browser.md](references/browser.md) for tool choice, manual bridging, and website limitations. 

# Failure handling
Login/MFA/CAPTCHA, unsupported radios/custom controls/iframes, validation, expiration, and auth sessions require user/manual recovery. Automatic CLI replay cannot resume a login-dependent authenticated session.

# Security
Never guess work authorization, citizenship, demographics, salary history, consent, or certifications. No blanket submission approval, CAPTCHA bypass, password persistence, or blind retry. Exact approved hosts and safe upload paths are required.

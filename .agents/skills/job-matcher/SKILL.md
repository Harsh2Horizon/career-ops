---
name: job-matcher
description: Evaluate a stored CareerOps job against actual resume.yaml evidence and configurable preferences, separating professional use, project use, listed knowledge, missing qualifications, and eligibility blockers. Use to score or shortlist jobs.
---

# Purpose
Explain an evidence-weighted match score and separate eligibility from ranking.

# Trigger conditions
How well do I match JOB_ID? Shortlist jobs above 70.

# Inputs and outputs
Inputs: resume.yaml, job_analysis.json, config/preferences.yaml; approved fact overlay in SQLite.

Outputs: data/jobs/JOB_ID/match_result.json; SQLite JobMatches and shortlist state.

# Workflow
Analyze if needed, load the current profile, then match. Explain each score dimension and provenance levels. Check unresolved education, authorization, and sponsorship requirements explicitly. Missing preferred technology alone does not reject a job. Weights are heuristics, not interview probabilities.

# Scripts
Run from the CareerOps root (the launcher also resolves the workspace):

```sh
python .agents/skills/job-matcher/scripts/run.py match JOB_ID
python .agents/skills/job-matcher/scripts/run.py shortlist --min-score 70
```

# References
Read [references/contracts.md](references/contracts.md) for artifact/schema or state-boundary questions. 

# Failure handling
Missing profile, invalid configuration, or unclear eligibility must be surfaced. Do not infer eligibility from name or location.

# Security
Do not convert listed AI skills into production experience. Only verified profile/approved details count.

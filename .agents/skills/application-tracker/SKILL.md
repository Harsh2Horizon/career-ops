---
name: application-tracker
description: Track and report CareerOps jobs, resumes, application status, immutable events, outstanding questions, and verified submission outcomes in SQLite. Use for application history, status updates, exports, and manual reconciliation.
---

# Purpose
Maintain reliable history and actionable tracking reports.

# Trigger conditions
Show pending approvals. Export my application history. Record an interview invitation.

# Inputs and outputs
Inputs: SQLite state; selected job/application IDs; user-verified status/evidence.

Outputs: Validated status transitions, immutable events, metadata-only CSV/JSON exports, and reports.

# Workflow
Read state, show the requested report, record only verified updates, and export metadata. Use reconcile for ambiguous submission evidence. Never mark submitted based solely on a clicked button. Filtered jobs remain accessible through jobs list --filtered.

# Scripts
Run from the CareerOps root (the launcher also resolves the workspace):

```sh
python .agents/skills/application-tracker/scripts/run.py applications list
python .agents/skills/application-tracker/scripts/run.py applications show APPLICATION_ID
python .agents/skills/application-tracker/scripts/run.py applications export --format csv
python .agents/skills/application-tracker/scripts/run.py report --kind awaiting-approval
python .agents/skills/application-tracker/scripts/run.py applications update APPLICATION_ID --status interview --note "Interview invitation received"
```

# References
Read [references/contracts.md](references/contracts.md) for artifact/schema or state-boundary questions. 

# Failure handling
Invalid transitions and duplicate or ambiguous submissions are rejected. Preserve history; migrations do not reset data.

# Security
Exports omit personal answers/session secrets and neutralize spreadsheet formulas. Private SQLite/JSON remain ignored by Git.

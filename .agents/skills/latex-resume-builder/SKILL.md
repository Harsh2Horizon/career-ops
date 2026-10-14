---
name: latex-resume-builder
description: Render CareerOps tailored resumes through professional, compact, or modern single-column LaTeX templates, compile and validate extractable PDFs, and create stable upload filenames. Use for resume PDF generation or layout preview.
---

# Purpose
Generate readable A4 resumes with preserved text, links, and safe page limits.

# Trigger conditions
Build an ATS-friendly PDF for JOB_ID. Preview the compact resume.

# Inputs and outputs
Inputs: TailoredResume with validated candidate provenance; local LaTeX engine; Poppler for previews.

Outputs: resume.tex, resume.pdf, document.json, PNG previews, and Candidate_Name_Resume.pdf in job-specific immutable versions.

# Workflow
Use resume build, which validates provenance, prefers latexmk, detects installed engines, compiles without shell escape, extracts text, verifies content/links/page boundaries, and renders PNG previews. Inspect every preview visually before declaring the document ready for real upload. One spacing adjustment is allowed; fonts stay at 10pt. Two pages are allowed when necessary. Templates are shared assets.

# Scripts
Run from the CareerOps root (the launcher also resolves the workspace):

```sh
python .agents/skills/latex-resume-builder/scripts/run.py resume build JOB_ID --template professional
python .agents/skills/latex-resume-builder/scripts/run.py resume preview JOB_ID
```

# References
Read [references/contracts.md](references/contracts.md) for artifact/schema or state-boundary questions. 

# Failure handling
Missing engines, fonts, packages, overflow, or missing content fail with actionable errors. Never substitute a non-LaTeX PDF or claim an uncompiled file is valid.

# Security
Escape all text and URLs; refuse unsafe schemes. Never execute raw TeX from job content. Missing contact data stays absent.

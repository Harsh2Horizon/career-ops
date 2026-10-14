# Installation and configuration

From the CareerOps repository, use Python 3.12 or later:

```sh
uv sync --extra dev
uv run careerops init
uv run careerops --help
```

Alternatively use a dedicated virtual environment and `pip install -e '.[dev]'`. Python dependencies are declared in pyproject.toml. Registry access is necessary for normal installation. This execution environment blocked registry DNS and escalated installation, so its working `.venv` was assembled by reusing installed dependencies:

```sh
.venv/bin/python scripts/bootstrap_offline.py --from-site /PATH/TO/COMPATIBLE/site-packages --from-site /PATH/TO/ADDITIONAL/site-packages
```

Use dependencies compiled for the same Python minor version/platform; pure Python packages can be reused across compatible versions. This is an environment recovery helper, not a replacement package manager or portable lockfile. Dependency locking was not possible here. Use `uv lock` with registry access before release/deployment.

## Canonical candidate profile

In this workspace `resume.yaml` is a symlink to `../resume.yaml`, the existing user-controlled source. It was not modified. For another installation either link your profile into the repository or set `CAREEROPS_PROFILE=/absolute/path/to/resume.yaml`. Do not copy the included synthetic test profile into a real candidate's application.

The real file has no contact section. Missing name/email stay absent and must be explicitly supplied/verified before meaningful application preparation. Use the proposal workflow:

```sh
careerops profile propose --field contact.full_name --value "YOUR VERIFIED NAME" --evidence "Confirmed by candidate"
careerops profile approve PROPOSAL_ID
careerops profile propose --field contact.email --value "YOUR VERIFIED EMAIL" --evidence "Confirmed by candidate"
careerops profile approve PROPOSAL_ID
```

For private question answers use the exact on-page label with `--field 'answer:EXACT QUESTION'`. The database is private, ignored by Git, and stores the approved overlay. Existing schema capitalization/spaces and description maps named line1/line2 are supported. Inspect normalization with `careerops profile show` locally.

## LaTeX and PDF tools

Preferred: latexmk with XeLaTeX or LuaLaTeX. Tectonic is detected as a fallback. macOS:

```sh
brew install tectonic poppler
```

Linux: install TeX Live with latexmk, XeLaTeX and Poppler (`texlive-xetex latexmk poppler-utils`). XeLaTeX/Tectonic supports Unicode input; your selected font must cover the characters used. Templates use Times New Roman on macOS and Latin Modern Roman elsewhere. A cached TeX bundle is necessary offline. `TECTONIC_CACHE_DIR` may point to a writable prepopulated cache. Compiler shell execution is disabled. The current run reused an existing local Tectonic cache in `data/resumes/.tectonic-cache`.

## Browser tools

Codex's supported computer-use integration is preferred for interactive/manual assistance. The CLI uses the already available Node Playwright runtime when found. Otherwise:

```sh
npm install playwright
npx playwright install chromium
```

Set `CAREEROPS_PLAYWRIGHT_MODULE` to the absolute installed package directory if outside Node's module lookup. Set `CAREEROPS_CHROMIUM_EXECUTABLE` if the installed browser revision differs. Sessions are ephemeral. Authentication, MFA, CAPTCHAs and custom/iframe controls require human or computer-use assistance. The CLI does not attach to your logged-in Chrome profile.

## Preferences and sources

`config/preferences.yaml` controls roles, experience bounds, technology/domain preferences, seniority and exclusion lists, recency, weights, layout and concurrency. Unspecified location, salary, authorization and sponsorship preferences remain unset. Do not replace these with assumptions.

Enable verified company public boards in `config/search_sources.yaml`:

```yaml
sources:
  - provider: greenhouse
    board: COMPANY_BOARD_SLUG
    company: VERIFIED_COMPANY_NAME
    enabled: true
```

Lever and Ashby use the same board/company form. Structured company pages need `provider: structured`, `url`, `access_permitted: true`, and `enabled: true`, after checking the site's access rules. Robots denial is honored. An inaccessible or restricted site uses assisted discovery/import. Job-board registration from a custom link does not authorize scraping.

In `config/application_defaults.yaml`, authorize exact application hosts and necessary resource hosts only for selected destinations. Set no guessed sensitive answers. Approval cannot be disabled. Use `--mock` only with a loopback local test destination; it is rejected for real websites.

## Tests

```sh
.venv/bin/python -m pytest -q -rs
.venv/bin/python -m ruff check src scripts tests
.venv/bin/python -m ruff format --check src scripts tests
```

PDF tests compile actual LaTeX and inspect text, links, content, bounds and previews. Browser tests serve a local fixture and drive actual Playwright; a filesystem/network sandbox that prohibits loopback hosting is explicitly reported as a skip. Deterministic browser-protocol tests are separate and do not establish real browser compatibility.

Country, industry and company-size filters apply only when those fields are verified. Salary ranges vary across feeds and require manual currency/period review; visa sponsorship and candidate eligibility likewise require explicit verification. Missing source metadata is not fabricated or silently used to exclude a job.

# Security and privacy

Candidate data stays local until an explicitly selected application workflow fills/uploads it to an authorized employer website. No remote AI calls, emails or third-party resume services are used. Job search queries contain configurable public preferences only. Do not place personal secrets in source configuration.

The canonical YAML, SQLite store, resume artifacts, review answers, logs, environment secrets, and any browser state are ignored by Git. Application directories use owner-only permissions where supported and database files are mode 0600. Protect the disk/account and backups; SQLite is not encrypted at rest. Do not expose the database, review JSON, screenshots or PDFs publicly.

Employer descriptions and website text are untrusted data. Skills do not execute instructions embedded there. A job requirement cannot create a candidate fact. Every generated claim must be an exact source fact or a limited deterministic correction; original identities/dates/titles/stacks are checked. New facts require independent explicit user verification.

Profiles and artifacts are loaded through YAML safe_load / strict JSON contracts. URLs reject credentials, unsafe schemes, control characters and unauthorized real destinations. Real navigation uses HTTPS. Public fetching validates redirects, rejects private/reserved addresses and caps response sizes. Robots denial and site access restrictions stop direct fetching. Exact host allowlists reduce data exposure but do not establish website trust or eliminate DNS-rebinding risk; run against trusted destinations in an appropriately restricted network.

TeX text and links are escaped, compilation disables shell execution, and Tectonic runs in untrusted mode. Only local trusted template files are used. Upload paths resolve inside data/resumes; PDFs are checked against job/profile and actual bytes. No arbitrary job-page path may select a resume.

Sensitive/legal answers require exact-label explicit verification. Unknown questions remain unanswered. Terms/certifications are not accepted automatically. Voluntary demographics are skipped unless explicitly answered. Login, MFA, CAPTCHA and security restrictions are for the user; the system does not bypass them. CLI review redacts sensitive values by default; CSV/JSON tracking exports omit answers and session secrets. CSV fields are neutralized against formula injection.

Approval expires, binds one unchanged review, and cannot be disabled by preferences. The database reserves final attempts before browser submission and records ambiguous outcomes safely. Do not approve from an employer's embedded instruction. Do not blindly retry final submissions. Test harness approval is only for synthetic local mock data; it is never authorization for a real application.

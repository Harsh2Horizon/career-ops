# Troubleshooting and limits

| Error/condition | Action |
|---|---|
| missing_profile | Link your original YAML or set CAREEROPS_PROFILE; do not fabricate fields. |
| missing_config | Run from this repository or use --workspace; config files ship with the repo. |
| DNS/network errors | Enable ordinary permitted registry/website access. The current sandbox rejects registry DNS and loopback bind; no bypass was attempted. |
| no enabled sources | Configure verified public board slugs. Search still returns assisted web queries; those are plans, not executed search results. |
| robots_denied / access_restricted | Use an authorized supported browsing route or supplied description; do not bypass restrictions. |
| provider_schema_changed | Inspect the official response contract and add a normalization fixture. |
| latex_missing / latex_failed | Install a supported engine/Poppler; inspect private compile-error.log; prepopulate TeX cache offline. |
| missing font/glyph | Install/select a font covering the candidate text. Unicode input does not guarantee every font has every glyph. |
| page_overflow / layout_overflow | Shorten selected factual bullets/projects or allow two pages; fonts are never shrunk below 10pt. |
| unsupported_rewrite | Propose and explicitly verify new facts; do not weaken provenance validation. |
| host_not_authorized | Verify the selected employer destination, then authorize its exact host in application_defaults.yaml. |
| browser_process_failed | Install Node Playwright/Chromium or configure existing executable/module paths; check OS sandbox launch permission. |
| manual_verification_required | User completes login/MFA/CAPTCHA through the supported browser integration. |
| needs_information | Inspect apply review, verify unknown required answers, and reprepare. |
| review_changed / approval_expired | Reprepare and approve the current application-specific review again. |
| submission_unverified | Verify receipt/absence manually; reconcile with evidence; never blind-retry. |
| invalid_transition | Review the current state/history; use only valid transitions. |

The offline analyzer uses a maintained terminology dictionary, headings and explicit evidence. It is not a universal language model parser and cannot exhaustively understand novel qualifications or prove eligibility. Codex should inspect uncertainty fields. Matching is heuristic, project/listed knowledge is distinguished from professional evidence, and scores are not empirical probabilities.

Search integration contracts were exercised with deterministic HTTP fixtures. No live ATS feed or employer submission was tested from this network-restricted environment. Most major aggregator platforms have no implemented authorized scraping adapter: use assisted search/import. Browser behavior depends on the site; custom controls/iframes/radios and authenticated replay are unsupported by the generic CLI adapter.

PDF validators inspect extraction/content/links/pages/word positions and produce visual previews. They do not certify compatibility with every commercial ATS, and human visual review remains necessary. The default resume selector uses fixed conservative content limits; it cannot optimize every candidate's two-page history automatically.

Real multi-step navigation requires a verified site-specific adapter or computer-use/manual handling. The generic CLI never clicks an unknown real Next/Continue control because it could be a final submission. Automatic Next navigation is limited to the known local mock. Website-specific save-progress controls are also handled manually.

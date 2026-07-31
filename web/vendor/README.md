# Vendored third-party code

| Package | Version | License | Source |
|---|---|---|---|
| cm-chessboard | 8.7.5 | MIT (see cm-chessboard/LICENSE) | https://github.com/shaack/cm-chessboard |

Vendored deliberately: the dashboard has no build step and must work offline,
so nothing is fetched from a CDN at runtime. To update, re-run the `npm pack`
recipe in `docs/superpowers/plans/2026-07-31-web-dashboard.md` (Task 6) with a
new version and re-run the browser tests.

Fetched with `npm pack cm-chessboard@8.7.5` on 2026-07-31; `src/` was copied to
`cm-chessboard/` (so the entry module is `web/vendor/cm-chessboard/Chessboard.js`)
and `assets/` was copied alongside it unmodified. No layout adaptation was
needed — the 8.7.5 tarball matches the recipe's expected shape exactly, and the
module's exports (`Chessboard`, `INPUT_EVENT_TYPE`, `COLOR`, `BORDER_TYPE`) and
constructor options (`assetsUrl`, `style.borderType`) match the brief as
written.

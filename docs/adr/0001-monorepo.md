# ADR 0001: Monorepo for core, CLI, API, web UI, and docs

Date: 2026-07-30
Status: accepted

## Context

The roadmap (docs/ROADMAP.md) adds an HTTP API (v0.6), a web dashboard and
cross-platform CLI work (v0.7), and large-scale generation (v0.8+) on top of
the existing C++ core + Python bindings + CLI in this repository. The
question: keep everything in this one repository, or split into separate
repos (core/CLI, API, web UI, possibly docs)?

Relevant facts:

- The v0.6 API is an optional extra of the existing Python package
  (`pip install .[server]`) wrapping the same pybind11 bindings — it has no
  independent existence from the core's version.
- Releases on the roadmap (v0.6, v0.7, …) each span several layers; the
  existing tag-triggered release workflow produces one coherent release per
  tag.
- One maintainer. No independent teams, no separate release cadences.
- Tablebase files (up to ~27 GB each) are distributed via a Hugging Face
  dataset (see 2026-07-30 storage/API design spec), never committed to git.

## Decision

**One repository** (this one, osick/8pieces-helpmate) holds all artefacts,
separated by path:

```
src/        C++ core (generator, probe, CLI)
python/     Python package (bindings; server extra lives inside the package)
server/     v0.6 FastAPI service + helpmate-tables sync tooling (Python)
web/        v0.7 dashboard (added when that rung starts)
tools/      maintenance/release scripts
docs/       all documentation, specs, ADRs (this file); no separate docs repo
specs/      raw idea notes (input to brainstorming sessions)
```

CI uses path filters so, e.g., `server/**`-only changes do not rebuild the
C++ matrix. Table files stay out of git without exception.

## Consequences

- Cross-cutting changes (format change + API adaptation + docs + tests) are
  one atomic commit with one review and one CI run.
- One issue tracker, one CI configuration, one version ladder, one release
  per tag — matching the roadmap's structure.
- CI must gain path filtering as layers are added, or pipeline time grows
  with every rung.
- Repo size must be watched; the guard is the existing rule that generated
  tables never enter git.
- **Escape hatch:** if the web UI (or any layer) gains its own maintainer or
  deploy cadence, extract it with `git filter-repo` keeping full history.
  Splitting later is cheap; re-merging separate repos later is not. A future
  split supersedes this ADR with a new one recording the cross-repo
  versioning contract.

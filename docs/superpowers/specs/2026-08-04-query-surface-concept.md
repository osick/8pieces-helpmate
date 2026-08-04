# Query surface at scale — Concept

Date: 2026-08-04
**Status: concept only. Nothing here is scheduled, specified or approved for
implementation.** It records a direction and the decisions that direction
implies, so that when a rung is cut from it the arguments are already had.
Origin: discussion of 2026-08-03/04 following the v0.8.0 theme release.

## The problem

v0.8.0 shipped 16 theme names against a glossary of 295
(`docs/THEME-CATALOG.md`), of which 142 need no machinery this codebase
lacks. Separately, three parametric filters were requested — promotion counts,
promotion multisets, capture counts. Both pressures push on the same place:
`mine`'s flag surface.

`mine` today already carries `--dtm --count --starts --ends --theme --max
--tables`. The measures below would add nine more. The theme vocabulary, if
tier A and B are ever built, reaches ~150 names. Neither scales as flags.

## Two kinds of filter, and why the distinction matters

- **Themes** are boolean and nameable: `model`, `en-passant`, `closed-walk`.
- **Measures** are parametric: they carry a value, and the value is the
  question.

The three requested capabilities are measures. Encoding "three promotions" as
a theme would need one registry entry per value; the promotion-multiset case
is combinatorially hopeless — there are hundreds of multisets over {Q,R,B,N}
before four promotions. Measures take a value; themes take a name. Keeping
them apart keeps both surfaces small, whatever the eventual UI.

## The measures

Nothing new is needed to compute any of them. `Ply` already carries
`captured`, `promotion` and the mover's colour, and `mine` already enumerates
a candidate's solutions once for the shape and theme filters. These are
arithmetic over data already in hand — the enumeration is the expense, as the
v0.8 measurements established.

**Promotion count**, per side or either — including zero, meaning a solution
that reaches mate with pawns present and none promoting.

**Promotion multiset** — the solution's promotions are exactly `Q,B,B,R`, or
`R,N,B,B`; order-independent, so `QBBR` and `RBBQ` are one query.

**Capture count**, per side or either. **Zero is the flagship**: a solution
reaching mate without a single capture is a recognised compositional virtue
and there is currently no way to ask for one.

### Three semantic decisions these force

**An exact promotion multiset is not Allumwandlung.** The glossary defines AUW
as *"the four possible types of promotion all take place during the course of
the solution"* — set **coverage**, so `Q,R,B,N,N` is also an AUW, while an
exact multiset of `QRBN` excludes it. Both questions are useful and they are
different. AUW stays a boolean theme; the multiset stays a measure. Whichever
UI ships, it must not conflate them.

**"Captures by White" means captures *made by* White**, not white units
captured. The other reading is the one Zilahi cares about and is genuinely
useful — but it is a different measure and would get its own name, never a
redefinition of this one.

**Zero captures is a property of one solution, not of the position.** Under
the `any` semantics themes already use, a position matches when *at least one*
optimal solution is capture-free. For a composer chasing a clean unique
problem the real query is zero-captures **and** count 1. Any UI must make that
visible rather than leaving it in a manual.

## The vocabulary problem

With ~300 names of which a minority are implemented, three failures are
distinct and need distinct answers:

1. **Typo** — must fail loudly, with a suggestion.
2. **Real theme, not implemented** — must fail *differently*; it is not the
   user's mistake.
3. **Cannot remember the name** — the common case, and an error message is
   the wrong tool for it.

The fix for 1 and 2 is to load **all 295 names** with a status
(`implemented` / `planned` / `impossible`), not only those with detectors.
That makes the tool honest about its own limits, and makes
`docs/THEME-CATALOG.md` unable to drift, because the catalogue becomes the
code. The glossary supplies aliases free: it contains explicit redirects
(`AUW → Allumwandlung`, `ODT → Orthogonal-diagonal transformation`), plus
synonyms worth wiring — `Rundlauf → closed-walk`, `BK moves only →
single-piece:black`.

Themes want **tags, not a hierarchy** — a tree forces one parent, and these
genuinely belong to several families at once (AUW is *promotion* and
*cross-solution*). Names stay flat and stable; `:` remains the colour-variant
separator it already is.

## The direction: the TUI carries the complexity

`helpmate mine -i` / `--interactive` opens a terminal UI for exploring the
data, and **new query complexity goes there instead of into new flags.**

This resolves the tension rather than trading it. The alternatives were both
bad: keep adding flags until `mine --help` is unreadable, or invent an
expression grammar (`--filter 'promotions=3 AND captures=0'`) that is powerful
but has to be learned before it can be used once.

What it would carry:

- **Material picker** from what is actually on disk — which subsumes the
  `helpmate list <dir>` backlog item.
- **Theme browser** with type-ahead over all 295, each showing its definition
  and status, so discovery replaces memorisation.
- **Measures** as fields, where nine flags become nine inputs and cost
  nothing.
- **Solution browsing** — step through a hit's optimal lines, which today
  needs a separate `line --all` invocation.

### The feature that would actually change the workflow

Not flag avoidance — **live feedback**. Mining is exploratory: you cannot
currently tell whether `--captures 0 --count 1 --theme model` yields three
hits or three hundred thousand without running it to completion. A TUI showing
the count updating as filters are toggled turns query-building from guesswork
into a conversation with the data.

**This is also the hard part, and the reason this is a concept and not a
plan.** A theme or measure query scans a whole table, and on the corpus's
larger materials that is not interactive-speed. Making it feel live needs one
of: progressive results streamed as the scan proceeds; sampling a prefix of
the table for an estimate and saying plainly that it is an estimate; or
caching per-material scans. Each has a different failure mode, and the wrong
choice produces a UI that lies about how many positions match. That decision
has to be made deliberately, with measurement, before any of this is built.

### What stays in the CLI

The TUI does not replace the flags, and must not. Scripted and CI use needs
the non-interactive surface, and every existing flag stays exactly as it is.

The open question — genuinely open, not rhetorical — is whether the measures
get CLI flags **at all**, or live only in the core, the API, the TUI and the
dashboard. The argument for flags is scriptability. The argument against is
that nine flags is precisely the overload the TUI exists to avoid, and that a
measure is far more useful when composed interactively than typed from memory.
A middle position exists: expose the one or two measures with obvious
scripted value (`--captures 0` above all) and leave the combinatorial rest to
the interactive surfaces.

## Layering, if any of this is built

- **Core** implements every measure and theme once, as pure functions of a
  `Solution` — as the detectors already are.
- **API** is the complete surface. It already serves the theme registry, and
  CLI, TUI and dashboard all enumerate it rather than hard-coding, so nothing
  drifts.
- **CLI** stays minimal and scriptable.
- **TUI and dashboard** are the two exploratory front-ends, and should share
  the same vocabulary, the same statuses and the same live-count behaviour.

## Cheapest useful order, if it is ever scheduled

1. Full-glossary registry with status — small, and immediately makes the tool
   honest and discoverable. Everything else inherits it.
2. Shell completion generated from that registry — the 80% of the CLI problem,
   and it helps scripted users a TUI never reaches.
3. Measures in core and API.
4. TUI, once the live-count question above has an answer backed by
   measurement.

## Not decided here

Whether measures get CLI flags. The live-count strategy. Whether the TUI is a
rung of its own or part of a larger interactive push including the dashboard.
Ranges (`captures 0-2`) — every existing filter is exact, and mixing needs the
same syntax decision an expression surface would. Same-solution conjunction,
which remains unavailable and is the one query the excelsior search of
2026-08-03 could not express.

# Dashboard UX round 2 — no modes, and say the shared fact once

Status: proposed
Extends `2026-08-12-dashboard-ux-design.md` (v0.11.0). The rail/readout
skeleton, the palette and the sentinel discipline all stand. This pass changes
how the board is operated and how dense the readout is.

## Why

Two complaints, both correct, and they have a common cause: **the interface
repeats itself.**

**The editor repeats a decision the user already made.** v0.11.0 shipped a
four-way arming state — play, place, erase, arrange — because click-to-place
and drag-to-rearrange both bind `pointerdown` and cannot be live at once. That
was a real constraint, but it was the wrong thing to solve for. syzygy's board
is configured `movable: { free: true, color: 'both' }` with
`deleteOnDropOff: true` **permanently**; its one toggle changes whether a drag
*counts as a move*, never whether you can edit. Editing is never gated. Once
click-to-place goes, the conflict goes with it, and so do three buttons, an
eyebrow, a three-sentence hint and the whole armed-ring apparatus.

**The move list repeats itself literally.** Measured on
`7k/8/5K2/8/8/8/8/6Q1 w`: the Slower group renders 25 rows, and the badge on
every one reads either `h#1 · slower` or `h#2 · slower`. Twenty-five badges
carrying two distinct facts, at roughly 750px. The rail sits empty beside it
because the readout is three times the board's height.

At rest the explorer currently shows **20 buttons, 10 eyebrow labels, 5
paragraphs and 28 move rows, over 2915px**.

## The rule this pass applies

> **Say the shared fact once. Show only what differs. Weight marks what you
> can act on.**

## The board has no modes

One rule, no control:

| gesture | result |
|---|---|
| drag a piece to a square it could legally move to | **plays that move** |
| drag a piece anywhere else | **relocates it** |
| drag a piece off the board | **deletes it** |
| drag a piece from a tray onto a square | **places it** |

Every drop re-evaluates immediately, and every drop pushes a history entry, so
**Back undoes any of them**. A position missing a king short-circuits on the
existing `kingProblem` guard and spends no request, exactly as today.

Two cases the table above does not settle:

- **Dropping onto an occupied square.** If the drag is a legal move it is a
  capture and plays as one. Otherwise the dragged piece **replaces** the
  occupant — the same result as deleting it and placing the new one, which is
  what a setup board should do.
- **Promotion survives unchanged.** A pawn dragged to the last rank where
  several promotion moves share the from/to prefix still opens the vendored
  promotion dialog and plays exactly the piece chosen; a cancel snaps back.
  That path is untouched by this pass.

**The accepted risk, and what limits it.** Relocating a piece to a square that
happens to be a legal move plays a move instead. Three things bound the damage:
a drag by the side *not* to move can never be a legal move, so half of setup
work is unambiguous by construction; the outcome is immediately visible,
because a move flips the side to move and rewrites the verdict while a
relocation does not; and **Back** is a single reliable undo for both. Back
therefore stops being a minor convenience and becomes the safety net, and is
weighted accordingly.

**Removed entirely:** click-to-place, `Erase`, `Arrange`, `Done — evaluate`,
the `Edit position` eyebrow, the hint paragraph, the armed `aria-pressed` ring,
and the `editBaseline`/`commitBoard` machinery the v0.11.0 final review had to
repair. This pass deletes more code than it adds.

**Kept:** `Clear board` — dragging 32 pieces off one at a time is not a way to
start from an empty board.

## The trays flank the board

Black above, white below: each tray sits on the side of the board its colour
occupies. They **swap when the board is flipped**, because that placement is
the entire rationale — a tray on the far side from its own pieces is just a
row of buttons again.

The trays are the affordance. No label, no panel, no hint copy.

## The move list: rows where the datum differs, chips where it does not

```
OPTIMAL 2                       rows — the count differs per move and is
  ▌ Kh8              only reply   the product's whole subject
  ▌ Kh6                 3 ways

SLOWER 25                       chips — within a distance every move
  h#1   Qa7 Qg2 Qg3 Qg4 Qg5       shares the same badge, so the badge
        Kf7                       becomes the row label
  h#2   Ke5 Kg5 Ke6 Kf5 Ke7
        Kg6 Qb1 Qh2+ Qh1+ …

NO MATE 2                       chips — nothing differs at all
  Qg6  Qg8+
```

The optimal group keeps full rows because its badge carries the solution count,
which differs per move and is what a composer is reading the screen for.
Everything below it collapses to chips under a shared distance label. That
group goes from ~750px to ~110px.

The split is a rule, not a preference: **a per-move badge earns its place only
when it says something the group heading cannot.**

`#move-list li` must continue to select exactly the move rows, so chips are
`<li>` elements inside the group's `<ul>` and keep their `data-san`.

## The rail's controls collapse to one line

Under the white tray:

```
7k/8/5K2/8/8/8/8/6Q1 w        To move ▾   Flip   Clear board
```

The `Position (FEN)` eyebrow and the separate `Set` button go; the field
applies on Enter. This line is also **the keyboard path** — there is no
click-to-place, so a keyboard user types or pastes a position, which is what
syzygy expects too. That is a real limitation and the spec states it rather
than implying parity.

## The table band is one line

```
KQvk · longest h#7 · 45,723 solvable                  Open in Materials
```

The two histograms already exist on Materials, one click away. This saves
roughly 900px on every explorer screen.

## Weight marks what you can act on

The brief asks for heavier link buttons; the useful generalisation is that
**weight becomes the affordance cue**, which then lets several borders come
off:

- `600` — nav items, `Flip`, `Clear board`, `Open in Materials`,
  `Download PGN`, move rows and move chips, the FEN field's applied state
- `400` — verdicts, hints, group counts, table figures, everything inert

`Flip` and `Clear board` lose their borders and become weighted text buttons.
They keep a visible `:focus-visible` ring and an accent on `:hover`, so the
affordance survives for keyboard users and greyscale.

## Non-goals

- No palette change. The v0.11.0 tokens are used as-is; no new colours.
- No build step, no bundler, no chessground.
- No keyboard select-then-place path. Decided: the FEN field is the keyboard
  route. Revisit only if it proves insufficient in use.
- Materials and Search keep their v0.11.0 layouts; only the weight rule and
  the shared button styling reach them.

## Verification

**Node** — the move-list grouper gains distance sub-grouping: assert the
sub-groups are ordered by distance, that a group with one distinct distance
still renders one band, and that the optimal group is never sub-grouped.

**UI** — every existing test that pins click-to-place or the armed state is
**rewritten, not deleted**, to pin the replacement behaviour. Specifically:
- a legal drag plays the move (side to move flips, verdict changes, history +1)
- an illegal drag relocates (side to move unchanged, verdict recomputed)
- a drag off the board deletes, with no mode entered first
- a tray drag places, with no mode entered first
- `Back` undoes a relocation as well as a move
- the trays swap when the board is flipped
- `#move-list li` still counts exactly the legal moves, chips included
- the explorer renders no histogram

**By eye** — the explorer at 1280px in both themes, and the count of visible
buttons, eyebrows and paragraphs re-measured against the numbers above. The
target is a materially shorter page; if it does not drop well below 2915px the
pass has not done its job.

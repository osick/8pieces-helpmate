#!/usr/bin/env python3
"""Mine a puzzle set (EPD) from the tablebase corpus for the dashboard's
puzzle mode.

Offline, run by hand; its output (an EPD file) is committed. It walks a
ladder of ten (piece count, mate length) rungs spanning the measured corpus
-- 4 men at h#2 through 6 men at h#9, each rung a genuinely distinct
(dtm, pieces) pair so a session drawn across the ladder actually increases
in difficulty ten separate times, not five plateaus shown twice (fix round 1:
the original five-rung ladder gave pickSession's equal-band selection only
five distinct depths for a ten-puzzle session, so adjacent slots collapsed
onto the same difficulty -- see task-4-report.md, "Fix round 1"). For each
rung it picks a handful of materials, ranked by how many unique-solution positions
they hold at that depth. That count is read straight out of each material's
``<material>.stats.json`` (the ``uniqueness`` histogram, keyed by side to
move, dtm, and optimal-line count) -- no probing needed, since mining a
material that turns out to have zero matches at a given dtm is itself a
`Tablebase.mine_with_stats` call, and stats.json already answers "how many"
for free. helpmate's mining API is then asked for up to --per-bucket
positions with count=1 -- a unique solution, exactly one optimal line, so
the puzzle has exactly one right answer.

Mining is read-only against --tables (default ~/tb) and deterministic given
--seed: regenerating the file produces a reviewable diff, not a reshuffle.
No caching, no progress bar, no parallelism, no resume -- measured against
the real corpus, most buckets return in well under a second (see
task-4-report.md); the handful that don't are ones where the bucket holds
fewer positions than --per-bucket, which forces mine_with_stats to exhaust
the whole plane looking for matches that don't exist to find, an inherent
cost of the mining algorithm and not something this script can shortcut.

    taskset -c 0-3 python3 tools/mine_puzzles.py --tables ~/tb \\
        --out src/packages/web/helpmate_web/static/puzzles.epd --seed 1

SAFETY: refuses to write --out anywhere under ~/tb (mirrors the guard in
tools/bench_compression.py, applied there to --tables instead of --out --
that corpus may have a live generation run writing into it and must never
be a write target for this or any other tool).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import helpmate

# (label, pieces, dtm) -- the ladder. h# is dtm/2; an odd dtm is a "half"
# helpmate (White moves first). Ten rungs, each a distinct (dtm, pieces)
# pair, monotonically increasing in both -- so that pickSession's
# equal-band selection over a real corpus (many puzzles per rung) actually
# produces ten different depths for a ten-puzzle session, not five shown
# twice. Some depths are reachable by two different piece counts (dtm=6 at
# 4 and 5 men; dtm=12 at 5 and 6 men) -- both are kept as separate rungs on
# purpose: same mate length, more or fewer pieces is itself a difficulty
# axis (piece count is difficultyOf's tiebreaker), and it is also how the
# corpus actually looks -- 5-piece problems run deeper than 6-piece.
# Availability (positions with a unique solution) measured against the
# real corpus, read via the same uniqueness histogram this script uses:
#   1.  4 men  h#2  dtm  4    1,691,640
#   2.  4 men  h#3  dtm  6      607,628
#   3.  5 men  h#3  dtm  6  152,760,522
#   4.  6 men  h#4  dtm  8   21,646,697
#   5.  6 men  h#5  dtm 10   12,190,532
#   6.  5 men  h#6  dtm 12    4,285,739
#   7.  6 men  h#6  dtm 12    3,849,934
#   8.  6 men  h#7  dtm 14    1,106,081
#   9.  6 men  h#8  dtm 16       53,300
#  10.  6 men  h#9  dtm 18          317  -- genuinely scarce; expect THIN.
LADDER = [
    ("4 men, h#2", 4, 4),
    ("4 men, h#3", 4, 6),
    ("5 men, h#3", 5, 6),
    ("6 men, h#4", 6, 8),
    ("6 men, h#5", 6, 10),
    ("5 men, h#6", 5, 12),
    ("6 men, h#6", 6, 12),
    ("6 men, h#7", 6, 14),
    ("6 men, h#8", 6, 16),
    ("6 men, h#9", 6, 18),
]

# Materials considered per (pieces, dtm) bucket, ranked by how many
# unique-solution positions they hold at that dtm (most first). Bounds the
# number of buckets for piece counts with dozens/hundreds of materials
# (4 men: 37 candidates, 5 men: 180) while still taking every eligible
# material for the sparser 6-men tiers, which rarely have this many anyway.
TOP_K_MATERIALS = 5

EPD_HEADER = """\
# Helpmate puzzle set -- one position per line, EPD format.
#
# Fields: the four FEN placement/side/castling/en-passant fields, then
# `;`-separated `key value` opcodes. Exactly two opcodes are read:
#   hm  -- the helpmate distance IN PLIES (so `hm 4` is h#2)
#   id  -- a stable identifier
# Unknown opcodes are ignored, not fatal, so a future field costs nothing.
# `#` lines are comments. `hm` is stored rather than derived so ordering a
# thousand puzzles costs no probes; piece count is derived from the FEN, so
# it is not stored.
#
# Generated by tools/mine_puzzles.py -- to add a custom problem, type an
# EPD line by hand in the same format:
#
#   8/7k/5K2/8/8/8/8/6Q1 b - - ; hm 4 ; id "KQvk.0001"
#
"""


def eprint(*a, **kw) -> None:
    print(*a, file=sys.stderr, **kw)


def refuse_if_under_tb(path: Path, flag_name: str) -> None:
    """Exit non-zero if `path` resolves under $HOME/tb.

    Mirrors the guard in tools/bench_compression.py, applied there to
    --tables (a script that might write there); here it guards --out, since
    reading ~/tb is this script's whole purpose but writing into it would
    risk a live generation run's irreplaceable corpus.
    """
    tb_root = (Path.home() / "tb").resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(tb_root)
    except ValueError:
        return
    eprint(f"refusing to write: {flag_name}={path} resolves to {resolved}, "
           f"which is under {tb_root}. A generation run may be writing "
           f"there and the corpus is irreplaceable; point {flag_name} "
           f"somewhere else.")
    sys.exit(2)


def piece_count(material: str) -> int:
    return sum(1 for c in material if c != "v")


def list_materials(tables_dir: Path) -> list[str]:
    return sorted(p.stem for p in tables_dir.glob("*.hm"))


class StatsCache:
    """In-memory only -- read once per material per run, nothing persisted
    to disk. Not the caching the brief says this script doesn't need
    (that's about avoiding a resume/progress mechanism across runs)."""

    def __init__(self, tables_dir: Path):
        self._dir = tables_dir
        self._cache: dict[str, dict] = {}

    def uniqueness(self, material: str, dtm: int) -> int:
        if material not in self._cache:
            path = self._dir / f"{material}.stats.json"
            try:
                with open(path) as f:
                    self._cache[material] = json.load(f).get("uniqueness", {})
            except (FileNotFoundError, json.JSONDecodeError):
                self._cache[material] = {}
        u = self._cache[material]
        total = 0
        for side in ("btm", "wtm"):
            total += u.get(side, {}).get(str(dtm), {}).get("1", 0)
        return total


def rank_materials(materials: list[str], pieces: int, dtm: int,
                    stats: StatsCache) -> list[tuple[str, int]]:
    """Materials of the given piece count with >=1 unique-solution position
    at this dtm, ranked by count descending (ties broken alphabetically for
    determinism), top TOP_K_MATERIALS kept."""
    candidates = [m for m in materials if piece_count(m) == pieces]
    scored = [(m, stats.uniqueness(m, dtm)) for m in candidates]
    scored = [(m, n) for m, n in scored if n > 0]
    scored.sort(key=lambda t: (-t[1], t[0]))
    return scored[:TOP_K_MATERIALS]


def mine_bucket(tb: "helpmate.Tablebase", material: str, dtm: int,
                 available: int, per_bucket: int, rng: random.Random,
                 ) -> tuple[list[str], float]:
    """Up to `per_bucket` unique-solution FENs for (material, dtm).

    When more are available than we need, over-fetch a modest pool (so the
    mining call can still early-exit well short of a full scan) and sample
    from it with the seeded RNG, so re-running with the same --seed
    reproduces the same puzzles and a different --seed reshuffles which
    ones get picked -- not just their order.
    """
    take = min(per_bucket, available)
    pool_cap = min(available, max(per_bucket * 10, 200))
    t0 = time.time()
    fens, _skipped = tb.mine_with_stats(material, dtm, 1, pool_cap, -1, -1, [])
    elapsed = time.time() - t0
    if len(fens) > take:
        fens = rng.sample(fens, take)
    else:
        rng.shuffle(fens)
    return fens, elapsed


def to_epd_line(fen: str, dtm: int, puzzle_id: str) -> str:
    fields = fen.split()[:4]
    return f'{" ".join(fields)} ; hm {dtm} ; id "{puzzle_id}"'


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tables", type=Path, default=Path.home() / "tb",
                         help="read-only tables directory (default: ~/tb)")
    parser.add_argument("--out", type=Path, required=True,
                         help="EPD file to write (must not resolve under ~/tb)")
    parser.add_argument("--per-bucket", type=int, default=20,
                         help="max positions taken per (material, dtm) bucket (default: 20; "
                              "ten rungs x up to 5 materials each keeps the total near 1000)")
    parser.add_argument("--seed", type=int, default=1,
                         help="RNG seed for which/how positions are sampled and ordered "
                              "within each bucket (default: 1)")
    args = parser.parse_args()

    refuse_if_under_tb(args.out, "--out")

    tables_dir = args.tables.expanduser()
    tb = helpmate.Tablebase(str(tables_dir))
    materials = list_materials(tables_dir)
    if not materials:
        eprint(f"no *.hm tables found under {tables_dir}")
        return 2
    stats = StatsCache(tables_dir)
    rng = random.Random(args.seed)

    rows: list[str] = []
    summary: list[tuple[str, str, int, int, int, int, float]] = []
    # (tier label, material, dtm, available, requested, found, seconds)
    rung_totals: list[tuple[str, int, int, int]] = []
    # (tier label, dtm, materials found, puzzles found) -- a rung can be
    # thin two different ways a single material row cannot show: fewer
    # eligible materials than TOP_K_MATERIALS (the depth is rare across the
    # whole corpus, not just for one material), or a low total even when
    # every individual material clears --per-bucket on its own.

    for label, pieces, dtm in LADDER:
        ranked = rank_materials(materials, pieces, dtm, stats)
        if not ranked:
            summary.append((label, "(none eligible)", dtm, 0, 0, 0, 0.0))
            rung_totals.append((label, dtm, 0, 0))
            continue
        rung_found = 0
        for material, available in ranked:
            fens, elapsed = mine_bucket(
                tb, material, dtm, available, args.per_bucket, rng)
            for i, fen in enumerate(fens, start=1):
                puzzle_id = f"{material}.h{dtm}.{i:04d}"
                rows.append(to_epd_line(fen, dtm, puzzle_id))
            summary.append((label, material, dtm, available,
                             min(args.per_bucket, available), len(fens), elapsed))
            rung_found += len(fens)
        rung_totals.append((label, dtm, len(ranked), rung_found))

    # --- bucket summary table -------------------------------------------
    print(f"{'tier':<20} {'material':<10} {'dtm':>4} {'available':>10} "
          f"{'requested':>10} {'found':>6} {'secs':>7}")
    for label, material, dtm, available, requested, found, elapsed in summary:
        # THIN/EMPTY compares against --per-bucket (what we asked the ladder
        # for), not `requested` (already capped to what was available) --
        # found always equals requested by construction, so that comparison
        # would never flag anything.
        flag = "  <-- EMPTY" if available == 0 else (
            "  <-- THIN" if available < args.per_bucket else "")
        print(f"{label:<20} {material:<10} {dtm:>4} {available:>10} "
              f"{requested:>10} {found:>6} {elapsed:>7.2f}{flag}")

    # --- rung totals -- catches a rung that is thin ACROSS materials, not ---
    # just one material below --per-bucket (e.g. only 2 of 5 materials exist
    # at that depth at all, but each of those 2 individually clears
    # --per-bucket, so no single row above would show it).
    ideal = TOP_K_MATERIALS * args.per_bucket
    print(f"\n{'tier':<20} {'dtm':>4} {'materials':>10} {'puzzles':>8}")
    for label, dtm, n_materials, found in rung_totals:
        flag = "  <-- EMPTY RUNG" if found == 0 else (
            "  <-- THIN RUNG" if n_materials < TOP_K_MATERIALS or found < ideal else "")
        print(f"{label:<20} {dtm:>4} {n_materials:>10} {found:>8}{flag}")

    print(f"\ntotal puzzles: {len(rows)}")

    # --- write --------------------------------------------------------
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        f.write(EPD_HEADER)
        for line in rows:
            f.write(line + "\n")
    print(f"wrote {len(rows)} lines to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

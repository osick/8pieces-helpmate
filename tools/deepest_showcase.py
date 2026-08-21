"""Build docs/DEEPEST.md: the deepest *sound* problem in every material class.

Sound means `count == 1` -- a single optimal solution. In problem chess that
is the quality criterion: a second solution is a dual and the composition is
unsound. So the interesting position in a material class is not its longest
one, it is the longest one that is still unique.

Those are rarely the same, and the gap is the point of this file. At maximum
depth the solution count is usually saturated (255+): the very deepest
positions have hundreds of ways to reach mate. `KRvkbn` runs to h#7, but every
position at h#7 and h#6.5 is saturated, and its deepest unique position is
h#6 -- twelve of them, in a table of 121 million cells.

Nothing here is mined. `uniqueness` in each stats sidecar maps dtm -> count ->
number of positions, so the deepest depth holding a unique solution is exact,
as is how many exist there. The sidecar's `deepest_unique` supplies a sample
FEN, which is then verified by probing before it is used.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

def run(binary: str, args: list[str], tables: str, retries: int = 3) -> str:
    # Retried because the compressed read path throws an intermittent
    # "zstd decompress failed: Restored data doesn't match checksum" on large
    # tables -- roughly one run in ten, single-threaded, tracked separately.
    for attempt in range(retries):
        p = subprocess.run([binary, *args, "--tables", tables],
                           capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout
        if "checksum" not in p.stderr:
            raise RuntimeError(f"{' '.join(args)}: {p.stderr.strip()[:200]}")
        print(f"    retry {attempt+1} after checksum error", file=sys.stderr)
    raise RuntimeError(f"{' '.join(args)}: failed after {retries} retries")

def deepest_unique_depth(stats: dict) -> tuple[int, int] | None:
    """(dtm, how many positions have a unique solution at that dtm), exact."""
    best = None
    for side in ("wtm", "btm"):
        for dtm, counts in stats.get("uniqueness", {}).get(side, {}).items():
            n = counts.get("1")
            if n and (best is None or int(dtm) > best[0]):
                best = (int(dtm), 0)
        # second pass: total across both sides at the winning depth
    if best is None:
        return None
    d = best[0]
    total = sum(int(stats["uniqueness"][s].get(str(d), {}).get("1", 0))
                for s in ("wtm", "btm"))
    return d, total

def saturated_at_max(stats: dict) -> bool:
    """True if every position at max_dtm has a saturated (255+) solution count."""
    md = str(stats["max_dtm"])
    keys: set[str] = set()
    for side in ("wtm", "btm"):
        keys |= set(stats.get("uniqueness", {}).get(side, {}).get(md, {}))
    return bool(keys) and keys == {"255"}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", required=True)
    ap.add_argument("--binary", default="./build/helpmate")
    ap.add_argument("--out", default="docs/DEEPEST.json")
    a = ap.parse_args()

    mats = []
    for sc in sorted(Path(a.tables).glob("*.stats.json")):
        s = json.loads(sc.read_text())
        if not isinstance(s.get("max_dtm"), int) or s["max_dtm"] > 250:
            continue                              # marker table: no mate exists
        mats.append((len(sc.name[: -len(".stats.json")]) - 1,
                     sc.name[: -len(".stats.json")], s))
    mats.sort(key=lambda t: (t[0], t[1]))

    results = []
    for pieces, mat, s in mats:
        du = deepest_unique_depth(s)
        if du is None:
            print(f"  {mat}: no unique solution at any depth", file=sys.stderr)
            continue
        depth, howmany = du
        fens = s.get("deepest_unique") or []
        if not fens:
            print(f"  {mat}: uniqueness says depth {depth} but no sample FEN",
                  file=sys.stderr)
            continue
        fen = fens[0]
        probe = run(a.binary, ["probe", fen], a.tables).strip()
        if "count=1" not in probe or f"dtm={depth} " not in probe + " ":
            print(f"  {mat}: SAMPLE MISMATCH -- {probe} vs depth {depth}",
                  file=sys.stderr)
            continue
        lines = [ln for ln in run(a.binary, ["line", fen, "--all", "--max", "2"],
                                  a.tables).splitlines() if ln.strip()]
        results.append({
            "material": mat, "pieces": pieces, "fen": fen, "probe": probe,
            "dtm": depth, "max_dtm": s["max_dtm"], "unique_at_depth": howmany,
            "plane_size": s.get("plane_size"),
            "saturated_at_max": saturated_at_max(s),
            "solution": lines[0] if lines else "",
            "extra_lines": len(lines) - 1,
        })
        gap = s["max_dtm"] - depth
        print(f"  {mat}: unique depth {depth} (max {s['max_dtm']}, gap {gap}), "
              f"{howmany} such position(s)", file=sys.stderr)

    Path(a.out).write_text(json.dumps(results, indent=1))
    print(f"wrote {len(results)} entries to {a.out}", file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())

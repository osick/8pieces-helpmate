#!/usr/bin/env python3
"""Performance gate for block-compressed tables (v0.7.5).

`docs/ROADMAP.md` makes the block-compression rung conditional on three
measured numbers, against a real 6-piece/5-piece corpus, not intuition:

    1. compression ratio            >= 5x
    2. warm probe latency           within ~2x of raw
    3. generation wall-clock        no more than a few percent slower

This script measures (2), (3), and the ratio for whatever material/table you
point it at, plus a "cold" probe number whose caveats it prints rather than
overclaiming (see below). It writes no production code and changes nothing
under version control; every scratch directory it creates comes from
`tempfile.mkdtemp()` (Python's `mktemp -d` equivalent) and is removed when
the run finishes, unless --keep-scratch is given.

SAFETY: this script REFUSES to run if --tables resolves under the user's
home "tb" directory (~/tb). That corpus (tens of GB) may have a live
generation run writing into it, and this script's job is to measure, not to
risk it. Point --tables at a directory you control -- if you want to
benchmark a table that currently lives under ~/tb, copy it out first
(`cp ~/tb/<material>.hm ~/tb/<material>.stats.json <somewhere-else>/`);
reading ~/tb directly with plain shell tools is fine, this script simply
will not accept it as an argument.

Usage:

    taskset -c 0-3 python3 tools/bench_compression.py --material KQvk
    taskset -c 0-3 python3 tools/bench_compression.py --material KRvk

    # Point at an existing raw table instead of generating one fresh
    # (recommended for anything past a few-piece material -- generation is
    # not free, see --skip-gen below):
    taskset -c 0-3 python3 tools/bench_compression.py \\
        --material KBvkbn --tables /path/to/staged/copy --skip-gen

Every subprocess this script launches (helpmate gen / compact) is itself run
under `taskset -c 0-3` regardless of how this script was invoked, but the
in-process probe timings (via the `helpmate` Python bindings) only get that
affinity if the interpreter itself is pinned -- hence the taskset prefix in
the usage examples above; the script also tries `os.sched_setaffinity(0,
{0,1,2,3})` on its own PID as a second line of defense.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

TASKSET = ["taskset", "-c", "0-3"]


def eprint(*a: Any, **kw: Any) -> None:
    print(*a, file=sys.stderr, **kw)


def pin_this_process() -> None:
    try:
        os.sched_setaffinity(0, {0, 1, 2, 3})
    except (AttributeError, OSError) as e:
        eprint(f"note: could not pin this process to cores 0-3 ({e}); "
               f"rely on the outer `taskset -c 0-3 python3 ...` instead")


def refuse_if_under_tb(path: Path, flag_name: str) -> None:
    """Exit non-zero if `path` resolves under $HOME/tb.

    Unconditional, with no escape hatch: this is the safety net against
    accidentally pointing a write-capable tool at the live 89.7 GB corpus.
    Reading ~/tb with ordinary shell commands remains fine; this check only
    ever fires on arguments the caller hands to *this script*.
    """
    tb_root = (Path.home() / "tb").resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(tb_root)
    except ValueError:
        return
    eprint(f"refusing to run: {flag_name}={path} resolves to {resolved}, "
           f"which is under {tb_root}. A generation run may be writing "
           f"there and the corpus is irreplaceable; point {flag_name} at a "
           f"directory you control (copy any files you need out of ~/tb "
           f"first -- reading it is fine, this script just won't accept it "
           f"as an argument).")
    sys.exit(2)


def check_bindings_freshness(repo_root: Path) -> None:
    """Best-effort warning if the installed `helpmate` extension predates
    the source tree it will be measured against (stale-build risk noted in
    the task brief -- this affects the reader/probe path directly)."""
    try:
        import helpmate._helpmate as ext  # type: ignore[import-not-found]

        so_path = Path(ext.__file__)
        so_mtime = so_path.stat().st_mtime
        newest_src = 0.0
        newest_file = None
        for pattern in ("src/core/**/*.cpp", "src/core/**/*.h",
                         "src/packages/bindings/**/*.cpp",
                         "src/packages/cli/**/*.cpp"):
            for f in repo_root.glob(pattern):
                m = f.stat().st_mtime
                if m > newest_src:
                    newest_src, newest_file = m, f
        if newest_src > so_mtime:
            eprint(f"WARNING: installed extension {so_path} is OLDER than "
                   f"{newest_file} in the source tree. Results may reflect "
                   f"stale code. Rebuild with:\n"
                   f"  GIT_CONFIG_GLOBAL=/dev/null CC=gcc-13 CXX=g++-13 "
                   f"taskset -c 0-3 python3 -m pip install -e . "
                   f"--no-build-isolation -q "
                   f"--config-settings=build-dir=build/skbuild")
        else:
            print(f"bindings freshness: ok ({so_path} newer than source tree)")
    except Exception as e:  # pragma: no cover - best-effort diagnostic only
        eprint(f"note: could not check bindings freshness ({e})")


def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    proc = subprocess.run(cmd, **kw)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")
    return proc


def tasksetted(cmd: list[str]) -> list[str]:
    return TASKSET + cmd


def dir_size(d: Path, material: str) -> int:
    f = d / f"{material}.hm"
    if not f.exists():
        raise FileNotFoundError(f"expected {f} to exist")
    return f.stat().st_size


def stage_or_generate_raw(material: str, tables: Path | None, threads: int,
                           raw_dir: Path) -> None:
    """Populate raw_dir/<material>.hm (+ .stats.json if available)."""
    if tables is not None:
        src_hm = tables / f"{material}.hm"
        if not src_hm.exists():
            raise FileNotFoundError(
                f"--tables {tables} has no {material}.hm; generate it first "
                f"or omit --tables to generate fresh in scratch")
        shutil.copy2(src_hm, raw_dir / src_hm.name)
        src_stats = tables / f"{material}.stats.json"
        if src_stats.exists():
            shutil.copy2(src_stats, raw_dir / src_stats.name)
        print(f"raw source: copied {src_hm} ({src_hm.stat().st_size:,} bytes)")
    else:
        print(f"raw source: generating {material} fresh into {raw_dir}")
        t0 = time.perf_counter()
        run(tasksetted(["helpmate", "gen", material, "--tables", str(raw_dir),
                         "--threads", str(threads)]))
        print(f"  generated in {time.perf_counter() - t0:.2f}s")


def make_compressed_copy(raw_dir: Path, material: str, comp_dir: Path) -> None:
    """Copy the raw table into comp_dir and convert it with
    `helpmate compact --compress`. The converter skips files modified in the
    last hour (protects a live generation run), so the freshly-copied file's
    mtime is backdated -- exactly what
    src/packages/cli/tests/verify_compress_skip_recent.cmake exercises."""
    src_hm = raw_dir / f"{material}.hm"
    dst_hm = comp_dir / f"{material}.hm"
    shutil.copy2(src_hm, dst_hm)
    src_stats = raw_dir / f"{material}.stats.json"
    if src_stats.exists():
        shutil.copy2(src_stats, comp_dir / src_stats.name)
    two_hours_ago = time.time() - 7200
    os.utime(dst_hm, (two_hours_ago, two_hours_ago))
    out = run(tasksetted(["helpmate", "compact", str(comp_dir), "--compress"]))
    print(f"  {out.stdout.strip()}")


def gather_candidate_fens(tables_dir: Path, material: str, target: int,
                           seed: int) -> tuple[list[str], int]:
    """Distinct FENs pulled from several dtm buckets (spread across the
    histogram, both sides to move) and globally shuffled.

    Caveat, stated plainly rather than hidden: within one dtm bucket,
    Tablebase.mine() returns matching cells in increasing cell-index order,
    i.e. a low-index PREFIX of that bucket's matches, not a uniform sample
    over the bucket. Sampling many buckets and shuffling the combined pool
    mitigates but does not eliminate this -- it is not a rigorous uniform
    random sample over the logical byte range, only a reasonable spread
    across it. See the report for what this does and does not establish
    about "cold" probes.
    """
    import helpmate  # local import: only needed here, and only after the
    # freshness check above has had a chance to warn about a stale build.

    tb = helpmate.Tablebase(str(tables_dir))
    stats_path = tables_dir / f"{material}.stats.json"
    dtm_values: list[int] = []
    if stats_path.exists():
        hist = json.loads(stats_path.read_text()).get("dtm_histogram", {})
        for side in ("wtm", "btm"):
            for k, v in hist.get(side, {}).items():
                if v > 0:
                    dtm_values.append(int(k))
        dtm_values = sorted(set(dtm_values))
    if not dtm_values:
        # No sidecar (or nothing solvable in it) -- brute-force a plausible
        # dtm range rather than give up; harmless if most probes miss.
        dtm_values = list(range(0, 40))

    rng = random.Random(seed)
    rng.shuffle(dtm_values)
    per_bucket = max(50, (target // max(1, len(dtm_values))) * 2 + 50)

    pool: list[str] = []
    seen: set[str] = set()
    for d in dtm_values:
        if len(pool) >= target * 3:
            break
        try:
            fens = tb.mine(material, dtm=d, max=per_bucket)
        except Exception:
            continue
        for f in fens:
            if f not in seen:
                seen.add(f)
                pool.append(f)

    rng.shuffle(pool)
    return pool[:target], len(pool)


def warm_probe_ns(tables_dir: Path, fen: str, reps: int) -> list[int]:
    import helpmate

    tb = helpmate.Tablebase(str(tables_dir))
    tb.probe(fen)  # warm the cache / page in the relevant bytes
    times = []
    for _ in range(reps):
        t0 = time.perf_counter_ns()
        tb.probe(fen)
        times.append(time.perf_counter_ns() - t0)
    return times


def cold_probe_ns(tables_dir: Path, fens: list[str]) -> list[int]:
    """One Tablebase, opened once; each of `fens` (already distinct and
    shuffled) probed exactly once, in order. This is "cold" with respect to
    the reader's own decompressed-block cache for any position whose block
    was not already visited by an earlier fen in this same list, but NOT
    cold with respect to the OS page cache -- see the caller for the
    disclaimer that belongs in the report, not buried here.
    """
    import helpmate

    tb = helpmate.Tablebase(str(tables_dir))
    times = []
    for fen in fens:
        t0 = time.perf_counter_ns()
        tb.probe(fen)
        times.append(time.perf_counter_ns() - t0)
    return times


def gen_wallclock_run(material: str, threads: int, compress: bool,
                       keep_scratch: bool) -> tuple[float, int]:
    scratch = Path(tempfile.mkdtemp(prefix="bench_compression_gen_"))
    refuse_if_under_tb(scratch, "scratch (internal)")
    try:
        cmd = tasksetted(["helpmate", "gen", material, "--tables", str(scratch),
                           "--threads", str(threads)])
        if compress:
            cmd.append("--compress")
        t0 = time.perf_counter()
        run(cmd)
        dt = time.perf_counter() - t0
        size = dir_size(scratch, material)
        return dt, size
    finally:
        if not keep_scratch:
            shutil.rmtree(scratch, ignore_errors=True)
        else:
            print(f"  kept scratch dir: {scratch}")


def fmt_ns(ns: float) -> str:
    if ns < 1000:
        return f"{ns:.0f} ns"
    if ns < 1_000_000:
        return f"{ns / 1000:.2f} us"
    return f"{ns / 1_000_000:.2f} ms"


def summarize(name: str, times: list[int]) -> dict[str, float]:
    med = statistics.median(times)
    mean = statistics.mean(times)
    p10 = sorted(times)[len(times) // 10]
    p90 = sorted(times)[min(len(times) - 1, (len(times) * 9) // 10)]
    print(f"  {name}: n={len(times)} median={fmt_ns(med)} mean={fmt_ns(mean)} "
          f"p10={fmt_ns(p10)} p90={fmt_ns(p90)}")
    return {"n": len(times), "median_ns": med, "mean_ns": mean,
            "p10_ns": p10, "p90_ns": p90}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--material", required=True,
                         help='canonical material string, e.g. "KQvk"')
    parser.add_argument("--tables", type=Path, default=None,
                         help="directory holding an existing <material>.hm "
                              "(and optionally <material>.stats.json) to use "
                              "as the raw baseline, copied read-only into "
                              "scratch. Omit to generate the material fresh "
                              "instead (fine for small materials only). "
                              "REFUSED if it resolves under ~/tb.")
    parser.add_argument("--gen-material", default=None,
                         help="material to use for the generation "
                              "wall-clock section (default: same as "
                              "--material). Use this to decouple a cheap "
                              "generation-timing material from an "
                              "already-generated --tables source used for "
                              "the ratio/probe sections.")
    parser.add_argument("--skip-gen", action="store_true",
                         help="skip the generation wall-clock section "
                              "entirely (use when --material/--gen-material "
                              "is too large to regenerate cheaply)")
    parser.add_argument("--gen-runs", type=int, default=2,
                         help="repeat count per gen mode (default: 2)")
    parser.add_argument("--gen-threads", type=int, default=4,
                         help="--threads passed to `helpmate gen` (default: "
                              "4, matching the 4 cores of taskset -c 0-3)")
    parser.add_argument("--probes", type=int, default=10000,
                         help="target distinct positions for the cold-probe "
                              "measurement (default: 10000)")
    parser.add_argument("--warm-reps", type=int, default=10000,
                         help="repeat count for the warm-probe measurement "
                              "(default: 10000)")
    parser.add_argument("--seed", type=int, default=0,
                         help="shuffle seed, for a reproducible candidate "
                              "pool (default: 0)")
    parser.add_argument("--keep-scratch", action="store_true",
                         help="do not remove scratch directories on exit "
                              "(debugging only)")
    parser.add_argument("--json", type=Path, default=None,
                         help="also write the full results as JSON to this "
                              "path")
    args = parser.parse_args()

    pin_this_process()

    repo_root = Path(__file__).resolve().parent.parent
    check_bindings_freshness(repo_root)

    if args.tables is not None:
        refuse_if_under_tb(args.tables, "--tables")

    gen_material = args.gen_material or args.material
    results: dict[str, Any] = {
        "material": args.material,
        "gen_material": gen_material,
        "tables_source": str(args.tables) if args.tables else None,
        "seed": args.seed,
    }

    raw_dir = Path(tempfile.mkdtemp(prefix="bench_compression_raw_"))
    comp_dir = Path(tempfile.mkdtemp(prefix="bench_compression_comp_"))
    refuse_if_under_tb(raw_dir, "scratch (internal)")
    refuse_if_under_tb(comp_dir, "scratch (internal)")
    try:
        print(f"=== ratio: {args.material} ===")
        stage_or_generate_raw(args.material, args.tables, args.gen_threads, raw_dir)
        raw_size = dir_size(raw_dir, args.material)
        make_compressed_copy(raw_dir, args.material, comp_dir)
        comp_size = dir_size(comp_dir, args.material)
        ratio = raw_size / comp_size
        print(f"  raw:        {raw_size:,} bytes")
        print(f"  compressed: {comp_size:,} bytes")
        print(f"  ratio:      {ratio:.2f}x")
        results["ratio"] = {"raw_bytes": raw_size, "compressed_bytes": comp_size,
                             "ratio": ratio}

        print(f"\n=== warm probe: {args.material} (n={args.warm_reps}) ===")
        fens, pool_size = gather_candidate_fens(raw_dir, args.material, 1, args.seed)
        if not fens:
            raise RuntimeError(f"could not find any solvable position in "
                                f"{args.material} to probe")
        warm_fen = fens[0]
        print(f"  position: {warm_fen}")
        raw_warm = warm_probe_ns(raw_dir, warm_fen, args.warm_reps)
        comp_warm = warm_probe_ns(comp_dir, warm_fen, args.warm_reps)
        raw_warm_stats = summarize("raw       ", raw_warm)
        comp_warm_stats = summarize("compressed", comp_warm)
        warm_ratio = comp_warm_stats["median_ns"] / raw_warm_stats["median_ns"]
        print(f"  compressed/raw median ratio: {warm_ratio:.3f}x "
              f"(gate: within ~2x)")
        results["warm_probe"] = {"fen": warm_fen, "raw": raw_warm_stats,
                                  "compressed": comp_warm_stats,
                                  "ratio": warm_ratio}

        print(f"\n=== cold probe: {args.material} (target n={args.probes}) ===")
        cold_fens, pool_size = gather_candidate_fens(raw_dir, args.material,
                                                       args.probes, args.seed)
        print(f"  candidate pool: {pool_size} distinct positions gathered "
              f"across dtm buckets; using {len(cold_fens)}")
        print("  NOTE: the OS page cache cannot be dropped without root on "
              "this machine. By the time cold probing runs, earlier "
              "operations (mine(), the warm probe above) have already "
              "touched large parts of both files, so these numbers mostly "
              "isolate per-probe CPU cost (board decode + decompression on "
              "a fresh Tablebase, no reuse across positions in the "
              "reader's own block cache) rather than real cold-disk "
              "latency. Read this as directional, not a disk-I/O "
              "benchmark.")
        raw_cold = cold_probe_ns(raw_dir, cold_fens)
        comp_cold = cold_probe_ns(comp_dir, cold_fens)
        raw_cold_stats = summarize("raw       ", raw_cold)
        comp_cold_stats = summarize("compressed", comp_cold)
        cold_ratio = comp_cold_stats["median_ns"] / raw_cold_stats["median_ns"]
        print(f"  compressed/raw median ratio: {cold_ratio:.3f}x "
              f"(informational -- not one of the three gate conditions)")
        results["cold_probe"] = {"pool_size": pool_size, "n": len(cold_fens),
                                  "raw": raw_cold_stats,
                                  "compressed": comp_cold_stats,
                                  "ratio": cold_ratio}
    finally:
        if not args.keep_scratch:
            shutil.rmtree(raw_dir, ignore_errors=True)
            shutil.rmtree(comp_dir, ignore_errors=True)
        else:
            print(f"\nkept scratch dirs: {raw_dir} {comp_dir}")

    if args.skip_gen:
        print("\n=== generation wall-clock: SKIPPED (--skip-gen) ===")
        results["generation"] = None
    else:
        print(f"\n=== generation wall-clock: {gen_material} "
              f"({args.gen_runs} run(s) per mode) ===")
        raw_runs = []
        comp_runs = []
        for i in range(args.gen_runs):
            dt, size = gen_wallclock_run(gen_material, args.gen_threads, False,
                                          args.keep_scratch)
            print(f"  raw        run {i + 1}: {dt:.3f}s ({size:,} bytes)")
            raw_runs.append({"seconds": dt, "bytes": size})
        for i in range(args.gen_runs):
            dt, size = gen_wallclock_run(gen_material, args.gen_threads, True,
                                          args.keep_scratch)
            print(f"  compressed run {i + 1}: {dt:.3f}s ({size:,} bytes)")
            comp_runs.append({"seconds": dt, "bytes": size})
        raw_mean = statistics.mean(r["seconds"] for r in raw_runs)
        comp_mean = statistics.mean(r["seconds"] for r in comp_runs)
        slowdown = (comp_mean - raw_mean) / raw_mean * 100
        print(f"  raw mean:        {raw_mean:.3f}s")
        print(f"  compressed mean: {comp_mean:.3f}s")
        print(f"  slowdown: {slowdown:+.1f}% (gate: no more than a few "
              f"percent slower)")
        results["generation"] = {"material": gen_material, "raw_runs": raw_runs,
                                  "compressed_runs": comp_runs,
                                  "raw_mean_s": raw_mean,
                                  "compressed_mean_s": comp_mean,
                                  "slowdown_pct": slowdown}

    print("\n=== gate summary (informational; judgment belongs in the "
          "report, not this script) ===")
    r = results.get("ratio", {}).get("ratio")
    if r is not None:
        print(f"  1. ratio >= 5x:                 {r:.2f}x -> "
              f"{'PASS' if r >= 5 else 'FAIL'}")
    w = results.get("warm_probe", {}).get("ratio")
    if w is not None:
        print(f"  2. warm probe within ~2x of raw: {w:.2f}x -> "
              f"{'PASS' if w <= 2.0 else 'FAIL'}")
    g = results.get("generation")
    if g is not None:
        s = g["slowdown_pct"]
        print(f"  3. generation slowdown small:    {s:+.1f}% -> "
              f"{'PASS (informal few-percent bar)' if s <= 5 else 'FAIL'}")

    if args.json is not None:
        args.json.write_text(json.dumps(results, indent=2))
        print(f"\nwrote {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

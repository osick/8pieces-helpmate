"""Corpus-wide summary over the .stats.json sidecars.

Pure: it takes already-parsed sidecar dicts and a catalog, and touches
neither the filesystem nor FastAPI, so the awkward cases -- a material with
no helpmate, a remote table with no sidecar -- are unit-testable without
generating a table.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Sequence

from .storage import SliceInfo

# A material where nothing is solvable stores this sentinel as max_dtm, not a
# distance. 67 of the 295 tables in the reference corpus are in that state.
DTM_UNSOLVABLE = 255

# How many entries the "deepest tables" ranking carries.
DEEPEST_N = 10


def as_int(value: Any, default: int | None = None) -> int | None:
    """int(value), or `default` when the sidecar says something else.

    Every number here comes out of a file on disk that a crashed or
    interrupted generation run may have left in any state at all. A sidecar
    carrying `"max_dtm": "deep"` (or a null, or a list) is one table's problem
    and must degrade to "this table has no usable stats" -- int() letting a
    ValueError out turned it into a 500 for the whole corpus-wide summary.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def has_helpmate(sidecar: dict[str, Any]) -> bool:
    max_dtm = as_int(sidecar.get("max_dtm"))
    if max_dtm is None or max_dtm >= DTM_UNSOLVABLE:
        return False
    hist = sidecar.get("dtm_histogram") or {}
    return any(hist.get(side) for side in ("btm", "wtm"))


def aggregate_stats(sidecars: Sequence[dict[str, Any]],
                    catalog: Iterable[SliceInfo]) -> dict[str, Any]:
    cat = list(catalog)
    by_pieces: Counter[str] = Counter(str(s.pieces) for s in cat)
    generators: Counter[str] = Counter()
    dtm: dict[str, Counter[str]] = {"btm": Counter(), "wtm": Counter()}
    uniq: dict[str, Counter[str]] = {"btm": Counter(), "wtm": Counter()}
    totals: defaultdict[str, int] = defaultdict(int)
    no_helpmate: list[str] = []
    deepest: list[dict[str, Any]] = []

    for s in sidecars:
        generators[s.get("generator_version") or "unknown"] += 1
        totals["total"] += (as_int(s.get("plane_size"), 0) or 0) * 2
        cells = s.get("cells") or {}
        for kind in ("invalid", "unsolvable"):
            side_counts = cells.get(kind) or {}
            for side in ("btm", "wtm"):
                totals[kind] += as_int(side_counts.get(side), 0) or 0

        if not has_helpmate(s):
            no_helpmate.append(str(s.get("material") or "unknown"))
            continue

        # has_helpmate() has already established that max_dtm is an int below
        # the sentinel, so this cast cannot be the one that fails.
        deepest.append({"material": s.get("material"), "max_dtm": as_int(s["max_dtm"])})
        hist = s.get("dtm_histogram") or {}
        for side in ("btm", "wtm"):
            for key, n in (hist.get(side) or {}).items():
                dtm[side][key] += as_int(n, 0) or 0
            # The per-distance breakdown does not survive aggregation; the
            # client buckets over every distance anyway. Collapsing under one
            # synthetic key keeps the nested SHAPE the reader expects.
            for per_dtm in (s.get("uniqueness") or {}).get(side, {}).values():
                for key, n in (per_dtm or {}).items():
                    uniq[side][key] += as_int(n, 0) or 0

    totals["solvable"] = totals["total"] - totals["invalid"] - totals["unsolvable"]
    deepest.sort(key=lambda d: (-d["max_dtm"], str(d["material"])))

    return {
        "tables": len(cat),
        "tables_by_pieces": dict(sorted(by_pieces.items())),
        "tables_without_stats": len(cat) - len(sidecars),
        "size_bytes": sum(s.size_bytes for s in cat),
        "cells": {k: totals[k] for k in ("solvable", "unsolvable", "invalid", "total")},
        "dtm_histogram": {side: dict(dtm[side]) for side in ("btm", "wtm")},
        "uniqueness": {side: ({"all": dict(uniq[side])} if uniq[side] else {})
                       for side in ("btm", "wtm")},
        "max_dtm": deepest[0]["max_dtm"] if deepest else None,
        "deepest": deepest[:DEEPEST_N],
        "no_helpmate": sorted(no_helpmate),
        "generators": dict(generators),
    }

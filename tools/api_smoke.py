#!/usr/bin/env python3
"""End-to-end smoke test for a running helpmate API server.

Exercises every /v1 route against a live server and checks the response
shapes, the error envelope, and (when a KQvk table is served) the known
golden values. Standard library only -- no pytest, no requests.

    helpmate-server --tables /path/to/tables &
    python3 tools/api_smoke.py --url http://127.0.0.1:8642

Exit status: 0 all checks passed, 1 one or more failed, 2 server unreachable.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# A KQvk position whose values are pinned by the C++, Python and CLI test
# suites alike: Black to move, mate in one help-move, four distinct optimal
# lines (Kh6 allows Qg6#/Qh1#/Qh2#, Kh8 allows Qg7#).
GOLDEN_FEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"
UNSOLVABLE_FEN = "8/8/8/8/8/4k3/8/4K3 w - - 0 1"  # bare kings: never a mate

_passed = 0
_failed: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    global _passed
    if condition:
        _passed += 1
        print(f"  ok   {name}")
    else:
        _failed.append(name)
        print(f"  FAIL {name}{': ' + detail if detail else ''}")
    return condition


def get(url: str, path: str, timeout: float = 30.0, **params):
    """GET path; returns (status, parsed_json_or_text)."""
    if params:
        path = f"{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url.rstrip("/") + path)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:                       # 4xx/5xx
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body


def is_envelope(body) -> bool:
    return (
        isinstance(body, dict)
        and isinstance(body.get("error"), dict)
        and {"code", "message"} <= set(body["error"])
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://127.0.0.1:8642",
                   help="base URL of a running helpmate-server")
    p.add_argument("--material", default=None,
                   help="material to exercise probe/mine against "
                        "(default: KQvk if served, else the first catalog entry)")
    p.add_argument("--fetch-timeout", type=float, default=0.0,
                   help="seconds to keep polling a 202-fetching response "
                        "(remote tables download in the background; 0 = don't wait)")
    a = p.parse_args(argv)

    print(f"helpmate API smoke test against {a.url}")

    # --- health ------------------------------------------------------------
    print("\n[health]")
    try:
        status, body = get(a.url, "/v1/health", timeout=10)
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  server unreachable: {e}")
        return 2
    check("GET /v1/health -> 200", status == 200, str(status))
    check("health reports status/version", isinstance(body, dict)
          and body.get("status") == "ok" and bool(body.get("version")), repr(body))
    n_local = body.get("tables_local", 0)
    n_remote = body.get("tables_remote", 0)
    print(f"       version {body.get('version')}, "
          f"{n_local} local / {n_remote} remote table(s)")

    # --- catalog -----------------------------------------------------------
    print("\n[catalog]")
    status, body = get(a.url, "/v1/materials")
    check("GET /v1/materials -> 200", status == 200, str(status))
    materials = {m["material"]: m for m in body.get("materials", [])} \
        if isinstance(body, dict) else {}
    check("catalog is non-empty", bool(materials),
          "no tables served -- start the server with --tables or --hf-repo")
    if not materials:
        return report()
    check("catalog entries carry pieces/size/location",
          all({"pieces", "size_bytes", "location"} <= set(m) for m in materials.values()))
    print(f"       {', '.join(sorted(materials)[:8])}"
          f"{' ...' if len(materials) > 8 else ''}")

    material = a.material or ("KQvk" if "KQvk" in materials else sorted(materials)[0])
    print(f"       exercising material: {material}")

    # --- stats -------------------------------------------------------------
    print("\n[stats]")
    status, body = get(a.url, f"/v1/materials/{material}/stats")
    if status == 202:
        status, body = await_fetch(a, f"/v1/materials/{material}/stats", body)
    check(f"GET /v1/materials/{material}/stats -> 200", status == 200, str(status))
    check("stats carries material/max_dtm/dtm_histogram",
          isinstance(body, dict) and {"material", "max_dtm", "dtm_histogram"} <= set(body),
          repr(body)[:120])

    # --- probe / line (golden values only for KQvk) ------------------------
    print("\n[probe & line]")
    if material == "KQvk":
        status, body = get(a.url, "/v1/probe", fen=GOLDEN_FEN)
        check("probe golden -> 200", status == 200, str(status))
        check("probe golden dtm=2 count=4 notation=h#1",
              isinstance(body, dict) and (body.get("dtm"), body.get("count"),
                                          body.get("notation")) == (2, 4, "h#1"),
              repr(body))
        status, body = get(a.url, "/v1/line", fen=GOLDEN_FEN)
        check("line golden -> [['Kh6', 'Qh2#']]",
              status == 200 and body.get("lines") == [["Kh6", "Qh2#"]], repr(body))
        status, body = get(a.url, "/v1/line", fen=GOLDEN_FEN, all="true")
        check("line ?all=true -> 4 optimal lines",
              status == 200 and len(body.get("lines", [])) == 4, repr(body)[:120])
        status, body = get(a.url, "/v1/probe", fen=UNSOLVABLE_FEN)
        check("probe unsolvable -> {'solvable': false}",
              status == 200 and body == {"solvable": False}, repr(body))
    else:
        # No golden values for an arbitrary material: mine one position and
        # verify probe agrees with what mining claimed.
        status, body = get(a.url, "/v1/mine", material=material, dtm=2, max=1, timeout=60)
        fens = body.get("fens", []) if isinstance(body, dict) else []
        if check("mine yields a sample position", status == 200 and bool(fens),
                 repr(body)[:120]):
            status, probed = get(a.url, "/v1/probe", fen=fens[0])
            check("probe of mined position agrees (dtm=2)",
                  status == 200 and probed.get("dtm") == 2, repr(probed))
            status, lines = get(a.url, "/v1/line", fen=fens[0])
            check("line of mined position is non-empty",
                  status == 200 and bool(lines.get("lines")), repr(lines)[:120])

    # --- mine caps ---------------------------------------------------------
    print("\n[mine]")
    status, body = get(a.url, "/v1/mine", material=material, dtm=2, max=3, timeout=60)
    check("GET /v1/mine -> 200", status == 200, str(status))
    check("mine returns fens + truncated flag",
          isinstance(body, dict) and isinstance(body.get("fens"), list)
          and isinstance(body.get("truncated"), bool), repr(body)[:120])
    check("mine respects ?max", len(body.get("fens", [])) <= 3,
          f"got {len(body.get('fens', []))}")

    # --- error contract ----------------------------------------------------
    print("\n[errors]")
    status, body = get(a.url, "/v1/probe", fen="garbage")
    check("invalid FEN -> 400 envelope",
          status == 400 and is_envelope(body), f"{status} {body!r}"[:120])
    status, body = get(a.url, "/v1/probe")
    check("missing parameter -> 400 envelope",
          status == 400 and is_envelope(body), f"{status} {body!r}"[:120])
    status, body = get(a.url, "/v1/mine", material="../etc/passwd", dtm=2)
    check("path traversal in material -> 400 envelope",
          status == 400 and is_envelope(body), f"{status} {body!r}"[:120])
    status, body = get(a.url, "/v1/materials/KQQQQvk/stats")
    check("unknown material -> 404 envelope with a gen hint",
          status == 404 and is_envelope(body)
          and "helpmate gen" in (body["error"].get("hint") or ""),
          f"{status} {body!r}"[:120])
    status, body = get(a.url, "/v1/nonexistent")
    check("unknown route -> 404 envelope", status == 404 and is_envelope(body),
          f"{status} {body!r}"[:120])

    return report()


def await_fetch(a, path: str, body):
    """Poll a 202-fetching response until it resolves (or give up)."""
    material = body.get("material") if isinstance(body, dict) else "?"
    if a.fetch_timeout <= 0:
        print(f"       {material}: server is fetching it from the remote; "
              f"re-run with --fetch-timeout N to wait")
        return 202, body
    print(f"       {material}: fetching from remote, waiting up to "
          f"{a.fetch_timeout:.0f}s ...")
    deadline = time.monotonic() + a.fetch_timeout
    while time.monotonic() < deadline:
        time.sleep(2)
        status, body = get(a.url, path)
        if status != 202:
            return status, body
    return 202, body


def report() -> int:
    print(f"\n{_passed} passed, {len(_failed)} failed")
    for name in _failed:
        print(f"  - {name}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations
import re
from pathlib import Path
from typing import Optional
import helpmate
from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from . import __version__
from .storage import ChainSource

_MATERIAL_RE = re.compile(r"^[KQRBNP]+v[kqrbnp]+$")

def error_json(code: str, message: str, hint: str | None = None) -> dict:
    return {"error": {"code": code, "message": message, "hint": hint}}

def _tb(chain: ChainSource, material_dir) -> helpmate.Tablebase:
    return helpmate.Tablebase(str(material_dir))

def _resolve_web_root(explicit: str | None) -> Optional[Path]:
    """Where the dashboard's static files live, or None to serve no dashboard.

    Order: an explicit --web-root (a hard error if wrong, because the user
    named it), then the installed helpmate-web package, then the source
    checkout. Locating it by import means a wheel, an editable install and a
    container all answer the same way -- the previous version guessed between
    two filesystem layouts and silently served nothing when it guessed wrong.
    """
    if explicit is not None:
        p = Path(explicit)
        if not p.is_dir():
            raise ValueError(f"--web-root is not a directory: {p}")
        return p
    try:
        import helpmate_web
        packaged = helpmate_web.static_dir()
        if packaged.is_dir():
            return packaged
    except ImportError:
        pass
    # parents[2] is src/packages/ -- app.py lives at
    # src/packages/api/helpmate_server/app.py in a source checkout.
    checkout = Path(__file__).resolve().parents[2] / "web" / "helpmate_web" / "static"
    return checkout if checkout.is_dir() else None


def create_app(chain: ChainSource, mine_cap: int = 1000,
               mine_timeout: float = 30.0, web_root: str | None = None,
               serve_web: bool = True) -> FastAPI:
    app = FastAPI(title="helpmate API", version=__version__)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        # Typed C++ errors (GeneratorLookupError etc.) carry material+FEN+cell
        # context in their message by design — surface it (spec: 500 + diagnostic).
        return JSONResponse(status_code=500,
                            content=error_json("internal", str(exc)))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc: StarletteHTTPException):
        # Framework-generated responses (unmatched routes, disallowed methods)
        # must also carry the contract envelope, not Starlette's {"detail": ...}.
        code = {405: "method_not_allowed", 404: "not_found"}.get(
            exc.status_code, "http_error")
        return JSONResponse(status_code=exc.status_code,
                            content=error_json(code, str(exc.detail)))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc: RequestValidationError):
        # Missing/malformed query params (e.g. /v1/probe with no fen, or
        # /v1/mine?dtm=notanint) raise this instead of StarletteHTTPException,
        # so it needs its own handler to keep the envelope contract intact.
        message = "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return JSONResponse(status_code=400,
                            content=error_json("invalid_request", message))

    def unknown(material: str) -> JSONResponse:
        return JSONResponse(status_code=404, content=error_json(
            "unknown_material", f"no table for material '{material}'",
            hint=f"generate it with: helpmate gen {material} --tables <dir>"))

    def _resolve_or_response(material: str):
        if not _MATERIAL_RE.match(material):
            return None, JSONResponse(status_code=400, content=error_json(
                "invalid_material", f"invalid material '{material}'"))
        kind, val = chain.status(material)
        if kind in ("local", "cached"):
            return val, None
        if kind == "remote":
            assert chain.remote is not None   # status() returns "remote" only when it is set
            chain.remote.start_fetch(material)
            return None, JSONResponse(status_code=202, content={
                "status": "fetching", "material": material,
                "size_bytes": val.size_bytes})
        if kind == "fetching":
            return None, JSONResponse(status_code=202, content={
                "status": "fetching", "material": material})
        if kind == "failed":
            # Make the hint below truthful: actually re-trigger the download
            # now, so this response reports the last (failed) attempt
            # honestly while the *next* request already sees "fetching".
            if chain.remote is not None:
                chain.remote.start_fetch(material)
            return None, JSONResponse(status_code=502, content=error_json(
                "fetch_failed", f"download of '{material}' failed",
                hint="check server logs; retry triggers a new download"))
        return None, unknown(material)

    @app.get("/v1/health")
    def health():
        cat = chain.catalog()
        return {"status": "ok", "version": __version__,
                "mine_timeout": mine_timeout,
                "tables_local": sum(1 for s in cat if s.location in ("local", "cached")),
                "tables_remote": sum(1 for s in cat if s.location == "remote")}

    @app.get("/v1/materials")
    def materials():
        return {"materials": [vars(s) for s in chain.catalog()]}

    @app.get("/v1/themes")
    def themes_list():
        # Served from the core registry so the dashboard never hard-codes a
        # theme list that can drift from the build it is talking to.
        return {"themes": helpmate.themes()}

    @app.get("/v1/materials/{name}/stats")
    def stats(name: str):
        d, resp = _resolve_or_response(name)
        if resp is not None:
            return resp
        return _tb(chain, d).stats(name)

    def _dir_for_fen(fen: str):
        # The FEN's board field determines the material, which names the table.
        parts = fen.split()
        if not parts:
            raise ValueError("empty FEN")
        board = parts[0]
        white = "".join(sorted((c for c in board if c.isalpha() and c.isupper()),
                               key="KQRBNP".index))
        black = "".join(sorted((c.upper() for c in board if c.isalpha() and c.islower()),
                               key="KQRBNP".index))
        return white + "v" + black.lower()

    def h_notation(dtm: int) -> str:
        # dtm plies; black-to-move depths are even (h#n = 2n plies).
        return f"h#{dtm // 2}" if dtm % 2 == 0 else f"h#{dtm // 2}.5"

    @app.get("/v1/probe")
    def probe(fen: str, themes: bool = False):
        material = None
        try:
            material = _dir_for_fen(fen)
            flipped_mat = material.split("v")[1].upper() + "v" + material.split("v")[0].lower()
            d = chain.resolve(material) or chain.resolve(flipped_mat)
            if d is None:
                d, resp = _resolve_or_response(material)
                if resp is not None:
                    return resp
            tb = _tb(chain, d)
            res = tb.probe(fen)
        except helpmate.MissingTableError:
            return unknown(material or fen)
        except ValueError as e:
            return JSONResponse(status_code=400,
                                content=error_json("invalid_fen", str(e)))
        if res is None:
            return {"solvable": False, "material": material}
        dtm, count, flipped = res
        # The table that DID THE WORK, which is the mirrored material whenever
        # the C++ layer answered by flipping colours. Deriving this client-side
        # from the FEN would be wrong in exactly the case that matters.
        out = {"dtm": dtm, "count": count, "flipped": flipped,
               "material": flipped_mat if flipped else material,
               "notation": h_notation(dtm)}
        if themes:
            # Opt-in: detection forces solution enumeration, and /v1/probe is
            # on the dashboard's hot path.
            if flipped:
                # tb.solutions(fen, ...) walks the position AS QUERIED. probe()
                # only answered by colour-flipping to the OTHER material's
                # table; that table cannot answer a solutions() walk of the
                # original (unflipped) FEN -- it throws MissingTableError,
                # turning a working probe into a 500. Flipping the position
                # ourselves and detecting on THAT is not a fix either: the
                # mate detectors are hard-coded to the black king, so the
                # colour-labelled themes (single-piece:white/:black,
                # excelsior:white/:black) would come out swapped -- a wrong
                # answer dressed as a right one. So: stay 200, report themes
                # as unavailable (None, distinct from "no themes found" = []),
                # and say why in a sibling field.
                out["themes"] = None
                out["themes_note"] = ("themes unavailable: colors were flipped to find a "
                                       "table. The mate detectors are hard-coded to the black "
                                       "king, so colour-labelled themes would come out swapped; "
                                       "re-run with the colours of the position exchanged to get "
                                       "a correct answer.")
            else:
                try:
                    out["themes"] = tb.themes(fen)
                    if count >= 255:
                        # Saturated (count == 255, the stored cap): tb.themes()
                        # falls back to detecting from the first 100 solutions
                        # only, same as `probe --themes`'s CLI note. On a
                        # saturated position that list is representative-
                        # dependent, not merely incomplete -- two mirror-image
                        # FENs of the same position class can enumerate a
                        # different first 100 and so report different themes
                        # (e.g. `pendulum` present on one, absent on the
                        # other), while full enumeration would report it for
                        # both. Say so, the same way the colour-flip branch
                        # above does.
                        out["themes_note"] = (
                            "this position's solution count is saturated (255+); themes "
                            "were detected from the first 100 solutions only, and the "
                            "list may differ between mirror-image representatives of the "
                            "same position.")
                except helpmate.MissingTableError:
                    # solutions() (which detection forces) calls value_of() on
                    # every legal child move, including captures/promotions
                    # into material this table set doesn't have -- exactly the
                    # partial-table-set case /v1/line and a themes-less
                    # /v1/probe already answer with 404, not 500. Match them.
                    return unknown(material or fen)
                except ValueError as e:
                    return JSONResponse(status_code=400,
                                        content=error_json("invalid_fen", str(e)))
        return out

    @app.get("/v1/line")
    def line(fen: str, all: bool = False):
        material = None
        try:
            material = _dir_for_fen(fen)
            d, resp = _resolve_or_response(material)
            if resp is not None:
                return resp
            tb = _tb(chain, d)
            lines = tb.lines(fen) if all else [tb.line(fen)]
        except helpmate.MissingTableError:
            return unknown(material or fen)
        except ValueError as e:
            return JSONResponse(status_code=400,
                                content=error_json("invalid_fen", str(e)))
        return {"lines": lines}

    @app.get("/v1/moves")
    def moves(fen: str):
        material = None
        try:
            material = _dir_for_fen(fen)
            flipped = material.split("v")[1].upper() + "v" + material.split("v")[0].lower()
            d = chain.resolve(material) or chain.resolve(flipped)
            if d is None:
                d, resp = _resolve_or_response(material)
                if resp is not None:
                    return resp
            tb = _tb(chain, d)
            res = tb.probe(fen)
            raw = tb.moves(fen)
        except helpmate.MissingTableError:
            return unknown(material or fen)
        except ValueError as e:
            return JSONResponse(status_code=400,
                                content=error_json("invalid_fen", str(e)))
        out = []
        for m in raw:
            out.append({**m,
                        "notation": h_notation(m["dtm"]) if m["solvable"] else None})
        if res is None:
            return {"fen": fen, "solvable": False, "material": material, "moves": out}
        dtm, count, flip = res
        return {"fen": fen, "dtm": dtm, "count": count, "notation": h_notation(dtm),
                "flipped": flip, "material": flipped if flip else material,
                "moves": out}

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
    pool = ThreadPoolExecutor(max_workers=2)

    @app.get("/v1/mine")
    def mine(material: str, dtm: int, count: int = -1, max: int = 100,
             starts: Optional[int] = None, ends: Optional[int] = None,
             theme: list[str] = Query(default=[])):
        for name, val in (("starts", starts), ("ends", ends)):
            if val is None:
                continue
            if val < 1:
                return JSONResponse(status_code=400, content=error_json(
                    "invalid_filter", f"{name} must be at least 1"))
            if count >= 0 and val > count:
                return JSONResponse(status_code=400, content=error_json(
                    "invalid_filter",
                    f"{name}={val} cannot exceed count={count}",
                    hint="a position with N solutions has at most N distinct "
                         "starting or mating moves"))
        known = {t["name"] for t in helpmate.themes()}
        for name in theme:
            if name not in known:
                return JSONResponse(status_code=400, content=error_json(
                    "invalid_theme", f"unknown theme: {name}",
                    hint="valid themes: " + ", ".join(t["name"] for t in helpmate.themes())))
        starts = -1 if starts is None else starts
        ends = -1 if ends is None else ends
        d, resp = _resolve_or_response(material)
        if resp is not None:
            return resp
        clamped = min(max, mine_cap)
        if mine_timeout <= 0:
            # A non-positive budget means "don't wait at all" — for a fast
            # in-process call, a real ThreadPoolExecutor+timeout(0) race can
            # resolve either way depending on OS scheduling, so short-circuit
            # deterministically instead of racing.
            return {"fens": [], "truncated": True, "note": "timeout",
                    "skipped_saturated": 0}
        fut = pool.submit(_tb(chain, d).mine_with_stats, material, dtm, count,
                          clamped + 1, starts, ends, theme)
        try:
            fens, skipped = fut.result(timeout=mine_timeout)
        except FutTimeout:
            return {"fens": [], "truncated": True, "note": "timeout",
                    "skipped_saturated": 0}
        truncated = len(fens) > clamped
        return {"fens": fens[:clamped], "truncated": truncated,
                "skipped_saturated": int(skipped)}

    # Dashboard. Mounted last so /v1 routes keep priority; html=True serves
    # index.html for "/".
    root = _resolve_web_root(web_root) if serve_web else None
    if root is not None:
        app.mount("/", StaticFiles(directory=str(root), html=True), name="web")

    return app

from __future__ import annotations
import re
from typing import Optional
import helpmate
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from . import __version__
from .storage import ChainSource

_MATERIAL_RE = re.compile(r"^[KQRBNP]+v[kqrbnp]+$")

def error_json(code: str, message: str, hint: str | None = None) -> dict:
    return {"error": {"code": code, "message": message, "hint": hint}}

def _tb(chain: ChainSource, material_dir) -> helpmate.Tablebase:
    return helpmate.Tablebase(str(material_dir))

def create_app(chain: ChainSource, mine_cap: int = 1000,
               mine_timeout: float = 30.0) -> FastAPI:
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
                "tables_local": sum(1 for s in cat if s.location in ("local", "cached")),
                "tables_remote": sum(1 for s in cat if s.location == "remote")}

    @app.get("/v1/materials")
    def materials():
        return {"materials": [vars(s) for s in chain.catalog()]}

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
    def probe(fen: str):
        material = None
        try:
            material = _dir_for_fen(fen)
            flipped = material.split("v")[1].upper() + "v" + material.split("v")[0].lower()
            d = chain.resolve(material) or chain.resolve(flipped)
            if d is None:
                d, resp = _resolve_or_response(material)
                if resp is not None:
                    return resp
            res = _tb(chain, d).probe(fen)
        except helpmate.MissingTableError:
            return unknown(material or fen)
        except ValueError as e:
            return JSONResponse(status_code=400,
                                content=error_json("invalid_fen", str(e)))
        if res is None:
            return {"solvable": False}
        dtm, count, flipped = res
        return {"dtm": dtm, "count": count, "flipped": flipped,
                "notation": h_notation(dtm)}

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
            return {"fen": fen, "solvable": False, "moves": out}
        dtm, count, flip = res
        return {"fen": fen, "dtm": dtm, "count": count, "notation": h_notation(dtm),
                "flipped": flip, "moves": out}

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
    pool = ThreadPoolExecutor(max_workers=2)

    @app.get("/v1/mine")
    def mine(material: str, dtm: int, count: int = -1, max: int = 100,
             starts: Optional[int] = None, ends: Optional[int] = None):
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
                          clamped + 1, starts, ends)
        try:
            fens, skipped = fut.result(timeout=mine_timeout)
        except FutTimeout:
            return {"fens": [], "truncated": True, "note": "timeout",
                    "skipped_saturated": 0}
        truncated = len(fens) > clamped
        return {"fens": fens[:clamped], "truncated": truncated,
                "skipped_saturated": int(skipped)}

    return app

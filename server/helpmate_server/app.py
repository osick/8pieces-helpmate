from __future__ import annotations
import helpmate
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from . import __version__
from .storage import ChainSource

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

    def unknown(material: str) -> JSONResponse:
        return JSONResponse(status_code=404, content=error_json(
            "unknown_material", f"no table for material '{material}'",
            hint=f"generate it with: helpmate gen {material} --tables <dir>"))

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
        d = chain.resolve(name)
        if d is None:
            return unknown(name)
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
            d = chain.resolve(material) or chain.resolve(
                material.split("v")[1].upper() + "v" + material.split("v")[0].lower())
            if d is None:
                return unknown(material)
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
            d = chain.resolve(material)
            if d is None:
                return unknown(material)
            tb = _tb(chain, d)
            lines = tb.lines(fen) if all else [tb.line(fen)]
        except helpmate.MissingTableError:
            return unknown(material or fen)
        except ValueError as e:
            return JSONResponse(status_code=400,
                                content=error_json("invalid_fen", str(e)))
        return {"lines": lines}

    return app

from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

@dataclass
class SliceInfo:
    material: str
    pieces: int
    size_bytes: int
    max_dtm: int | None
    cells: int | None
    location: str  # "local" | "remote" | "cached"

def _piece_count(material: str) -> int:
    return sum(1 for c in material if c != "v")

def _info_from_files(hm: Path, location: str) -> SliceInfo:
    material = hm.name[: -len(".hm")]
    max_dtm = cells = None
    sidecar = hm.with_name(material + ".stats.json")
    if sidecar.exists():
        s = json.loads(sidecar.read_text())
        max_dtm, cells = s.get("max_dtm"), s.get("plane_size")
    return SliceInfo(material, _piece_count(material), hm.stat().st_size,
                     max_dtm, cells, location)

class LocalDir:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def catalog(self) -> list[SliceInfo]:
        return sorted((_info_from_files(hm, "local")
                       for hm in self.path.glob("*.hm")),
                      key=lambda s: s.material)

    def resolve(self, material: str) -> Path | None:
        return self.path if (self.path / f"{material}.hm").exists() else None

class ChainSource:
    def __init__(self, locals_: list[LocalDir], remote=None):
        self.locals = locals_
        self.remote = remote  # Task 4

    def catalog(self) -> list[SliceInfo]:
        seen: dict[str, SliceInfo] = {}
        for src in self.locals:
            for s in src.catalog():
                seen.setdefault(s.material, s)
        if self.remote is not None:
            for s in self.remote.catalog():
                seen.setdefault(s.material, s)
        return sorted(seen.values(), key=lambda s: s.material)

    def resolve(self, material: str) -> Path | None:
        for src in self.locals:
            hit = src.resolve(material)
            if hit is not None:
                return hit
        return None

    def status(self, material: str):
        hit = self.resolve(material)
        if hit is not None:
            return ("local", hit)
        return ("unknown", None)  # remote states: Task 4

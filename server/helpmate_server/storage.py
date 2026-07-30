from __future__ import annotations
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .manifest import verify_file

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

def _safe_material(material: str) -> bool:
    # Defense-in-depth: the API layer already rejects malformed material
    # names, but this guards direct callers too against path traversal via
    # "/", "\\", or "..".
    return "/" not in material and "\\" not in material and ".." not in material

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
        if not _safe_material(material):
            return None
        return self.path if (self.path / f"{material}.hm").exists() else None

class RemoteHub(Protocol):
    def fetch_manifest(self) -> dict: ...
    def download(self, filename: str, dest_dir: Path) -> Path: ...

class HFHub:
    """Hugging Face dataset hub. Network I/O only — kept thin, no unit tests
    (manual acceptance covers it)."""
    def __init__(self, repo_id: str):
        self.repo_id = repo_id
    def fetch_manifest(self) -> dict:
        import json as _json
        from huggingface_hub import hf_hub_download
        p = hf_hub_download(self.repo_id, "manifest.json", repo_type="dataset")
        return _json.loads(Path(p).read_text())
    def download(self, filename: str, dest_dir: Path) -> Path:
        from huggingface_hub import hf_hub_download
        p = hf_hub_download(self.repo_id, filename, repo_type="dataset",
                            local_dir=dest_dir)
        return Path(p)

class RemoteSource:
    def __init__(self, hub: RemoteHub, cache_dir: str | Path):
        self.hub = hub
        self.cache_dir = Path(cache_dir)
        self._manifest: dict | None = None
        self._states: dict[str, str] = {}
        self._verified: set[str] = set()
        self._lock = threading.Lock()

    def manifest(self) -> dict:
        with self._lock:
            if self._manifest is None:
                self._manifest = self.hub.fetch_manifest()
            return self._manifest

    def catalog(self) -> list[SliceInfo]:
        out = []
        for name, entry in self.manifest()["files"].items():
            if not name.endswith(".hm"):
                continue
            material = name[: -len(".hm")]
            out.append(SliceInfo(material, _piece_count(material),
                                 entry["size"], None, None, "remote"))
        return sorted(out, key=lambda s: s.material)

    def _cleanup_cache_files(self, material: str) -> None:
        if not _safe_material(material):
            return
        (self.cache_dir / f"{material}.hm").unlink(missing_ok=True)
        (self.cache_dir / f"{material}.stats.json").unlink(missing_ok=True)

    def fetch_state(self, material: str) -> str:
        if not _safe_material(material):
            return "absent"
        with self._lock:
            st = self._states.get(material)
        if st in ("fetching", "failed"):
            return st
        hm_path = self.cache_dir / f"{material}.hm"
        if not hm_path.exists():
            return "absent"
        with self._lock:
            already_verified = material in self._verified
        if already_verified:
            return "cached"
        # Cheap O(1) integrity check: compare on-disk size against the
        # manifest (full sha256 verification only ever happens at
        # download time — files can be tens of GB).
        try:
            entry = self.manifest()["files"][f"{material}.hm"]
            expected_size = entry["size"]
        except Exception:
            # Manifest unavailable/unparseable: fall back to existence-only
            # behavior, and do NOT cache this as verified.
            return "cached"
        if hm_path.stat().st_size == expected_size:
            with self._lock:
                self._verified.add(material)
            return "cached"
        self._cleanup_cache_files(material)
        return "absent"

    def start_fetch(self, material: str) -> None:
        if self.fetch_state(material) in ("fetching", "cached"):
            return
        with self._lock:
            if self._states.get(material) == "fetching":
                return
            self._states[material] = "fetching"
        threading.Thread(target=self._fetch, args=(material,), daemon=True).start()

    def _fetch(self, material: str) -> None:
        try:
            m = self.manifest()
            for name in (f"{material}.hm", f"{material}.stats.json"):
                if name not in m["files"]:
                    continue
                p = self.hub.download(name, self.cache_dir)
                if not verify_file(p, m):
                    p.unlink(missing_ok=True)
                    raise IOError(f"sha256 mismatch for {name}")
            with self._lock:
                self._states[material] = "done"
        except Exception:
            self._cleanup_cache_files(material)
            with self._lock:
                self._states[material] = "failed"

class ChainSource:
    def __init__(self, locals_: list[LocalDir], remote: "RemoteSource | None" = None):
        self.locals = list(locals_)
        self.remote = remote

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
        if self.remote is not None and self.remote.fetch_state(material) == "cached":
            return self.remote.cache_dir
        return None

    def status(self, material: str):
        for src in self.locals:
            hit = src.resolve(material)
            if hit is not None:
                return ("local", hit)
        if self.remote is not None:
            st = self.remote.fetch_state(material)
            if st == "cached":
                return ("cached", self.remote.cache_dir)
            if st in ("fetching", "failed"):
                return (st, None)
            info = {s.material: s for s in self.remote.catalog()}.get(material)
            if info is not None:
                return ("remote", info)
        return ("unknown", None)

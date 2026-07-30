from __future__ import annotations
import hashlib, json
from pathlib import Path

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def build_manifest(tables_dir: Path, generator_version: str) -> dict:
    files = {}
    for pat in ("*.hm", "*.stats.json"):
        for p in sorted(Path(tables_dir).glob(pat)):
            files[p.name] = {"sha256": sha256_file(p), "size": p.stat().st_size}
    return {"schema": 1, "generator_version": generator_version, "files": files}

def write_manifest(tables_dir: Path, generator_version: str) -> Path:
    out = Path(tables_dir) / "manifest.json"
    out.write_text(json.dumps(build_manifest(tables_dir, generator_version),
                              indent=2, sort_keys=True))
    return out

def verify_file(path: Path, manifest: dict) -> bool:
    entry = manifest.get("files", {}).get(Path(path).name)
    return bool(entry) and sha256_file(path) == entry["sha256"]

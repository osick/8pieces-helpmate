from __future__ import annotations
import argparse, sys
from pathlib import Path
from .manifest import write_manifest, verify_file

def _default_hub(repo_id: str):
    from .storage import HFHub
    hub = HFHub(repo_id)

    def upload(path: Path, repo: str) -> None:
        from huggingface_hub import HfApi
        HfApi().upload_file(path_or_fileobj=str(path), path_in_repo=path.name,
                            repo_id=repo, repo_type="dataset")
    hub.upload = lambda path, repo=repo_id: upload(path, repo)  # type: ignore[attr-defined]
    return hub

def main(argv: list[str] | None = None, hub_factory=_default_hub) -> int:
    p = argparse.ArgumentParser("helpmate-tables")
    sub = p.add_subparsers(dest="cmd")
    for name in ("push", "pull"):
        s = sub.add_parser(name)
        s.add_argument("--tables", required=True, metavar="DIR")
        s.add_argument("--repo", required=True, metavar="USER/DATASET")
        s.add_argument("--material", action="append", default=[])
    a = p.parse_args(argv)
    if a.cmd is None:
        p.print_usage()
        return 2
    tables = Path(a.tables)
    if not tables.is_dir():
        print(f"error: not a directory: {tables}", file=sys.stderr)
        return 2
    hub = hub_factory(a.repo)

    if a.cmd == "push":
        gen_version = "unknown"
        for sc in sorted(tables.glob("*.stats.json")):
            import json as _json
            gen_version = _json.loads(sc.read_text()).get("generator_version",
                                                          "unknown")
            break
        manifest_path = write_manifest(tables, generator_version=gen_version)
        names = a.material or sorted({f.name[: -len(".hm")]
                                      for f in tables.glob("*.hm")})
        for mat in names:
            for f in (tables / f"{mat}.hm", tables / f"{mat}.stats.json"):
                if f.exists():
                    hub.upload(f, a.repo)
                    print(f"pushed {f.name}")
        hub.upload(manifest_path, a.repo)
        print("pushed manifest.json")
        return 0

    # pull
    manifest = hub.fetch_manifest()
    for mat in a.material:
        for name in (f"{mat}.hm", f"{mat}.stats.json"):
            if name not in manifest["files"]:
                continue
            f = hub.download(name, tables)
            if not verify_file(f, manifest):
                f.unlink(missing_ok=True)
                print(f"error: sha256 mismatch for {name}", file=sys.stderr)
                return 1
            print(f"pulled {name}")
    return 0

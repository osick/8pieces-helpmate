from __future__ import annotations
import argparse, json, sys, tempfile
from pathlib import Path
from .manifest import build_manifest, verify_file

def _default_hub(repo_id: str):
    from .storage import HFHub
    hub = HFHub(repo_id)

    def upload(path: Path, repo: str) -> None:
        from huggingface_hub import HfApi
        HfApi().upload_file(path_or_fileobj=str(path), path_in_repo=path.name,
                            repo_id=repo, repo_type="dataset")
    hub.upload = lambda path, repo=repo_id: upload(path, repo)  # type: ignore[attr-defined]

    real_fetch_manifest = hub.fetch_manifest

    def fetch_manifest():
        from huggingface_hub.utils import EntryNotFoundError, RepositoryNotFoundError
        try:
            return real_fetch_manifest()
        except (EntryNotFoundError, RepositoryNotFoundError):
            # No manifest.json yet (or the dataset repo itself doesn't exist
            # yet): treat as "remote has no manifest", not an error.
            return None
    hub.fetch_manifest = fetch_manifest  # type: ignore[method-assign]
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
        try:
            gen_version = "unknown"
            for sc in sorted(tables.glob("*.stats.json")):
                gen_version = json.loads(sc.read_text()).get("generator_version",
                                                              "unknown")
                break
            local_manifest = build_manifest(tables, gen_version)
            (tables / "manifest.json").write_text(
                json.dumps(local_manifest, indent=2, sort_keys=True))
            local_files = local_manifest["files"]
            names = a.material or sorted({f.name[: -len(".hm")]
                                          for f in tables.glob("*.hm")})

            # Fetch the remote manifest *before* uploading anything: if this
            # fails (transient network error, corrupt manifest), we must not
            # upload a manifest that forgets previously-pushed materials.
            remote_manifest = hub.fetch_manifest()
            remote_files = (dict(remote_manifest.get("files", {}))
                            if remote_manifest is not None else {})

            uploaded_names: list[str] = []
            for mat in names:
                for f in (tables / f"{mat}.hm", tables / f"{mat}.stats.json"):
                    if f.exists():
                        hub.upload(f, a.repo)
                        uploaded_names.append(f.name)
                        print(f"pushed {f.name}")

            for name in uploaded_names:
                remote_files[name] = local_files[name]
            upload_manifest = {"schema": 1, "generator_version": gen_version,
                                "files": remote_files}

            with tempfile.TemporaryDirectory() as tmpdir:
                upload_manifest_path = Path(tmpdir) / "manifest.json"
                upload_manifest_path.write_text(json.dumps(upload_manifest,
                                                            indent=2, sort_keys=True))
                hub.upload(upload_manifest_path, a.repo)
            print("pushed manifest.json")
            return 0
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    # pull
    try:
        manifest = hub.fetch_manifest()
        if manifest is None:
            print("error: remote has no manifest", file=sys.stderr)
            return 1
        materials = a.material or sorted({name[: -len(".hm")]
                                          for name in manifest.get("files", {})
                                          if name.endswith(".hm")})
        for mat in materials:
            for name in (f"{mat}.hm", f"{mat}.stats.json"):
                if name not in manifest.get("files", {}):
                    continue
                f = hub.download(name, tables)
                if not verify_file(f, manifest):
                    f.unlink(missing_ok=True)
                    print(f"error: sha256 mismatch for {name}", file=sys.stderr)
                    return 1
                print(f"pulled {name}")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0

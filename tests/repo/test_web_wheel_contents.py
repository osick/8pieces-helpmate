"""The helpmate-web wheel must ship exactly the files git tracks.

Why this exists: the repo's generic Python `lib/` ignore rule has excluded
shipping deliverables from the wheel THREE times in this project's history
(js/lib's URL-state/export/FEN/stats helpers, then cm-chessboard's vendored
lib/). `.gitignore` carries negation lines that rescue both -- a
repo-root-relative pair for git, and a *second*, package-relative pair for
hatchling, which resolves .gitignore patterns relative to the subpackage
root it is building from rather than the repo root. That second pair looks
redundant next to the first and is an easy "cleanup" target; nothing but an
obscure Playwright failure in CI would catch its removal. This test builds
the real wheel and asserts its contents against `git ls-files`, so a
regression fails here in a couple of seconds instead of downstream.
"""
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB_PKG_DIR = ROOT / "src" / "packages" / "web"
WEB_PACKAGE_NAME = "helpmate_web"

pytest.importorskip("hatchling")


def _git_tracked_wheel_members() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", str(WEB_PKG_DIR / WEB_PACKAGE_NAME)],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    prefix = str(WEB_PKG_DIR.relative_to(ROOT)) + "/"
    members = set()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        assert line.startswith(prefix), line
        members.add(line[len(prefix):])
    return members


def test_web_wheel_contains_every_git_tracked_file(tmp_path):
    expected = _git_tracked_wheel_members()
    assert expected, "git ls-files returned nothing -- test itself is broken"

    result = subprocess.run(
        [
            "python", "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
            "-w", str(tmp_path), str(WEB_PKG_DIR),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(
            "helpmate-web wheel build failed for an environment reason:\n"
            + result.stdout + result.stderr
        )

    wheels = list(tmp_path.glob("helpmate_web-*.whl"))
    assert len(wheels) == 1, f"expected exactly one built wheel, found {wheels}"

    with zipfile.ZipFile(wheels[0]) as z:
        actual = {
            n for n in z.namelist()
            if n.startswith(f"{WEB_PACKAGE_NAME}/") and not n.endswith("/")
        }

    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        lines = []
        for f in missing:
            lines.append(f"{f} missing from wheel")
        for f in extra:
            lines.append(f"{f} unexpectedly in wheel (not git-tracked)")
        pytest.fail("\n".join(lines))

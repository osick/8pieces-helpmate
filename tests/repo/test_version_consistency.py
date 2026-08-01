"""Every declared version must equal the VERSION file.

This is the one suite that is deliberately not colocated with a package: it
is a statement about the repo, not about any single package. Six places have
carried the version by hand, and two of them have been missed on a release.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYPROJECTS = [
    ROOT / "pyproject.toml",
    ROOT / "src" / "packages" / "api" / "pyproject.toml",
    ROOT / "src" / "packages" / "web" / "pyproject.toml",
]


def declared_version(pyproject: Path) -> str:
    # Deliberately not tomllib: the project declares a 3.9 floor and tomllib
    # only arrived in 3.11.
    section = pyproject.read_text().split("[project]", 1)[1]
    m = re.search(r'^version\s*=\s*"([^"]+)"', section, re.M)
    assert m, f"no [project] version in {pyproject}"
    return m.group(1)


@pytest.fixture(scope="session")
def version() -> str:
    return (ROOT / "VERSION").read_text().strip()


def test_version_file_is_a_bare_version(version):
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version


@pytest.mark.parametrize("pyproject", PYPROJECTS, ids=lambda p: p.parent.name)
def test_pyproject_matches_version_file(pyproject, version):
    if not pyproject.exists():
        pytest.skip(f"{pyproject} does not exist yet")
    assert declared_version(pyproject) == version


def test_python_bindings_match_version_file(version):
    import helpmate
    assert helpmate.__version__ == version


def test_server_matches_version_file(version):
    helpmate_server = pytest.importorskip("helpmate_server")
    assert helpmate_server.__version__ == version


def test_cli_binary_matches_version_file(version):
    exe = shutil.which("helpmate") or str(ROOT / "build" / "helpmate")
    if not Path(exe).exists():
        pytest.skip("helpmate binary not built or installed")
    out = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout
    assert version in out, out

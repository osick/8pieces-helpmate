"""Local lint/typecheck/format tool versions must match what CI pins.

Why this exists: `make lint` exited 0 locally while CI's Lint job found 46
errors, purely because CI's `pip install ruff` (unpinned) picked up 0.16.1
while the local machine had 0.15.7 -- 0.16 enabled a much larger default
rule set (import sorting, pyupgrade, blind-except, ...). .github/workflows/ci.yml
now pins ruff/mypy/clang-format exactly so CI is reproducible; this test is
the second half of that fix -- it makes the drift impossible to miss by
failing loudly (rather than "through a red PR") the moment a contributor's
local tool disagrees with the pin.

Versions are parsed from the workflow file rather than duplicated here, so
there is exactly one place to bump them.
"""
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _pinned_versions() -> dict:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text())
    env = workflow.get("env", {})
    required = {
        "ruff": "RUFF_VERSION",
        "mypy": "MYPY_VERSION",
        "clang-format": "CLANG_FORMAT_VERSION",
    }
    versions = {}
    for tool, key in required.items():
        assert key in env, f"{CI_WORKFLOW} has no top-level env.{key}"
        versions[tool] = str(env[key])
    return versions


PINNED = _pinned_versions()


def test_workflow_pins_all_three_tool_versions():
    for tool, version in PINNED.items():
        assert re.fullmatch(r"\d+(\.\d+){1,3}", version), (tool, version)


def test_ruff_version_matches_pin():
    exe = "ruff"
    import shutil
    if shutil.which(exe) is None:
        pytest.skip(f"{exe} is not installed")
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, check=False).stdout
    m = re.search(r"ruff (\S+)", out)
    assert m, out
    assert m.group(1) == PINNED["ruff"], (
        f"local ruff is {m.group(1)}, but .github/workflows/ci.yml pins "
        f"{PINNED['ruff']} -- reinstall with "
        f"`pip install ruff=={PINNED['ruff']}` or bump the pin deliberately"
    )


def test_mypy_version_matches_pin():
    import shutil
    if shutil.which("mypy") is None:
        pytest.skip("mypy is not installed")
    out = subprocess.run(
        ["python3", "-m", "mypy", "--version"], capture_output=True, text=True, check=False
    ).stdout
    m = re.search(r"mypy (\S+)", out)
    assert m, out
    assert m.group(1) == PINNED["mypy"], (
        f"local mypy is {m.group(1)}, but .github/workflows/ci.yml pins "
        f"{PINNED['mypy']} -- reinstall with "
        f"`pip install mypy=={PINNED['mypy']}` or bump the pin deliberately"
    )


def test_clang_format_version_matches_pin():
    import shutil
    if shutil.which("clang-format") is None:
        pytest.skip("clang-format is not installed")
    out = subprocess.run(
        ["clang-format", "--version"], capture_output=True, text=True, check=False
    ).stdout
    m = re.search(r"clang-format version (\S+)", out)
    assert m, out
    assert m.group(1) == PINNED["clang-format"], (
        f"local clang-format is {m.group(1)}, but .github/workflows/ci.yml pins "
        f"{PINNED['clang-format']} -- reinstall with "
        f"`pip install clang-format=={PINNED['clang-format']}` or bump the pin "
        f"deliberately"
    )

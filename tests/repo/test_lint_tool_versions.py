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

The comparison is against the installed pip DISTRIBUTION, not against
whatever binary is first on PATH. CI's Ubuntu runner ships a system
clang-format 18.1.3 from apt while the cppformat job pip-installs the
pinned 22.1.8, so a PATH-based check failed in a job that installs no
clang-format at all. What is pinned is the pip distribution, so that is
what is asserted; a job without it installed skips.
"""
import re
from importlib.metadata import PackageNotFoundError, version as dist_version
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


@pytest.mark.parametrize("tool", sorted(PINNED))
def test_installed_version_matches_pin(tool):
    try:
        installed = dist_version(tool)
    except PackageNotFoundError:
        pytest.skip(f"{tool} is not installed in this environment")
    assert installed == PINNED[tool], (
        f"installed {tool} is {installed}, but .github/workflows/ci.yml pins "
        f"{PINNED[tool]} -- reinstall with `pip install {tool}=={PINNED[tool]}` "
        f"or bump the pin deliberately"
    )

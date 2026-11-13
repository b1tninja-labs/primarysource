"""The packaging claims that only fail at install time, on somebody else's machine."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]


def _libzim_requirement() -> Requirement:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    found = [Requirement(line) for line in project["optional-dependencies"]["zim"] if line.startswith("libzim")]
    assert len(found) == 1
    return found[0]


@pytest.mark.parametrize(
    ("platform", "machine", "wanted"),
    [
        ("win32", "AMD64", True),
        ("win32", "ARM64", False),  # no wheel and no practical sdist build: install must still succeed
        ("linux", "x86_64", True),
        ("linux", "aarch64", True),
        ("darwin", "arm64", True),
    ],
)
def test_libzim_marker_excludes_only_windows_on_arm(platform: str, machine: str, wanted: bool) -> None:
    """PEP 508 has no `not`: the first version of this marker was invalid and hatchling refused to build."""
    requirement = _libzim_requirement()
    assert requirement.marker is not None
    environment = {"sys_platform": platform, "platform_machine": machine}
    assert requirement.marker.evaluate(environment) is wanted


def test_libzim_is_an_extra_and_never_a_base_dependency() -> None:
    """The core and every other collection import and run without it (PLAN.md §5.13)."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert not any("libzim" in line for line in project["dependencies"])


def test_python_floor_matches_what_libzim_supports() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["requires-python"] == ">=3.12"

"""Where the cve collection keeps its corpus: the order PLAN.md §5.8 gives, with cvelib's old settings first."""

from __future__ import annotations

from pathlib import Path

import pytest

from primarysource.cve import config


@pytest.fixture
def clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for name in ("CVELIB_HOME", "PRIMARYSOURCE_CVE_HOME", "PRIMARYSOURCE_HOME"):
        monkeypatch.delenv(name, raising=False)
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: user))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    return user


def test_cvelib_home_still_wins_over_every_other_setting(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVELIB_HOME", str(clean / "old"))
    monkeypatch.setenv("PRIMARYSOURCE_CVE_HOME", str(clean / "own"))
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(clean / "all"))
    (clean / ".cvelib").mkdir()
    assert config.home() == clean / "old"


def test_the_collection_setting_then_the_shared_one(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(clean / "all"))
    (clean / ".cvelib").mkdir()
    assert config.home() == clean / "all" / "cve"
    monkeypatch.setenv("PRIMARYSOURCE_CVE_HOME", str(clean / "own"))
    assert config.home() == clean / "own"


def test_an_existing_dot_cvelib_beats_the_per_user_default(clean: Path) -> None:
    default = config.home()
    assert default.name == "cve" and default.parent.name == "primarysource"
    (clean / ".cvelib").mkdir()
    assert config.home() == clean / ".cvelib"


def test_the_index_and_raw_directories_sit_under_the_home(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVELIB_HOME", str(clean / "h"))
    assert config.index_path() == clean / "h" / "index.sqlite"
    assert config.raw_dir() == clean / "h" / "raw"
    assert config.kernel_repo_dir() == clean / "h" / "repos" / "kernel-vulns"

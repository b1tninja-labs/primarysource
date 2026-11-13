"""Shared fixtures: an offline sample library in a path that exercises the
cross-platform cases (a space and a non-ASCII character in every path)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "library"


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """An empty library home; network forced off, no auto-init."""
    h = tmp_path / "Zoë Q" / "rfc lib"
    monkeypatch.setenv("RFCLIB_HOME", str(h))
    monkeypatch.setenv("RFCLIB_NETWORK", "offline")
    monkeypatch.delenv("RFCLIB_AUTO_INIT", raising=False)
    return h


@pytest.fixture
def library(home):
    """The sample library after `rfclib init` (catalog) with its documents
    present in the mirror but not yet indexed: the on-demand starting point."""
    from primarysource.rfc import errata, library as lib
    from primarysource.rfc.config import Paths
    from primarysource.rfc.sync import scanner
    from primarysource.rfc.sync.state import open_db

    paths = Paths.default().ensure()
    shutil.copyfile(FIXTURE / "meta" / "rfc-index.xml", paths.manifest_xml)
    shutil.copytree(FIXTURE / "mirror", paths.mirror, dirs_exist_ok=True)
    conn = open_db(paths.db)
    lib.init_catalog(conn, paths, subjects=False)
    errata.sync_bulk(conn, json.loads(
        (FIXTURE / "errata.json").read_text("utf-8")))
    scanner.scan_mirror(conn, paths.mirror)
    yield conn, paths
    conn.close()

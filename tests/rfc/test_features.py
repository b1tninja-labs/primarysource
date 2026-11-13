"""The core install must work without the optional extras: nothing in the
library, CLI or search path may import mcp / model2vec / sqlite_vec /
numpy until a feature that needs them is actually used."""

from __future__ import annotations

import subprocess
import sys

OPTIONAL = ("mcp", "model2vec", "sqlite_vec", "numpy", "tokenizers")


def test_core_imports_no_optional_packages():
    code = (
        "import sys, primarysource.rfc.cli, primarysource.rfc.views, primarysource.rfc.library, "
        "primarysource.rfc.index.hybrid, primarysource.rfc.index.search, primarysource.rfc.index.embed; "
        f"print(sorted(m for m in {OPTIONAL!r} if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True).stdout.strip()
    assert out == "[]"


def test_hybrid_search_works_without_semantic(library, monkeypatch):
    from primarysource.rfc import views
    from primarysource.rfc.index import embed

    def missing(*a, **k):
        raise RuntimeError("semantic search is an optional feature")
    monkeypatch.setattr(embed, "semantic_search", missing)
    conn, paths = library
    views.read(conn, "RFC5234", mirror_root=paths.mirror)
    out = views.search_text(conn, "ABNF rule definition")
    assert "RFC5234" in out


def test_features_are_reported():
    from primarysource.rfc.library import features
    got = features()
    assert set(got) == {"mcp", "semantic", "zim"}
    assert all(isinstance(v, bool) for v in got.values())

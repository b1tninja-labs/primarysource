"""Library lifecycle and cross-platform behaviour, against the offline
sample library (tests/fixtures/library, see scripts/make_test_fixture.py)."""

from __future__ import annotations

import re
import sqlite3

import pytest

from primarysource.rfc import views
from primarysource.rfc.config import Paths


# --------------------------------------------------------------------------
# where the library lives

def test_home_from_env(home):
    assert Paths.default().home == home


def test_home_defaults_to_platform_dir_not_cwd(monkeypatch, tmp_path):
    # primarysource.home.collection_home: an existing per-user rfclib
    # library is kept; otherwise the per-user primarysource/rfc. Never cwd.
    from primarysource.home import resolve_home
    monkeypatch.delenv("RFCLIB_HOME", raising=False)
    monkeypatch.delenv("PRIMARYSOURCE_HOME", raising=False)
    for var in ("LOCALAPPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(var, str(tmp_path / "user data"))
    monkeypatch.chdir(tmp_path)
    fresh = Paths.default().home
    assert fresh == resolve_home("primarysource") / "rfc"
    assert tmp_path / "user data" in fresh.parents or "Library" in fresh.parts
    old = resolve_home("rfclib")
    old.mkdir(parents=True)
    assert Paths.default().home == old


def test_legacy_library_in_cwd_is_reported(monkeypatch, tmp_path):
    from primarysource.rfc.config import legacy_home
    monkeypatch.delenv("RFCLIB_HOME", raising=False)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "rfclib.db").write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    assert legacy_home() == tmp_path / "data"


# --------------------------------------------------------------------------
# portable file paths

def test_file_paths_are_stored_relative(library):
    from primarysource.rfc.sync.state import file_path
    conn, paths = library
    rows = conn.execute("SELECT path FROM files").fetchall()
    assert rows
    for (stored,) in rows:
        assert "\\" not in stored and not stored.startswith("/")
        assert not re.match(r"^[A-Za-z]:", stored)
        assert file_path(conn, stored).is_file()


def test_absolute_paths_from_any_os_are_migrated(home):
    from primarysource.rfc.sync.state import open_db, set_meta
    conn = open_db(Paths.default().ensure().db)
    conn.executemany(
        "INSERT INTO files(doc_id, fmt, path) VALUES(?,?,?)",
        [("RFC1", "txt", r"D:\code\rfclibrary\data\mirror\rfc\rfc1.txt"),
         ("RFC2", "txt", "/home/mirror/rfc/rfc2.txt"),
         ("RFC3", "txt", "/elsewhere/rfc3.txt")])
    set_meta(conn, "files_paths", "")
    conn.close()
    conn = open_db(Paths.default().db)
    got = dict(conn.execute("SELECT doc_id, path FROM files"))
    assert got == {"RFC1": "rfc/rfc1.txt", "RFC2": "rfc/rfc2.txt",
                   "RFC3": "/elsewhere/rfc3.txt"}


# --------------------------------------------------------------------------
# tiers: empty -> catalog -> on demand

def test_empty_library_says_what_to_run(home):
    from primarysource.rfc.sync.state import open_db
    conn = open_db(Paths.default().ensure().db)
    for call in (lambda: views.search_text(conn, "tls"),
                 lambda: views.parse_ref(conn, "RFC9000"),
                 lambda: views.info_text(conn, "RFC9000")):
        with pytest.raises(views.RefError, match="rfclib init"):
            call()


def test_catalog_answers_without_documents(library):
    conn, _ = library
    info = views.info_text(conn, "RFC793")
    assert "OBSOLETE" in info and "current replacement: RFC9293" in info
    hits = views.search_text(conn, "transmission control protocol",
                             scope="documents")
    assert "RFC9293" in hits


def test_rfcxml_document_is_indexed_on_first_read(library):
    conn, _ = library
    assert not conn.execute(
        "SELECT 1 FROM chunk_src WHERE doc_id='RFC8651'").fetchone()
    out = views.read(conn, "RFC8651", mirror_root=library[1].mirror)
    assert "RFC 8651" in out and "§1" in out
    method = conn.execute("SELECT method FROM seg_quality WHERE "
                          "doc_id='RFC8651'").fetchone()[0]
    assert method == "rfcxml"
    page = views.read(conn, "RFC8651§1", mirror_root=library[1].mirror)
    assert re.search(r"\[§1¶\d+\]", page)


def test_txt_only_document_is_segmented_from_its_toc(library):
    conn, paths = library
    outline = views.outline(conn, "RFC5234", depth=None)
    assert "§4 ABNF Definition of ABNF" in outline
    hits = views.grep(conn, "RFC5234", r"^ *rulelist +=",
                      mirror_root=paths.mirror)
    assert re.search(r"RFC5234§4¶\d+", hits)
    code = views.read(conn, "RFC5234§4", mirror_root=paths.mirror,
                      view="code", lang="abnf")
    assert "rulelist" in code


def test_series_alias_reads_its_rfc(library):
    conn, paths = library
    out = views.read(conn, "BCP14", mirror_root=paths.mirror)
    assert out.startswith("RFC 2119 (via BCP14)")


def test_offline_fetch_is_refused_with_a_reason(library):
    conn, paths = library
    with pytest.raises(views.RefError, match="RFCLIB_NETWORK=offline"):
        views.read(conn, "RFC9293§3.1", mirror_root=paths.mirror)


def test_section_search_reports_coverage(library):
    conn, paths = library
    views.read(conn, "RFC5234", mirror_root=paths.mirror)
    out = views.search_text(conn, "ABNF rule definition")
    assert out.startswith("coverage:")
    assert "RFC5234" in out


def test_paging_by_next_ref_is_lossless(library):
    conn, paths = library
    ref = "RFC5234§4"
    r = views.parse_ref(conn, ref)
    lines = views._text(conn, r, paths.mirror)
    a, b, _sec, _t = views._scope(conn, r, len(lines))
    want = [t for _n, t in views._clean_lines(lines, a, b) if t]
    got, cur, pages = [], ref, 0
    while cur and pages < 50:
        page = views.read(conn, cur, mirror_root=paths.mirror, max_tokens=150)
        body = page.split("\n\n", 1)[1].rsplit("\n\n— ", 1)[0]
        got += [x for x in body.split("\n")
                if x and not re.fullmatch(r"\[[^\]]*\]", x)]
        m = re.search(r"— next: (\S+)", page)
        cur, pages = (m.group(1) if m else None), pages + 1
    assert pages > 1 and got == want


def test_paragraph_citation_has_anchor_and_hash(library):
    conn, paths = library
    out = views.cite(conn, "RFC8651§1¶1", mirror_root=paths.mirror)
    assert "rfc8651.html#section-1-1" in out
    assert re.search(r"span sha256:[0-9a-f]{16}", out)


def test_errata_come_from_the_bulk_feed(library):
    conn, _ = library
    out = views.errata_text(conn, "RFC5234", status="all")
    assert "errata for RFC5234" in out and "[eid" in out


# --------------------------------------------------------------------------
# filesystem helpers

def test_atomic_write_replaces_whole_file(tmp_path):
    from primarysource.rfc.fsutil import atomic_write_bytes
    dest = tmp_path / "Zoë" / "rfc9000.txt"
    atomic_write_bytes(dest, b"old")
    atomic_write_bytes(dest, b"new\x0c\n")
    assert dest.read_bytes() == b"new\x0c\n"
    assert [p.name for p in dest.parent.iterdir()] == ["rfc9000.txt"]


def test_bulk_lock_is_exclusive(tmp_path):
    from primarysource.rfc.fsutil import LockHeld, bulk_lock
    with bulk_lock(tmp_path):
        with pytest.raises(LockHeld):
            with bulk_lock(tmp_path):
                pass
    with bulk_lock(tmp_path):      # released
        pass


def test_db_waits_for_writers(library):
    conn, _ = library
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 30000
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert isinstance(conn, sqlite3.Connection)

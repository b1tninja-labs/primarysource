"""The shared FTS5 index, on invented documents only."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from primarysource import index
from primarysource.errors import LibError
from primarysource.index import Hit, Ranking
from primarysource.model import Document, Section, Unit

REBUILD = "primarysource demo index --rebuild"


def _doc(doc_id: str, *sections: tuple[str, str, str], title: str = "Invented Document") -> Document:
    return Document(
        id=doc_id,
        title=title,
        unit=Unit.PARAGRAPH,
        sections=tuple(Section(id=sid, title=heading, units=(body,)) for sid, heading, body in sections),
    )


GLOSSARY = _doc(
    "D1",
    ("1", "Gizmo framing", "A gizmo frame begins with a sprocket marker and ends with a checksum."),
    ("2", "Sprocket rules", "Each sprocket is encoded as a varint; a frame without one is rejected."),
    ("3", "Résumé of the wobble", "The wobble resumes after the gizmo yields."),
)
MANUAL = _doc(
    "D2",
    ("A", "Overview", "Nothing here mentions the framing words at all, only lanterns and kites."),
    ("B", "Lantern behaviour", "A lantern glows; a kite drifts. Sprocket appears here once."),
    title="Lantern Manual",
)


@pytest.fixture
def built(tmp_path: Path) -> Path:
    path = tmp_path / "demo.sqlite3"
    index.rebuild(path, [GLOSSARY, MANUAL], rebuild_command=REBUILD)
    return path


@pytest.fixture
def reader(built: Path) -> Iterator[sqlite3.Connection]:
    conn = index.open_read(built, rebuild_command=REBUILD)
    yield conn
    conn.close()


def _ids(result: index.SearchResult) -> list[tuple[str, str]]:
    return [(hit.doc_id, hit.section_id) for hit in result.hits]


# --- cl.index_fts5 ---------------------------------------------------------------------------------------------


def test_sections_table_is_fts5_with_the_porter_unicode61_tokenizer(reader: sqlite3.Connection) -> None:
    (sql,) = reader.execute("SELECT sql FROM sqlite_master WHERE name = 'sections_fts'").fetchone()
    assert "USING fts5" in sql and "tokenize='porter unicode61'" in sql
    assert reader.execute("SELECT count(*) FROM sections").fetchone()[0] == 5


def test_porter_stems_and_unicode61_folds_diacritics(reader: sqlite3.Connection) -> None:
    assert ("D1", "2") in _ids(index.search(reader, "encoding"))
    assert _ids(index.search(reader, "resume"))[0] == ("D1", "3")


def test_bm25_column_weights_decide_whether_a_heading_or_a_body_match_wins(reader: sqlite3.Connection) -> None:
    # "framing" is a heading word in D1§1 and a body word in D2§A.
    heading_first = index.search(reader, "framing", ranking=Ranking(title=10.0, body=1.0))
    body_first = index.search(reader, "framing", ranking=Ranking(title=0.0, body=10.0))
    assert _ids(heading_first)[0] == ("D1", "1")
    assert _ids(body_first)[0] == ("D2", "A")
    assert all(hit.score > 0 for hit in heading_first.hits)


def test_the_rank_adjust_hook_rescales_and_reorders(reader: sqlite3.Connection) -> None:
    seen: list[str] = []

    def demote_glossary(hit: Hit, query: str) -> float:
        seen.append(query)
        return 0.01 if hit.doc_id == "D1" else 1.0

    plain = index.search(reader, "sprocket")
    adjusted = index.search(reader, "sprocket", ranking=Ranking(adjust=demote_glossary))
    assert _ids(plain)[0][0] == "D1"
    assert _ids(adjusted)[0] == ("D2", "B")
    assert seen and set(seen) == {"sprocket"}


def test_reindexing_a_document_replaces_its_sections(built: Path) -> None:
    conn = index.open_write(built, rebuild_command=REBUILD)
    try:
        index.index_document(conn, _doc("D2", ("A", "Overview", "Only teapots now.")))
        assert _ids(index.search(conn, "lantern")) == []
        assert _ids(index.search(conn, "teapots")) == [("D2", "A")]
        assert conn.execute("SELECT sections FROM documents WHERE doc_id = 'D2'").fetchone()[0] == 1
        assert index.remove_document(conn, "D2")
        assert not index.remove_document(conn, "D2")
        assert _ids(index.search(conn, "teapots")) == []
    finally:
        conn.close()


# --- cl.fts_query_sanitise -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    ["set-of value", "NEAR(gizmo", "title:gizmo", "gizmo*", 'a "b', "gizmo AND", "(sprocket", "^frame", "NOT", "-x"],
)
def test_fts5_operators_in_user_text_never_raise(reader: sqlite3.Connection, query: str) -> None:
    index.search(reader, query)  # an answer or nothing, never OperationalError


def test_terms_are_quoted_and_filler_is_not_required() -> None:
    assert index.fts_query('how is the "gizmo" set-of') == '"""gizmo""" "set-of"'
    assert index.fts_query("gizmo sprocket", any_term=True) == '"gizmo" OR "sprocket"'
    assert index.fts_query("the") == '"the"'  # filler alone is still a query


def test_a_query_without_words_is_an_error_naming_the_remedy() -> None:
    with pytest.raises(LibError) as raised:
        index.fts_query(' - " ( ')
    assert raised.value.hint


# --- cl.search_relaxed -----------------------------------------------------------------------------------------


def test_every_term_is_required_first(reader: sqlite3.Connection) -> None:
    result = index.search(reader, "gizmo sprocket")
    assert not result.relaxed
    assert _ids(result) == [("D1", "1")]


def test_when_no_section_has_every_term_any_term_matches_and_says_relaxed(reader: sqlite3.Connection) -> None:
    result = index.search(reader, "glows checksum")
    assert result.relaxed
    assert set(_ids(result)) == {("D1", "1"), ("D2", "B")}


def test_nothing_matching_is_an_empty_result_not_relaxed(reader: sqlite3.Connection) -> None:
    result = index.search(reader, "zeppelin quokka")
    assert result.hits == () and not result.relaxed and result.next_start is None


def test_paging_follows_next_start(reader: sqlite3.Connection) -> None:
    first = index.search(reader, "sprocket", limit=2)
    assert len(first.hits) == 2 and first.next_start == 2
    rest = index.search(reader, "sprocket", limit=2, start=first.next_start)
    assert rest.next_start is None
    assert len(set(_ids(first)) | set(_ids(rest))) == 3


# --- cl.index_readonly_open ------------------------------------------------------------------------------------


def test_read_only_open_refuses_writes(reader: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        reader.execute("DELETE FROM documents")


def test_read_only_open_of_a_missing_index_names_the_rebuild_and_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / "absent.sqlite3"
    with pytest.raises(LibError) as raised:
        index.open_read(path, rebuild_command=REBUILD)
    assert REBUILD in raised.value.hint
    assert not path.exists()


def test_read_only_open_skips_schema_setup(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite3"
    sqlite3.connect(path).close()  # a database, but never set up as an index
    with pytest.raises(LibError):
        index.open_read(path, rebuild_command=REBUILD)
    check = sqlite3.connect(path)
    try:
        assert check.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
    finally:
        check.close()


def test_read_only_open_sets_a_busy_timeout(built: Path) -> None:
    conn = index.open_read(built, rebuild_command=REBUILD, busy_timeout_ms=4321)
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 4321
    finally:
        conn.close()


# --- cl.index_write_txn ----------------------------------------------------------------------------------------


def test_writer_uses_wal_and_a_busy_timeout(tmp_path: Path) -> None:
    conn = index.open_write(tmp_path / "w.sqlite3", rebuild_command=REBUILD, busy_timeout_ms=2345)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 2345
        assert conn.execute("PRAGMA user_version").fetchone()[0] == index.SCHEMA_VERSION
    finally:
        conn.close()


def test_a_second_writer_waits_for_the_lock_up_front(tmp_path: Path) -> None:
    path = tmp_path / "w.sqlite3"
    holder = index.open_write(path, rebuild_command=REBUILD)
    other = index.open_write(path, rebuild_command=REBUILD, busy_timeout_ms=50)
    try:
        holder.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            index.index_document(other, GLOSSARY)
        assert not other.in_transaction  # refused at BEGIN, before any row was touched
        holder.execute("ROLLBACK")
        assert index.index_document(other, GLOSSARY) == 3
    finally:
        holder.close()
        other.close()


def test_concurrent_writers_all_land(tmp_path: Path) -> None:
    path = tmp_path / "w.sqlite3"
    index.open_write(path, rebuild_command=REBUILD).close()
    errors: list[BaseException] = []

    def write(n: int) -> None:
        conn = index.open_write(path, rebuild_command=REBUILD)
        try:
            for round_ in range(5):
                index.index_document(conn, _doc(f"T{n}", *[(str(i), f"t{round_}", f"body {n}") for i in range(4)]))
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)
        finally:
            conn.close()

    threads = [threading.Thread(target=write, args=(n,)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    conn = index.open_read(path, rebuild_command=REBUILD)
    try:
        assert conn.execute("SELECT count(*), count(DISTINCT doc_id) FROM sections").fetchone() == (24, 6)
    finally:
        conn.close()


def test_a_failed_document_rolls_back_and_keeps_the_old_version(built: Path) -> None:
    conn = index.open_write(built, rebuild_command=REBUILD)
    broken = Document(id="D1", title="x", unit=Unit.PARAGRAPH, sections=(Section(id="1", title=None),))  # type: ignore[arg-type]
    try:
        with pytest.raises(sqlite3.IntegrityError):
            index.index_document(conn, broken)
        assert not conn.in_transaction
        assert conn.execute("SELECT count(*) FROM sections WHERE doc_id = 'D1'").fetchone()[0] == 3
    finally:
        conn.close()


def test_inside_a_callers_transaction_index_document_does_not_commit(built: Path) -> None:
    conn = index.open_write(built, rebuild_command=REBUILD)
    try:
        conn.execute("BEGIN IMMEDIATE")
        index.index_document(conn, _doc("D9", ("1", "Teapot", "spout")))
        assert conn.in_transaction
        conn.execute("ROLLBACK")
        assert conn.execute("SELECT count(*) FROM documents WHERE doc_id = 'D9'").fetchone()[0] == 0
    finally:
        conn.close()


# --- cl.index_schema_version -----------------------------------------------------------------------------------


@pytest.mark.parametrize("opener", [index.open_read, index.open_write])
def test_a_schema_version_mismatch_is_refused_with_the_rebuild_command(built: Path, opener: object) -> None:
    raw = sqlite3.connect(built)
    raw.execute(f"PRAGMA user_version = {index.SCHEMA_VERSION + 1}")
    raw.close()
    with pytest.raises(LibError) as raised:
        opener(built, rebuild_command=REBUILD)  # type: ignore[operator]
    assert REBUILD in raised.value.hint
    assert str(index.SCHEMA_VERSION + 1) in raised.value.message


@pytest.mark.parametrize("opener", [index.open_read, index.open_write])
def test_a_file_that_is_not_a_database_is_refused_with_the_rebuild_command(tmp_path: Path, opener: object) -> None:
    path = tmp_path / "junk.sqlite3"
    path.write_bytes(b"this is not sqlite" * 100)
    with pytest.raises(LibError) as raised:
        opener(path, rebuild_command=REBUILD)  # type: ignore[operator]
    assert REBUILD in raised.value.hint


def test_open_write_refuses_a_foreign_database(tmp_path: Path) -> None:
    path = tmp_path / "foreign.sqlite3"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE something_else(x)")
    raw.commit()
    raw.close()
    with pytest.raises(LibError) as raised:
        index.open_write(path, rebuild_command=REBUILD)
    assert REBUILD in raised.value.hint


# --- cl.index_atomic_rebuild -----------------------------------------------------------------------------------


def _leftovers(directory: Path, keep: str) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if not p.name.startswith(keep))


def test_rebuild_replaces_the_index_and_leaves_no_temporary_file(built: Path) -> None:
    index.rebuild(built, [_doc("N1", ("1", "Teapot", "A teapot with a spout."))], rebuild_command=REBUILD)
    conn = index.open_read(built, rebuild_command=REBUILD)
    try:
        assert _ids(index.search(conn, "teapot")) == [("N1", "1")]
        assert _ids(index.search(conn, "sprocket")) == []
    finally:
        conn.close()
    assert _leftovers(built.parent, built.name) == []


def test_readers_see_the_old_index_while_the_new_one_is_built(built: Path) -> None:
    observed: list[list[tuple[str, str]]] = []

    def documents() -> Iterator[Document]:
        yield _doc("N1", ("1", "Teapot", "A teapot."))
        conn = index.open_read(built, rebuild_command=REBUILD)
        try:
            observed.append(_ids(index.search(conn, "gizmo sprocket")))
            observed.append(_ids(index.search(conn, "teapot")))
        finally:
            conn.close()

    index.rebuild(built, documents(), rebuild_command=REBUILD)
    assert observed == [[("D1", "1")], []]


def test_a_failed_rebuild_keeps_the_old_index_and_removes_the_temporary(built: Path) -> None:
    def documents() -> Iterator[Document]:
        yield _doc("N1", ("1", "Teapot", "A teapot."))
        raise RuntimeError("the reader failed half-way")

    with pytest.raises(RuntimeError):
        index.rebuild(built, documents(), rebuild_command=REBUILD)
    conn = index.open_read(built, rebuild_command=REBUILD)
    try:
        assert _ids(index.search(conn, "gizmo sprocket")) == [("D1", "1")]
    finally:
        conn.close()
    assert _leftovers(built.parent, built.name) == []


def test_a_rebuilt_index_is_published_in_rollback_mode_and_the_next_writer_switches_to_wal(built: Path) -> None:
    raw = sqlite3.connect(built)
    try:
        assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        raw.close()
    index.open_write(built, rebuild_command=REBUILD).close()
    raw = sqlite3.connect(built)
    try:
        assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        raw.close()


def test_rebuild_refuses_while_a_reader_pins_the_old_write_ahead_log(built: Path) -> None:
    writer = index.open_write(built, rebuild_command=REBUILD)
    index.index_document(writer, _doc("W1", ("1", "Kettle", "A kettle.")))
    reader = index.open_read(built, rebuild_command=REBUILD)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM sections").fetchone()  # holds a read snapshot of the WAL
        index.index_document(writer, _doc("W2", ("1", "Pot", "A pot.")))  # frames the checkpoint cannot drop
        with pytest.raises(LibError) as raised:
            index.rebuild(
                built, [_doc("N1", ("1", "Teapot", "A teapot."))], rebuild_command=REBUILD, busy_timeout_ms=50
            )
        assert REBUILD in raised.value.hint
        reader.execute("COMMIT")
        assert _ids(index.search(reader, "kettle")) == [("W1", "1")]
    finally:
        reader.close()
        writer.close()
    assert _leftovers(built.parent, built.name) == []

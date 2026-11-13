"""The shared MCP server: `rfclib mcp --transport http`, the read-only mode
for extra stdio servers, and what happens when several connections and
processes use one library at once. Everything is offline, in a temporary
RFCLIB_HOME, on a port the OS hands out."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

DOCS = ["RFC768", "RFC2119", "RFC5234", "RFC7405", "RFC8174", "RFC8651"]


def _env(home: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("RFCLIB_")}
    env.update(RFCLIB_HOME=str(home), RFCLIB_NETWORK="offline",
               PYTHONIOENCODING="utf-8", **extra)
    return env


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _assert_sound(db: Path) -> None:
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        # external-content FTS: the index must agree with the chunks table
        conn.execute("INSERT INTO chunks_fts(chunks_fts, rank) "
                     "VALUES('integrity-check', 1)")
        ids = [r[0] for r in conn.execute("SELECT id FROM chunks")]
        assert len(ids) == len(set(ids)) and ids
    finally:
        conn.close()


# --------------------------------------------------------------------------
# the --transport option

@pytest.fixture
def run_calls(monkeypatch):
    pytest.importorskip("mcp")
    from primarysource.rfc.mcp import server
    calls: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(server.mcp, "run",
                        lambda *a, **k: calls.append((a, k)))
    return calls


def _cli(*args: str):
    from typer.testing import CliRunner

    from primarysource.rfc.cli import app
    return CliRunner().invoke(app, ["mcp", *args])


def test_stdio_is_the_default_transport(home, run_calls):
    assert _cli().exit_code == 0
    assert run_calls == [((), {"transport": "stdio"})]


def test_http_transport_binds_loopback_and_is_stateless(home, run_calls):
    res = _cli("--transport", "http", "--port", "9123")
    assert res.exit_code == 0, res.output
    (_a, kw), = run_calls
    assert kw["transport"] == "streamable-http"
    assert (kw["host"], kw["port"]) == ("127.0.0.1", 9123)
    assert kw["stateless_http"] is True and kw["json_response"] is True
    # None on loopback: the SDK then turns its Host/Origin check on
    assert kw["transport_security"] is None


def test_http_on_other_address_takes_allowed_hosts(home, run_calls):
    res = _cli("--transport", "http", "--host", "0.0.0.0",
               "--allowed-host", "localhost:*")
    assert res.exit_code == 0, res.output
    sec = run_calls[0][1]["transport_security"]
    assert sec.enable_dns_rebinding_protection
    assert sec.allowed_hosts == ["localhost:*"]
    assert "http://localhost:*" in sec.allowed_origins


def test_unknown_transport_is_refused(home, run_calls):
    assert _cli("--transport", "carrier-pigeon").exit_code == 2
    assert run_calls == []


def test_read_only_flag_sets_the_mode(home, run_calls, monkeypatch):
    monkeypatch.setenv("RFCLIB_READONLY", "")       # restored after the test
    from primarysource.rfc import config
    assert not config.read_only()
    assert _cli("--read-only").exit_code == 0
    assert config.read_only() and config.network_mode() == "offline"


# --------------------------------------------------------------------------
# a real server process, spoken to with raw JSON-RPC over HTTP

@pytest.fixture
def http_server(library):
    pytest.importorskip("mcp")
    conn, paths = library
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "primarysource.rfc", "mcp", "--transport", "http",
         "--port", str(port)],
        env=_env(paths.home), stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE)
    import httpx
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if proc.poll() is not None:
                pytest.fail("server exited: "
                            + proc.stderr.read().decode("utf-8", "replace"))
            try:
                if httpx.get(base + "/healthz", timeout=2).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.1)
        else:
            pytest.fail("server did not start")
        yield base, paths
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        proc.stderr.close()


def _rpc(base: str, method: str, params: dict, rid: int = 1,
         headers: dict | None = None):
    import httpx
    return httpx.post(
        base + "/mcp", timeout=60,
        headers={"Accept": "application/json, text/event-stream",
                 **(headers or {})},
        json={"jsonrpc": "2.0", "id": rid, "method": method,
              "params": params})


def _call(base: str, tool: str, **args) -> str:
    r = _rpc(base, "tools/call", {"name": tool, "arguments": args})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert not result["isError"], result
    return result["content"][0]["text"]


def test_http_server_answers_initialize_search_and_read(http_server):
    base, paths = http_server
    import httpx
    health = httpx.get(base + "/healthz", timeout=5).json()
    assert health["status"] == "ok" and health["documents"] > 0

    init = _rpc(base, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"}}).json()["result"]
    assert init["serverInfo"]["name"] == "rfclib"

    tools = _rpc(base, "tools/list", {}).json()["result"]["tools"]
    assert {"search", "read", "cite"} <= {t["name"] for t in tools}

    # the first read indexes the document: the server is the writer
    assert "User Datagram Protocol" in _call(base, "read", ref="RFC768")
    hits = _call(base, "search", query="pseudo header", mode="exact")
    assert "RFC768" in hits
    _assert_sound(paths.db)


def test_http_server_rejects_foreign_host_header(http_server):
    base, _ = http_server
    r = _rpc(base, "tools/list", {}, headers={"Host": "evil.example"})
    assert r.status_code == 421


def test_http_server_serves_concurrent_clients(http_server):
    """Several clients at once, each first read indexing a different RFC:
    the requests run in threads of one process and must not collide."""
    base, paths = http_server
    out: dict[str, object] = {}

    def client(doc: str) -> None:
        try:
            out[doc] = _call(base, "read", ref=doc)
        except BaseException as e:  # noqa: BLE001 - reported below
            out[doc] = e

    threads = [threading.Thread(target=client, args=(d,)) for d in DOCS]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    assert not any(t.is_alive() for t in threads), "a request hung"
    bad = {d: r for d, r in out.items() if not isinstance(r, str)}
    assert not bad, bad
    _assert_sound(paths.db)
    conn = sqlite3.connect(paths.db)
    assert conn.execute("SELECT COUNT(*) FROM chunk_src").fetchone()[0] \
        == len(DOCS)
    conn.close()


# --------------------------------------------------------------------------
# single-writer safety

def test_two_writers_do_not_pick_the_same_chunk_ids(library, monkeypatch):
    """index_doc used to read MAX(chunks.id) before its transaction began,
    so a second writer starting meanwhile chose the same new ids and failed
    with 'UNIQUE constraint failed: chunks.id'. The first writer is held
    just after that read to make the overlap certain."""
    from primarysource.rfc.index import search as ix
    from primarysource.rfc.sync.state import open_db
    _conn, paths = library
    first_reading = threading.Event()
    real = ix._doc_sections
    slow = threading.local()

    def held(*a, **k):
        if getattr(slow, "on", False):
            first_reading.set()
            time.sleep(0.6)
        return real(*a, **k)

    monkeypatch.setattr(ix, "_doc_sections", held)
    errors: list[BaseException] = []

    def writer(doc: str, hold: bool) -> None:
        slow.on = hold
        conn = open_db(paths.db)
        try:
            assert ix.index_doc(conn, doc)
        except BaseException as e:  # noqa: BLE001 - reported below
            errors.append(e)
        finally:
            conn.close()

    a = threading.Thread(target=writer, args=("RFC5234", True))
    b = threading.Thread(target=writer, args=("RFC2119", False))
    a.start()
    assert first_reading.wait(10)
    b.start()
    a.join(60)
    b.join(60)
    assert not a.is_alive() and not b.is_alive(), "writers deadlocked"
    assert not errors, errors
    _assert_sound(paths.db)


_WORKER = r"""
import sys, time
from primarysource.rfc import config, library, views
from primarysource.rfc.config import Paths
from primarysource.rfc.index import search as ix
from primarysource.rfc.sync.state import open_db

role, seconds = sys.argv[1], float(sys.argv[2])
docs = sys.argv[3:]
paths = Paths.default()
end = time.monotonic() + seconds
n = 0
while time.monotonic() < end:
    # a new connection per request, as the MCP server does
    conn = open_db(paths.db, read_only=config.read_only())
    if role == "writer":
        doc = docs[n % len(docs)]
        assert ix.index_doc(conn, doc), doc      # re-chunk: delete + insert
    else:
        text = views.search_text(conn, "header checksum", mode="exact")
        assert "hit" in text or "no " in text.lower(), text
        for doc in docs:
            row = conn.execute("SELECT COUNT(*), MAX(id) FROM chunks "
                               "WHERE doc_id=?", (doc,)).fetchone()
            assert row[0] > 0, (doc, "chunks vanished mid-transaction")
        views.read(conn, docs[n % len(docs)], mirror_root=paths.mirror)
    conn.close()
    n += 1
print(role, n)
"""


def test_two_readers_and_one_writer_processes(library):
    """One writer process re-indexing documents while two reader processes
    search and read (one of them through a read-only connection, the mode
    meant for extra stdio servers): nobody fails, nobody hangs, and the
    database and its FTS index are sound afterwards."""
    from primarysource.rfc import library as lib
    conn, paths = library
    for doc in DOCS:
        assert lib.ensure_indexed(conn, doc)
    conn.commit()

    def spawn(role: str, **extra: str) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, "-c", _WORKER, role, "4", *DOCS],
            env=_env(paths.home, **extra), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8")

    procs = [spawn("writer"), spawn("reader"),
             spawn("reader", RFCLIB_READONLY="1")]
    results = []
    for p in procs:
        try:
            out, err = p.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            for q in procs:
                q.kill()
            pytest.fail("reader/writer processes deadlocked")
        results.append((p.returncode, out.strip(), err.strip()[-2000:]))
    assert all(rc == 0 for rc, _o, _e in results), results
    # every process got real work done while the others were running
    assert all(int(out.split()[1]) >= 3 for _rc, out, _e in results), results
    _assert_sound(paths.db)


# --------------------------------------------------------------------------
# read-only mode for extra stdio servers

def test_read_only_server_reads_but_never_writes(library, monkeypatch):
    pytest.importorskip("mcp")
    from mcp.server.mcpserver.exceptions import ToolError

    from primarysource.rfc import library as lib
    from primarysource.rfc.mcp import server
    conn, paths = library
    assert lib.ensure_indexed(conn, "RFC768")
    conn.commit()
    before = conn.execute("PRAGMA data_version").fetchone()[0]

    monkeypatch.setenv("RFCLIB_READONLY", "1")
    monkeypatch.setenv("RFCLIB_NETWORK", "auto")    # read-only still wins
    assert "User Datagram Protocol" in server.read("RFC768")
    assert "RFC768" in server.search("pseudo header", mode="exact")
    assert "RFC 2119" in server.info("RFC2119")
    assert server.errata("RFC768")
    assert server.cite("RFC768")
    # in the mirror but not indexed: indexing would be a write
    with pytest.raises(ToolError, match="read-only"):
        server.read("RFC2119")
    ro, _ = server._conn()
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ro.execute("DELETE FROM docs")
    ro.close()
    # no other connection committed anything meanwhile
    assert conn.execute("PRAGMA data_version").fetchone()[0] == before


def test_read_only_server_does_not_create_a_library(home, monkeypatch):
    pytest.importorskip("mcp")
    from mcp.server.mcpserver.exceptions import ToolError

    from primarysource.rfc.mcp import server
    monkeypatch.setenv("RFCLIB_READONLY", "1")
    with pytest.raises(ToolError, match="existing library"):
        server.search("anything")
    assert not home.exists()


def test_health_payload_is_json(library):
    """/healthz is served by the same process; here only its shape."""
    pytest.importorskip("mcp")
    import asyncio

    from primarysource.rfc.mcp import server
    resp = asyncio.run(server.healthz(None))
    body = json.loads(resp.body)
    assert resp.status_code == 200 and body["status"] == "ok"
    assert body["documents"] > 0

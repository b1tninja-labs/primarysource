from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from datetime import date
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from zimfixture import build_zim

from primarysource.zim import catalog, cli, groups, library, manage, sync
from primarysource.zim.errors import ZimloreError


class Kiwix:
    """A local stand-in for the catalogue and its mirror: a feed per `name=` query, `.meta4` files and the ZIMs."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.editions: dict[str, list[tuple[str, str, int]]] = {}
        self.requests: list[str] = []
        self.base = ""

    def publish(self, name: str, day: str, *, corrupt: bool = False) -> int:
        """Add an edition; returns the rounded length the feed will claim (the entry's `approx_bytes`)."""
        filename = f"{name}_{day[:7]}.zim"
        path = build_zim(self.directory, filename, name=name, title=name, date=day)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        meta = (
            '<metalink xmlns="urn:ietf:params:xml:ns:metalink"><file name="x.zim">'
            f'<size>{path.stat().st_size}</size><hash type="sha-256">{digest}</hash></file></metalink>'
        )
        (self.directory / (filename + ".meta4")).write_text(meta, encoding="utf-8")
        if corrupt:
            data = bytearray(path.read_bytes())
            data[-1] ^= 0xFF
            path.write_bytes(bytes(data))
        approx = (path.stat().st_size // 1000 + 1) * 1000
        self.editions.setdefault(name, []).append((day, filename, approx))
        return approx

    def feed(self, name: str) -> bytes:
        rows = "".join(
            f"<entry><id>urn:uuid:{filename}</id><title>{name}</title><updated>{day}T00:00:00Z</updated>"
            f"<language>eng</language><name>{name}</name><articleCount>5</articleCount>"
            f'<link type="application/x-zim" href="{self.base}/{filename}.meta4" length="{approx}"/></entry>'
            for day, filename, approx in self.editions.get(name, [])
        )
        total = len(self.editions.get(name, []))
        return (
            f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><totalResults>{total}</totalResults>'
            f"{rows}</feed>"
        ).encode()

    def fetched(self) -> list[str]:
        """Requests for anything but the catalogue: `.meta4` files and ZIMs."""
        return [p for p in self.requests if not p.startswith("/catalog")]


@pytest.fixture
def kiwix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Kiwix]:
    mirror = Kiwix(tmp_path / "served")

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            return None

        def do_GET(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            mirror.requests.append(parts.path)
            if parts.path == "/catalog/v2/entries":
                body = mirror.feed(parse_qs(parts.query).get("name", [""])[0])
                self.send_response(200)
                self.send_header("Content-Type", "application/atom+xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    server = HTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(mirror.directory)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    mirror.base = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setattr(catalog, "CATALOG_URL", mirror.base + "/catalog/v2/entries")
    try:
        yield mirror
    finally:
        server.shutdown()
        server.server_close()


def _manifest(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "libs.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _tree(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()
    }


# --- the manifest ---------------------------------------------------------------------------------------------


def test_a_manifest_names_catalogue_entries_and_nothing_else(tmp_path: Path) -> None:
    good = sync.load_manifest(
        _manifest(
            tmp_path,
            'libraries = ["devdocs_en_python", "stackoverflow.com_en_all"]\ngroups = ["infra"]\n'
            'max_age_days = 90\nbudget = "2GB"\n',
        )
    )
    assert good.libraries == ("devdocs_en_python", "stackoverflow.com_en_all")
    assert (good.groups, good.max_age_days, good.budget) == (("infra",), 90, 2_000_000_000)
    bad = {
        'libraries = ["https://evil.example/x.zim"]': "not a catalogue name",
        'libraries = ["../escape"]': "not a catalogue name",
        'libraries = ["C:\\\\temp\\\\x"]': "not a catalogue name",
        'libraries = ["devdocs_en_python.zim"]': "not a catalogue name",
        'libraries = ["a b"]': "not a catalogue name",
        'libraries = ["https://evil.example/x"]': "not a catalogue name",
        'libraries = ["sub/dir"]': "not a catalogue name",
        'libraries = ["host:8080"]': "not a catalogue name",
        "libraries = [3]": "not a catalogue name",
        'groups = ["nope"]': "unknown group",
        'run = "rm -rf /"': "unknown key",
        'budget = "plenty"': "not a size",
        "max_age_days = 0": "max_age_days",
        'max_age_days = "30"': "max_age_days",
        'libraries = "devdocs_en_python"': "must be lists",
        "libraries = [": "not a readable TOML",
    }
    for text, message in bad.items():
        with pytest.raises(ZimloreError, match=message):
            sync.load_manifest(_manifest(tmp_path, text))


def test_budget_sizes_are_decimal_and_a_bare_number_is_bytes() -> None:
    assert sync.parse_budget("2GB") == 2_000_000_000
    assert sync.parse_budget("500 mb") == 500_000_000
    assert sync.parse_budget("1.5GB") == 1_500_000_000
    assert sync.parse_budget(12345) == 12345 and sync.parse_budget("42") == 42
    for nonsense in ("", "GB", "-1GB", "0MB", "2 parsecs", True, 0, 1.5):
        with pytest.raises(ZimloreError, match="not a size"):
            sync.parse_budget(nonsense)


def test_the_manifest_is_found_explicit_then_here_then_in_the_home(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = tmp_path / "project"
    here.mkdir()
    assert sync.find_manifest("", here) is None
    (home / sync.HOME_MANIFEST).write_text('libraries = ["a"]', encoding="utf-8")
    assert sync.find_manifest("", here) == home / sync.HOME_MANIFEST
    (here / sync.MANIFEST_NAME).write_text('libraries = ["b"]', encoding="utf-8")
    assert sync.find_manifest("", here) == here / sync.MANIFEST_NAME
    explicit = _manifest(tmp_path, 'libraries = ["c"]')
    assert sync.find_manifest(str(explicit), here) == explicit
    with pytest.raises(ZimloreError, match="does not exist"):
        sync.find_manifest(str(tmp_path / "missing.toml"), here)
    monkeypatch.chdir(here)
    assert sync.find_manifest("") == here / sync.MANIFEST_NAME, "the working directory is the default"


def test_shipped_groups_hold_catalogue_names_only_and_say_they_are_a_default() -> None:
    assert groups.EDITORIAL_DEFAULT is True
    assert sorted(groups.GROUPS) == ["infra", "languages-core", "web-testing"]
    for name, members in groups.GROUPS.items():
        assert members and len(set(members)) == len(members), name
        for member in members:
            assert sync.check_name(member, name) == member and member.startswith("devdocs_en_")
    slugs = {name: [m.removeprefix("devdocs_en_") for m in members] for name, members in groups.GROUPS.items()}
    assert slugs["languages-core"] == [
        "python", "rust", "go", "php", "node", "npm", "typescript", "javascript", "c", "cpp", "ruby", "openjdk",
    ]  # fmt: skip
    assert slugs["web-testing"] == [
        "html", "css", "dom", "http", "playwright", "cypress", "pytest", "jest", "vitest", "puppeteer", "mocha",
    ]  # fmt: skip
    assert slugs["infra"] == ["bash", "git", "docker", "sqlite", "postgresql", "terraform", "kubectl"]


def test_wanted_names_are_libraries_then_group_members_once_each(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(groups.GROUPS, "tiny", ("one", "two"))
    assert sync.wanted_names(("two", "zero"), ("tiny",)) == ["two", "zero", "one"]
    with pytest.raises(ZimloreError, match="unknown group"):
        sync.wanted_names((), ("nope",))


# --- the plan --------------------------------------------------------------------------------------------------


def _world(kiwix: Kiwix, home: Path) -> dict[str, int]:
    """Catalogue: alpha (new), beta (2026-09-01 and 2026-10-01), gamma. Installed: beta 2026-09-01, gamma
    2026-10-01, zeta (not in any manifest). `delta` is nowhere."""
    sizes = {
        "alpha": kiwix.publish("alpha", "2026-10-01"),
        "gamma": kiwix.publish("gamma", "2026-10-01"),
    }
    kiwix.publish("beta", "2026-09-01")
    sizes["beta"] = kiwix.publish("beta", "2026-10-01")
    build_zim(home / "zim", "beta_2026-09.zim", name="beta", title="beta", date="2026-09-01")
    build_zim(home / "zim", "gamma_2026-10.zim", name="gamma", title="gamma", date="2026-10-01")
    build_zim(home / "zim", "zeta_2026-01.zim", name="zeta", title="zeta", date="2026-01-01")
    return sizes


def test_the_plan_installs_missing_updates_only_on_request_and_reports_extras(kiwix: Kiwix, home: Path) -> None:
    sizes = _world(kiwix, home)
    manifest = sync.Manifest(None, ("alpha", "beta", "gamma", "delta"))
    plan = sync.make_plan(manifest)
    rows = {i.name: i for i in plan.items}
    assert {n: i.action for n, i in rows.items()} == {
        "alpha": "install",
        "beta": "outdated",
        "gamma": "current",
        "delta": "unavailable",
    }
    assert rows["beta"].installed == "2026-09-01" and rows["beta"].available == "2026-10-01"
    assert [(e["name"], e["editions"]) for e in plan.extras] == [("zeta", 1)]
    assert plan.download_bytes == sizes["alpha"], "an update nobody asked for is not downloaded or counted"
    assert plan.problems == [rows["delta"]] and [i.name for i in plan.to_fetch] == ["alpha"]
    updating = sync.make_plan(manifest, update=True)
    assert {i.name: i.action for i in updating.items}["beta"] == "update"
    assert updating.download_bytes == sizes["alpha"] + sizes["beta"]
    assert updating.as_dict()["download_note"].startswith("approximate")


def test_a_dry_run_plan_touches_nothing_and_downloads_nothing(kiwix: Kiwix, home: Path) -> None:
    _world(kiwix, home)
    before = _tree(home)
    plan = sync.make_plan(sync.Manifest(None, ("alpha", "beta", "gamma")), update=True)
    assert plan.to_fetch, "there is something it would do"
    assert _tree(home) == before
    assert kiwix.fetched() == [], "sizes come from the catalogue; no .meta4 and no ZIM is requested"


def test_a_name_the_catalogue_lacks_but_is_installed_is_kept_and_not_a_problem(kiwix: Kiwix, home: Path) -> None:
    _world(kiwix, home)
    plan = sync.make_plan(sync.Manifest(None, ("zeta",)))
    assert [(i.name, i.action) for i in plan.items] == [("zeta", "unlisted")] and plan.problems == []


def test_max_age_days_flags_an_old_edition_whether_or_not_a_newer_one_exists(kiwix: Kiwix, home: Path) -> None:
    _world(kiwix, home)
    names = ("beta", "gamma")
    tight = sync.make_plan(sync.Manifest(None, names, max_age_days=20), today=date(2026, 10, 15))
    assert {i.name: i.over_max_age for i in tight.items} == {"beta": True, "gamma": False}
    edge = date(2026, 10, 15) - date(2026, 9, 1)  # beta is exactly this old: the limit itself is allowed
    for limit, flagged in [(edge.days, False), (edge.days - 1, True)]:
        plan = sync.make_plan(sync.Manifest(None, ("beta",), max_age_days=limit), today=date(2026, 10, 15))
        assert plan.items[0].over_max_age is flagged, limit
    loose = sync.make_plan(sync.Manifest(None, names, max_age_days=60), today=date(2026, 10, 15))
    assert not any(i.over_max_age for i in loose.items)
    unset = sync.make_plan(sync.Manifest(None, names), today=date(2026, 10, 15))
    assert not any(i.over_max_age for i in unset.items)


def test_a_file_already_at_the_target_name_blocks_the_download_and_is_left_alone(kiwix: Kiwix, home: Path) -> None:
    kiwix.publish("alpha", "2026-10-01")
    junk = home / "zim" / "alpha_2026-10.zim"
    junk.write_bytes(b"not a zim")
    plan = sync.make_plan(sync.Manifest(None, ("alpha",)))
    assert (
        plan.items[0].action == "blocked"
        and plan.items[0].approx_bytes == 0
        and "move it aside" in plan.items[0].note
    )
    assert sync.execute(plan) == [] and junk.read_bytes() == b"not a zim" and kiwix.fetched() == []


def test_the_budget_caps_the_library_after_the_sync_and_the_boundary_is_allowed(kiwix: Kiwix, home: Path) -> None:
    _world(kiwix, home)
    installed = sum(b.size for b in library.scan().books)
    sizes = {n: kiwix.editions[n][-1][2] for n in kiwix.editions}
    exact = installed + sizes["alpha"]
    fits = sync.make_plan(sync.Manifest(None, ("alpha",), budget=exact))
    assert fits.installed_bytes == installed and not fits.over_budget
    over = sync.make_plan(sync.Manifest(None, ("alpha",), budget=exact - 1))
    assert over.over_budget
    with pytest.raises(ZimloreError, match="over the .* budget; nothing was downloaded") as refused:
        sync.execute(over)
    assert "budget" in refused.value.action and kiwix.fetched() == []
    assert not list((home / "zim").glob("alpha*"))
    assert sync.make_plan(sync.Manifest(None, ("alpha",))).over_budget is False, "no budget means no cap"


# --- running a sync --------------------------------------------------------------------------------------------


def test_sync_installs_what_is_missing_stamps_it_sync_and_stages_updates_beside_the_old_edition(
    kiwix: Kiwix, home: Path
) -> None:
    _world(kiwix, home)
    old = home / "zim" / "beta_2026-09.zim"
    old_state = (old.read_bytes(), old.stat().st_mtime_ns)
    results = sync.execute(sync.make_plan(sync.Manifest(None, ("alpha", "beta", "gamma")), update=True))
    assert [(r["name"], r["ok"]) for r in results] == [("alpha", True), ("beta", True)]
    names = sorted(p.name for p in (home / "zim").glob("*.zim"))
    assert names == [
        "alpha_2026-10.zim",
        "beta_2026-09.zim",
        "beta_2026-10.zim",
        "gamma_2026-10.zim",
        "zeta_2026-01.zim",
    ], "the old edition and the extra are still there"
    assert (old.read_bytes(), old.stat().st_mtime_ns) == old_state, "the old edition is never touched"
    record, _ = manage.read_sidecar(home / "zim" / "alpha_2026-10.zim")
    assert record is not None and record.added_by == "sync" and record.catalogue_name == "alpha"
    assert not list((home / "zim").glob("*.part*")), "no part and no lock is left behind"
    again = sync.make_plan(sync.Manifest(None, ("alpha", "beta", "gamma")), update=True)
    assert {i.action for i in again.items} == {"current"} and again.to_fetch == []


def test_one_failed_library_is_reported_and_does_not_stop_the_others(kiwix: Kiwix, home: Path) -> None:
    kiwix.publish("alpha", "2026-10-01", corrupt=True)
    kiwix.publish("beta", "2026-10-01")
    results = sync.execute(sync.make_plan(sync.Manifest(None, ("alpha", "beta"))))
    assert [(r["name"], r["ok"]) for r in results] == [("alpha", False), ("beta", True)]
    assert "was discarded" in results[0]["error"]
    assert sorted(p.name for p in (home / "zim").glob("*.zim")) == ["beta_2026-10.zim"]


# --- the command -------------------------------------------------------------------------------------------------


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_dry_run_with_a_group_prints_the_plan_and_the_approximate_total_and_changes_nothing(
    kiwix: Kiwix, home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(home)  # no .zimlore.toml here
    monkeypatch.setitem(groups.GROUPS, "tiny", ("alpha", "beta"))
    sizes = {"alpha": kiwix.publish("alpha", "2026-10-01"), "beta": kiwix.publish("beta", "2026-10-01")}
    before = _tree(home)
    code, out, _ = _run(capsys, "sync", "--group", "tiny", "--dry-run")
    assert code == 0 and _tree(home) == before and kiwix.fetched() == []
    assert "install" in out and "alpha" in out and "beta" in out
    assert f"~{sum(sizes.values()) / 1e6:.1f} MB (approximate" in out and ".meta4 has the true size" in out
    assert "dry run: nothing was downloaded" in out
    code, out, _ = _run(capsys, "sync", "--group", "tiny", "--dry-run", "--json")
    data = json.loads(out)
    assert code == 0 and data["dry_run"] is True and data["download_bytes_approx"] == sum(sizes.values())
    assert [i["action"] for i in data["items"]] == ["install", "install"] and kiwix.fetched() == []


def test_cli_sync_from_a_manifest_downloads_and_reports(
    kiwix: Kiwix, home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    kiwix.publish("alpha", "2026-10-01")
    manifest = _manifest(tmp_path, 'libraries = ["alpha"]\nbudget = "1GB"\n')
    code, out, _ = _run(capsys, "sync", "--manifest", str(manifest))
    assert code == 0 and "installed  alpha" in out and "within the budget" in out
    assert (home / "zim" / "alpha_2026-10.zim").is_file()
    code, out, _ = _run(capsys, "sync", "--manifest", str(manifest))
    assert code == 0 and "current" in out and "installed  alpha" not in out


def test_cli_sync_exit_codes_for_nothing_to_do_budget_and_unavailable(
    kiwix: Kiwix, home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(home)
    code, _, err = _run(capsys, "sync")
    assert code == 2 and "nothing to sync" in err and "--group" in err
    kiwix.publish("alpha", "2026-10-01")
    small = _manifest(tmp_path, 'libraries = ["alpha"]\nbudget = "1KB"\n')
    code, out, _ = _run(capsys, "sync", "--manifest", str(small), "--dry-run")
    assert code == 1 and "EXCEEDS the budget" in out and kiwix.fetched() == []
    code, out, err = _run(capsys, "sync", "--manifest", str(small))
    assert code == 2 and "budget" in err and "nothing was downloaded" in err and kiwix.fetched() == []
    missing = _manifest(tmp_path, 'libraries = ["delta"]\n')
    code, out, _ = _run(capsys, "sync", "--manifest", str(missing), "--dry-run")
    assert code == 1 and "unavailable" in out and "no entry with this name" in out


def test_sync_and_outdated_compare_editions_as_dates_not_as_text(
    kiwix: Kiwix, home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(home)
    build_zim(home / "zim", "alpha_old.zim", name="alpha", title="alpha", date="2026-9-15")
    kiwix.publish("alpha", "2026-10-01")
    plan = sync.make_plan(sync.Manifest(libraries=("alpha",)))
    assert plan.items[0].action == "outdated", "as text '2026-10-01' < '2026-9-15': the catalogue looked older"
    code, out, _ = _run(capsys, "outdated", "--json")
    assert code == 0 and json.loads(out)["rows"][0]["outdated"] is True


def test_sync_does_not_call_an_undated_installed_edition_current(kiwix: Kiwix, home: Path) -> None:
    build_zim(home / "zim", "alpha_old.zim", name="alpha", title="alpha", date="")
    kiwix.publish("alpha", "2026-10-01")
    item = sync.make_plan(sync.Manifest(libraries=("alpha",))).items[0]
    assert item.action == "outdated" and "no usable Date" in item.note


def test_cli_get_will_not_replace_a_different_file_until_told_and_says_when_nothing_changed(
    kiwix: Kiwix, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    kiwix.publish("alpha", "2026-10-01")
    mine = home / "zim" / "alpha_2026-10.zim"
    mine.write_bytes(b"somebody's file")
    code, _, err = _run(capsys, "get", "alpha")
    assert code == 2 and "not replacing" in err and "--replace" in err
    assert mine.read_bytes() == b"somebody's file"
    code, out, _ = _run(capsys, "get", "alpha", "--replace")
    assert code == 0 and "verified (SHA-256) and replaced" in out
    code, out, _ = _run(capsys, "get", "alpha")
    assert code == 0 and "already installed, identical" in out

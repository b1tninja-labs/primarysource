from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest
from zimfixture import build_zim

from primarysource.zim import _libzim, library
from primarysource.zim.errors import ZimloreError
from primarysource.zim.refs import Ref, format_ref, parse_ref


def test_reference_grammar_round_trips() -> None:
    ref = parse_ref("devdocs_en_flask§blueprints/index#why-blueprints¶3")
    assert ref == Ref("devdocs_en_flask", "blueprints/index", "why-blueprints", 3)
    assert str(ref) == "devdocs_en_flask§blueprints/index#why-blueprints¶3"
    assert parse_ref("flask::blueprints/index") == Ref("flask", "blueprints/index")
    assert parse_ref("flask") == Ref("flask", ""), "a library alone means its main page"
    assert parse_ref("/x/y", default_book="flask") == Ref("flask", "x/y")
    assert format_ref("a", "") == "a"


@pytest.mark.parametrize("bad", ["", "   ", "§path", "flask§x¶0"])
def test_malformed_refs_are_errors_not_guesses(bad: str) -> None:
    with pytest.raises(ZimloreError):
        parse_ref(bad)


def test_an_empty_library_is_an_error_naming_the_fix(home: Path) -> None:
    scanned = library.scan()
    assert scanned.books == []
    error = library.empty_library_error(scanned)
    assert "no ZIM files found" in error.message
    assert "primarysource zim get" in error.action, "the error must name the command that fixes it"


def test_scan_reads_metadata_and_reports_unreadable_files(home: Path) -> None:
    build_zim(home / "zim")
    (home / "zim" / "broken.zim").write_bytes(b"this is not a zim file at all")
    scanned = library.scan()
    assert [b.name for b in scanned.books] == ["acme_en_widgets"]
    book = scanned.books[0]
    assert (book.title, book.date, book.language, book.creator) == (
        "Acme Widgets Docs",
        "2026-10-01",
        "eng",
        "Acme Docs",
    )
    assert book.tags == ("devdocs", "acme"), "scraper-internal _tags are not tags"
    assert book.has_fulltext and book.has_titles
    assert [p["path"].endswith("broken.zim") for p in scanned.problems] == [True], "a bad file is reported"


def test_freshness_is_data_and_unknown_is_not_fresh(home: Path) -> None:
    path = build_zim(home / "zim")
    book = library.read_book(path)
    assert book.freshness(date(2026, 11, 7)) == {
        "date": "2026-10-01",
        "age_days": 37,
        "stale": False,
        "stale_after_days": library.STALE_DAYS,
    }
    assert book.freshness(date(2028, 1, 1))["stale"] is True
    undated = library.Book(**{**book.__dict__, "date": ""})
    assert undated.freshness()["stale"] is None, "no Date metadata means unknown, never 'fresh'"


def test_aliases_cover_devdocs_titles_and_stack_exchange_hosts() -> None:
    def book(name: str, title: str) -> library.Book:
        return library.Book(
            name, title, "2026-01-01", "eng", "", "", "", (), "", "", Path("x.zim"), "u", 1, 1, True, True
        )

    assert {"flask", "flask docs", "devdocs en flask", "devdocs flask"} <= book(
        "devdocs_en_flask", "Flask Docs"
    ).aliases()
    se = book("security.stackexchange.com_en_all", "Information Security Stack Exchange").aliases()
    assert {"security", "security stackexchange com"} <= se
    assert "stackoverflow" in book("stackoverflow.com_en_all_2026-07", "Stack Overflow").aliases()
    assert "py" in book("devdocs_en_python", "Python Docs").aliases({"py": "devdocs_en_python"})


def test_resolution_prefers_exact_and_reports_what_is_installed_when_nothing_matches(home: Path) -> None:
    build_zim(home / "zim", "a.zim", name="devdocs_en_react", title="React Docs")
    build_zim(home / "zim", "b.zim", name="devdocs_en_react-native", title="React Native Docs")
    assert library.find("react").name == "devdocs_en_react", "an exact alias beats longer names that contain it"
    assert library.find("react native").name == "devdocs_en_react-native"
    with pytest.raises(ZimloreError) as missing:
        library.find("cobol")
    assert missing.value.extra["installed"] == ["devdocs_en_react", "devdocs_en_react-native"]
    assert "primarysource zim list" in missing.value.action


def test_two_libraries_that_match_equally_are_listed_not_guessed(home: Path) -> None:
    build_zim(home / "zim", "a.zim", name="devdocs_en_react", title="React Docs")
    build_zim(home / "zim", "b.zim", name="reactjs.org_en_all", title="React Docs")
    with pytest.raises(ZimloreError) as tied:
        library.find("react")
    names = {c["name"] for c in tied.value.extra["candidates"]}  # type: ignore[attr-defined]
    assert names == {"devdocs_en_react", "reactjs.org_en_all"}
    assert library.find("devdocs_en_react").name == "devdocs_en_react", "the full name always disambiguates"


def test_a_clearly_better_match_is_not_called_a_tie(home: Path) -> None:
    """Two libraries both match 'react', one exactly and one by prefix. Their scores differ, and a tolerance wide
    enough to swallow the difference would make `find` refuse a query it can answer."""
    build_zim(home / "zim", "a.zim", name="devdocs_en_react", title="React Docs")
    build_zim(home / "zim", "b.zim", name="devdocs_en_react-native", title="React Native Docs")
    ranked = library.rank("react", library.scan().books, library.user_aliases())
    assert len(ranked) == 2 and ranked[0].score - ranked[1].score > 0.01
    assert library.find("react").name == "devdocs_en_react"


def test_two_editions_of_one_library_resolve_to_the_newest_and_say_so(home: Path) -> None:
    build_zim(home / "zim", "acme_2026-08.zim", date="2026-08-01")
    build_zim(home / "zim", "acme_2026-10.zim", date="2026-10-01")
    scanned = library.scan()
    assert len(scanned.books) == 2
    chosen = library.find("acme", scanned)
    assert chosen.date == "2026-10-01"
    assert [b.date for b in library.editions(chosen, scanned.books)] == ["2026-10-01", "2026-08-01"]


def test_user_aliases_file_and_a_malformed_one(home: Path) -> None:
    build_zim(home / "zim")
    (home / "aliases.json").write_text(json.dumps({"widgets": "acme_en_widgets"}), encoding="utf-8")
    assert library.find("widgets").name == "acme_en_widgets"
    (home / "aliases.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ZimloreError, match="not valid JSON"):
        library.find("widgets")


def test_zim_path_overrides_the_home_subdirectory(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "kiwix-library"
    build_zim(elsewhere)
    monkeypatch.setenv(library.PATH_ENV, str(elsewhere))
    assert [b.name for b in library.scan().books] == ["acme_en_widgets"]
    assert library.zim_dirs() == [elsewhere]


def _clear_home_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (library.HOME_ENV, "PRIMARYSOURCE_ZIM_HOME", "PRIMARYSOURCE_HOME"):
        monkeypatch.delenv(name, raising=False)


def test_home_settings_apply_in_the_documented_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """$ZIMLORE_HOME, $PRIMARYSOURCE_ZIM_HOME, $PRIMARYSOURCE_HOME/zim, an existing ~/.zimlore, the user default."""
    _clear_home_settings(monkeypatch)
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("USERPROFILE", str(user))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    default = library.home()
    assert "zimlore" not in default.parts[-1] and default.name == "zim" and default.parent.name == "primarysource"
    old = user / ".zimlore"
    old.mkdir()
    assert library.home() == old, "an existing ~/.zimlore is found instead of an empty library beside it"
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path / "all"))
    assert library.home() == tmp_path / "all" / "zim"
    monkeypatch.setenv("PRIMARYSOURCE_ZIM_HOME", str(tmp_path / "zimonly"))
    assert library.home() == tmp_path / "zimonly"
    monkeypatch.setenv(library.HOME_ENV, str(tmp_path / "legacy"))
    assert library.home() == tmp_path / "legacy"


def test_the_legacy_zim_path_setting_still_works_and_the_new_one_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(library.PATH_ENV, raising=False)
    monkeypatch.setenv(library.LEGACY_PATH_ENV, str(tmp_path / "old"))
    assert library.zim_dirs() == [tmp_path / "old"]
    monkeypatch.setenv(library.PATH_ENV, str(tmp_path / "new"))
    assert library.zim_dirs() == [tmp_path / "new"]


def test_default_home_is_under_the_user_profile_not_the_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_home_settings(monkeypatch)
    repo = Path(__file__).resolve().parents[2]
    assert repo not in library.home().parents and library.home() != repo


def test_a_missing_binding_is_an_error_naming_the_remedy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "libzim", None)
    monkeypatch.setitem(sys.modules, "libzim.reader", None)
    assert _libzim.available() is False
    with pytest.raises(ZimloreError) as caught:
        _libzim.load("reader")
    assert 'pip install "primarysource[zim]"' in caught.value.hint

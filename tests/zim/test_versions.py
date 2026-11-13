"""Versioned libraries: a package's versions are separate ZIM Names that share a family; purls name them.

The ZIMs are synthetic (`zimfixture.build_zim`): only their metadata matters here, never their pages.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from zimfixture import build_zim, contract_server, managed, tool_error, tool_text

from primarysource.zim import cli, library, manage, purl, service
from primarysource.zim.errors import LibraryNotFound, ZimloreError
from primarysource.zim.refs import Ref, parse_ref

COBRA = "golang_github.com_spf13_cobra"


def versions(
    home: Path, family: str, found: list[str], title: str = "github.com/spf13/cobra {v} documentation"
) -> None:
    """One ZIM per version, named `<family>_<version>`, titled the way the Go prototype titles them."""
    service.forget()
    for version in found:
        name = f"{family}_{version}"
        build_zim(home / "zim", f"{name}.zim", name=name, title=title.format(v=version))


# --- family and version are derived, not stored ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "family", "version"),
    [
        ("pypi_cryptography_50.0.2", "pypi_cryptography", "50.0.2"),
        ("golang_github.com_spf13_cobra_v1.8.1", "golang_github.com_spf13_cobra", "v1.8.1"),
        ("golang_github.com_spf13_cobra_v1.10.2", "golang_github.com_spf13_cobra", "v1.10.2"),
        ("npm_left-pad_1.3.0", "npm_left-pad", "1.3.0"),
        ("pypi_django_5", "pypi_django", "5"),
        ("pypi_flask_3.1.0rc1", "pypi_flask", "3.1.0rc1"),
        ("pypi_attrs_26.1.0-beta.2", "pypi_attrs", "26.1.0-beta.2"),
        ("cargo_serde_1.x", "cargo_serde", "1.x"),
        ("devdocs_en_flask", "devdocs_en_flask", None),
        ("devdocs_en_node_2026-10", "devdocs_en_node", None),
        ("devdocs_en_node_20_2026-10", "devdocs_en_node", "20"),
        ("docs.python.org_en_all", "docs.python.org_en_all", None),
        ("stackoverflow.com_en_all", "stackoverflow.com_en_all", None),
        ("stackoverflow.com_en_all_2026-07", "stackoverflow.com_en_all", None),
        ("wikipedia_en_100", "wikipedia_en_100", None),
        ("ubuntu_en_all_2024", "ubuntu_en_all_2024", None),
        ("1.2.3", "1.2.3", None),
    ],
)
def test_family_and_version_are_derived_from_the_name(name: str, family: str, version: str | None) -> None:
    assert library.split_name(name) == (family, version)


def test_the_purl_tag_wins_over_the_name(home: Path) -> None:
    build_zim(home / "zim", "a.zim", name="some_site_build", tags="docs;purl:pkg:pypi/flask@3.1.0;_ftindex:yes")
    build_zim(home / "zim", "b.zim", name="devdocs_en_flask", title="Flask Docs")
    build_zim(home / "zim", "c.zim", name="pypi_x_9.9", title="X", tags="purl:not-a-purl")
    by_name = {b.name: b for b in library.scan().books}
    tagged = by_name["some_site_build"]
    assert (tagged.family, tagged.version) == ("pkg:pypi/flask", "3.1.0")
    plain = by_name["devdocs_en_flask"]
    assert (plain.family, plain.version) == ("devdocs_en_flask", None), "no tag and no token: its own family"
    assert (by_name["pypi_x_9.9"].family, by_name["pypi_x_9.9"].version) == ("pypi_x", "9.9"), "a bad tag is ignored"


# --- the version order -----------------------------------------------------------------------------------------


def _newest_first(*texts: str) -> list[str]:
    return sorted(texts, key=library.version_key, reverse=True)


def test_versions_order_numerically_and_tolerate_what_ecosystems_write() -> None:
    assert _newest_first("1.8.1", "1.10.2", "1.9.0") == ["1.10.2", "1.9.0", "1.8.1"], "1.10 is above 1.8"
    assert _newest_first("v1.8.1", "1.10.2", "V1.9") == ["1.10.2", "V1.9", "v1.8.1"], "a v prefix is not a version"
    assert library.version_key("v1.0") == library.version_key("1.0.0"), "trailing zeros do not matter"
    assert _newest_first("3.1.0rc1", "3.1.0", "3.1.0b2", "3.1.0a1", "3.1.0.dev3") == [
        "3.1.0",
        "3.1.0rc1",
        "3.1.0b2",
        "3.1.0a1",
        "3.1.0.dev3",
    ], "a pre-release is below its release"
    assert _newest_first("2.0-beta.2", "2.0-beta.10", "1.9") == ["2.0-beta.10", "2.0-beta.2", "1.9"]
    assert _newest_first("1.2.3", "1.2.3.post1") == ["1.2.3.post1", "1.2.3"], "a post-release is above"
    assert _newest_first("1.2.3+build9", "1.2.4") == ["1.2.4", "1.2.3+build9"], "build metadata is ignored"
    assert _newest_first("1.2.x", "1.2.0") == ["1.2.0", "1.2.x"], "a wildcard suffix never outranks a release"


def test_a_version_with_no_number_sorts_last() -> None:
    assert _newest_first("latest", "0.0.1", "main")[0] == "0.0.1"
    assert _newest_first("latest", "0.0", "main")[0] == "0.0", "zero is a number"
    assert _newest_first("stable", "0.0")[0] == "0.0", "a number outranks a word that is not a pre-release"
    assert _newest_first("latest", "0.0.1")[-1] == "latest"
    assert library.version_key("latest") != library.version_key("main"), "unnumbered versions stay distinguishable"


def test_a_version_prefix_matches_whole_components() -> None:
    assert library.version_prefix("3.1", "3.1.4") and library.version_prefix("v3", "3.10.0")
    assert not library.version_prefix("3.1", "3.10.0"), "3.1 is not a prefix of 3.10"
    assert not library.version_prefix("3.1.0rc1", "3.1.0rc1.post2"), "a suffix has no prefix reading"
    assert not library.version_prefix("latest", "latest")


# --- resolution ------------------------------------------------------------------------------------------------


def test_a_family_resolves_to_its_newest_version_not_the_shorter_name(home: Path) -> None:
    """The measured defect: `cobra` picked v1.8.1 over v1.10.2 because that alias is a character shorter."""
    versions(home, COBRA, ["v1.8.1", "v1.10.2"])
    books = library.scan().books
    ranked = library.rank("cobra", books)
    assert len(ranked) == 1, "versions of one library are one candidate, not two that nearly tie"
    assert ranked[0].book.version == "v1.10.2" and len(ranked[0].members) == 2
    chosen = library.select("cobra")
    assert chosen.book.name == f"{COBRA}_v1.10.2" and chosen.kind == "newest"
    assert chosen.other_versions == ["v1.8.1"] and chosen.versions == ["v1.10.2", "v1.8.1"]
    assert library.find("github.com/spf13/cobra").version == "v1.10.2"


def test_two_different_libraries_still_tie_but_two_versions_of_one_never_do(home: Path) -> None:
    versions(home, "golang_cobra", ["v1.0", "v1.1"], title="Cobra Docs")
    versions(home, "pypi_cobra", ["2.0", "2.1"], title="Cobra Docs")
    with pytest.raises(ZimloreError) as tied:
        library.find("cobra")
    names = [c["name"] for c in tied.value.extra["candidates"]]  # type: ignore[attr-defined]
    assert names == ["golang_cobra_v1.1", "pypi_cobra_2.1"], "one candidate per library, each at its newest"
    assert library.find("golang cobra").name == "golang_cobra_v1.1"
    assert library.find("pypi_cobra_2.0").version == "2.0", "a whole Name selects that very version"


@pytest.mark.parametrize(
    "query", ["cobra v1.8.1", "cobra 1.8.1", "cobra@v1.8.1", "cobra==1.8.1", "github.com/spf13/cobra@1.8.1"]
)
def test_a_query_with_a_version_selects_that_version(home: Path, query: str) -> None:
    versions(home, COBRA, ["v1.8.1", "v1.10.2"])
    chosen = library.select(query)
    assert (chosen.book.version, chosen.kind, chosen.requested) == (
        "v1.8.1",
        "exact",
        query.split()[-1].split("@")[-1].split("==")[-1],
    )
    assert chosen.other_versions == ["v1.10.2"]


def test_a_version_prefix_selects_the_newest_that_starts_with_it(home: Path) -> None:
    versions(home, "pypi_flask", ["3.0.3", "3.1.0", "3.1.4", "3.10.0"], title="Flask {v}")
    assert (library.select("flask 3.1").book.version, library.select("flask 3.1").kind) == ("3.1.4", "prefix")
    assert library.select("flask@3").book.version == "3.10.0"
    assert library.select("flask 3.1.0").kind == "exact"
    assert library.select("flask").book.version == "3.10.0" and library.select("flask").kind == "newest"


def test_a_version_that_is_not_installed_is_an_error_listing_the_installed_ones(home: Path) -> None:
    versions(home, "pypi_flask", ["3.0.3", "3.1.0"], title="Flask {v}")
    with pytest.raises(LibraryNotFound) as missing:
        library.select("flask 4.0")
    error = missing.value
    assert "no installed version matching '4.0'" in error.message and "3.1.0, 3.0.3" in error.message
    assert error.extra["installed_versions"] == ["3.1.0", "3.0.3"] and error.extra["requested_version"] == "4.0"
    assert "build" not in (error.message + error.hint).lower(), "`primarysource zim docs build` does not exist"
    with pytest.raises(LibraryNotFound):
        library.select("flask 3.1.9")  # a prefix needs a version that starts with it, not one that is near it


def test_a_version_asked_of_a_library_that_states_none_is_an_error_not_a_guess(home: Path) -> None:
    build_zim(home / "zim", "a.zim", name="devdocs_en_flask", title="Flask Docs")
    with pytest.raises(LibraryNotFound, match="none of the installed ZIMs states a version"):
        library.select("flask 3.1")
    assert library.select("flask").kind == "newest" and library.select("flask").versions == []


def test_a_number_that_is_part_of_the_name_still_resolves(home: Path) -> None:
    build_zim(home / "zim", "a.zim", name="devdocs_en_python", title="Python 3 Docs")
    assert library.find("python 3").name == "devdocs_en_python"


# --- purls -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "key", "version"),
    [
        ("pkg:pypi/flask@3.1.0", ("pypi", "", "flask"), "3.1.0"),
        ("pkg:pypi/Flask_SQLAlchemy", ("pypi", "", "flask-sqlalchemy"), None),
        ("pkg:golang/github.com/spf13/cobra@v1.8.1", ("golang", "github.com/spf13", "cobra"), "v1.8.1"),
        ("pkg:npm/%40angular/core@17.0.0", ("npm", "@angular", "core"), "17.0.0"),
        ("pkg:npm/@angular/core@17.0.0", ("npm", "@angular", "core"), "17.0.0"),
        ("pkg:npm/left-pad@1.3.0?repository_url=x#lib/a", ("npm", "", "left-pad"), "1.3.0"),
        ("pkg:maven/com.google.guava/guava@33.0.0-jre", ("maven", "com.google.guava", "guava"), "33.0.0-jre"),
        ("pkg:cargo/serde@1.0.200", ("cargo", "", "serde"), "1.0.200"),
        ("pkg:gem/rails@7.1.0", ("gem", "", "rails"), "7.1.0"),
        ("pkg:nuget/Newtonsoft.Json@13.0.3", ("nuget", "", "newtonsoft.json"), "13.0.3"),
        ("pkg:github/Pallets/Flask@3.1.0", ("github", "pallets", "flask"), "3.1.0"),
        ("pkg:generic/openssl@3.0.0", ("generic", "", "openssl"), "3.0.0"),
        ("PKG:pypi/flask%40x@1%2E0", ("pypi", "", "flask@x"), "1.0"),
    ],
)
def test_purl_forms_parse_to_a_package_key_and_a_version(
    text: str, key: tuple[str, str, str], version: str | None
) -> None:
    parsed = purl.parse(text)
    assert parsed.key == key and parsed.version == version


@pytest.mark.parametrize(
    "bad",
    [
        "pkg:",
        "pkg:pypi",
        "pkg:pypi/",
        "pkg:cobol/thing@1",
        "pkg:pypi/a/b@1",
        "pkg:golang/cobra@v1",
        "pkg:maven/guava@1",
        "pkg:pypi/flask@",
        "pkg:pypi/flask?bad",
        "pkg:pypi/flask?A=1&a=2",
        "flask@3.1.0",
        "",
    ],
)
def test_garbage_purls_are_zimlore_errors(bad: str) -> None:
    with pytest.raises(ZimloreError) as caught:
        purl.parse(bad)
    assert caught.value.hint


def test_a_purl_selects_by_the_zims_purl_tag(home: Path) -> None:
    service.forget()
    for version in ("3.0.3", "3.1.0", "3.1.4"):
        build_zim(
            home / "zim",
            f"site_{version}.zim",
            name=f"site_build_{version.replace('.', '_')}",
            title="Docs",
            tags=f"docs;purl:pkg:pypi/flask@{version}",
        )
    build_zim(home / "zim", "other.zim", name="other_site", title="Docs", tags="purl:pkg:pypi/django@5.0.0")
    exact = library.select("pkg:pypi/flask@3.1.0")
    assert (exact.book.version, exact.kind, exact.requested) == ("3.1.0", "exact", "3.1.0")
    assert exact.other_versions == ["3.1.4", "3.0.3"]
    assert library.select("pkg:pypi/Flask").book.version == "3.1.4", "no version: the newest; case is folded"
    assert library.select("pkg:pypi/django@5.0.0").book.name == "other_site", "the tag names the package"
    assert library.select("pkg:pypi/flask@3.1").kind == "prefix"
    with pytest.raises(LibraryNotFound, match="no installed version matching '4.0'"):
        library.select("pkg:pypi/flask@4.0")
    assert library.find("flask 3.0").version == "3.0.3", "the tag's package name is also a name"
    with pytest.raises(ZimloreError, match="not a usable purl"):
        library.select("pkg:pypi/a/b")


def test_a_purl_falls_back_to_the_name_when_no_zim_carries_the_tag(home: Path) -> None:
    versions(home, "pypi_cryptography", ["49.0.0", "50.0.2"], title="cryptography {v}")
    assert library.select("pkg:pypi/cryptography@50.0.2").book.name == "pypi_cryptography_50.0.2"
    assert library.select("pkg:pypi/cryptography").book.version == "50.0.2"
    assert library.select("cryptography==49.0.0").book.name == "pypi_cryptography_49.0.0"
    assert library.select("cryptography@50").kind == "prefix"


def test_a_purl_is_a_library_everywhere_a_library_name_goes(home: Path) -> None:
    service.forget()
    build_zim(home / "zim", "f.zim", name="flask_site", tags="purl:pkg:pypi/flask@3.1.0")
    ref = parse_ref("pkg:pypi/flask@3.1.0§guide/config#timeouts¶2")
    assert ref == Ref("pkg:pypi/flask@3.1.0", "guide/config", "timeouts", 2), "the @ and / do not move the split"
    assert parse_ref("pkg:golang/github.com/spf13/cobra@v1.8.1::a/b") == Ref(
        "pkg:golang/github.com/spf13/cobra@v1.8.1", "a/b"
    )
    assert parse_ref("pkg:pypi/flask@3.1.0") == Ref("pkg:pypi/flask@3.1.0", "")
    assert parse_ref("guide/config", "pkg:pypi/flask@3.1.0") == Ref("pkg:pypi/flask@3.1.0", "guide/config")
    page = service.read("pkg:pypi/flask@3.1.0§guide/config#timeouts")
    assert page["ref"] == "flask_site§guide/config#timeouts", "the answer names the ZIM that was read"
    assert service.search("timeout flange spin", "pkg:pypi/flask@3.1.0")["libraries_searched"] == ["flask_site"]
    assert service.cite("pkg:pypi/flask@3.1.0§guide/config")["cite"].startswith("Acme Widgets Docs [flask_site]")
    assert service.resolve("pkg:pypi/flask@3.1.0")["name"] == "flask_site"


# --- editions are not versions ---------------------------------------------------------------------------------


def test_prune_never_treats_versions_as_editions_of_each_other(home: Path) -> None:
    service.forget()
    for version, date in (("v1.0", "2026-06-01"), ("v1.1", "2026-07-01"), ("v2.0", "2026-08-01")):
        name = f"acme_{version}"
        managed(build_zim(home / "zim", f"{name}.zim", name=name, title=f"Acme {version}", date=date))
    plan = manage.prune(keep=1)
    assert plan["files"] == [], "three versions are three libraries, each with its one edition"
    managed(build_zim(home / "zim", "acme_v1.0_old.zim", name="acme_v1.0", title="Acme v1.0", date="2026-01-01"))
    plan = manage.prune(keep=1)
    assert [Path(i["file"]).name for i in plan["files"]] == ["acme_v1.0_old.zim"], "the older EDITION of v1.0 only"
    assert (home / "zim" / "acme_v1.1.zim").exists()


def test_remove_will_not_pick_a_version_for_you(home: Path) -> None:
    versions(home, COBRA, ["v1.8.1", "v1.10.2"])
    with pytest.raises(ZimloreError, match="2 versions installed") as caught:
        manage.remove("cobra")
    assert caught.value.extra["versions"] == ["v1.10.2", "v1.8.1"]
    one = manage.remove("cobra v1.8.1")
    assert [Path(i["file"]).name for i in one["files"]] == [f"{COBRA}_v1.8.1.zim"]
    both = manage.remove("cobra", all_versions=True)
    assert len(both["files"]) == 2
    assert len(manage.verify("cobra", hash_files=False)["files"]) == 2, "verify checks every version of a family"


# --- what the listings and tools show --------------------------------------------------------------------------


def test_the_listing_collapses_a_family_and_all_versions_shows_every_name(home: Path) -> None:
    versions(home, COBRA, ["v1.8.1", "v1.10.2"])
    build_zim(home / "zim", "f.zim", name="devdocs_en_flask", title="Flask Docs")
    listing = service.libraries()
    rows = {r["name"]: r for r in listing["libraries"]}
    assert listing["total"] == 2 and set(rows) == {f"{COBRA}_v1.10.2", "devdocs_en_flask"}
    cobra = rows[f"{COBRA}_v1.10.2"]
    assert (cobra["version"], cobra["versions"], cobra["family"]) == ("v1.10.2", ["v1.10.2", "v1.8.1"], COBRA)
    assert not {"version", "versions", "family"} & set(rows["devdocs_en_flask"]), "no key where there is nothing"
    every = service.libraries(all_versions=True)
    assert every["total"] == 3 and all("versions" not in r for r in every["libraries"])
    assert service.libraries("cobra")["libraries"][0]["versions"] == ["v1.10.2", "v1.8.1"]


def test_cli_list_shows_the_family_with_its_versions_collapsed(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    versions(home, "golang_cobra", ["v1.8.1", "v1.10.2"])
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert out.count("golang_cobra") == 1 and "golang_cobra [v1.10.2, v1.8.1]  " in out
    assert cli.main(["list", "--all-versions"]) == 0
    out = capsys.readouterr().out
    assert "golang_cobra_v1.10.2  " in out and "golang_cobra_v1.8.1  " in out
    assert cli.main(["resolve", "golang_cobra", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["other_versions"] == ["v1.8.1"]


def test_resolve_says_which_version_which_match_and_what_else_is_installed(home: Path) -> None:
    versions(home, COBRA, ["v1.8.1", "v1.10.2"])
    newest = service.resolve("cobra")
    assert newest["version"]["upstream"] == "v1.10.2" and newest["version"]["selected"] == "newest"
    assert newest["other_versions"] == ["v1.8.1"] and "requested" not in newest["version"]
    older = service.resolve("cobra 1.8")
    assert (older["version"]["upstream"], older["version"]["selected"]) == ("v1.8.1", "prefix")
    assert older["version"]["requested"] == "1.8" and older["other_versions"] == ["v1.10.2"]
    assert older["version"]["pinned_by"] == "version in the Name"
    with pytest.raises(LibraryNotFound) as missing:
        service.resolve("cobra 9")
    assert "obtainable" not in missing.value.extra and "snapshot_hint" not in missing.value.extra, "it IS installed"


def test_search_over_every_library_reads_each_package_once(home: Path) -> None:
    versions(home, COBRA, ["v1.8.1", "v1.10.2"])
    result = service.search("kettle")
    assert result["libraries_searched"] == [f"{COBRA}_v1.10.2"]
    assert service.search("kettle", "cobra v1.8.1")["libraries_searched"] == [f"{COBRA}_v1.8.1"]


def test_the_mcp_tools_take_a_version_a_purl_and_all_versions(home: Path) -> None:
    versions(home, COBRA, ["v1.8.1", "v1.10.2"])
    server = contract_server()
    resolved = tool_text(server, "zim_resolve", name="cobra v1.8.1")
    assert resolved.startswith(f"{COBRA}_v1.8.1") and "also installed: v1.10.2" in resolved
    listed = tool_text(server, "zim_libraries")
    assert f"{COBRA} [v1.10.2, v1.8.1]  " in listed and listed.count(COBRA) == 1
    assert tool_text(server, "zim_libraries", all_versions=True).startswith("2 installed")
    missing = tool_error(server, "zim_resolve", name="cobra 7")
    assert "v1.8.1" in missing["error"] and "zim_libraries" in missing["hint"] and "action" not in missing

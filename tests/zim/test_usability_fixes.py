"""Fixes from an independent usability test: a model used the real server with only its descriptions (see
`ROADMAP.md`, `zl.mcp_usability_*`). Every test here failed against the code before the fix."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import zimfixture
from zimfixture import build_zim, contract_server, shell, tool_error

from primarysource.zim import cli, library, mcp, service, snapshot
from primarysource.zim.errors import ZimloreError

anyio = pytest.importorskip("anyio")

BOOK = "acme_en_widgets"

# A page of 96 blocks: over the new threshold (60), under the old one (200).
MEDIUM = shell(
    "<h1>Medium Manual</h1><p>Overview of the page.</p>"
    + "".join(
        f"<section id='{anchor}'><h2>{heading}</h2><p>{lead}</p>{zimfixture._filler(anchor, 22)}</section>"
        for anchor, heading, lead in [
            ("alpha", "Alpha", "Alpha is first."),
            ("beta", "Beta", "The wibblesprocket must be primed before the gadget spins."),
            ("gamma", "Gamma", "Gamma is last."),
            ("delta", "Delta", "Delta closes."),
        ]
    ),
    "Medium Manual",
)


def _write_snapshot(names: list[tuple[str, str]]) -> None:
    entries = [
        {
            "name": name,
            "title": title,
            "date": "2026-10-01",
            "language": "eng",
            "summary": "",
            "creator": "",
            "articles": 5,
            "approx_bytes": 1_000_000,
            "url": f"https://example.invalid/{name}.zim",
            "tags": [],
        }
        for name, title in names
    ]
    document = {
        "schema": snapshot.SCHEMA,
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_results": len(entries),
        "entries": entries,
    }
    snapshot.path().write_text(json.dumps(document), encoding="utf-8")


def _error(tool: str, **arguments: Any) -> dict[str, str]:
    """A failing tool as a client sees it: the `error:`, `hint:` and `action:` lines."""
    return tool_error(contract_server(), tool, **arguments)


# --- F2: a search that found only partial matches says so -------------------------------------------------------

PARTIAL = "how do the automated gaskets and sprockets work"  # 'automated' occurs nowhere: every hit is partial


def test_a_search_whose_hits_are_all_partial_is_low_confidence_and_offers_the_catalogue(acme: Path) -> None:
    _write_snapshot([("devdocs_en_gaskets", "Gaskets Docs"), ("devdocs_en_other", "Other Docs")])
    result = service.search(PARTIAL, "acme")
    assert {h["match"] for h in result["hits"]} == {"some terms"}
    assert result["confidence"] == "low"
    assert "no hit matched all your words" in result["note"] and "zim_available" in result["note"]
    assert [row["name"] for row in result["obtainable"]] == ["devdocs_en_gaskets"], "matched by a query word"
    assert "snapshot_age_days" in result


def test_low_confidence_never_fails_for_want_of_a_snapshot_or_touches_the_network(
    acme: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.request

    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("the network was touched")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    result = service.search(PARTIAL, "acme")
    assert result["confidence"] == "low" and "obtainable" not in result and "snapshot_hint" not in result
    snapshot.path().write_text("{not json", encoding="utf-8")
    assert service.search(PARTIAL, "acme")["confidence"] == "low", "an unusable snapshot is no reason to fail"


def test_a_full_match_or_an_exact_title_carries_no_low_confidence(acme: Path) -> None:
    assert "confidence" not in service.search("gaskets sprockets", "acme")
    assert "confidence" not in service.search("Installing Acme Widgets", "acme"), "an exact title is not a guess"


def test_an_exact_title_is_sure_where_there_is_no_full_text_index_and_a_partial_title_is_not(home: Path) -> None:
    service.forget()
    build_zim(home / "zim", fulltext=False)
    exact = service.search("Installing Acme Widgets", "acme")
    assert [h["match"] for h in exact["hits"]][0] == "title" and "confidence" not in exact
    partial = service.search("installing widgets", "acme")
    assert partial["hits"] and partial["confidence"] == "low", "title matches that are not the title are guesses"


def test_a_search_that_matches_nothing_is_low_confidence_too(acme: Path) -> None:
    result = service.search("qqqqzzzz", "acme")
    assert result["hits"] == [] and result["confidence"] == "low"


def test_the_search_description_defines_every_match_value() -> None:
    text = " ".join(next(t for t in anyio.run(mcp.build().list_tools) if t.name == "zim_search").description.split())
    assert "[full-text]" in text and "[some terms]" in text and "[title]" in text and "confidence" in text


# --- F3/F4: errors speak to the audience that reads them --------------------------------------------------------


def test_mcp_errors_name_tools_and_the_cli_keeps_its_commands(acme: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = _error("zim_search", query="x", library="cobol")
    assert "zim_libraries" in missing["hint"] and "zim_available" in missing["hint"]
    assert "primarysource zim list" not in missing["hint"] and "tool_hint" not in missing

    entry = _error("zim_read", ref="acme§nope/nope")
    assert (
        "zim_search" in entry["hint"] and "zim_outline" in entry["hint"] and "primarysource zim" not in entry["hint"]
    )
    assert "action" not in entry, "a model can fix this itself: no command for the human"

    anchor = _error("zim_read", ref="acme§guide/config#nope")
    assert "zim_outline" in anchor["hint"] and "acme_en_widgets§guide/config" in anchor["hint"]
    assert "primarysource zim" not in anchor["hint"]

    # The CLI's reader is the human: command wording, and none of the model-facing keys.
    with pytest.raises(ZimloreError) as caught:
        service.search("x", "cobol")
    cli_view = caught.value.as_dict()
    assert "primarysource zim list" in str(cli_view["hint"]) and "tool_hint" not in cli_view
    assert "snapshot_hint" in cli_view and "user_action" not in cli_view
    assert cli.main(["read", "acme§nope/nope"]) == 2
    assert "primarysource zim search" in capsys.readouterr().err


def test_without_a_snapshot_available_lists_the_installed_libraries_and_says_who_must_act(acme: Path) -> None:
    error = _error("zim_available", query="django")
    assert BOOK in error["error"], "'not installed' is answerable from the error alone"
    assert "ask the user" in error["hint"] and "primarysource zim catalog --refresh" in error["hint"]
    assert error["action"] == "primarysource zim catalog --refresh"
    assert "zimlore" not in error["hint"]


def test_a_missing_library_without_a_snapshot_asks_the_user(acme: Path) -> None:
    error = _error("zim_resolve", name="cobol")
    assert "ask the user" in error["hint"] and error["action"] == "primarysource zim catalog --refresh"
    assert "snapshot_hint" not in "".join(error.values()), "CLI wording does not go to a model"


# --- F5: ¶n inside a section is section-relative ----------------------------------------------------------------


def test_a_block_ref_with_an_anchor_counts_inside_the_section(acme: Path) -> None:
    page = service.read("acme§guide/config#timeouts")
    first = service.read("acme§guide/config#timeouts¶1")
    assert first["scope"] == "section" and first["content"].startswith("## Timeouts"), "¶1 is the section's heading"
    assert first["content"] == page["content"], "¶1 is the whole section"
    second = service.read("acme§guide/config#timeouts¶2", max_tokens=1)
    assert "timeout setting bounds" in second["content"]
    assert second["content"] in page["content"] and "Settings control widgets" not in second["content"]
    assert second["blocks"] == {"from": 2, "to": 2, "of": 3}
    assert second["cite"].endswith("entry guide/config#timeouts ¶2"), "the cite echoes what was read"
    assert second["ref"] == f"{BOOK}§guide/config#timeouts" and second["next"] == f"{BOOK}§guide/config#timeouts¶3"
    article = service.read("acme§guide/config¶2")
    assert "Settings control widgets" in article["content"], "without an anchor ¶n still counts the page"


def test_a_block_past_the_end_of_the_section_is_an_error_naming_the_section_size(acme: Path) -> None:
    with pytest.raises(ZimloreError, match="no ¶4") as caught:
        service.read("acme§guide/config#timeouts¶4")
    assert caught.value.extra["blocks"] == 3 and "#timeouts" in caught.value.message
    with pytest.raises(ZimloreError, match="no ¶4"):
        service.cite("acme§guide/config#timeouts¶4")
    assert service.cite("acme§guide/config#timeouts¶3")["cite"].endswith("#timeouts ¶3")
    with pytest.raises(ZimloreError, match="no ¶999"):
        service.cite("acme§guide/config¶999")


def test_an_empty_available_query_is_not_reported_as_a_missing_snapshot(acme: Path) -> None:
    with pytest.raises(ZimloreError, match="empty query") as caught:
        service.available("")
    assert "user_action" not in caught.value.extra and "installed" not in caught.value.extra


def test_the_read_description_says_what_a_pilcrow_counts() -> None:
    text = " ".join(next(t for t in anyio.run(mcp.build().list_tools) if t.name == "zim_read").description.split())
    assert "starts at the nth block" in text and "#anchor" in text


# --- F7: hits on medium pages -----------------------------------------------------------------------------------


def test_a_medium_page_hit_gets_a_section_and_every_hit_gets_its_block_count(home: Path) -> None:
    service.forget()
    build_zim(home / "zim", extra={"medium": MEDIUM})
    doc, _, _ = service.document(library.find("acme", library.scan()), "medium")
    assert 60 < len(doc.blocks) < 200, "the fixture sits between the old threshold and the new one"
    result = service.search("wibblesprocket primed before the gadget spins", "acme")
    hit = next(h for h in result["hits"] if h["ref"].endswith("§medium"))
    assert hit["section"]["anchor"] == "beta" and hit["blocks"] == len(doc.blocks)
    small = service.search("timeout flange spin", "acme")["hits"][0]
    assert "section" not in small and small["blocks"] > 1, "a short page has a count and no section"


# --- F8/F9: sizes and totals ------------------------------------------------------------------------------------


def test_a_cut_read_says_how_much_is_left_in_blocks_and_tokens(acme: Path) -> None:
    cut = service.read("acme§guide/config", max_tokens=60)
    assert cut["next"] and cut["remaining_blocks"] == cut["blocks"]["of"] - cut["blocks"]["to"]
    rest = service.read(cut["next"], max_tokens=8000)
    assert rest["next"] is None and "remaining_blocks" not in rest
    assert abs(cut["remaining_tokens"] - service.tokens(rest["content"])) <= cut["remaining_blocks"], (
        "the estimate is the tokens of the blocks still to come, give or take the joins between them"
    )


def test_an_outline_states_its_total_and_is_truncated_whenever_next_is_present(acme: Path) -> None:
    whole = service.outline("acme§guide/config")
    assert whole["total"] == len(whole["outline"]) and whole["truncated"] is False
    page = service.outline("acme§guide/config", limit=2)
    assert page["total"] == whole["total"] > 2
    assert "next" in page and page["truncated"] is True, "rows are missing, so it is truncated"
    listing = service.outline("acme", limit=2)
    assert "next" in listing and listing["truncated"] is True


# --- F10: a mistyped anchor gets the closest anchors -------------------------------------------------------------


def test_a_mistyped_anchor_names_the_three_closest_anchors_not_the_first_25(acme: Path) -> None:
    with pytest.raises(ZimloreError) as caught:
        service.read("acme§guide/config#widget.runn")
    close: list[str] = caught.value.extra["did_you_mean"]  # type: ignore[assignment]
    assert close[0] == f"{BOOK}§guide/config#widget.run" and len(close) <= 3
    assert "anchors" not in caught.value.extra
    with pytest.raises(ZimloreError) as far:
        service.read("acme§guide/config#qqqqqqqq")
    assert "did_you_mean" not in far.value.extra, "no near anchor, no noise"


# --- F11/F12: budgets are bounded -------------------------------------------------------------------------------


def test_max_tokens_is_clamped_at_8000_on_every_tool_that_takes_it(acme: Path) -> None:
    assert service.read("acme§guide/config", max_tokens=100_000)["clamped"] == {"max_tokens": 8000}
    assert service.search("kettle", "acme", max_tokens=100_000)["clamped"] == {"max_tokens": 8000}
    assert service.links("acme§guide/install", max_tokens=100_000)["clamped"] == {"max_tokens": 8000}
    assert service.outline("acme§guide/config", max_tokens=100_000)["clamped"] == {"max_tokens": 8000}
    assert "clamped" not in service.read("acme§guide/config", max_tokens=8000)


def test_the_cite_description_says_reads_already_carry_one() -> None:
    text = " ".join(next(t for t in anyio.run(mcp.build().list_tools) if t.name == "zim_cite").description.split())
    assert "zim_read footers already carry" in text


# --- F13: the instructions open with a decision tree --------------------------------------------------------------


def test_the_instructions_open_with_the_decision_tree_and_stay_short() -> None:
    text = mcp.INSTRUCTIONS
    assert len(text) < 2200
    order = [
        text.index(word)
        for word in ("zim_available", "zim_libraries", "best section ref", "confidence: low", "Refs:")
    ]
    assert order == sorted(order), "decisions first, then refs, paging, warnings and the security note"
    assert text.index("warning") > text.index("Refs:") and "untrusted data" in text

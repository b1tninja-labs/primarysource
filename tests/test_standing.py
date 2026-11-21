"""A read names a later edition from the catalogue the collection already has."""

from __future__ import annotations

from primarysource.bluetooth.catalogue import Spec
from primarysource.bluetooth.library import standing_for
from primarysource.ieee.catalogue import POSIX_2024, Edition, standing_of
from primarysource.itu import sources
from primarysource.nist.spec import publication_standing
from primarysource.pdfcorpus.models import Document
from primarysource.rfc.cite import relation_clause
from primarysource.standing import Aside, dated_family, notes, warning
from primarysource.standing import Edition as Standing


def test_a_superseded_edition_names_the_current_text() -> None:
    old = Standing("X.690#2008-11", 200811, current=False)
    new = Standing("X.690#2021-02", 202102, current=True)
    text = warning(old, (old, new))
    assert text == "this edition is not current; current text: X.690#2021-02"


def test_a_later_edition_that_is_not_imported_is_still_named() -> None:
    older = Standing("ecma:119@5", 5, imported=True)
    newer = Standing("ecma:119@6", 6, imported=False)
    text = warning(older, (older, newer))
    assert text == "a later edition is recorded: ecma:119@6 (not imported)"


def test_an_amendment_beside_the_edition_is_not_applied() -> None:
    base = Standing("iso:9899@2024", 2024)
    text = warning(base, (base,), (Aside("iso:9899@2024+amd1-2026"),))
    assert text == "separate text, not applied to this edition: iso:9899@2024+amd1-2026"


def test_dated_ids_of_one_number_name_the_later_year_and_a_supplement() -> None:
    def split(token: str) -> tuple[str, str | None]:
        number, _, rest = token.partition("@")
        return number, rest or None

    keys = ["7816-3@2006", "7816-3@2006+amd1-2006", "7816-3@2020"]
    text = dated_family("7816-3@2006", keys, split, "iso")
    assert "a later edition is recorded: iso:7816-3@2020" in text
    assert "iso:7816-3@2006+amd1-2006" in text
    supplement = dated_family("7816-3@2006+amd1-2006", keys, split, "iso")
    assert supplement.startswith("supplement of iso:7816-3@2006")
    assert "iso:7816-3@2020" in supplement


def test_the_itu_registry_names_the_in_force_edition_and_its_erratum() -> None:
    old = warning_of("X.690#2008-11")
    assert "current text: X.690#2021-02" in old
    assert "erratum" not in old
    current = warning_of("X.690#2021-02")
    assert current == "separate text, not applied to this edition: X.690#2021-02!erratum-1"
    assert sources.standing_of(sources.resolve("X.680")) == ""


def warning_of(key: str) -> str:
    return sources.standing_of(sources.resolve(key))


def test_the_posix_edition_in_force_has_no_successor_in_the_catalogue() -> None:
    assert standing_of(POSIX_2024) == ""
    older = Edition(
        collection="posix",
        id="posix-2017",
        designations=("IEEE Std 1003.1-2017",),
        title="",
        publisher="",
        edition_date="",
        page_url="",
        source_url=None,
        archive=None,
        sha256=None,
        size=None,
    )
    assert "1003.1-2024" in standing_of(older)


def test_a_search_page_names_each_older_document_once() -> None:
    lines = notes(
        [
            ("iso:7816-3@2006", "a later edition is recorded: iso:7816-3@2020"),
            ("iso:7816-3@2006", "a later edition is recorded: iso:7816-3@2020"),
            ("iso:9899@2024", ""),
        ]
    )
    assert lines == ["iso:7816-3@2006: a later edition is recorded: iso:7816-3@2020"]


def test_a_citation_names_the_documents_that_update_this_one() -> None:
    assert relation_clause({"updates": ["RFC5280"], "updated_by": ["RFC9598"]}) == (
        "updates RFC5280 | updated by RFC9598"
    )


def _spec(doc: str, title: str, version: str, status: str) -> Spec:
    return Spec(doc, title, version, "profile", status, "https://example.invalid/")


def test_an_older_bluetooth_version_names_the_later_adopted_one() -> None:
    title = "Battery Service"
    specs = [
        _spec("battery-service-1-0", title, "1.0", "Adopted"),
        _spec("battery-service-1-0-1", title, "1.0.1", "Adopted"),
        _spec("battery-service-1-1", title, "1.1", "Draft"),
    ]
    text = standing_for("battery-service-1-0", specs, {"battery-service-1-0"})
    assert text == "a later edition is recorded: bluetooth:battery-service-1-0-1 (not imported)"
    draft = standing_for("battery-service-1-1", specs, set())
    assert "current text: bluetooth:battery-service-1-0-1" in draft


def test_an_older_nist_revision_names_the_default_document() -> None:
    older = Document(
        doc_id="sp800-53r4",
        number="800-53 Rev. 4",
        title="",
        date="2015-01",
        status="final",
        url="",
        sha256="0" * 64,
        text_file="sp800-53r4.txt",
        sections=(),
    )
    text = publication_standing(older, {"800-53": "sp800-53r5"})
    assert text == "this edition is not current; current text: sp800-53r5"
    assert publication_standing(older, {"800-53": "sp800-53r4"}) == ""
    addendum = Document(
        doc_id="sp800-38a-add",
        number="NIST SP 800-38A",
        title="",
        date="2010-10",
        status="final",
        url="",
        sha256="0" * 64,
        text_file="sp800-38a-add.txt",
        sections=(),
    )
    assert publication_standing(addendum, {"800-38A": "sp800-38a"}) == ""
    oscal = Document(
        doc_id="sp800-53r5-oscal",
        number="800-53 Rev. 5",
        title="",
        date="2020-09",
        status="final",
        url="",
        sha256="0" * 64,
        text_file="sp800-53r5-oscal.txt",
        sections=(),
    )
    assert publication_standing(oscal, {"800-53": "sp800-53r5"}) == ""

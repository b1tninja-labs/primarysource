"""Names, refs, licence legends, XML root facts, the life-cycle verdict and the tracked catalogue."""

from __future__ import annotations

import json
from datetime import date

import pytest
from draft_fixture import HOSTILE_XML, build_txt, v2_xml, v3_xml

from primarysource.draft import catalogue, licence, names, status, xmlmeta
from primarysource.draft.status import Status
from primarysource.errors import LibError


def test_a_trailing_two_digit_group_is_the_revision() -> None:
    assert names.split_doc("draft-ietf-sidrops-8210bis-17") == ("draft-ietf-sidrops-8210bis", "17")
    assert names.split_doc("draft-ietf-sidrops-8210bis") == ("draft-ietf-sidrops-8210bis", None)
    assert names.split_doc("DRAFT-Koch-LibrePGP-06") == ("draft-koch-librepgp", "06")
    # a name that itself ends in two digits is only unambiguous with its revision
    assert names.split_doc("draft-foo-12") == ("draft-foo", "12")
    assert names.split_doc("draft-foo-12-00") == ("draft-foo-12", "00")
    assert names.split_doc("draft-foo-2024") == ("draft-foo-2024", None)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "rfc9000",
        "draft-",
        "draft--x",
        "draft-x-",
        "../draft-x-00",
        "draft-x/../../etc/passwd",
        "draft-x%2e%2e",
        "draft-x\n-00",
        "draft-x y",
        "draft-" + "a" * 200,
        "draft-x-é",
    ],
)
def test_a_hostile_name_never_gets_as_far_as_a_url_or_a_path(bad: str) -> None:
    with pytest.raises(LibError):
        names.split_doc(bad)
    with pytest.raises(LibError):
        names.parse_name(bad)


def test_the_ref_grammar_carries_name_revision_section_and_paragraph() -> None:
    ref = names.GRAMMAR.parse("draft-ietf-sidrops-8210bis-17§5.1¶2")
    assert (ref.doc, ref.section, ref.para) == ("draft-ietf-sidrops-8210bis-17", "5.1", 2)
    assert names.GRAMMAR.parse("draft-x-y-03§security-considerations").section == "security-considerations"
    assert names.GRAMMAR.parse("draft-x-y-03§A.2").section == "A.2"
    assert names.GRAMMAR.parse("draft-x-y-03:10-20").lines == (10, 20)
    assert names.GRAMMAR.parse("draft-x-y").section is None


def test_revisions_are_two_digits() -> None:
    assert names.with_revision("draft-x-y", "07") == "draft-x-y-07"
    for bad in ("7", "007", "ab", "0 ", ""):
        with pytest.raises(LibError):
            names.valid_revision(bad)


def test_the_legend_in_the_text_is_read_whatever_the_xml_says() -> None:
    plain = licence.detect(build_txt(year=2026))
    assert (plain.restriction, plain.year) == (licence.NONE, 2026)
    nomod = licence.detect(
        build_txt(
            legend="This document may not be modified, and derivative works of it may not be\n"
            "created, except to format it."
        )
    )
    assert nomod.restriction == licence.NO_MODIFICATION
    noderiv = licence.detect(
        build_txt(
            legend="This document may not be modified, and derivative works of it may not be created, and it\n"
            "may not be published except as an Internet-Draft."
        )
    )
    assert noderiv.restriction == licence.NO_DERIVATIVES
    pre = licence.detect(
        build_txt(
            legend="This document may contain material from IETF Documents or IETF Contributions published or "
            "made publicly\navailable before November 10, 2008."
        )
    )
    assert pre.restriction == licence.PRE_5378
    assert (
        licence.detect("no legend here", xml_ipr="noModificationTrust200902").restriction == licence.NO_MODIFICATION
    )
    assert "forbids modification" in nomod.summary()


def test_a_draft_older_than_tlp5_is_not_described_as_covered_by_it() -> None:
    old = licence.detect(build_txt(year=2013)).summary()
    assert "before the Trust Legal Provisions 5.0" in old
    assert "TLP 5.0 §1.c" in old
    assert "§3.c applies" in licence.detect(build_txt(year=2026)).summary()
    assert "no IETF Trust copyright notice" in licence.detect("nothing").summary()


def test_xml_root_facts_come_from_the_start_tag_only() -> None:
    v2 = xmlmeta.inspect(v2_xml(ipr="noModificationTrust200902"))
    assert (v2.state, v2.ipr, v2.doc_name, v2.category) == (
        xmlmeta.V2,
        "noModificationTrust200902",
        "draft-example-frob-proto-03",
        "std",
    )
    assert xmlmeta.inspect(v3_xml()).state == xmlmeta.V3


def test_hostile_xml_is_refused_or_reported_never_expanded() -> None:
    assert xmlmeta.inspect(HOSTILE_XML).state == xmlmeta.REFUSED
    assert xmlmeta.inspect(b'<?xml version="1.0"?><!DOCTYPE rfc [<!ELEMENT rfc ANY>]><rfc/>').state == xmlmeta.REFUSED
    assert xmlmeta.inspect(b"<html><body/></html>").state == xmlmeta.UNPARSEABLE
    assert xmlmeta.inspect(b"<rfc").state == xmlmeta.UNPARSEABLE
    assert xmlmeta.inspect(b"").state == xmlmeta.UNPARSEABLE
    assert xmlmeta.inspect(b"\x00\x01\x02 not xml").state == xmlmeta.UNPARSEABLE
    huge = b'<rfc ipr="' + b"x" * 100_000 + b'"/>'
    assert len(xmlmeta.inspect(huge).ipr) <= 200


def _status(state: str, expires: str = "2099-01-01 00:00:00", **extra: object) -> Status:
    base: dict[str, object] = {
        "name": "draft-x-y", "title": "T", "state": state, "rev": "03", "expires": expires, "replaced_by": (),
        "became_rfc": None, "revisions": (("03", "2026-01-01"),), "authors": (), "group": "", "stream": "",
        "pages": None, "checked": "2026-11-01T00:00:00+00:00",
    }  # fmt: skip
    base.update(extra)
    return Status(**base)  # type: ignore[arg-type]


def test_every_datatracker_state_gets_a_verdict_a_caller_cannot_miss() -> None:
    today = date(2026, 11, 13)
    assert status.lifecycle(_status("Active"), today).alive
    expired = status.lifecycle(_status("Expired", "2024-05-08 19:45:10"), today)
    assert (expired.level, expired.alive) == (status.EXPIRED, False)
    assert "2024-05-08" in expired.text
    replaced = status.lifecycle(_status("Replaced", replaced_by=("draft-a-b",)), today)
    assert (replaced.level, replaced.alive) == (status.REPLACED, False)
    assert "draft-a-b" in replaced.text
    rfc = status.lifecycle(_status("RFC", became_rfc="RFC9999"), today)
    assert (rfc.level, rfc.alive) == (status.RFC, False)
    assert "cite the RFC" in rfc.text
    assert status.lifecycle(_status("Withdrawn by Submitter"), today).level == status.WITHDRAWN
    assert status.lifecycle(_status("Withdrawn by IETF"), today).level == status.WITHDRAWN
    assert status.lifecycle(_status("Somewhere Else"), today).level == status.UNKNOWN


def test_an_active_draft_past_its_expiry_date_is_reported_expired() -> None:
    late = status.lifecycle(_status("Active", "2026-05-01 00:00:00"), date(2026, 11, 13))
    assert (late.level, late.alive) == (status.EXPIRED, False)
    assert "past its expiry date" in late.text


def test_a_draft_that_became_an_rfc_is_never_alive_even_if_the_state_lags() -> None:
    assert status.lifecycle(_status("Active", became_rfc="RFC9999"), date(2026, 11, 13)).level == status.RFC


def test_a_status_snapshot_round_trips_and_a_damaged_one_names_its_remedy() -> None:
    snapshot = _status("Replaced", replaced_by=("draft-a-b",), became_rfc=None, pages=7)
    assert Status.from_json(snapshot.to_json()) == snapshot
    with pytest.raises(LibError, match="damaged") as caught:
        Status.from_json('{"name": 3}')
    assert "refresh" in caught.value.action
    assert status.staleness(snapshot, date(2026, 11, 13)) == 12


def test_the_tracked_catalogue_is_well_formed_and_pins_the_revision_it_read() -> None:
    assert catalogue.TERMS.placement == "volume"
    assert "draft-ietf-sidrops-8210bis" in catalogue.TRACKED
    for tracked in catalogue.TRACKED.values():
        assert tracked.rev_read in tracked.pins, tracked.name
        assert tracked.pins[tracked.rev_read].txt is not None
        assert tracked.why and tracked.checked and tracked.state
        assert len(tracked.why) < 300  # a reason, never document text
    assert catalogue.pin_for("draft-ietf-sidrops-8210bis", "29") is not None
    assert catalogue.pin_for("draft-ietf-sidrops-8210bis", "01") is None
    with pytest.raises(LibError, match="not in the tracked catalogue"):
        catalogue.tracked("draft-nobody-nothing")


def test_a_malformed_catalogue_is_a_packaging_bug_and_raises() -> None:
    good = json.dumps(
        {
            "schema": 1,
            "terms": {"licence": "l", "placement": "volume", "terms_url": "u", "terms_read": "d", "summary": "s"},
            "drafts": [],
        }
    )
    catalogue.parse(good)
    for broken in (
        good.replace('"schema": 1', '"schema": 2'),
        good.replace('"volume"', '"image"'),
    ):
        with pytest.raises(ValueError):
            catalogue.parse(broken)
    entry: dict[str, object] = {
        "name": "draft-a-b",
        "why": "w",
        "consumers": [],
        "rev_read": "01",
        "state": "Active",
        "replaced_by": [],
        "became_rfc": None,
        "expires": "",
        "checked": "",
        "pins": {"01": {"txt": "nothex"}},
    }
    doc = json.loads(good)
    doc["drafts"] = [entry]
    with pytest.raises(ValueError, match="sha256"):
        catalogue.parse(json.dumps(doc))

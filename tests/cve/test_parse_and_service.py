from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from primarysource.cve import service, store, sync
from primarysource.cve.errors import CvelibError
from primarysource.cve.parse import parse_cve_record, parse_epss, parse_kev

from .conftest import (
    CISA_ADP,
    CVSS_31,
    KERNEL_BACKPORT_ID,
    KERNEL_ID,
    OLD_KERNEL_ID,
    REJECTED_ID,
    WEB_ID,
    WILDCARD_ID,
    cve_doc,
)


def test_cve_record_flattened_with_adp_metrics_and_ssvc() -> None:
    record = parse_cve_record(cve_doc(WEB_ID, metrics=[CVSS_31], adp=[CISA_ADP]))
    assert record is not None
    assert [m.label for m in record.metrics] == ["CNA:acme", "ADP:CISA-ADP"]
    assert record.ssvc is not None and record.ssvc["exploitation"] == "active"


def test_legacy_cveid_spelling_in_old_kernel_files() -> None:
    doc = cve_doc("CVE-2019-25161")
    doc["cveMetadata"]["cveID"] = doc["cveMetadata"].pop("cveId")
    record = parse_cve_record(doc)
    assert record is not None and record.cve == "CVE-2019-25161"


def test_epss_header_and_rows() -> None:
    body = gzip.compress(b"#model_version:v1,score_date:2026-01-05T00:00:00Z\ncve,epss,percentile\nCVE-1-1,0.5,0.9\n")
    assert parse_epss(body) == ("v1", "2026-01-05T00:00:00Z", [("CVE-1-1", 0.5, 0.9)])


def test_kev_shape_rejected_when_wrong() -> None:
    with pytest.raises(CvelibError):
        parse_kev(b'{"nope": 1}')


def test_missing_corpus_is_an_error_naming_the_fix(home: Path) -> None:
    with pytest.raises(CvelibError) as caught:
        service.search("anything")
    assert caught.value.action == "primarysource cve sync"
    assert service.info()["status"] == "not_synced"


def test_partial_corpus_reports_what_is_missing(home: Path, tmp_path: Path) -> None:
    from .conftest import kernel_tree

    (tmp_path / "s").mkdir()
    conn = store.open_write()
    sync.sync_kernel(conn, kernel_tree(tmp_path / "s"))
    conn.close()
    answer = service.read(KERNEL_ID)
    assert any(line.startswith("kev:") for line in answer["partial"])
    assert answer["kev"]["status"] == "unknown"


def test_merged_record_attributes_each_field(synced: Path) -> None:
    answer = service.read(KERNEL_ID)
    # The kernel repository's own copy wins for the description of a kernel CVE.
    assert answer["description"].startswith("In the Linux kernel")
    assert answer["description_source"].startswith("kernel CNA")
    assert answer["kernel"]["fixed_in"]["5.15"] == "5.15.5"
    assert answer["kev"]["status"] == "not_listed"
    assert answer["epss"]["score"] == 0.002
    assert "CISA" in answer["cvss"]["preferred"]["label"]
    assert "cve-list" in json.dumps(answer["sources_used"]).lower().replace(" ", "-")
    assert "partial" not in answer


def test_cna_cvss_preferred_over_adp(synced: Path) -> None:
    answer = service.read(WEB_ID)
    assert answer["cvss"]["preferred"]["label"] == "CNA:acme"
    assert answer["cvss"]["preferred"]["score"] == 7.8
    assert answer["kev"]["status"] == "listed"
    assert answer["kev"]["date_added"] == "2026-01-04"
    assert answer["next"] == f"{WEB_ID}§references¶1"
    assert answer["ssvc"]["exploitation"] == "active"


def test_references_page_and_follow_next(synced: Path) -> None:
    first = service.read(f"{WEB_ID}§references", max_tokens=200)
    assert first["total"] == 30
    assert first["next"].startswith(f"{WEB_ID}§references¶")
    second = service.read(first["next"], max_tokens=200)
    assert second["start"] == len(first["items"]) + 1
    assert set(first["items"]).isdisjoint(second["items"])


def test_search_finds_and_filters(synced: Path) -> None:
    hits = service.search("authentication bypass")["hits"]
    assert hits[0]["ref"] == WEB_ID and hits[0]["kev"] is True
    assert service.search("Widget", kernel_only=True)["hits"] == []
    assert [h["ref"] for h in service.search("sock", kernel_only=True)["hits"]] == [KERNEL_ID]


def test_search_by_source_file_path(synced: Path) -> None:
    assert [h["ref"] for h in service.search("net/invented/sock.c")["hits"]] == [KERNEL_ID]


def test_search_exact_id_and_relaxed_and_rejected_hidden(synced: Path) -> None:
    assert service.search(WEB_ID)["hits"][0]["ref"] == WEB_ID
    relaxed = service.search("Widget unrelatedword")
    assert relaxed["relaxed"] and relaxed["hits"][0]["ref"] == WEB_ID
    assert REJECTED_ID not in [h["ref"] for h in service.search("Widget rejected")["hits"]]


def test_empty_hits_mean_no_match_not_no_corpus(synced: Path) -> None:
    assert service.search("zzzqqqxyzzy")["hits"] == []


def test_kev_status_listing_and_filter(synced: Path) -> None:
    assert service.kev(WEB_ID)["status"] == "listed"
    assert service.kev(KERNEL_ID)["status"] == "not_listed"
    assert service.kev(vendor="acme")["total"] == 1
    assert service.kev(since="2026-02-01")["total"] == 0


def test_unknown_cve_explained(synced: Path) -> None:
    with pytest.raises(CvelibError):
        service.read("CVE-2099-99999")


def test_kernel_question_prefers_kernel_cna_over_ranges(synced: Path) -> None:
    fixed = service.kernel_check(KERNEL_BACKPORT_ID, "6.18.62")
    assert fixed["verdict"] == "not_affected"
    assert fixed["reason"] == "fixed_on_branch"
    assert fixed["source"].startswith("kernel CNA")
    assert fixed["confidence"] == "high"


def test_kernel_question_dead_branch_zero(synced: Path) -> None:
    answer = service.kernel_check(KERNEL_ID, "6.18.62")
    assert answer["verdict"] == "not_affected"


def test_kernel_question_non_kernel_cna_is_hedged(synced: Path) -> None:
    inside = service.kernel_check(OLD_KERNEL_ID, "5.8.1")
    assert inside["verdict"] == "possibly_affected"
    assert inside["confidence"] == "low"
    assert inside["source"].startswith("CVE List")
    outside = service.kernel_check(OLD_KERNEL_ID, "6.18.62")
    assert outside["verdict"] == "unknown"


def test_wildcard_record_is_not_evidence(synced: Path) -> None:
    answer = service.kernel_check(WILDCARD_ID, "6.18.62")
    assert answer["verdict"] == "unknown"
    assert answer["reason"] == "wildcard_record"


def test_kernel_list_and_filters(synced: Path) -> None:
    listing = service.kernel_list("5.15.2")
    assert {item["ref"] for item in listing["items"]} == {KERNEL_ID, KERNEL_BACKPORT_ID}
    assert listing["assessed"] == 2
    assert [i["ref"] for i in service.kernel_list("5.15.2", path="net/invented")["items"]] == [KERNEL_ID]
    assert service.kernel_list("6.18.62")["affected_total"] == 0


def test_rejected_by_kernel_cna_surfaces_state(synced: Path) -> None:
    answer = service.read("CVE-2026-1003")
    assert answer["state"] == "REJECTED"


def test_failed_source_is_reported_and_others_kept(home: Path) -> None:
    def explode(url: str, headers: dict[str, str]) -> sync.Response:
        raise CvelibError("boom", "retry")

    conn = store.open_write()
    try:
        with pytest.raises(CvelibError):
            sync.sync_kev(conn, fetch=explode)
        store.mark_source(conn, "kev", "failed", detail="boom")
    finally:
        conn.close()
    with pytest.raises(CvelibError):
        service.kev("CVE-2025-2001")


def test_cvelist_delta_targets_stop_at_since() -> None:
    from datetime import UTC, datetime

    log = [
        {"fetchTime": "2026-01-03T00:00:00Z", "new": [{"githubLink": "u1"}], "updated": [{"githubLink": "u2"}]},
        {"fetchTime": "2026-01-01T00:00:00Z", "new": [{"githubLink": "u3"}], "updated": []},
    ]
    assert sync._delta_targets(log, datetime(2026, 1, 2, tzinfo=UTC)) == ["u1", "u2"]


def test_a_download_is_put_in_place_whole_or_not_at_all(tmp_path: Path) -> None:
    source = tmp_path / "in.bin"
    source.write_bytes(b"x" * 5000)
    target = tmp_path / "out" / "baseline.zip"
    sync.http_download(source.as_uri(), target)
    assert target.read_bytes() == b"x" * 5000 and not list(target.parent.glob("*.part"))
    other = tmp_path / "out" / "other.zip"
    with pytest.raises(CvelibError):
        sync.http_download((tmp_path / "missing.bin").as_uri(), other)
    assert not other.exists() and not list(other.parent.glob("*.part"))

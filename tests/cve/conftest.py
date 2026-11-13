"""A small invented corpus, built in a temporary directory. No upstream data is in this repository."""

from __future__ import annotations

import gzip
import json
import zipfile
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from primarysource.cve import config, store, sync
from primarysource.cve.sync import Response

KERNEL_ORG = config.KERNEL_ORG_ID


def cve_doc(
    cve: str,
    *,
    org: str = "aaaaaaaa-0000-0000-0000-000000000000",
    short: str = "acme",
    title: str = "",
    text: str = "An invented flaw used only for testing.",
    state: str = "PUBLISHED",
    updated: str = "2026-01-02T00:00:00.000Z",
    affected: list[dict[str, Any]] | None = None,
    metrics: list[dict[str, Any]] | None = None,
    adp: list[dict[str, Any]] | None = None,
    refs: list[str] | None = None,
) -> dict[str, Any]:
    cna: dict[str, Any] = {
        "providerMetadata": {"orgId": org, "shortName": short},
        "title": title,
        "descriptions": [{"lang": "en", "value": text}],
        "affected": affected or [],
        "references": [{"url": url} for url in (refs or ["https://example.invalid/advisory"])],
    }
    if metrics:
        cna["metrics"] = metrics
    containers: dict[str, Any] = {"cna": cna}
    if adp:
        containers["adp"] = adp
    return {
        "dataType": "CVE_RECORD",
        "dataVersion": "5.1",
        "cveMetadata": {
            "cveId": cve,
            "assignerOrgId": org,
            "assignerShortName": short,
            "state": state,
            "dateUpdated": updated,
            "datePublished": "2026-01-01T00:00:00.000Z",
        },
        "containers": containers,
    }


CVSS_31 = {
    "cvssV3_1": {
        "version": "3.1",
        "vectorString": "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
        "baseScore": 7.8,
        "baseSeverity": "HIGH",
    }
}
CISA_ADP = {
    "providerMetadata": {"shortName": "CISA-ADP"},
    "metrics": [
        {
            "cvssV3_1": {
                "version": "3.1",
                "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                "baseScore": 9.8,
                "baseSeverity": "CRITICAL",
            }
        },
        {
            "other": {
                "type": "ssvc",
                "content": {
                    "options": [{"Exploitation": "active"}, {"Automatable": "yes"}, {"Technical Impact": "total"}],
                    "version": "2.0.3",
                    "timestamp": "2026-01-03T00:00:00Z",
                },
            }
        },
    ],
}

KERNEL_ID = "CVE-2026-1001"  # the dead-branch trap
KERNEL_BACKPORT_ID = "CVE-2026-1002"  # fixed on 6.18.x, so mainline ranges would falsely flag it
OLD_KERNEL_ID = "CVE-2021-3001"  # kernel record with a CNA range, not from the kernel CNA
WILDCARD_ID = "CVE-2021-3002"  # kernel record with no range at all
WEB_ID = "CVE-2025-2001"  # general software, in KEV
REJECTED_ID = "CVE-2025-2002"


def kernel_tree(root: Path) -> Path:
    tree = root / "vulns"
    pub = tree / "cve" / "published" / "2026"
    rej = tree / "cve" / "rejected" / "2026"
    pub.mkdir(parents=True)
    rej.mkdir(parents=True)
    affected = [{"vendor": "Linux", "product": "Linux", "programFiles": ["net/invented/sock.c"]}]
    (pub / f"{KERNEL_ID}.json").write_text(
        json.dumps(
            cve_doc(
                KERNEL_ID,
                org=KERNEL_ORG,
                short="Linux",
                title="invented: sock leak",
                text="In the Linux kernel, an invented sock leak.",
                affected=affected,
            )
        ),
        encoding="utf-8",
    )
    (pub / f"{KERNEL_ID}.dyad").write_text(
        "# dyad version: 1.2.0\n5.14.15:aaaa:0:0\n5.15:bbbb:5.15.5:cccc\n5.15:bbbb:5.16:dddd\n", encoding="utf-8"
    )
    (pub / f"{KERNEL_BACKPORT_ID}.json").write_text(
        json.dumps(
            cve_doc(
                KERNEL_BACKPORT_ID,
                org=KERNEL_ORG,
                short="Linux",
                title="invented: pipe overflow",
                text="In the Linux kernel, an invented pipe overflow.",
                affected=[{"vendor": "Linux", "product": "Linux", "programFiles": ["fs/invented/pipe.c"]}],
            )
        ),
        encoding="utf-8",
    )
    (pub / f"{KERNEL_BACKPORT_ID}.dyad").write_text("4.14:eeee:6.18.22:ffff\n4.14:eeee:7.0:0101\n", encoding="utf-8")
    (rej / "CVE-2026-1003.json").write_text(
        json.dumps(
            cve_doc(
                "CVE-2026-1003", org=KERNEL_ORG, short="Linux", state="REJECTED", text="Rejected invented record."
            )
        ),
        encoding="utf-8",
    )
    return tree


def cvelist_zip(root: Path) -> Path:
    path = root / "2026-01-02_all_CVEs_at_midnight.zip"
    inner_path = root / "cves.zip"
    docs = {
        KERNEL_ID: cve_doc(
            KERNEL_ID,
            org=KERNEL_ORG,
            short="Linux",
            title="list copy of sock leak",
            text="List copy.",
            adp=[CISA_ADP],
        ),
        OLD_KERNEL_ID: cve_doc(
            OLD_KERNEL_ID,
            title="older kernel bug",
            text="A Linux kernel issue assigned by another CNA.",
            affected=[
                {
                    "vendor": "Linux",
                    "product": "Linux Kernel",
                    "versions": [
                        {"version": "5.0", "lessThan": "5.10", "status": "affected", "versionType": "semver"}
                    ],
                }
            ],
        ),
        WILDCARD_ID: cve_doc(
            WILDCARD_ID,
            title="older kernel record",
            text="A Linux kernel issue with no version range.",
            affected=[{"vendor": "Linux", "product": "kernel", "versions": [{"version": "*", "status": "affected"}]}],
        ),
        WEB_ID: cve_doc(
            WEB_ID,
            title="Widget login bypass",
            text="Widget server authentication bypass via invented header.",
            affected=[
                {
                    "vendor": "Acme",
                    "product": "Widget",
                    "versions": [{"version": "1.0", "lessThan": "2.0", "status": "affected"}],
                }
            ],
            metrics=[CVSS_31],
            adp=[CISA_ADP],
            refs=[f"https://example.invalid/advisory/longer/path/{i}" for i in range(30)],
        ),
        REJECTED_ID: cve_doc(REJECTED_ID, state="REJECTED", text="Widget rejected duplicate."),
    }
    with zipfile.ZipFile(inner_path, "w") as inner:
        for cve, doc in docs.items():
            year, number = cve.split("-")[1:]
            inner.writestr(f"cves/{year}/{number[:-3]}xxx/{cve}.json", json.dumps(doc))
    with zipfile.ZipFile(path, "w") as outer:
        outer.write(inner_path, "cves.zip")
    inner_path.unlink()
    return path


KEV_PAYLOAD = json.dumps(
    {
        "catalogVersion": "2026.01.05",
        "dateReleased": "2026-01-05T00:00:00Z",
        "vulnerabilities": [
            {
                "cveID": WEB_ID,
                "vendorProject": "Acme",
                "product": "Widget",
                "vulnerabilityName": "Acme Widget Authentication Bypass",
                "dateAdded": "2026-01-04",
                "shortDescription": "Invented.",
                "requiredAction": "Invented action.",
                "dueDate": "2026-01-25",
                "knownRansomwareCampaignUse": "Known",
                "notes": "https://example.invalid/kev",
                "cwes": ["CWE-287"],
                "forensicTriage": "No",
            }
        ],
    }
).encode()

EPSS_PAYLOAD = gzip.compress(
    f"#model_version:v2026.01.01,score_date:2026-01-05T00:00:00Z\ncve,epss,percentile\n{WEB_ID},0.91,0.99\n{KERNEL_ID},0.002,0.1\n".encode()
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "home"
    monkeypatch.setenv("CVELIB_HOME", str(target))
    return target


def fake_fetch(url: str, headers: dict[str, str]) -> Response:
    body = {config.KEV_URL: KEV_PAYLOAD, config.EPSS_URL: EPSS_PAYLOAD}[url]
    headers_out = Message()
    headers_out["ETag"] = "fixture-etag"
    return Response(200, body, headers_out)


@pytest.fixture
def synced(home: Path, tmp_path: Path) -> Path:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    conn = store.open_write()
    sync.sync_kev(conn, fetch=fake_fetch)
    sync.sync_epss(conn, fetch=fake_fetch)
    sync.sync_kernel(conn, kernel_tree(source_dir))
    sync.sync_cvelist(conn, local_zip=cvelist_zip(source_dir))
    conn.commit()
    conn.close()
    return home

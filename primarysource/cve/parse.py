"""Turn upstream documents into plain rows. No I/O and no SQL, so every trap in a format has a unit test."""

from __future__ import annotations

import csv
import gzip
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .config import CISA_ADP_SHORT_NAME, KERNEL_ORG_ID
from .errors import CvelibError

CVE_ID = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)


def normalize_cve(text: str) -> str:
    candidate = text.strip().upper()
    if not CVE_ID.match(candidate):
        raise CvelibError(f"not a CVE id: {text!r}", "Give an id such as CVE-2024-14027.")
    return candidate


@dataclass(frozen=True)
class Metric:
    label: str
    version: str
    vector: str
    score: float | None
    severity: str | None


@dataclass
class Record:
    cve: str
    state: str
    assigner: str
    assigner_org: str
    published: str
    updated: str
    title: str
    description: str
    cwes: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    affected: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    ssvc: dict[str, Any] | None = None
    program_files: list[str] = field(default_factory=list)

    @property
    def is_kernel(self) -> bool:
        return self.assigner_org == KERNEL_ORG_ID


METRIC_KEYS = (
    ("cvssV4_0", "4.0"),
    ("cvssV3_1", "3.1"),
    ("cvssV3_0", "3.0"),
    ("cvssV2_0", "2.0"),
)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _english(items: object) -> str:
    """The English entry of a `descriptions` list, else the first one with text."""
    if not isinstance(items, Sequence):
        return ""
    fallback = ""
    for item in items:
        if not isinstance(item, Mapping):
            continue
        value = _text(item.get("value"))
        if value and _text(item.get("lang")).lower().startswith("en"):
            return value
        fallback = fallback or value
    return fallback


def _metrics(container: Mapping[str, Any], label: str) -> tuple[list[Metric], dict[str, Any] | None]:
    metrics: list[Metric] = []
    ssvc: dict[str, Any] | None = None
    for item in container.get("metrics") or []:
        if not isinstance(item, Mapping):
            continue
        for key, version in METRIC_KEYS:
            block = item.get(key)
            if isinstance(block, Mapping) and _text(block.get("vectorString")):
                metrics.append(
                    Metric(
                        label,
                        version,
                        _text(block.get("vectorString")),
                        _float(block.get("baseScore")),
                        _text(block.get("baseSeverity")) or None,
                    )
                )
        other = item.get("other")
        if isinstance(other, Mapping) and _text(other.get("type")).lower() == "ssvc":
            content = other.get("content")
            if isinstance(content, Mapping):
                options: dict[str, Any] = {}
                for option in content.get("options") or []:
                    if isinstance(option, Mapping):
                        options.update(option)
                ssvc = {
                    "exploitation": options.get("Exploitation"),
                    "automatable": options.get("Automatable"),
                    "technical_impact": options.get("Technical Impact"),
                    "version": content.get("version"),
                    "timestamp": content.get("timestamp"),
                }
    return metrics, ssvc


def _compact_version(item: Mapping[str, Any]) -> dict[str, Any]:
    kept = {
        key: item[key] for key in ("version", "lessThan", "lessThanOrEqual", "status", "versionType") if item.get(key)
    }
    return kept


def _compact_affected(items: object) -> tuple[list[dict[str, Any]], list[str]]:
    compact: list[dict[str, Any]] = []
    files: set[str] = set()
    if not isinstance(items, Sequence):
        return compact, []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, Any] = {}
        for key in ("vendor", "product", "defaultStatus", "repo"):
            if item.get(key):
                entry[key] = item[key]
        versions = item.get("versions")
        if isinstance(versions, Sequence):
            entry["versions"] = [_compact_version(version) for version in versions if isinstance(version, Mapping)]
        program = item.get("programFiles")
        if isinstance(program, Sequence):
            files.update(path for path in program if isinstance(path, str))
        compact.append(entry)
    return compact, sorted(files)


def _cwes(container: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    for problem in container.get("problemTypes") or []:
        if not isinstance(problem, Mapping):
            continue
        for description in problem.get("descriptions") or []:
            if isinstance(description, Mapping):
                cwe = _text(description.get("cweId")) or _text(description.get("description"))
                if cwe and cwe not in found:
                    found.append(cwe)
    return found


def parse_cve_record(data: Mapping[str, Any], fallback_state: str = "PUBLISHED") -> Record | None:
    """A CVE JSON 5.x record, flattened, or None if it has no id."""
    metadata = data.get("cveMetadata")
    containers = data.get("containers")
    if not isinstance(metadata, Mapping) or not isinstance(containers, Mapping):
        return None
    # Older kernel CNA files spell it cveID.
    cve = (_text(metadata.get("cveId")) or _text(metadata.get("cveID"))).upper()
    if not cve:
        return None
    cna = _mapping(containers.get("cna"))
    provider = _mapping(cna.get("providerMetadata"))
    short = _text(provider.get("shortName")) or _text(metadata.get("assignerShortName"))

    state = _text(metadata.get("state")).upper() or fallback_state
    description = _english(cna.get("descriptions")) or _english(cna.get("rejectedReasons"))
    metrics, ssvc = _metrics(cna, f"CNA:{short}" if short else "CNA")
    affected, files = _compact_affected(cna.get("affected"))
    cwes = _cwes(cna)

    references: list[str] = []
    for ref in cna.get("references") or []:
        if isinstance(ref, Mapping) and _text(ref.get("url")):
            references.append(_text(ref.get("url")))

    for adp in containers.get("adp") or []:
        if not isinstance(adp, Mapping):
            continue
        meta = adp.get("providerMetadata")
        adp_short = _text(meta.get("shortName")) if isinstance(meta, Mapping) else ""
        adp_metrics, adp_ssvc = _metrics(adp, f"ADP:{adp_short or 'unknown'}")
        metrics.extend(adp_metrics)
        if adp_ssvc is not None and (ssvc is None or adp_short == CISA_ADP_SHORT_NAME):
            ssvc = adp_ssvc
        for cwe in _cwes(adp):
            if cwe not in cwes:
                cwes.append(cwe)
        for ref in adp.get("references") or []:
            if isinstance(ref, Mapping) and _text(ref.get("url")) and _text(ref.get("url")) not in references:
                references.append(_text(ref.get("url")))

    return Record(
        cve=cve,
        state=state,
        assigner=_text(metadata.get("assignerShortName")) or short,
        assigner_org=_text(metadata.get("assignerOrgId")),
        published=_text(metadata.get("datePublished")),
        updated=_text(metadata.get("dateUpdated")),
        title=_text(cna.get("title")),
        description=description,
        cwes=cwes,
        references=references,
        affected=affected,
        metrics=metrics,
        ssvc=ssvc,
        program_files=files,
    )


@dataclass(frozen=True)
class KevEntry:
    cve: str
    vendor: str
    product: str
    name: str
    date_added: str
    due_date: str
    ransomware: str
    action: str
    description: str
    notes: str
    cwes: list[str]
    forensic_triage: str | None


def parse_kev(payload: bytes) -> tuple[str, str, list[KevEntry]]:
    """`(catalog_version, date_released, entries)` from the CISA catalog JSON."""
    data = json.loads(payload)
    if not isinstance(data, Mapping) or not isinstance(data.get("vulnerabilities"), list):
        raise CvelibError(
            "the KEV catalog is not in the expected shape", "Check docs/sources.md and the CISA schema."
        )
    entries: list[KevEntry] = []
    for item in data["vulnerabilities"]:
        if not isinstance(item, Mapping) or not _text(item.get("cveID")):
            continue
        cwes = item.get("cwes")
        triage = item.get("forensicTriage")
        entries.append(
            KevEntry(
                cve=_text(item.get("cveID")).upper(),
                vendor=_text(item.get("vendorProject")),
                product=_text(item.get("product")),
                name=_text(item.get("vulnerabilityName")),
                date_added=_text(item.get("dateAdded")),
                due_date=_text(item.get("dueDate")),
                ransomware=_text(item.get("knownRansomwareCampaignUse")),
                action=_text(item.get("requiredAction")),
                description=_text(item.get("shortDescription")),
                notes=_text(item.get("notes")),
                cwes=[cwe for cwe in cwes if isinstance(cwe, str)] if isinstance(cwes, list) else [],
                forensic_triage=_text(triage) if triage else None,
            )
        )
    return _text(data.get("catalogVersion")), _text(data.get("dateReleased")), entries


def parse_epss(payload: bytes) -> tuple[str, str, list[tuple[str, float, float]]]:
    """`(model_version, score_date, [(cve, epss, percentile)])` from the gzipped daily CSV."""
    text = gzip.decompress(payload).decode("utf-8")
    lines = text.splitlines()
    model = score_date = ""
    if lines and lines[0].startswith("#"):
        for part in lines[0].lstrip("#").split(","):
            key, _, value = part.partition(":")
            if key == "model_version":
                model = value
            elif key == "score_date":
                score_date = value
        lines = lines[1:]
    rows: list[tuple[str, float, float]] = []
    for row in csv.DictReader(lines):
        epss = _float(row.get("epss"))
        percentile = _float(row.get("percentile"))
        if row.get("cve") and epss is not None and percentile is not None:
            rows.append((str(row["cve"]).upper(), epss, percentile))
    return model, score_date, rows


def json_records(payloads: Iterator[bytes]) -> Iterator[Record]:
    """Parse a stream of CVE JSON documents, skipping any that are not records."""
    for payload in payloads:
        try:
            data = json.loads(payload)
        except ValueError:
            continue
        if isinstance(data, Mapping):
            record = parse_cve_record(data)
            if record is not None:
                yield record

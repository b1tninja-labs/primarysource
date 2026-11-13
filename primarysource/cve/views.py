"""Text views of `service`'s answers: what a tool or a command prints (PLAN.md §5.9).

`service` returns plain dicts, which is what `--json` prints. These functions turn the same dicts into `render()`
text: the answer as lines, then the fixed footer. What a dict carries as a field either stays a line of the body
(`kev:`, `epss:`, the verdict) or becomes a footer line:

- `cite:` the sources that supplied the answer, as `service` names them;
- `unit:` is `block` when the lines are the numbered items of a list section (a reference, an affected entry, a
  kernel range): each carries its own ref, `CVE-Y-N§references¶9`, and `¶n` on a read means "from item n on";
- `next:` a ref string for a read (`CVE-Y-N§references¶9`, what `cve_read` takes back as `ref`), `start=<n>` for a
  list (`render.next_start`);
- `relaxed:` the search matched only some of its terms;
- `partial:` every source that is missing, failed or stale, because an absence means less when one is (a CVE
  "not in KEV" is a different fact from a KEV catalog that was never synced);
- `warning:` a hedge the reader must not drop: a truncated description, a version string with a distribution
  suffix.

Record text (titles, descriptions, references, KEV notes) is data from other people. It is printed as it came and
never interpreted; the server instructions say so.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from primarysource.render import next_start, render

PARTIAL_JOIN = " | "


def _footer(payload: Mapping[str, Any], **fixed: str) -> dict[str, str]:
    """The footer lines `payload` implies, plus `fixed` ones. A multi-line value is cut to one line."""
    footer = {key: " ".join(str(value).split()) for key, value in fixed.items() if value}
    gaps = payload.get("partial")
    if gaps:
        footer["partial"] = PARTIAL_JOIN.join(" ".join(str(gap).split()) for gap in gaps)
    return footer


def _next(payload: Mapping[str, Any]) -> str:
    """A read's `next` is already a ref; a list's is `{"start": n}`."""
    value = payload.get("next")
    if isinstance(value, Mapping):
        return next_start(int(value["start"]))
    return str(value) if value else ""


def _score(metric: Mapping[str, Any] | None) -> str:
    if not metric:
        return "none"
    severity = f" {metric['severity']}" if metric.get("severity") else ""
    return f"{metric['score']}{severity} (CVSS {metric['version']}, {metric['label']})"


def _json_line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _kev_line(kev: Mapping[str, Any]) -> str:
    if kev["status"] == "listed":
        return (
            f"listed, added {kev['date_added']}, due {kev['due_date']}, ransomware use {kev['ransomware']}; "
            f"action: {kev['action']}"
        )
    if kev["status"] == "not_listed":
        return f"not listed ({kev['source']})"
    return f"unknown: {kev.get('why', 'not consulted')}"


def _epss_line(epss: Mapping[str, Any]) -> str:
    return f"{epss['score']} (percentile {epss['percentile']}) {epss['source']}"


def _fixed_in(fixed: Mapping[str, str]) -> str:
    return ", ".join(f"{branch} -> {fix}" for branch, fix in fixed.items()) or "none recorded"


# --- info ----------------------------------------------------------------------------------------------------


def info(payload: Mapping[str, Any]) -> str:
    if payload.get("status") == "not_synced":
        body = f"home: {payload['home']}\nindex: not synced yet"
        return render(body, {"warning": f"{payload['error']}; {payload['hint']}; run: {payload['action']}"})
    if "counts" not in payload:
        lines = [f"{payload['ref']}  {payload['state']}  {payload['title']}"]
        lines.append(f"cvss: {_score(payload['cvss'])}")
        lines.append(f"kev: {payload['kev']}")
        if payload.get("epss"):
            lines.append(f"epss: {_epss_line(payload['epss'])}")
        lines.append(f"kernel CNA data: {'yes' if payload['kernel_cna'] else 'no'}")
        return render("\n".join(lines), _footer(payload, next=str(payload["next"])))
    lines = [f"home: {payload['home']}", f"index: {payload['index']} ({payload['index_mb']} MB)"]
    lines += [f"{name}: {count}" for name, count in payload["counts"].items()]
    lines.append("sources:")
    for name, row in payload["sources"].items():
        lines.append(
            f"  {name}  {row['state']}  version {row['version'] or '-'}  upstream {row['upstream_date'] or '-'}  "
            f"synced {row['synced_at'] or '-'}  records {row['records'] if row['records'] is not None else '-'}"
            + (f"  detail: {row['detail']}" if row["detail"] else "")
        )
    return render("\n".join(lines), _footer(payload))


# --- search --------------------------------------------------------------------------------------------------


def search(payload: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for hit in payload["hits"]:
        flags = "".join(
            [
                f" cvss={hit['cvss']}" if "cvss" in hit else "",
                " KEV" if hit.get("kev") else "",
                f" epss={hit['epss']:.3f}" if "epss" in hit else "",
            ]
        )
        lines.append(f"{hit['ref']}  [{hit['source']}]{flags}  {hit['title']}")
        if hit.get("snippet"):
            lines.append(f"    {' '.join(str(hit['snippet']).split())}")
    body = "\n".join(lines) or f"no CVE record matches {payload['query']!r}"
    relaxed = "no record holds every term; these hold some of them" if payload.get("relaxed") and lines else ""
    return render(body, _footer(payload, next=_next(payload), relaxed=relaxed))


# --- read ----------------------------------------------------------------------------------------------------


def _items(payload: Mapping[str, Any], label: str, lines: list[str]) -> list[str]:
    """The numbered items of a list section, each with its own ref so it can be cited."""
    section = str(payload["ref"])
    head = f"{section}: items {payload['start']}-{payload['start'] + len(payload['items']) - 1} of {payload['total']}"
    if not payload["items"]:
        head = f"{section}: no {label}"
    numbered = [f"{section}¶{payload['start'] + offset}  {item}" for offset, item in enumerate(payload["items"])]
    return [head, *lines, *numbered]


def _affected_line(entry: Any) -> str:
    if not isinstance(entry, Mapping):
        return str(entry)
    head = f"{entry.get('vendor', '')} {entry.get('product', '')}".strip()
    ranges: list[str] = []
    for version in entry.get("versions") or []:
        if not isinstance(version, Mapping):
            continue
        bits = [str(version.get("status", "")), str(version.get("version", ""))]
        bits += [f"{key} {version[key]}" for key in ("lessThan", "lessThanOrEqual") if version.get(key)]
        ranges.append(" ".join(bit for bit in bits if bit))
    if ranges:
        return f"{head}: {'; '.join(ranges)}"
    return head or _json_line(entry)


def read(payload: Mapping[str, Any]) -> str:
    ref = str(payload["ref"])
    if payload.get("state") == "UNKNOWN_TO_CVE_SOURCES":
        lines = [f"{ref}  {payload['note']}", f"kev: {_kev_line(payload['kev'])}"]
        if payload.get("epss"):
            lines.append(f"epss: {_epss_line(payload['epss'])}")
        return render("\n".join(lines), _footer(payload))
    cite = str(payload.get("cite", ""))
    if "§" in ref:
        section = ref.split("§", 1)[1]
        if section == "references":
            body = "\n".join(_items(payload, "references", []))
            return render(body, _footer(payload, cite=cite, unit="block", next=_next(payload)))
        if section == "affected":
            lines = _items(
                {**payload, "items": [_affected_line(i) for i in payload["items"]]}, "affected entries", []
            )
            return render("\n".join(lines), _footer(payload, cite=cite, unit="block", next=_next(payload)))
        if section == "cvss":
            lines = [f"{ref}  preferred: {_score(payload['preferred'])}"]
            for metric in payload["items"]:
                lines.append(f"{metric['label']}  {metric['version']}  {_score(metric)}  {metric['vector']}")
            if not payload["items"]:
                lines.append("no CVSS score in any synced source")
            return render("\n".join(lines), _footer(payload, cite=cite))
        if section == "kernel":
            if "items" not in payload:
                return render(f"{ref}  {payload['note']}", _footer(payload, cite=cite))
            lines = [
                f"fixed in: {_fixed_in(payload['fixed_in'])}",
                f"unfixed on start: {', '.join(payload['unfixed_on_start']) or 'none'}",
                f"source: {payload['source']}",
            ]
            body = "\n".join(_items(payload, "kernel ranges", lines))
            return render(body, _footer(payload, cite=cite, unit="block", next=_next(payload)))
        lines = [f"{ref}"]
        for name, row in payload["sources"].items():
            lines.append(
                f"{name}  {row['state']}  version {row['version'] or '-'}  upstream {row['upstream_date'] or '-'}  "
                f"synced {row['synced_at'] or '-'}"
            )
        return render("\n".join(lines), _footer(payload, cite=cite))
    return _summary(payload)


def _summary(payload: Mapping[str, Any]) -> str:
    lines = [f"{payload['ref']}  {payload['state']}"]
    if payload["title"]:
        lines.append(f"title: {payload['title']}")
    lines.append(
        f"assigner: {payload['assigner'] or '-'}  published: {payload['published']}  updated: {payload['updated']}"
    )
    lines.append(f"cwe: {', '.join(payload['cwe']) or '-'}")
    lines.append(
        f"cvss: {_score(payload['cvss']['preferred'])}; {payload['cvss']['count']} score(s) in {payload['ref']}§cvss"
    )
    lines.append(f"kev: {_kev_line(payload['kev'])}")
    if payload.get("epss"):
        lines.append(f"epss: {_epss_line(payload['epss'])}")
    if payload.get("ssvc"):
        lines.append("ssvc: " + ", ".join(f"{key}={value}" for key, value in payload["ssvc"].items()))
    kernel = payload.get("kernel")
    if kernel:
        lines.append(f"kernel: {kernel['source']}; fixed in {_fixed_in(kernel['fixed_in'])}")
        if kernel["unfixed_on_start"]:
            lines.append(f"kernel unfixed on start: {', '.join(kernel['unfixed_on_start'])}")
        if kernel["files"]:
            more = kernel["files_total"] - len(kernel["files"])
            lines.append(f"kernel files: {' '.join(kernel['files'])}" + (f" (+{more} more)" if more > 0 else ""))
        lines.append(f"kernel question: cve_kernel('{payload['ref']}', '<version>')")
    lines.append(f"description ({payload['description_source']}):")
    lines.append(str(payload["description"]))
    lines.append(f"references ({len(payload['references'])} of {payload['references_total']}):")
    lines += [f"  {url}" for url in payload["references"]]
    lines.append("sections: " + ", ".join(payload["sections"]))
    warning = "description and references cut to fit max_tokens; raise max_tokens" if payload.get("truncated") else ""
    return render("\n".join(lines), _footer(payload, cite=str(payload["cite"]), next=_next(payload), warning=warning))


# --- kev -----------------------------------------------------------------------------------------------------


def kev(payload: Mapping[str, Any]) -> str:
    if "status" in payload:
        if payload["status"] == "not_listed":
            body = f"{payload['ref']} is not in the CISA KEV catalog"
            return render(body, _footer(payload, cite=str(payload["source"])))
        lines = [
            f"{payload['ref']}  listed in CISA KEV",
            f"vendor: {payload['vendor']}  product: {payload['product']}",
            f"name: {payload['name']}",
            f"added: {payload['date_added']}  due: {payload['due_date']}  ransomware use: {payload['ransomware']}",
            f"action: {payload['action']}",
            f"description: {payload['description']}",
        ]
        if payload.get("notes"):
            lines.append(f"notes: {payload['notes']}")
        if payload.get("cwes"):
            lines.append(f"cwe: {', '.join(payload['cwes'])}")
        if payload.get("forensic_triage"):
            lines.append(f"forensic triage: {payload['forensic_triage']}")
        return render("\n".join(lines), _footer(payload, cite=str(payload["source"])))
    lines = [f"{payload['total']} KEV entries, newest first"]
    lines += [
        f"{row['cve']}  added {row['date_added']}  due {row['due_date']}  {row['vendor']}/{row['product']}  "
        f"{row['name']}" + (f"  ransomware: {row['ransomware']}" if row["ransomware"] else "")
        for row in payload["items"]
    ]
    return render("\n".join(lines), _footer(payload, cite=str(payload["source"]), next=_next(payload)))


# --- kernel --------------------------------------------------------------------------------------------------


def _caveats(payload: Mapping[str, Any]) -> str:
    return PARTIAL_JOIN.join(payload.get("caveats", []))


def kernel_check(payload: Mapping[str, Any]) -> str:
    confidence = f"  (confidence: {payload['confidence']})" if payload.get("confidence") else ""
    lines = [f"{payload['ref']} on kernel {payload['version']}: {payload['verdict']}{confidence}"]
    if payload.get("reason"):
        lines.append(f"reason: {payload['reason']}")
    if payload.get("detail"):
        lines.append(f"detail: {payload['detail']}")
    lines += [f"evidence: {item}" for item in payload.get("evidence", [])]
    if payload.get("fixed_in"):
        lines.append(f"fixed in: {_fixed_in(payload['fixed_in'])}")
    if payload.get("note"):
        lines.append(f"note: {payload['note']}")
    return render("\n".join(lines), _footer(payload, cite=str(payload.get("source", "")), warning=_caveats(payload)))


def kernel_list(payload: Mapping[str, Any]) -> str:
    lines = [f"{payload['version']}: {payload['affected_total']} of {payload['assessed']} kernel CNA CVEs affect it"]
    for item in payload["items"]:
        marks = "".join([" KEV" if item.get("kev") else "", f" epss={item['epss']:.3f}" if "epss" in item else ""])
        files = f"  files: {' '.join(item['files'])}" if item.get("files") else ""
        lines.append(f"{item['ref']}{marks}  {item['title']}  ({item['why']}){files}")
    lines.append(f"note: {payload['note']}")
    return render(
        "\n".join(lines),
        _footer(payload, cite=str(payload["source"]), next=_next(payload), warning=_caveats(payload)),
    )


def path(home: str, index: str) -> str:
    return render(f"home: {home}\nindex: {index}\nsetting: CVELIB_HOME or PRIMARYSOURCE_CVE_HOME", {})

"""The text of a result: `service`'s payload as `render()` text with the core's fixed footer (PLAN.md §5.9).

`service` answers in dictionaries, which the CLI's `--json` prints as they are. The MCP tools and the CLI's human
output show the same text instead: the passage or the rows first, then footer lines in the core's fixed order
(`cite`, `unit`, `span`, `next`, `relaxed`, `confidence`, `warning`). What a JSON result carried as fields is a
footer line where it is a fact about the whole result, and part of a row where it belongs to one hit.

`next:` is exactly what to pass back (PLAN.md §5.11): a ref for a read, `start=<n>` for the same list tool.
"""

from __future__ import annotations

from typing import Any

from primarysource.render import next_start, render


def _age(fresh: dict[str, Any]) -> str:
    if fresh.get("age_days") is None:
        return "undated"
    return f"{fresh['date']}, {fresh['age_days']} days old" + (", STALE" if fresh.get("stale") else "")


def _stale(fresh: dict[str, Any], what: str = "the ZIM") -> str:
    """The warning for a ZIM past `library.STALE_DAYS`: a snapshot, so version details may have moved on."""
    if fresh.get("stale"):
        return f"{what} is a snapshot from {fresh['date']}, {fresh['age_days']} days old; check version details"
    return ""


def _warn(*parts: str) -> str:
    """One footer line: the non-empty parts, joined (a footer value is one line)."""
    return "; ".join(" ".join(part.split()) for part in parts if part)


def _clamped(payload: dict[str, Any]) -> str:
    clamped = payload.get("clamped")
    if not clamped:
        return ""
    return "limits were lowered: " + ", ".join(f"{name} to {value}" for name, value in clamped.items())


def _row(row: dict[str, Any]) -> str:
    """One library as a line: name, title, then what choosing one needs."""
    bits = [row["search"], f"{row['articles']} articles", f"{row['size_bytes'] / 1e6:.1f} MB", _age(row["freshness"])]
    if row.get("version") is not None and not isinstance(row["version"], dict):
        bits.append(f"version {row['version']}")
    label = f"{row['family']} [{', '.join(row['versions'])}]" if row.get("versions") else row["name"]
    line = f"{label}  {row['title']}  [{'; '.join(bits)}]"
    extra = []
    if row.get("other_editions"):
        extra.append(f"other editions: {', '.join(row['other_editions'])}")
    if row.get("provenance") and isinstance(row["provenance"], str):
        extra.append(f"provenance: {row['provenance']}")
    if row.get("match"):
        extra.append(f"match: {row['match']}")
    if row.get("description"):
        extra.append(f"description: {row['description']}")
    if row.get("creator"):
        extra.append(f"creator: {row['creator']}")
    if row.get("tags"):
        extra.append(f"tags: {', '.join(row['tags'])}")
    if "license" in row:
        extra.append(f"licence: {row['license'] or 'not stated in the ZIM'}")
    if isinstance(row.get("provenance"), dict):
        record = row["provenance"]
        extra.append(
            f"provenance: {record['state']}" + (f", from {record['source']}" if record.get("source") else "")
        )
    return "\n".join([line, *(f"    {item}" for item in extra)])


def libraries(payload: dict[str, Any]) -> str:
    rows = payload["libraries"]
    if not rows:
        body = f"no installed library matches {payload.get('query', '')!r}"
    else:
        body = "\n".join(_row(row) for row in rows)
    problems = payload.get("problems") or []
    warning = _warn(
        f"{len(problems)} ZIM file(s) could not be read: " + "; ".join(f"{p['path']}: {p['error']}" for p in problems)
        if problems
        else "",
        _clamped(payload),
    )
    head = f"{payload['total']} installed ({payload['directory']})"
    return render(f"{head}\n{body}", {"next": next_start(payload.get("next")), "warning": warning})


def resolve(payload: dict[str, Any]) -> str:
    version = payload["version"]
    lines = [_row({**payload, "version": None})]
    if "upstream" in version:
        others = f"; also installed: {', '.join(payload['other_versions'])}" if payload.get("other_versions") else ""
        lines.append(f"    upstream version: {version['upstream']} ({version['selected']}){others}")
    else:
        lines.append(f"    version: {version['note']}")
    return render("\n".join(lines), {"warning": _stale(payload["freshness"])})


def _hit(hit: dict[str, Any]) -> str:
    tags = [hit["match"]] + ([f"{hit['blocks']} blocks"] if "blocks" in hit else [])
    if hit.get("language"):
        tags.append(f"language {hit['language']}")
    lines = [f"{hit['ref']}  {hit['title']}  [{'; '.join(tags)}]"]
    if hit.get("excerpt"):
        lines.append(f"    {' '.join(hit['excerpt'].split())}")
    if hit.get("note"):
        lines.append(f"    {hit['note']}")
    if hit.get("section"):
        section = hit["section"]
        lines.append(f"    best section: {section['ref']}  {section['heading']}  [{section['blocks']} blocks]")
    return "\n".join(lines)


def _obtainable(payload: dict[str, Any]) -> list[str]:
    """What the offline catalogue snapshot says could be installed, as lines a model relays to the user."""
    lines = []
    if payload.get("obtainable"):
        age = payload.get("snapshot_age_days")
        lines.append(f"not installed, but in the catalogue snapshot ({age} days old); give the user the command:")
        lines += [f"    {row['name']}  {row['title']}  ->  {row['install']}" for row in payload["obtainable"]]
    elif payload.get("user_action"):
        lines.append(f"{payload['user_action']}")
    return lines


def search(payload: dict[str, Any]) -> str:
    hits = payload["hits"]
    searched = ", ".join(
        f"{name} (ZIM edition {payload['editions'].get(name) or 'undated'})" for name in payload["libraries_searched"]
    )
    lines = [f"searched: {searched}"]
    lines += [_hit(hit) for hit in hits] if hits else [payload.get("note", "no entry matched")]
    if hits and payload.get("note"):
        lines.append(payload["note"])
    for key in ("title_only", "ranking"):
        if payload.get(key):
            lines.append(f"({payload[key]})")
    lines += _obtainable(payload)
    partial = [hit for hit in hits if hit["match"] == "some terms"]
    relaxed = f"{len(partial)} of {len(hits)} hit(s) matched only some of the words" if partial else ""
    low = "low: no hit matched all the words, so the topic may not be covered; do not answer from these hits"
    footer = {
        "next": next_start(payload.get("next")),
        "relaxed": relaxed,
        "confidence": low if payload.get("confidence") == "low" and hits else "",
        "warning": _clamped(payload),
    }
    return render("\n".join(lines), footer)


def read(payload: dict[str, Any]) -> str:
    blocks = payload["blocks"]
    left = f"; {payload['remaining_tokens']} tokens left" if payload.get("remaining_tokens") else ""
    title = payload.get("page_title") or payload["title"]
    head = f"{title}  [¶{blocks['from']}-{blocks['to']} of {blocks['of']}{left}]"
    if payload.get("redirected_from"):
        head += f"  (redirected from {payload['redirected_from']})"
    warning = _warn(
        _stale(payload["freshness"]),
        payload.get("oversize", ""),
        payload.get("converted_truncated", ""),
        payload.get("images", ""),
        _clamped(payload),
    )
    footer = {"cite": payload["cite"], "unit": "block", "next": payload.get("next") or "", "warning": warning}
    return render(f"{head}\n\n{payload['content']}", footer)


def outline(payload: dict[str, Any]) -> str:
    footer = {"next": next_start(payload.get("next")), "warning": _clamped(payload)}
    if "outline" in payload:
        rows = payload["outline"]
        lines = [f"{payload['ref']}  {payload['title']}  [{payload['total']} rows]"]
        for row in rows:
            indent = "  " * (int(row.get("level") or 4) - 1)
            anchor = f"  #{row['anchor']}" if row.get("anchor") else ""
            kind = "  (definition)" if row.get("kind") else ""
            lines.append(f"{indent}{row['text']}{anchor}{kind}")
        if not rows:
            lines.append("no headings or definitions")
        return render("\n".join(lines), footer)
    footer["warning"] = _warn(_stale(payload["freshness"]), footer["warning"])
    lines = [f"{row['ref']}  {row['title']}" for row in payload["entries"]]
    if not lines:
        lines = [f"no entries in {payload['library']} match"]
    return render("\n".join(lines), footer)


def links(payload: dict[str, Any]) -> str:
    lines = [f"{payload['ref']}  [{payload['total']} links]"]
    for row in payload["links"]:
        target = row.get("url") or row["ref"] + ("" if row.get("in_zim") else "  (not in this ZIM)")
        lines.append(f"{row['text']}  ->  {target}")
    if not payload["links"]:
        lines.append("no links")
    return render("\n".join(lines), {"next": next_start(payload.get("next")), "warning": _clamped(payload)})


def cite(payload: dict[str, Any]) -> str:
    lines = [payload["cite"], f"licence: {payload['license']}"]
    if payload.get("creator"):
        lines.append(f"creator: {payload['creator']}")
    record = payload["provenance"]
    lines.append(f"ZIM {payload['uuid']}; provenance: {record['state']}")
    footer = {
        "cite": payload["cite"],
        "unit": "block" if "span" in payload else "",
        "span": payload.get("span", ""),
        "warning": _stale(payload["freshness"]),
    }
    return render("\n".join(lines), footer)


def available(payload: dict[str, Any]) -> str:
    snap = payload["snapshot"]
    lines = []
    for row in payload["available"]:
        state = f"INSTALLED {row['installed_edition']}" if row["installed"] else "not installed"
        lines.append(
            f"{row['name']}  {row['title']}  [{row['date']}; ~{row['approx_mb']} MB; {row['articles']} articles; "
            f"{state}]\n    install: {row['install']}"
        )
    if not payload["available"]:
        lines.append(f"nothing in the snapshot matches {payload['query']!r}")
    lines.append(
        f"({payload['matches']} matches; snapshot of {snap['fetched_at']}, {snap['age_days']} days old, offline)"
    )
    return render("\n".join(lines), {"next": next_start(payload.get("next"))})

"""The vector tools as plain functions over a `Store`, returning text with the core's fixed footer.

Each result is a body (one line per item, or one case in full), then footer lines: `cite:` names the set, its
source file and pinned sha256, `span:` is the hash of the exact text returned (case reads). When the token budget
cuts a page, `next:` is exactly what to pass back: for `read`, the ref that reads on (`<set or group ref>¶<n>`,
the nth line of that listing); for `groups` and `find`, `start=<n>`, a 0-based line offset.
"""

from __future__ import annotations

import json
from typing import Any

from primarysource import cursor
from primarysource.budget import page
from primarysource.cavp.model import (
    CREDIT,
    Case,
    Group,
    Store,
    VectorSet,
    find_case,
    find_group,
    format_ref,
    norm_value,
    parse_ref,
)
from primarysource.errors import LibError
from primarysource.model import span_hash
from primarysource.render import next_start, render

SHOWN = 60  # characters of a field value in a listing; a case read is never shortened


def _value(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, separators=(",", ":"))


def _short(v: Any) -> str:
    s = _value(v)
    return s if len(s) <= SHOWN else f"{s[:SHOWN]}...({len(s)} chars)"


def _cite(s: VectorSet, where: str = "") -> str:
    kind = "ACVP" if s.kind == "acvp" else "CAVP"
    head = f"NIST {kind} {s.algorithm} {s.mode}".strip()
    rev = f" rev {s.revision}" if s.revision else ""
    return f"{head}{rev}{where}; {s.source_url}; sha256:{s.sha256}"


def _listed(lines: list[str], start: int, max_tokens: int, cite: str) -> str:
    """A list cut at the token budget from the 0-based line `start`; `next: start=<n>` continues."""
    if start < 0 or max_tokens < 1:
        raise LibError(f"start is a 0-based offset and max_tokens positive (got {start}, {max_tokens})", "")
    got = page(lines, start + 1, max_tokens)
    body = "\n".join(got.units) if got.units else f"nothing at start={start} ({got.total} lines)"
    resume = None if got.next_start is None else got.next_start - 1
    return render(body, {"cite": cite, "next": next_start(resume)})


def _read_page(lines: list[str], scope: str, line: int | None, max_tokens: int, cite: str) -> str:
    """A read cut at the token budget from line `line` (1-based); `next:` is the ref that reads on."""
    if max_tokens < 1:
        raise LibError("max_tokens must be positive", "")
    got = page(lines, cursor.first_unit(line, len(lines), "lines", f"{scope}¶{line}"), max_tokens)
    return render("\n".join(got.units), {"cite": cite, "next": cursor.read_next(scope, got)})


def sets(store: Store, query: str | None = None, limit: int = 50) -> str:
    """One line per imported set. `query` keeps the sets whose id, algorithm or mode contains it."""
    entries = store.require()
    needle = (query or "").lower()
    hits = [e for e in entries if needle in f"{e.id} {e.algorithm} {e.mode}".lower()]
    if not hits:
        return f"no vector set matches {query!r} ({len(entries)} imported)\n"
    lines = [
        f"{format_ref(e.id)}: {e.algorithm} {e.mode}{' rev ' + e.revision if e.revision else ''}, "
        f"{e.groups} groups, {e.cases} cases"
        for e in hits[: max(1, limit)]
    ]
    if len(hits) > limit:
        lines.append(f"... {len(hits) - limit} more; narrow the query")
    return "\n".join(lines) + "\n"


def _group_line(s: VectorSet, g: Group) -> str:
    extras = " ".join(f"{k}={_short(v)}" for k, v in g.params.items())
    return f"{format_ref(s.id, g.label)}: {len(g.cases)} cases {extras}".rstrip()


def _case_body(s: VectorSet, g: Group, c: Case) -> str:
    lines = [format_ref(s.id, g.label, c.id)]
    lines += [f"{k} = {_value(v)}" for k, v in c.fields.items()]
    lines += [f"expected.{k} = {_value(v)}" for k, v in c.expected.items()]
    return "\n".join(lines)


def groups(store: Store, set_ref: str, start: int = 0, max_tokens: int = 2000) -> str:
    """The groups of a set, one line each, as refs."""
    ref = parse_ref(set_ref)
    s = store.load(ref.set_id)
    return _listed([_group_line(s, g) for g in s.groups], start, max_tokens, _cite(s))


def read(store: Store, ref_text: str, max_tokens: int = 2000) -> str:
    """A set (its header and groups), a group (its cases, values shortened) or one case in full. `<ref>¶n` reads a
    set or a group from line n of its listing."""
    text, line = cursor.split_para(ref_text)
    ref = parse_ref(text)
    s = store.load(ref.set_id)
    if ref.group is None:
        header = [f"# {h.lstrip('# ')}" for h in s.header[:5]]
        lines = header + [_group_line(s, g) for g in s.groups]
        return _read_page(lines, format_ref(s.id), line, max_tokens, _cite(s))
    g = find_group(s, ref.group)
    if ref.case is None:
        lines = [
            f"{format_ref(s.id, g.label, c.id)}: "
            + " ".join(
                f"{k}={_short(v)}"
                for k, v in {**c.fields, **{f"expected.{k}": v for k, v in c.expected.items()}}.items()
            )
            for c in g.cases
        ]
        return _read_page(lines, format_ref(s.id, g.label), line, max_tokens, _cite(s, f", group {g.label}"))
    if line is not None:
        raise LibError(f"{ref_text}: a case is read whole", f"read {format_ref(s.id, g.label, ref.case)}")
    c = find_case(g, ref.case)
    body = _case_body(s, g, c)
    return render(body, {"cite": _cite(s, f", group {g.label}, case {c.id}"), "span": span_hash(body)})


def find(
    store: Store,
    set_ref: str,
    field: str,
    value: str,
    group: str | None = None,
    start: int = 0,
    max_tokens: int = 2000,
) -> str:
    """The cases of a set whose `field` equals `value` (compared as hex: case and `0x` ignored), as refs with the
    case's other short fields. `field` may be `expected.<name>` for an ACVP answer. Zero matches is said, not an
    error."""
    s = store.load(parse_ref(set_ref).set_id)
    chosen = [find_group(s, group)] if group else list(s.groups)
    want = norm_value(value)
    lines: list[str] = []
    for g in chosen:
        for c in g.cases:
            held = c.expected.get(field[9:]) if field.startswith("expected.") else c.fields.get(field)
            if held is not None and norm_value(_value(held)) == want:
                lines.append(f"{format_ref(s.id, g.label, c.id)}: {_short(held)}")
    if not lines:
        return f"no case in {format_ref(s.id)} has {field} = {_short(value)}\n"
    return _listed(lines, start, max_tokens, _cite(s))


def cite(store: Store, ref_text: str) -> str:
    """The citation for a ref, with its source, pinned digest and NIST's credit line."""
    ref = parse_ref(ref_text)
    s = store.load(ref.set_id)
    where = ""
    if ref.group is not None:
        g = find_group(s, ref.group)
        where = f", group {g.label}"
        if ref.case is not None:
            where += f", case {find_case(g, ref.case).id}"
    return f"{format_ref(s.id, ref.group, ref.case)}\n{_cite(s, where)}\n{CREDIT}\n"

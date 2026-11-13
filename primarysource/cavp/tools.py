"""The vector tools as plain functions over a `Store`, returning text with the core's fixed footer.

Each result is a body (one line per item, or one case in full), then footer lines: `cite:` names the set, its
source file and pinned sha256, `span:` is the hash of the exact text returned (case reads), `next:` is
`start=N` when a listing was cut at the token budget.
"""

from __future__ import annotations

import json
from typing import Any

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
from primarysource.render import render

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


def _paged(lines: list[str], start: int, max_tokens: int, cite: str) -> str:
    try:
        got = page(lines, start, max_tokens)
    except ValueError as exc:
        raise LibError(str(exc), "start is 1-based; max_tokens is positive") from None
    body = "\n".join(got.units) if got.units else f"nothing at start={start} ({got.total} lines)"
    return render(body, {"cite": cite, "next": f"start={got.next_start}" if got.next_start else ""})


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


def groups(store: Store, set_ref: str, start: int = 1, max_tokens: int = 2000) -> str:
    """The groups of a set, one line each, as refs."""
    ref = parse_ref(set_ref)
    s = store.load(ref.set_id)
    return _paged([_group_line(s, g) for g in s.groups], start, max_tokens, _cite(s))


def read(store: Store, ref_text: str, start: int = 1, max_tokens: int = 2000) -> str:
    """A set (its header and groups), a group (its cases, values shortened) or one case in full."""
    ref = parse_ref(ref_text)
    s = store.load(ref.set_id)
    if ref.group is None:
        header = [f"# {h.lstrip('# ')}" for h in s.header[:5]]
        return _paged(header + [_group_line(s, g) for g in s.groups], start, max_tokens, _cite(s))
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
        return _paged(lines, start, max_tokens, _cite(s, f", group {g.label}"))
    c = find_case(g, ref.case)
    body = _case_body(s, g, c)
    return render(body, {"cite": _cite(s, f", group {g.label}, case {c.id}"), "span": span_hash(body)})


def find(
    store: Store,
    set_ref: str,
    field: str,
    value: str,
    group: str | None = None,
    start: int = 1,
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
    return _paged(lines, start, max_tokens, _cite(s))


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

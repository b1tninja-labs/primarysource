"""Parse CAVP `.rsp` response files and ACVP vector-set JSON into `VectorSet`s, within fixed bounds.

Bytes in, a `VectorSet` out: nothing is written to disk and no archive is unpacked (a zip member is read into
memory, capped at `MAX_SOURCE_BYTES`).

An `.rsp` file is a header of `#` comments, then `[...]` lines that open a group, then blocks of `Key = Value`
lines separated by blank lines. Rules this parser applies, because real files need them:

- consecutive `[...]` lines form one group (label joined with `,`); a `[...]` line after cases opens the next;
- a repeated key inside a block starts a new block, so a file with no blank lines still splits;
- RSA `SigVer` files put the modulus `n` in a block of its own, ahead of the cases that use it. A block whose
  keys are disjoint from the group's most common block shape is *context*: it is merged into every following
  case of the group and is not a case itself;
- a case's id is its `COUNT` when every case of the group has a unique one, else its 1-based position.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections import Counter
from typing import Any

from primarysource.cavp.model import (
    KINDS,
    MAX_CASES,
    MAX_FIELDS_PER_CASE,
    MAX_GROUPS,
    MAX_HEADER_LINES,
    MAX_LINE_BYTES,
    MAX_SOURCE_BYTES,
    SET_ID,
    Case,
    Group,
    VectorSet,
    sha256_bytes,
)
from primarysource.errors import LibError

_MODE = re.compile(r'#\s*"([^"]+)"\s+information', re.IGNORECASE)


def read_member(archive: bytes, member: str) -> bytes:
    """One file out of a zip held in memory, refused when it is larger than the cap (declared or actual)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive))
        info = zf.getinfo(member)
    except zipfile.BadZipFile:
        raise LibError("the artifact is not a zip file", "check the url and the pinned sha256") from None
    except KeyError:
        names = ", ".join(n for n in zf.namelist() if not n.endswith("/"))[:400]
        raise LibError(f"zip has no member {member!r} (members: {names})", "fix `member` in vectors.toml") from None
    if info.file_size > MAX_SOURCE_BYTES:
        raise LibError(f"{member}: {info.file_size} bytes is over the {MAX_SOURCE_BYTES} byte cap", "")
    with zf.open(info) as stream:
        data = stream.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise LibError(f"{member}: larger than the {MAX_SOURCE_BYTES} byte cap", "")
    return data


def _decode(data: bytes, what: str) -> str:
    if len(data) > MAX_SOURCE_BYTES:
        raise LibError(f"{what}: {len(data)} bytes is over the {MAX_SOURCE_BYTES} byte cap", "")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise LibError(f"{what} is not UTF-8 ({exc})", "") from None


def _group_params(labels: list[str]) -> dict[str, Any]:
    """`[L = 1024, N = 160, SHA-1]` -> {"L": "1024", "N": "160", "tokens": ["SHA-1"]}."""
    params: dict[str, Any] = {}
    tokens: list[str] = []
    for label in labels:
        for piece in label.split(","):
            key, eq, value = piece.partition("=")
            if eq:
                params[key.strip()] = value.strip()
            elif piece.strip():
                tokens.append(piece.strip())
    if tokens:
        params["tokens"] = tokens
    return params


def _cases(blocks: list[dict[str, str]]) -> tuple[Case, ...]:
    if not blocks:
        return ()
    dominant = Counter(frozenset(b) for b in blocks).most_common(1)[0][0]
    context: dict[str, str] = {}
    rows: list[dict[str, str]] = []
    for block in blocks:
        if dominant.isdisjoint(block):
            context = block
        else:
            rows.append({**context, **block})
    counts = [row.get("COUNT") for row in rows]
    use_count = bool(rows) and all(c is not None for c in counts) and len(set(counts)) == len(counts)
    return tuple(Case(str(row["COUNT"]) if use_count else str(i), row) for i, row in enumerate(rows, 1))


def parse_rsp(
    data: bytes,
    *,
    set_id: str,
    algorithm: str,
    source_url: str,
    sha256: str,
    member_sha256: str,
    mode: str = "",
) -> VectorSet:
    """Parse one `.rsp`. `mode` defaults to the quoted name in the file's header (`# "SigVer" information`)."""
    text = _decode(data, set_id)
    header: list[str] = []
    groups: list[tuple[list[str], list[dict[str, str]]]] = []
    labels: list[str] | None = None
    blocks: list[dict[str, str]] = []
    block: dict[str, str] = {}

    def close_block() -> None:
        nonlocal block
        if block:
            blocks.append(block)
            block = {}

    def close_group() -> None:
        nonlocal labels, blocks
        close_block()
        if labels is not None or blocks:
            groups.append((labels if labels is not None else ["all"], blocks))
        labels, blocks = None, []

    for number, raw in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        if len(raw) > MAX_LINE_BYTES:
            raise LibError(f"{set_id} line {number}: over {MAX_LINE_BYTES} characters", "")
        line = raw.strip()
        if not line:
            close_block()
        elif line.startswith("#"):
            if not groups and labels is None and not blocks and len(header) < MAX_HEADER_LINES:
                header.append(line)
        elif line.startswith("[") and line.endswith("]"):
            close_block()
            if labels is None or blocks:
                close_group()
                labels = []
            labels.append(line[1:-1].strip())
            if len(groups) >= MAX_GROUPS:
                raise LibError(f"{set_id}: more than {MAX_GROUPS} groups", "")
        else:
            key, eq, value = line.partition("=")
            if not eq or not key.strip():
                raise LibError(f"{set_id} line {number}: not 'Key = Value' or '[group]': {line[:60]!r}", "")
            key = key.strip()
            if key in block:
                close_block()
            block[key] = value.strip()
            if len(block) > MAX_FIELDS_PER_CASE:
                raise LibError(f"{set_id} line {number}: more than {MAX_FIELDS_PER_CASE} fields in one case", "")
    close_group()

    seen: Counter[str] = Counter()
    out: list[Group] = []
    total = 0
    for group_labels, group_blocks in groups:
        label = ",".join(group_labels)
        seen[label] += 1
        if seen[label] > 1:
            label = f"{label}~{seen[label]}"
        cases = _cases(group_blocks)
        total += len(cases)
        if total > MAX_CASES:
            raise LibError(f"{set_id}: more than {MAX_CASES} cases", "")
        out.append(Group(label, _group_params(group_labels), cases))
    if not out:
        raise LibError(f"{set_id}: no groups or cases found", "is this a CAVP .rsp file?")
    found = _MODE.search("\n".join(header))
    return VectorSet(
        id=set_id,
        kind="cavp",
        algorithm=algorithm,
        mode=mode or (found.group(1) if found else ""),
        source_url=source_url,
        sha256=sha256,
        member_sha256=member_sha256,
        header=tuple(header),
        groups=tuple(out),
    )


def _acvp_document(data: bytes, what: str) -> dict[str, Any]:
    try:
        doc = json.loads(_decode(data, what))
    except (ValueError, RecursionError) as exc:
        raise LibError(f"{what} is not valid JSON ({exc})", "") from None
    if isinstance(doc, list):  # a server response: [{"acvVersion": ...}, {the vector set}]
        doc = next((d for d in doc if isinstance(d, dict) and "testGroups" in d), None)
    if not isinstance(doc, dict) or not isinstance(doc.get("testGroups"), list):
        raise LibError(f"{what}: no testGroups", "is this an ACVP prompt.json or expectedResults.json?")
    return doc


def parse_acvp(
    prompt: bytes,
    expected: bytes | None,
    *,
    set_id: str,
    source_url: str,
    sha256: str,
    member_sha256: str,
) -> VectorSet:
    """One ACVP vector set: `prompt.json` (the inputs), joined by (tgId, tcId) with `expectedResults.json`."""
    doc = _acvp_document(prompt, f"{set_id} prompt")
    answers: dict[tuple[str, str], dict[str, Any]] = {}
    if expected is not None:
        for g in _acvp_document(expected, f"{set_id} expectedResults")["testGroups"]:
            for t in g.get("tests", []):
                answers[(str(g.get("tgId")), str(t.get("tcId")))] = {k: v for k, v in t.items() if k != "tcId"}
    groups: list[Group] = []
    total = 0
    used = 0
    for g in doc["testGroups"]:
        tg = str(g.get("tgId"))
        tests = g.get("tests")
        if not isinstance(tests, list):
            raise LibError(f"{set_id} group {tg}: no tests list", "")
        cases = []
        for t in tests:
            tc = str(t.get("tcId"))
            fields = {k: v for k, v in t.items() if k != "tcId"}
            if len(fields) > MAX_FIELDS_PER_CASE:
                raise LibError(f"{set_id} case {tg}/{tc}: more than {MAX_FIELDS_PER_CASE} fields", "")
            answer = answers.get((tg, tc), {})
            used += bool(answer)
            cases.append(Case(tc, fields, answer))
        total += len(cases)
        if total > MAX_CASES or len(groups) >= MAX_GROUPS:
            raise LibError(f"{set_id}: over {MAX_CASES} cases or {MAX_GROUPS} groups", "")
        groups.append(Group(tg, {k: v for k, v in g.items() if k not in ("tests", "tgId")}, tuple(cases)))
    if expected is not None and used != len(answers):
        raise LibError(
            f"{set_id}: expectedResults has {len(answers) - used} cases that prompt does not",
            "pair the files of one vector set",
        )
    return VectorSet(
        id=set_id,
        kind="acvp",
        algorithm=str(doc.get("algorithm", "")),
        mode=str(doc.get("mode", "")),
        source_url=source_url,
        sha256=sha256,
        member_sha256=member_sha256,
        header=(),
        groups=tuple(groups),
        revision=str(doc.get("revision", "")),
    )


def check_set_id(set_id: str, kind: str) -> None:
    if kind not in KINDS or not SET_ID.fullmatch(set_id) or not set_id.startswith(kind + "/"):
        raise LibError(
            f"bad set id {set_id!r} for kind {kind!r}", "ids look like cavp/ecdsa/SigVer.rsp or acvp/ECDSA-SigVer-1.0"
        )


__all__ = ["check_set_id", "parse_acvp", "parse_rsp", "read_member", "sha256_bytes"]

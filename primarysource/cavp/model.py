"""Test vectors: the data model, the ref grammar and the on-disk store.

A *set* is one vector file: a CAVP `.rsp` response file, or one ACVP vector set (`prompt.json` joined with
`expectedResults.json`). A set holds *groups* (CAVP `[...]` header lines, ACVP `testGroups`) and a group holds
*cases*. Refs, with `nist:` optional on input:

    nist:cavp/ecdsa/SigVer.rsp                      a set
    nist:cavp/ecdsa/SigVer.rsp#[P-256,SHA-256]      a group
    nist:cavp/ecdsa/SigVer.rsp#[P-256,SHA-256]/3    a case
    nist:acvp/ECDSA-SigVer-1.0#1/3                  ACVP: the group is the tgId, the case the tcId

`docs/cavp.md` has the full grammar.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from primarysource.errors import LibError
from primarysource.home import atomic_write

SCHEMA_VERSION = 1
REF_PREFIX = "nist:"
INDEX_FILE = "index.json"
SETS_DIR = "sets"

# Bounds. A source over these is refused, never read.
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_GROUPS = 100_000
MAX_CASES = 2_000_000
MAX_FIELDS_PER_CASE = 64
MAX_HEADER_LINES = 100

SET_ID = re.compile(r"(cavp|acvp)(/[A-Za-z0-9][A-Za-z0-9._+-]*)+")
KINDS = ("cavp", "acvp")

CREDIT = (
    "Source: NIST Cryptographic Algorithm Validation Program (CAVP/ACVP). Created by employees of the National "
    "Institute of Standards and Technology (NIST), not subject to copyright in the United States (17 U.S.C. 105); "
    "provided AS IS. https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-"
    "and-technical-series-publications"
)


@dataclass(frozen=True, slots=True)
class Case:
    """`id` is COUNT or tcId when the source has one, else the 1-based position in the group. `fields` are the
    inputs (and, in CAVP, the expected result as well); `expected` is the joined ACVP expectedResults."""

    id: str
    fields: dict[str, Any]
    expected: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Group:
    label: str
    params: dict[str, Any]
    cases: tuple[Case, ...]


@dataclass(frozen=True, slots=True)
class VectorSet:
    id: str
    kind: str
    algorithm: str
    mode: str
    source_url: str
    sha256: str  # of the downloaded artifact (the zip, or prompt.json)
    member_sha256: str  # of the file inside the zip; equal to sha256 when the artifact is the file
    header: tuple[str, ...]
    groups: tuple[Group, ...]
    revision: str = ""

    @property
    def case_count(self) -> int:
        return sum(len(g.cases) for g in self.groups)


@dataclass(frozen=True, slots=True)
class VectorRef:
    set_id: str
    group: str | None = None
    case: str | None = None

    def __str__(self) -> str:
        return format_ref(self.set_id, self.group, self.case)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def format_ref(set_id: str, group: str | None = None, case: str | None = None) -> str:
    out = REF_PREFIX + set_id
    if group is not None:
        out += "#" + (f"[{group}]" if set_id.startswith("cavp/") else group)
        if case is not None:
            out += "/" + case
    elif case is not None:
        raise LibError("a case ref needs its group", "nist:<set>#<group>/<case>")
    return out


def parse_ref(text: str) -> VectorRef:
    """`nist:<set>[#<group>[/<case>]]`. The case is what follows the last `/`, so a group label may hold one."""
    shown = text.strip().removeprefix(REF_PREFIX)
    set_id, sep, rest = shown.partition("#")
    hint = "e.g. nist:cavp/ecdsa/SigVer.rsp#[P-256,SHA-256]/3 or nist:acvp/ECDSA-SigVer-1.0#1/3"
    if not SET_ID.fullmatch(set_id):
        raise LibError(f"not a vector ref: {text!r}", hint)
    if not sep:
        return VectorRef(set_id)
    group, slash, case = rest.rpartition("/")
    if not slash:
        group, case = rest, ""
    if not group:
        raise LibError(f"not a vector ref: {text!r} (empty group)", hint)
    if set_id.startswith("cavp/"):
        if not (group.startswith("[") and group.endswith("]") and len(group) > 2):
            raise LibError(f"not a vector ref: {text!r} (a CAVP group is written in brackets)", hint)
        group = group[1:-1]
    return VectorRef(set_id, group, case or None)


# ---- serialisation -----------------------------------------------------------------------------------------


def set_to_json(s: VectorSet) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "id": s.id,
        "kind": s.kind,
        "algorithm": s.algorithm,
        "mode": s.mode,
        "revision": s.revision,
        "source_url": s.source_url,
        "sha256": s.sha256,
        "member_sha256": s.member_sha256,
        "header": list(s.header),
        "groups": [
            {
                "label": g.label,
                "params": g.params,
                "cases": [{"id": c.id, "fields": c.fields, "expected": c.expected} for c in g.cases],
            }
            for g in s.groups
        ],
    }


def _text(where: str, value: object) -> str:
    if not isinstance(value, str):
        raise LibError(f"{where}: expected a string", "", "primarysource cavp fetch")
    return value


def set_from_json(raw: object, where: str) -> VectorSet:
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA_VERSION:
        raise LibError(f"{where}: not a schema {SCHEMA_VERSION} vector set", "", "primarysource cavp fetch")
    groups: list[Group] = []
    for g in raw.get("groups", []):
        cases = tuple(
            Case(_text("id", c["id"]), dict(c["fields"]), dict(c.get("expected") or {})) for c in g["cases"]
        )
        groups.append(Group(_text("label", g["label"]), dict(g.get("params") or {}), cases))
    return VectorSet(
        id=_text("id", raw.get("id")),
        kind=_text("kind", raw.get("kind")),
        algorithm=_text("algorithm", raw.get("algorithm")),
        mode=_text("mode", raw.get("mode")),
        source_url=_text("source_url", raw.get("source_url")),
        sha256=_text("sha256", raw.get("sha256")),
        member_sha256=_text("member_sha256", raw.get("member_sha256")),
        header=tuple(_text("header", h) for h in raw.get("header", [])),
        groups=tuple(groups),
        revision=_text("revision", raw.get("revision", "")),
    )


# ---- the store -----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IndexEntry:
    id: str
    kind: str
    algorithm: str
    mode: str
    revision: str
    source_url: str
    sha256: str
    groups: int
    cases: int
    file: str


class Store:
    """A directory of imported sets: `index.json` plus `sets/<id with / as __>.json`."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def entries(self) -> list[IndexEntry]:
        path = self.root / INDEX_FILE
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["schema"] != SCHEMA_VERSION:
                raise KeyError("schema")
            return [IndexEntry(**e) for e in data["sets"]]
        except (ValueError, KeyError, TypeError) as exc:
            raise LibError(
                f"{path} is not a schema {SCHEMA_VERSION} index ({exc})", "", "primarysource cavp fetch"
            ) from None

    def require(self) -> list[IndexEntry]:
        """The entries, or an error that names the import command when there are none."""
        found = self.entries()
        if not found:
            raise LibError(f"no vector sets imported under {self.root}", "", "primarysource cavp fetch")
        return found

    def load(self, set_id: str) -> VectorSet:
        found = self.require()
        entry = next((e for e in found if e.id == set_id), None)
        if entry is None:
            names = ", ".join(e.id for e in found)
            raise LibError(f"no vector set {set_id!r} (imported: {names})", "cavp_sets lists what is imported")
        path = (self.root / entry.file).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise LibError(f"{set_id}: {entry.file!r} escapes the store", "", "primarysource cavp fetch")
        try:
            return set_from_json(json.loads(path.read_text(encoding="utf-8")), set_id)
        except FileNotFoundError:
            raise LibError(f"{set_id}: {entry.file} is missing", "", "primarysource cavp fetch") from None
        except (ValueError, KeyError, TypeError) as exc:
            raise LibError(f"{path} is damaged ({exc})", "", "primarysource cavp fetch") from None

    def write(self, s: VectorSet) -> IndexEntry:
        rel = f"{SETS_DIR}/{s.id.replace('/', '__')}.json"
        body = json.dumps(set_to_json(s), ensure_ascii=False, separators=(",", ":"))
        atomic_write(self.root / rel, body.encode("utf-8"))
        entry = IndexEntry(
            s.id, s.kind, s.algorithm, s.mode, s.revision, s.source_url, s.sha256, len(s.groups), s.case_count, rel
        )
        entries = sorted([e for e in self.entries() if e.id != s.id] + [entry], key=lambda e: e.id)
        index = {"schema": SCHEMA_VERSION, "sets": [asdict(e) for e in entries]}
        atomic_write(self.root / INDEX_FILE, (json.dumps(index, indent=2) + "\n").encode("utf-8"))
        return entry


def norm_value(value: object) -> str:
    """Compare as hex is compared: case-insensitive, without spaces or a `0x` prefix. CAVP writes lower case,
    ACVP upper case."""
    s = str(value).strip().lower().replace(" ", "")
    return s[2:] if s.startswith("0x") else s


def find_group(s: VectorSet, label: str) -> Group:
    for g in s.groups:
        if g.label == label:
            return g
    shown = ", ".join(g.label for g in s.groups[:10]) + (", ..." if len(s.groups) > 10 else "")
    raise LibError(f"{s.id} has no group {label!r} (groups: {shown})", f"cavp_groups('nist:{s.id}') lists them")


def find_case(g: Group, case_id: str) -> Case:
    for c in g.cases:
        if c.id == case_id:
            return c
    raise LibError(f"group {g.label!r} has no case {case_id!r} (it has {len(g.cases)} cases)", "")

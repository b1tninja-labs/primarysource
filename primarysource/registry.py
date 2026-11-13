"""The collection registry: how the core finds a library without importing it.

A collection (`nist`, `itu`, `ieee`, ...) is one corpus with its own database, tool-name prefix, declared unit
and ref grammar (PLAN.md §5.8). The core never imports a collection by name. It reads two sources of
`name -> "module:attribute"` targets and imports a target only when that collection is asked for:

- `BUILTIN`: the collections that ship in this package as subpackages, each behind its own extra;
- the `primarysource.collections` entry-point group: a separately installed package that registers itself the
  same way, for a collection with its own licence or release cadence.

Either way the target is a module attribute holding a `Collection`. A collection whose extra is not installed
fails with a `LibError` that names the install command, never with a bare `ImportError`.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

from primarysource.errors import LibError
from primarysource.model import Unit
from primarysource.refs import RefParser

ENTRY_POINT_GROUP = "primarysource.collections"

# name -> "module:attribute" or "module:attribute [extra]", the entry-point spelling. A collection is added here
# when it moves in (PLAN.md §6). Without "[extra]" the extra is the collection's name; two collections that share
# one extra (posix and ieee802 in `[ieee]`) both name it.
BUILTIN: dict[str, str] = {
    "rfc": "primarysource.rfc.collection:COLLECTION [rfc]",
    "nist": "primarysource.nist.collection:COLLECTION",
    "usb": "primarysource.usb.collection:COLLECTION",
    "posix": "primarysource.ieee:POSIX [ieee]",
    "ieee802": "primarysource.ieee:IEEE802 [ieee]",
    "iana": "primarysource.iana:COLLECTION [iana]",
    "cavp": "primarysource.cavp:COLLECTION",
    "usbids": "primarysource.usbids:COLLECTION",
    "draft": "primarysource.draft.collection:COLLECTION [draft]",
    "c2sp": "primarysource.c2sp:C2SP",
    "bbf": "primarysource.bbf:BBF [bbf]",
    "ecma": "primarysource.ecma:ECMA [ecma]",
}

_NAME = re.compile(r"[a-z][a-z0-9]*")
_SPEC = re.compile(r"\s*(?P<target>[\w.]+:[\w.]+)\s*(?:\[\s*(?P<extra>[\w-]+)\s*\])?\s*")


def _split(spec: str) -> tuple[str, str | None]:
    """`module:attribute [extra]` -> (`module:attribute`, `extra` or None)."""
    match = _SPEC.fullmatch(spec)
    if match is None:
        raise LibError(f"malformed collection target {spec!r}", "expected 'module:attribute [extra]'")
    return match["target"], match["extra"]


@dataclass(frozen=True, slots=True)
class Collection:
    """What the core needs to know to serve a collection. Builders (index, readers, tools) are added as the core
    grows; this is the part every collection has today.

    `server` and `cli` are "module:attribute" targets, imported only when used, so a collection can be listed and
    described without its extra installed: `server` names the `MCPServer` object, `cli` a `main(argv)` function
    that runs the collection's own commands."""

    name: str
    title: str
    prefix: str
    unit: Unit
    grammar: RefParser
    server: str = ""
    cli: str = ""

    def __post_init__(self) -> None:
        if not _NAME.fullmatch(self.name):
            raise ValueError(f"collection name {self.name!r} must be lowercase letters and digits")
        if self.prefix not in ("", f"{self.name}_"):
            raise ValueError(f"tool prefix for {self.name!r} must be {self.name + '_'!r} or empty")


@dataclass(frozen=True, slots=True)
class _Target:
    spec: str
    install: str
    # the hint when the collection's MCP server is what is missing: its own extra plus primarysource[mcp]
    server_install: str = ""


def _targets() -> dict[str, _Target]:
    """Every registered collection, without importing any of them. A built-in wins over a plugin of the same
    name, so an installed package cannot shadow one shipped here."""
    found: dict[str, _Target] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        dist = ep.dist.name if ep.dist is not None else ep.name
        target, extra = _split(ep.value)
        package = f"{dist}[{extra}]" if extra else dist
        found[ep.name] = _Target(target, f'pip install "{package}"', f'pip install "{package}" "primarysource[mcp]"')
    for name, spec in BUILTIN.items():
        target, extra = _split(spec)
        found[name] = _Target(
            target,
            f'pip install "primarysource[{extra or name}]"',
            f'pip install "primarysource[{extra or name},mcp]"',
        )
    return found


def available() -> tuple[str, ...]:
    """Names of every registered collection, sorted. Nothing is imported."""
    return tuple(sorted(_targets()))


def load(name: str, targets: Mapping[str, _Target] | None = None) -> Collection:
    """Import and return one collection, or raise a `LibError` that says what to do."""
    known = _targets() if targets is None else targets
    target = known.get(name)
    if target is None:
        names = ", ".join(sorted(known)) or "none"
        raise LibError(f"no collection named {name!r} (registered: {names})", "primarysource collections")
    module_name, _, attribute = target.spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise LibError(f"collection {name!r} needs {exc.name!r}, which is not installed", target.install) from exc
    collection = getattr(module, attribute, None)
    if not isinstance(collection, Collection) or collection.name != name:
        raise LibError(f"{target.spec} does not hold the {name!r} collection", "")
    return collection


def attribute(collection: Collection, spec: str, what: str) -> Any:
    """Import a collection's `server` or `cli` target, mapping a missing dependency to the install hint."""
    if not spec:
        raise LibError(f"collection {collection.name!r} has no {what}", "")
    module_name, _, name = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        target = _targets().get(collection.name)
        if target is None:
            hint = f'pip install "primarysource[{collection.name}]"'
        else:
            hint = target.server_install if what == "server" and target.server_install else target.install
        raise LibError(f"the {collection.name!r} {what} needs {exc.name!r}, which is not installed", hint) from exc
    return getattr(module, name)

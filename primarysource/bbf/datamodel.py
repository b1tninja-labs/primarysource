"""Read a Broadband Forum data-model XML file (CWMP and USP `dm:document`) into addressable nodes.

A node is an object, a parameter, a command, an event, a profile, a data type or a model. Its address (the part
of a ref after `§`) is the full path: `Device.IP.Interface.{i}` for an object (written without its trailing dot;
`Device.IP.Interface.{i}.` also resolves), `Device.IP.Interface.{i}.Enable` for a parameter,
`Device.Reboot()` for a command, `Device.Boot!` for an event, `Baseline:1` for a profile, `IPAddress` for a data
type, `Root:2.22` for a model. A command's arguments are `Device.Reboot().Input.Delay` and
`Device.Reboot().Output.X`.

`¶n` counts the paragraphs of a node's description, in order. The description is kept as the file gives it: BBF
template macros (`{{param}}`, `{{enum}}`, `{{numentries}}`, `{{object}}`) are NOT expanded; they are the
publisher's own markup and expanding them would be this code's interpretation, not the standard's text.
A profile's units are its description paragraphs and then one line per object or parameter it requires.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405 - elements come from the hardened parser in `_xml`
from dataclasses import dataclass, field

from primarysource.bbf import _xml
from primarysource.errors import LibError

KINDS = ("model", "object", "parameter", "command", "event", "profile", "datatype")
MAX_NODES = 400_000
MAX_ENUM = 200
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
_TITLE = re.compile(rb"<!--\s*\n?\s*([^\n]+)")


@dataclass(frozen=True, slots=True)
class Node:
    """One addressable item. `props` is the ordered attribute summary shown in the header line."""

    kind: str
    id: str
    props: tuple[tuple[str, str], ...] = ()
    paragraphs: tuple[str, ...] = ()
    component: str = ""

    def header(self) -> str:
        shown = " ".join(f"{k}={v}" for k, v in self.props if v != "")
        text = f"{self.kind} {self.id}" + (f"  [{shown}]" if shown else "")
        return text + (f"  (component {self.component})" if self.component else "")


@dataclass(frozen=True, slots=True)
class DataModel:
    """A parsed file. `nodes` are in document order; `imports` are the files it imports."""

    title: str
    spec: str
    file: str
    imports: tuple[str, ...]
    nodes: tuple[Node, ...]
    index: dict[str, int] = field(default_factory=dict)

    def find(self, wanted: str) -> tuple[Node, str]:
        """The node `wanted` names and a warning ("" if none): exact id, then without a trailing dot, then with
        case ignored. Raises `LibError` with close matches when nothing fits."""
        text = wanted.strip()
        for candidate in (text, text.rstrip(".") if text.endswith(".") else text):
            if candidate in self.index:
                return self._answer(candidate)
        low = text.rstrip(".").casefold()
        for key in self.index:
            if key.casefold() == low:
                return self._answer(key)
        import difflib

        close = difflib.get_close_matches(text.rstrip("."), list(self.index), n=3, cutoff=0.6)
        hint = f"did you mean: {', '.join(close)}" if close else "bbf_outline lists the nodes of a data model"
        raise LibError(f"no node {text!r} in {self.file or 'this file'}", hint)

    def _answer(self, key: str) -> tuple[Node, str]:
        same = [n for n in self.nodes if n.id == key]
        warning = f"{len(same)} definitions of {key}; this is the first" if len(same) > 1 else ""
        return self.nodes[self.index[key]], warning

    def children(self, node: Node) -> tuple[Node, ...]:
        """The parameters, commands and events directly under an object."""
        if node.kind != "object":
            return ()
        prefix = node.id + "."
        out: list[Node] = []
        for other in self.nodes:
            if other.kind in ("parameter", "command", "event") and other.id.startswith(prefix):
                rest = other.id[len(prefix) :]
                if "." not in rest.replace("().", "()#"):
                    out.append(other)
        return tuple(out)


def _paragraphs(element: ET.Element | None) -> tuple[str, ...]:
    """The text of a `<description>`: blank-line-separated paragraphs, whitespace collapsed inside each."""
    if element is None:
        return ()
    text = "".join(element.itertext()).strip("\n")
    return tuple(" ".join(p.split()) for p in _PARAGRAPH_BREAK.split(text) if p.strip())


def _syntax(parameter: ET.Element) -> list[tuple[str, str]]:
    """The type and restrictions of a parameter as header props."""
    syntax = parameter.find("syntax")
    if syntax is None:
        return []
    props: list[tuple[str, str]] = []
    is_list = syntax.find("list")
    holder = is_list if is_list is not None else syntax  # a list holds the element type, and its own bounds
    type_el = next(
        (c for c in holder if c.tag not in ("list", "default", "description", "hidden", "command", "size")), None
    )
    scope = type_el if type_el is not None else syntax
    name = ""
    if type_el is not None:
        name = type_el.get("ref") or type_el.tag
        extras = {
            k: v
            for k, v in type_el.attrib.items()
            if k in ("refType", "targetParent", "targetType", "targetParentScope")
        }
        if extras:
            name += "(" + ",".join(f"{k}={v}" for k, v in sorted(extras.items())) + ")"
    bounds: list[str] = []
    for restriction in [*scope, *(list(is_list.findall("size")) if is_list is not None else [])]:
        if restriction.tag == "size":
            bounds.append(f"size={restriction.get('minLength', '')}..{restriction.get('maxLength', '')}")
        elif restriction.tag == "range":
            bounds.append("range=" + restriction.get("minInclusive", "") + ".." + restriction.get("maxInclusive", ""))
        elif restriction.tag == "pattern" and restriction.get("value"):
            bounds.append(f"pattern={restriction.get('value')}")
        elif restriction.tag == "units":
            bounds.append(f"units={restriction.get('value', '')}")
    if is_list is not None:
        name = f"list of {name}" if name else "list"
        bounds = [f"items={is_list.get('minItems', '')}..{is_list.get('maxItems', '')}", *bounds]
    props.append(("type", name + (f"({', '.join(bounds)})" if bounds else "")))
    values = [e.get("value", "") for e in scope.iter("enumeration")][:MAX_ENUM]
    if values:
        props.append(("enum", "|".join(values)))
    default = syntax.find("default")
    if default is not None and default.get("value") is not None:
        props.append(("default", repr(default.get("value"))))
    return props


_COMMON = (
    "access",
    "version",
    "status",
    "mandatory",
    "activeNotify",
    "forcedInform",
    "async",
    "minEntries",
    "maxEntries",
)


def _props(element: ET.Element, extra: list[tuple[str, str]] | None = None) -> tuple[tuple[str, str], ...]:
    found = [(k, element.get(k, "")) for k in _COMMON if element.get(k) is not None]
    return tuple(found + (extra or []))


def parse(data: bytes) -> DataModel:
    """Parse one file. Raises `LibError` if it is not a well-formed BBF data-model document."""
    root = _xml.parse(data)
    if root.tag != "document":
        raise LibError(
            f"the root element is <{root.tag}>, not a data-model document", "this is not a BBF data-model file"
        )
    title_match = _TITLE.search(data[:4096])
    title = title_match.group(1).decode("utf-8", errors="replace").strip() if title_match else ""
    nodes: list[Node] = []

    def add(node: Node) -> None:
        if len(nodes) >= MAX_NODES:
            raise LibError("the data model has too many nodes", "")
        nodes.append(node)

    def walk_object(obj: ET.Element, component: str) -> None:
        path = (obj.get("name") or obj.get("ref") or "").strip()
        if not path:
            return
        oid = path.rstrip(".")
        keys = [p.get("ref", "") for k in obj.findall("uniqueKey") for p in k.findall("parameter")]
        extra = [("uniqueKey", ",".join(keys))] if keys else []
        if obj.get("numEntriesParameter"):
            extra.append(("numEntriesParameter", obj.get("numEntriesParameter", "")))
        add(Node("object", oid, _props(obj, extra), _paragraphs(obj.find("description")), component))
        for child in obj:
            if child.tag == "parameter" and child.get("name"):
                pid = f"{oid}.{child.get('name')}"
                add(
                    Node(
                        "parameter",
                        pid,
                        _props(child, _syntax(child)),
                        _paragraphs(child.find("description")),
                        component,
                    )
                )
            elif child.tag in ("command", "event") and child.get("name"):
                name = child.get("name", "")
                cid = f"{oid}.{name}" if child.tag == "event" or name.endswith("()") else f"{oid}.{name}()"
                add(Node(child.tag, cid, _props(child), _paragraphs(child.find("description")), component))
                for part in ("input", "output"):
                    for arg in child.findall(f"{part}/parameter"):
                        if arg.get("name"):
                            aid = f"{cid}.{part.capitalize()}.{arg.get('name')}"
                            add(
                                Node(
                                    "parameter",
                                    aid,
                                    _props(arg, _syntax(arg)),
                                    _paragraphs(arg.find("description")),
                                    component,
                                )
                            )
                if child.tag == "event":
                    for arg in child.findall("parameter"):
                        if arg.get("name"):
                            add(
                                Node(
                                    "parameter",
                                    f"{cid}.{arg.get('name')}",
                                    _props(arg, _syntax(arg)),
                                    _paragraphs(arg.find("description")),
                                    component,
                                )
                            )

    def walk_profile(profile: ET.Element, component: str) -> None:
        name = profile.get("name")
        if not name:
            return
        lines: list[str] = []
        for member in profile:
            if member.tag == "object" and member.get("ref"):
                lines.append(f"object {member.get('ref')} requires {member.get('requirement', '')}")
                lines.extend(
                    f"parameter {member.get('ref')}{p.get('ref')} requires {p.get('requirement', '')}"
                    for p in member.findall("parameter")
                    if p.get("ref")
                )
        extra = [(k, profile.get(k, "")) for k in ("base", "extends") if profile.get(k)]
        add(Node("profile", name, tuple(extra), (*_paragraphs(profile.find("description")), *lines), component))

    def walk_container(container: ET.Element, component: str) -> None:
        for child in container:
            if child.tag == "object":
                walk_object(child, component)
            elif child.tag == "profile":
                walk_profile(child, component)

    imports: list[str] = []
    for child in root:
        if child.tag == "import" and child.get("file"):
            imports.append(child.get("file", ""))
        elif child.tag == "dataType" and child.get("name"):
            add(
                Node(
                    "datatype",
                    child.get("name", ""),
                    _props(child, _syntax(child)),
                    _paragraphs(child.find("description")),
                )
            )
        elif child.tag == "component":
            walk_container(child, child.get("name", ""))
        elif child.tag == "model" and child.get("name"):
            refs = [c.get("ref", "") for c in child.findall("component")]
            extra = [("components", ",".join(refs))] if refs else []
            extra += [(k, child.get(k, "")) for k in ("base", "isService") if child.get(k)]
            add(Node("model", child.get("name", ""), tuple(extra), _paragraphs(child.find("description"))))
            walk_container(child, "")
    index: dict[str, int] = {}
    for position, node in enumerate(nodes):
        index.setdefault(node.id, position)
    return DataModel(title, root.get("spec", ""), root.get("file", ""), tuple(imports), tuple(nodes), index)

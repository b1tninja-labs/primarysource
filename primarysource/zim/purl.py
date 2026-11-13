"""A small Package-URL (purl) parser for the types zimlore resolves documentation for.

Adapted from `docs/prototypes/purl-plan/purl.py` (which checks 212 of the 213 purl-spec cases and carries the
full rule tables); this is the reading half only. It accepts `pypi`, `npm`, `maven`, `cargo`, `golang`, `gem`,
`nuget`, `github` and `generic`, percent-decodes every component, treats `@` as the version separator only in the
LAST path segment (an npm scope is `%40angular` or an unencoded `@angular` in the namespace), and raises
`ZimloreError` for anything else. It never fetches anything.

A purl is used here for exactly two things: to read the `purl:` tag a ZIM built from one carries (`Tags` metadata,
see `docs/prototypes/purl-sphinx-docker/package_zim.py`), and to let a caller name a library by purl. Matching
ignores the version, the qualifiers and the subpath; `Purl.key` is the identity of the package.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote, unquote

from .errors import ZimloreError

TYPES = ("pypi", "npm", "maven", "cargo", "golang", "gem", "nuget", "github", "generic")

_NAMESPACE = {  # purl-spec `main`: required | prohibited | optional
    "pypi": "prohibited",
    "cargo": "prohibited",
    "gem": "prohibited",
    "nuget": "prohibited",
    "maven": "required",
    "golang": "required",
    "github": "required",
    "npm": "optional",
    "generic": "optional",
}
_KEY = re.compile(r"^[a-z][a-z0-9._\-]*$")
_PEP503 = re.compile(r"[-_.]+")


def is_purl(text: str) -> bool:
    """Does `text` start like a purl (`pkg:`)? Says nothing about whether it is a valid one."""
    return text.strip()[:4].lower() == "pkg:"


@dataclass(frozen=True)
class Purl:
    type: str
    name: str
    namespace: str = ""
    version: str | None = None
    qualifiers: dict[str, str] = field(default_factory=dict, compare=False)
    subpath: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        """The package's identity: (type, namespace, name), case-folded; a PyPI name is PEP 503 normalised."""
        name = _PEP503.sub("-", self.name.lower()) if self.type == "pypi" else self.name.lower()
        return (self.type, self.namespace.lower(), name)

    @property
    def text(self) -> str:
        """The purl without version, qualifiers and subpath: the family a version belongs to."""
        path = "/".join(quote(s, safe="@:") for s in [*self.namespace.split("/"), self.name] if s)
        return f"pkg:{self.type}/{path}"

    def __str__(self) -> str:
        return self.text + (f"@{quote(self.version, safe='')}" if self.version else "")

    @property
    def words(self) -> str:
        """Plain spelling for name matching: `github.com/spf13/cobra` for golang, `flask` for pypi."""
        return "/".join(p for p in (self.namespace, self.name) if p)


def parse(text: str) -> Purl:
    """Parse `pkg:type/namespace/name@version?qualifiers#subpath`. Raises `ZimloreError` on anything invalid or of a
    type zimlore does not resolve."""
    raw = text.strip()

    def bad(why: str) -> ZimloreError:
        return ZimloreError(
            f"{text!r} is not a usable purl: {why}",
            "write pkg:type/namespace/name@version, e.g. pkg:pypi/flask@3.1.0 or pkg:golang/example.org/x/t@v1.8",
        )

    if not raw or not is_purl(raw):
        raise bad("it must start with 'pkg:'")
    rest = raw[4:].lstrip("/")
    subpath = ""
    if "#" in rest:
        rest, _, frag = rest.partition("#")
        subpath = "/".join(unquote(s) for s in frag.split("/") if s not in ("", ".", ".."))
    qualifiers: dict[str, str] = {}
    if "?" in rest:
        rest, _, query = rest.partition("?")
        for pair in query.split("&"):
            if not pair:
                continue
            key, eq, value = pair.partition("=")
            key = key.lower()
            if not eq or not _KEY.match(key) or key in qualifiers:
                raise bad(f"bad qualifier {pair!r}")
            if value:
                qualifiers[key] = unquote(value)
    type_, slash, path = rest.partition("/")
    type_ = type_.lower()
    if not slash:
        raise bad("no '/' after the type")
    if type_ not in TYPES:
        raise bad(f"type {type_!r} is not supported (supported: {', '.join(TYPES)})")
    segments = [s for s in path.split("/") if s]
    if not segments:
        raise bad("the name is missing")
    last = segments.pop()
    base, at, ver = last.rpartition("@") if "@" in last else (last, "", "")
    version = unquote(ver) if at else None
    if at and not version:
        raise bad("'@' with no version after it")
    name = unquote(base if at else last)
    namespace = "/".join(unquote(s) for s in segments)
    if not name or "/" in name or any("/" in unquote(s) for s in segments):
        raise bad("an empty name, or a '/' inside a component")
    if _NAMESPACE[type_] == "prohibited" and namespace:
        raise bad(f"type {type_} has no namespace")
    if _NAMESPACE[type_] == "required" and not namespace:
        raise bad(f"type {type_} needs a namespace")
    if type_ in ("github",):
        namespace, name = namespace.lower(), name.lower()
    if type_ == "pypi":
        name = name.lower().replace("_", "-")
    return Purl(type_, name, namespace, version, qualifiers, subpath)

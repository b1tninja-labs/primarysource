"""Where imported registry files live and how they are read back.

`$PRIMARYSOURCE_HOME/iana/<name>.xml` is the file exactly as IANA served it; `manifest.json` beside them records,
per file, its URL, sha256, size, the registry's own `updated` date, when it was fetched and the server's
`Last-Modified`. Reading parses a file once per (path, mtime, size) and checks it against its recorded sha256.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.iana import xmlsafe
from primarysource.iana.catalogue import NAME
from primarysource.iana.model import RegistryFile, from_tree

MANIFEST = "manifest.json"
MAX_BYTES = 32_000_000
"""Ceiling on one registry file. The largest catalogued file (ipfix) is under 0.5 MB; the biggest IANA registries
(media-types, service-names-port-numbers) are a few MB."""


def home() -> Path:
    return collection_home("iana")


def read_manifest(base: Path) -> dict[str, dict[str, Any]]:
    path = base / MANIFEST
    if not path.is_file():
        return {}
    try:
        files = json.loads(path.read_text(encoding="utf-8"))["files"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LibError(f"{path} is not a readable manifest", "delete it and import again") from exc
    if not isinstance(files, dict):
        raise LibError(f"{path} is not a readable manifest", "delete it and import again")
    return {str(k): dict(v) for k, v in files.items() if isinstance(v, dict)}


def imported(base: Path | None = None) -> tuple[str, ...]:
    """Names of the registry files present, sorted."""
    root = base or home()
    if not root.is_dir():
        return ()
    return tuple(sorted(p.stem for p in root.glob("*.xml") if NAME.fullmatch(p.stem)))


@dataclass(frozen=True, slots=True)
class Loaded:
    file: RegistryFile
    sha256: str
    digest_ok: bool | None
    """True if the manifest's sha256 equals the file's, False if it differs, None if the manifest has no entry."""


@lru_cache(maxsize=16)
def _parse(path: str, mtime_ns: int, size: int, name: str) -> tuple[RegistryFile, str]:
    raw = Path(path).read_bytes()
    return from_tree(xmlsafe.parse(raw, MAX_BYTES), name), hashlib.sha256(raw).hexdigest()


def load(name: str, base: Path | None = None) -> Loaded:
    """One imported registry file, parsed. A missing file is an error that names the import command."""
    if not NAME.fullmatch(name):
        raise LibError(f"{name!r} is not a registry file name", "e.g. dns-parameters, bgp-parameters")
    root = base or home()
    path = root / f"{name}.xml"
    if not path.is_file():
        raise LibError(f"registry {name!r} is not imported (looked in {root})", f"primarysource iana import {name}")
    stat = path.stat()
    parsed, digest = _parse(str(path), stat.st_mtime_ns, stat.st_size, name)
    recorded = read_manifest(root).get(name, {}).get("sha256")
    return Loaded(parsed, digest, None if recorded is None else recorded == digest)

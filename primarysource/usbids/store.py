"""Where the imported `usb.ids` lives and how it is read back.

`$PRIMARYSOURCE_HOME/usbids/usb.ids` is the file exactly as served; `manifest.json` beside it records its URL,
sha256, size, the file's own `# Version:` and `# Date:`, when it was fetched, the server's validators and whether
the digest was the pinned one. Reading parses once per (path, mtime, size) and refuses a file whose sha256 no
longer matches the manifest.

Placement: the database is distributable under GPL-2.0-or-later or BSD-3-Clause (docs/usbids.md), so a built image
may carry it as a layer; the importer writes the same layout either way.
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
from primarysource.usbids.parse import Limits, UsbIds, parse

FILE = "usb.ids"
MANIFEST = "manifest.json"
IMPORT_HINT = "primarysource usbids import"
LICENCE = "GPL-2.0-or-later OR BSD-3-Clause"


def home() -> Path:
    return collection_home("usbids")


def read_manifest(base: Path) -> dict[str, Any]:
    path = base / MANIFEST
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise LibError(f"{path} is not a readable manifest", "delete it and import again") from exc
    if not isinstance(data, dict) or not isinstance(data.get("file"), dict):
        raise LibError(f"{path} is not a readable manifest", "delete it and import again")
    return dict(data["file"])


@dataclass(frozen=True, slots=True)
class Loaded:
    ids: UsbIds
    manifest: dict[str, Any]
    sha256: str
    path: Path


@lru_cache(maxsize=4)
def _load(path: str, mtime_ns: int, size: int) -> tuple[UsbIds, str]:
    data = Path(path).read_bytes()
    return parse(data, Limits()), hashlib.sha256(data).hexdigest()


def load(base: Path | None = None) -> Loaded:
    """The imported database, or a `LibError` that names the import command."""
    root = base or home()
    path = root / FILE
    if not path.is_file():
        raise LibError(f"usb.ids is not imported (looked in {root})", IMPORT_HINT)
    stat = path.stat()
    ids, digest = _load(str(path), stat.st_mtime_ns, stat.st_size)
    manifest = read_manifest(root)
    recorded = manifest.get("sha256")
    if recorded and recorded != digest:
        raise LibError(
            f"{path} has sha256 {digest}, but the manifest recorded {recorded}: the file changed after import",
            IMPORT_HINT + " --force",
        )
    if not ids.entries:
        raise LibError(f"{path} holds no usb.ids entries", IMPORT_HINT + " --force")
    return Loaded(ids, manifest, digest, path)

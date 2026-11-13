"""Import an Ecma standard into `$PRIMARYSOURCE_HOME/ecma/`.

The PDF is fetched from ecma-international.org (one request) or taken from a file the user downloaded, checked
against the catalogue's pinned sha256 before anything is parsed or written, stored as `<number>-<edition>.pdf`,
and read once with `_pdf.extract` into `<number>-<edition>.json`, which is what the readers use. `install.json`
records the pin, the extractor and the time. Placement is a volume: this is the user's own copy, downloaded under
Ecma's terms (see `catalogue.json`), and is not for an image layer.

Run as `primarysource ecma import [NUMBER] [--file PDF]`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from primarysource.c2sp._fetch import Fetcher, Transport, verify
from primarysource.ecma import _pdf
from primarysource.ecma.catalogue import HOSTS, Catalogue, Edition
from primarysource.ecma.catalogue import catalogue as packaged_catalogue
from primarysource.errors import LibError
from primarysource.home import atomic_write

INSTALL_RECORD = "install.json"
MAX_PDF = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ImportResult:
    key: str
    pdf: Path
    extraction: Path
    sections: int
    requests: int


def read_record(home: Path) -> dict[str, Any]:
    path = home / INSTALL_RECORD
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"editions": {}}
    return loaded if isinstance(loaded, dict) and isinstance(loaded.get("editions"), dict) else {"editions": {}}


def import_edition(
    home: Path,
    number: str,
    edition: int | None = None,
    *,
    file: Path | None = None,
    cat: Catalogue | None = None,
    transport: Transport | None = None,
    fetcher: Fetcher | None = None,
) -> ImportResult:
    """Fetch (or read `file`), verify, store and extract one edition. Nothing is written unless the sha256
    matches the pin and the PDF reads."""
    cat = cat or packaged_catalogue()
    found: Edition = cat.edition(number, edition)
    requests = 0
    if file is not None:
        try:
            data = file.read_bytes()
        except OSError as exc:
            raise LibError(f"cannot read {file}: {exc}", "pass the PDF you downloaded from the publisher") from exc
        if len(data) > MAX_PDF:
            raise LibError(f"{file} is larger than {MAX_PDF} bytes", "")
    else:
        fetcher = fetcher or Fetcher(HOSTS, transport)
        data = fetcher.get(found.source_url, MAX_PDF)
        requests = fetcher.requests
    verify(data, found.sha256, found.designation)
    if not data.startswith(b"%PDF-"):
        raise LibError(f"{found.designation}: not a PDF", "the pinned file is a PDF; nothing was written")
    pdf_path = home / f"{found.key}.pdf"
    home.mkdir(parents=True, exist_ok=True)
    part = home / f"{found.key}.pdf.part"
    part.write_bytes(data)
    try:
        extraction = _pdf.extract(data, part)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, pdf_path)
    extraction.update(
        {
            "title": found.title,
            "designation": found.designation,
            "edition": found.edition_name,
            "page_url": found.page_url,
            "sha256": found.sha256,
        }
    )
    json_path = home / f"{found.key}.json"
    atomic_write(json_path, (json.dumps(extraction, ensure_ascii=False) + "\n").encode("utf-8"))
    record = read_record(home)
    record["collection"] = "ecma"
    record["editions"][found.key] = {
        "sha256": found.sha256,
        "extractor": extraction["extractor"],
        "imported": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    atomic_write(home / INSTALL_RECORD, (json.dumps(record, indent=2) + "\n").encode("utf-8"))
    return ImportResult(found.key, pdf_path, json_path, len(extraction["sections"]), requests)

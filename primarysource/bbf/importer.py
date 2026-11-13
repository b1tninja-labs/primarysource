"""Import Broadband Forum data models and Technical Reports into `$PRIMARYSOURCE_HOME/bbf/`.

- `import_models`: each XML file is fetched from `raw.githubusercontent.com/BroadbandForum/cwmp-data-models/<commit>/`
  (one request per second), checked against its pinned sha256, parsed once with the hardened parser (a file that
  does not parse is not installed) and written to `models/<id>.xml`.
- `import_report`: a Technical Report PDF is fetched from broadband-forum.org (or taken from a file the user
  downloaded), checked against its sha256, stored as `reports/<id>.pdf`, and read once into `reports/<id>.json`
  with the private PDF reader. Reports go on a volume: the Forum's terms do not allow redistribution of
  derivatives, and this code only writes to the user's own home.

`install.json` is written last, after every file it names. Run as `primarysource bbf import-models [ID ...]` and
`primarysource bbf import-report <ID> [--file PDF]`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from primarysource.bbf import _xml, datamodel
from primarysource.bbf.catalogue import DOC_ID, HOSTS, Catalogue, Model
from primarysource.bbf.catalogue import catalogue as packaged_catalogue
from primarysource.c2sp._fetch import Fetcher, Transport, sha256, verify
from primarysource.ecma import _pdf
from primarysource.errors import LibError
from primarysource.home import atomic_write

INSTALL_RECORD = "install.json"
MAX_PDF = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ImportResult:
    ids: tuple[str, ...]
    requests: int


def read_record(home: Path) -> dict[str, Any]:
    """The install record, or an empty one. Always has `models` and `reports` mappings."""
    try:
        loaded = json.loads((home / INSTALL_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        loaded = {}
    if not isinstance(loaded, dict):
        loaded = {}
    for key in ("models", "reports"):
        if not isinstance(loaded.get(key), dict):
            loaded[key] = {}
    return loaded


def _write_record(home: Path, record: dict[str, Any]) -> None:
    record["collection"] = "bbf"
    atomic_write(home / INSTALL_RECORD, (json.dumps(record, indent=2) + "\n").encode("utf-8"))


def import_models(
    home: Path,
    only: Sequence[str] = (),
    *,
    cat: Catalogue | None = None,
    transport: Transport | None = None,
    fetcher: Fetcher | None = None,
) -> ImportResult:
    """Fetch, verify, parse and install the catalogued data-model files (all, or those named in `only`)."""
    cat = cat or packaged_catalogue()
    chosen = [cat.model(name) for name in only] if only else list(cat.models)
    fetcher = fetcher or Fetcher(HOSTS, transport)
    record = read_record(home)
    done: list[str] = []
    for model in chosen:
        data = fetcher.get(cat.model_url(model), min(_xml.MAX_BYTES, max(model.size * 2, 4096)))
        verify(data, model.sha256, model.id)
        datamodel.parse(data)
        atomic_write(home / "models" / model.path, data)
        record["models"][model.id] = model.sha256
        done.append(model.id)
    record["commit"] = cat.commit
    record["models_licence"] = cat.model_terms.licence
    record["imported"] = datetime.now(UTC).isoformat(timespec="seconds")
    _write_record(home, record)
    return ImportResult(tuple(done), fetcher.requests)


def import_report(
    home: Path,
    report_id: str,
    *,
    file: Path | None = None,
    cat: Catalogue | None = None,
    transport: Transport | None = None,
    fetcher: Fetcher | None = None,
) -> ImportResult:
    """Fetch (or read `file`), verify, store and extract one Technical Report PDF."""
    cat = cat or packaged_catalogue()
    report = cat.report(report_id)
    requests = 0
    if file is not None:
        try:
            data = file.read_bytes()
        except OSError as exc:
            raise LibError(f"cannot read {file}: {exc}", "pass the PDF you downloaded from the Forum") from exc
        if len(data) > MAX_PDF:
            raise LibError(f"{file} is larger than {MAX_PDF} bytes", "")
    else:
        fetcher = fetcher or Fetcher(HOSTS, transport)
        data = fetcher.get(report.source_url, MAX_PDF)
        requests = fetcher.requests
    verify(data, report.sha256, report.designation)
    if not data.startswith(b"%PDF-"):
        raise LibError(f"{report.designation}: not a PDF", "the pinned file is a PDF; nothing was written")
    folder = home / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / f"{report.id}.pdf.part"
    part.write_bytes(data)
    try:
        extraction = _pdf.extract(data, part)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, folder / f"{report.id}.pdf")
    extraction.update(
        {"title": report.title, "designation": report.designation, "edition": report.issue, "sha256": report.sha256}
    )
    atomic_write(folder / f"{report.id}.json", (json.dumps(extraction, ensure_ascii=False) + "\n").encode("utf-8"))
    record = read_record(home)
    record["reports"][report.id] = {
        "sha256": report.sha256,
        "extractor": extraction["extractor"],
        "imported": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _write_record(home, record)
    return ImportResult((report.id,), requests)


def pin_models(raw_base: str, commit: str, names: Sequence[str], fetcher: Fetcher) -> list[Model]:
    """Maintainer step: fetch `names` (file stems) at `commit` and return catalogue entries with size and sha256.
    The result is what goes in `catalogue.json`; it is a review step, never run by the importer."""
    pinned: list[Model] = []
    for name in names:
        if not DOC_ID.fullmatch(name):
            raise LibError(f"not a data-model file stem: {name!r}", "")
        data = fetcher.get(f"{raw_base}{commit}/{name}.xml", _xml.MAX_BYTES)
        parsed = datamodel.parse(data)
        pinned.append(Model(name, f"{name}.xml", parsed.title or name, len(data), sha256(data)))
    return pinned

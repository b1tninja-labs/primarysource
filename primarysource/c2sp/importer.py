"""Import the pinned C2SP specifications into `$PRIMARYSOURCE_HOME/c2sp/<commit>/`.

Each specification is fetched from `raw.githubusercontent.com/C2SP/C2SP/<commit>/<id>.md`, at most one request per
second, and written only if its sha256 equals the catalogue's pin. `install.json` is written last, so a reader
never sees an install that is missing a file. C2SP specifications are licensed CC BY 4.0, so the installed files
may also be baked into an image layer; this code only ever writes to the home directory.

Run as `primarysource c2sp import [--only ID ...]`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from primarysource.c2sp import markdown
from primarysource.c2sp._fetch import Fetcher, Transport, sha256, verify
from primarysource.c2sp.catalogue import DOC_ID, HOSTS, Catalogue, Spec
from primarysource.c2sp.catalogue import catalogue as packaged_catalogue
from primarysource.errors import LibError
from primarysource.home import atomic_write

INSTALL_RECORD = "install.json"
MAX_FILE = markdown.MAX_BYTES


@dataclass(frozen=True, slots=True)
class ImportResult:
    commit: str
    directory: Path
    files: dict[str, str] = field(default_factory=dict)
    requests: int = 0


def install_dir(home: Path, commit: str) -> Path:
    return home / commit


def import_specs(
    home: Path,
    only: Sequence[str] = (),
    *,
    cat: Catalogue | None = None,
    transport: Transport | None = None,
    fetcher: Fetcher | None = None,
) -> ImportResult:
    """Fetch, verify and install the catalogued specs (all, or those named in `only`) under `home`."""
    cat = cat or packaged_catalogue()
    chosen = [cat.spec(name) for name in only] if only else list(cat.specs)
    fetcher = fetcher or Fetcher(HOSTS, transport)
    target = install_dir(home, cat.commit)
    record_path = target / INSTALL_RECORD
    installed: dict[str, str] = {}
    if record_path.is_file():
        try:
            installed = dict(json.loads(record_path.read_text(encoding="utf-8")).get("files", {}))
        except (ValueError, OSError):
            installed = {}
    for spec in chosen:
        data = fetcher.get(cat.url(spec), min(MAX_FILE, max(spec.size * 2, 1024)))
        verify(data, spec.sha256, spec.id)
        markdown.parse(data)  # refuses non-UTF-8, NULs and over-bound text before anything is written
        atomic_write(target / spec.path, data)
        installed[spec.id] = spec.sha256
    record = {
        "collection": "c2sp",
        "repo": cat.repo,
        "commit": cat.commit,
        "licence": cat.terms.licence,
        "imported": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": dict(sorted(installed.items())),
    }
    atomic_write(record_path, (json.dumps(record, indent=2) + "\n").encode("utf-8"))
    return ImportResult(cat.commit, target, dict(sorted(installed.items())), fetcher.requests)


def pin_specs(raw_base: str, commit: str, names: Sequence[str], fetcher: Fetcher) -> list[Spec]:
    """Maintainer step: fetch `names` (file ids) at `commit` and return catalogue entries with size and sha256.
    The result is what goes in `catalogue.json`; it is a review step, never run by the importer."""
    specs: list[Spec] = []
    for name in names:
        if not DOC_ID.fullmatch(name):
            raise LibError(f"not a specification id: {name!r}", "")
        data = fetcher.get(f"{raw_base}{commit}/{name}.md", MAX_FILE)
        doc = markdown.parse(data)
        specs.append(Spec(name, f"{name}.md", doc.title or name, len(data), sha256(data)))
    return specs

"""Import a user-supplied IEEE document into `$PRIMARYSOURCE_HOME/<collection>/<edition>/`.

Nothing here fetches. The user downloads the POSIX archive or an 802 PDF themselves, under the publisher's terms
(`docs/ieee.md`), and hands the file over; a name, an email address, a login or a terms checkbox is a human act
this code never performs.

`import_posix` checks the archive against the pinned sha256 before reading a single member, then streams the
tarball (`tarfile` mode `r|gz`, no seeking) and writes only the HTML pages, under bounds, into a staging directory
that replaces the installed edition in one rename. This is an installation step: the readers in `posix.py` then
read one page file at a time.

`import_pdf` reads an 802 PDF with `pypdf` (the `[ieee]` extra) and stores its bookmarks and page text.

Run as `python -m primarysource.ieee.importer posix <susv5.tgz>` or `... ieee802 <file.pdf> <designation>`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import tarfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from primarysource.errors import LibError
from primarysource.home import atomic_write
from primarysource.home import collection_home as core_collection_home
from primarysource.ieee import POSIX_PAGE
from primarysource.ieee.catalogue import POSIX_2024, Edition, edition

INSTALL_RECORD = "install.json"
INSTALL_HINT = 'pip install "primarysource[ieee]"'
_PAGE = re.compile(POSIX_PAGE)
_CHUNK = 1 << 20


@dataclass(frozen=True, slots=True)
class Limits:
    """Ceilings on what an import will accept. The real POSIX 2024 archive measures 4,962,222 bytes, 1,715
    members, 1,616 HTML pages, 24,248,288 bytes of HTML, largest page 459,326 bytes."""

    archive_bytes: int = 64_000_000
    members: int = 10_000
    member_bytes: int = 4_000_000
    total_bytes: int = 200_000_000
    pdf_bytes: int = 300_000_000


@dataclass(frozen=True, slots=True)
class Report:
    """What an import wrote and what it skipped, by reason."""

    edition: str
    path: Path
    pages: int
    bytes: int
    skipped: dict[str, int] = field(default_factory=dict)


def collection_home(collection: str, home: Path | None = None) -> Path:
    """The core's `home.collection_home` (`$PRIMARYSOURCE_HOME/<collection>`, PLAN.md §5.8), or
    `<home>/<collection>` when a home is given (tests, the measurement script)."""
    return home / collection if home is not None else core_collection_home(collection)


def sha256_file(path: Path, limit: int) -> tuple[str, int]:
    """Digest and size of a file, refusing one larger than `limit` without reading past it."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK):
            size += len(chunk)
            if size > limit:
                raise LibError(f"{path.name} is over {limit:,} bytes; this is not the expected file", "")
            digest.update(chunk)
    return digest.hexdigest(), size


def _verify(path: Path, pinned: Edition, limit: int) -> tuple[str, int]:
    if not path.is_file():
        raise LibError(f"no file at {path}", f"download {pinned.source_url or pinned.page_url} first")
    got, size = sha256_file(path, limit)
    if pinned.sha256 is not None and got != pinned.sha256:
        raise LibError(
            f"{path.name} has sha256 {got}, not the {pinned.sha256} pinned for {pinned.id}: the file is damaged, "
            "truncated, or a different edition or archive format",
            f"download {pinned.source_url or pinned.page_url} again (docs/ieee.md says how)",
        )
    return got, size


def _member_path(name: str) -> PurePosixPath:
    """The member's path, or a LibError for one that could escape the install directory."""
    if "\x00" in name or "\\" in name or name.startswith("/") or re.match(r"[A-Za-z]:", name):
        raise LibError(f"refusing archive member {name!r}: absolute or unsafe path", "")
    path = PurePosixPath(name)
    if ".." in path.parts:
        raise LibError(f"refusing archive member {name!r}: path traversal", "")
    return path


def _install(staging: Path, target: Path) -> None:
    """Replace `target` with `staging` by renames, so a reader sees the old edition or the new one."""
    old = target.with_name(f".{target.name}.old-{secrets.token_hex(4)}")
    if target.exists():
        os.replace(target, old)
    try:
        os.replace(staging, target)
    except BaseException:
        if old.exists():
            os.replace(old, target)
        raise
    shutil.rmtree(old, ignore_errors=True)


def import_posix(
    archive: Path | str,
    *,
    home: Path | None = None,
    pinned: Edition = POSIX_2024,
    limits: Limits | None = None,
) -> Report:
    """Verify and install the POSIX HTML archive. Refuses, naming the cause, on a digest mismatch, an unsafe or
    oversize member, or more members or bytes than `limits` allow; nothing is installed unless all of it passed."""
    limits = limits or Limits()
    path = Path(archive)
    if pinned.sha256 is None or pinned.root is None:
        raise LibError(f"{pinned.id} has no pinned archive", "")
    digest, size = _verify(path, pinned, limits.archive_bytes)
    base = collection_home(pinned.collection, home)
    base.mkdir(parents=True, exist_ok=True)
    staging = base / f".{pinned.id}.part-{secrets.token_hex(4)}"
    staging.mkdir()
    skipped: Counter[str] = Counter()
    pages = 0
    written = 0
    try:
        with path.open("rb") as raw, tarfile.open(fileobj=raw, mode="r|gz") as tar:
            for count, member in enumerate(tar, start=1):
                if count > limits.members:
                    raise LibError(f"{path.name} has more than {limits.members:,} members", "")
                name = _member_path(member.name)
                if not member.isfile():
                    skipped["not a regular file"] += 1
                    continue
                relative = str(name)
                if not relative.startswith(pinned.root):
                    skipped["outside " + pinned.root] += 1
                    continue
                relative = relative[len(pinned.root) :]
                if not relative.endswith(".html"):
                    skipped["not html"] += 1
                    continue
                if not _PAGE.fullmatch(relative[: -len(".html")]):
                    skipped["no page id"] += 1
                    continue
                if member.size > limits.member_bytes:
                    raise LibError(f"refusing {member.name!r}: {member.size:,} bytes is over the per-page limit", "")
                stream = tar.extractfile(member)
                data = stream.read(limits.member_bytes + 1) if stream is not None else b""
                if len(data) > limits.member_bytes:
                    raise LibError(f"refusing {member.name!r}: over the per-page limit", "")
                written += len(data)
                if written > limits.total_bytes:
                    raise LibError(f"{path.name} unpacks to more than {limits.total_bytes:,} bytes of pages", "")
                destination = staging.joinpath(*PurePosixPath(relative).parts)
                if staging.resolve() not in destination.resolve().parents:
                    raise LibError(f"refusing archive member {member.name!r}: resolves outside the install", "")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                pages += 1
        record = {
            "edition": pinned.id,
            "archive": path.name,
            "sha256": digest,
            "size": size,
            "pages": pages,
            "bytes": written,
            "skipped": dict(sorted(skipped.items())),
            "imported": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        (staging / INSTALL_RECORD).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        target = base / pinned.id
        _install(staging, target)
    except tarfile.TarError as exc:
        raise LibError(f"{path.name} is not a readable gzip tar archive ({exc})", "") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return Report(pinned.id, target, pages, written, dict(skipped))


_CLAUSE = re.compile(r"\s*(?:Annex\s+)?(?P<id>[0-9]+(?:\.[0-9]+)*|[A-Z](?:\.[0-9]+)*)\b[\s.:)-]*(?P<title>.*)")


def clause_of(title: str) -> str | None:
    """The clause or annex number a bookmark title starts with (`5.4 Bridge`, `Annex A`), or None."""
    match = _CLAUSE.match(title)
    if match is None:
        return None
    ident = match["id"]
    if len(ident) == 1 and ident.isalpha() and not title.lstrip().startswith(("Annex", ident + ".", ident + " ")):
        return None
    return ident


def normalise_designation(text: str) -> str:
    """`IEEE Std 802.1Q-2022` and `IEEE 802.1Q-2022` -> `802.1Q-2022`."""
    return re.sub(r"^\s*IEEE\s+(?:Std\.?\s+)?", "", text).strip()


def import_pdf(
    pdf: Path | str,
    designation: str,
    *,
    home: Path | None = None,
    limits: Limits | None = None,
) -> Report:
    """Store the bookmarks and page text of a user-supplied 802 PDF. Refuses a designation the catalogue does not
    list, a file that is not a PDF, a digest that differs from a pin, and an encrypted PDF (never decrypted)."""
    limits = limits or Limits()
    pinned = edition("ieee802", normalise_designation(designation))
    path = Path(pdf)
    if not path.is_file():
        raise LibError(f"no file at {path}", f"download {pinned.id} from {pinned.page_url} yourself first")
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise LibError(f"{path.name} is not a PDF", "")
    digest, size = _verify(path, pinned, limits.pdf_bytes)
    try:
        import pypdf
    except ModuleNotFoundError as exc:
        raise LibError(f"importing an 802 PDF needs {exc.name!r}, which is not installed", INSTALL_HINT) from exc
    try:
        reader = pypdf.PdfReader(path)
        if reader.is_encrypted:
            raise LibError(f"{path.name} is encrypted; primarysource never decrypts a document", "")
        outline = _outline(reader, reader.outline, 1)
        pages = [page.extract_text() or "" for page in reader.pages]
    except pypdf.errors.PyPdfError as exc:
        raise LibError(f"{path.name} could not be read as a PDF ({exc})", "") from exc
    target = collection_home("ieee802", home) / pinned.id
    record: dict[str, Any] = {
        "edition": pinned.id,
        "file": path.name,
        "sha256": digest,
        "size": size,
        "pinned": pinned.sha256 is not None,
        "backend": f"pypdf {pypdf.__version__}",
        "pages": len(pages),
        "imported": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    atomic_write(target / "outline.json", (json.dumps(outline, indent=1) + "\n").encode("utf-8"))
    atomic_write(target / "pages.json", json.dumps(pages).encode("utf-8"))
    atomic_write(target / INSTALL_RECORD, (json.dumps(record, indent=2) + "\n").encode("utf-8"))
    return Report(pinned.id, target, len(pages), sum(len(p) for p in pages), {})


def _outline(reader: Any, items: Sequence[Any], depth: int) -> list[dict[str, Any]]:
    """Bookmarks in reading order: depth, title, clause number (or None) and 1-based page."""
    found: list[dict[str, Any]] = []
    if depth > 12:
        return found
    for item in items:
        if isinstance(item, list):
            found.extend(_outline(reader, item, depth + 1))
            continue
        title = str(getattr(item, "title", "") or "").strip()
        try:
            page = reader.get_destination_page_number(item) + 1
        except Exception:  # a broken destination loses its page, not the import
            page = None
        found.append({"depth": depth, "title": title, "clause": clause_of(title), "page": page})
    return found


def _index_after_import() -> None:
    """Build the search index of the edition just installed; a failure is reported, not fatal to the import."""
    from primarysource.ieee import posix_index

    try:
        written = posix_index.build()
    except LibError as exc:
        print(f"search index not built:\n{exc.as_text()}", file=sys.stderr)
        return
    print(f"indexed {written} section(s) into {posix_index.index_path()}")


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) == 2 and args[0] == "posix":
            report = import_posix(args[1])
            _index_after_import()
        elif len(args) == 3 and args[0] == "ieee802":
            report = import_pdf(args[1], args[2])
        else:
            print("usage: python -m primarysource.ieee.importer posix <susv5.tgz>", file=sys.stderr)
            print("       python -m primarysource.ieee.importer ieee802 <file.pdf> <designation>", file=sys.stderr)
            return 2
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
    skipped = ", ".join(f"{reason}: {n}" for reason, n in sorted(report.skipped.items())) or "none"
    print(f"{report.edition}: {report.pages} pages, {report.bytes:,} bytes -> {report.path} (skipped: {skipped})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

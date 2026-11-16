"""Sync free IEC / ISO/IEC / ISO publications from the local webstore stub catalogue."""

from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.iec.webstore import DownloadResult, FreePublication, Webstore, credentials_from_env

STUBS = "webstore/stubs"
PDFS = "pdfs"
ARTIFACTS = "artifacts"
SYNC_RECORD = "free-sync.json"


def default_home() -> Path:
    return collection_home("iec")


def free_from_stubs(stubs_dir: Path) -> list[FreePublication]:
    if not stubs_dir.is_dir():
        raise LibError(
            f"no IEC webstore stubs in {stubs_dir}",
            "",
            "restore the webstore stubs under PRIMARYSOURCE_HOME/iec/webstore/stubs",
        )
    found: list[FreePublication] = []
    for path in sorted(stubs_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not data.get("is_free"):
            continue
        pub_id = str(data.get("id") or path.stem)
        reference = str(data.get("reference") or pub_id)
        found.append(
            FreePublication(
                publication_id=pub_id,
                reference=reference,
                title=str(data.get("title") or reference),
                head=str(data.get("head") or ""),
            )
        )
    return found


def pdf_name(reference: str, publication_id: str) -> str:
    slug = re.sub(r"[^\w.\-]+", "_", reference, flags=re.UNICODE).strip("_")
    return f"{slug or publication_id}.pdf"


def read_record(home: Path) -> dict[str, dict[str, object]]:
    path = home / SYNC_RECORD
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    docs = loaded.get("documents") if isinstance(loaded, dict) else None
    return docs if isinstance(docs, dict) else {}


def write_record(home: Path, documents: dict[str, dict[str, object]]) -> None:
    path = home / SYNC_RECORD
    path.write_text(
        json.dumps({"collection": "iec", "documents": documents}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_extract(archive: Path, dest: Path) -> None:
    """Unpack `archive` into `dest`. A member that would write outside `dest` is refused."""
    root = dest.resolve()
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            target = (dest / info.filename).resolve()
            if target != root and root not in target.parents:
                raise LibError(f"{archive.name} contains an unsafe path {info.filename}", "")
        zipped.extractall(dest)


def unpack_related(archive: Path, dest: Path, *, depth: int = 3) -> Path:
    """Keep `archive` where it is and unpack it, including nested zips, under `dest`.

    The zip stays put. Nested zips are unpacked beside themselves and kept as well.
    """
    dest.mkdir(parents=True, exist_ok=True)
    marker = dest / ".unpacked"
    if not marker.is_file():
        _safe_extract(archive, dest)
        marker.write_text(archive.name + "\n", encoding="utf-8")
    for _ in range(depth):
        pending = [path for path in dest.rglob("*.zip") if path.is_file() and not (path.with_suffix("")).is_dir()]
        if not pending:
            break
        for path in pending:
            inner = path.with_suffix("")
            inner.mkdir()
            _safe_extract(path, inner)
    return dest


def keep_related(home: Path, downloaded: Path) -> dict[str, str]:
    """Retain a downloaded archive's PDF, HTML, and software beside the zip.

    A lone PDF at the top of the archive is also copied next to the zip, under the zip's name,
    so the publication itself can be imported. Nested supplements stay in the artifact tree.
    """
    if downloaded.suffix.lower() != ".zip":
        return {}
    artifact = unpack_related(downloaded, home / ARTIFACTS / downloaded.stem)
    extra = {"artifacts": str(artifact.relative_to(home)).replace("\\", "/")}
    pdfs = [path for path in artifact.glob("*.pdf") if path.is_file() and path.stat().st_size > 1000]
    if len(pdfs) == 1:
        published = downloaded.with_suffix(".pdf")
        if not published.is_file() or published.stat().st_size != pdfs[0].stat().st_size:
            shutil.copy2(pdfs[0], published)
        extra["pdf"] = str(published.relative_to(home)).replace("\\", "/")
    return extra


def _iso_mirror(path: Path, pub: FreePublication) -> Path | None:
    """ISO and ISO/IEC free PDFs also land in the iso home for `primarysource iso import`."""
    if not pub.head.upper().startswith("ISO"):
        return None
    dest = collection_home("iso") / path.name
    if dest.resolve() == path.resolve():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file() or dest.stat().st_size != path.stat().st_size:
        shutil.copy2(path, dest)
    return dest


def sync_free(
    home: Path | None = None,
    *,
    only: Sequence[str] = (),
    limit: int = 0,
    force: bool = False,
) -> list[DownloadResult]:
    """Add every missing free stub to one cart, check out once, then download the library."""
    root = default_home() if home is None else home
    stubs = free_from_stubs(root / STUBS)
    if only:
        wanted = {item.casefold() for item in only}
        stubs = [
            s
            for s in stubs
            if s.publication_id in only or s.reference.casefold() in wanted or s.publication_id.casefold() in wanted
        ]
    if limit > 0:
        stubs = stubs[:limit]
    email, password = credentials_from_env()
    if not email or not password:
        raise LibError(
            "IEC webstore credentials are not set",
            "",
            "set IEC_EMAIL and IEC_PASSWORD in .env (see .env.example)",
        )
    store = Webstore(email, password)
    record = read_record(root)
    store.login_html()
    owned = {ref.casefold(): item_id for item_id, ref, _ in store.library_order_items(login=False)}
    results: list[DownloadResult] = []
    pdf_dir = root / PDFS
    to_order: list[FreePublication] = []
    to_fetch: list[tuple[FreePublication, str, str]] = []
    for pub in stubs:
        dest = pdf_dir / pdf_name(pub.reference, pub.publication_id)
        prior = record.get(pub.publication_id) or {}
        archive = dest.with_suffix(".zip")
        extra: dict[str, str] = {}
        if archive.is_file() and archive.stat().st_size > 1000 and not force:
            extra = keep_related(root, archive)
        on_disk = dest if dest.is_file() and dest.stat().st_size > 1000 else None
        if on_disk is None and archive.is_file() and archive.stat().st_size > 1000:
            on_disk = archive
        if extra.get("pdf"):
            on_disk = root / extra["pdf"]
        if on_disk is not None and not force:
            _iso_mirror(on_disk, pub)
            if extra.get("artifacts"):
                prior = dict(prior)
                prior["artifacts"] = extra["artifacts"]
                record[pub.publication_id] = {**prior, "artifacts": extra["artifacts"]}
                write_record(root, record)
            results.append(
                DownloadResult(
                    pub.publication_id,
                    pub.reference,
                    on_disk,
                    on_disk.stat().st_size,
                    str(prior.get("order_item_id") or ""),
                    True,
                    "already on disk",
                )
            )
            continue
        order_item = owned.get(pub.reference.casefold())
        if order_item:
            to_fetch.append((pub, order_item, "already in library"))
        else:
            to_order.append(pub)
    if to_order:
        try:
            _order_id, failed = store.order_free_batch([pub.publication_id for pub in to_order])
        except LibError as exc:
            for pub in to_order:
                results.append(
                    DownloadResult(
                        pub.publication_id,
                        pub.reference,
                        pdf_dir / pdf_name(pub.reference, pub.publication_id),
                        0,
                        "",
                        False,
                        f"error: {exc.message}",
                    )
                )
            to_order = []
            failed = []
        else:
            owned = {ref.casefold(): item_id for item_id, ref, _ in store.library_order_items(login=True)}
            print(f"library lists {len(owned)} publication(s)", file=sys.stderr)
            failed_ids = set(failed)
            for pub in to_order:
                if pub.publication_id in failed_ids:
                    results.append(
                        DownloadResult(
                            pub.publication_id,
                            pub.reference,
                            pdf_dir / pdf_name(pub.reference, pub.publication_id),
                            0,
                            "",
                            False,
                            "error: could not add to cart",
                        )
                    )
                    continue
                order_item = owned.get(pub.reference.casefold())
                if not order_item:
                    results.append(
                        DownloadResult(
                            pub.publication_id,
                            pub.reference,
                            pdf_dir / pdf_name(pub.reference, pub.publication_id),
                            0,
                            "",
                            False,
                            "error: ordered but not yet listed in the library",
                        )
                    )
                    continue
                to_fetch.append((pub, order_item, "ordered"))
    for pub, order_item, note in to_fetch:
        dest = pdf_dir / pdf_name(pub.reference, pub.publication_id)
        try:
            size = store.fetch_pdf(order_item, dest)
            written = dest.with_suffix(".zip")
            if written.is_file() and not dest.is_file():
                dest = written
            extra = keep_related(root, dest)
            if extra.get("pdf"):
                dest = root / extra["pdf"]
                size = dest.stat().st_size
        except LibError as exc:
            results.append(
                DownloadResult(
                    pub.publication_id,
                    pub.reference,
                    dest,
                    0,
                    order_item,
                    False,
                    f"error: {exc.message}",
                )
            )
            continue
        mirror = _iso_mirror(dest, pub)
        record[pub.publication_id] = {
            "reference": pub.reference,
            "title": pub.title,
            "head": pub.head,
            "order_item_id": order_item,
            "path": str(dest.relative_to(root)).replace("\\", "/"),
            "bytes": size,
            "iso_path": str(mirror.name) if mirror is not None else "",
            "artifacts": extra.get("artifacts", ""),
        }
        write_record(root, record)
        results.append(DownloadResult(pub.publication_id, pub.reference, dest, size, order_item, False, note))
    return results

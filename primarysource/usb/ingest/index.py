"""The corpus index: ``index.json`` as described in docs/contract.md."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from primarysource.usb.models import Document, Section

SCHEMA = 1


def sha256_file(path: Path) -> str:
    """Hex sha256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def document_from_dict(raw: dict[str, object]) -> Document:
    sections = raw["sections"]
    if not isinstance(sections, list):
        raise ValueError("sections must be a list")
    return Document(
        doc_id=str(raw["doc_id"]),
        number=str(raw["number"]),
        title=str(raw["title"]),
        date=str(raw["date"]),
        status=str(raw["status"]),
        url=str(raw["url"]),
        sha256=str(raw["sha256"]),
        text_file=str(raw["text_file"]),
        sections=tuple(
            Section(
                id=str(s["id"]),
                heading=str(s["heading"]),
                start_line=int(s["start_line"]),
                end_line=int(s["end_line"]),
            )
            for s in sections
        ),
    )


def write_index(path: Path, documents: list[Document]) -> None:
    """Write ``{"schema": 1, "documents": [...]}`` atomically."""
    payload = {"schema": SCHEMA, "documents": [asdict(d) for d in documents]}
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)


def read_index(path: Path) -> list[Document]:
    """Read an index; a missing, unreadable or foreign-schema file yields no documents."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema") != SCHEMA:
            return []
        return [document_from_dict(item) for item in raw["documents"]]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []

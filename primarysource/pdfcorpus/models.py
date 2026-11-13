"""Data contract shared by the ingest pipeline and the MCP server. Change it only with both sides."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Section:
    """One numbered section of a document, located by line range in its extracted text."""

    id: str  # dotted section number, e.g. "3.2.4"
    heading: str
    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive


@dataclass(frozen=True, slots=True)
class Document:
    """One publication in the corpus index."""

    doc_id: str  # file-safe slug, e.g. "sp800-73pt2-5"
    number: str  # as cited, e.g. "NIST SP 800-73pt2-5" or "USB-IF CCID Rev 1.1"
    title: str
    date: str  # "YYYY-MM"
    status: str  # e.g. "final", "withdrawn"
    url: str  # where the user fetched the PDF
    sha256: str  # of the PDF as fetched
    text_file: str  # path relative to data/corpus/
    sections: tuple[Section, ...]

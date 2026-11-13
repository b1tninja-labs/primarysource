"""Safety rules for unpacking ZIP packages downloaded from the USB-IF site."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from primarysource.usb.ingest.acquire import _extract_pdfs, _safe_member


@pytest.mark.parametrize("name", ["spec.pdf", "docs/spec.PDF", "a/b/c.pdf"])
def test_safe_member_accepts_pdfs(name: str) -> None:
    assert _safe_member(name)


@pytest.mark.parametrize("name", ["../evil.pdf", "docs/../../evil.pdf", "/etc/passwd.pdf", "readme.txt", "spec.pdf.exe"])
def test_safe_member_refuses_traversal_absolute_and_non_pdf(name: str) -> None:
    assert not _safe_member(name)


def test_extract_writes_only_pdfs_flat_into_the_target(tmp_path: Path) -> None:
    archive = tmp_path / "pkg.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("docs/spec.pdf", b"%PDF-1.4 spec")
        zf.writestr("readme.txt", b"not a pdf")
        zf.writestr("../escape.pdf", b"%PDF-1.4 escape")
    out = tmp_path / "pdf"
    out.mkdir()
    written = _extract_pdfs(archive, out)
    assert written == ["spec.pdf"]
    assert sorted(p.name for p in out.iterdir()) == ["spec.pdf"]
    assert not (tmp_path / "escape.pdf").exists()


def test_extract_creates_the_target_directory(tmp_path: Path) -> None:
    """main() passes raw/<slug>/pdf, which does not exist on the first ZIP; the run crashed there."""
    archive = tmp_path / "pkg.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("spec.pdf", b"%PDF-1.4 spec")
    out = tmp_path / "raw" / "slug" / "pdf"
    assert _extract_pdfs(archive, out) == ["spec.pdf"]
    assert (out / "spec.pdf").read_bytes() == b"%PDF-1.4 spec"

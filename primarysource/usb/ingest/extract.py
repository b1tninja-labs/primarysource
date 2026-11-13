"""Text extraction with ``pdftotext -layout``. The section splitter is primarysource.pdfcorpus.split."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


MISSING_MESSAGE = (
    "pdftotext was not found on PATH. Install poppler-utils (on MSYS2: pacman -S mingw-w64-x86_64-poppler) "
    "and make sure pdftotext is on PATH."
)


class ExtractError(RuntimeError):
    """Raised when text extraction cannot run or fails."""


def find_pdftotext() -> str:
    """Return the path of pdftotext, or raise ExtractError saying how to get it."""
    found = shutil.which("pdftotext")
    if found is None:
        raise ExtractError(MISSING_MESSAGE)
    return found


def extract_text(pdf: Path, *, timeout: float = 300.0) -> str:
    """Run ``pdftotext -layout`` on ``pdf`` and return the text (pages separated by form feeds)."""
    exe = find_pdftotext()
    try:
        result = subprocess.run(  # noqa: S603
            [exe, "-layout", "-enc", "UTF-8", str(pdf), "-"],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ExtractError(f"pdftotext timed out after {timeout:.0f}s on {pdf}") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ExtractError(f"pdftotext failed on {pdf} (exit {result.returncode}): {detail}")
    return result.stdout.decode("utf-8", "replace")


# The splitter is shared (primarysource.pdfcorpus.split); it is re-exported here for the importers that have
# always found it in this module.
from primarysource.pdfcorpus.split import split_sections as split_sections  # noqa: E402

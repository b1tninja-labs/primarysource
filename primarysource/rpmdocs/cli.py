"""`primarysource rpmdocs import|status|docs|outline|read|search|cite`."""

from __future__ import annotations

from collections.abc import Sequence

from primarysource.pkgdocs.serving import run
from primarysource.rpmdocs.catalogue import SPEC


def main(argv: Sequence[str]) -> int:
    return run(SPEC, argv)

"""`primarysource pms import|status|docs|outline|read|search|cite`."""

from __future__ import annotations

from collections.abc import Sequence

from primarysource.pkgdocs.serving import run
from primarysource.pms.catalogue import SPEC


def main(argv: Sequence[str]) -> int:
    return run(SPEC, argv)

"""`primarysource kconfig import|status|docs|outline|read|search|cite`."""

from __future__ import annotations

from collections.abc import Sequence

from primarysource.kconfig.catalogue import SPEC
from primarysource.pkgdocs.serving import run


def main(argv: Sequence[str]) -> int:
    return run(SPEC, argv)

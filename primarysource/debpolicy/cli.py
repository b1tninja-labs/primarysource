"""`primarysource debpolicy import|status|docs|outline|read|search|cite`."""

from __future__ import annotations

from collections.abc import Sequence

from primarysource.debpolicy.catalogue import SPEC
from primarysource.pkgdocs.serving import run


def main(argv: Sequence[str]) -> int:
    return run(SPEC, argv)

"""`primarysource can ...`: built by `localpdf.cli`."""

from __future__ import annotations

from primarysource.can import SPEC
from primarysource.localpdf.cli import make_main

main = make_main(SPEC)

"""`primarysource sae ...`: built by `localpdf.cli`."""

from __future__ import annotations

from primarysource.localpdf.cli import make_main
from primarysource.sae import SPEC

main = make_main(SPEC)

"""`python -m primarysource.zim` is the same as `primarysource zim`."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

"""`python -m primarysource.itu` is the same as `primarysource itu`."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

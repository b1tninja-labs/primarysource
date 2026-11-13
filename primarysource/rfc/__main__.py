"""Allow `python -m primarysource.rfc ...` as an alias for the `rfclib` console script."""

from .cli import main

if __name__ == "__main__":
    main()
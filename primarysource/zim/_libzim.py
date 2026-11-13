"""The only place that imports the native binding.

`libzim` is a compiled extension (it carries libzim and Xapian). It ships wheels for CPython 3.11+ on
Windows x64, macOS (x86-64, arm64) and Linux (glibc and musl, x86-64 and aarch64), and nothing else, so on any
other platform `import libzim` fails. Everything that does not read a ZIM (the CLI's `info`, `catalog`, `get`,
the reference grammar, the converter) must keep working there, which is why the import is lazy and why its
failure is a `ZimloreError` naming the remedy instead of a traceback from deep inside a tool.
"""

from __future__ import annotations

import importlib
from types import ModuleType

from .errors import ZimloreError

REMEDY = (
    'pip install "primarysource[zim]" (libzim wheels: Windows x64, macOS, Linux glibc/musl; CPython 3.11+). On a '
    "platform without a wheel, build libzim from source (https://github.com/openzim/python-libzim) or serve the "
    "same files with kiwix-serve and read them in a browser"
)


def load(name: str) -> ModuleType:
    """Import `libzim.<name>` (reader, search, suggestion, writer)."""
    try:
        return importlib.import_module(f"libzim.{name}")
    except ImportError as error:
        raise ZimloreError(f"the libzim binding is not available ({error})", REMEDY) from error


def available() -> bool:
    try:
        load("reader")
    except ZimloreError:
        return False
    return True

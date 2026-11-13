"""Invented C2SP-style Markdown documents and a catalogue that pins them, for the c2sp tests. No real text."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path

from primarysource.c2sp.catalogue import Catalogue, Spec, Terms

COMMIT = "0123456789abcdef0123456789abcdef01234567"
BASE = "https://raw.githubusercontent.com/C2SP/C2SP/"

INVENTED_LOG = """\
---
description: An invented log protocol
---

> [!WARNING]
> This is the editor's copy of an invented specification.

# The Invented Log

The log publishes **checkpoints** about [widgets](https://example.invalid/widgets).

## Log Entries

First entry paragraph, mentioning the gasket and a `code span`.

Second entry paragraph, mentioning the origin line.

### Entry Format: Details

```
# not a heading, inside a fence

still the same block
```

Closing paragraph of the details.

## Another: Section

Text of the colon-titled section.

## Log Entries

A second heading with the same title.

Setext Heading
--------------

Under a setext heading.
"""

INVENTED_NOTE = """\
# Signed Note

A note is text followed by signatures. Signatures cover the text.

## Format

The text ends with a newline.
"""

DOCS = {"invented-log": INVENTED_LOG, "invented-note": INVENTED_NOTE}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def catalogue(docs: Mapping[str, str | bytes] | None = None, base: str = BASE) -> Catalogue:
    items = docs if docs is not None else dict(DOCS)
    specs = []
    for name, text in items.items():
        data = text.encode("utf-8") if isinstance(text, str) else text
        specs.append(Spec(name, f"{name}.md", name, len(data), sha(data)))
    return Catalogue(
        "C2SP/C2SP",
        COMMIT,
        base,
        Terms("CC-BY-4.0", "layer", "https://example.invalid/terms", "2026-11-12", "invented"),
        tuple(specs),
    )


def transport(
    docs: Mapping[str, str | bytes] | None = None, log: list[str] | None = None
) -> Callable[[str, int], bytes]:
    items = {
        f"{BASE}{COMMIT}/{name}.md": (t.encode("utf-8") if isinstance(t, str) else t)
        for name, t in (docs or DOCS).items()
    }

    def fetch(url: str, max_bytes: int) -> bytes:
        if log is not None:
            log.append(url)
        return items[url]

    return fetch


class Clock:
    """A fake clock and sleep, so the one-request-per-second test takes no real time."""

    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def install(home: Path) -> Path:
    """Import the invented documents under `home` and return `home`."""
    from primarysource.c2sp.importer import import_specs

    import_specs(home, cat=catalogue(), transport=transport())
    return home

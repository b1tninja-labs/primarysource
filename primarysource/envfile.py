"""Load a `.env` file into the process environment.

A stdio client starts `primarysource mcp` with whatever environment it was given, which often does not include
the user-account variables. The file in this checkout is the place those values live: the library directory,
and the ISO and IEC webstore accounts. A variable already set in the environment is left alone, so a client
that passes its own value wins, and a test that sets one is not overwritten by a developer's file.
"""

from __future__ import annotations

import os
import re
from collections.abc import MutableMapping, Sequence
from pathlib import Path

from primarysource.errors import LibError

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_EXPORT = re.compile(r"export\s+")


def candidate_paths() -> tuple[Path, ...]:
    """Files to read, first match winning: `$PRIMARYSOURCE_ENV`, the checkout `.env`, then `./.env`."""
    found: list[Path] = []
    explicit = os.environ.get("PRIMARYSOURCE_ENV", "").strip()
    if explicit:
        found.append(Path(explicit))
    checkout = Path(__file__).resolve().parents[1]
    if (checkout / "pyproject.toml").is_file():
        found.append(checkout / ".env")
    found.append(Path.cwd() / ".env")
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in found:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return tuple(unique)


def load_env(
    paths: Sequence[Path] | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> tuple[Path, ...]:
    """Set missing variables from `paths` (or `candidate_paths()`). Returns the files that existed."""
    env = os.environ if environ is None else environ
    files = candidate_paths() if paths is None else tuple(paths)
    loaded: list[Path] = []
    for path in files:
        if not path.is_file():
            continue
        apply_file(path, env)
        loaded.append(path)
    return tuple(loaded)


def apply_file(path: Path, environ: MutableMapping[str, str]) -> None:
    """Merge one file. A blank value is skipped. A line that is not a comment and has no `=` is an error."""
    text = path.read_text(encoding="utf-8-sig")
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = _EXPORT.sub("", line, count=1)
        key, separator, value = line.partition("=")
        if not separator or not _KEY.fullmatch(key.strip()):
            raise LibError(
                f"{path}:{number} is not a NAME=value line",
                "fix the line or remove it; comments start with #",
            )
        name = key.strip()
        if (environ.get(name) or "").strip():
            continue
        parsed = _unquote(value.strip())
        if parsed:
            environ[name] = parsed


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value

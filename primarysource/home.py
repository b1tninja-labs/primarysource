"""Where a library keeps its data, and writing there without leaving half a file.

One variable per library (`<APP>_HOME`), else a per-user data directory, never the working directory and never
a path beside the installed package: nistlib and usblib default to `parents[2]/data`, which points into
site-packages once installed from a wheel.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path


def resolve_home(app: str, environ: Mapping[str, str] | None = None, platform: str | None = None) -> Path:
    """`$<APP>_HOME` if set, else the per-user data directory for `app`. Nothing is created."""
    env = os.environ if environ is None else environ
    system = sys.platform if platform is None else platform
    explicit = env.get(f"{app.upper()}_HOME")
    if explicit:
        return Path(explicit)
    if system == "win32" and env.get("LOCALAPPDATA"):
        return Path(env["LOCALAPPDATA"]) / app
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / app
    if env.get("XDG_DATA_HOME"):
        return Path(env["XDG_DATA_HOME"]) / app
    return Path.home() / ".local" / "share" / app


def collection_home(
    name: str,
    legacy_app: str | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    """Where one collection keeps its library (PLAN.md §5.8). The first that applies:

    1. `$<LEGACY_APP>_HOME`, e.g. `RFCLIB_HOME`: an explicit setting from before the move keeps working;
    2. `$PRIMARYSOURCE_HOME/<name>`;
    3. the legacy app's per-user directory (`%LOCALAPPDATA%\\rfclib`), if it already exists, so an existing
       library is found instead of an empty one being started beside it;
    4. the per-user `primarysource/<name>`.

    Nothing is created.
    """
    env = dict(os.environ if environ is None else environ)
    legacy_var = f"{legacy_app.upper()}_HOME" if legacy_app else ""
    if legacy_app and env.get(legacy_var):
        return Path(env[legacy_var])
    if env.get("PRIMARYSOURCE_HOME"):
        return Path(env["PRIMARYSOURCE_HOME"]) / name
    if legacy_app:
        old = resolve_home(legacy_app, env, platform)
        if old.is_dir():
            return old
    return resolve_home("primarysource", env, platform) / name


def atomic_write(path: Path, data: bytes) -> None:
    """Write `data` to `path` through a temp file in the same directory and `os.replace`.

    A reader sees the old file or the new one, never a partial one. itulib's index rebuild unlinks first and a
    concurrent reader then sees "no index"; this is the replacement for that.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".part")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise

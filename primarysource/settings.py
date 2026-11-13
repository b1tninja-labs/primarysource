"""Per-collection settings read from the environment: the network mode and the read-only switch.

Generalised from rfclib's `config.py` (`RFCLIB_NETWORK`, `RFCLIB_READONLY`, `require_network`). One process may
serve several collections (PLAN.md §5.8), so each setting is looked up per collection, most specific first, the
same way `home.collection_home` finds the home:

1. `<LEGACY_APP>_<KEY>`, e.g. `RFCLIB_NETWORK`: a setting from before the move keeps working;
2. `PRIMARYSOURCE_<COLLECTION>_<KEY>`, e.g. `PRIMARYSOURCE_NIST_NETWORK`: one collection of a shared process;
3. `PRIMARYSOURCE_<KEY>`: every collection.

The first variable that is set and not blank decides; a more specific `0` overrides a general `1`. A value that is
not understood is an error naming the variable, never a silent fallback: `RFCLIB_NETWORK=ofline` must not fetch.

Network modes:

- `auto` (the default): fetch what is asked for, and refresh catalogues when they are stale;
- `on-demand`: fetch only when a document is asked for;
- `offline`: never touch the network; answer from what is stored.

A read-only process (`<PREFIX>_READONLY=1`) must not write its library, so it is always offline: a fetch would
have to be stored.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home

NETWORK_MODES = ("auto", "on-demand", "offline")
DEFAULT_NETWORK = "auto"
_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


class NetworkDisabled(LibError):
    """A fetch was needed and the settings forbid it (offline, or read-only)."""


def prefixes(collection: str | None = None, legacy_app: str | None = None) -> tuple[str, ...]:
    """The variable prefixes consulted for `collection`, most specific first."""
    found: list[str] = []
    if legacy_app:
        found.append(legacy_app.upper())
    if collection:
        found.append(f"PRIMARYSOURCE_{collection.upper()}")
    found.append("PRIMARYSOURCE")
    return tuple(found)


def _lookup(key: str, names: tuple[str, ...], env: Mapping[str, str]) -> tuple[str, str] | None:
    """(variable, value) of the first `<prefix>_<key>` that is set and not blank, or None."""
    for prefix in names:
        variable = f"{prefix}_{key}"
        value = (env.get(variable) or "").strip()
        if value:
            return variable, value
    return None


@dataclass(frozen=True)
class Settings:
    """One collection's settings, read once from the environment by `settings()`."""

    collection: str | None
    home: Path | None
    network: str
    read_only: bool
    network_variable: str
    """The variable that set `network` (or forced it, for a read-only process), for messages."""
    read_only_variable: str

    def require_network(self, what: str) -> None:
        """Return if `what` may be fetched now; raise `NetworkDisabled` naming the variable that forbids it."""
        if self.read_only:
            raise NetworkDisabled(
                f"{what} is not stored here and this process is read-only ({self.read_only_variable})",
                "ask the shared server that writes this library, or run the import without "
                f"{self.read_only_variable}",
            )
        if self.network == "offline":
            raise NetworkDisabled(
                f"{what} is not stored here and {self.network_variable}=offline forbids fetching it",
                f"run the import while online, or unset {self.network_variable}",
            )


def settings(
    collection: str | None = None,
    legacy_app: str | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> Settings:
    """Read `collection`'s settings. With no collection only the `PRIMARYSOURCE_*` variables apply and `home` is
    None. Raises `LibError` for a value it does not understand."""
    env = os.environ if environ is None else environ
    names = prefixes(collection, legacy_app)

    read_only, read_only_variable = False, f"{names[0]}_READONLY"
    found = _lookup("READONLY", names, env)
    if found:
        read_only_variable, value = found
        if value.lower() in _TRUE:
            read_only = True
        elif value.lower() not in _FALSE:
            raise LibError(
                f"{read_only_variable}={value!r} is not a yes or a no", f"set {read_only_variable} to 1 or 0"
            )

    network, network_variable = DEFAULT_NETWORK, f"{names[0]}_NETWORK"
    found = _lookup("NETWORK", names, env)
    if found:
        network_variable, value = found
        network = value.lower()
        if network not in NETWORK_MODES:
            raise LibError(
                f"{network_variable}={value!r} is not a network mode",
                f"set {network_variable} to one of {', '.join(NETWORK_MODES)}",
            )
    if read_only:
        network, network_variable = "offline", read_only_variable

    home = collection_home(collection, legacy_app, env, platform) if collection else None
    return Settings(collection, home, network, read_only, network_variable, read_only_variable)


def network_mode(
    collection: str | None = None, legacy_app: str | None = None, environ: Mapping[str, str] | None = None
) -> str:
    """`auto`, `on-demand` or `offline` for `collection`; always `offline` when it is read-only."""
    return settings(collection, legacy_app, environ).network


def read_only(
    collection: str | None = None, legacy_app: str | None = None, environ: Mapping[str, str] | None = None
) -> bool:
    """True when `collection` must not write its library."""
    return settings(collection, legacy_app, environ).read_only


def require_network(
    what: str,
    collection: str | None = None,
    legacy_app: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Raise `NetworkDisabled` unless `collection` may fetch `what` now. Read at each call, not cached."""
    settings(collection, legacy_app, environ).require_network(what)

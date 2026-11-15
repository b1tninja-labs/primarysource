"""A value that must never reach a log, a repr, an f-string or a traceback."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from primarysource.errors import LibError

USERNAME_VARIABLE = "PRIMARYSOURCE_IEC_USERNAME"
PASSWORD_VARIABLE = "PRIMARYSOURCE_IEC_PASSWORD"  # noqa: S105 - the name of a variable, not a password
SESSION_FILE_VARIABLE = "PRIMARYSOURCE_IEC_SESSION_FILE"


class Secret:
    """Holds a string; `repr`, `str` and formatting show `<redacted>`. `reveal()` is the one way out, and it is
    called only where the value is put on the wire."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"

    def __format__(self, spec: str) -> str:
        return "<redacted>"

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(("Secret", self._value))

    def __reduce__(self) -> tuple[type[Secret], tuple[str]]:
        raise TypeError("a Secret is never pickled")


@dataclass(frozen=True, slots=True)
class Credentials:
    """The owner's webstore login. Both fields are redacted wherever they are printed."""

    username: Secret = field(repr=False)
    password: Secret = field(repr=False)

    def __repr__(self) -> str:
        return "Credentials(<redacted>)"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Credentials:
        env = os.environ if environ is None else environ
        username = (env.get(USERNAME_VARIABLE) or "").strip()
        password = env.get(PASSWORD_VARIABLE) or ""
        if not username or not password:
            raise LibError(
                "no IEC webstore credentials in the environment",
                f"set {USERNAME_VARIABLE} and {PASSWORD_VARIABLE} (never put them in a file in a repository)",
            )
        return cls(Secret(username), Secret(password))

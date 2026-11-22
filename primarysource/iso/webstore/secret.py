"""A value that never prints."""

from __future__ import annotations

from typing import NoReturn


class Secret:
    """A value that never prints. `reveal()` is the one way out, and it is called at the single place the value is
    sent."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(<redacted>)"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return "Secret(<redacted>)"

    def __bool__(self) -> bool:
        return bool(self._value)

    def __reduce__(self) -> NoReturn:
        raise TypeError("a Secret is not serialised")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    __hash__ = None  # type: ignore[assignment]

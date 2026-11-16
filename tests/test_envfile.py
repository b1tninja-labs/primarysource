"""The `.env` file loaded at startup: the library location and the webstore accounts."""

from __future__ import annotations

from pathlib import Path

import pytest

from primarysource.envfile import apply_file, load_env
from primarysource.errors import LibError

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"


def test_a_file_fills_a_missing_variable_and_leaves_one_that_is_set(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "\n".join(
            (
                "# the library",
                "PRIMARYSOURCE_HOME=D:\\reference",
                'ISO_EMAIL="buyer@example.com"',
                "ISO_PASSWORD=",
                "export IEC_EMAIL='buyer@example.com'",
            )
        ),
        encoding="utf-8",
    )
    env = {"PRIMARYSOURCE_HOME": "C:\\already"}
    apply_file(path, env)
    assert env["PRIMARYSOURCE_HOME"] == "C:\\already"
    assert env["ISO_EMAIL"] == "buyer@example.com"
    assert env["IEC_EMAIL"] == "buyer@example.com"
    assert "ISO_PASSWORD" not in env


def test_the_first_file_wins_and_a_missing_file_is_skipped(tmp_path: Path) -> None:
    first = tmp_path / "a.env"
    second = tmp_path / "b.env"
    first.write_text("ISO_EMAIL=first@example.com\n", encoding="utf-8")
    second.write_text("ISO_EMAIL=second@example.com\nIEC_EMAIL=second@example.com\n", encoding="utf-8")
    env: dict[str, str] = {}
    loaded = load_env([first, tmp_path / "missing.env", second], env)
    assert loaded == (first, second)
    assert env == {"ISO_EMAIL": "first@example.com", "IEC_EMAIL": "second@example.com"}


def test_a_line_without_an_equals_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("NOT_A_LINE\n", encoding="utf-8")
    with pytest.raises(LibError) as raised:
        apply_file(path, {})
    assert str(path) in raised.value.message


def test_the_example_names_the_library_and_the_webstore_accounts() -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    for name in ("PRIMARYSOURCE_HOME", "ISO_EMAIL", "ISO_PASSWORD", "IEC_EMAIL", "IEC_PASSWORD"):
        assert f"{name}=" in text

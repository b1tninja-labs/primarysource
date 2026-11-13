"""ROADMAP.md cannot name a test that does not exist.

Since the move into primarysource this covers the `zl.*` rows (section 3a of the repository's ROADMAP.md); the
other sections are the repository's own matrix.

The project's rule (ROADMAP header): a row reads `[ok]` only when a named test would fail on regression. The first
half of that, that the named test is real, is mechanical, and it was already false once: a ROADMAP row once cited a
test that had never been written. This reads every obligation table (header's first column `Obligation`, with a
`Status` column), and for each `[ok]` row requires at least one `tests/<file>.py::<test>` reference, and for every
row with such references requires that the file parses and defines that exact name. `::name` continues the file of
the reference before it, as the rows are written.

It checks existence, not strength: whether a test would fail on a regression is shown by breaking the code, which
the ROADMAP says was done and which no test can do for itself. `pytest.fail` is used instead of `assert` so that
`python -O` cannot turn the check into a pass.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REF = re.compile(r"(tests/[\w./-]+\.py)|::(\w+)")
STATUSES = {"[ok]", "[part]", "[ ]", "[no]"}


def _cells(line: str) -> list[str]:
    bars = [i for i, ch in enumerate(line) if ch == "|" and (i == 0 or line[i - 1] != "\\")]
    return [line[bars[k] + 1 : bars[k + 1]].strip() for k in range(len(bars) - 1)]


def _rows() -> list[tuple[int, str, str, str]]:
    """(line number, id, status, where) for every data row of every obligation table."""
    lines = (ROOT / "ROADMAP.md").read_text(encoding="utf-8").splitlines()
    found: list[tuple[int, str, str, str]] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("|"):
            index += 1
            continue
        start = index
        while index < len(lines) and lines[index].startswith("|"):
            index += 1
        table = lines[start:index]
        if len(table) < 3 or not all(c and set(c) <= set("-: ") for c in _cells(table[1])):
            continue
        header = [h.lower() for h in _cells(table[0])]
        if not header or header[0] not in {"obligation", "id"} or "status" not in header:
            continue
        status_at = header.index("status")
        where_at = status_at + 1  # every table here ends `Status | Where`; the Future tables put prose there too
        for offset, line in enumerate(table[2:], start=start + 3):
            cells = _cells(line)
            if len(cells) <= where_at:
                continue
            if cells[0].strip("`").startswith("zl."):
                found.append((offset, cells[0].strip("`"), cells[status_at].strip("`").lower(), cells[where_at]))
    return found


def _defined(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)}


def test_the_matrix_is_found_and_every_status_is_known() -> None:
    rows = _rows()
    if len(rows) < 60:
        pytest.fail(f"expected about 65 zl.* rows, found {len(rows)}")
    unknown = [(n, i, s) for n, i, s, _ in rows if s not in STATUSES]
    if unknown:
        pytest.fail(f"unknown status in ROADMAP.md: {unknown}")


def test_every_ok_row_names_tests_and_every_named_test_exists() -> None:
    cache: dict[str, set[str]] = {}
    problems: list[str] = []
    for line, row, status, where in _rows():
        if status in {"[ ]", "[no]"}:
            continue
        current = ""
        refs: list[tuple[str, str]] = []
        for match in REF.finditer(where):
            if match.group(1):
                current = match.group(1)
            elif current:
                refs.append((current, match.group(2)))
        if status == "[ok]" and not refs:
            problems.append(f"line {line} {row}: [ok] but no tests/<file>.py::<test> reference")
        for file, name in refs:
            path = ROOT / file
            if not path.is_file():
                problems.append(f"line {line} {row}: {file} does not exist")
                continue
            if file not in cache:
                cache[file] = _defined(path)
            if name not in cache[file]:
                problems.append(f"line {line} {row}: {file}::{name} is not defined")
    if problems:
        pytest.fail("ROADMAP.md names tests that do not exist:\n  " + "\n  ".join(problems))

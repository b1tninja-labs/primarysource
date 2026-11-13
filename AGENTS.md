# Instructions for coding agents

`primarysource` is the shared core of the citable document libraries in this workspace (`rfclibrary`, `itulibrary`,
`zimlore`, `nistlibrary`, `usblibrary`): the sectioned-document model, the ref grammar, token-budgeted paging and,
as they are built, readers, a full-text index, a CLI and an MCP server. `PLAN.md` says why and in what order;
`ROADMAP.md` says what is pinned by a test.

## Finding work

If the person gave you a task, do that task. This project is not registered in `PORTFOLIO.md` yet, so the board
has no rows for it: with no task, ask the person.

## Commands

```
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy primarysource tests
```

Python 3.12+: `from __future__ import annotations`, `collections.abc`, `X | None`, `datetime.UTC`. `ruff format`
decides line breaks. Never run a formatter from above this directory.

## Rules

- **No document text in the tree.** Not a PDF, not an extract, not one clause in a fixture. ITU and USB-IF text
  cannot be redistributed; tests use invented text, and must pass with no corpus anywhere.
- **Move code here behind the tests that already pin it.** A function lifted from a library arrives with the
  library's tests for it, and the library then imports it; a second copy that drifts is the problem this
  repository exists to end.
- **Streams, not extraction.** A reader takes bytes or a stream and never unpacks an archive to disk.
- **An error names its remedy; an empty result means nothing matched.** Use `LibError(message, hint)`.
- **A result is text with the fixed footer** (`primarysource/render.py`). Do not add a footer key without adding it
  to `FOOTER_ORDER` and to `PLAN.md` §5.
- **A new dependency arrives as an extra with the reader that needs it**, and its licence is read first.
- **`[ok]` in `ROADMAP.md` needs a named test that exists.**
- Do not edit the sibling libraries from here; adoption is a change in that library, under its own `AGENTS.md`.

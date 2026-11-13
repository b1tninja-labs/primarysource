"""A tripwire, not a proof: it catches the obvious ways ZIM content could enter the repository.

ZIM files are other people's content under their own licences, and a ZIM is one binary file that git history
cannot take back. The design answer is that content only ever lives in the collection's home (ZIMLORE_HOME or
$PRIMARYSOURCE_HOME/zim); this file keeps it true.

Since the move into primarysource the file-content checks cover what came from zimlore (the zim package, its tests,
its docs and scripts); `.gitignore` and `git check-ignore` cover the whole repository.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCOPE = (ROOT / "primarysource" / "zim", ROOT / "tests" / "zim", ROOT / "docs" / "zim")
SKIP = {".venv", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__", "dist", "build"}
# Suffixes that could carry archived content. Fixtures are built at test time, into tmp_path.
FORBIDDEN = {".zim", ".zimaa", ".meta4", ".part"}


def _tree() -> list[Path]:
    found: list[Path] = []
    for base in SCOPE:
        for path in base.rglob("*"):
            if any(part in SKIP for part in path.relative_to(ROOT).parts) or not path.is_file():
                continue
            found.append(path)
    return found


def test_no_zim_content_files_are_in_the_tree() -> None:
    bad = [p for p in _tree() if p.suffix.lower() in FORBIDDEN]
    assert bad == [], f"ZIM content belongs in ZIMLORE_HOME, not the repository: {bad}"


def test_nothing_in_the_tree_is_large_enough_to_be_a_corpus() -> None:
    big = [(p, p.stat().st_size) for p in _tree() if p.stat().st_size > 512_000]
    assert big == [], f"a file this size is content, not code: {big}"


def test_gitignore_names_every_way_a_zim_can_be_spelled() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for pattern in ("*.zim", "*.zimaa", "*.meta4", "/zim/", ".zimlore/", "zimlore-home/"):
        assert pattern in ignored, f".gitignore must contain {pattern}"


def test_git_agrees_that_a_zim_would_be_ignored() -> None:
    if not (ROOT / ".git").exists():
        return  # an sdist extraction has no repository; the .gitignore text test above still ran
    for name in ("devdocs_en_flask_2026-10.zim", "zim/anything.bin", ".zimlore/x"):
        done = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT, check=False)  # noqa: S603
        assert done.returncode == 0, f"{name} would be tracked"


def test_the_zim_ignore_rule_does_not_hide_the_collections_own_code() -> None:
    """`zim/` unanchored would ignore primarysource/zim/ and tests/zim/ as well: the rule is `/zim/`."""
    if not (ROOT / ".git").exists():
        return
    for name in ("primarysource/zim/library.py", "tests/zim/test_license.py"):
        done = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT, check=False)  # noqa: S603
        assert done.returncode == 1, f"{name} is ignored"


def test_notice_states_the_content_policy() -> None:
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "contains no" in notice and "ZIMLORE_HOME" in notice

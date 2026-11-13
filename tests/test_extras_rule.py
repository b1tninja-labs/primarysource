"""PLAN.md §5.13, the self-sufficiency rule for extras, checked rather than promised.

(a) The core and every registered collection import with no extra installed. A fresh interpreter blocks every
    package any extra in `pyproject.toml` names (so a new extra is blocked as soon as it is declared) and loads
    each collection through the registry.
(b) The serving path needs nothing beyond the standard library and `mcp`. The top-level imports of the core's
    serving modules and of every collection's server module, followed through `primarysource`, may name only
    the standard library and `mcp`. An import inside a function runs only when that function does, which is how
    an ingest-time dependency such as pypdf stays off this path. A collection that does not meet the rule yet is
    named in `NOT_YET` with what it imports; that entry fails as soon as it is no longer true, so it is removed
    when the collection is fixed rather than outliving the fix.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from primarysource import registry

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "primarysource"
CORE_SERVING = ("primarysource.cli", "primarysource.serve", "primarysource.scaffold", "primarysource.render")

# Collections whose serving path still imports a package only their own extra installs. rfc: `views`, `subjects`
# and `sync` import httpx at module level to fetch a missing file or the errata on demand; `mcp` 2.3 depends on
# httpx2, not httpx, so `[mcp]` alone does not provide it. The fix is a lazy import in rfc, under cl.adopt_rfclib.
NOT_YET: dict[str, frozenset[str]] = {"rfc": frozenset({"httpx"})}


def _extra_packages() -> set[str]:
    """The import names of every package any extra requires, `dev` aside."""
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    names = set()
    for extra, specs in extras.items():
        if extra == "dev":
            continue
        for spec in specs:
            name = re.match(r"[A-Za-z0-9_.-]+", spec)
            if name and name[0] != "primarysource":
                names.add(name[0].lower().replace("-", "_"))
    return names


_PROBE = """
import importlib, importlib.abc, json, sys
blocked = set(json.loads(sys.argv[1]))

class Missing(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in blocked:
            raise ModuleNotFoundError(f"No module named {name!r} (extra not installed)", name=name)
        return None

sys.meta_path.insert(0, Missing())
from primarysource import registry
for module in json.loads(sys.argv[2]):
    importlib.import_module(module)
failed = {}
for name in registry.available():
    try:
        registry.load(name)
    except Exception as exc:
        failed[name] = f"{type(exc).__name__}: {exc}"
leaked = sorted(m for m in sys.modules if m.split(".")[0] in blocked)
print(json.dumps({"failed": failed, "leaked": leaked, "loaded": list(registry.available())}))
"""


def test_the_core_and_every_collection_import_with_no_extra_installed() -> None:
    blocked = _extra_packages()
    assert {"mcp", "pypdf", "httpx", "typer"} <= blocked  # the probe really is blocking the extras
    core = [
        "primarysource",
        *CORE_SERVING,
        "primarysource.errors",
        "primarysource.registry",
        "primarysource.budget",
        "primarysource.model",
        "primarysource.refs",
        "primarysource.home",
    ]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH")]))}
    done = subprocess.run(  # noqa: S603 - our own interpreter on our own probe
        [sys.executable, "-c", _PROBE, json.dumps(sorted(blocked)), json.dumps(core)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        check=False,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout)
    assert report["failed"] == {}
    assert report["leaked"] == []
    assert sorted(report["loaded"]) == sorted(registry.available())


def _module_file(name: str) -> Path | None:
    path = ROOT.joinpath(*name.split("."))
    for candidate in (path / "__init__.py", path.with_suffix(".py")):
        if candidate.is_file():
            return candidate
    return None


def _top_level_imports(name: str) -> list[str]:
    """Modules imported when `name` is imported: module-level statements, including inside `if` and `try`, but
    not function bodies and not `if TYPE_CHECKING:` blocks."""
    path = _module_file(name)
    assert path is not None, name
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    found: list[str] = []

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                found.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                    module = ".".join(base + ([node.module] if node.module else []))
                else:
                    module = node.module or ""
                found.append(module)
                found.extend(
                    f"{module}.{alias.name}" for alias in node.names if _module_file(f"{module}.{alias.name}")
                )
            elif isinstance(node, ast.If):
                if "TYPE_CHECKING" not in ast.unparse(node.test):
                    visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.Try):
                visit(node.body)
                for handler in node.handlers:
                    visit(handler.body)
                visit(node.orelse)
                visit(node.finalbody)

    visit(ast.parse(path.read_text(encoding="utf-8")).body)
    return found


def _outside_imports(start: str) -> dict[str, str]:
    """Every import outside the standard library and `primarysource` reached from `start`: {module: importer}."""
    outside: dict[str, str] = {}
    seen: set[str] = set()
    todo = [start]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        parts = name.split(".")
        todo.extend(".".join(parts[:i]) for i in range(1, len(parts)))  # importing a.b.c imports a and a.b
        for imported in _top_level_imports(name):
            top = imported.split(".")[0]
            if top == "primarysource":
                if _module_file(imported):
                    todo.append(imported)
            elif top not in sys.stdlib_module_names:
                outside.setdefault(top, name)
    return outside


def _serving_modules() -> dict[str, str]:
    modules = {f"core:{name}": name for name in CORE_SERVING}
    for name in registry.available():
        collection = registry.load(name)
        modules[name] = collection.server.partition(":")[0]
    return modules


@pytest.mark.parametrize(("label", "module"), sorted(_serving_modules().items()))
def test_the_serving_path_needs_only_the_standard_library_and_mcp(label: str, module: str) -> None:
    outside = {top: importer for top, importer in _outside_imports(module).items() if top != "mcp"}
    assert set(outside) == NOT_YET.get(label, frozenset()), f"{label}: the serving path imports {outside}"

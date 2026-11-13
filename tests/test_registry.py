from __future__ import annotations

import sys
import types
from collections.abc import Iterator

import pytest

from primarysource import registry
from primarysource.errors import LibError
from primarysource.model import Unit
from primarysource.refs import Ref, RefGrammar
from primarysource.registry import Collection, _Target, available, load

DEMO = Collection("demo", "Demo standards", "demo_", Unit.SENTENCE, RefGrammar(r"D\d+"))


@pytest.fixture
def demo_module() -> Iterator[str]:
    module = types.ModuleType("_ps_demo_collection")
    module.COLLECTION = DEMO  # type: ignore[attr-defined]
    sys.modules[module.__name__] = module
    yield module.__name__
    del sys.modules[module.__name__]


def test_a_registered_collection_loads_by_name(demo_module: str) -> None:
    targets = {"demo": _Target(f"{demo_module}:COLLECTION", 'pip install "primarysource[demo]"')}
    collection = load("demo", targets)
    assert collection is DEMO
    assert collection.grammar.parse("D7§1¶2").para == 2


def test_a_missing_extra_names_the_install_command() -> None:
    targets = {"demo": _Target("_ps_not_installed_anywhere:COLLECTION", 'pip install "primarysource[demo]"')}
    with pytest.raises(LibError) as caught:
        load("demo", targets)
    assert caught.value.hint == 'pip install "primarysource[demo]"'
    assert "not installed" in caught.value.message


def test_an_unknown_collection_lists_the_registered_ones() -> None:
    with pytest.raises(LibError, match=r"registered: a, b"):
        load("nope", {"a": _Target("x:Y", ""), "b": _Target("x:Y", "")})


def test_a_target_holding_the_wrong_object_is_refused(demo_module: str) -> None:
    with pytest.raises(LibError, match="does not hold"):
        load("other", {"other": _Target(f"{demo_module}:COLLECTION", "")})


def test_builtins_win_over_plugins_and_nothing_is_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "BUILTIN", {"demo": "_ps_never_imported:COLLECTION"})
    assert "demo" in available()
    assert "_ps_never_imported" not in sys.modules


def test_two_builtins_can_share_one_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        registry, "BUILTIN", {"posixdemo": "_ps_absent.mod:POSIX [shared]", "netdemo": "_ps_absent.mod:NET"}
    )
    found = registry._targets()
    assert found["posixdemo"] == _Target(
        "_ps_absent.mod:POSIX", 'pip install "primarysource[shared]"', 'pip install "primarysource[shared,mcp]"'
    )
    assert found["netdemo"].install == 'pip install "primarysource[netdemo]"'
    with pytest.raises(LibError) as caught:
        load("posixdemo", found)
    assert caught.value.hint == 'pip install "primarysource[shared]"'


def test_a_malformed_target_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "BUILTIN", {"bad": "no-colon"})
    with pytest.raises(LibError, match="malformed"):
        available()


@pytest.mark.parametrize(("name", "prefix"), [("Demo", "Demo_"), ("demo", "dm_"), ("2x", "")])
def test_names_and_prefixes_are_checked(name: str, prefix: str) -> None:
    with pytest.raises(ValueError):
        Collection(name, "t", prefix, Unit.BLOCK, RefGrammar(r"D\d+"))


def test_a_missing_server_names_the_shared_extra_and_mcp(monkeypatch: pytest.MonkeyPatch, demo_module: str) -> None:
    monkeypatch.setattr(registry, "BUILTIN", {"demo": f"{demo_module}:COLLECTION [shared]"})
    collection = load("demo")
    with pytest.raises(LibError) as caught:
        registry.attribute(collection, "_ps_absent_server:mcp", "server")
    assert caught.value.hint == 'pip install "primarysource[shared,mcp]"'
    with pytest.raises(LibError) as caught:
        registry.attribute(collection, "_ps_absent_cli:main", "command line")
    assert caught.value.hint == 'pip install "primarysource[shared]"'


class _IdKeyed:
    """A ref parser for id-keyed refs (`demo:1d6b:0002`) that RefGrammar cannot express."""

    def parse(self, text: str) -> Ref:
        doc, sep, key = text.partition(":")
        if not sep or doc != "demo" or not key:
            raise LibError(f"not a demo ref: {text!r}", "write demo:<id>")
        return Ref(doc=doc, section=key)

    def format(self, ref: Ref) -> str:
        return f"{ref.doc}:{ref.section}"


def test_a_collection_may_bring_its_own_ref_parser() -> None:
    collection = Collection("demo", "Demo registry", "demo_", Unit.BLOCK, _IdKeyed())
    ref = collection.grammar.parse("demo:1d6b:0002")
    assert ref == Ref(doc="demo", section="1d6b:0002")
    assert collection.grammar.format(ref) == "demo:1d6b:0002"
    with pytest.raises(LibError):
        collection.grammar.parse("other:1")

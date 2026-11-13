"""Per-collection network and read-only settings (`primarysource.settings`). Environments are passed in, not set."""

from __future__ import annotations

from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.settings import NetworkDisabled, network_mode, read_only, require_network, settings


def test_network_defaults_to_auto_and_reads_each_mode() -> None:
    assert network_mode("nist", environ={}) == "auto"
    for mode in ("auto", "on-demand", "offline"):
        assert network_mode("nist", environ={"PRIMARYSOURCE_NETWORK": f" {mode.upper()} "}) == mode


def test_the_most_specific_variable_wins_per_collection() -> None:
    env = {"PRIMARYSOURCE_NETWORK": "offline", "PRIMARYSOURCE_RFC_NETWORK": "on-demand", "RFCLIB_NETWORK": "auto"}
    assert network_mode("rfc", "rfclib", env) == "auto"
    assert network_mode("rfc", None, env) == "on-demand"
    assert network_mode("nist", None, env) == "offline"
    assert network_mode(None, None, env) == "offline"
    found = settings("rfc", None, env)
    assert found.network_variable == "PRIMARYSOURCE_RFC_NETWORK"


def test_a_blank_variable_is_unset() -> None:
    env = {"PRIMARYSOURCE_RFC_NETWORK": "  ", "PRIMARYSOURCE_NETWORK": "offline"}
    assert network_mode("rfc", None, env) == "offline"


def test_an_unknown_mode_is_an_error_not_a_fallback_to_auto() -> None:
    with pytest.raises(LibError) as raised:
        network_mode("rfc", "rfclib", {"RFCLIB_NETWORK": "ofline"})
    assert "RFCLIB_NETWORK" in raised.value.message
    assert "on-demand" in raised.value.hint


def test_read_only_forces_offline_and_a_specific_no_overrides_a_general_yes() -> None:
    env = {"PRIMARYSOURCE_READONLY": "yes", "PRIMARYSOURCE_NETWORK": "auto"}
    assert read_only("nist", environ=env)
    assert network_mode("nist", environ=env) == "offline"
    assert settings("nist", environ=env).network_variable == "PRIMARYSOURCE_READONLY"
    env["PRIMARYSOURCE_NIST_READONLY"] = "0"
    assert not read_only("nist", environ=env)
    assert network_mode("nist", environ=env) == "auto"
    assert read_only("rfc", "rfclib", {"RFCLIB_READONLY": "on"})


def test_an_unknown_read_only_value_is_an_error() -> None:
    with pytest.raises(LibError, match="PRIMARYSOURCE_READONLY"):
        read_only(environ={"PRIMARYSOURCE_READONLY": "maybe"})


def test_require_network_names_the_variable_that_forbids_it() -> None:
    require_network("x", "nist", environ={"PRIMARYSOURCE_NETWORK": "on-demand"})
    with pytest.raises(NetworkDisabled) as offline:
        require_network("SP 800-1", "nist", environ={"PRIMARYSOURCE_NIST_NETWORK": "offline"})
    assert "SP 800-1" in offline.value.message
    assert "PRIMARYSOURCE_NIST_NETWORK" in offline.value.hint
    with pytest.raises(NetworkDisabled) as readonly:
        require_network("RFC 1", "rfc", "rfclib", {"RFCLIB_READONLY": "1", "RFCLIB_NETWORK": "auto"})
    assert "read-only" in readonly.value.message
    assert "RFCLIB_READONLY" in readonly.value.message
    assert isinstance(readonly.value, LibError)


def test_settings_carry_the_collection_home(tmp_path: Path) -> None:
    env = {"PRIMARYSOURCE_HOME": str(tmp_path)}
    assert settings("nist", environ=env).home == tmp_path / "nist"
    assert settings("rfc", "rfclib", {**env, "RFCLIB_HOME": str(tmp_path / "old")}).home == tmp_path / "old"
    assert settings(environ=env).home is None

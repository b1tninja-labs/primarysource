"""The terms-acknowledgement gate: the variable, the refusal, the record and the serving check.

Everything here is invented: a made-up collection and publisher, and environments passed in as dicts. No test
sets a real collection's variable outside `monkeypatch`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from primarysource import terms
from primarysource.errors import LibError
from primarysource.terms import Terms

T = Terms("widgets", "Widget Works")
HOME = Path("/data/widgets")
YES = {"PRIMARYSOURCE_WIDGETS_ACCEPT_TERMS": "1"}


def test_the_variable_is_named_for_the_collection() -> None:
    assert T.variable == "PRIMARYSOURCE_WIDGETS_ACCEPT_TERMS"


def test_only_one_true_yes_says_accepted_and_unset_or_a_no_says_not() -> None:
    for yes in ("1", "true", "TRUE", "Yes", " yes "):
        assert terms.accepted(T, {T.variable: yes}) is True
    for no in (None, "", "  ", "0", "false", "No", "off"):
        assert terms.accepted(T, {} if no is None else {T.variable: no}) is False


def test_an_unrecognised_value_is_an_error_naming_the_variable_not_a_silent_no() -> None:
    with pytest.raises(LibError, match="PRIMARYSOURCE_WIDGETS_ACCEPT_TERMS='maybe' is not a yes or a no") as raised:
        terms.accepted(T, {T.variable: "maybe"})
    assert "set PRIMARYSOURCE_WIDGETS_ACCEPT_TERMS to 1" in raised.value.hint


def test_the_variable_is_per_collection_and_the_general_one_does_not_count() -> None:
    assert terms.accepted(T, {"PRIMARYSOURCE_ACCEPT_TERMS": "1", "PRIMARYSOURCE_OTHER_ACCEPT_TERMS": "1"}) is False


def test_the_refusal_names_the_variable_and_the_home_and_a_url_only_when_one_is_given() -> None:
    with pytest.raises(LibError) as raised:
        terms.require_accepted(T, HOME, "the import", {})
    text = raised.value.as_text()
    assert "PRIMARYSOURCE_WIDGETS_ACCEPT_TERMS" in text and str(HOME) in text and "Widget Works" in text
    assert "http" not in text
    with pytest.raises(LibError) as linked:
        terms.require_accepted(
            Terms("widgets", "Widget Works", "https://example.invalid/terms"), HOME, "the import", {}
        )
    assert "https://example.invalid/terms" in linked.value.as_text()


def test_no_refusal_when_the_variable_says_yes() -> None:
    terms.require_accepted(T, HOME, "the import", YES)


def test_a_recorded_acknowledgement_keeps_the_first_timestamp_per_document_across_imports() -> None:
    record: dict[str, object] = {"documents": {}}
    first = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    terms.record_acceptance(T, record, ["a"], YES, first)
    later = datetime(2026, 6, 7, 8, 9, 10, tzinfo=UTC)
    terms.record_acceptance(T, record, ["a", "b"], YES, later)
    assert record[terms.RECORD_KEY] == {
        "variable": "PRIMARYSOURCE_WIDGETS_ACCEPT_TERMS",
        "documents": {"a": "2026-01-02T03:04:05+00:00", "b": "2026-06-07T08:09:10+00:00"},
    }
    assert terms.recorded(record) == record[terms.RECORD_KEY]["documents"]  # type: ignore[index]


def test_a_timestamp_is_utc_whatever_the_clock_zone() -> None:
    from datetime import timedelta, timezone

    record: dict[str, object] = {}
    terms.record_acceptance(T, record, ["a"], YES, datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=5))))
    assert terms.recorded(record) == {"a": "2026-01-01T07:00:00+00:00"}


def test_nothing_is_recorded_for_an_owner_who_did_not_assert() -> None:
    record: dict[str, object] = {"documents": {}}
    with pytest.raises(LibError, match="is not set to 1, true or yes"):
        terms.record_acceptance(T, record, ["a"], {})
    assert terms.RECORD_KEY not in record


def test_a_malformed_record_counts_as_no_acknowledgement() -> None:
    for bad in (
        {},
        {terms.RECORD_KEY: "yes"},
        {terms.RECORD_KEY: {"documents": ["a"]}},
        {terms.RECORD_KEY: {"documents": {"a": 1}}},
    ):
        assert terms.recorded(bad) == {}


def test_serving_needs_both_the_variable_and_a_record_for_the_document() -> None:
    record: dict[str, object] = {"documents": {"a": {}, "b": {}}}
    terms.record_acceptance(T, record, ["a"], YES)
    terms.require_served(T, record, ["a"], HOME, "a read", "primarysource widgets import", YES)
    with pytest.raises(LibError, match="PRIMARYSOURCE_WIDGETS_ACCEPT_TERMS is not set"):
        terms.require_served(T, record, ["a"], HOME, "a read", "primarysource widgets import", {})
    with pytest.raises(LibError, match="no terms acknowledgement is recorded for b") as raised:
        terms.require_served(T, record, ["a", "b"], HOME, "a read", "primarysource widgets import", YES)
    assert raised.value.action == "primarysource widgets import"
    # the variable alone is not enough: an index built outside the gate has no record
    with pytest.raises(LibError, match="no terms acknowledgement is recorded for a"):
        terms.require_served(T, {"documents": {}}, ["a"], HOME, "a read", "primarysource widgets import", YES)

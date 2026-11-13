from __future__ import annotations

import pytest

from primarysource.budget import page, tokens


def test_tokens_round_up_at_four_characters() -> None:
    assert [tokens(""), tokens("a"), tokens("abcd"), tokens("abcde")] == [0, 1, 1, 2]


def test_paging_follows_next_and_loses_nothing() -> None:
    units = [f"unit {n} " + "x" * 30 for n in range(1, 12)]
    seen: list[str] = []
    start: int | None = 1
    pages = 0
    while start is not None:
        result = page(units, start=start, max_tokens=25)
        assert result.first == start and result.last == start + len(result.units) - 1
        seen.extend(result.units)
        start = result.next_start
        pages += 1
    assert seen == units
    assert pages > 1


def test_a_page_always_makes_progress_when_one_unit_exceeds_the_budget() -> None:
    result = page(["x" * 400, "small"], start=1, max_tokens=10)
    assert result.units == ("x" * 400,)
    assert result.oversize
    assert result.next_start == 2


def test_a_unit_is_never_split() -> None:
    result = page(["a" * 40, "b" * 40], start=1, max_tokens=15)
    assert result.units == ("a" * 40,)
    assert not result.oversize


def test_the_last_page_has_no_next() -> None:
    result = page(["one", "two"], start=2, max_tokens=100)
    assert (result.units, result.next_start, result.total) == (("two",), None, 2)


def test_a_start_past_the_end_is_an_empty_page_not_an_error() -> None:
    result = page(["one"], start=5)
    assert (result.units, result.first, result.last, result.next_start) == ((), 0, 0, None)


@pytest.mark.parametrize(("start", "max_tokens"), [(0, 10), (1, 0)])
def test_nonsense_arguments_are_refused(start: int, max_tokens: int) -> None:
    with pytest.raises(ValueError):
        page(["one"], start=start, max_tokens=max_tokens)

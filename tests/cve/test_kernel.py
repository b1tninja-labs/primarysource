"""The traps found in real `.dyad` data. Kept next to the logic they protect."""

from __future__ import annotations

from primarysource.cve.kernel import (
    Pair,
    affects,
    explain,
    fallback_ranges,
    fixed_in_by_branch,
    is_kernel_product,
    parse_dyad,
    parse_version,
    version_caveats,
)

V = (6, 18, 62)


def pairs(*items: tuple[tuple[int, ...], tuple[int, ...]]) -> list[Pair]:
    return [Pair(start, "", fix, "") for start, fix in items]


def test_fix_on_own_branch_at_or_before_version_clears_it() -> None:
    table = pairs(((4, 14), (6, 18, 22)), ((4, 14), (7, 0)))
    assert not affects(table, V)
    assert explain(table, V).reason == "fixed_on_branch"
    assert affects(table, (6, 18, 20))


def test_dead_branch_zero_marker_is_not_a_finding() -> None:
    table = pairs(((5, 14, 15), (0,)), ((5, 15), (5, 15, 5)), ((5, 15), (5, 16)))
    assert not affects(table, V)
    assert explain(pairs(((5, 14, 15), (0,))), V).reason == "dead_branch_zero_ignored"


def test_zero_marker_counts_on_own_branch_or_from_mainline() -> None:
    assert affects(pairs(((6, 18, 40), (0,))), V)
    assert affects(pairs(((5, 10), (0,))), V)


def test_later_mainline_fix_without_backport_is_a_finding() -> None:
    assert affects(pairs(((2, 6, 24), (7, 2, 10)), ((2, 6, 24), (7, 3))), V)


def test_bug_introduced_after_this_version_does_not_apply() -> None:
    table = pairs(((6, 19), (7, 1)))
    assert not affects(table, V)
    assert explain(table, V).reason == "introduced_later"


def test_release_candidates_parse() -> None:
    assert parse_version("4.4-rc1") == (4, 4)


def test_regression_reopened_on_own_branch_survives_an_earlier_fix() -> None:
    # Fixed in 6.18.22, broken again in 6.18.40, fixed in 6.18.70: 6.18.62 sits in the reopened window.
    table = pairs(((4, 14), (6, 18, 22)), ((6, 18, 40), (6, 18, 70)))
    assert explain(table, V).reason == "open_range"
    assert not affects(table, (6, 18, 30))


def test_unpaired_zero_is_closed_by_a_later_fix_on_the_branch() -> None:
    # Real shape, CVE-2026-53145: dyad could pair one of three introducing commits; 6.18.36 fixes the bug.
    table = pairs(((6, 18, 32), (6, 18, 36)), ((6, 18, 33), (0,)), ((6, 18, 35), (0,)))
    assert not affects(table, V)
    assert affects(table, (6, 18, 34))


def test_zero_starting_after_the_last_fix_stays_open() -> None:
    # Real shape, CVE-2026-89639: fixed at 6.18.50, introduced again at 6.18.51.
    table = pairs(((6, 18, 44), (6, 18, 50)), ((6, 18, 51), (0,)))
    assert explain(table, V).reason == "unfixed_on_branch"
    assert not affects(table, (6, 18, 50))


def test_stable_introduction_after_fix_on_older_branch() -> None:
    table = pairs(((6, 6, 51), (6, 6, 133)), ((6, 11), (6, 12, 77)), ((6, 11), (6, 13)), ((6, 10, 10), (0,)))
    assert affects(table, (6, 10, 12))  # zero on its own branch
    assert not affects(table, (6, 10, 5))  # before the stable backport introduced it
    assert not affects(table, (6, 12, 80))  # fixed on 6.12.x
    assert affects(table, (6, 12, 10))
    assert affects(table, (6, 6, 60))
    assert not affects(table, (6, 6, 200))
    assert not affects(table, (6, 13, 2))  # mainline fix in 6.13, branch 6.13 at or above it


def test_unknown_introduction_uses_the_fix_only() -> None:
    table = pairs(((0,), (5, 10, 219)), ((0,), (6, 1, 90)), ((0,), (6, 9)))
    assert not affects(table, (5, 10, 300))
    assert affects(table, (5, 15, 100))
    assert not affects(table, (6, 9, 1))


def test_zero_zero_line_says_nothing() -> None:
    assert not affects(pairs(((0,), (0,))), V)


def test_version_spellings() -> None:
    assert parse_version("v6.18.20-1-lts") == (6, 18, 20)
    assert parse_version("6.18.0") == parse_version("6.18")


def test_mainline_release_at_fix_counts_as_fixed() -> None:
    assert not affects(pairs(((6, 1), (6, 18))), (6, 18))


def test_dyad_format_skips_comments_and_keeps_git_ids() -> None:
    table = parse_dyad("# dyad\n6.6.51:aaa:6.6.133:bbb\n6.10.10:ccc:0:0\nnot a line\n")
    assert [p.text for p in table] == ["6.6.51 -> 6.6.133", "6.10.10 -> 0"]
    assert table[0].fix_git == "bbb"
    assert table[1].fix == (0,)


def test_fixed_in_by_branch() -> None:
    table = pairs(((6, 6, 51), (6, 6, 133)), ((6, 11), (6, 12, 77)), ((6, 11), (6, 13)), ((6, 10, 10), (0,)))
    assert fixed_in_by_branch(table) == {"6.6": "6.6.133", "6.12": "6.12.77", "6.13": "6.13"}


def test_distro_suffix_is_flagged() -> None:
    assert version_caveats("5.14.0-503.el9")
    assert version_caveats("6.18.62") == []


def test_kernel_product_spellings() -> None:
    assert is_kernel_product({"vendor": "n/a", "product": "Kernel"})
    assert is_kernel_product({"vendor": "Linux", "product": "Linux Kernel"})
    assert not is_kernel_product({"vendor": "Microsoft Corporation", "product": "Windows Kernel"})
    assert not is_kernel_product({"vendor": "Red Hat", "product": "kernel"})


def test_fallback_ignores_wildcards_and_uses_ranges() -> None:
    wildcard: list[dict[str, object]] = [
        {"vendor": "Linux", "product": "kernel", "versions": [{"version": "*", "status": "affected"}]}
    ]
    assert fallback_ranges(wildcard, V) == ([], 0)
    ranged: list[dict[str, object]] = [
        {
            "vendor": "Linux",
            "product": "Linux Kernel",
            "versions": [{"version": "6.0", "lessThan": "6.19", "status": "affected"}],
        }
    ]
    assert fallback_ranges(ranged, V) == (["6.0 -> 6.19"], 1)
    out: list[dict[str, object]] = [
        {
            "vendor": "Linux",
            "product": "Linux Kernel",
            "versions": [{"version": "5.0", "lessThan": "5.10", "status": "affected"}],
        }
    ]
    assert fallback_ranges(out, V) == ([], 1)

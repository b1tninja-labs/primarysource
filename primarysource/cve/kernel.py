"""Does a kernel CVE apply to one version? Read from the kernel CNA's `.dyad` files.

A `.dyad` line is `vulnerable:git:fixed:git`, one per place the bug was introduced and (maybe) fixed:

    6.6.51:c031...:6.6.133:9a3a...    bug arrived in 6.6.51, fixed in 6.6.133 on that stable branch
    6.11:c3a5...:6.13:a718...         bug arrived in mainline 6.11, fixed in mainline 6.13
    6.10.10:8d58...:0:0               arrived in 6.10.10, no fix on that branch

The trap is the last form. A `0` fix means unfixed *on that start version's own branch*, which is often a stable
branch that died long ago (`5.14.15:...:0:0`). Counting it as "unfixed everywhere" flags every later kernel. The rule
here is `kconfigscope/tools/cve_reach.py` plus one correction: a bug whose introduction on the version's own branch
comes *after* the last fix there (`6.18.51:...:0:0` beside a fix at 6.18.50) is still present.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import CvelibError

Version = tuple[int, ...]

ZERO: Version = (0,)
DEFAULT_RC_NOTE = "A release candidate is treated as the release it leads to."


def parse_version(text: str) -> Version:
    """`6.18.62`, `v6.18`, `4.4-rc1`, `6.18.20-1-lts`: the numeric dotted head of a kernel version string."""
    head = text.strip().lower().removeprefix("v").split("-", 1)[0].split("+", 1)[0]
    parts = head.split(".")
    if not head or not all(part.isdigit() for part in parts):
        raise CvelibError(f"not a kernel version: {text!r}", "Give a dotted version such as 6.18.62 or 6.12.")
    numbers = [int(part) for part in parts]
    # 6.18.0 and 6.18 are the same release; keeping one spelling makes tuple comparison correct.
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers)


def version_caveats(text: str) -> list[str]:
    """What the caller's version string implies that this data cannot speak to."""
    notes: list[str] = []
    suffix = text.strip().lower().removeprefix("v").split("-", 1)
    if len(suffix) == 2 and suffix[1].startswith("rc"):
        notes.append(DEFAULT_RC_NOTE)
    elif len(suffix) == 2 and suffix[1]:
        notes.append(
            f"The suffix '-{suffix[1]}' looks like a distribution or local build. kernel.org data knows mainline "
            "and stable releases, not distribution backports: check the distribution's own tracker too."
        )
    return notes


@dataclass(frozen=True)
class Pair:
    """One dyad line. `start` of `(0,)` means the introducing commit is unknown; `fix` of `(0,)` means no fix."""

    start: Version
    start_git: str
    fix: Version
    fix_git: str

    @property
    def text(self) -> str:
        return f"{_show(self.start)} -> {_show(self.fix)}"


def _show(version: Version) -> str:
    return "0" if version == ZERO else ".".join(str(part) for part in version)


def parse_dyad(text: str) -> list[Pair]:
    """Every `vulnerable:git:fixed:git` line. Comments and malformed lines are skipped, not guessed at."""
    pairs: list[Pair] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.count(":") != 3:
            continue
        start, start_git, fix, fix_git = line.split(":")
        try:
            pairs.append(Pair(parse_version(start), start_git, parse_version(fix), fix_git))
        except CvelibError:
            continue
    return pairs


@dataclass(frozen=True)
class Verdict:
    affected: bool
    reason: str
    detail: str
    evidence: tuple[str, ...]


def _is_mainline(version: Version) -> bool:
    return len(version) <= 2


def explain(pairs: list[Pair], version: Version) -> Verdict:
    """Whether the bug is present in `version`, preferring the fix on that version's own stable branch."""
    branch = version[:2]

    # A range opened on this branch and still open here is decisive: it survives an earlier fix on the branch.
    # A `0` entry is weaker than a stated fix: dyad emits one for each introducing commit it could not pair, so a fix
    # on this branch at or after that entry's start closes it. Only a start *after* every such fix reopens the bug.
    branch_fixes = [pair.fix for pair in pairs if pair.fix != ZERO and pair.fix[:2] == branch and pair.fix <= version]
    for pair in pairs:
        same_branch_start = pair.start != ZERO and pair.start[:2] == branch and not _is_mainline(pair.start)
        if not same_branch_start or pair.start > version:
            continue
        if pair.fix == ZERO:
            if not any(fix >= pair.start for fix in branch_fixes):
                detail = f"no fix on {_show(branch)}.x since {_show(pair.start)}"
                return Verdict(True, "unfixed_on_branch", detail, (pair.text,))
        elif pair.fix[:2] == branch and pair.fix > version:
            return Verdict(True, "open_range", f"fixed on this branch only in {_show(pair.fix)}", (pair.text,))

    # Then the fix on this branch, which is what decides almost every longterm kernel.
    fixes_here = [pair for pair in pairs if pair.fix != ZERO and pair.fix[:2] == branch and pair.fix <= version]
    if fixes_here:
        best = max(fixes_here, key=lambda pair: pair.fix)
        return Verdict(False, "fixed_on_branch", f"fixed on this branch in {_show(best.fix)}", (best.text,))

    dead_zero: list[Pair] = []
    open_pairs: list[Pair] = []
    for pair in pairs:
        if pair.start == ZERO and pair.fix == ZERO:
            continue  # says nothing at all
        if pair.start > version:
            continue
        if pair.fix == ZERO:
            if _is_mainline(pair.start) or pair.start[:2] == branch:
                open_pairs.append(pair)
            else:
                dead_zero.append(pair)
        elif pair.fix > version:
            open_pairs.append(pair)

    if open_pairs:
        pair = open_pairs[0]
        if pair.fix == ZERO:
            detail = f"unfixed from mainline {_show(pair.start)}"
        elif pair.start == ZERO:
            detail = f"introduction unknown; first fix past this version is {_show(pair.fix)}"
        else:
            detail = (
                f"present since {_show(pair.start)}, no fix on {_show(branch)}.x, fixed later in {_show(pair.fix)}"
            )
        return Verdict(True, "open_range", detail, tuple(item.text for item in open_pairs[:4]))

    if dead_zero:
        return Verdict(
            False,
            "dead_branch_zero_ignored",
            "the only open entries are '0' fixes on other stable branches, which say nothing about this one",
            tuple(pair.text for pair in dead_zero[:4]),
        )
    if pairs and all(pair.start > version for pair in pairs if pair.start != ZERO):
        return Verdict(False, "introduced_later", "every recorded introduction is newer than this version", ())
    return Verdict(False, "fixed_before_version", "every recorded range closes at or before this version", ())


def affects(pairs: list[Pair], version: Version) -> bool:
    return explain(pairs, version).affected


def fixed_in_by_branch(pairs: list[Pair]) -> dict[str, str]:
    """`{"6.6": "6.6.133", "6.12": "6.12.77", "6.13": "6.13"}`, the earliest fix recorded on each branch."""
    best: dict[Version, Version] = {}
    for pair in pairs:
        if pair.fix == ZERO:
            continue
        branch = pair.fix[:2]
        if branch not in best or pair.fix < best[branch]:
            best[branch] = pair.fix
    return {_show(branch): _show(best[branch]) for branch in sorted(best)}


def unfixed_starts(pairs: list[Pair]) -> list[str]:
    return sorted({_show(pair.start) for pair in pairs if pair.fix == ZERO and pair.start != ZERO})


WILDCARD_VERSIONS = {"", "*", "0", "n/a", "unspecified", "unknown", "-"}
KERNEL_PRODUCTS = {"linux", "kernel", "linux kernel", "linux_kernel"}


def is_kernel_product(entry: dict[str, object]) -> bool:
    vendor = str(entry.get("vendor") or "").lower()
    product = str(entry.get("product") or "").lower()
    # Real spellings outside the kernel CNA include ("n/a", "Kernel") and ("Linux", "Linux Kernel").
    anonymous = vendor in {"", "n/a"}
    if product in {"linux kernel", "linux_kernel"}:
        return True
    if product == "kernel":
        return "linux" in vendor or anonymous
    return product == "linux" and "linux" in vendor


def fallback_ranges(affected: list[dict[str, object]], version: Version) -> tuple[list[str], int]:
    """Evaluate a non-kernel-CNA record's ranges for `version`.

    Returns `(matches, usable)`. A record with no upper bound and a wildcard start (the usual NVD and early MITRE
    kernel record) carries no usable range: such a record is noise, and it contributes nothing here.
    """
    matches: list[str] = []
    usable = 0
    for entry in affected:
        if not is_kernel_product(entry):
            continue
        for item in entry.get("versions") or []:  # type: ignore[attr-defined]
            if not isinstance(item, dict) or item.get("status") != "affected":
                continue
            start_text = str(item.get("version") or "").strip().lower()
            upper = str(item.get("lessThan") or item.get("lessThanOrEqual") or "").strip()
            inclusive = bool(item.get("lessThanOrEqual"))
            if upper in {"", "*"} or upper.endswith(".*"):
                upper = ""
            if start_text in WILDCARD_VERSIONS and not upper:
                continue
            try:
                start = parse_version(start_text) if start_text not in WILDCARD_VERSIONS else ZERO
                end = parse_version(upper) if upper else None
            except CvelibError:
                continue
            usable += 1
            if end is None:
                if start == version:
                    matches.append(f"{start_text}")
                continue
            if start <= version and (version < end or (inclusive and version == end)):
                matches.append(f"{start_text or '0'} -> {upper}")
    return matches, usable

"""Named sets of catalogue names for `zimlore sync --group NAME`. Names only: no content, no URLs, no paths.

**The membership below is an EDITORIAL DEFAULT, not a decision.** Which documentation a "core" set should hold is
the maintainer's call (`docs/library-management.md` section 6, "should groups ship in the package"); until that is
made these sets are a starting point that a manifest can ignore, and a user who disagrees loses nothing by naming
libraries directly. They were chosen from catalogue sizes measured on 2026-11-07 (the catalogue lengths summed
to about 52 MB for `languages-core`, 29 MB for `web-testing` and 42 MB for `infra`, of which 32 MB is Terraform).

Every member is a DevDocs ZIM (`devdocs_en_<slug>`); `tests/test_sync.py` checks each is a valid catalogue name.
"""

from __future__ import annotations

EDITORIAL_DEFAULT = True
"""True while the membership awaits the maintainer's decision (library-management.md section 6)."""


def _devdocs(*slugs: str) -> tuple[str, ...]:
    return tuple(f"devdocs_en_{slug}" for slug in slugs)


GROUPS: dict[str, tuple[str, ...]] = {
    "languages-core": _devdocs(
        "python", "rust", "go", "php", "node", "npm", "typescript", "javascript", "c", "cpp", "ruby", "openjdk"
    ),
    "web-testing": _devdocs(
        "html", "css", "dom", "http", "playwright", "cypress", "pytest", "jest", "vitest", "puppeteer", "mocha"
    ),
    "infra": _devdocs("bash", "git", "docker", "sqlite", "postgresql", "terraform", "kubectl"),
}

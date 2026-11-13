"""The CVE collection as primarysource sees it. Importing this needs nothing beyond the core."""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.refs import RefGrammar
from primarysource.registry import Collection

# cvelib's refs: CVE-2024-14027, CVE-2024-14027§references, CVE-2024-14027§references¶21. The section is one of a
# fixed set of lower-case names (service.SECTIONS); ¶n is the nth item of a list section (reference, affected
# entry, kernel range), not a paragraph of prose. The tools already carry the cve_ prefix.
COLLECTION = Collection(
    name="cve",
    title="CVE records merged with the Linux kernel CNA, CISA KEV and FIRST EPSS, synced by the user",
    prefix="cve_",
    unit=Unit.BLOCK,
    grammar=RefGrammar(r"CVE-\d{4}-\d{4,}", r"[a-z]+"),
    server="primarysource.cve.mcp:build",
    cli="primarysource.cve.cli:main",
)

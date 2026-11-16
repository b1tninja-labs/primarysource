"""SAE standards from the owner's own copies of the PDFs.

A local-only volume on the shared `primarysource.localpdf` mechanism, behind the terms-acknowledgement gate
(`primarysource.terms`): `primarysource sae import` refuses unless `PRIMARYSOURCE_SAE_ACCEPT_TERMS` says the owner
has read the terms under which the copies were obtained and accepts them. The gate records that assertion; it does
not check anyone's licence. SAE standards are sold, usually under a single-user or company licence, so the copies
belong in the owner's home folder only: never in this repository or an image (`docs/sae.md`). SAE's terms URL was
not verified, so the gate names none.

Two files are recognised by name: `J2735_V201603.pdf` (SAE J2735, March 2016) and `sae.j1979.2002.pdf` (SAE J1979,
2002, as posted by Public.Resource.Org). Any other name is skipped with a note, never guessed at; add a rule in
`name_file` for a new document.
"""

from __future__ import annotations

import re

from primarysource.localpdf import LocalPdfSpec, LocalRefs
from primarysource.localpdf.spec import DocId
from primarysource.model import Unit
from primarysource.registry import Collection
from primarysource.terms import Terms

TERMS = Terms("sae", "SAE International", None)

_J2735 = re.compile(r"^J2735[ _-]?V?(?P<ym>\d{6})\b.*\.pdf$", re.IGNORECASE)
_J1979 = re.compile(r"^(?:sae[._ -])?j1979[._ -](?P<year>\d{4})\b.*\.pdf$", re.IGNORECASE)


def name_file(name: str, digest: str) -> DocId | None:
    """`J2735_V201603.pdf` is `j2735-201603`; `sae.j1979.2002.pdf` is `j1979-2002`. `digest` is not needed."""
    m = _J2735.match(name)
    if m:
        ym = m["ym"]
        return DocId(f"j2735-{ym}", f"j2735-{ym}", f"SAE J2735 ({ym[:4]}-{ym[4:]})", "DSRC Message Set Dictionary")
    m = _J1979.match(name)
    if m:
        year = m["year"]
        return DocId(f"j1979-{year}", f"j1979-{year}", f"SAE J1979 ({year})", "E/E Diagnostic Test Modes")
    return None


SPEC = LocalPdfSpec(
    name="sae",
    title="SAE standards",
    terms=TERMS,
    name_file=name_file,
    instructions=(
        "SAE standards (J2735, J1979) from the user's own copies of the PDFs. Loop: sae_search('<words>') -> "
        "sae_read('<ref>'). Refs: 'sae:j2735-201603§6.1' (a bookmarked clause), '...¶3' (from its 3rd sentence). "
        "sae_outline('<doc>') lists clauses as refs; sae_docs lists what is imported. Check the edition: these are "
        "older editions, not the current ones. Every tool refuses until the owner has set "
        "PRIMARYSOURCE_SAE_ACCEPT_TERMS; the error says what to do."
    ),
    ref_example="sae:j2735-201603§6.1¶2",
    front_matter=True,
)

SAE = Collection(
    name="sae",
    title="SAE standards from the owner's own PDFs",
    prefix="sae_",
    unit=Unit.SENTENCE,
    grammar=LocalRefs(SPEC),
    server="primarysource.sae.server:server",
    cli="primarysource.sae.cli:main",
)
"""Refs: `sae:j2735-201603§6.1¶2`: the document (`<standard>-<edition>`), a clause as the PDF's bookmarks number
it, and `¶n`, the nth sentence of the clause's span."""

__all__ = ["SAE", "SPEC", "TERMS"]

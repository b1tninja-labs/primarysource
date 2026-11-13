"""What an Internet-Draft's own legends say about reuse, read from its text and, when it has one, its XML.

This is information for `info`, not legal advice. The sources are:

- BCP 78 (RFC 5378) §3.6: contributors keep the copyright in their Internet-Drafts and grant the IETF Trust
  non-exclusive rights; §5.4: the Trust sublicenses them for the IETF Standards Process and may sublicense more;
- the IETF Trust's Trust Legal Provisions 5.0, §3.c: anyone may copy, publish, display and distribute a
  Contribution "in full and without modification", or unmodified portions with attribution, and §3.d: no licence
  to modify outside the Standards Process, and none to distribute without the required legends. §1.b and §1.c:
  that applies to Contributions submitted after 2015-03-25; older ones stay under the policy in force then;
- RFC 7991 Appendix A.1.1: the `ipr` values, three of which add a legend that withdraws the right to modify.

So a draft is not covered by one blanket licence: the answer depends on its submission date and its legends.
That is why this collection stores drafts on the reader's own volume and never in an image (docs/draft.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NONE = "none"
NO_MODIFICATION = "no-modification"
NO_DERIVATIVES = "no-derivatives"
PRE_5378 = "pre-5378"

TLP5_EFFECTIVE = (2015, 3, 25)

_IPR = {
    "trust200902": NONE,
    "nomodificationtrust200902": NO_MODIFICATION,
    "noderivativestrust200902": NO_DERIVATIVES,
    "pre5378trust200902": PRE_5378,
}
_YEAR = re.compile(r"Copyright \(c\) (\d{4}) IETF Trust")
_NO_DERIVATIVES = re.compile(r"may not be published except as an Internet-Draft", re.I)
_NO_MODIFICATION = re.compile(
    r"This document may not be modified, and derivative works of it may not be created", re.I
)
_PRE_5378 = re.compile(
    r"may contain material from IETF Documents or IETF Contributions published or made publicly", re.I
)


@dataclass(frozen=True, slots=True)
class Licence:
    """`restriction` is one of NONE, NO_MODIFICATION, NO_DERIVATIVES, PRE_5378; `year` is the copyright year of
    the IETF Trust notice, 0 if there is none; `ipr` is the xml2rfc `ipr` attribute, or ''."""

    restriction: str
    year: int
    ipr: str

    def summary(self) -> str:
        """One line for `info`."""
        parts = []
        if self.year and self.year < TLP5_EFFECTIVE[0]:
            parts.append(
                f"copyright {self.year}: submitted before the Trust Legal Provisions 5.0 (2015-03-25), so the "
                "policy in force at its submission applies, not TLP 5.0 (TLP 5.0 §1.c)"
            )
        elif self.year:
            parts.append(f"copyright {self.year} IETF Trust and the authors; Trust Legal Provisions 5.0 §3.c applies")
        else:
            parts.append("no IETF Trust copyright notice found: check the draft's own legends")
        if self.restriction == NO_MODIFICATION:
            parts.append("its legend forbids modification (TLP 6.c.i)")
        elif self.restriction == NO_DERIVATIVES:
            parts.append("its legend forbids modification and publication except as an Internet-Draft (TLP 6.c.ii)")
        elif self.restriction == PRE_5378:
            parts.append("its pre-5378 legend limits modification outside the IETF Standards Process (TLP 6.c.iii)")
        return "; ".join(parts)


def detect(text: str, xml_ipr: str = "") -> Licence:
    """Read the legend from the text (whitespace collapsed, since the legend wraps) and the XML `ipr`. A legend in
    the text wins over the attribute, because the text is what a reader sees."""
    flat = " ".join(text.split())
    restriction = NONE
    if _NO_DERIVATIVES.search(flat):
        restriction = NO_DERIVATIVES
    elif _PRE_5378.search(flat):
        restriction = PRE_5378
    elif _NO_MODIFICATION.search(flat):
        restriction = NO_MODIFICATION
    if restriction == NONE:
        restriction = _IPR.get(xml_ipr.lower(), NONE)
    match = _YEAR.search(flat)
    return Licence(restriction, int(match.group(1)) if match else 0, xml_ipr)

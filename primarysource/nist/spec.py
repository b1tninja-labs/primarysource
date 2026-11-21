"""The nist collection's settings for the shared skeleton (primarysource.pdfcorpus)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from primarysource.nist.paths import corpus_dir
from primarysource.pdfcorpus.models import Document
from primarysource.pdfcorpus.spec import CorpusSpec
from primarysource.standing import Edition, warning


def publication_name(key: str) -> str:
    """A reference with its issuer stripped: "nist sp 800-53 low" -> "800-53 low", "nist csf" -> "csf"."""
    name = re.sub(r"^nist ", "", key)
    return re.sub(r"^(special publication|sp|csrc) ", "", name)


def _read_defaults(root: Path) -> Mapping[str, str]:
    from primarysource.nist.ingest.status import read_defaults

    return read_defaults(root)


_REVISION = re.compile(r"r\d+")


def _revision_stem(doc_id: str) -> str:
    """The publication id with its revision token removed: ``sp800-53r4`` and ``sp800-53r5-oscal`` are one stem."""
    return _REVISION.sub("", doc_id).removesuffix("-oscal")


def _revision(doc_id: str) -> str:
    match = _REVISION.search(doc_id)
    return match.group(0) if match else ""


def publication_standing(document: Document, defaults: Mapping[str, str]) -> str:
    """The current doc_id, when this document is another revision of that same publication.

    An addendum or a part that merely shares a parsed number (``sp800-38a-add`` beside ``sp800-38a``) is a
    different document. The same revision in another form (the OSCAL of ``r5``) is not an older text.
    """
    from primarysource.nist.ingest.status import csrc_number_for, publication_key

    number = csrc_number_for(document.doc_id)
    if number is None:
        return ""
    current = defaults.get(publication_key(number))
    if not current or current == document.doc_id:
        return ""
    if _revision_stem(document.doc_id) != _revision_stem(current):
        return ""
    if _revision(document.doc_id) == _revision(current):
        return ""
    reading = Edition(document.doc_id, 0, current=False)
    return warning(reading, (reading, Edition(current, 1)))


SPEC = CorpusSpec(
    name="nist",
    server_name="nistlib",
    env_var="NISTLIB_CORPUS",
    fetch_command="primarysource nist fetch",
    index_command="primarysource nist index",
    default_dir=corpus_dir,
    instructions=(
        "NIST publications (SP 800-73 PIV, SP 800-78, SP 800-76, FIPS 201) from a locally fetched corpus. search('<words>') -> read('<doc_id>§<section>') -> cite('<doc_id>§<section>'). Search hits start with that ref; a read's 'next:' line is a ref to pass back to read. Documents are addressed by doc_id or by number. Check info(doc) for status before quoting. A missing corpus or search index is an error whose 'action:' line is the command to run (`primarysource nist fetch`, `primarysource nist index`)."
    ),
    cite_example="NIST SP 800-73pt2-5 §3.2.4",
    read_defaults=_read_defaults,
    alias=publication_name,
    standing=publication_standing,
)

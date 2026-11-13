"""The nist collection's settings for the shared skeleton (primarysource.pdfcorpus)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from primarysource.nist.paths import corpus_dir
from primarysource.pdfcorpus.spec import CorpusSpec


def publication_name(key: str) -> str:
    """A reference with its issuer stripped: "nist sp 800-53 low" -> "800-53 low", "nist csf" -> "csf"."""
    name = re.sub(r"^nist ", "", key)
    return re.sub(r"^(special publication|sp|csrc) ", "", name)


def _read_defaults(root: Path) -> Mapping[str, str]:
    from primarysource.nist.ingest.status import read_defaults

    return read_defaults(root)


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
    cite_example='NIST SP 800-73pt2-5 §3.2.4',
    read_defaults=_read_defaults,
    alias=publication_name,
)

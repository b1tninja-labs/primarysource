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
    default_dir=corpus_dir,
    instructions=(
        "NIST publications (SP 800-73 PIV, SP 800-78, SP 800-76, FIPS 201) from a locally fetched corpus. search('<question>') -> read(doc, section=<id>) -> cite(doc, section=<id>). Documents are addressed by doc_id or by number. Check info(doc) for status before quoting. If the corpus is missing, tools say so and name `primarysource nist fetch`."
    ),
    cite_example='NIST SP 800-73pt2-5 §3.2.4',
    read_defaults=_read_defaults,
    alias=publication_name,
)

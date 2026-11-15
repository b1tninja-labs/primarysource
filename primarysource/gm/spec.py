"""The gm collection's settings for the shared skeleton (primarysource.pdfcorpus)."""

from __future__ import annotations

from primarysource.gm.paths import corpus_dir
from primarysource.pdfcorpus.spec import CorpusSpec

SPEC = CorpusSpec(
    name="gm",
    server_name="gm",
    env_var="PRIMARYSOURCE_GM_CORPUS",
    fetch_command="primarysource gm import",
    index_command="primarysource gm index",
    default_dir=corpus_dir,
    instructions=(
        "GM's own published OBD documents (Mode $06 definitions, per-group diagnostic parameter files), from the "
        "owner's local copies. Tools are named gm_<tool>. search('<words or a DTC such as P0010>') -> "
        "read('<doc_id>§<section>') -> cite('<doc_id>§<section>'). Refs look like gm:17OBDG01-hybrid§P0010 or "
        "gm:mode6-can§01-02; the gm: prefix is optional. Sections follow the tables, not numbered clauses: read a "
        "section whole, because wrapped table cells are interleaved line by line. A missing corpus or index is an "
        "error whose 'action:' line is the command to run (`primarysource gm import`, `primarysource gm index`)."
    ),
    cite_example="GM 17OBDG01 Hybrid Diagnostics §P0010",
    ref_prefix="gm:",
)

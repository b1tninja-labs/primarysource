"""The bluetooth collection's settings for the shared skeleton (primarysource.pdfcorpus)."""

from __future__ import annotations

from primarysource.bluetooth.paths import corpus_dir
from primarysource.pdfcorpus.spec import CorpusSpec

SPEC = CorpusSpec(
    name="bluetooth",
    server_name="bluetooth",
    env_var="PRIMARYSOURCE_BLUETOOTH_CORPUS",
    fetch_command="primarysource bluetooth fetch",
    index_command="primarysource bluetooth index",
    default_dir=corpus_dir,
    instructions=(
        "Bluetooth SIG specifications (Core, profiles, services, mesh, assigned-number supplements), fetched by the "
        "user from bluetooth.com. Tools are named bluetooth_<tool>. search('<words>') -> "
        "read('<doc_id>§<section>') -> cite('<doc_id>§<section>'). Documents are addressed by doc_id, the last part "
        "of the spec's page address (core-specification-6-3, battery-service, hands-free-profile-1-10), or by "
        "number. Refs look like bluetooth:battery-service§3.1; the bluetooth: prefix is optional. Check info(doc) "
        "for status (adopted, draft, deprecated, withdrawn) before quoting. A missing corpus or index is an error "
        "whose 'action:' line is the command to run (`primarysource bluetooth fetch` or `... index`)."
    ),
    cite_example="Bluetooth Battery Service 1.1 §3.1",
    ref_prefix="bluetooth:",
)

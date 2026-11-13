"""The usb collection's settings for the shared skeleton (primarysource.pdfcorpus)."""

from __future__ import annotations

from primarysource.usb.paths import corpus_dir
from primarysource.pdfcorpus.spec import CorpusSpec


SPEC = CorpusSpec(
    name="usb",
    server_name="usblib",
    env_var="USBLIB_CORPUS",
    fetch_command="primarysource usb fetch",
    index_command="primarysource usb index",
    default_dir=corpus_dir,
    instructions=(
        "USB-IF specifications from a locally fetched corpus. search('<words>') -> read('<doc_id>§<section>') -> cite('<doc_id>§<section>'). Search hits start with that ref; a read's 'next:' line is a ref to pass back to read. Documents are addressed by doc_id or by number. Check info(doc) for status before quoting. A missing corpus or search index is an error whose 'action:' line is the command to run (`primarysource usb fetch`, `primarysource usb index`)."
    ),
    cite_example='USB-IF CCID Rev 1.1 §6.1.1',
)

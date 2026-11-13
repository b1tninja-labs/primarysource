"""The usb collection's settings for the shared skeleton (primarysource.pdfcorpus)."""

from __future__ import annotations

from primarysource.usb.paths import corpus_dir
from primarysource.pdfcorpus.spec import CorpusSpec


SPEC = CorpusSpec(
    name="usb",
    server_name="usblib",
    env_var="USBLIB_CORPUS",
    fetch_command="primarysource usb fetch",
    default_dir=corpus_dir,
    instructions=(
        "USB-IF specifications from a locally fetched corpus. search('<question>') -> read(doc, section=<id>) -> cite(doc, section=<id>). Documents are addressed by doc_id or by number. Check info(doc) for status before quoting. If the corpus is missing, tools say so and name `primarysource usb fetch`."
    ),
    cite_example='USB-IF CCID Rev 1.1 §6.1.1',
)

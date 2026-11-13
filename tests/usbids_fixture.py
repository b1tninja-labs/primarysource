"""An invented `usb.ids`, in the real file's shape, and a transport that serves it. No real entries.

Names are made up (`Gizmo Works`, `Frobnicator`) and the ids are from ranges nobody is claimed to own; the
structure (tab depth, section tags, the Latin-1 byte, the doubled-space quirk) is what the real file has.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from primarysource.usbids import importer
from primarysource.usbids.importer import Pin, Response

SAMPLE = (
    b"#\n"
    b"#\tList of USB ID's\n"
    b"#\n"
    b"# Version: 2099.01.02\n"
    b"# Date:    2099-01-02 03:04:05\n"
    b"#\n"
    b"\n"
    b"# Vendors, devices and interfaces.\n"
    b"0001  Gizmo Works\n"
    b"\t0002  Frobnicator 2000\n"
    b"\t0003   Frobnicator Mini\n"
    b"\t\t01  Control interface\n"
    b"0a0a  Sprocket Ltd.\n"
    b"\t0001  Frobnicator 2000 clone\n"
    b"0B0B  Upper Case Id\n"
    b"\n"
    b"# List of known device classes, subclasses and protocols\n"
    b"C 00  (Defined at Interface level)\n"
    b"C 09  Hub\n"
    b"\t00  Unused\n"
    b"\t\t00  Full speed\n"
    b"\t\t02  TT per port\n"
    b"C ff  Vendor Specific Class\n"
    b"\n"
    b"AT 0201  Microphone\n"
    b"HID 21  HID\n"
    b"R 04  Usage Page\n"
    b"BIAS 1  Right Hand\n"
    b"PHY 01  Hand\n"
    b"HUT 01  Generic Desktop Controls\n"
    b"\t006  Keyboard\n"
    b"\t030  Direction-X\n"
    b"HUT 07  Keyboard/Keypad\n"
    b"\t001  Keyboard ErrorRollOver\n"
    b"L 0409  English\n"
    b"\t01  US\n"
    b"HCC 09  German\n"
    b"VT 0201  Camera Sensor\n"
)

DIGEST = hashlib.sha256(SAMPLE).hexdigest()
PIN = Pin(version="2099.01.02", date="2099-01-02 03:04:05", size=len(SAMPLE), sha256=DIGEST)


class FakeTransport:
    """Serves `body` for every source and records each call. `plan` may map a url to a canned `Response`."""

    def __init__(self, body: bytes = SAMPLE, plan: Mapping[str, Response] | None = None) -> None:
        self.body = body
        self.plan = dict(plan or {})
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> Response:
        self.calls.append((url, dict(headers)))
        if url in self.plan:
            return self.plan[url]
        if headers.get("If-None-Match") == '"v1"':
            return Response(304, {}, b"")
        return Response(200, {"etag": '"v1"', "last-modified": "Fri, 02 Jan 2099 03:04:05 GMT"}, self.body)


def install(tmp: Path) -> Path:
    """Import SAMPLE into `tmp / 'usbids'` and return that directory."""
    base = tmp / "usbids"
    importer.import_usbids(base=base, transport=FakeTransport(), pin=PIN, sleep=lambda _s: None)
    return base

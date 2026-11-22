"""The owner's-products part of the webstore client: the Vaadin UI conversation and the PDF download. Invented UIDL in
the shape the capture shows; a fake transport; no network."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from test_iso_webstore_fakes import BASE, FakeStream, make_session, reply

from primarysource.errors import LibError
from primarysource.iso.webstore import HttpRequest, HttpResponse, LicenceConfirmation, ObpSession, download_owned
from primarysource.iso.webstore.download import server_filename
from primarysource.iso.webstore.obp import UiState, basket_urls, parse_products

KEY = "key-for-tests-only"
PAGE = (
    '<html><body><div id="obpui-1" class="v-app"></div><script>'
    'vaadin.initApplication("obpui-1",{"theme":"iso-red","versionInfo":{"vaadinVersion":"8.14.3"}});</script></body></html>'
)
TYPES = {"com.vaadin.ui.Label": 1, "com.vaadin.ui.Button": 2, "com.vaadin.server.FileDownloader": 3}
LABEL, BUTTON, DOWNLOADER = "1", "2", "3"


def label(text: str) -> dict[str, Any]:
    return {"text": text}


def button(caption: str) -> dict[str, Any]:
    return {"caption": caption}


def products_state() -> tuple[dict[str, Any], dict[str, str]]:
    """Two rows: one with the licence unassigned (10-17), one assigned with a download link (20-26)."""
    state = {
        "10": label("ISO/IEC\xa099999-1:2031"),
        "11": label("(en)"),
        "12": label("Invented title of the first publication"),
        "13": button("PDF"),
        "14": label("Assign licence #1 to"),
        "15": button("you"),
        "16": label("or"),
        "17": button("someone else"),
        "20": label("ISO\xa088888:2030"),
        "21": label("(en)"),
        "22": label("Invented title of the second publication"),
        "23": button("PDF"),
        "24": {"resources": {"dl": {"uRL": "app://APP/connector/0/24/dl"}}},
    }
    types = {
        "10": LABEL,
        "11": LABEL,
        "12": LABEL,
        "13": BUTTON,
        "14": LABEL,
        "15": BUTTON,
        "16": LABEL,
        "17": BUTTON,
        "20": LABEL,
        "21": LABEL,
        "22": LABEL,
        "23": BUTTON,
        "24": DOWNLOADER,
    }
    return state, types


def uidl(
    sync: int, client: int, state: dict[str, Any] | None = None, types: dict[str, str] | None = None, **extra: Any
) -> str:
    body = {"syncId": sync, "clientId": client, "changes": [], "state": state or {}, "types": types or {}, "rpc": []}
    body.update(extra)
    return "for(;;);[" + json.dumps(body) + "]"


class Obp:
    """A scripted browsing platform that checks the RPC envelope the way a Vaadin server would."""

    def __init__(self) -> None:
        self.rpcs: list[dict[str, Any]] = []
        self.sync = 1
        self.clicks: list[str] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method == "GET" and request.url == f"{BASE}/obp/ui":
            return reply(200, PAGE)
        if request.method == "POST" and request.url.startswith(f"{BASE}/obp/ui?v-"):
            assert b"v-browserDetails=1" in (request.body or b"") and b"obpui-1" in (request.body or b"")
            first = {
                "Vaadin-Security-Key": KEY,
                "syncId": 1,
                "clientId": 0,
                "resynchronize": True,
                "state": {},
                "types": {},
                "typeMappings": TYPES,
            }
            return reply(200, json.dumps({"v-uiId": 0, "uidl": json.dumps(first)}))
        assert request.url == f"{BASE}/obp/ui/UIDL/?v-uiId=0", request.url
        payload = json.loads(request.body or b"{}")
        assert (
            payload["csrfToken"] == KEY and payload["syncId"] == self.sync and payload["clientId"] == len(self.rpcs)
        )
        self.rpcs.append(payload)
        self.sync += 1
        if payload.get("resynchronize"):
            state, types = products_state()
            return reply(200, uidl(self.sync, len(self.rpcs) - 1, state, types, resynchronize=True))
        calls = payload["rpc"]
        if calls and calls[0][2] == "click":
            target = calls[0][0]
            self.clicks.append(target)
            if target == "15":  # the "you" button: the platform asks for confirmation
                return reply(
                    200,
                    uidl(
                        self.sync,
                        len(self.rpcs) - 1,
                        {"30": label("sure?"), "31": button("Ok"), "32": button("Cancel")},
                        {"30": LABEL, "31": BUTTON, "32": BUTTON},
                    ),
                )
            if target == "31":  # Ok: the row now offers the PDF
                return reply(
                    200,
                    uidl(
                        self.sync,
                        len(self.rpcs) - 1,
                        {"18": {"resources": {"dl": {"uRL": "app://APP/connector/0/18/dl"}}}},
                        {"18": DOWNLOADER},
                    ),
                )
        return reply(200, uidl(self.sync, len(self.rpcs) - 1))


def opened() -> tuple[ObpSession, Obp]:
    script = Obp()
    session, _, _ = make_session(script)
    obp = ObpSession(session, now=lambda: 1.0)
    obp.open()
    return obp, script


def test_open_replays_the_handshake_and_reads_the_product_rows() -> None:
    obp, script = opened()
    assert [r["rpc"][0][2] if r["rpc"] else "resync" for r in script.rpcs] == ["resize", "resync"]
    first, second = obp.products()
    assert (
        first.designation == "ISO/IEC 99999-1:2031" and first.language == "en" and "first publication" in first.title
    )
    assert first.assign_button == "15" and first.download_paths == () and first.format_buttons == ("13",)
    assert second.designation == "ISO 88888:2030" and second.assign_button is None
    assert second.download_paths == ("/obp/ui/APP/connector/0/24/dl",)


def test_assigning_a_licence_is_a_dry_run_until_confirmed() -> None:
    obp, script = opened()
    first = obp.products()[0]
    assert not obp.assign_licence(first).executed and script.clicks == []
    with pytest.raises(LibError):
        obp.assign_licence(first, LicenceConfirmation("ISO 88888:2030"))
    assert script.clicks == []
    result = obp.assign_licence(first, LicenceConfirmation("ISO/IEC 99999-1:2031"))
    assert result.executed and script.clicks == ["15", "31"]
    with pytest.raises(LibError):
        obp.assign_licence(obp.products()[1], LicenceConfirmation("ISO 88888:2030"))  # nothing to press


def test_parse_ignores_a_page_without_products_and_basket_urls_are_elided() -> None:
    ui = UiState()
    ui.apply({"state": {"1": label("Your products")}, "types": {"1": LABEL}, "typeMappings": TYPES})
    assert parse_products(ui) == ()
    seen = basket_urls(
        {
            "rpc": [
                [
                    "285",
                    "org.example.HttpRequestClientRpc",
                    "open",
                    [f"{BASE}/webstore/MiniShoppingBasket?memberId=ISO&purchaseId=a~b~c~d"],
                ]
            ]
        }
    )
    assert seen == (f"{BASE}/webstore/MiniShoppingBasket?memberId=ISO&purchaseId=<elided>",)


# --- the download -------------------------------------------------------------------------------------------------

PDF = b"%PDF-1.7\n" + bytes(range(256)) * 50


def _downloader(
    body: bytes = PDF, disposition: str = 'attachment; filename="ISO_IEC_99999_2031(en).pdf"', status: int = 200
) -> Any:
    def stream(request: HttpRequest) -> FakeStream:
        assert request.url == f"{BASE}/obp/ui/APP/connector/0/24/dl"
        return FakeStream(status, body, {"Content-Disposition": disposition})

    return stream


PATH = "/obp/ui/APP/connector/0/24/dl"


def test_download_streams_to_part_verifies_and_replaces(tmp_path: Path) -> None:
    session, transport, _ = make_session(lambda r: reply(500), _downloader())
    done = download_owned(session, PATH, tmp_path)
    assert done.path == tmp_path / "ISO_IEC_99999_2031(en).pdf" and done.size == len(PDF) and not done.reused
    assert done.sha256 == hashlib.sha256(PDF).hexdigest() and done.path.read_bytes() == PDF
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ISO_IEC_99999_2031(en).pdf"]  # no .part, no .lock left
    again = download_owned(session, PATH, tmp_path)
    assert again.reused and again.sha256 == done.sha256
    assert transport.requests[0].headers["User-Agent"].startswith("primarysource")


@pytest.mark.parametrize(
    ("body", "disposition", "status"),
    [
        (b"<html>session expired</html>", 'attachment; filename="a.pdf"', 200),
        (b"", 'attachment; filename="a.pdf"', 200),
        (PDF, 'attachment; filename="../../evil.exe"', 200),
        (PDF, "attachment", 200),
        (PDF, 'attachment; filename="a.pdf"', 404),
    ],
    ids=["not-a-pdf", "empty", "bad-name", "no-name", "http-404"],
)
def test_download_keeps_nothing_it_cannot_trust(tmp_path: Path, body: bytes, disposition: str, status: int) -> None:
    session, _, _ = make_session(lambda r: reply(500), _downloader(body, disposition, status))
    with pytest.raises(LibError):
        download_owned(session, PATH, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_download_refuses_other_paths_and_repositories(tmp_path: Path) -> None:
    session, transport, _ = make_session(lambda r: reply(500), _downloader())
    for bad in ("/obp/ui/en/content/x", "https://www.iso.org" + PATH, "/obp/ui/APP/connector/0/24/dl?x=1"):
        with pytest.raises(LibError):
            download_owned(session, bad, tmp_path)
    assert transport.requests == []
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(LibError):
        download_owned(session, PATH, tmp_path / "repo")
    assert transport.requests == []


def test_server_filename_is_reduced_to_a_plain_pdf_name() -> None:
    assert server_filename("attachment; filename=ISO_IEC_1_2030(en).pdf") == "ISO_IEC_1_2030(en).pdf"
    assert server_filename("attachment; filename*=UTF-8''X_1(en).pdf") == "X_1(en).pdf"
    assert server_filename('attachment; filename="a/b/c.pdf"') == "c.pdf"
    with pytest.raises(LibError):
        server_filename('attachment; filename="c.exe"')

"""The owner's own products, in the Online Browsing Platform (OBP): which publications they hold, assigning the
licence to themselves, and the link their PDF downloads from.

SCOPE. This reads the page "Your products" (`#account/products`) and the one download link it carries. It does
NOT read, search, outline or export any standard's text: ISO's terms forbid scraping and text-and-data-mining of the
OBP and of the no-cost content (docs/iso.md section 3), so this module has no call that opens a standard, a search
result or a table of contents in the OBP, and none will be added.

HOW THE OBP WORKS (docs/iso-webstore.md section 6). It is a Vaadin 8 application: no REST endpoints, one stateful UI.
The browser loads `/obp/ui`, posts its details, receives the whole UI as JSON ("UIDL"), and from then on posts RPCs
(`click` on connector 11034) to `/obp/ui/UIDL/`. A purchased PDF is a `FileDownloader` extension whose resource
`app://APP/connector/<ui>/<connector>/dl` is valid for that UI session only: the link cannot be known without the UI
session, which is why this module holds one. All of this is reconstructed from one capture and is unproven against
the live site (docs/iso-webstore.md section 9).
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from primarysource.errors import LibError
from primarysource.iso.webstore.session import BASE, WebstoreSession

UI_URL = f"{BASE}/obp/ui"
UIDL_URL = f"{BASE}/obp/ui/UIDL/"
PRODUCTS_FRAGMENT = "account/products"
WSVER = "8.14.3"
"""The Vaadin version the capture reports. Sent in the RPC envelope as the browser does."""
_DL = re.compile(r"app://APP/connector/(\d+)/(\d+)/dl")
DL_PATH = re.compile(r"/obp/ui/APP/connector/\d+/\d+/dl")
_DESIGNATION = re.compile(r"(?:ISO|IEC)(?:/[A-Z]+)*\s+(?:[A-Z]{2,5}\s+)?\d")
_LANGUAGE = re.compile(r"\(([a-z]{2})\)")
_MOUSE = {
    "altKey": False,
    "button": "LEFT",
    "clientX": 10,
    "clientY": 10,
    "ctrlKey": False,
    "metaKey": False,
    "relativeX": 5,
    "relativeY": 5,
    "shiftKey": False,
    "type": 1,
}


class UiState:
    """The UI's connectors as the server last described them: id to state, id to type, type to class name."""

    def __init__(self) -> None:
        self.state: dict[str, dict[str, Any]] = {}
        self.types: dict[str, str] = {}
        self.type_names: dict[str, str] = {}

    def apply(self, uidl: dict[str, Any]) -> None:
        if uidl.get("resynchronize"):
            self.state.clear()
            self.types.clear()
        for cid, value in (uidl.get("state") or {}).items():
            if isinstance(value, dict):
                self.state.setdefault(str(cid), {}).update(value)
        self.types.update({str(k): str(v) for k, v in (uidl.get("types") or {}).items()})
        for name, number in (uidl.get("typeMappings") or {}).items():
            self.type_names[str(number)] = str(name)

    def kind(self, cid: str) -> str:
        """The short class name of a connector (`Button`, `Label`, `FileDownloader`), or ''."""
        return self.type_names.get(self.types.get(cid, ""), "").rsplit(".", 1)[-1]

    def ids(self) -> list[str]:
        return sorted(self.state, key=lambda cid: int(cid) if cid.isdigit() else -1)


@dataclass(frozen=True, slots=True)
class OwnedProduct:
    designation: str
    language: str
    title: str
    format_buttons: tuple[str, ...] = ()
    assign_button: str | None = None
    """The "you" button of "Assign licence #1 to you or someone else": present while the licence is unassigned."""
    download_paths: tuple[str, ...] = ()
    """`/obp/ui/APP/connector/<ui>/<id>/dl`: ready only once the licence is assigned. Valid for this UI session."""


def _text(value: Any) -> str:
    return str(value).replace("\xa0", " ").strip()


def parse_products(ui: UiState) -> tuple[OwnedProduct, ...]:
    """The product rows of "Your products", read from connector ids in the order the server created them.

    A row starts at a Label that reads as a designation, followed by a `(en)` language label and a title label; its
    buttons captioned PDF are the formats, "you" is the assign button, and a FileDownloader carries the link.
    """
    rows: list[dict[str, Any]] = []
    for cid in ui.ids():
        kind, state = ui.kind(cid), ui.state[cid]
        if kind == "Label":
            text = _text(state.get("text", ""))
            if _DESIGNATION.match(text):
                rows.append(
                    {"designation": text, "language": "", "title": "", "formats": [], "assign": None, "dl": []}
                )
            elif rows:
                language = _LANGUAGE.fullmatch(text)
                if language and not rows[-1]["language"]:
                    rows[-1]["language"] = language[1]
                elif len(text) > 3 and not rows[-1]["title"] and "licen" not in text.lower():
                    rows[-1]["title"] = text
        elif kind == "Button" and rows:
            caption = _text(state.get("caption", ""))
            if caption == "PDF":
                rows[-1]["formats"].append(cid)
            elif caption.lower() == "you" and rows[-1]["assign"] is None:
                rows[-1]["assign"] = cid
        elif kind == "FileDownloader" and rows:
            link = _DL.fullmatch(str((state.get("resources") or {}).get("dl", {}).get("uRL", "")))
            if link:
                rows[-1]["dl"].append(f"/obp/ui/APP/connector/{link[1]}/{link[2]}/dl")
    return tuple(
        OwnedProduct(r["designation"], r["language"], r["title"], tuple(r["formats"]), r["assign"], tuple(r["dl"]))
        for r in rows
    )


def basket_urls(uidl: dict[str, Any]) -> tuple[str, ...]:
    """The basket URLs the server asks the browser to open (`HttpRequestClientRpc.open`), the purchase id elided.

    When the browsing platform adds an item the server answers with such an RPC; the browser then performs the GET.
    Returned only so a person can see the shape; this module never follows them."""
    found: list[str] = []
    for rpc in uidl.get("rpc") or ():
        if (
            isinstance(rpc, list)
            and len(rpc) >= 4
            and str(rpc[1]).endswith("HttpRequestClientRpc")
            and rpc[2] == "open"
        ):
            found.append(re.sub(r"purchaseId=[^&]+", "purchaseId=<elided>", str(rpc[3][0])))
    return tuple(found)


@dataclass(frozen=True, slots=True)
class LicenceConfirmation:
    """Permission to assign licence #1 of one product to the signed-in user."""

    designation: str


@dataclass(frozen=True, slots=True)
class AssignResult:
    executed: bool
    product: OwnedProduct
    products: tuple[OwnedProduct, ...] = field(default=())


class ObpSession:
    """One browsing-platform UI session. `open()` first; the caller has signed in to the OBP already
    (`auth.login(session, credentials, start=auth.OBP_LOGIN)`)."""

    def __init__(self, session: WebstoreSession, *, now: Callable[[], float] = time.time) -> None:
        self._session = session
        self._now = now
        self._ui = UiState()
        self._ui_id: str | None = None
        self._key = ""
        self._sync = 0
        self._client = 0

    @property
    def ui(self) -> UiState:
        return self._ui

    # --- the UIDL conversation ---

    def open(self, fragment: str = PRODUCTS_FRAGMENT) -> None:
        page = self._session.request("GET", UI_URL)
        if page.status != 200:
            raise LibError(
                f"/obp/ui: HTTP {page.status}", "sign in to the browsing platform first (auth.login with OBP_LOGIN)"
            )
        text = page.text()
        app = re.search(r'initApplication\("(obpui-\d+)"', text)
        theme = re.search(r'"theme":"([A-Za-z0-9_-]+)"', text)
        if not app:
            raise LibError(
                "the browsing platform page has no Vaadin application id",
                "it changed; update primarysource.iso.webstore.obp",
            )
        details = urllib.parse.urlencode(
            {
                "v-browserDetails": "1",
                "theme": theme[1] if theme else "iso-red",
                "v-appId": app[1],
                "v-sh": "1080",
                "v-sw": "1920",
                "v-cw": "1280",
                "v-ch": "800",
                "v-curdate": int(self._now() * 1000),
                "v-tzo": "0",
                "v-dstd": "0",
                "v-rtzo": "0",
                "v-dston": "false",
                "v-tzid": "UTC",
                "v-vw": "1280",
                "v-vh": "800",
                "v-loc": f"{UI_URL}#{fragment}",
                "v-wn": app[1] + "-0",
            }
        ).encode("ascii")
        response = self._session.request(
            "POST",
            f"{UI_URL}?v-{int(self._now() * 1000)}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=details,
            follow=False,
        )
        try:
            outer = json.loads(response.body)
            uidl = json.loads(outer["uidl"])
            self._ui_id = str(outer["v-uiId"])
            self._key = str(uidl["Vaadin-Security-Key"])
        except (ValueError, KeyError, TypeError) as exc:
            raise LibError("the browsing platform did not start a UI session", "sign in again, then retry") from exc
        self._ui = UiState()
        self._ui.apply(uidl)
        self._sync, self._client = int(uidl.get("syncId", 1)), int(uidl.get("clientId", 0))
        self.rpc([["0", "com.vaadin.shared.ui.ui.UIServerRpc", "resize", [1280, 800, 1280, 800]]])
        self.rpc([], resynchronize=True)

    def rpc(self, calls: list[list[Any]], *, resynchronize: bool = False) -> dict[str, Any]:
        if self._ui_id is None:
            raise LibError("no UI session", "call open() first")
        payload: dict[str, Any] = {
            "csrfToken": self._key,
            "rpc": calls,
            "syncId": self._sync,
            "clientId": self._client,
            "wsver": WSVER,
        }
        if resynchronize:
            payload["resynchronize"] = True
        response = self._session.request(
            "POST",
            f"{UIDL_URL}?v-uiId={self._ui_id}",
            headers={"Content-Type": "application/json; charset=UTF-8"},
            body=json.dumps(payload).encode("utf-8"),
            follow=False,
        )
        text = response.text().strip()
        if response.status != 200 or not text.startswith("for(;;);["):
            raise LibError(
                f"the browsing platform refused an RPC (HTTP {response.status})", "open() a new UI session"
            )
        try:
            uidl = json.loads(text[len("for(;;);") :])[0]
        except (ValueError, IndexError) as exc:
            raise LibError("the browsing platform's answer is not UIDL", "open() a new UI session") from exc
        self._client += 1
        self._sync = int(uidl.get("syncId", self._sync))
        self._ui.apply(uidl)
        return dict(uidl)

    def click(self, connector: str) -> dict[str, Any]:
        return self.rpc([[connector, "com.vaadin.shared.ui.button.ButtonServerRpc", "click", [dict(_MOUSE)]]])

    # --- what the owner holds ---

    def products(self) -> tuple[OwnedProduct, ...]:
        return parse_products(self._ui)

    def assign_licence(self, product: OwnedProduct, confirm: LicenceConfirmation | None = None) -> AssignResult:
        """Assign licence #1 of `product` to the signed-in user, the step the platform wants before it offers the PDF.

        Dry-run unless `confirm` names the same designation. The platform asks "are you sure" in a dialog; this
        presses its Ok. Without a button to press (the licence is already assigned) it raises instead of guessing."""
        if product.assign_button is None:
            raise LibError(
                f"{product.designation}: there is no assign-licence button", "the licence is already assigned"
            )
        if confirm is None:
            return AssignResult(False, product)
        if _text(confirm.designation) != product.designation:
            raise LibError(
                "the confirmation names a different product", "build it from the product's own designation"
            )
        before = max((int(cid) for cid in self._ui.state if cid.isdigit()), default=0)
        self.click(product.assign_button)
        ok = [
            cid
            for cid in self._ui.ids()
            if cid.isdigit()
            and int(cid) > before
            and self._ui.kind(cid) == "Button"
            and _text(self._ui.state[cid].get("caption")) == "Ok"
        ]
        if len(ok) != 1:
            raise LibError("the platform's confirmation dialog was not found", "assign the licence in a browser")
        self.click(ok[0])
        after = self.products()
        return AssignResult(True, product, after)

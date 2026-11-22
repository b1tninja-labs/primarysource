"""Signing in to the ISO webstore, as the browser does it.

What the capture shows (docs/iso-webstore.md section 3): the webstore and the Online Browsing Platform are both
server-side clients of one Keycloak realm. `GET /webstore/oauth2/authorization/iso` redirects to the realm's
authorization endpoint (`response_type=code`, a `state` and a `nonce`, no PKCE challenge); the realm shows a form
(`id="login"`, fields `username`, `password` and a hidden `credentialId`); it redirects back to the webstore with a
`code`; the webstore exchanges it server-side and sets its own session cookie. The client never holds a bearer
token: the session is a cookie in the transport.

Credentials come from `PRIMARYSOURCE_ISO_USERNAME` and `PRIMARYSOURCE_ISO_PASSWORD` and live in `Secret`s whose
text is redacted. `PRIMARYSOURCE_ISO_TOKEN_FILE` may name a file that caches the session cookies between runs; it
is a credential, so it is written with owner-only permissions, never inside a git work tree.
"""

from __future__ import annotations

import contextlib
import html
import json
import os
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import NoReturn

from primarysource.errors import LibError
from primarysource.fsutil import atomic_write
from primarysource.iso.webstore.graphql import CURRENT_DATA, GraphQLClient
from primarysource.iso.webstore.secret import Secret
from primarysource.iso.webstore.session import BASE, WebstoreSession

ENV_USERNAME = "PRIMARYSOURCE_ISO_USERNAME"
ENV_PASSWORD = "PRIMARYSOURCE_ISO_PASSWORD"  # noqa: S105 - the name of a variable, not a password
ENV_TOKEN_FILE = "PRIMARYSOURCE_ISO_TOKEN_FILE"  # noqa: S105 - the name of a variable, not a token
WEBSTORE_LOGIN = f"{BASE}/webstore/oauth2/authorization/iso"
OBP_LOGIN = f"{BASE}/obp/oauth2/authorization/iso"


@dataclass(frozen=True, slots=True)
class Credentials:
    username: Secret
    password: Secret

    def __repr__(self) -> str:
        return "Credentials(<redacted>)"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Credentials:
        env = os.environ if environ is None else environ
        missing = [name for name in (ENV_USERNAME, ENV_PASSWORD) if not (env.get(name) or "").strip()]
        if missing:
            raise LibError(
                f"no ISO credentials: {', '.join(missing)} not set",
                f"set {ENV_USERNAME} and {ENV_PASSWORD} in the environment of the process that runs this "
                "(never in a file in the repository)",
            )
        return cls(Secret(env[ENV_USERNAME].strip()), Secret(env[ENV_PASSWORD]))


# --- the session cache ------------------------------------------------------------------------------------------


def _inside_git_tree(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in (path.resolve(), *path.resolve().parents))


def ensure_outside_repo(path: Path, what: str) -> None:
    """Refuse a `path` inside a git work tree: a credential or a licensed file there is one `git add -A` from
    being committed."""
    if _inside_git_tree(path if path.is_dir() else path.parent):
        raise LibError(
            f"{what} would be written inside a git work tree ({path})",
            "choose a location outside every repository, e.g. under the collection home",
        )


@dataclass(frozen=True, slots=True)
class SessionCache:
    """Cached session cookies in one JSON file. The values are credentials; nothing here prints them."""

    path: Path

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SessionCache | None:
        env = os.environ if environ is None else environ
        value = (env.get(ENV_TOKEN_FILE) or "").strip()
        return cls(Path(value)) if value else None

    def load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise LibError(
                f"the session cache {self.path} is unreadable ({type(exc).__name__})", "delete it"
            ) from exc
        if not isinstance(data, dict):
            raise LibError(f"the session cache {self.path} is not a cookie map", "delete it")
        return {str(k): str(v) for k, v in data.items()}

    def save(self, cookies: Mapping[str, str]) -> None:
        ensure_outside_repo(self.path, "the session cache")
        atomic_write(self.path, json.dumps(dict(cookies)).encode("utf-8"))
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)  # best effort: a no-op for group/other on Windows


# --- the login form ---------------------------------------------------------------------------------------------


class _Form(HTMLParser):
    """The first `<form id="...">` with the given id: its action and its `<input>` name/value pairs."""

    def __init__(self, form_id: str) -> None:
        super().__init__()
        self._want = form_id
        self._inside = False
        self.action: str | None = None
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k: v or "" for k, v in attrs}
        if tag == "form" and values.get("id") == self._want and self.action is None:
            self._inside = True
            self.action = html.unescape(values.get("action", ""))
        elif tag == "input" and self._inside and values.get("name"):
            self.fields[values["name"]] = html.unescape(values.get("value", ""))

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._inside = False


def parse_login_form(page: str) -> tuple[str, dict[str, str]] | None:
    """(action, fields) of the sign-in form, or None if the page has none."""
    parser = _Form("login")
    parser.feed(page)
    return (parser.action, parser.fields) if parser.action else None


def _fail(message: str, hint: str) -> NoReturn:
    raise LibError(message, hint)


def login(session: WebstoreSession, credentials: Credentials, *, start: str = WEBSTORE_LOGIN) -> None:
    """Sign in. On return the transport holds the session cookie of the client `start` names.

    Raises `LibError` when the form is missing (the realm changed, or a challenge is in the way), when the realm
    shows the sign-in form again (wrong credentials or a captcha) and when it asks for a required action (terms to
    accept, a password to update, a second factor): those are for a person in a browser.
    """
    page = session.request("GET", start)
    host = urllib.parse.urlsplit(page.url).hostname
    if host == "www.iso.org":
        return  # the realm already knows this session and sent the browser straight back
    form = parse_login_form(page.text())
    if form is None:
        _fail(
            "the ISO sign-in page has no login form",
            "the realm may have changed or asks for a challenge; sign in once in a browser, then retry",
        )
    action, fields = form
    body = urllib.parse.urlencode(
        {**fields, "username": credentials.username.reveal(), "password": credentials.password.reveal()}
    ).encode("ascii")
    result = session.request(
        "POST",
        urllib.parse.urljoin(page.url, action),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": page.url},
        body=body,
    )
    if urllib.parse.urlsplit(result.url).hostname == "www.iso.org":
        return
    text = result.text()
    if parse_login_form(text) is not None:
        _fail(
            "ISO refused the sign-in (wrong credentials, or a captcha)",
            "check the two variables; sign in in a browser once",
        )
    _fail(
        "ISO asks for something before it will sign in (terms to accept, a password to change, or a second factor)",
        "complete that in a browser with this account, then retry",
    )


@dataclass(frozen=True, slots=True)
class WhoAmI:
    """What `currentData` says about the session. The user name and display name are deliberately not kept."""

    signed_in: bool
    roles: tuple[str, ...] = ()
    preferred_language: str | None = None
    has_credentials: bool = False


def who_am_i(graphql: GraphQLClient) -> WhoAmI:
    data = graphql.execute("currentData", CURRENT_DATA)
    user = data.get("currentUser")
    if not isinstance(user, dict):
        return WhoAmI(False)
    roles = user.get("roles") or ()
    return WhoAmI(
        True,
        tuple(str(role) for role in roles),
        user.get("preferredLanguage"),
        bool(user.get("hasCredentials")),
    )


def sign_in(
    session: WebstoreSession,
    graphql: GraphQLClient,
    credentials: Credentials | None = None,
    cache: SessionCache | None = None,
) -> WhoAmI:
    """A signed-in session: cached cookies first (checked with `currentData`), else a form login, then cached."""
    if cache is not None:
        cached = cache.load()
        if cached:
            session.transport.set_cookies(cached)
            state = who_am_i(graphql)
            if state.signed_in:
                return state
    login(session, credentials or Credentials.from_env())
    state = who_am_i(graphql)
    if not state.signed_in:
        _fail(
            "the sign-in finished but the webstore does not see a user", "retry; if it persists, sign in in a browser"
        )
    if cache is not None:
        cache.save(session.transport.cookies())
    return state

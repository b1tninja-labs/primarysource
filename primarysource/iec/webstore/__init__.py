"""A client for the IEC webstore (https://webstore.iec.ch): search, catalogue metadata, the owner's own downloads.

Read docs/iec-webstore.md first. In short: search and catalogue reads go to the store's public search API; the
owner's licences and downloads need the owner's login from the environment; every state-changing call is a dry run
unless given an explicit `Confirmation`; and nothing here reads a standard's text from an online reader or crawls
the store. Stdlib only; every client takes a `Transport`, and the tests use a fake one.
"""

from __future__ import annotations

from primarysource.iec.webstore._secret import Credentials, Secret
from primarysource.iec.webstore.cart import (
    BillingAddress,
    Confirmation,
    ItemChoice,
    OrderResult,
    Plan,
    Shop,
)
from primarysource.iec.webstore.catalog import filter_catalog, find, rebuild_index, sync_catalog, write_stubs
from primarysource.iec.webstore.models import Publication, SearchPage
from primarysource.iec.webstore.orders import DownloadResult, OrderClient
from primarysource.iec.webstore.search import SearchClient, SearchQuery
from primarysource.iec.webstore.session import IecSession
from primarysource.iec.webstore.transport import HttpRequest, HttpResponse, PoliteTransport, Transport

__all__ = [
    "BillingAddress",
    "Confirmation",
    "Credentials",
    "DownloadResult",
    "HttpRequest",
    "HttpResponse",
    "IecSession",
    "ItemChoice",
    "OrderClient",
    "OrderResult",
    "Plan",
    "PoliteTransport",
    "Publication",
    "SearchClient",
    "SearchPage",
    "SearchQuery",
    "Secret",
    "Shop",
    "Transport",
    "filter_catalog",
    "find",
    "rebuild_index",
    "sync_catalog",
    "write_stubs",
]

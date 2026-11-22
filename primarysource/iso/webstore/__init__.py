"""A client SDK for the ISO webstore (https://www.iso.org), built from the owner's own browser capture.

It searches the public catalog, reads what the owner is licensed for, downloads what the owner holds, and, only
when explicitly confirmed, places a free order. It never reads a standard's text through the Online Browsing
Platform. `docs/iso-webstore.md` is the description of the API as observed, the terms caution and every open
question. Nothing here runs at import time and nothing touches the network except through `WebstoreSession`.
"""

from __future__ import annotations

from primarysource.iso.webstore.auth import Credentials, SessionCache, WhoAmI, login, sign_in, who_am_i
from primarysource.iso.webstore.basket import (
    AddConfirmation,
    Basket,
    FreeOrderConfirmation,
    FreeOrderResult,
    free_order_problems,
)
from primarysource.iso.webstore.catalog import CatalogFilter, CatalogStore
from primarysource.iso.webstore.download import Downloaded, download_owned
from primarysource.iso.webstore.graphql import GraphQLClient
from primarysource.iso.webstore.models import CatalogEntry, Order, OrderSummary, Price, ProductCode
from primarysource.iso.webstore.obp import LicenceConfirmation, ObpSession, OwnedProduct
from primarysource.iso.webstore.search import CatalogSearch, SearchConfig
from primarysource.iso.webstore.secret import Secret
from primarysource.iso.webstore.session import WebstoreSession
from primarysource.iso.webstore.sync import SyncReport, sync_catalog
from primarysource.iso.webstore.transport import HttpRequest, HttpResponse, Transport, UrllibTransport

__all__ = [
    "AddConfirmation",
    "Basket",
    "CatalogEntry",
    "CatalogFilter",
    "CatalogSearch",
    "CatalogStore",
    "Credentials",
    "Downloaded",
    "FreeOrderConfirmation",
    "FreeOrderResult",
    "GraphQLClient",
    "HttpRequest",
    "HttpResponse",
    "LicenceConfirmation",
    "ObpSession",
    "Order",
    "OrderSummary",
    "OwnedProduct",
    "Price",
    "ProductCode",
    "SearchConfig",
    "Secret",
    "SessionCache",
    "SyncReport",
    "Transport",
    "UrllibTransport",
    "WebstoreSession",
    "WhoAmI",
    "download_owned",
    "free_order_problems",
    "login",
    "sign_in",
    "sync_catalog",
    "who_am_i",
]

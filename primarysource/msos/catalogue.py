"""The Open Specifications document sets named by [MS-OPENSPECLP].

Each set is one PDF zip linked from the set's own page on learn.microsoft.com. The link is read from that page
at sync time; the page is the stable address and the zip URL behind it moves.
"""

from __future__ import annotations

from dataclasses import dataclass

PROTOCOLS = (
    "https://learn.microsoft.com/en-us/openspecs/protocols/ms-protocolslp/9a3ae8a2-02e5-4d05-874a-b3551405d8f9"
)
WINDOWS = (
    "https://learn.microsoft.com/en-us/openspecs/windows_protocols/MS-WINPROTLP/92b33e19-6fff-496b-86c3-d168206f9845"
)
STANDARDS = (
    "https://learn.microsoft.com/en-us/openspecs/standards_support/MS-STDSUPLP/17a32be7-10b3-4025-bea4-133a66b4c689"
)
LANGUAGES = (
    "https://learn.microsoft.com/en-us/openspecs/computer_languages/ms-complanlp/63bd758c-9134-4ea3-9a74-566b27e92046"
)
PORTABILITY = (
    "https://learn.microsoft.com/en-us/openspecs/data_portability/ms-dataportlp/a2bc1311-e0e7-4808-970a-4dc0a100f708"
)


@dataclass(frozen=True, slots=True)
class SpecSet:
    """One zip of published PDFs."""

    id: str
    family: str
    label: str
    page: str
    # Used when the page's fwlink no longer resolves to a zip. Empty for a link that still does.
    direct: str = ""


SETS: tuple[SpecSet, ...] = (
    SpecSet("windows", "protocols", "Windows Protocols", WINDOWS),
    SpecSet("exchange", "protocols", "Exchange Server Protocols", PROTOCOLS),
    SpecSet("office", "protocols", "Microsoft Office Protocols", PROTOCOLS),
    SpecSet("sharepoint", "protocols", "SharePoint Products and Technologies Protocols", PROTOCOLS),
    # LinkId=120223 on the protocols page now redirects to Bing. The current specification pages
    # publish SQLServerProtocols.zip; this is that file after the CDN redirect.
    SpecSet(
        "sql",
        "protocols",
        "Microsoft SQL Server Protocols",
        PROTOCOLS,
        "https://sqlprotocoldoc.z19.web.core.windows.net/SQLServerProtocols.zip",
    ),
    SpecSet("exchange-standards", "standards", "Exchange Server and Outlook Standards", STANDARDS),
    SpecSet("ie", "standards", "Internet Explorer Standards", STANDARDS),
    SpecSet("odata", "standards", "OData Standards", STANDARDS),
    SpecSet("sql-standards", "standards", "SQL Server Standards Support", STANDARDS),
    SpecSet("wordpad", "standards", "Windows WordPad", STANDARDS),
    SpecSet("office-standards", "standards", "Word, Excel, and PowerPoint Standards", STANDARDS),
    SpecSet("languages", "languages", "General Purpose Programming Languages", LANGUAGES),
    SpecSet("dsl", "languages", "Domain-Specific Languages", LANGUAGES),
    SpecSet("office-formats", "portability", "Office File Formats", PORTABILITY),
    SpecSet("sql-portability", "portability", "SQL Server Data Portability", PORTABILITY),
)


def by_id(set_id: str) -> SpecSet:
    from primarysource.errors import LibError

    for item in SETS:
        if item.id == set_id:
            return item
    known = ", ".join(item.id for item in SETS)
    raise LibError(f"unknown Open Specifications set {set_id!r}", f"known sets: {known}")

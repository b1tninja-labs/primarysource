"""A Kiwix library (ZIM files) as a primarysource collection. Importing this needs nothing beyond the core: the
native `libzim` binding is imported only when a ZIM is opened (`_libzim.load`)."""

from __future__ import annotations

from primarysource.errors import LibError
from primarysource.model import Unit
from primarysource.refs import Ref
from primarysource.registry import Collection

from . import refs
from .errors import ZimloreError


class ZimRefs:
    """zimlore's refs (`devdocs_en_flask§blueprints/index#why-blueprints¶3`) as the core's `Ref`: the library is the
    `doc`, the entry path the `section`. A path is a slash-separated URL path, not a dotted number, so the core's
    `RefGrammar` cannot read it; `refs.parse_ref` can."""

    @staticmethod
    def parse(text: str) -> Ref:
        try:
            parsed = refs.parse_ref(text)
        except ZimloreError as exc:
            raise LibError(exc.message, exc.hint) from exc
        return Ref(parsed.book, parsed.path or None, parsed.para, parsed.anchor or None)

    @staticmethod
    def format(ref: Ref) -> str:
        return refs.format_ref(ref.doc or "", ref.section or "", ref.anchor or "", ref.para)


COLLECTION = Collection(
    name="zim",
    title="Kiwix libraries (ZIM files): DevDocs, Stack Exchange, language and tool documentation",
    prefix="zim_",
    unit=Unit.BLOCK,
    grammar=ZimRefs(),
    server="primarysource.zim.mcp:build",
    cli="primarysource.zim.cli:main",
)

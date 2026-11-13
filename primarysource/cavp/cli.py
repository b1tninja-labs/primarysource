"""`primarysource cavp ...`: the collection's own commands.

primarysource cavp fetch [id ...]                         download the pinned sources in vectors.toml, import them
primarysource cavp import <id> <file> [<expected-file>]   import files you already have, under the same pins
primarysource cavp pin <file>                             print the sha256 to pin
primarysource cavp sets [query]
primarysource cavp groups <set-ref>
primarysource cavp read <ref> [--max-tokens N]
primarysource cavp find <set-ref> <field> <value> [--group G]
primarysource cavp cite <ref>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from primarysource.cavp import importer, tools
from primarysource.cavp.model import sha256_bytes
from primarysource.cavp.paths import open_store
from primarysource.errors import LibError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource cavp", description="NIST CAVP/ACVP test vectors")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", help="download and import the pinned sources").add_argument("ids", nargs="*")
    imp = sub.add_parser("import", help="import local files under a vectors.toml pin")
    imp.add_argument("id")
    imp.add_argument("file", type=Path)
    imp.add_argument("expected", type=Path, nargs="?")
    sub.add_parser("pin", help="print a file's sha256").add_argument("file", type=Path)
    sub.add_parser("sets").add_argument("query", nargs="?")
    sub.add_parser("groups").add_argument("ref")
    read = sub.add_parser("read")
    read.add_argument("ref")
    read.add_argument("--max-tokens", type=int, default=2000)
    find = sub.add_parser("find")
    find.add_argument("ref")
    find.add_argument("field")
    find.add_argument("value")
    find.add_argument("--group")
    sub.add_parser("cite").add_argument("ref")
    return parser


def _say(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    store = open_store()
    try:
        if args.command == "pin":
            return _say(sha256_bytes(args.file.read_bytes()))
        if args.command in ("fetch", "import"):
            known = {s.id: s for s in importer.load_sources()}
            wanted = args.ids if args.command == "fetch" else [args.id]
            unknown = [i for i in wanted if i not in known]
            if unknown:
                raise LibError(f"not in vectors.toml: {', '.join(unknown)}", f"known: {', '.join(known)}")
            for source in (known[i] for i in (wanted or list(known))):
                if args.command == "fetch":
                    entry = importer.fetch(store, source)
                else:
                    entry = importer.import_files(store, source, args.file, args.expected)
                print(f"{entry.id}: {entry.groups} groups, {entry.cases} cases, sha256 {entry.sha256}")
            return 0
        if args.command == "sets":
            return _say(tools.sets(store, args.query))
        if args.command == "groups":
            return _say(tools.groups(store, args.ref))
        if args.command == "read":
            return _say(tools.read(store, args.ref, args.max_tokens))
        if args.command == "find":
            return _say(tools.find(store, args.ref, args.field, args.value, args.group))
        return _say(tools.cite(store, args.ref))
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1

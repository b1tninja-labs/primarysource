"""Retrieval quality over real ZIMs: does a question land on the page that answers it?

Not part of the test suite (it needs downloaded ZIMs, and the suite must run without any) and not shipped in the
sdist. Run it after changing search, ranking or the converter:

    zimlore get devdocs_en_flask ; zimlore get devdocs_en_python
    python scripts/eval_retrieval.py            # summary and misses
    python scripts/eval_retrieval.py --verbose  # every query with its top hits

**How the cases were written.** Each question is a paraphrase of a page *title* taken from a listing of the two
ZIMs' entry titles (devdocs_en_flask 2026-10-01, devdocs_en_python 2026-10-31), written **before any search was
run against them**: the query avoids the title's own words where a natural paraphrase exists, and the expected
page is the one the title names. No expectation was adjusted after seeing a result; `git log` on this file shows
the cases committed before the first run. A result is correct when it IS an accepted path. Two cases accept two
paths because the titles name two pages that both plausibly answer the question; that choice was made up front.

Metrics: hit@1, hit@5 and mean reciprocal rank over the top 5. Two systems are compared on the same cases: the
shipped search (title suggestions + full-text) and a baseline that only uses the ZIM's title-suggestion index,
which is all a `_ftindex:no` ZIM would give. The cases are few and drawn from titles, so the numbers say
whether search is broken, not how good it is on questions people actually ask.
"""

from __future__ import annotations

import argparse
import sys

from zimlore import library, service
from zimlore.errors import ZimloreError

FLASK = "devdocs_en_flask"
PYTHON = "devdocs_en_python"
RUST = "devdocs_en_rust"
GO = "devdocs_en_go"
NODE = "devdocs_en_node"
PHP = "devdocs_en_php"

# (library, question, accepted entry paths)
CASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (FLASK, "serve a single page javascript app from flask", ("patterns/singlepageapplications/index",)),
    (FLASK, "make flask trust the forwarded headers of a reverse proxy", ("deploying/proxy_fix/index",)),
    (FLASK, "accept files uploaded through a form", ("patterns/fileuploads/index",)),
    (FLASK, "create the app object inside a function", ("patterns/appfactories/index",)),
    (FLASK, "show a one-time message on the next request", ("patterns/flashing/index",)),
    (FLASK, "write automated tests for a flask application", ("testing/index",)),
    (FLASK, "run slow jobs in the background with a task queue", ("patterns/celery/index",)),
    (FLASK, "use a sqlite database from a view", ("patterns/sqlite3/index",)),
    (FLASK, "views implemented as classes", ("views/index",)),
    (FLASK, "what happens from the start of a request to its end", ("lifecycle/index", "reqcontext/index")),
    (FLASK, "inspect errors with the interactive debugger", ("debugging/index",)),
    (FLASK, "production server with worker processes", ("deploying/gunicorn/index", "deploying/index")),
    (FLASK, "cross-site scripting and other attacks to guard against", ("web-security/index",)),
    (FLASK, "coroutines in view functions", ("async-await/index",)),
    (FLASK, "send a large response piece by piece", ("patterns/streaming/index",)),
    (PYTHON, "write a command line interface that parses arguments", ("howto/argparse",)),
    (PYTHON, "encode and decode text, code points and bytes", ("howto/unicode",)),
    (PYTHON, "time zones from the IANA database", ("library/zoneinfo",)),
    (PYTHON, "read and write comma separated values", ("library/csv",)),
    (PYTHON, "measure how long a small piece of code takes", ("library/timeit",)),
    (PYTHON, "split a string the way a unix shell would", ("library/shlex",)),
    (PYTHON, "efficient looping building blocks for iterators", ("library/itertools",)),
    (PYTHON, "attach a debugger to a process that is already running", ("howto/remote_debugging",)),
    (PYTHON, "isolated environment for project packages", ("tutorial/venv",)),
    (PYTHON, "first-in first-out and last-in first-out containers", ("library/queue",)),
    (PYTHON, "parse an XML document into a tree", ("library/xml.etree.elementtree",)),
    (PYTHON, "keyed hash message authentication", ("library/hmac",)),
    (PYTHON, "how attribute lookup uses __get__ and __set__", ("howto/descriptor",)),
    (PYTHON, "framework for writing and running test cases", ("library/unittest",)),
    (PYTHON, "order in which base classes are searched", ("howto/mro",)),
    (PYTHON, "add and subtract dates and times", ("library/datetime",)),
    (PYTHON, "filesystem paths as objects", ("library/pathlib",)),
    (PYTHON, "find out where a program spends its time", ("library/pstats", "library/profile")),
    (PYTHON, "run the interpreter inside a larger C program", ("extending/embedding",)),
)

# Second batch, added 2026-11-07 after the first: Rust, Go, Node and PHP (DevDocs, editions 2026-10-01, 2026-10-02,
# 2026-08-02, 2026-08-18). Written from a title listing of each ZIM before any search was run against it, and
# committed before the first run. Reported separately so the first batch stays comparable across versions.
EXTRA_CASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (RUST, "store values under keys in a map", ("book/ch08-03-hash-maps", "std/collections/hash_map/struct.hashmap")),
    (RUST, "share mutable state between threads with a lock", ("book/ch16-03-shared-state",)),
    (RUST, "when the compiler lets you leave out lifetime annotations", ("reference/lifetime-elision",)),
    (RUST, "get the name of a type as a string", ("std/intrinsics/fn.type_name",)),
    (RUST, "create a directory along with its missing parents", ("std/fs/fn.create_dir_all",)),
    (RUST, "borrowed data that is copied only when modified", ("std/borrow/enum.cow",)),
    (RUST, "iterator adapter that carries state between items", ("std/iter/struct.scan",)),
    (RUST, "range that includes its end value", ("std/range/struct.rangeinclusive", "std/ops/struct.rangeinclusive")),
    (RUST, "delete a process environment variable", ("std/env/fn.remove_var",)),
    (RUST, "iterate over valid pieces of bytes that may contain invalid utf-8", ("std/str/struct.utf8chunks",)),
    (GO, "encode and decode json documents", ("encoding/json/index",)),
    (GO, "priority queue built on a heap interface", ("container/heap/index",)),
    (GO, "define and parse command line options", ("flag/index",)),
    (GO, "test an http handler without opening a socket", ("net/http/httptest/index",)),
    (GO, "compute a sha-256 digest", ("crypto/sha256/index",)),
    (GO, "read and write comma separated records", ("encoding/csv/index",)),
    (GO, "arbitrary precision integers and rationals", ("math/big/index",)),
    (GO, "wrap an error and check what it wraps", ("errors/index",)),
    (GO, "bundle static files into the executable", ("embed/index",)),
    (GO, "turn source text into a syntax tree", ("go/parser/index", "go/ast/index")),
    (NODE, "launch another program and read its output", ("child_process",)),
    (NODE, "join and normalize file system paths", ("path",)),
    (NODE, "objects that emit named events to listeners", ("events",)),
    (NODE, "parse and build web addresses", ("url",)),
    (NODE, "write tests without a third party framework", ("test",)),
    (NODE, "run javascript on parallel threads", ("worker_threads",)),
    (NODE, "gzip and deflate compression", ("zlib",)),
    (NODE, "schedule a callback after a delay", ("timers",)),
    (NODE, "read a stream one line at a time", ("readline",)),
    (PHP, "compare two version numbers", ("function.version-compare",)),
    (PHP, "split a url into scheme host and path", ("function.parse-url",)),
    (PHP, "calculate the md5 hash of a string", ("function.md5",)),
    (PHP, "when was a file's inode last changed", ("function.filectime",)),
    (PHP, "the value a finished coroutine returned", ("fiber.getreturn",)),
    (PHP, "stop a process started with proc_open", ("function.proc-terminate",)),
    (PHP, "compare strings using the current locale", ("function.strcoll",)),
    (PHP, "iterator that stops after a number of elements", ("limititerator.construct",)),
    (PHP, "choose the indentation of generated xml", ("xmlwriter.setindent",)),
    (PHP, "absolute path of a file described by an info object", ("splfileinfo.getrealpath",)),
)

# Cases with no library given: the right library has to be chosen too.
UNSCOPED: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (FLASK, "create the app object inside a function", ("patterns/appfactories/index",)),
    (PYTHON, "write a command line interface that parses arguments", ("howto/argparse",)),
    (FLASK, "accept files uploaded through a form", ("patterns/fileuploads/index",)),
    (PYTHON, "time zones from the IANA database", ("library/zoneinfo",)),
)


def shipped(name: str, question: str) -> list[str]:
    result = service.search(question, name, limit=5, max_tokens=100_000)
    return [h["ref"].split("§", 1)[1] for h in result["hits"] if h["ref"].startswith(library.find(name).name + "§")]


def titles_only(name: str, question: str) -> list[str]:
    book = library.find(name)
    return [path for path, _ in service._suggest(book, question, 5)]


def shipped_all(_name: str, question: str) -> list[str]:
    result = service.search(question, "", limit=5, max_tokens=100_000)
    return [h["ref"] for h in result["hits"]]


def score(
    cases: tuple[tuple[str, str, tuple[str, ...]], ...], run: object, verbose: bool, with_library: bool = False
) -> tuple[int, int, float, list[str]]:
    hit1 = hit5 = 0
    reciprocal = 0.0
    misses: list[str] = []
    for name, question, accepted in cases:
        found: list[str] = run(name, question)  # type: ignore[operator]
        wanted = {f"{name}§{p}" for p in accepted} if with_library else set(accepted)
        rank = next((i for i, path in enumerate(found, 1) if path in wanted), 0)
        hit1 += rank == 1
        hit5 += rank >= 1
        reciprocal += 1 / rank if rank else 0
        if verbose:
            print(f"  [{rank or '-'}] {question!r} -> {found}")
        if rank != 1:
            misses.append(f"{question!r}: wanted {sorted(wanted)}, rank {rank or 'none'}, got {found[:3]}")
    return hit1, hit5, reciprocal / len(cases), misses


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    try:
        library.find(FLASK)
        library.find(PYTHON)
    except ZimloreError as error:
        print(f"{error.message}\nfix: zimlore get {FLASK} ; zimlore get {PYTHON}", file=sys.stderr)
        return 2
    extra_ready = True
    for name in (RUST, GO, NODE, PHP):
        try:
            library.find(name)
        except ZimloreError:
            extra_ready = False
            print(f"(second batch skipped: {name} is not installed; zimlore get {name})", file=sys.stderr)
    editions = ", ".join(f"{b.name} {b.date}" for b in (library.find(FLASK), library.find(PYTHON)))
    print(f"editions: {editions}")
    total = len(CASES)
    for label, run, cases, with_library in (
        ("shipped search, scoped to the library", shipped, CASES, False),
        ("baseline: title suggestions only", titles_only, CASES, False),
        ("shipped search, no library given", shipped_all, UNSCOPED, True),
        *(
            (("second batch (Rust, Go, Node, PHP), shipped search", shipped, EXTRA_CASES, False),)
            if extra_ready
            else ()
        ),
        *(
            (("second batch, baseline: title suggestions only", titles_only, EXTRA_CASES, False),)
            if extra_ready
            else ()
        ),
    ):
        h1, h5, mrr, misses = score(cases, run, args.verbose, with_library)
        count = len(cases)
        print(f"{label}: {count} cases, hit@1 {h1}/{count}, hit@5 {h5}/{count}, MRR {mrr:.3f}")
        for miss in misses:
            print(f"    miss: {miss}")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())

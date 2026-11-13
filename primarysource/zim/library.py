"""The local library: which ZIM files are installed, what they are, and which one a name means.

The home directory is the collection's home (`home.collection_home("zim", "zimlore")`): `$ZIMLORE_HOME`, then
`$PRIMARYSOURCE_ZIM_HOME`, then `$PRIMARYSOURCE_HOME/zim`, then an existing `~/.zimlore`, then the per-user
default. The ZIM files live in its `zim/` subdirectory. `PRIMARYSOURCE_ZIM_PATH` (legacy: `ZIMLORE_ZIM_PATH`; a
list separated by the platform's path separator) replaces that subdirectory, so an existing Kiwix library can be
used where it already is instead of copied. Nothing in this module writes to the
repository, and the repository's `.gitignore` names every way a ZIM could be spelled.

A ZIM identifies itself by its `Name` metadata (`devdocs_en_flask`), not by its file name, and carries a `Date`.
Two ZIMs with one `Name` and different dates are two *editions* of one library; resolution picks the newest and
reports the others rather than choosing silently.

Producers that build documentation per package version name each build differently (`golang_..._cobra_v1.8.1`),
so a version is NOT an edition: those are separate Names. They share a *family* (the Name without its trailing
version token, or the `purl:` tag without its version) and carry a `version`. A query naming a family resolves to
its newest version by `version_key` order; a query naming a version selects that one (`select`).
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Any, NamedTuple

from primarysource import home as _homes

from . import _libzim, purl
from .errors import LibraryNotFound, ZimloreError

HOME_ENV = "ZIMLORE_HOME"
"""The setting from before the move into primarysource; it still wins (`home.collection_home`)."""
PATH_ENV = "PRIMARYSOURCE_ZIM_PATH"
LEGACY_PATH_ENV = "ZIMLORE_ZIM_PATH"
STALE_DAYS = 365
"""A ZIM older than this is reported `stale`. The number is a convention, not a measurement: the response always
carries the date and the age in days so a caller can apply its own threshold."""

_DATE_SUFFIX = re.compile(r"_\d{4}-\d{2}$")
_VERSION_TOKEN = re.compile(
    r"^(?P<family>.*[A-Za-z].*?)_(?P<version>[vV]?\d+(?:\.[0-9A-Za-z]+)*(?:-[0-9A-Za-z.]+)?)$"
)
_BARE_YEAR = re.compile(r"^(19|20)\d\d$")
_DATE_TEXT = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?![0-9])")


def parse_date(text: str) -> dt.date | None:
    """A ZIM `Date` (or a catalogue date) as a calendar date, or None when it is not one. `2026-9-15` is read as
    September 15th, a trailing time is ignored, and nothing else is guessed: free text is never compared as a
    string, because `"2026-9-15" > "2026-10-01"` and `"" < everything` would reorder editions."""
    match = _DATE_TEXT.match(text.strip())
    if match is None:
        return None
    try:
        return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def date_key(text: str) -> dt.date:
    """A sort key for display and 'which is newest' choices: undated sorts oldest. Nothing is ever DELETED on the
    strength of this; `manage.prune` refuses a group with an unparseable date instead."""
    return parse_date(text) or dt.date.min


def is_newer(candidate: str, installed: str) -> bool | None:
    """Is `candidate` a later date than `installed`? None when either is not a date: unknown is not 'no'."""
    a, b = parse_date(candidate), parse_date(installed)
    return None if a is None or b is None else a > b


def split_name(name: str) -> tuple[str, str | None]:
    """A ZIM `Name` as (family, version): the trailing `_v?<digits>(.<alnum>)*(-<alnum>)?` token is the version and
    the rest is the family; None when the Name ends in no such token. A `_YYYY-MM` date suffix is an edition
    marker and is dropped first (it is not a version); a bare four-digit year and a bare integer of more than two
    digits (`wikipedia_en_100`) are not versions either, because a count or a year in a name is not a release."""
    base = _DATE_SUFFIX.sub("", name)
    match = _VERSION_TOKEN.match(base)
    if match:
        version = match.group("version")
        bare = version.isdigit()
        if not (bare and (_BARE_YEAR.match(version) or len(version) > 2)):
            return match.group("family"), version
    return base, None


_PRE = {"dev": -4, "a": -3, "alpha": -3, "b": -2, "beta": -2, "c": -1, "rc": -1, "pre": -1, "preview": -1}
_POST = {"post": 1, "p": 1, "patch": 1, "sp": 1, "rev": 1, "r": 1}
_FINAL = {"final", "release", "ga", "stable"}


def _version_parts(text: str) -> tuple[list[int], list[str]]:
    """(leading numeric release components, the tokens after them) of a version, case-folded, without a `v` prefix
    and without `+build` metadata."""
    folded = re.sub(r"^v(?=\d)", "", text.strip().lower()).split("+", 1)[0]
    tokens = re.findall(r"\d+|[a-z]+", folded)
    release: list[int] = []
    while tokens and tokens[0].isdigit():
        release.append(int(tokens.pop(0)))
    return release, tokens


def version_key(text: str) -> tuple[int, tuple[int, ...], int, tuple[int, ...], str]:
    """A sort key for version strings, tolerant of what package ecosystems write. Numeric components compare as
    numbers (`1.10` > `1.8`), a `v` prefix and trailing zeros do not matter (`v1.0` == `1.0.0`), a pre-release
    (`dev` < `a`/`alpha` < `b`/`beta` < `rc`) sorts below its release and a post-release above it, an unknown
    suffix (`1.2.x`) sorts with the pre-releases, and a version with no number at all (`latest`, `main`) sorts
    below every numbered one: 'newest' never prefers it."""
    release, rest = _version_parts(text)
    numbered = bool(release)  # before trimming: `0.0` has a number even though its release trims to nothing
    while release and release[-1] == 0:
        release.pop()
    word = rest[0] if rest and not rest[0].isdigit() else ""
    known = not word or word in _PRE or word in _POST or word in _FINAL
    phase = 0 if not word or word in _FINAL else _PRE.get(word, _POST.get(word, -1))
    numbers = tuple(int(t) for t in rest[1:] if t.isdigit()) if word else tuple(int(t) for t in rest if t.isdigit())
    return (1 if numbered else 0, tuple(release), phase, numbers, "" if known and release else text.strip().lower())


def same_version(a: str, b: str) -> bool:
    """The same version as written, ignoring case, a `v` prefix and build metadata. `3.1` is NOT `3.1.0` here
    (they sort alike, but asking for `3.1` means 'the 3.1 line', which `version_prefix` answers)."""
    return _version_parts(a) == _version_parts(b)


def version_prefix(requested: str, candidate: str) -> bool:
    """Does `candidate` start with `requested`, component by component? `3.1` matches `3.1.4` and not `3.10.0`. A
    requested version carrying a pre-release or other suffix has no prefix reading, only an exact one."""
    wanted, suffix = _version_parts(requested)
    have, _ = _version_parts(candidate)
    return bool(wanted) and not suffix and have[: len(wanted)] == wanted


def home() -> Path:
    """Where the library lives. An explicit setting wins; without one an existing `~/.zimlore` is found instead of
    an empty library being started beside it."""
    explicit = any(os.environ.get(name) for name in (HOME_ENV, "PRIMARYSOURCE_ZIM_HOME", "PRIMARYSOURCE_HOME"))
    old = Path.home() / ".zimlore"
    if not explicit and old.is_dir():
        return old
    return _homes.collection_home("zim", "zimlore").expanduser()


def zim_dirs() -> list[Path]:
    override = os.environ.get(PATH_ENV) or os.environ.get(LEGACY_PATH_ENV)
    if override:
        return [Path(part).expanduser() for part in override.split(os.pathsep) if part]
    return [home() / "zim"]


def norm(text: str) -> str:
    """Lower-case words separated by single spaces: `Flask Docs`, `devdocs_en_flask` and `devdocs/flask` all
    become comparable token strings."""
    return " ".join(re.split(r"[^0-9a-z+#]+", text.lower())).strip()


@dataclass(frozen=True)
class Book:
    name: str
    title: str
    date: str  # ISO YYYY-MM-DD from the Date metadata, "" when the ZIM has none
    language: str
    creator: str
    publisher: str
    description: str
    tags: tuple[str, ...]
    license: str  # the License metadata, "" when the ZIM does not state one
    source: str
    path: Path
    uuid: str
    articles: int
    size: int
    has_fulltext: bool
    has_titles: bool
    scraper: str = ""

    @property
    def when(self) -> dt.date | None:
        return parse_date(self.date)

    @cached_property
    def package(self) -> purl.Purl | None:
        """The package this ZIM documents, from a `purl:pkg:...` tag (set by the producer), else None. A tag that
        is not a usable purl is ignored: a scan must not fail on someone else's metadata."""
        for tag in self.tags:
            if tag[:5].lower() == "purl:":
                try:
                    return purl.parse(tag[5:])
                except ZimloreError:
                    continue
        return None

    @cached_property
    def family(self) -> str:
        """What versions of one package share: the purl without its version when the ZIM carries one, else the
        Name without its trailing version token (`golang_github.com_spf13_cobra_v1.8.1` ->
        `golang_github.com_spf13_cobra`). A Name with no version token is its own family."""
        return self.package.text if self.package else split_name(self.name)[0]

    @cached_property
    def version(self) -> str | None:
        """The upstream version this ZIM documents, from the purl tag or the Name's version token; None when the
        ZIM does not say (a DevDocs ZIM records a date, not a release)."""
        return (self.package.version if self.package else None) or split_name(self.name)[1]

    def age_days(self, today: dt.date | None = None) -> int | None:
        when = self.when
        if when is None:
            return None
        return ((today or datetime.now(UTC).date()) - when).days

    def freshness(self, today: dt.date | None = None) -> dict[str, object]:
        """Staleness as data: the date, the age, and whether it passes STALE_DAYS. `unknown` when the ZIM
        carries no usable Date, which is not the same as fresh."""
        age = self.age_days(today)
        return {
            "date": self.date or None,
            "age_days": age,
            "stale": None if age is None else age > STALE_DAYS,
            "stale_after_days": STALE_DAYS,
        }

    def aliases(self, user: dict[str, str] | None = None) -> set[str]:
        found = name_aliases(self.name, self.title, self.version)
        if self.package:
            found.update(
                {norm(self.package.name), norm(self.package.words), norm(f"{self.package.type} {self.package.name}")}
            )
        if user:
            found.update(norm(alias) for alias, target in user.items() if target in {self.name, self.title})
        found.discard("")
        return found


def name_aliases(name: str, title: str, version: str | None = None) -> set[str]:
    """The comparable spellings of one library from its `Name` and `Title`: shared by installed books and by
    catalogue snapshot entries, so a query ranks the same way against both.

    A versioned library also gets its version-free spellings. Without them `cobra` scores `v1.8.1` above `v1.10.2`
    only because that alias is a character shorter: the version is not part of what a name query asks about."""
    found = {norm(name), norm(_DATE_SUFFIX.sub("", name)), norm(title)}
    normal_title = norm(title)
    if version is None:
        version = split_name(name)[1]
    if version:
        found.add(norm(split_name(name)[0]))
        wanted = {norm(version), norm(version.lstrip("vV"))} - {""}
        for spelling in wanted:
            normal_title = f" {normal_title} ".replace(f" {spelling} ", " ").strip()
        normal_title = " ".join(normal_title.split())
        found.add(normal_title)
    for suffix in (" docs", " documentation", " reference", " manual"):
        if normal_title.endswith(suffix):
            found.add(normal_title[: -len(suffix)])
    parts = (split_name(name)[0] if version else _DATE_SUFFIX.sub("", name)).split("_")
    if parts[0] == "devdocs" and len(parts) >= 3:
        slug = "_".join(parts[2:])
        found.update({norm(slug), norm("devdocs " + slug)})
    host = parts[0]
    if "." in host:  # stackoverflow.com_en_all, security.stackexchange.com_en_all, docs.python.org_en_all
        found.add(norm(host))
        first = host.split(".")[0]
        if host.endswith("stackexchange.com") or host.endswith("stackoverflow.com"):
            found.add(norm(first))
    found.discard("")
    return found


def score_aliases(wanted: str, aliases: set[str]) -> tuple[float, str]:
    """Best score of a normalised query against a set of aliases: exact beats all-words beats prefix beats
    substring beats fuzzy. `(0.0, "")` means no match. Shared by `rank` and the snapshot's `available`."""
    words = set(wanted.split())
    best, why = 0.0, ""
    for alias in aliases:
        if alias == wanted:
            score, reason = 100.0, f"exact match on '{alias}'"
        elif words and words <= set(alias.split()):
            score, reason = 80.0 - 0.1 * len(alias), f"every word appears in '{alias}'"
        elif alias.startswith(wanted):
            score, reason = 70.0 - 0.1 * len(alias), f"'{alias}' starts with the query"
        elif wanted in alias:
            score, reason = 60.0 - 0.1 * len(alias), f"'{alias}' contains the query"
        else:
            ratio = difflib.SequenceMatcher(None, wanted, alias).ratio()
            score, reason = (ratio * 50.0, f"close to '{alias}' ({ratio:.2f})") if ratio >= 0.8 else (0.0, "")
        if score > best:
            best, why = score, reason
    return best, why


@dataclass
class Scan:
    books: list[Book] = field(default_factory=list)
    problems: list[dict[str, str]] = field(default_factory=list)
    directories: list[Path] = field(default_factory=list)


_ARCHIVES: dict[tuple[str, int, int], Any] = {}
_BOOKS: dict[tuple[str, int, int], Book] = {}


def close_all() -> None:
    """Drop every cached archive handle. Windows keeps a ZIM file locked while a handle is open, so anything
    that deletes or replaces a ZIM (the test suite, `primarysource zim get --replace`) calls this first."""
    _ARCHIVES.clear()
    _BOOKS.clear()


def close_path(path: Path) -> None:
    """Drop every cached handle for ONE file (under any recorded mtime and size), leaving the others open. Deleting
    or replacing a ZIM calls this: on Windows an `Archive` blocks the delete until its last reference is gone."""
    for cache in (_ARCHIVES, _BOOKS):
        for key in [k for k in cache if k[0] == str(path)]:
            del cache[key]


def open_archive(path: Path) -> Any:
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _ARCHIVES:
        for stale in [k for k in _ARCHIVES if k[0] == key[0]]:
            del _ARCHIVES[stale]  # a replaced file: the old handle would keep the old inode open for the process
        for stale in [k for k in _BOOKS if k[0] == key[0] and k != key]:
            del _BOOKS[stale]
        reader = _libzim.load("reader")
        try:
            _ARCHIVES[key] = reader.Archive(str(path))
        except (RuntimeError, OSError) as error:
            raise ZimloreError(
                f"{path} is not a readable ZIM file ({error})", "re-download it: primarysource zim get"
            ) from error
    return _ARCHIVES[key]


def _meta(archive: Any, key: str) -> str:
    try:
        raw = archive.get_metadata(key)
    except (KeyError, RuntimeError):
        return ""
    return bytes(raw).decode("utf-8", errors="replace").strip()


def read_book(path: Path) -> Book:
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key in _BOOKS:
        return _BOOKS[key]
    archive = open_archive(path)
    tags = tuple(tag for tag in _meta(archive, "Tags").split(";") if tag and not tag.startswith("_"))
    book = Book(
        name=_meta(archive, "Name") or path.stem,
        title=_meta(archive, "Title") or path.stem,
        date=_meta(archive, "Date"),
        language=_meta(archive, "Language"),
        creator=_meta(archive, "Creator"),
        publisher=_meta(archive, "Publisher"),
        description=_meta(archive, "Description"),
        tags=tags,
        license=_meta(archive, "License"),
        source=_meta(archive, "Source"),
        path=path,
        uuid=str(archive.uuid),
        articles=int(archive.article_count),
        size=stat.st_size,
        has_fulltext=bool(archive.has_fulltext_index),
        has_titles=bool(archive.has_title_index),
        scraper=_meta(archive, "Scraper"),
    )
    _BOOKS[key] = book
    return book


def scan(directories: list[Path] | None = None) -> Scan:
    """Read every `*.zim` under the library directories. A file that is not a readable ZIM is reported in
    `problems`, never dropped: the books that are missing are exactly the ones a user wonders about."""
    result = Scan(directories=directories if directories is not None else zim_dirs())
    for directory in result.directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.zim")):
            try:
                result.books.append(read_book(path))
            except ZimloreError as error:
                result.problems.append({"path": str(path), "error": error.message})
    result.books.sort(key=lambda b: (b.name, date_key(b.date), str(b.path)))
    return result


def user_aliases() -> dict[str, str]:
    """`$ZIMLORE_HOME/aliases.json`: {"py": "devdocs_en_python"}. A malformed file is an error, not an empty map."""
    path = home() / "aliases.json"
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ZimloreError(f"{path} is not valid JSON ({error})", f"fix or delete {path}") from error
    if not isinstance(loaded, dict) or not all(isinstance(v, str) for v in loaded.values()):
        raise ZimloreError(f"{path} must map alias to library name", f"fix or delete {path}")
    return {str(k): v for k, v in loaded.items()}


@dataclass(frozen=True)
class Candidate:
    book: Book
    score: float
    why: str
    members: tuple[Book, ...] = ()  # every installed book of the family that matched; `book` is the newest


def empty_library_error(scanned: Scan) -> ZimloreError:
    where = ", ".join(str(d) for d in scanned.directories)
    unreadable = ""
    if scanned.problems:
        unreadable = (
            f"; {len(scanned.problems)} file(s) there could not be read, first: {scanned.problems[0]['error']}"
        )
    # Files that cannot be opened because the binding is missing are not an empty library: install it first.
    fix = (
        "download one: primarysource zim catalog flask ; primarysource zim get devdocs_en_flask "
        "(or copy a .zim into that directory)"
        if not scanned.problems or _libzim.available()
        else _libzim.REMEDY
    )
    return ZimloreError(
        f"no ZIM files found in {where}{unreadable}",
        fix,
        searched=[str(d) for d in scanned.directories],
        problems=scanned.problems,
    )


def newest_version(books: list[Book]) -> Book:
    """The book with the newest version (a book with no version loses to any that has one), then the newest
    edition date, then the file name so that the answer never depends on directory order."""
    return max(
        sorted(books, key=lambda b: str(b.path)),
        key=lambda b: (version_key(b.version) if b.version else (-1, (), 0, (), ""), date_key(b.date)),
    )


def rank(query: str, books: list[Book], user: dict[str, str] | None = None) -> list[Candidate]:
    """Score each FAMILY of books against a name, best first: exact alias beats all-words beats prefix beats
    substring beats fuzzy. Every version and edition of one family scores alike (the best of them), so a tie can
    only be between different libraries; the candidate's `book` is the family's newest version, newest edition,
    and `members` is everything installed in the family.

    This is where `cobra` once resolved to v1.8.1 over v1.10.2: each version was scored on its own alias, the
    scores differed by 0.1 per character of alias length, and the ambiguity guard compared only the top two."""
    wanted = norm(query)
    if not wanted:
        return []
    families: dict[str, list[tuple[Book, float, str]]] = {}
    for book in books:
        best, why = score_aliases(wanted, book.aliases(user))
        if best:
            families.setdefault(book.family, []).append((book, best, why))
    out: list[Candidate] = []
    for members in families.values():
        _, score, why = max(members, key=lambda m: m[1])
        matched = [m[0] for m in members]
        out.append(Candidate(newest_version(matched), score, why, tuple(matched)))
    return sorted(out, key=lambda c: (-c.score, c.book.family))


def editions(book: Book, books: list[Book]) -> list[Book]:
    """Every installed file of `book`'s library, newest first by PARSED date (undated last, ties by path)."""
    mine = sorted((b for b in books if b.name == book.name), key=lambda b: str(b.path))
    return sorted(mine, key=lambda b: date_key(b.date), reverse=True)


def family_of(book: Book, books: list[Book]) -> list[Book]:
    """Every installed book in `book`'s family: all its versions and all their editions."""
    return [b for b in books if b.family == book.family]


def versions_of(book: Book, books: list[Book]) -> list[str]:
    """The distinct upstream versions installed in `book`'s family, newest first; versions the ZIMs do not state
    are left out (a family of ZIMs that state none has none to list)."""
    found = {b.version for b in books if b.family == book.family and b.version}
    return sorted(found, key=version_key, reverse=True)


def newest(books: list[Book]) -> Book | None:
    """The newest of `books` by parsed date; None for an empty list."""
    return max(sorted(books, key=lambda b: str(b.path)), key=lambda b: date_key(b.date), default=None)


@dataclass(frozen=True)
class Selection:
    """What a library query selected. `kind` is `newest` (a family named, no version asked), `exact` or `prefix`
    (the version asked for) or `name` (a whole `Name` was given, which is already one version)."""

    book: Book
    why: str
    kind: str
    requested: str | None = None
    members: tuple[Book, ...] = ()

    @property
    def versions(self) -> list[str]:
        return versions_of(self.book, list(self.members))

    @property
    def other_versions(self) -> list[str]:
        return [v for v in self.versions if v != self.book.version]


class Query(NamedTuple):
    package: purl.Purl | None
    text: str  # the name part: the whole query, or what is left of it after the version is split off
    version: str | None


_VERSION_TAIL = re.compile(r"^[vV]?\d+(?:\.[0-9A-Za-z]+)*(?:-[0-9A-Za-z.]+)?$")


def split_query(text: str) -> tuple[str, str] | None:
    """`cryptography==50.0.2`, `cryptography@50`, `cobra v1.8.1`, `flask 3.1` as (name, version); None when the
    query carries no version. An `@` at the very start is an npm scope, not a version separator."""
    cleaned = text.strip()
    for separator in ("==", "@"):
        if separator in cleaned[1:]:
            name, _, version = cleaned.rpartition(separator)
            if name.strip() and version.strip() and " " not in version.strip():
                return name.strip(), version.strip()
    parts = cleaned.rsplit(None, 1)
    if len(parts) == 2 and _VERSION_TAIL.match(parts[1]):
        return parts[0].strip(), parts[1]
    return None


def parse_query(text: str) -> list[Query]:
    """The readings of a library query, most specific first. A purl is one reading; anything else is a name with a
    version split off (when it has one) and then the whole text as a name."""
    if purl.is_purl(text):
        parsed = purl.parse(text)
        return [Query(parsed, parsed.words, parsed.version)]
    readings: list[Query] = []
    split = split_query(text)
    if split:
        readings.append(Query(None, split[0], split[1]))
    readings.append(Query(None, text.strip(), None))
    return readings


def _version_error(family: str, requested: str, members: list[Book]) -> ZimloreError:
    """The requested version is not installed. No build command is named: none exists."""
    installed = versions_of(members[0], members)
    stated = (
        f"installed versions: {', '.join(installed)}" if installed else "none of the installed ZIMs states a version"
    )
    return LibraryNotFound(
        f"{family} has no installed version matching '{requested}' ({stated})",
        "ask for one of the installed versions, or omit the version to get the newest; "
        "primarysource zim list shows them"
        if installed
        else "this library records its edition date, not a release: omit the version",
        tool_hint="omit the version to get the newest, or ask for an installed one: zim_libraries lists them",
        requested_version=requested,
        installed_versions=installed,
        installed=sorted({b.name for b in members}),
    )


def _pick_version(members: list[Book], requested: str | None) -> tuple[Book, str] | None:
    """The book of `members` for a requested version and how it matched (`exact`, `prefix`, `newest`); None when
    nothing installed matches the version."""
    if requested is None:
        return newest_version(members), "newest"
    exact = [b for b in members if b.version and same_version(b.version, requested)]
    if exact:
        return newest_version(exact), "exact"
    near = [b for b in members if b.version and version_prefix(requested, b.version)]
    if near:
        return newest_version(near), "prefix"
    return None


def _tied(query: str, tied: list[Candidate]) -> ZimloreError:
    return ZimloreError(
        f"'{query}' matches {len(tied)} libraries equally well; name one of them",
        "use the library name exactly as listed",
        candidates=[{"name": c.book.name, "title": c.book.title, "why": c.why} for c in tied],
    )


def select(query: str, scanned: Scan | None = None) -> Selection:
    """The one book a library query means, or a `ZimloreError` that lists the candidates or the installed versions.

    The query may be a name or alias (`cobra`: the newest installed version), a name with a version (`cobra
    v1.8.1`, `flask 3.1`, `cryptography==50.0.2`, `cryptography@50`: that version, or the newest that starts
    with it), a whole `Name` (that very ZIM) or a purl (`pkg:pypi/flask@3.1.0`, matched on the ZIM's `purl:` tag).
    Never guesses between two different libraries that match equally well; the versions of one library are
    ordered, not tied."""
    scanned = scanned or scan()
    if not scanned.books:
        raise empty_library_error(scanned)
    books = scanned.books
    user = user_aliases()
    readings = parse_query(query)
    wanted = norm(query)
    pinned = {target for alias, target in user.items() if norm(alias) == wanted}
    named = [] if readings[0].package else [b for b in books if norm(b.name) == wanted or b.name in pinned]
    if named:
        families = sorted({b.family for b in named})
        if len(families) > 1:
            raise _tied(
                query,
                [
                    Candidate(newest_version([b for b in named if b.family == f]), 100.0, "exact Name")
                    for f in families
                ],
            )
        return Selection(
            newest_version(named),
            f"exact match on '{named[0].name}'",
            "name",
            None,
            tuple(family_of(named[0], books)),
        )
    unstated: ZimloreError | None = None
    for reading in readings:
        if reading.package:
            tagged = [b for b in books if b.package and b.package.key == reading.package.key]
            if tagged:
                members = family_of(tagged[0], books)
                chosen = _pick_version(members, reading.version)
                if chosen is None:
                    raise _version_error(tagged[0].family, reading.version or "", members)
                return Selection(
                    chosen[0], f"purl tag {reading.package.text}", chosen[1], reading.version, tuple(members)
                )
        ranked = rank(reading.text, books, user)
        if not ranked:
            continue
        top = ranked[0]
        tied = [c for c in ranked if abs(c.score - top.score) < 1e-9]
        if len(tied) > 1:
            raise _tied(query, tied)
        chosen = _pick_version(list(top.members), reading.version)
        if chosen is None:
            if reading.version and not versions_of(top.book, list(top.members)) and len(readings) > 1:
                # nothing installed states a version: `python 3` may be a name, so read the whole text, and
                # report the missing version if that finds nothing either
                unstated = _version_error(top.book.family, reading.version, list(top.members))
                continue
            raise _version_error(top.book.family, reading.version or "", list(top.members))
        return Selection(chosen[0], top.why, chosen[1], reading.version, top.members)
    if unstated:
        raise unstated
    raise LibraryNotFound(
        f"no installed library matches '{query}'",
        "primarysource zim list shows what is installed; primarysource zim catalog <name> finds one to download",
        installed=[b.name for b in books],
    )


def find(query: str, scanned: Scan | None = None) -> Book:
    """The one book a name means (see `select`)."""
    return select(query, scanned).book

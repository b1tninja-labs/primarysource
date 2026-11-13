"""Import vector sets named in `vectors.toml`: download, check the pinned sha256, parse, store.

Every entry pins the sha256 of what it downloads (the zip, or the ACVP `prompt.json`), so a first fetch never
defines the truth. An entry without a pin is refused, and `primarysource cavp pin <file>` prints the digest to
write. Nothing here unpacks an archive to disk.

    [[vector]]
    id = "cavp/ecdsa/SigVer.rsp"
    kind = "cavp"
    algorithm = "ECDSA"
    url = "https://csrc.nist.gov/.../186-4ecdsatestvectors.zip"
    sha256 = "..."                 # of the zip
    member = "186-4ecdsatestvectors/SigVer.rsp"

    [[vector]]
    id = "acvp/ECDSA-SigVer-1.0"
    kind = "acvp"
    url = ".../prompt.json"            # pin a commit, not a branch
    sha256 = "..."
    expected_url = ".../expectedResults.json"
    expected_sha256 = "..."
"""

from __future__ import annotations

import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from primarysource.cavp.model import MAX_SOURCE_BYTES, IndexEntry, Store, VectorSet, sha256_bytes
from primarysource.cavp.parse import check_set_id, parse_acvp, parse_rsp, read_member
from primarysource.errors import LibError

PACKAGE_DATA = Path(__file__).resolve().parent / "data"
USER_AGENT = "primarysource-cavp/0.1 (pinned test-vector fetch)"
TIMEOUT_SECONDS = 120
_FIELDS = {"id", "kind", "algorithm", "mode", "url", "sha256", "member", "expected_url", "expected_sha256"}

Opener = Callable[[urllib.request.Request, float], IO[bytes]]


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    kind: str
    algorithm: str
    url: str
    sha256: str
    member: str = ""
    mode: str = ""
    expected_url: str = ""
    expected_sha256: str = ""


def load_sources(path: Path | None = None) -> tuple[Source, ...]:
    """The entries of `vectors.toml`: the file given, else the one shipped in the package."""
    file = path if path is not None else PACKAGE_DATA / "vectors.toml"
    try:
        raw: dict[str, Any] = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LibError(f"cannot read {file}: {exc}", "") from None
    out: list[Source] = []
    for row in raw.get("vector", []):
        unknown = sorted(set(row) - _FIELDS)
        if unknown:
            raise LibError(f"{file}: unknown field(s) {', '.join(unknown)} in {row.get('id')!r}", "")
        try:
            source = Source(**row)
        except TypeError as exc:
            raise LibError(f"{file}: bad entry {row.get('id')!r} ({exc})", "") from None
        check_set_id(source.id, source.kind)
        if source.kind == "acvp" and bool(source.expected_url) != bool(source.expected_sha256):
            raise LibError(f"{source.id}: expected_url and expected_sha256 go together", "")
        out.append(source)
    ids = [s.id for s in out]
    if len(set(ids)) != len(ids):
        raise LibError(f"{file}: duplicate vector ids", "")
    return tuple(out)


def download(url: str, opener: Opener | None = None) -> bytes:
    """GET `url`, at most `MAX_SOURCE_BYTES`. https only (a test may pass its own opener)."""
    if opener is None and not url.startswith("https://"):
        raise LibError(f"refusing {url!r}: only https downloads", "")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    try:
        if opener is None:
            stream = urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS)  # noqa: S310
        else:
            stream = opener(request, TIMEOUT_SECONDS)
        with stream:
            body: bytes = stream.read(MAX_SOURCE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LibError(f"download failed for {url}: {exc}", "check the network and the url") from None
    if len(body) > MAX_SOURCE_BYTES:
        raise LibError(f"{url}: larger than {MAX_SOURCE_BYTES} bytes, refusing", "")
    return body


def check_pin(what: str, data: bytes, pinned: str) -> str:
    """The digest of `data`, or a `LibError` when it is not the pinned one or nothing is pinned."""
    actual = sha256_bytes(data)
    if not pinned:
        raise LibError(f"{what}: no sha256 pinned (this file is {actual})", "add sha256 to its vectors.toml entry")
    if actual != pinned.lower():
        raise LibError(
            f"{what}: sha256 {actual} is not the pinned {pinned}", "the upstream file changed: review, then re-pin"
        )
    return actual


def build(source: Source, artifact: bytes, expected: bytes | None = None) -> VectorSet:
    """Check pins and parse. `artifact` is the downloaded file (zip or json); `expected` the ACVP answers file."""
    digest = check_pin(source.id, artifact, source.sha256)
    if source.kind == "cavp":
        member = read_member(artifact, source.member) if source.member else artifact
        return parse_rsp(
            member,
            set_id=source.id,
            algorithm=source.algorithm,
            source_url=source.url,
            sha256=digest,
            member_sha256=sha256_bytes(member),
            mode=source.mode,
        )
    if source.expected_url:
        if expected is None:
            raise LibError(f"{source.id}: the expectedResults file is needed", "")
        check_pin(f"{source.id} expectedResults", expected, source.expected_sha256)
    return parse_acvp(
        artifact,
        expected if source.expected_url else None,
        set_id=source.id,
        source_url=source.url,
        sha256=digest,
        member_sha256=digest,
    )


def import_files(store: Store, source: Source, artifact: Path, expected: Path | None = None) -> IndexEntry:
    """Import from files already on disk (the same pins apply)."""
    size = artifact.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise LibError(f"{artifact}: {size} bytes is over the {MAX_SOURCE_BYTES} byte cap", "")
    return store.write(build(source, artifact.read_bytes(), expected.read_bytes() if expected else None))


def fetch(store: Store, source: Source, opener: Opener | None = None) -> IndexEntry:
    """Download `source`, verify its pins, parse and store it."""
    artifact = download(source.url, opener)
    expected = download(source.expected_url, opener) if source.expected_url else None
    return store.write(build(source, artifact, expected))

"""The pinned archive stream: verified, bounded, never extracted, over in-memory archives."""

from __future__ import annotations

import gzip
import io
import tarfile
import urllib.request
from pathlib import Path

import pytest
from pkgdocs_fixture import FILES, INCLUDE, MIRROR, URL, make_tar, manifest_for, no_wait, opener_for

from primarysource.errors import LibError
from primarysource.pkgdocs import fetch
from primarysource.pkgdocs.fetch import Limits, Refused, Source, Throttle, fetch_tree, read_tree

SOURCE = Source(URL, strip=1)
PINNED = manifest_for(FILES, INCLUDE)


def test_a_verified_archive_yields_only_the_selected_regular_files() -> None:
    result = read_tree(io.BytesIO(make_tar(FILES)), SOURCE, include=INCLUDE, expect=PINNED)
    assert sorted(result.files) == ["docs/alpha.md", "docs/beta.md"]
    assert result.pinned and result.files_sha256 == PINNED
    assert result.skipped == {"link, directory or special file": 1, "not selected": 1}
    assert result.gz_sha256 is not None


def test_a_digest_mismatch_yields_nothing_and_names_the_remedy() -> None:
    with pytest.raises(Refused, match="not the .* pinned for them") as caught:
        read_tree(io.BytesIO(make_tar(FILES)), SOURCE, include=INCLUDE, expect="0" * 64)
    assert "pin" in caught.value.hint


def test_the_manifest_digest_does_not_depend_on_how_the_archive_was_made() -> None:
    forge = make_tar(FILES, prefix="repo-1234/")
    subtree = make_tar(FILES, prefix="", gz=False)
    other_prefix_depth = fetch.read_tree(io.BytesIO(forge), SOURCE, include=INCLUDE)
    plain = fetch.read_tree(io.BytesIO(subtree), Source(URL, strip=0), include=INCLUDE)
    assert other_prefix_depth.files_sha256 == plain.files_sha256 == PINNED
    assert other_prefix_depth.tar_sha256 != plain.tar_sha256
    assert plain.gz_sha256 is None


def test_a_subdir_source_reads_a_whole_repository_archive_as_a_subtree_archive() -> None:
    members = {"README": b"top", **{f"sub/{k}": v for k, v in FILES.items()}}
    whole = fetch.read_tree(io.BytesIO(make_tar(members)), Source(URL, strip=1, subdir="sub"), include=INCLUDE)
    assert whole.files_sha256 == PINNED


def test_links_dotdot_absolute_nul_and_backslash_names_are_skipped_and_counted() -> None:
    members = {"docs/ok.md": b"# ok\n", "../evil.md": b"x", "/abs.md": b"x", "docs/back\\slash.md": b"x"}
    result = read_tree(
        io.BytesIO(
            make_tar(members, links={"docs/sym.md": (b"s", "/etc/passwd"), "docs/hard.md": (b"h", "docs/ok.md")})
        ),
        SOURCE,
        include=lambda path: path.endswith(".md"),
    )
    assert sorted(result.files) == ["docs/ok.md"]
    assert result.skipped["unsafe member name"] == 3 and result.skipped["link, directory or special file"] == 3


def test_a_kept_member_over_the_cap_raises_and_so_does_a_declared_giant() -> None:
    with pytest.raises(Refused, match="limit per file"):
        read_tree(
            io.BytesIO(make_tar({"docs/big.md": b"x" * 5000})),
            SOURCE,
            include=INCLUDE,
            limits=Limits(member_bytes=4096),
        )
    info = tarfile.TarInfo("repo-aaaa/docs/huge.md")
    info.size = 1 << 30  # declared, never written
    header = info.tobuf()
    with pytest.raises(Refused, match="declares 1,073,741,824 bytes"):
        read_tree(io.BytesIO(header), SOURCE, include=INCLUDE)


def test_member_count_total_bytes_and_decompressed_size_are_bounded() -> None:
    many = {f"docs/m{chr(97 + n)}.md": b"x" for n in range(6)}
    with pytest.raises(Refused, match="more than 5 members"):
        read_tree(io.BytesIO(make_tar(many)), SOURCE, include=INCLUDE, limits=Limits(members=5))
    with pytest.raises(Refused, match="total more than 3 bytes"):
        read_tree(io.BytesIO(make_tar(many)), SOURCE, include=INCLUDE, limits=Limits(total_bytes=3))
    bomb = gzip.compress(b"\x00" * 5_000_000, mtime=0)
    with pytest.raises(Refused, match="decompressed archive is over 100,000 bytes"):
        read_tree(io.BytesIO(bomb), SOURCE, include=INCLUDE, limits=Limits(tar_bytes=100_000))
    with pytest.raises(Refused, match="the archive is over 50 bytes"):
        read_tree(io.BytesIO(make_tar(FILES)), SOURCE, include=INCLUDE, limits=Limits(compressed_bytes=50))


def test_a_truncated_or_damaged_archive_raises_and_returns_nothing_partial() -> None:
    data = make_tar(FILES, gz=False)
    for cut in (700, 1300, 2000, 3000):
        with pytest.raises(LibError, match="truncated"):
            read_tree(io.BytesIO(data[:cut]), SOURCE, include=INCLUDE)
    gz = make_tar(FILES)
    with pytest.raises(LibError, match="truncated"):
        read_tree(io.BytesIO(gz[: len(gz) // 2]), SOURCE, include=INCLUDE)
    with pytest.raises(LibError, match="truncated"):
        read_tree(io.BytesIO(b"\x1f\x8b" + b"junk" * 50), SOURCE, include=INCLUDE)


def test_one_request_per_second_is_enforced_by_the_throttle() -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    throttle = Throttle(1.0, clock=lambda: now[0], sleep=sleep)
    throttle.wait()
    now[0] += 0.25
    throttle.wait()
    now[0] += 5
    throttle.wait()
    assert slept == [0.75]


def test_fetching_waits_before_each_source_and_falls_over_to_a_mirror_that_gives_the_same_digest() -> None:
    seen: list[str] = []
    waits: list[float] = []
    throttle = Throttle(1.0, clock=lambda: 0.0, sleep=waits.append)
    result = fetch_tree(
        [SOURCE, Source(MIRROR, strip=1)],
        include=INCLUDE,
        expect=PINNED,
        opener=opener_for({MIRROR: make_tar(FILES)}, seen),
        throttle=throttle,
    )
    assert seen == [URL, MIRROR] and result.url == MIRROR
    assert waits == [1.0], "the second request waited out the interval"


def test_a_mirror_that_disagrees_is_a_finding_not_a_retry() -> None:
    changed = {**FILES, "docs/alpha.md": b"# Different\n"}
    seen: list[str] = []
    with pytest.raises(Refused, match="not the .* pinned"):
        fetch_tree(
            [SOURCE, Source(MIRROR, strip=1)],
            include=INCLUDE,
            expect=PINNED,
            opener=opener_for({URL: make_tar(changed), MIRROR: make_tar(FILES)}, seen),
            throttle=no_wait(),
        )
    assert seen == [URL]


def test_when_every_source_fails_the_error_lists_each_and_names_a_remedy() -> None:
    with pytest.raises(LibError, match="no source could be read") as caught:
        fetch_tree([SOURCE, Source(MIRROR, strip=1)], include=INCLUDE, opener=opener_for({}), throttle=no_wait())
    assert URL in caught.value.message and MIRROR in caught.value.message
    assert "archive" in caught.value.hint


def test_only_https_sources_are_read() -> None:
    with pytest.raises(Refused, match="only https"):
        fetch_tree(
            [Source("http://forge.invalid/a.tar.gz")], include=INCLUDE, opener=opener_for({}), throttle=no_wait()
        )


def test_a_redirect_to_an_unlisted_host_or_to_http_is_refused() -> None:
    handler = fetch._Redirects(frozenset({"forge.invalid", "codeload.invalid"}))
    request = urllib.request.Request(URL)  # noqa: S310
    ok = handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, "https://codeload.invalid/x")
    assert ok is not None
    for target in ("https://elsewhere.invalid/x", "http://forge.invalid/x", "ftp://forge.invalid/x"):
        with pytest.raises(Refused, match="host is not one the catalogue lists"):
            handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, target)


def test_read_local_reads_a_downloaded_archive_and_names_the_remedy_when_it_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "a.tar.gz"
    path.write_bytes(make_tar(FILES))
    result = fetch.read_local(str(path), SOURCE, include=INCLUDE, expect=PINNED)
    assert result.pinned
    with pytest.raises(LibError, match="no file at") as caught:
        fetch.read_local(str(tmp_path / "gone.tar.gz"), SOURCE, include=INCLUDE)
    assert caught.value.hint

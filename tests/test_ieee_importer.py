"""Importing user-supplied IEEE files: a synthesised POSIX archive and pypdf-made 802 PDFs. No real text."""

from __future__ import annotations

import hashlib
import io
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from ieee_posixfixture import FROB, archive

from primarysource.errors import LibError
from primarysource.ieee import importer
from primarysource.ieee.catalogue import EDITIONS, POSIX_2024
from primarysource.ieee.importer import Limits, clause_of, import_pdf, import_posix, normalise_designation


def test_a_verified_archive_installs_only_its_html_pages(tmp_path: Path) -> None:
    path, pinned = archive(tmp_path, symlink="susv5-html/functions/style.css")
    report = import_posix(path, home=tmp_path / "home", pinned=pinned)
    root = tmp_path / "home" / "posix" / "posix-2024"
    assert report.path == root and report.pages == 3
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*.html")) == [
        "basedefs/V9_chap09.html",
        "functions/frob.html",
        "utilities/[.html",
    ]
    assert report.skipped == {"not html": 2, "not a regular file": 1}
    record = json.loads((root / "install.json").read_text(encoding="utf-8"))
    assert record["sha256"] == pinned.sha256 and record["pages"] == 3
    assert [p.name for p in (tmp_path / "home" / "posix").iterdir()] == ["posix-2024"], "no staging left behind"


def test_a_digest_mismatch_is_refused_before_anything_is_read(tmp_path: Path) -> None:
    path, _ = archive(tmp_path)
    with pytest.raises(LibError, match="not the .* pinned for posix-2024") as caught:
        import_posix(path, home=tmp_path / "home")
    assert POSIX_2024.source_url is not None and POSIX_2024.source_url in caught.value.hint
    assert not (tmp_path / "home" / "posix").exists() or not any((tmp_path / "home" / "posix").iterdir())


@pytest.mark.parametrize(
    "name", ["susv5-html/../../evil.html", "/etc/evil.html", "susv5-html\\..\\evil.html", "C:/evil.html"]
)
def test_traversal_members_refuse_the_whole_import(tmp_path: Path, name: str) -> None:
    members = {"susv5-html/functions/frob.html": FROB.encode(), name: b"<p>x</p>"}
    path, pinned = archive(tmp_path, members)
    with pytest.raises(LibError, match="refusing archive member"):
        import_posix(path, home=tmp_path / "home", pinned=pinned)
    assert not (tmp_path / "home" / "posix" / "posix-2024").exists()
    assert not list(tmp_path.rglob("evil.html"))


def test_oversize_members_and_member_counts_are_refused(tmp_path: Path) -> None:
    path, pinned = archive(tmp_path, {"susv5-html/functions/big.html": b"x" * 5000})
    with pytest.raises(LibError, match="per-page limit"):
        import_posix(path, home=tmp_path / "home", pinned=pinned, limits=Limits(member_bytes=4096))
    many = {f"susv5-html/functions/p{n}.html": b"<p>x</p>" for n in range(6)}
    path, pinned = archive(tmp_path, many)
    with pytest.raises(LibError, match="more than 5 members"):
        import_posix(path, home=tmp_path / "home", pinned=pinned, limits=Limits(members=5))
    with pytest.raises(LibError, match="unpacks to more than"):
        import_posix(path, home=tmp_path / "home", pinned=pinned, limits=Limits(total_bytes=20))


def test_an_oversize_archive_is_refused_without_reading_it_all(tmp_path: Path) -> None:
    path, pinned = archive(tmp_path)
    with pytest.raises(LibError, match="over 100 bytes"):
        import_posix(path, home=tmp_path / "home", pinned=pinned, limits=Limits(archive_bytes=100))


def test_a_reimport_replaces_the_edition_whole(tmp_path: Path) -> None:
    home = tmp_path / "home"
    path, pinned = archive(tmp_path, {"susv5-html/functions/old.html": b"<p>old</p>"})
    import_posix(path, home=home, pinned=pinned)
    path, pinned = archive(tmp_path)
    import_posix(path, home=home, pinned=pinned)
    root = home / "posix" / "posix-2024"
    assert not (root / "functions" / "old.html").exists() and (root / "functions" / "frob.html").exists()


def test_a_file_that_is_not_a_tarball_is_a_liberror(tmp_path: Path) -> None:
    path = tmp_path / "susv5.tgz"
    path.write_bytes(b"not a tarball at all")
    pinned = replace(POSIX_2024, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(LibError, match="not a readable gzip tar"):
        import_posix(path, home=tmp_path / "home", pinned=pinned)


# --- 802 PDFs ---------------------------------------------------------------------------------------------------


def _pdf(tmp_path: Path, *, encrypt: bool = False) -> Path:
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=200, height=200)
    parent = writer.add_outline_item("5 Invented clause", 0)
    writer.add_outline_item("5.4 Invented subclause", 1, parent=parent)
    writer.add_outline_item("Annex A (informative) Invented annex", 2)
    writer.add_outline_item("Contents", 0)
    if encrypt:
        writer.encrypt("user-pw", algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    path = tmp_path / "invented.pdf"
    path.write_bytes(buffer.getvalue())
    return path


def test_a_pdf_import_stores_the_clause_outline(tmp_path: Path) -> None:
    from primarysource.ieee import ieee802

    report = import_pdf(_pdf(tmp_path), "IEEE Std 802.1Q-2022", home=tmp_path)
    assert report.edition == "802.1Q-2022" and report.pages == 3
    record = json.loads((report.path / "install.json").read_text(encoding="utf-8"))
    assert record["pinned"] is False and record["backend"].startswith("pypdf ")
    text = ieee802.outline("802.1Q-2022", home=tmp_path)
    assert "5 Invented clause  802.1Q-2022§5  (p. 1)" in text
    assert "  5.4 Invented subclause  802.1Q-2022§5.4  (p. 2)" in text
    assert "Annex A (informative) Invented annex  802.1Q-2022§A  (p. 3)" in text
    assert "Contents  (p. 1)" in text


def test_an_unknown_designation_is_refused_and_lists_the_known_ones(tmp_path: Path) -> None:
    with pytest.raises(LibError, match=r"not in the ieee802 catalogue \(known: 802.1Q-2022, 802.3-2022\)"):
        import_pdf(tmp_path / "x.pdf", "802.99-2030", home=tmp_path)


def test_a_file_that_is_not_a_pdf_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "x.pdf"
    path.write_bytes(b"<html>a login page saved by mistake</html>")
    with pytest.raises(LibError, match="not a PDF"):
        import_pdf(path, "802.3-2022", home=tmp_path)


def test_an_encrypted_pdf_is_never_decrypted(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="encrypted"):
        import_pdf(_pdf(tmp_path, encrypt=True), "802.3-2022", home=tmp_path)


def test_a_pinned_pdf_with_another_digest_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF-1.7 invented")
    monkeypatch.setitem(EDITIONS, "802.3-2022", replace(EDITIONS["802.3-2022"], sha256="0" * 64))
    with pytest.raises(LibError, match="not the 0{64} pinned for 802.3-2022"):
        import_pdf(path, "802.3-2022", home=tmp_path)


def test_without_pypdf_the_pdf_import_names_the_extra(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF-1.7 invented")
    monkeypatch.setitem(sys.modules, "pypdf", None)
    with pytest.raises(LibError, match="needs 'pypdf'") as caught:
        import_pdf(path, "802.3-2022", home=tmp_path)
    assert caught.value.hint == 'pip install "primarysource[ieee]"'


@pytest.mark.parametrize(
    ("title", "clause"),
    [("5.4 Bridge", "5.4"), ("12 Scope", "12"), ("Annex B Tables", "B"), ("B.3 More", "B.3"), ("Contents", None)],
)
def test_bookmark_titles_give_clause_numbers(title: str, clause: str | None) -> None:
    assert clause_of(title) == clause


def test_designations_are_normalised() -> None:
    assert normalise_designation("IEEE Std 802.1Q-2022") == "802.1Q-2022"
    assert normalise_designation("IEEE 802.3-2022") == "802.3-2022"


def test_the_command_line_reports_a_refusal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert importer.main(["posix", str(tmp_path / "missing.tgz")]) == 1
    assert "no file at" in capsys.readouterr().err
    assert importer.main([]) == 2

"""The LaTeX reader over an invented specification, hostile input included. No real text."""

from __future__ import annotations

import time

import pytest

from primarysource.errors import LibError
from primarysource.pkgdocs.readers.latex import read_latex

ROOT = r"""\documentclass{book}
\title{Invented}
\begin{document}
\maketitle
{\small Copyright someone. Released under a made-up licence.}
\tableofcontents
\include{one}
% a comment line
\appendix
\include{two}
\end{document}
"""

ONE = r"""\chapter{First chapter}
\label{ch:first}

Intro text with \t{code} and \emph{stress}.\@ See section~\ref{sec:inner}.

\section{Inner part}
\label{sec:inner}

\begin{description}
\item[ALPHA] The first variable, as in \cite{ref1}.
\item[BETA] The second.
\end{description}

\begin{compactitem}
\item one thing
\item another
\end{compactitem}

\begin{verbatim}
raw \t{text} % not a comment here? yes it is stripped by the reader's comment pass
\end{verbatim}

\subsection{Deeper}

Deep text --- with dashes.

\section*{Unnumbered}

Plain.
"""

TWO = r"""\chapter{Appendix chapter}

\section{Part A one}

Appendix \textbackslash{} text, 100\% sure.
"""


FILES = {"root.tex": ROOT.encode(), "one.tex": ONE.encode(), "two.tex": TWO.encode()}


def test_chapters_are_numbered_then_lettered_after_appendix_and_labels_resolve_refs() -> None:
    doc = read_latex(FILES, "root.tex", "inv", "Invented")
    assert [(s.id, s.title, s.depth) for s in doc.sections] == [
        ("0", "Invented", 1),
        ("1", "First chapter", 1),
        ("1.1", "Inner part", 2),
        ("1.1.1", "Deeper", 3),
        ("u1", "Unnumbered", 2),
        ("A", "Appendix chapter", 1),
        ("A.1", "Part A one", 2),
    ]
    assert [s.anchor for s in doc.sections][1:3] == ["ch:first", "sec:inner"]
    assert doc.sections[0].units == ("Copyright someone. Released under a made-up licence.",)
    assert doc.sections[1].units == ("Intro text with code and stress. See section 1.1.",)


def test_items_are_blocks_and_environments_keep_their_raw_text() -> None:
    doc = read_latex(FILES, "root.tex", "inv", "Invented")
    inner = doc.sections[2].units
    assert inner[:4] == ("ALPHA: The first variable, as in [ref1].", "BETA: The second.", "one thing", "another")
    assert inner[4].startswith("[verbatim]\n\\begin{verbatim}\nraw")
    assert doc.sections[3].units == ("Deep text \u2014 with dashes.",)
    assert doc.sections[6].units == ("Appendix \\ text, 100% sure.",)


def test_an_include_reads_only_from_the_given_files_and_a_missing_one_is_reported() -> None:
    root = b"\\begin{document}\n\\chapter{C}\n\\include{/etc/passwd}\n\\include{gone}\n\\end{document}\n"
    doc = read_latex({"root.tex": root}, "root.tex", "d", "D")
    assert doc.sections[0].units == ("[include] /etc/passwd [include] gone",)
    assert doc.warnings and "/etc/passwd" in doc.warnings[0] and "gone" in doc.warnings[0]


def test_an_include_loop_and_deep_chain_terminate() -> None:
    loop = {"a.tex": b"\\begin{document}\n\\include{b}\n", "b.tex": b"\\chapter{B}\n\\include{a}\n\\include{b}\n"}
    doc = read_latex(loop, "a.tex", "d", "D")
    assert any(s.title == "B" for s in doc.sections)
    chain = {f"f{n}.tex": f"\\chapter{{N{n}}}\n\\include{{f{n + 1}}}\n".encode() for n in range(20)}
    chain["f0.tex"] = b"\\begin{document}\n" + chain["f0.tex"]
    deep = read_latex(chain, "f0.tex", "d", "D")
    assert len([s for s in deep.sections if s.depth == 1 and s.id != "0"]) <= 5


def test_unknown_commands_are_dropped_with_one_warning_that_names_them() -> None:
    doc = read_latex(
        {"r.tex": b"\\begin{document}\n\\chapter{C}\nSee \\weird{kept words} and \\bare here.\n\\end{document}\n"},
        "r.tex",
        "d",
        "D",
    )
    assert doc.sections[0].units == ("See kept words and here.",)
    assert doc.warnings == ("LaTeX commands dropped (their arguments kept): bare, weird",)


def test_unbalanced_braces_a_long_command_run_and_nesting_are_linear() -> None:
    hostile = "\\begin{document}\n\\chapter{C}\n" + "\\a{" * 50_000 + "x" + "}" * 10 + "\n" + "{" * 100_000 + "\n"
    start = time.perf_counter()
    read_latex({"r.tex": hostile.encode()}, "r.tex", "d", "D")
    assert time.perf_counter() - start < 3


@pytest.mark.parametrize("payload", [b"\\begin{document}\n\x00\n", b"\\begin{document}\n\xff\n"])
def test_nul_bytes_and_invalid_utf8_raise_liberror(payload: bytes) -> None:
    with pytest.raises(LibError):
        read_latex({"r.tex": payload}, "r.tex", "d", "D")


def test_a_missing_root_is_an_empty_document_with_a_warning() -> None:
    doc = read_latex({}, "pms.tex", "d", "D")
    assert doc.sections == () and doc.warnings

"""Markup in labels and notes: ``f_p``, ``T_{ij}``, ``cm^2``, ``*k*`` and ``**bold**``.

A one-letter script ends at the next space or sign, and ``{}`` holds more. What is not markup stays as written:
``beam_splitter``, ``2 * 3``, ``a*b``. A backslash keeps the next character: ``a\\_b``.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, replace
from typing import Callable

SCRIPT_SHARE = 0.72                  # a script's size, as a share of the text's
SUB_DROP = 0.25                      # how far a subscript drops and a superscript rises, in the text's size
SUP_RISE = 0.38
_SCRIPT_TEX = {"sub": r"\textsubscript", "sup": r"\textsuperscript"}
_HELVETICA = {0.222: "ijl", 0.278: " ftI.,:;/!", 0.333: "r()-", 0.5: "cksvxyzJ", 0.611: "FTZ", 0.667: "ABEKPSVXY",
              0.722: "CDHNRUw", 0.778: "GOQ", 0.833: "mM", 0.944: "W"}    # letter widths over the font size; others 0.556
_LETTER_WIDTH = {letter: width for width, letters in _HELVETICA.items() for letter in letters}

_MARKS = re.compile(r"""
    \\(?P<keep>[_^*{}\\])
  | (?<=\S)(?P<script>[_^])(?:\{(?P<long>[^{}]+)\}|(?P<one>[^\W_])(?![^\W_]))
  | (?<![^\W_])\*\*(?P<bold>\S(?:.*?\S)??)\*\*(?![^\W_])
  | (?<![^\W_*])\*(?P<italic>[^\s*](?:[^*]*?[^\s*])?)\*(?![^\W_*])
""", re.X)


@dataclass(frozen=True)
class Run:
    """A piece of a label with one look. ``script`` is ``"sub"``, ``"sup"`` or empty."""

    text: str
    script: str = ""
    italic: bool = False
    bold: bool = False


def runs(text: str, look: Run = Run("")) -> list[Run]:
    """The runs of ``text``, each next to the run with another look. ``look`` is what the text sits inside."""

    out: list[Run] = []

    def add(words: str) -> None:
        if out and replace(out[-1], text="") == look:
            out[-1] = replace(look, text=out[-1].text + words)
        elif words:
            out.append(replace(look, text=words))

    at = 0
    for found in _MARKS.finditer(text):
        add(text[at:found.start()])
        at = found.end()
        if found["keep"]:
            add(found["keep"])
        elif found["script"]:
            inner = replace(look, script="sub" if found["script"] == "_" else "sup")
            out += runs(found["long"] or found["one"], inner)
        else:
            out += runs(found["italic"] or found["bold"], replace(look, italic=look.italic or bool(found["italic"]),
                                                                  bold=look.bold or bool(found["bold"])))
    add(text[at:])
    return out


def plain(text: str) -> str:
    """The letters of ``text`` as they print, with no markup."""

    return "".join(run.text for run in runs(text))


def has_markup(text: str) -> bool:
    return runs(text) != ([Run(text)] if text else [])


def text_width(text: str, size: float) -> float:
    """The printed width of ``text`` in Helvetica at font size ``size``, its scripts at their own size."""

    return size * sum(sum(_LETTER_WIDTH.get(letter, 0.556) for letter in run.text) * (SCRIPT_SHARE if run.script else 1.0)
                      for run in runs(text))


def svg_spans(text: str, size: float) -> str:
    """What goes inside an SVG ``<text>`` of font size ``size``: plain text, or ``<tspan>`` runs."""

    out, height = [], 0.0
    for run in runs(text):
        wanted = {"sub": SUB_DROP * size, "sup": -SUP_RISE * size}.get(run.script, 0.0)
        look = [f'dy="{wanted - height:.3g}"'] if wanted != height else []
        height = wanted
        if run.script:
            look.append(f'font-size="{SCRIPT_SHARE * size:.3g}"')
        if run.italic:
            look.append('font-style="oblique"')                  # cairo finds Helvetica's slant only under this name
        if run.bold:
            look.append('font-weight="bold"')
        words = html.escape(run.text)
        out.append(f'<tspan {" ".join(look)}>{words}</tspan>' if look else words)
    return "".join(out)


def svg_text(text: str, size: float, x: float, y: float, anchor: str = "start", look: str = "") -> str:
    """A whole ``<text>`` element. Writers differ on an anchor over several runs (cairosvg anchors each run by itself,
    so the runs pile up), so it starts at an x worked out from the letter widths and has no anchor."""

    start = x - {"middle": 0.5, "end": 1.0}.get(anchor, 0.0) * text_width(text, size)
    return f'<text x="{start:.3f}" y="{y}" font-size="{size}" {look}>{svg_spans(text, size)}</text>'


def latex(text: str, escape: Callable[[str], str]) -> str:
    """``text`` for LaTeX, with ``escape`` applied to the words of each run."""

    out = []
    for run in runs(text):
        words = escape(run.text)
        if run.script:
            words = f"{_SCRIPT_TEX[run.script]}{{{words}}}"
        if run.italic:
            words = f"\\textit{{{words}}}"
        if run.bold:
            words = f"\\textbf{{{words}}}"
        out.append(words)
    return "".join(out)

"""Record the sections of the stacks bundled before the open stacks: the golden data of test_old_sections_are_unchanged.

Run it once on the base commit, before any change to the section engine, from the checkout root:

    PYTHONPATH=. python tests/fixtures/xsection/record_old_sections.py tests/fixtures/xsection/old_sections.json

The test imports this file, so the sections and their fingerprints come from the same code at both ends.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import tempfile
from pathlib import Path

# The seven stacks bundled before the open stacks, each with its core layer. An explicit list: new stacks never enter.
STACKS = {
    "cornerstone_si500": (3, 0),
    "cornerstone_sin300": (203, 0),
    "gdsfactory_generic": (1, 0),
    "siepic_ebeam": (1, 0),
    "siepic_ebeam_si": (1, 0),
    "siepic_ebeam_si_nominal_metal": (1, 0),
    "siepic_ebeam_sin": (4, 0),
}
CUTS = ("core", "pyramid")
FIGURE = {"width_mm": 89, "font_pt": 7}
_TEXT = re.compile(r"<text\b([^>]*)>(.*?)</text>", re.S)
_ATTR = re.compile(r'([\w:-]+)="([^"]*)"')
_RUN = re.compile(r"<tspan\b([^>]*)>(.*?)</tspan>|([^<]+)", re.S)
_SHARE = {"middle": 0.5, "end": 1.0}


def pyramid_layers(stack: str) -> list[list[int]]:
    """The visible layers of ``stack``, in file order."""

    from optodraw.gds.parsers import load_layer_stack

    return [[int(spec[0]), int(spec[1])] for spec, style in load_layer_stack(stack).styles.items()
            if style.get("visible") is not False]


def section(stack: str, cut: str, layers: list[list[int]] | None = None):
    """Cut ``core``: the core guide 0.5 um wide. Cut ``pyramid``: one rectangle per layer of ``layers``, centred on
    the cut, each 2 um narrower than the one before, and a window 1 um wider than the widest on each side."""

    import gdstk

    from optodraw.gds.xsection import cross_section, stack_section

    if cut == "core":
        return stack_section(stack, STACKS[stack], width=0.5)
    widest = 2.0 * len(layers) + 1.0
    reach = widest / 2.0 + 2.0
    library = gdstk.Library()
    cell = library.new_cell("pyramid")
    for index, (layer, datatype) in enumerate(layers):
        half = widest / 2.0 - index
        cell.add(gdstk.rectangle((-5.0, -half), (5.0, half), layer=layer, datatype=datatype))
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "pyramid.gds"
        library.write_gds(path)
        return cross_section(path, stack, ((0.0, -reach), (0.0, reach)), window=(1.0, 2.0 * reach - 1.0))


def _width(inner: str, size: float) -> float:
    """The printed width of a text element's runs; a run with a font size of its own is a script."""

    from optodraw.core.markup import SCRIPT_SHARE, text_width

    total = 0.0
    for head, words, bare in _RUN.findall(inner):
        letters = re.sub(r"([\\_^*{}])", r"\\\1", html.unescape(words or bare))
        total += (SCRIPT_SHARE if "font-size" in head else 1.0) * text_width(letters, size)
    return total


def fingerprint(xs, anchors: tuple[str, ...] | list[str] = ()) -> dict:
    """The hash of each region in order, the hash of the figure with every text removed, and each text as printed
    with its anchor point (mm). A text set from its start with no text-anchor (a label with a script) is placed
    by ``anchors``: the anchors the old figure gave its texts, in turn."""

    from optodraw.core.markup import plain

    svg = xs.svg(**FIGURE)
    labels = []
    for index, (head, inner) in enumerate(_TEXT.findall(svg)):
        attrs = dict(_ATTR.findall(head))
        anchor = attrs.get("text-anchor") or (anchors[index] if index < len(anchors) else "start")
        x = float(attrs["x"])
        if "text-anchor" not in attrs:
            x += _SHARE.get(anchor, 0.0) * _width(inner, float(attrs["font-size"]))
        words = html.unescape(re.sub(r"<[^>]+>", "", inner))
        labels.append([plain(words), anchor, round(x, 3), round(float(attrs["y"]), 3)])
    return {"regions": [[name, hashlib.sha256(geometry.wkb).hexdigest()] for name, geometry in xs.regions.items()],
            "art": hashlib.sha256(_TEXT.sub("", svg).encode("utf-8")).hexdigest(),
            "labels": labels}


def main(out: str) -> None:
    golden = {}
    for stack in STACKS:
        for cut in CUTS:
            layers = pyramid_layers(stack) if cut == "pyramid" else None
            golden[f"{stack}/{cut}"] = {"layers": layers, **fingerprint(section(stack, cut, layers))}
    Path(out).write_text(json.dumps(golden, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: record_old_sections.py <out.json>")
    main(sys.argv[1])

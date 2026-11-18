"""Draw every part of the catalog on review sheets: one sheet for each family.

A sheet shows what optodraw has, at a glance: the 2D drawing of each part with
its name and its ports, and the 1D symbols of the symbol library. A part that
is large in a layout (an AWG, a weight bank) is scaled down to its cell, so
every part fits on the sheet.

    python scripts/make_component_sheets.py                  # into build/sheets/
    python scripts/make_component_sheets.py --out my_folder
    python scripts/make_component_sheets.py --list           # the families and their parts

Needs cairosvg and Pillow (the ``gif`` extra). Nothing here is shipped.
"""

from __future__ import annotations

import argparse
import io
import re
import warnings
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "build" / "sheets"

# In the catalog, but not a part to draw: light paths, routes, the grid, and the
# wrappers that draw a file the user supplies.
NOT_PARTS = {"Beam", "Route", "Grid", "CustomModel", "GDSModel"}

FAMILIES = {
    "2d_on_chip": ("On-chip parts", lambda spec: spec.platform == "on_chip" and spec.category == "on_chip"),
    "2d_electronics": ("Electronics and packaging", lambda spec: spec.category == "electronics"),
    "2d_free_space": ("Free-space and fibre optics", lambda spec: spec.category == "optics"),
    "2d_instruments": ("Instruments, sources, detectors, samples",
                       lambda spec: spec.category in {"instruments", "devices", "samples", "misc"}),
}

CELL_W, CELL_H = 300, 190            # the room for one drawing, pixels
LABEL_H = 46                         # the name and the ports under it
COLUMNS = 6
MARGIN = 24


def families() -> dict[str, tuple[str, list[str]]]:
    """Each sheet: its title and the catalog names on it, sorted."""

    import optodraw  # noqa: F401  (fills the registry)
    from optodraw.registry import component_registry

    catalog = component_registry()
    sheets = {}
    for key, (title, wanted) in FAMILIES.items():
        names = sorted(name for name, spec in catalog.items() if name not in NOT_PARTS and wanted(spec))
        sheets[key] = (title, names)
    return sheets


def _font(size: int):
    from PIL import ImageFont

    for path in ("/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _thumbnail(name: str):
    """The 2D drawing of one default part, scaled to fit a cell. None if it cannot be drawn."""

    import cairosvg
    from PIL import Image

    from optodraw.registry import build_component

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        part = build_component(name)
        part.label = ""                                    # the sheet prints the name itself
        svg = part.preview_scene(padding=6.0).render_svg().as_svg()
        ports = " ".join(part.ports())
    size = re.search(r'<svg[^>]*\swidth="([\d.]+)"[^>]*\sheight="([\d.]+)"', svg)
    width, height = (float(size.group(1)), float(size.group(2))) if size else (CELL_W, CELL_H)
    scale = min(CELL_W / width, CELL_H / height) * 2.0     # drawn at twice the size, then reduced: clean edges
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=max(int(width * scale), 1),
                           output_height=max(int(height * scale), 1), background_color="white")
    image = Image.open(io.BytesIO(png)).convert("RGB")
    image.thumbnail((CELL_W, CELL_H), Image.LANCZOS)
    return image, ports


def write_sheet_2d(title: str, names: list[str], target: Path) -> tuple[int, list[str]]:
    """Write one PNG sheet. Return how many parts it shows and the names that could not be drawn."""

    from PIL import Image, ImageDraw

    rows = (len(names) + COLUMNS - 1) // COLUMNS
    sheet = Image.new("RGB", (2 * MARGIN + COLUMNS * CELL_W, 70 + rows * (CELL_H + LABEL_H) + MARGIN), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((MARGIN, 20), f"{title}: {len(names)} parts, 2D", fill="black", font=_font(26))
    name_font, port_font = _font(15), _font(11)
    failed = []
    for index, name in enumerate(names):
        x = MARGIN + (index % COLUMNS) * CELL_W
        y = 70 + (index // COLUMNS) * (CELL_H + LABEL_H)
        try:
            image, ports = _thumbnail(name)
        except Exception as error:                         # a part that cannot draw is news: show it, go on
            failed.append(name)
            draw.text((x + 8, y + CELL_H // 2), f"cannot draw: {type(error).__name__}", fill="#b00020", font=port_font)
            ports = ""
        else:
            sheet.paste(image, (x + (CELL_W - image.width) // 2, y + (CELL_H - image.height) // 2))
        draw.text((x + 8, y + CELL_H + 4), name, fill="black", font=name_font)
        if len(ports) > 46:
            ports = ports[:44] + " ..."
        draw.text((x + 8, y + CELL_H + 24), ports, fill="#666666", font=port_font)
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target)
    return len(names) - len(failed), failed


def write_sheet_1d(target: Path) -> int:
    """The sheet of the 1D symbol library, as SVG and PNG. Return the number of symbols."""

    import json

    import cairosvg

    from optodraw.symbols import build

    target.parent.mkdir(parents=True, exist_ok=True)
    build.write_sheet(build.HERE, target.with_suffix(".svg"))
    cairosvg.svg2png(url=str(target.with_suffix(".svg")), write_to=str(target), output_width=2600)
    return len(json.loads((build.HERE / "symbols.json").read_text(encoding="utf-8"))["symbols"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(OUT), help="folder for the sheets")
    parser.add_argument("--list", action="store_true", help="print the families and stop")
    options = parser.parse_args(argv)
    sheets = families()
    if options.list:
        for key, (title, names) in sheets.items():
            print(f"{key}: {title} ({len(names)})\n  " + ", ".join(names))
        return 0
    out = Path(options.out)
    for key, (title, names) in sheets.items():
        drawn, failed = write_sheet_2d(title, names, out / f"{key}.png")
        print(f"{out / (key + '.png')}: {drawn} parts" + (f"; could not draw {failed}" if failed else ""))
    print(f"{out / '1d_symbols.png'}: {write_sheet_1d(out / '1d_symbols.png')} symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

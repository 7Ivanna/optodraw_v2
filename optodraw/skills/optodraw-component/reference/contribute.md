# A 1D symbol of your own, and a part for optodraw itself

## A 1D symbol

A symbol is a TikZ `pic` that marks each port with `\odport`, plus a table row
that ties it to your class. Build it once into a folder and register the
folder. It needs LaTeX and dvisvgm; `tests/test_symbols_user_library.py` runs
this path in the optodraw suite.

```python
# not run: needs LaTeX and dvisvgm
from pathlib import Path

from optodraw import symbols
from optodraw.symbols import build

Path("my_symbols.tex").write_text(r"""
\tikzset{pics/od shadeplate/.default={}, pics/od shadeplate/.style={code={
  \pgfkeys{/od/.cd,#1}\gdef\odportlist{}
  \draw[od el, fill=gray!40] (-0.15,-0.5) rectangle (0.15,0.5);
  \odport[free_space]{in}{-0.15,0}\odport[free_space]{out}{0.15,0}
}}}
""")
Path("my_symbols.toml").write_text('[[variant]]\nsymbol = "shadeplate"\ncomponent = "my_parts:ShadePlate"\n')
build.main(["--tex", "my_symbols.tex", "--table", "my_symbols.toml", "--out", "my_symbol_lib",
            "--sheet", "my_symbols_sheet.svg"])
symbols.add_library("my_symbol_lib")        # lookup(part) now finds the exact symbol
```

The `component` field is `module:Class`, so the class must live in an
importable module (here `my_parts.py`). A symbol is a real line drawing in
black on white: a labeled box is not a symbol. Look at the contact sheet the
build writes before you use the symbol. Without LaTeX, give an SVG part a
`symbol_1d=` SVG instead.

## Contribute a part to optodraw

1. Put the class in the matching file under `optodraw/components/` and export
   it from `optodraw/__init__.py`, `optodraw/components/__init__.py` and its
   subpackage `__init__.py`. A chip part has two sizes: its ports and stated
   geometry are physical, and it draws at a schematic size unless
   `render_physical=True`. Copy the `_draw_variant` pattern of
   `RacetrackResonator` so the ports follow the drawing in both modes.
2. Add its catalog entry to `_BUILTIN_METADATA` and its class to
   `_build_class_map()` in `optodraw/registry.py`.
3. Add a 1D symbol: a pic in `optodraw/symbols/tikz/`, a row in
   `optodraw/symbols/variants.toml`. Check your rows alone first: put them in
   a small TOML and run `python -m optodraw.symbols.build --table rows.toml
   --out <your own scratch folder> --sheet <scratch>/sheet.svg`, then look at
   the sheet. Run the full `python -m optodraw.symbols.build` once at the end:
   it rewrites the whole library (about 12 minutes). The 2D art is this pic
   fitted to the part's ports, so put each port where the pic draws it, in
   units of the part's size (`EIC.PLAN`, `SMU.JACKS`): else a wire or a beam
   ends in the air. A thin plate may carry a beam stub past its port.
4. Give it an animation behaviour in `optodraw/animation_engine/behaviours/`
   with `@register("YourPart")`, or an `animation_behaviour()` method.
5. Run `pytest tests/test_registry_checklist.py tests/test_free_space_parts_3d.py
   tests/test_port_art.py`: every part builds, renders, round-trips, has no
   loose solids, stands on its post and meets its wires and beams in 2D.
6. Look at the part in 2D, 1D and 3D, and say what you looked at.

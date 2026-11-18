"""Build the 1D symbols: one TikZ pic becomes one SVG file and its ports.

Run:  python -m optodraw.symbols.build
      python -m optodraw.symbols.build --tex my.tex --table my.toml --out my_symbols/

Needs ``latex`` and ``dvisvgm`` (TeX Live). The result is ``<out>/svg/<slug>.svg``
and ``<out>/symbols.json``. A row of the table that names a component class is
checked: the symbol's port names and kinds must equal the component's.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
TIKZ_DIR = HERE / "tikz"
BORDER_PT = 2.0                  # standalone border, TeX points
PT_TO_BP = 72.0 / 72.27          # TeX point -> SVG point (1/72 inch)


class SymbolBuildError(RuntimeError):
    """LaTeX or dvisvgm failed, or a symbol does not agree with its component."""


def library_files(extra: tuple[str | Path, ...] = ()) -> list[Path]:
    """The TikZ sources in load order: the core, the family files, then ``extra``."""

    families = sorted(path for path in TIKZ_DIR.glob("od-*.tex") if path.name != "od-core.tex")
    return [TIKZ_DIR / "od-core.tex", *families, *(Path(path) for path in extra)]


def fix_sides(symbol: str, params: dict[str, Any], ports: dict[str, dict[str, Any]]) -> None:
    """Ports whose side their place does not tell: set it. A side is otherwise the edge a port lies nearest, in
    proportion to the box, and a corner port of a tall symbol then reads as top or bottom."""

    if symbol == "periscope" and params.get("view") != "top":
        # Face ports need explicit directions: their position is no longer a beam stub.
        ports["in"]["side"] = "left"
        ports["out"]["side"] = "right"
    if symbol in ("knifeedge", "slm") or (symbol == "sample" and not params.get("kind")):
        # The beam crosses these off the middle of their box: at the tip of the blade, between the clips of a chip,
        # on the panel of an SLM whose flex cable widens the box.
        ports["in"]["side"] = "left"
        ports["out"]["side"] = "right"
    if symbol == "detector" and params.get("view") != "top":
        # The beam meets the diode's left edge, right of the middle of a box the light arrows widen to the left.
        ports["in"]["side"] = "left"
    if symbol == "flipmirror" and params.get("view") != "top":
        # The outline of the place it flips to makes the box tall: the beam still meets the face, as on a mirror.
        ports["io"]["side"] = "left"
        ports["pass"]["side"] = "right"
    if symbol == "coupledring":                            # the buses run left to right, however tall the stack
        for name, side in (("o1", "left"), ("o3", "left"), ("o2", "right"), ("o4", "right")):
            if name in ports:
                ports[name]["side"] = side


def source_hash(files: list[Path], table_text: str = "") -> str:
    """One hash over the TikZ sources and the variant table."""

    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))      # a Windows checkout has CRLF
    digest.update(table_text.encode())
    return digest.hexdigest()


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def keys(params: dict[str, Any]) -> str:
    """The parameters as a TikZ key list, for ``od <symbol>={...}``."""

    return ", ".join(key if value is True else f"{key}={_value(value)}" for key, value in sorted(params.items()))


def slug(symbol: str, params: dict[str, Any]) -> str:
    """The file and lookup name of one variant. Key order and 2 vs 2.0 do not matter."""

    parts = []
    for key, value in sorted(params.items()):
        if value is False:
            continue
        tail = "" if value is True else _value(value)
        parts.append(re.sub(r"[^A-Za-z0-9.]", "", f"{key}{tail}"))
    name = re.sub(r"[^A-Za-z0-9]", "", symbol)
    return f"{name}__{'_'.join(parts)}" if parts else name


def latex_available() -> bool:
    return shutil.which("latex") is not None and shutil.which("dvisvgm") is not None


def _run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise SymbolBuildError(f"{command[0]} failed:\n{result.stdout[-1500:]}\n{result.stderr[-400:]}")


def _pt(value: str) -> float:
    return float(value.replace("pt", ""))


def _unique_ids(text: str, prefix: str) -> str:
    """Give every id in an SVG body a prefix, and every reference to it, so symbols can share a page."""

    for old in set(re.findall(r"\sid='([^']+)'", text)):
        new = f"{prefix}-{old}"
        text = (text.replace(f"id='{old}'", f"id='{new}'").replace(f"url(#{old})", f"url(#{new})")
                .replace(f"'#{old}'", f"'#{new}'"))
    return text


def compile_symbol(
    symbol: str,
    params: dict[str, Any],
    out_dir: str | Path,
    tex_files: list[Path] | None = None,
) -> dict[str, Any]:
    """Compile one variant. Write ``<out_dir>/svg/<slug>.svg`` and return its table entry."""

    name = slug(symbol, params)
    files = tex_files or library_files()
    svg_dir = Path(out_dir) / "svg"
    svg_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for path in files:                      # copies: \input then needs no path, so spaces are safe
            shutil.copy(path, work / path.name)
        inputs = "".join(f"\\input{{{path.stem}}}\n" for path in files)

        def run(look: str, frame: str) -> tuple[str, list[list[str]]]:
            (work / "s.tex").write_text(
                "\\documentclass[dvisvgm,tikz,border=%gpt]{standalone}\n" % BORDER_PT
                + inputs
                + "\\begin{document}\n\\immediate\\openout\\odout=\\jobname.ports\n" + look + "\\begin{tikzpicture}\n"
                + f"\\pic (s) at (0,0) {{od {symbol}={{{keys(params)}}}}};\n"
                + "\\odwriteports{s}\\odwritebbox\n" + frame + "\\end{tikzpicture}\n"
                + "\\immediate\\closeout\\odout\n\\end{document}\n",
                encoding="utf-8",
            )
            # TikZ's own SVG driver through DVI: strokes stay strokes, and no clip ids.
            _run(["latex", "-interaction=nonstopmode", "-halt-on-error", "s.tex"], work)
            _run(["dvisvgm", "--no-fonts", "--bbox=papersize", "-o", "s.svg", "s.dvi"], work)
            return (work / "s.svg").read_text(encoding="utf-8"), \
                [line.split() for line in (work / "s.ports").read_text(encoding="utf-8").splitlines()]

        raw, rows = run("", "")
        corner = {row[0]: (row[1], row[2]) for row in rows if row[0] in ("sw", "ne")}
        # The 2D look: the same pic painted. Its frame is held to the 1D frame (a cast shadow
        # may reach past it), so the ports and the origin of the entry serve both looks.
        raw2d, _ = run("\\odtwodlook\n", "\\pgfresetboundingbox\\path ({},{}) rectangle ({},{});\n".format(
            *corner["sw"], *corner["ne"]))

    def write(text: str, file_name: str) -> tuple[float, float, float, float]:
        box = re.search(r"viewBox='([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)'", text)
        body = re.search(r"<svg[^>]*>(.*)</svg>", text, re.S)
        if box is None or body is None:
            raise SymbolBuildError(f"{name}: dvisvgm wrote an SVG this build cannot read")
        ox, oy, w, h = (float(value) for value in box.groups())
        if file_name.endswith(".2d.svg"):                      # gradients need their ids: make them this symbol's own
            inner = _unique_ids(body.group(1), f"od-{name}")
        else:
            inner = re.sub(r"\s+id='[^']*'", "", body.group(1))    # ids would collide when symbols share a page
        (svg_dir / file_name).write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}pt" height="{h}pt">'
            f'<g transform="translate({-ox},{-oy})">{inner}</g></svg>',
            encoding="utf-8",
        )
        return ox, oy, w, h

    ox, oy, width, height = write(raw, f"{name}.svg")
    write(raw2d, f"{name}.2d.svg")

    sw = next((_pt(row[1]), _pt(row[2])) for row in rows if row[0] == "sw")
    ne = next((_pt(row[1]), _pt(row[2])) for row in rows if row[0] == "ne")

    def to_svg(x: float, y: float) -> tuple[float, float]:   # TikZ frame (y up) -> SVG frame (y down)
        return (round((x - sw[0] + BORDER_PT) * PT_TO_BP, 3), round((ne[1] - y + BORDER_PT) * PT_TO_BP, 3))

    expected_width = (ne[0] - sw[0] + 2 * BORDER_PT) * PT_TO_BP
    if abs(width - expected_width) > 0.6:                     # the mapping above depends on this
        raise SymbolBuildError(f"{name}: SVG width {width} is not the picture width {expected_width:.2f}")
    ports, hub = {}, None
    for _, port_name, kind, x, y in (row for row in rows if row[0] == "port"):
        px, py = to_svg(_pt(x), _pt(y))
        if kind == "hub":                                     # where the beams of a splitter meet: not a port
            hub = [px, py]
        else:
            ports[port_name] = {"x": px, "y": py, "kind": kind}
    fix_sides(symbol, params, ports)
    entry = {
        "symbol": symbol,
        "params": params,
        "svg": f"{name}.svg",
        "svg2d": f"{name}.2d.svg",                            # the same pic painted, for the 2D view
        "width": width,
        "height": height,
        "origin": list(to_svg(0.0, 0.0)),                     # where the pic's (0,0) sits, for TikZ export
        "ports": ports,
    }
    if hub is not None:
        entry["hub"] = hub
    return entry


def load_table(path: str | Path) -> list[dict[str, Any]]:
    """Read the variant table: a list of ``[[variant]]`` rows."""

    try:
        import tomllib
    except ModuleNotFoundError:                               # Python 3.10
        try:
            import tomli as tomllib
        except ModuleNotFoundError as error:
            raise SymbolBuildError("Python 3.10 needs the package 'tomli' to read the variant table") from error
    rows = tomllib.loads(Path(path).read_text(encoding="utf-8")).get("variant", [])
    for row in rows:
        if "symbol" not in row:
            raise SymbolBuildError(f"a variant row has no symbol: {row}")
        row.setdefault("params", {})
    return rows


def component_ports(name: str, args: dict[str, Any]) -> dict[str, str]:
    """Port name -> kind of ``name(**args)``. ``name`` is a part of the optodraw catalog or ``module:Class``."""

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if ":" in name:
            module, _, attribute = name.partition(":")
            cls = getattr(importlib.import_module(module), attribute)
        else:
            optodraw = importlib.import_module("optodraw")
            cls = importlib.import_module("optodraw.registry").get_component_class(name) or getattr(optodraw, name)
        return {port_name: port.kind for port_name, port in cls(**args).ports().items()}


def port_mismatch(entry: dict[str, Any], name: str, args: dict[str, Any]) -> str | None:
    """Why the symbol does not fit the component, or None when it fits."""

    real = component_ports(name, args)
    mine = {port_name: port["kind"] for port_name, port in entry["ports"].items()}
    if mine == real:
        return None
    missing = sorted(set(real) - set(mine))
    extra = sorted(set(mine) - set(real))
    kinds = sorted(port_name for port_name in set(real) & set(mine) if real[port_name] != mine[port_name])
    return f"{entry['svg']} vs {name}({args}): missing {missing}, extra {extra}, wrong kind {kinds}"


def build(table_path: str | Path, out_dir: str | Path, extra_tex: tuple[str | Path, ...] = ()) -> dict[str, Any]:
    """Build every row of the table. Raise if a symbol does not fit its component."""

    table_path, out_dir = Path(table_path), Path(out_dir)
    files = library_files(extra_tex)
    rows = load_table(table_path)
    shutil.rmtree(out_dir / "svg", ignore_errors=True)
    symbols: dict[str, Any] = {}
    problems: list[str] = []
    for row in rows:
        entry = compile_symbol(row["symbol"], row["params"], out_dir, files)
        key = slug(row["symbol"], row["params"])
        if key in symbols:
            problems.append(f"{key}: two rows give the same variant")
        if row.get("component"):
            entry["component"] = row["component"]
            entry["args"] = row.get("args", {})
            entry["also"] = list(row.get("also", []))
            for name, args in [(entry["component"], entry["args"]), *((other, {}) for other in entry["also"])]:
                problem = port_mismatch(entry, name, args)
                if problem:
                    problems.append(problem)
        symbols[key] = entry
    if problems:
        raise SymbolBuildError("symbols that do not fit:\n  " + "\n  ".join(problems))
    library = {
        "version": 1,
        "source_hash": source_hash(files, table_path.read_text(encoding="utf-8")),
        "symbols": symbols,
    }
    (out_dir / "symbols.json").write_text(json.dumps(library, indent=1) + "\n", encoding="utf-8")
    return library


def write_sheet(library_dir: str | Path, target: str | Path, width: float = 620.0) -> Path:
    """One SVG with every symbol, its ports in red, and the parts it stands for: the sheet to review by eye."""

    library_dir, target = Path(library_dir), Path(target)
    symbols = json.loads((library_dir / "symbols.json").read_text(encoding="utf-8"))["symbols"]
    cells, x, y, row_height = [], 12.0, 14.0, 0.0
    for name, entry in symbols.items():
        if entry.get("component"):
            args = ", ".join(f"{key}={value}" for key, value in entry.get("args", {}).items())
            lines = [entry["component"] + (f" ({args})" if args else ""), *entry.get("also", [])]
        else:
            lines = ["1D only", keys(entry["params"]) or entry["symbol"]]
        cell_width = max(entry["width"], 2.5 * max(len(line) for line in lines))
        if x + cell_width > width:
            x, y, row_height = 12.0, y + row_height + 14.0 + 7.0 * 2, 0.0
        text = (library_dir / "svg" / entry["svg"]).read_text(encoding="utf-8")
        inner = re.search(r"<svg[^>]*>(.*)</svg>", text, re.S).group(1)
        marks = "".join(
            f'<circle cx="{port["x"]}" cy="{port["y"]}" r="0.8" fill="#d00"/>'
            f'<text x="{port["x"] + 1.5}" y="{port["y"] - 1.5}" font-size="3.4" '
            f'font-family="Helvetica" fill="#d00">{port_name}</text>'
            for port_name, port in entry["ports"].items()
        )
        caption = "".join(
            f'<text x="0" y="{entry["height"] + 8 + 6 * index}" font-size="4.6" font-family="Helvetica" '
            f'fill="{"#000" if entry.get("component") else "#777"}">{line}</text>'
            for index, line in enumerate(lines)
        )
        cells.append(f'<g transform="translate({x},{y})">{inner}{marks}{caption}</g>')
        x += cell_width + 22.0
        row_height = max(row_height, entry["height"])
    height = y + row_height + 26.0
    target.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}pt" height="{height}pt"><rect width="100%" height="100%" fill="white"/>'
        f'{"".join(cells)}</svg>',
        encoding="utf-8",
    )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m optodraw.symbols.build", description=__doc__.splitlines()[0])
    parser.add_argument("--table", default=str(HERE / "variants.toml"), help="variant table (TOML)")
    parser.add_argument("--out", default=str(HERE), help="library folder: gets svg/ and symbols.json")
    parser.add_argument("--tex", action="append", default=[], help="an extra TikZ file with your own pics")
    parser.add_argument("--sheet", help="also write a review sheet (SVG) to this path")
    options = parser.parse_args(argv)
    if not latex_available():
        print("The build needs 'latex' and 'dvisvgm' on the PATH (TeX Live).", file=sys.stderr)
        return 2
    try:
        library = build(options.table, options.out, tuple(options.tex))
    except SymbolBuildError as error:
        print(error, file=sys.stderr)
        return 1
    symbols = library["symbols"]
    checked = sum(1 for entry in symbols.values() if entry.get("component"))
    print(f"{len(symbols)} variants built; {checked} checked against a component; "
          f"{len(symbols) - checked} are 1D only")
    if options.sheet:
        print("sheet:", write_sheet(options.out, options.sheet))
    return 0


if __name__ == "__main__":
    sys.exit(main())

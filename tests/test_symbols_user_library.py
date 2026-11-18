"""The documented path for a user's own symbol (docs/content/guides/your-own-parts.md) works end to end."""

from __future__ import annotations

import sys
import textwrap

import pytest

from optodraw import symbols
from optodraw.symbols import build, lookup

PIC = r"""
\tikzset{pics/od attenuator/.default={}, pics/od attenuator/.style={code={
  \pgfkeys{/od/.cd,#1}\gdef\odportlist{}
  \draw[od wg] (-0.9,0) -- (0.9,0);
  \draw[od el, fill=white] (-0.4,-0.25) rectangle (0.4,0.25);
  \draw[od el] (-0.3,-0.2) -- (0.3,0.2);
  \odport{o1}{-0.9,0}\odport{o2}{0.9,0}
  \odport[electrical]{e1}{0,0.25}
}}}
"""

PART = """
from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Vec3


class Attenuator(Component):
    def ports(self):
        return {
            "o1": Port("o1", Vec3(-9, 0, 0), orientation_deg=180),
            "o2": Port("o2", Vec3(9, 0, 0), orientation_deg=0),
            "e1": Port("e1", Vec3(0, 3, 0), orientation_deg=90, kind="electrical"),
        }

    def geometry_2d(self):
        return {"type": "group", "children": []}
"""


@pytest.mark.skipif(not build.latex_available(), reason="needs latex and dvisvgm")
def test_a_user_adds_a_symbol_in_four_steps(tmp_path, monkeypatch):
    (tmp_path / "my.tex").write_text(PIC, encoding="utf-8")                      # 1. the pic
    (tmp_path / "my.toml").write_text(textwrap.dedent('''
        [[variant]]
        symbol = "attenuator"
        component = "my_parts_for_test:Attenuator"
    '''), encoding="utf-8")                                                      # 2. the table row
    (tmp_path / "my_parts_for_test.py").write_text(PART, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    out = tmp_path / "my_symbols"
    sheet = tmp_path / "sheet.svg"
    assert build.main(["--tex", str(tmp_path / "my.tex"), "--table", str(tmp_path / "my.toml"),
                       "--out", str(out), "--sheet", str(sheet)]) == 0            # 3. the build
    assert sheet.is_file() and (out / "symbols.json").is_file()

    import my_parts_for_test

    part = my_parts_for_test.Attenuator()
    assert lookup(part).source == "block"
    symbols.add_library(out)                                                     # 4. register
    try:
        symbol = lookup(part)
        assert (symbol.name, symbol.source, symbol.exact) == ("attenuator", "prebuilt", True)
        assert {name: port.kind for name, port in symbol.ports.items()} == {
            "o1": "optical", "o2": "optical", "e1": "electrical"}
    finally:
        symbols._LIBRARIES.remove(out)
        symbols._index.cache_clear()
        sys.modules.pop("my_parts_for_test", None)

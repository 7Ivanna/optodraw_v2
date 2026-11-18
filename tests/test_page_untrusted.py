"""A page file is data from anyone: loading and drawing one runs no tool, reads no file and keeps no script."""

from __future__ import annotations

import builtins
import json
import pathlib
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from optodraw import Inset
from optodraw.check import check_figure
from optodraw.figure.fragment import sanitized
from optodraw.figure.page import Page
from optodraw.schema import scene_from_spec

DOCS = Path(__file__).resolve().parents[1] / "docs" / "examples" / "figures"


def _hand_written(record):
    """A page spec written by hand: an inset ``box`` with ``record`` and no fragment, a callout that points into it
    and a zoom from it to a second inset."""

    spec = json.loads(json.dumps(Page(width_mm=120, height_mm=80, letters=False).to_spec()))
    spec["components"] = [
        {"type": "Inset", "id": "box", "label": "box", "center": [30, 40], "width": 40, "source": record},
        {"type": "Inset", "id": "far", "label": "far", "center": [90, 40], "width": 30,
         "source": {"kind": "EmptyBox", "height": None}},
        {"type": "Callout", "text": "c", "center": [60, 70],
         "target": {"anchor": "box", "point": [1, 1], "options": {}}},
        {"type": "ZoomLink", "small": "box", "region": [1, 1, 2, 2], "big": "far"},
    ]
    return spec


def _box(page):
    return next(n for n in page.walk() if isinstance(n, Inset) and n.label == "box")


def test_a_hand_written_file_record_reads_no_file(tmp_path, monkeypatch):
    secret = tmp_path / "secret.svg"
    secret.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><text>SECRET-WORDS</text></svg>',
                      encoding="utf-8")
    opened = []
    real_open, real_read = builtins.open, pathlib.Path.read_text
    monkeypatch.setattr(builtins, "open", lambda file, *a, **k: opened.append(str(file)) or real_open(file, *a, **k))
    monkeypatch.setattr(pathlib.Path, "read_text",
                        lambda self, *a, **k: opened.append(str(self)) or real_read(self, *a, **k))
    page = scene_from_spec(_hand_written({"kind": "SvgFile", "path": str(secret), "drop_text": []}))
    svg = page.svg()
    exported = page.export(tmp_path / "page", formats=("svg",))["svg"]
    assert str(secret) not in opened and "SECRET-WORDS" not in svg + real_read(exported)
    assert any('"box"' in f and "SvgFile" in f and "rebuild()" in f for f in check_figure(page))
    page.save(tmp_path / "again.json")                                  # it saves as it came: no drawing
    stored = next(c for c in json.loads(real_read(tmp_path / "again.json"))["components"] if c.get("id") == "box")
    assert "fragment" not in stored and stored["source"]["path"] == "secret.svg"     # beside the page file
    _box(page).rebuild()                                                # only a rebuild reads the file
    assert str(secret) in opened and "SECRET-WORDS" in page.svg()
    assert not any('"box"' in f and "rebuild()" in f for f in check_figure(page))


@pytest.mark.skipif(shutil.which("latex") is None or shutil.which("dvisvgm") is None, reason="needs latex, dvisvgm")
def test_a_tex_equation_opens_no_file_outside_its_folder(tmp_path):
    from optodraw.figure.sources import Equation

    outside = tmp_path / "outside.tex"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"latex failed.*Not reading.*openin_any = p"):
        Equation(f"\\input{{{outside}}}", tex=True).fragment(30.0, font_pt=7.0)
    assert Equation("E = mc^2", tex=True).fragment(30.0, font_pt=7.0).svg     # a plain formula still sets


UNSAFE = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 40 20" '
          'onload="alert(1)"><script>alert(2)</script><image href="x.png" onerror="alert(3)" width="4" height="4"/>'
          '<a xlink:href="javascript:alert(4)"><rect width="40" height="20" fill="#cccccc"/></a>'
          '<foreignObject><div onclick="alert(5)">x</div></foreignObject><use href="#keep"/>'
          '<image href="data:image/png;base64,AAAA" width="1" height="1"/></svg>')


@pytest.mark.parametrize("svg, want", [
    ('<svg><!--><image href=x onerror=alert(1)>--><rect/></svg>', "<svg><rect/></svg>"),
    ("<svg><desc><![CDATA[ ><img src=x onerror=alert(1)> ]]></desc></svg>", "<svg><desc></desc></svg>"),
    ("<svg><image/onerror=alert(1) href=data:image/png;base64,AAA></svg>",
     "<svg><image/  href=data:image/png;base64,AAA></svg>"),
    ('<svg><a xlink:href="&#106;avascript:alert(1)">x</a></svg>', "<svg><a  >x</a></svg>"),
    ('<svg><set attributeName="href" to="javascript:alert(1)"/><rect/></svg>', "<svg><rect/></svg>"),
    ("<svg><style><img src=x onerror=alert(1)></style></svg>", "<svg><style></style></svg>"),
    ('<svg><?xml-stylesheet href="x"?><SCRIPT>alert(1)</SCRIPT><svg:script>x</svg:script></svg>', "<svg></svg>"),
    ('<svg><rect ONCLICK="x" fill="red"/>< text></svg>', '<svg><rect   fill="red"/>&lt; text></svg>'),
    ('<svg><!-- a plain comment --><use href="http://host/x.svg#a"/></svg>',
     "<svg><!-- a plain comment --><use  /></svg>"),
    ('<svg><rect id="a<b" fill="red"/><g class=x<y></g></svg>', '<svg><rect   fill="red"/><g  ></g></svg>'),
    ('<svg><desc>a <g id="x"><rect/></g>b<style>p{}</style><title>t</title>c</desc><rect/></svg>',
     "<svg><desc>a bc</desc><rect/></svg>"),
    ("<svg><title>a<tspan>b</tspan>c<img src=x>d<br/>e</title><rect/></svg>", "<svg><title>acde</title><rect/></svg>"),
])
def test_the_sanitizer_reads_markup_as_a_browser_does(svg, want):
    assert sanitized(svg) == want


# ---- raw text: in an SVG desc or title (HTML integration points) a browser reads style and title as raw text ----

RAW_TEXT = (                                    # a "</style>" or "</title>" in a quoted value ends the element there
    '<desc><style><g id="</style><img src=x onerror=alert(8)>"/></style></desc>',
    '<title><style><g id="</style><img src=x onerror=alert(8)>"/></style></title>',
    '<desc><title><g id="</title><img src=x onerror=alert(8)>"/></title></desc>',
    '<desc><style/><g id="</style><img src=x onerror=alert(8)>"/></desc>',
    '</svg></svg></svg><style><g id="</style><img src=x onerror=alert(8)>"/></style>',   # out of every svg
)


def _svg_with(payload, n):
    """A fragment SVG that holds ``payload``, its handler set to ``alert(n)``."""

    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">' + payload.replace("alert(8)", f"alert({n})")
            + '<rect width="40" height="20"/></svg>')


def _served(svg):
    """The SVG that POST /api/scene serves for a page whose stored inset fragment is ``svg``. The editor's canvas sets
    it with innerHTML."""

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from optodraw.app.server import create_app

    page = Page(width_mm=100, height_mm=60, letters=False)
    page.add(Inset(None, center=(50, 30), width=40, label="box"))
    spec = json.loads(json.dumps(page.to_spec()))
    next(c for c in spec["components"] if c["type"] == "Inset")["fragment"].update(svg=svg, size_mm=[40.0, 20.0])
    response = TestClient(create_app()).post("/api/scene", json={"spec": spec})
    assert response.status_code == 200, response.text
    return response.json()["svg"]


class _Html(HTMLParser):
    """The start tags an HTML parser reads in a text. With ``style``, a style is raw text; with ``title``, a title is
    escapable raw text; either one also when it is written ``<style/>`` (HTML ignores that slash)."""

    def __init__(self, text, style, title):
        super().__init__(convert_charrefs=True)
        self.CDATA_CONTENT_ELEMENTS = tuple(t for t in HTMLParser.CDATA_CONTENT_ELEMENTS if style or t != "style")
        self.RCDATA_CONTENT_ELEMENTS = tuple(t for t in HTMLParser.RCDATA_CONTENT_ELEMENTS if title or t != "title")
        self.tags = []
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, tuple(key for key, _ in attrs)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in self.CDATA_CONTENT_ELEMENTS + self.RCDATA_CONTENT_ELEMENTS:
            self.set_cdata_mode(tag, escapable=tag in self.RCDATA_CONTENT_ELEMENTS)


def _runs(text):
    """The tags of ``text`` that an HTML parser reads as an img or that carry an ``on...`` handler. A browser reads
    style and title as raw text only where it reads HTML (in an SVG desc or title), so each is read both ways."""

    return sorted({tag for style in (True, False) for title in (True, False) for tag in _Html(text, style, title).tags
                   if tag[0] == "img" or any(key.startswith("on") for key in tag[1])})


# ---- the scoping step strips CSS comments in each style span: the text it joins is sanitized again ----

SCOPED = (                                      # with the comment out, "o" and "nerror" join to "onerror"
    '<style/><image href="data:image/png;base64,AAAA" width="4" height="4" o/**/nerror="alert(8)"/><style></style>',
    '<style><image href="data:image/png;base64,AAAA" width="4" height="4" o/**/nerror="alert(8)"/></style>',
    '<style:g><image href="data:image/png;base64,AAAA" width="4" height="4" o/**/nerror="alert(8)"/></style:g>'
    '</style>',
    '<style/><image href="data:image/png;base64,AAAA" width="4" height="4" o/*><g a="*/nerror="alert(8)"/>'
    '<style></style>',                          # the comment hides a whole tag
)


@pytest.mark.skipif(not hasattr(HTMLParser, "RCDATA_CONTENT_ELEMENTS"), reason="this parser has no escapable raw text")
@pytest.mark.parametrize("n, payload", list(enumerate(SCOPED, start=len(RAW_TEXT) + 1)))
def test_scoping_joins_no_handler(n, payload):
    svg = _svg_with(payload, n)
    assert _runs(re.sub(r"/\*.*?\*/", "", svg, flags=re.S))             # with the comments out, the check finds it
    assert _runs(_served(svg)) == []


def _chrome():
    """A Chrome or Chromium to run a page in, or None."""

    found = next((shutil.which(name) for name in ("google-chrome", "chromium", "chrome") if shutil.which(name)), None)
    mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return found or (str(mac) if mac.exists() else None)


def _handlers_run(shown, folder):
    """The handlers that run when headless Chrome sets each SVG of ``shown`` with innerHTML, as the canvas does. A
    Chrome that is found but does not start skips the test."""

    text = [json.dumps(svg).replace("<", "\\u003c") for svg in shown]     # no "</script>" ends the script early
    sets = "".join(f"document.getElementById('el{k}').innerHTML = {value};" for k, value in enumerate(text))
    page = folder / "canvas.html"
    page.write_text("<!doctype html><html><body><i id=loaded></i>"
                    + "".join(f"<div id=el{k}></div>" for k in range(len(shown)))
                    + "<pre id=out></pre><script>var hits = []; window.alert = function (n) { hits.push(n); };" + sets
                    + "setTimeout(function () { document.getElementById('out').textContent = 'HITS' + "
                      "JSON.stringify(hits); }, 500);</script></body></html>", encoding="utf-8")
    try:
        run = subprocess.run([_chrome(), "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                              f"--user-data-dir={folder / 'profile'}", "--virtual-time-budget=5000", "--dump-dom",
                              page.as_uri()], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        pytest.skip(f"Chrome does not start: {error}")
    if 'id="loaded"' not in run.stdout:                                 # no page came back: Chrome did not start
        pytest.skip(f"Chrome does not start: {run.stderr[-500:]}")
    hits = re.search(r"HITS(\[[^\]]*\])", run.stdout)
    assert hits, run.stderr[-2000:]
    return json.loads(hits.group(1))


def test_a_chrome_that_does_not_start_skips_the_browser_test(tmp_path, monkeypatch):
    broken = tmp_path / "chrome"
    broken.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    broken.chmod(0o755)
    for chrome in (broken, tmp_path / "gone"):                          # one that fails, one that is not there
        monkeypatch.setitem(globals(), "_chrome", lambda chrome=chrome: str(chrome))
        with pytest.raises(pytest.skip.Exception, match="Chrome does not start"):
            _handlers_run(["<svg></svg>"], tmp_path)


def _bench():
    from optodraw import Laser, Lens, Scene

    scene = Scene(width=100, height=60)
    scene.add(Laser(center=(10, 0)))
    scene.add(Lens(center=(40, 0), label="L1"))
    return scene

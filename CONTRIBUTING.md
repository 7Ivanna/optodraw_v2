# Contributing to optodraw

Thanks for looking. optodraw is maintained by one person alongside a PhD, so the
most useful contributions are small, specific, and easy to verify.

## The fastest way to help

**Tell me what you tried to draw and couldn't.** A missing component, an optic
that renders wrong, a layout the router mangles — those reports shape the tool
more than anything else. Open a
[component request](https://github.com/Acceluma/optodraw/issues/new?template=component_request.yml)
or a [bug report](https://github.com/Acceluma/optodraw/issues/new?template=bug_report.yml).
A screenshot and the scene JSON (Export → JSON) make it actionable immediately.

## Development setup

```bash
git clone https://github.com/Acceluma/optodraw
cd optodraw
pip install -e ".[dev,gui,gds]"
pytest -q                 # green before you start; leaves out the tests in tests/slow_tests.txt
ruff check optodraw tests
mypy optodraw/__init__.py optodraw/_compat.py
optodraw-gui              # the editor, at 127.0.0.1:8000
```

The package is pure Python; the Rust crate in `src/` is not wired up (see the README).
ruff is pinned `>=0.15,<0.16` on purpose.

## What a good change looks like

- **A test that fails first.** Most bugs here are geometric, and a test that
  pins the behaviour is what stops it coming back. Assert the *contract* (this
  mount sits behind the glass) rather than the numbers you happened to produce.
- **Look at the output.** Rendering is the product. A change that passes tests
  and looks wrong is not done — open the editor and check.
- **Real proportions for hardware.** Components are parameterised by aperture,
  so express dimensions as ratios of it, and note where the ratio came from.
  See [`cad/README.md`](cad/README.md): several parts were measured off CAD
  models built to catalogue dimensions, because eyeballing them went badly.
- **Match the surrounding style.** Comments explain *why*, not what.

## The images in the README and the docs

They are all generated, never hand-taken — a screenshot of a renderer that
changed the next week is a lie nobody notices:

```bash
python scripts/make_media.py      # every README image: figures, 3D, the light GIF (ffmpeg), the editor
python scripts/make_demo.py       # the demo recording (needs Playwright + ffmpeg)
```

Each one drives a throwaway workspace, so your own saved scenes are untouched.

## Before opening a pull request

```bash
OPTODRAW_FULL=1 pytest -q && ruff check optodraw tests && mypy optodraw/__init__.py optodraw/_compat.py && mkdocs build --strict
```

`OPTODRAW_FULL=1` runs every test, the slow ones too. The everyday `pytest -q` leaves out the tests that took 1 s or
more in a timed run; `tests/slow_tests.txt` lists them. When you add a slow test, or make one fast, list them again:
`OPTODRAW_FULL=1 pytest -q --durations=0 > timed.log`, then `python scripts/slow_tests.py timed.log`.

Say what you changed and how you checked it. If you added a component, include
a rendered image — 2D and 3D if it has both.

## Scope

optodraw is a **visualization and authoring tool**. Its physics is deliberately
presentation-grade: geometric ray envelopes rather than Gaussian modes, ideal
thin elements, stub effective indices. Contributions that improve how a setup
*reads* are always welcome. Contributions that turn it into a simulator are a
bigger conversation — open an issue first.

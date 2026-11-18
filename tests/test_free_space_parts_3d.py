"""The 3D shape of free-space parts: each one reads as the real part on a bench.

The local origin of a free-space part is the beam axis; x runs along the beam, y up, z across it.
"""

from __future__ import annotations



import optodraw


def _solids(node):
    if node.get("shape") == "group":
        for child in node.get("children", []):
            yield from _solids(child)
    else:
        yield node


def _boxes(node):
    """(x0, x1, y0, y1, z0, z1) of every box and upright cylinder that is not turned."""

    for s in _solids(node):
        if s["shape"] not in ("box", "cylinder") or any(s.get("rotation") or []):
            continue
        x, y, z = s.get("position") or [0.0, 0.0, 0.0]
        hx, hz = (s["width"] / 2, s["depth"] / 2) if s["shape"] == "box" else (s["radius"], s["radius"])
        yield (x - hx, x + hx, y - s["height"] / 2, y + s["height"] / 2, z - hz, z + hz)


def _inside(point, polygon):
    """Whether a point lies inside a polygon (even-odd rule)."""

    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


KINEMATIC = [optodraw.Mirror(), optodraw.ConcaveMirror(), optodraw.BiconvexMirror(), optodraw.BeamSplitter(),
             optodraw.PartialMirror(), optodraw.DichroicMirror(), optodraw.KinematicMount()]




def _luminance(hex_color):
    r, g, b = (int(hex_color.lstrip("#")[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


_COILS = {"PolarizationController", "FiberAmplifier", "FiberSpool", "Cryostat", "Sample", "VacuumChamber"}


def test_the_power_meter_console_symbol_shows_a_digital_reading():
    """The PM100D shows its reading on an LCD; the symbol drew an analogue needle."""

    from importlib.resources import files

    source = (files("optodraw.symbols") / "tikz" / "od-instruments.tex").read_text()
    pic = source[source.index("pics/od powermeter/.style"):]
    pic = pic[:pic.index("}}}")]
    assert "arc" not in pic and "rectangle" in pic.split("od screen", 1)[1]

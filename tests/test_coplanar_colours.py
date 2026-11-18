"""No catalog part puts two looks on one plane in 3D, and no on-chip layer leaves its stack level to avoid it.

Where two solids of a part have faces on one plane that face one way and overlap, the viewer z-fights. With two
colours, or one colour at two opacities, the part flickers there. The pairs come from the geometry
(``viewer_flat.coplanar``), so the test needs no Chrome. A pair of one look may stay: it does not flicker visibly.
A shared base counts as well as a shared top: a view from below with no chip base shows it, because every material
is drawn double-sided. The fix gives each patch of a plane one owner, by a cut in plan.

A lift off the plane removes a pair but moves the layer, and the stack outranks the drawing. So the second test
reads the solids the viewer draws for each on-chip part and checks that each one starts on a level of its part's
stack (``test_onchip_stack.py`` holds the same rule on the part's own tree).
"""

from __future__ import annotations

import pytest

pytest.importorskip("shapely")
pytest.importorskip("PIL")                      # viewer_flat reads its images with Pillow

import viewer_flat  # noqa: E402

from optodraw import Scene  # noqa: E402
from optodraw.registry import build_component, component_registry  # noqa: E402
from optodraw.renderers.vector3d_scene import scene_solids  # noqa: E402
from optodraw.renderers.vector3d_solids import Vector3DError  # noqa: E402

from sweep import sweep

_REGISTRY = component_registry()
# PhaseShifter is thermo-optic by default.
_VARIANTS: dict[str, list[dict[str, str]]] = {"MZM": [{"drive_style": "gsg"}],
                                               "PhaseShifter": [{"mechanism": "electro_optic"}]}
# Not process layers (as in test_onchip_stack.py): flip-chip dies, the die itself, and a preset group.
_NOT_ON_THE_STACK = {"TIA", "ADC", "DACDriver", "ChipSubstrate", "PresetWDMInput"}
_BUILDS = [(name, kwargs) for name in sorted(_REGISTRY) for kwargs in [{}, *_VARIANTS.get(name, [])]]
_ON_THE_STACK = [(name, kwargs) for name, kwargs in _BUILDS
                 if _REGISTRY[name].platform == "on_chip" and name not in _NOT_ON_THE_STACK]
_BONDED = {"indium_phosphide", "gallium_arsenide"}      # a III-V stack bonded above the silicon process
_ON_THE_CORE = {"germanium", "sio2", "gst"}              # GE starts on the core top (zmin 0.220); so do oxide and a GST film over it
_TOLERANCE = 1e-6                                        # world units; coplanar() rounds a plane to 1e-6


def _ids(builds: list[tuple[str, dict[str, str]]]) -> list[str]:
    return [f"{name}-{'-'.join(kwargs.values()) or 'default'}" for name, kwargs in builds]


def _alone(name: str, kwargs: dict[str, str]):
    """The part and the solids the viewer draws for it alone in a scene of its platform."""

    try:
        part = build_component(name, **kwargs)
    except TypeError:                      # a part that needs a source to build (CustomModel, GDSModel)
        pytest.skip(f"{name} needs a source to build")
    platform = _REGISTRY[name].platform
    scene = Scene(width=200, height=200, platform=platform if platform != "mixed" else "free_space")
    scene.add(part)
    try:
        return part, scene_solids(scene)
    except Vector3DError:                  # a part the vector view does not draw
        pytest.skip(f"the vector view does not draw {name}")


def _check_no_part_has_two_looks_on_one_plane(name, kwargs):
    # mutant: give the feet of _carry_handle (instruments.py) the grip's depth 2.4 again: Oscilloscope and OSA fail
    _, built = _alone(name, kwargs)
    solids = built.solids

    def look(solid):
        return f"{solid.look.preset or '?'} {solid.look.color} {solid.look.opacity:.2f}"

    pairs = sorted({f"{look(solids[a])} / {look(solids[b])}" for a, b in viewer_flat.coplanar(built, range(len(solids)))
                    if solids[a].look.color.lower() != solids[b].look.color.lower()
                    or abs(solids[a].look.opacity - solids[b].look.opacity) > 1e-6})
    assert not pairs, f"{name} {kwargs}: two looks on one plane, which the viewer z-fights: {pairs}"


def test_no_part_has_two_looks_on_one_plane():
    sweep(_check_no_part_has_two_looks_on_one_plane, _BUILDS)



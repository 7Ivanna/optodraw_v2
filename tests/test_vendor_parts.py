"""Vendor parts drawn to scale from the vendors' drawings: every part number builds, stands whole in 3D, keeps its
size and part number through a saved scene, and acts on light as the optodraw part it extends."""

from __future__ import annotations

import math

import pytest

from optodraw import Scene, check_part_3d
from optodraw.components.vendor import (
    FAMILIES,
    CatalogCageMount,
    CatalogCubeSplitter,
    CatalogLens,
    CatalogLensTube,
    CatalogNDFilter,
    CatalogWavePlate,
)
from optodraw.components.vendor.data import CAGE_MOUNTS, LENSES, TUBES
from optodraw.symbols import lookup

MM = 1 / 2.54
CASES = [(cls, part) for cls in FAMILIES for part in cls.TABLE]


@pytest.mark.parametrize(("cls", "part"), CASES, ids=[f"{c.__name__}-{p}" for c, p in CASES])
def test_every_vendor_part_builds_whole_with_its_symbol(cls, part):
    item = cls(part=part)
    assert item.part == part and item.label == part
    assert check_part_3d(item) == []
    symbol = lookup(item)
    assert symbol.exact and symbol.source == "prebuilt"


def test_an_unknown_part_number_names_the_known_ones():
    with pytest.raises(ValueError, match="SM1L10"):
        CatalogLensTube(part="SM1L99")


def test_a_vendor_part_keeps_its_part_number_through_a_saved_scene():
    scene = Scene()
    for cls in FAMILIES:
        scene.add(cls(center=(0, 0), part=list(cls.TABLE)[-1]))
    again = [n for n in Scene.from_spec(scene.to_spec()).walk() if hasattr(n, "TABLE")]
    assert [(type(n).__name__, n.part) for n in again] == [(c.__name__, list(c.TABLE)[-1]) for c in FAMILIES]


def test_sizes_come_from_the_drawings():
    tube = CatalogLensTube(part="SM1L10")
    assert tube.length == pytest.approx(29.2 * MM)                        # SM1L10 drawing: 29.2 mm overall
    assert CatalogLensTube(part="SM1L03").length == pytest.approx((0.30 * 25.4 + 3.8) * MM)
    plate = CatalogCageMount(part="CP33")
    assert plate.depth == pytest.approx(8.9 * MM)                         # CP33 drawing: 0.35" thick
    assert CAGE_MOUNTS["LCP33"]["rod_outer"] == 60.0
    cube = CatalogCubeSplitter(part="PBS122")
    assert cube.ports()["in"].center.x == pytest.approx(-12.7 * MM / 2)   # a 1/2" cube
    assert all(spec["length"] > 0 for spec in TUBES.values())


def test_a_lens_focuses_at_the_vendors_focal_length_and_shows_its_surfaces():
    lens = CatalogLens(part="45-806")                                     # Edmund 25 mm x 100 mm achromat
    assert lens.focal_length == pytest.approx(100.0 * MM)
    glass = [c for c in lens.geometry_3d()["children"] if c.get("role") == "glass element"]
    assert len(glass) == 2                                                # the doublet's two elements
    pcx = CatalogLens(part="67-562")
    assert len([c for c in pcx.geometry_3d()["children"] if c.get("role") == "glass element"]) == 1
    for spec in LENSES.values():
        assert spec["d"] > 0 and spec["efl"] > 0


def test_optics_keep_their_physics():
    quarter = CatalogWavePlate(part="WPQ10M-1550")
    assert quarter.retardance == pytest.approx(math.pi / 2) and quarter.design_wavelength_nm == 1550
    assert CatalogNDFilter(part="NE20A-B").optical_density == 2.0
    pbs = CatalogCubeSplitter(part="PBS255")
    assert pbs.physics_metadata()["polarization_selective"] is True
    npbs = CatalogCubeSplitter(part="BS030")
    assert npbs.split_ratio == (0.9, 0.1)


def test_a_part_added_from_the_palette_lands_where_you_look_and_clear_of_others():
    from optodraw.app.session import EditorSession

    session = EditorSession()
    session.load({"components": [{"type": "Breadboard", "id": "board", "center": [0, 0]},
                                  {"type": "Mirror", "id": "m", "center": [40, 20]}]})
    first = session.add_component("CatalogLens", {"near": [100, -30]})
    entry = next(c for c in session.spec["components"] if c["id"] == first)
    assert entry["center"] == [100.0, -30.0]                     # the middle of the view, which is free
    second = session.add_component("CatalogLens", {"near": [40, 20]})
    entries = {c["id"]: c for c in session.spec["components"]}
    spot = entries[second]["center"]
    lens, mirror = EditorSession._footprint(entries[second]), EditorSession._footprint(entries["m"])
    assert lens[2] <= mirror[0] or mirror[2] <= lens[0] or lens[3] <= mirror[1] or mirror[3] <= lens[1]  # not on it
    assert math.hypot(spot[0] - 40, spot[1] - 20) <= 20         # but only to the next free spot


def test_a_new_part_lands_clear_of_big_parts_and_on_the_grid():
    from optodraw.app.session import EditorSession

    session = EditorSession()
    session.load({"components": [{"type": "Breadboard", "id": "board", "center": [0, 0]},
                                  {"type": "CatalogRightAngleMount", "id": "kcb2", "part": "KCB2C", "center": [0, 0]}]})
    placed = [session.add_component("CatalogCageCube", {"near": [0, 0], "grid": 10}) for _ in range(3)]
    entries = {c["id"]: c for c in session.spec["components"]}
    boxes = [EditorSession._footprint(entries[i]) for i in ["kcb2", *placed]]
    for i, a in enumerate(boxes):                               # no two footprints overlap, the 76 mm mount's included
        for b in boxes[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
    for i in placed:                                            # each on the 10-unit snap grid
        assert all(v % 10 == 0 for v in entries[i]["center"])


def test_the_right_angle_mount_follows_its_drawing():
    from optodraw.components.vendor import CatalogRightAngleMount

    mount = CatalogRightAngleMount(part="KCB1C")
    roles = [s.get("role") for s in mount.geometry_3d()["children"]]
    assert roles.count("end") == 2 and roles.count("rod bore") == 8     # two solid ends, four bores a face
    assert {"pitch knob", "yaw knob", "Z actuator", "kinematic plate", "mirror"} <= set(roles)
    h = 48.3 * MM / 2
    tap = -h + 17.8 * MM                                                 # the post under the drawing's tap
    assert mount.geometry_3d()["post_at"] == pytest.approx([tap, -h, tap])


def test_the_attocube_breadboard_follows_its_drawing():
    from optodraw import Breadboard, Scene

    board = Breadboard(part="attocube 1011879-2")
    assert (board.length, board.width, board.thickness) == pytest.approx((500 * MM, 475 * MM, 10 * MM))
    taps, pockets, holes = board._drawn()
    assert len(taps) == 17 * 16 - 5 and len(pockets) == 18 * 17 - 4    # none crowd the Ø31 hole
    big = max(holes, key=lambda h: h[2])
    assert big[2] == pytest.approx(31 * MM / 2)
    assert big[0] == pytest.approx(0) and big[1] == pytest.approx(-(237.5 - 75) * MM)   # 75 mm from the near edge
    assert check_part_3d(board) == []
    again = next(n for n in Scene.from_spec(_one(board)).walk()
                 if type(n).__name__ == "Breadboard")
    assert again.part == board.part and again.length == pytest.approx(board.length)
    assert Breadboard().part == "custom" and "part" not in Breadboard().to_dict()


def _one(part):
    from optodraw import Scene

    scene = Scene()
    scene.add(part)
    return scene.to_spec()


def test_table_clamps_have_their_own_card_and_the_cl5_profile():
    from optodraw.app.palette_groups import palette_place
    from optodraw.catalog import component_catalog
    from optodraw.components.vendor import CatalogHardware, CatalogTableClamp

    assert set(CatalogTableClamp.TABLE) == {"CF125", "CL4", "CL5", "CL5A", "CL6", "CL8"}
    assert not set(CatalogTableClamp.TABLE) & set(CatalogHardware.TABLE)
    info = component_catalog()["CatalogTableClamp"]
    assert info["display_name"] == "Table Clamp"
    assert palette_place("CatalogTableClamp", info["category"]) == ("Free-space optics", "Mounts & hardware")
    body = next(s for s in CatalogTableClamp(part="CL5").geometry_3d()["children"] if s["role"] == "clamp body")
    xs = [x for x, _ in body["points"]]
    ys = [y for _, y in body["points"]]
    assert max(xs) - min(xs) == pytest.approx(50.8 * MM) and max(ys) == pytest.approx(17.3 * MM)
    assert body["height"] == pytest.approx(19.1 * MM)                  # 0.75" wide


def test_the_60_mm_and_rod_hung_cage_parts_follow_their_drawings():
    from optodraw.components.vendor import CatalogRightAngleMount

    kcb2 = CatalogRightAngleMount(part="KCB2C")
    assert kcb2.cage == 60 and kcb2.size.cube_half == pytest.approx(76.2 * MM / 2)     # a 60 mm cage block
    assert kcb2.size.rod_half == pytest.approx(30.0 * MM)
    plate = CatalogCageMount(part="LCP6S")
    assert plate.depth == pytest.approx(6.0 * MM) and plate.base_mount == "post"
    # the parts that hang on the cage rods stand on no post, and whole
    for part in ("LCP360R", "CDA1", "CPA1", "VRC2CPT", "VRC8CPT", "ERCPS", "ER8", "C30L24"):
        item = CatalogCageMount(part=part)
        assert item.base_mount == "none", part
    assert CatalogCageMount(part="ER8").depth == pytest.approx(203.2 * MM)              # 8" long
    roles = [s.get("role") for s in CatalogCageMount(part="VRC2CPT").geometry_3d()["children"]]
    assert "pinhole" in roles and "fluorescing disk" in roles


def test_a_size_set_by_hand_changes_the_part_and_only_that_size_is_saved():
    tube = CatalogLensTube(part="SM1L10", length_mm=40.0)
    assert tube.length == pytest.approx(40.0 * MM)
    assert tube.sizes_changed == {"length": 40.0}
    assert CatalogLensTube(part="SM1L10").length == pytest.approx(29.2 * MM)   # the drawing itself is untouched
    assert check_part_3d(tube) == []
    entry = tube.to_dict()
    assert entry["length_mm"] == 40.0 and "od_mm" not in entry
    again = next(n for n in Scene.from_spec(_scene_of(tube).to_spec()).walk()
                 if isinstance(n, CatalogLensTube))
    assert again.length == pytest.approx(40.0 * MM) and again.sizes_changed == {"length": 40.0}


def _scene_of(item):
    scene = Scene()
    scene.add(item)
    return scene


def test_every_size_of_a_part_is_named_and_filled_from_its_drawing():
    assert {"od_mm", "length_mm"} <= set(CatalogLensTube.size_names())
    assert CatalogLensTube.part_sizes("SM1L10")["length_mm"] == 29.2
    lens = next(iter(CatalogLens.TABLE))
    assert CatalogLens.part_sizes(lens)["r2_mm"] < 0                      # signed radii stay signed


def test_a_negative_or_unknown_size_is_refused():
    with pytest.raises(ValueError):
        CatalogLensTube(part="SM1L10", length_mm=-1.0)
    with pytest.raises(ValueError, match="length_mm"):
        CatalogLensTube(part="SM1L10", lenght_mm=10.0)


def test_a_lens_radius_can_change_sign():
    part = next(iter(CatalogLens.TABLE))
    lens = CatalogLens(part=part, r2_mm=40.0)
    assert lens.sizes_changed == {"r2": 40.0}
    assert check_part_3d(lens) == []


def test_the_editor_drops_hand_sizes_when_the_part_number_changes():
    pytest.importorskip("fastapi")
    from optodraw.app.session import EditorSession

    session = EditorSession()
    item = session.add_component("CatalogLensTube", {"part": "SM1L10"})
    session.update(item, {"length_mm": 40.0})
    entry = next(c for c in session.spec["components"] if c["id"] == item)
    assert entry["length_mm"] == 40.0
    session.update(item, {"length_mm": None})                             # clearing a size goes back to the drawing
    assert "length_mm" not in next(c for c in session.spec["components"] if c["id"] == item)
    session.update(item, {"length_mm": 40.0})
    session.update(item, {"part": "SM1L03"})
    entry = next(c for c in session.spec["components"] if c["id"] == item)
    assert entry["part"] == "SM1L03" and "length_mm" not in entry

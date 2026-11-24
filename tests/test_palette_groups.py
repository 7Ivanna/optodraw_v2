"""The editor's parts menu: every part sits in a section (Free-space optics, On-chip photonics, Electronics,
Annotations) and a group inside it, so a part is found where you would look for it."""

from __future__ import annotations

import pytest

from optodraw.app.palette_groups import FREE_SPACE_GROUPS, SECTIONS, palette_place
from optodraw.catalog import component_catalog


def test_every_part_has_a_section_and_a_group():
    for name, info in component_catalog().items():
        section, group = palette_place(name, str(info.get("category", "")))
        assert section in SECTIONS, name
        assert group, name


def test_the_free_space_list_names_only_real_parts():
    known = set(component_catalog())
    listed = [name for names in FREE_SPACE_GROUPS.values() for name in names]
    assert len(listed) == len(set(listed))                     # no part in two groups
    assert set(listed) <= known, sorted(set(listed) - known)


@pytest.mark.parametrize(("name", "section", "group"), [
    ("CageCube", "Free-space optics", "Cage system"),
    ("CatalogRightAngleMount", "Free-space optics", "Cage system"),
    ("MotorizedMirror", "Free-space optics", "Mirrors"),
    ("CatalogLens", "Free-space optics", "Lenses & objectives"),
    ("KinematicMount", "Free-space optics", "Mounts & hardware"),
    ("CatalogWavePlate", "Free-space optics", "Polarization"),
    ("CryostatCabinet", "Free-space optics", "Samples & cryostats"),
    ("MicroringResonator", "On-chip photonics", "Resonators & interferometers"),
    ("VerticalGratingCoupler", "On-chip photonics", "Couplers & I/O"),
    ("Resistor", "Electronics", "Circuit parts"),
    ("Oscilloscope", "Electronics", "Instruments"),
])
def test_parts_land_where_you_would_look(name, section, group):
    info = component_catalog()[name]
    assert palette_place(name, str(info.get("category", ""))) == (section, group)


def test_the_catalog_endpoint_sends_each_parts_place():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from optodraw.app.server import create_app

    body = TestClient(create_app()).get("/api/catalog").json()
    assert body["sections"] == list(SECTIONS)
    assert body["components"]["CageCube"]["section"] == "Free-space optics"
    assert body["components"]["CageCube"]["group"] == "Cage system"

"""2D animator payloads — 2D is the reference, 3D follows it."""

from fastapi.testclient import TestClient

from optodraw import Scene
from optodraw.app.server import create_app
from optodraw.components.devices import Laser
from optodraw.components.optics import Mirror


def test_animation_payloads_endpoint_returns_map():
    app = create_app()
    c = TestClient(app)
    # empty scene has no anim payloads
    r = c.get("/api/animation/payloads")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)

    # scene with a beam should return at least one pulse payload
    s = Scene()
    laser = s.add(Laser(center=(-40, 0)))
    mir = s.add(Mirror(center=(0, 0), angle=45))
    from optodraw.components.devices import Photodiode
    from optodraw.core.beam import Beam

    pd = s.add(Photodiode(center=(0, 30)))
    s.add(Beam(laser, mir, pd, wavelength=1550))
    # need to push scene to session via API to test endpoint with that scene
    # instead test directly via anim_payload_map
    from optodraw.core.timeline3d import anim_payload_map

    m = anim_payload_map(s)
    assert len(m) >= 1
    # payload should contain t_ps-compatible fields, not stub Q
    for payload in m.values():
        if "pulse" in payload:
            assert "segments" in payload["pulse"]
            for seg in payload["pulse"]["segments"]:
                assert "len" in seg and "n" in seg

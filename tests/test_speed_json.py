import json
import math

from optodraw.renderers.threejs_renderer import _json_script_safe


def test_script_json_is_compact_without_rounding():
    data = {"points": [[0.12345678901234567, 1.2345678901234567e-12, 1e20, -0.0]],
            "label": "keep spaces inside text", "custom": {"future": True}}
    encoded = _json_script_safe(data)
    assert len(encoded) < len(json.dumps(data))
    decoded = json.loads(encoded)
    assert decoded == data
    assert [x.hex() for x in decoded["points"][0]] == [x.hex() for x in data["points"][0]]
    assert math.copysign(1, decoded["points"][0][-1]) == -1


def test_compact_json_keeps_script_escaping_and_unknown_fields():
    data = {"svg": "</script>&\u2028\u2029", "part_definition": "custom-ref",
            "shape": {"type": "future_outline", "paths": ["M 0 0 C 1 2 3 4 5 6"]}}
    encoded = _json_script_safe(data, ensure_ascii=False)
    assert json.loads(encoded) == data
    assert not any(char in encoded for char in "<>&\u2028\u2029")

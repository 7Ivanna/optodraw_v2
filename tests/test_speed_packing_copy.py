"""Shared records retain values without repeatedly copying nested geometry."""

from copy import deepcopy

from optodraw.renderers import _scene_data


def test_shared_record_packing_copies_the_source_tree_once(monkeypatch):
    leaf = {"shape": "box", "width": 1.23456789012345, "height": -0.0,
            "material": {"color": "#111", "roughness": 0.123456789012345}}
    source = [{"position": [0, 0, 0], "geometry": {
        "shape": "group", "children": [leaf, leaf], "metadata": {"values": [1, 2]},
    }}] * 2
    original = deepcopy(source)
    calls = []

    def counted(value):
        calls.append(value)
        return deepcopy(value)

    monkeypatch.setattr(_scene_data, "deepcopy", counted)
    packed = _scene_data.pack_scene_data(source)
    assert len(calls) == 1
    assert _scene_data.expand_scene_data(packed) == original
    assert source == original
    assert len(packed["materials"]) == 1
    assert len(packed["geometries"]) == 2
    source[0]["geometry"]["metadata"]["values"].append(3)
    assert _scene_data.expand_scene_data(packed) == original
def test_equal_flat_records_encode_once(monkeypatch):
    """Repeated simple geometry must not repeat the canonical JSON work."""
    import optodraw.renderers._scene_data as module

    original = module.json.dumps
    calls = []

    def dumps(value, **kwargs):
        calls.append(value)
        return original(value, **kwargs)

    monkeypatch.setattr(module.json, "dumps", dumps)
    items = [
        {
            "id": str(index),
            "geometry": {
                "type": "box",
                "width": 2.0,
                "position": [0.0, 1.0, 2.0],
                "material": {"color": "#000000", "opacity": 1.0},
            },
        }
        for index in range(300)
    ]
    packet = module.pack_scene_data(items)
    assert len(calls) == 2
    assert len(packet["geometries"]) == 1
    assert len(packet["materials"]) == 1
    assert module.expand_scene_data(packet) == items


def test_flat_key_retains_numeric_json_distinctions():
    from optodraw.renderers._scene_data import expand_scene_data, pack_scene_data

    values = [False, 0, 0.0, -0.0, True, 1, 1.0]
    items = [{"geometry": {"type": "custom", "value": value}} for value in values]
    packet = pack_scene_data(items)
    assert len(packet["geometries"]) == len(values)
    import json

    assert json.dumps(expand_scene_data(packet)) == json.dumps(items)


def test_equal_nested_records_encode_once(monkeypatch):
    import sys
    import optodraw.renderers._scene_data as module
    original = module.json.dumps
    calls = []
    def dumps(value, **kwargs):
        calls.append(value)
        return original(value, **kwargs)
    monkeypatch.setattr(module.json, "dumps", dumps)
    items = [{"geometry": {"type": "extruded_polygon", "points": [[j*0.1, j*0.2] for j in range(80)],
                            "material": {"color": "black"}}} for _ in range(300)]
    packet = module.pack_scene_data(items)
    assert len(calls) == (2 if sys.version_info >= (3, 13) else 301)
    assert module.expand_scene_data(packet) == items


def test_opaque_records_do_not_run_pickle_hooks():
    from optodraw.renderers._scene_data import expand_scene_data, pack_scene_data
    class Description:
        def __str__(self):
            return "described geometry"
        def __reduce__(self):
            raise AssertionError("Packing must not execute pickle hooks")
    value = Description()
    items = [{"geometry": {"type": "custom", "metadata": value}}]
    import json
    packet = json.loads(json.dumps(pack_scene_data(items, copy_records=False), default=str))
    assert expand_scene_data(packet) == json.loads(json.dumps(items, default=str))


def test_code_objects_use_the_existing_string_fallback():
    from optodraw.renderers._scene_data import expand_scene_data, pack_scene_data
    import json
    items = [{"geometry": {"type": "custom", "metadata": compile("1", "same", "eval")}} for _ in range(2)]
    restored = expand_scene_data(pack_scene_data(items, copy_records=False))
    assert json.loads(json.dumps(restored, default=str)) == json.loads(json.dumps(items, default=str))


def test_native_and_older_python_paths_retain_the_same_hashes(monkeypatch):
    from types import SimpleNamespace
    import optodraw.renderers._scene_data as module
    items = [{"geometry": {"type": "group", "children": [
        {"type": "path", "points": [[0.0, -0.0], [1, True]], "material": {"opacity": 0.5}}
    ]}} for _ in range(3)]
    native = module.pack_scene_data(items)
    monkeypatch.setattr(module, "sys", SimpleNamespace(version_info=(3, 12)))
    assert module.pack_scene_data(items) == native

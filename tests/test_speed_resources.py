import shutil
import subprocess
from pathlib import Path

import pytest

from optodraw.renderers._scene_data import expand_scene_data


def records():
    geometry = {"shape": "custom_outline", "part_definition": "future-part",
                "curves": [[0.12345678901234567, 2, 3, 4]], "holes": [[1, 2, 3]],
                "material": {"color": "#123456", "roughness": 0.12345678901234567},
                "children": [{"shape": "future_shape", "position": [1, 2, 3],
                              "material": {"color": "#abcdef"}}]}
    return [{"type": "mesh", "componentId": str(i), "position": [i, 0, -i],
             "rotation": [0, i / 7, 0], "ports3d": [[i, -i, 0]],
             "anim": {"power": i / 13}, "geometry": geometry} for i in range(12)]


def test_legacy_items_and_missing_references():
    items = records()
    assert expand_scene_data(items) == items
    with pytest.raises(ValueError, match="geometry"):
        expand_scene_data({"items": [{"geometryRef": "missing"}], "geometries": {}, "materials": {}})


def test_resource_cache_clones_placements_and_highlight_materials():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    source = Path(__file__).parents[1] / "optodraw/renderers/js/scene_resources.js"
    script = source.read_text() + r'''
const assert = require('node:assert/strict');
let builds = 0;
const material = { emissive: { value: 0, setHex(v) { this.value = v; } },
  emissiveIntensity: 0, clone() { return { ...this, emissive: { ...this.emissive } }; }, dispose() {} };
const build = () => { builds++; return { geometry: {}, material, position: [0, 0, 0],
  clone() { return { ...this, position: [...this.position] }; } }; };
const shape = { shape: 'arbitrary_future_shape', curves: [1, 2, 3] };
const a = odSharedGeometry(shape, build), b = odSharedGeometry({ curves: [1, 2, 3], shape: shape.shape }, build);
assert.equal(builds, 1); assert.notEqual(a, b); assert.equal(a.geometry, b.geometry);
a.position[0] = 99; assert.equal(b.position[0], 0);
odHighlightMaterial(a, true); assert.notEqual(a.material, b.material);
assert.equal(b.material.emissive.value, 0); assert.equal(a.material.emissive.value, 0x2563eb);
odHighlightMaterial(a, false); assert.equal(a.material, b.material);
const c = { material: [material, material] }; odHighlightMaterial(c, true);
assert.notEqual(c.material[0], material); assert.equal(material.emissive.value, 0);
odHighlightMaterial(c, false); assert.equal(c.material[0], material);
let mats = 0; const make = () => { mats++; return {}; };
assert.equal(odSharedMaterial({color:'#fff'}, make), odSharedMaterial({color:'#fff'}, make));
assert.equal(mats, 1);
odClearResources(); odSharedGeometry(shape, build); assert.equal(builds, 2);
'''
    result = subprocess.run([node, "-e", script], text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr

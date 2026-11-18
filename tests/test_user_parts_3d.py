"""User SVG outlines remain usable in the 3D viewer."""

import json

import pytest

from optodraw import PartLibrary, Scene, define_part
from optodraw.renderers.capabilities import UnsupportedGeometryError
from optodraw.renderers.threejs_renderer import ThreeJsRenderer
from optodraw.renderers.capture3d import find_chrome, run_page


OUTLINE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -5 20 10">'
           '<path d="M-10 0Q0 -10 10 0Q0 10 -10 0Z" fill="black"/></svg>')


def part(svg=OUTLINE, **kwargs):
    return define_part("user:example/Outline", platform="on_chip", ports=[],
                       symbol_2d=svg, library=PartLibrary())(**kwargs)


def test_3d_fallback_retains_outline_not_a_bounding_box():
    node = part(scale=2)
    geometry = node.geometry_3d()
    assert geometry["shape"] == "svg_extrusion"
    assert geometry["schematic"] is True
    assert "Q0 -10" in geometry["svg"]
    assert geometry["scale"] == [2, 2, 2]
    assert geometry["height"] == pytest.approx(0.2)
    assert "width" not in geometry


def test_existing_scene_and_preview_render_with_user_part_and_report_schematic():
    scene = Scene(platform="on_chip")
    scene.add(part(center=(25, 12), angle=90))
    renderer = ThreeJsRenderer(scene)
    page = renderer.render()
    assert "svg_extrusion" in page
    assert "odMakeSvgExtrusion" in page
    assert "SVGLoader.js" in page
    assert any("schematic" in item for item in renderer.report.approximated)
    assert "svg_extrusion" in scene.preview()._repr_html_()


def test_strict_renderer_rejects_schematic_fallback_with_named_reason():
    scene = Scene(platform="on_chip")
    scene.add(part())
    with pytest.raises(UnsupportedGeometryError, match="schematic"):
        ThreeJsRenderer(scene, strict=True).render()


def test_explicit_2d_outline_wins_over_1d_and_transforms_stay_in_svg():
    factory = define_part(
        "user:example/Artwork", platform="on_chip", ports=[],
        symbol_2d=OUTLINE.replace('<path ', '<g transform="translate(3 2)"><path ').replace('/></svg>', '/></g></svg>'),
        symbol_1d=OUTLINE.replace("Q0 -10", "L0 -5"), library=PartLibrary())
    geometry = factory().geometry_3d()
    assert "translate(3 2)" in geometry["svg"]
    assert "Q0 -10" in geometry["svg"]


def test_line_only_symbol_fallback_is_not_empty():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
           '<line x1="0" y1="5" x2="10" y2="5" stroke="black" stroke-width="2"/></svg>')
    factory = define_part("user:example/Line", platform="on_chip", ports=[],
                          symbol_1d=svg, library=PartLibrary())
    assert "line" in factory().geometry_3d()["svg"]


@pytest.mark.skipif(find_chrome(required=False) is None, reason="needs a headless browser")
def test_browser_extrudes_holes_strokes_and_transformed_curves():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 15">'
           '<path fill="none" fill-rule="evenodd" d="M0 0H10V10H0Z M3 3H7V7H3Z"/>'
           '<g transform="translate(15 5)"><circle r="3" fill="none" stroke="black" stroke-width="2"/></g>'
           '<path d="M22 1Q26 10 29 1" fill="none" stroke="black" stroke-width="1"/>'
           '<rect x="22" y="11" width="5" height="3" fill="none"/></svg>')
    scene = Scene(platform="on_chip")
    scene.add(part(svg))
    page = ThreeJsRenderer(scene, show_export_controls=False).render()
    probe = '''
const probeGroup = odMakeSvgExtrusion(sceneData.find(item => item.geometry?.shape === 'svg_extrusion').geometry);
probeGroup.updateMatrixWorld(true);
const ray = new THREE.Raycaster();
const hits = (x, z) => {
  ray.set(new THREE.Vector3(x, 10, z), new THREE.Vector3(0, -1, 0));
  return ray.intersectObject(probeGroup, true).length;
};
let meshCount = 0, finite = true, maxY = 0;
probeGroup.traverse(node => {
  if (!node.isMesh) return;
  meshCount++;
  const p = node.geometry.getAttribute('position');
  for (let i = 0; i < p.count; i++) {
    finite = finite && [p.getX(i), p.getY(i), p.getZ(i)].every(Number.isFinite);
    maxY = Math.max(maxY, p.getY(i));
  }
});
const result = {meshCount, finite, maxY, solid: hits(1, 1), hole: hits(5, 5),
  ring: hits(18, 5), ringCenter: hits(15, 5), rectangle: hits(24, 12),
  openCurve: hits(26, 2), outside: hits(12, 12)};
const probeOutput = document.createElement('textarea');
probeOutput.id = 'od-probe'; probeOutput.value = JSON.stringify(result); document.body.append(probeOutput);
'''
    # The probe shares the page's real imports and geometry helpers.
    probe = probe.replace("sceneData.find(item => item.geometry?.shape === 'svg_extrusion').geometry",
                          json.dumps(part(svg).geometry_3d()))
    page = page.replace("function makeGeometry(geo) {", probe + "\nfunction makeGeometry(geo) {")
    data = json.loads(run_page(page, width=160, height=100, timeout=90, element="od-probe"))
    assert data["meshCount"] == 5
    assert data["finite"] is True
    assert data["maxY"] == pytest.approx(0.3)
    assert data["solid"] > 0 and data["ring"] > 0
    assert data["ringCenter"] > 0 and data["rectangle"] > 0
    assert data["hole"] == data["openCurve"] == data["outside"] == 0

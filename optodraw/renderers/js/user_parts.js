// SVG coordinates map to viewer (x, height, y). Ports use the same local origin.
function odSvgShape(points) {
  const shape = new THREE.Shape();
  if (!points.length) return shape;
  shape.moveTo(points[0].x, -points[0].y);
  for (const p of points.slice(1)) shape.lineTo(p.x, -p.y);
  return shape;
}

function odExtrudeSvgStroke(stroke, height) {
  // Keep the stroke's caps and joins. Extrude its triangulation and boundary only.
  const source = stroke.index ? stroke.toNonIndexed() : stroke;
  const attribute = source.getAttribute('position');
  const vertices = [];
  const edges = new Map();
  const key = p => `${Math.round(p[0] * 1e8)},${Math.round(p[1] * 1e8)}`;
  const emit = (a, b, c) => vertices.push(...a, ...b, ...c);
  for (let i = 0; i < attribute.count; i += 3) {
    const points = [0, 1, 2].map(j => [attribute.getX(i + j), attribute.getY(i + j)]);
    const [a, b, c] = points;
    const cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    if (!cross) continue;
    if (cross > 0) points.reverse();
    const bottom = points.map(p => [p[0], 0, p[1]]);
    const top = points.map(p => [p[0], height, p[1]]);
    emit(...top);
    emit(bottom[2], bottom[1], bottom[0]);
    for (let j = 0; j < 3; j++) {
      const p = points[j], q = points[(j + 1) % 3];
      const pk = key(p), qk = key(q);
      const edgeKey = pk < qk ? `${pk}|${qk}` : `${qk}|${pk}`;
      if (edges.has(edgeKey)) edges.delete(edgeKey);
      else edges.set(edgeKey, [p, q]);
    }
  }
  for (const [p, q] of edges.values()) {
    const a = [p[0], 0, p[1]], b = [q[0], 0, q[1]];
    const c = [q[0], height, q[1]], d = [p[0], height, p[1]];
    emit(a, b, c); emit(a, c, d);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
  geometry.computeVertexNormals();
  if (source !== stroke) source.dispose();
  stroke.dispose();
  return geometry;
}

function odMakeSvgExtrusion(geo) {
  const group = new THREE.Group();
  group.userData.optodrawRepresentation = 'schematic';
  group.userData.partName = geo.part_name;
  const material = makeMaterial(geo.material || {});
  const height = geo.height;
  const parsed = new SVGLoader().parse(geo.svg);
  function add(geometry) {
    const mesh = new THREE.Mesh(geometry, material);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData.optodrawRepresentation = 'schematic';
    group.add(mesh);
  }
  for (const path of parsed.paths) {
    const style = path.userData.style;
    if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) === 0) continue;
    // A closed outline describes the schematic body, even without an SVG fill.
    const body = new THREE.ShapePath();
    body.userData = path.userData;
    body.subPaths = path.subPaths.filter(subpath => {
      if (style.fill !== 'none' && Number(style.fillOpacity) !== 0) return true;
      const points = subpath.getPoints(24);
      return subpath.autoClose || (points.length > 2 &&
        points[0].distanceToSquared(points[points.length - 1]) < 1e-12);
    });
    if (body.subPaths.length) {
      for (const original of SVGLoader.createShapes(body)) {
        const outline = original.extractPoints(24);
        const shape = odSvgShape(outline.shape);
        shape.holes = outline.holes.map(points => odSvgShape(points));
        const geometry = new THREE.ExtrudeGeometry(shape, {
          depth: height, bevelEnabled: false, steps: 1,
        });
        geometry.rotateX(-Math.PI / 2);
        add(geometry);
      }
    }
    if (style.stroke && style.stroke !== 'none' && Number(style.strokeOpacity) !== 0) {
      for (const subpath of path.subPaths) {
        const stroke = SVGLoader.pointsToStroke(subpath.getPoints(24), style, 12, 0.000001);
        if (stroke) add(odExtrudeSvgStroke(stroke, height));
      }
    }
  }
  const label = document.createElement('div');
  label.textContent = 'Schematic';
  label.title = `${geo.part_name}: shallow SVG outline, not physical 3D geometry`;
  label.style.cssText = 'font-size:10px;color:#555;background:rgba(255,255,255,.85);padding:2px 4px;pointer-events:none';
  const marker = new CSS2DObject(label);
  marker.position.set(0, height, 0);
  group.add(marker);
  return group;
}

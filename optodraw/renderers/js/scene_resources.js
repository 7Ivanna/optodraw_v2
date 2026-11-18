// Complete records form resource keys. Instance objects remain separate.
const odGeometryCache = new Map();
const odMaterialCache = new Map();
const odHighlightOriginals = new WeakMap();

function odResourceKey(value) {
  if (Array.isArray(value)) return '[' + value.map(odResourceKey).join(',') + ']';
  if (value && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + odResourceKey(value[k])).join(',') + '}';
  }
  if (Object.is(value, -0)) return '-0';
  return JSON.stringify(value);
}

function odExpandSceneData(data) {
  if (Array.isArray(data)) return data;
  const geometry = key => {
    const source = data.geometries[key];
    if (!source) throw new Error('Missing geometry reference: ' + key);
    const record = { ...source };
    if ('materialRef' in record) {
      const material = data.materials[record.materialRef];
      if (!material) throw new Error('Missing material reference: ' + record.materialRef);
      record.material = { ...material }; delete record.materialRef;
    }
    if (record.children) record.children = record.children.map(child => geometry(child.geometryRef));
    return record;
  };
  return data.items.map(item => {
    if (!('geometryRef' in item)) return item;
    const record = { ...item, geometry: geometry(item.geometryRef) };
    delete record.geometryRef;
    return record;
  });
}

function odSharedGeometry(record, build) {
  const key = odResourceKey(record);
  if (!odGeometryCache.has(key)) odGeometryCache.set(key, build(record));
  return odGeometryCache.get(key).clone(true);
}

function odSharedMaterial(record, build) {
  const key = odResourceKey(record);
  if (!odMaterialCache.has(key)) odMaterialCache.set(key, build());
  return odMaterialCache.get(key);
}

function odClearResources() {
  odGeometryCache.clear();
  odMaterialCache.clear();
}

function odHighlightMaterial(mesh, enabled) {
  if (enabled) {
    if (odHighlightOriginals.has(mesh)) return;
    const original = mesh.material;
    odHighlightOriginals.set(mesh, original);
    const clones = new Map();
    const highlight = material => {
      if (!material || !material.emissive) return material;
      if (!clones.has(material)) {
        const clone = material.clone();
        clone.emissive.setHex(0x2563eb); clone.emissiveIntensity = 0.55;
        clones.set(material, clone);
      }
      return clones.get(material);
    };
    mesh.material = Array.isArray(original) ? original.map(highlight) : highlight(original);
  } else if (odHighlightOriginals.has(mesh)) {
    const original = odHighlightOriginals.get(mesh);
    const retained = new Set(Array.isArray(original) ? original : [original]);
    const current = new Set(Array.isArray(mesh.material) ? mesh.material : [mesh.material]);
    current.forEach(material => { if (material && !retained.has(material)) material.dispose(); });
    mesh.material = original;
    odHighlightOriginals.delete(mesh);
  }
}

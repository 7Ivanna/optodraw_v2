"""End-to-end rib cross-section engine tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from optodraw.gds.xsection import CrossSectionStripLayout, XSectionEngine, export_xsection_bundle


pytest.importorskip("yaml")
pytest.importorskip("shapely")


FIXTURE = Path(__file__).parent / "fixtures" / "xsection" / "generic_siph_minimal.yaml"


def test_generic_bundle_matches_output_layer_contract(tmp_path):
    engine = XSectionEngine.from_yaml(FIXTURE)
    cut = (
        CrossSectionStripLayout()
        .strip("RIB", width_um=0.5, center_y_um=0.0)
        .strip("SLAB", width_um=2.0, center_y_um=0.0)
        .strip("MT1", width_um=0.7, center_y_um=0.0)
        .section(label="quality-check")
        .to_layout_cut()
    )
    bundle = export_xsection_bundle(engine, cut, tmp_path)
    assert bundle.output_stack is not None

    expected_names = {layer.name for layer in engine.process.output_layers}
    stack_layers = {layer.name: layer for layer in bundle.output_stack.layers}
    assert set(stack_layers) == expected_names
    assert set(bundle.layer_paths) == expected_names

    for spec in engine.process.output_layers:
        layer = stack_layers[spec.name]
        assert layer.color == spec.color
        assert bundle.layer_paths[spec.name].exists()

    for name in {"Oxide", "Silicon", "Metal1"}:                    # Metal1 was empty: grow into oxide1 aliased it
        assert not stack_layers[name].geometry.is_empty


def _strip_cut():
    return (
        CrossSectionStripLayout()
        .strip("RIB", width_um=0.5, center_y_um=0.0)
        .strip("SLAB", width_um=2.0, center_y_um=0.0)
        .to_layout_cut()
    )


def test_nm_definition_matches_um_geometry():
    import yaml

    from optodraw.gds.xsection.schema import ProcessDefinition

    raw = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    um_engine = XSectionEngine.from_yaml(FIXTURE)
    um_stack = um_engine.run(_strip_cut())

    nm_raw = dict(raw, units="nm")
    nm_raw["substrate"] = {k: (v * 1000.0 if isinstance(v, (int, float)) else v) for k, v in raw["substrate"].items() if not k.endswith("material")}
    nm_raw["substrate"].update({k: v for k, v in raw["substrate"].items() if k.endswith("material")})
    nm_raw["device"] = {"material": raw["device"]["material"], "thickness": 220.0, "z_on_box": 0.0}
    nm_steps = []
    for entry in raw["process"]:
        step = dict(entry)
        for block, keys in (("deposit", ("thickness",)), ("etch", ("depth",)), ("planarize", ("to_z",)),
                            ("fill", ("to_z",))):
            if step.get(block):
                chunk = dict(step[block])
                for key in keys:
                    if key in chunk:
                        chunk[key] = chunk[key] * 1000.0
                step[block] = chunk
        nm_steps.append(step)
    nm_raw["process"] = nm_steps
    nm_engine = XSectionEngine(process=ProcessDefinition.from_mapping(nm_raw))
    nm_stack = nm_engine.run(_strip_cut())

    um_layers = {layer.name: layer for layer in um_stack.layers}
    nm_layers = {layer.name: layer for layer in nm_stack.layers}
    assert set(nm_layers) == set(um_layers)
    for name in um_layers:
        assert nm_layers[name].geometry.area == pytest.approx(um_layers[name].geometry.area, rel=1e-9)


def test_unknown_process_units_rejected():
    from optodraw.gds.xsection.schema import ProcessDefinition

    with pytest.raises(ValueError, match="units must be"):
        ProcessDefinition.from_mapping({"units": "mm"})

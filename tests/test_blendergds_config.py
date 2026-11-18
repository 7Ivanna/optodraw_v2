"""Tests for BlenderGDS-style layer config parsing."""

from __future__ import annotations

import pytest

from optodraw import Technology, parse_blendergds_layer_config, parse_klayout_lyp


pytest.importorskip("yaml")


def test_parse_blendergds_layer_config_with_colors(tmp_path):
    stack_path = tmp_path / "stack.yaml"
    stack_path.write_text(
        """
Metal1:
  index: 8
  type: 0
  z: 0.640
  height: 0.400
Metal1Filler:
  index: 8
  type: 22
  purpose: filler
  z: 0.640
  height: 0.400
Waveguide:
  index: 1
  type: 0
  z: 0.000
  height: 0.220
""".strip(),
        encoding="utf-8",
    )
    color_path = tmp_path / "colors.yaml"
    color_path.write_text(
        """
name: Test
layers:
  Metal1:
    color: [0.5, 0.25, 0.0, 0.4]
    metallic: 0.9
    roughness: 0.2
  Waveguide:
    color: [0.1, 0.2, 0.3, 1.0]
""".strip(),
        encoding="utf-8",
    )

    styles = parse_blendergds_layer_config(stack_path, color_config_path=color_path)

    assert (8, 0) in styles
    assert (8, 22) not in styles
    assert styles[(8, 0)]["name"] == "Metal1"
    assert styles[(8, 0)]["color"] == "#804000"
    assert styles[(8, 0)]["opacity"] == 0.4
    assert styles[(8, 0)]["material_preset"] == "aluminum"
    assert styles[(8, 0)]["metallic"] == 0.9
    assert styles[(8, 0)]["roughness"] == 0.2
    assert styles[(8, 0)]["zmin"] == 0.64
    assert styles[(8, 0)]["thickness"] == 0.4
    assert styles[(1, 0)]["material_preset"] == "silicon"
    assert styles[(1, 0)]["style_source"] == "blendergds-yaml"


def test_parse_blendergds_layer_config_can_include_filler(tmp_path):
    stack_path = tmp_path / "stack.yaml"
    stack_path.write_text(
        """
Metal1Filler:
  index: 8
  type: 22
  purpose: filler
  z: 0.640
  height: 0.400
""".strip(),
        encoding="utf-8",
    )

    styles = parse_blendergds_layer_config(stack_path, include_filler=True)

    assert styles[(8, 22)]["purpose"] == "filler"


def test_technology_wraps_blendergds_layer_config(tmp_path):
    stack_path = tmp_path / "stack.yaml"
    stack_path.write_text(
        """
RIB:
  index: 10
  type: 0
  z: 0.000
  height: 0.220
MT1:
  index: 105
  type: 0
  z: 1.000
  height: 0.700
  material: Al
""".strip(),
        encoding="utf-8",
    )

    technology = Technology.from_blendergds_layer_config(stack_path, name="demo-process")

    assert technology.name == "demo-process"
    assert technology.get((10, 0)).name == "RIB"
    assert technology.get("105/0").material_preset == "aluminum"
    assert technology.to_layer_styles()[(105, 0)]["zmin"] == 1.0
    assert technology.describe_layers()[0]["spec"] == (10, 0)


def test_parse_klayout_lyp_and_technology_include_hidden(tmp_path):
    lyp_path = tmp_path / "layers.lyp"
    lyp_path.write_text(
        """
<layer-properties>
  <properties>
    <name>RIB</name>
    <source>10/0@1</source>
    <fill-color>#336699</fill-color>
    <frame-color>#123456</frame-color>
    <visible>true</visible>
    <transparent>false</transparent>
  </properties>
  <properties>
    <name>Hidden Metal</name>
    <source>105/0@1</source>
    <fill-color>#ffcc00</fill-color>
    <visible>false</visible>
  </properties>
</layer-properties>
""".strip(),
        encoding="utf-8",
    )

    visible_styles = parse_klayout_lyp(lyp_path)
    technology = Technology.from_klayout_lyp(lyp_path, include_hidden=True)

    assert (10, 0) in visible_styles
    assert (105, 0) not in visible_styles
    assert visible_styles[(10, 0)]["color"] == "#336699"
    assert visible_styles[(10, 0)]["stroke"] == "#123456"
    assert technology.get((105, 0)).visible is False

    # A .lyp file holds colours only. The parser adds no thickness or height, and says so.
    parsed = visible_styles[(10, 0)]
    assert parsed["physical_stack_known"] is False
    assert not {"thickness", "zmin", "z_offset"} & set(parsed)
    assert "unknown thickness" in parsed["description"]

    # A technology needs numbers to draw with, so it adds drawing defaults.
    # The layer stays flagged as "stack not known", and every parsed field is kept.
    styles = technology.layer_styles(include_hidden=False)
    assert set(styles) == {(10, 0)}
    assert technology.get((10, 0)).physical_stack_known is False
    assert styles[(10, 0)]["physical_stack_known"] is False
    assert {key: styles[(10, 0)][key] for key in parsed} == parsed
    assert set(styles[(10, 0)]) - set(parsed) == {"thickness", "zmin", "z_offset"}
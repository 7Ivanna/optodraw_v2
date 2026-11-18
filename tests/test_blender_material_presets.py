"""Tests for Blender Principled BSDF material presets, overrides, and add-on hook."""

from __future__ import annotations

import pytest

from optodraw.blender import (
    BLENDER_MATERIAL_PRESETS,
    BlenderAddonInvocation,
    BlenderMaterialOverride,
    CAMERA_PRESETS,
    export_blender_script,
    get_blender_material_preset,
    list_blender_material_presets,
    list_camera_presets,
)


@pytest.fixture
def source_glb(tmp_path):
    path = tmp_path / "scene.glb"
    path.write_bytes(b"glTF")
    return path


class TestBlenderMaterialPresetTable:
    def test_required_photonics_presets_present(self):
        keys = set(list_blender_material_presets())
        for required in {"silicon", "silicon_nitride", "germanium", "sio2", "gold", "aluminum", "copper"}:
            assert required in keys

    def test_preset_aliases_resolve_case_insensitively(self):
        sin_preset = get_blender_material_preset("SIN")
        assert sin_preset == BLENDER_MATERIAL_PRESETS["silicon_nitride"]

        assert get_blender_material_preset("Au")["metallic"] == pytest.approx(1.0)
        assert get_blender_material_preset("ito")["transmission"] == pytest.approx(0.72)

    def test_unknown_preset_raises(self):
        with pytest.raises(KeyError):
            get_blender_material_preset("unobtainium")

    def test_each_preset_has_principled_bsdf_inputs(self):
        for name, preset in BLENDER_MATERIAL_PRESETS.items():
            assert "base_color" in preset, name
            r, g, b = preset["base_color"]
            assert 0.0 <= r <= 1.0 and 0.0 <= g <= 1.0 and 0.0 <= b <= 1.0


class TestCameraPresetTable:
    def test_canonical_preset_names_present(self):
        names = set(list_camera_presets())
        assert {
            "top",
            "isometric",
            "side",
            "front",
            "cross_section",
            "free_space_table",
        }.issubset(names)

    def test_camera_presets_have_directions(self):
        for name, spec in CAMERA_PRESETS.items():
            direction = spec["direction"]
            assert len(direction) == 3, name
            assert any(abs(v) > 0.0 for v in direction), name


class TestExportedScriptMaterialOverrides:
    def test_material_override_payload_resolves_preset(self, tmp_path, source_glb):
        script_path = export_blender_script(
            tmp_path / "render.blender.py",
            source_glb=source_glb,
            material_overrides=[
                BlenderMaterialOverride(name="Metal1", preset="aluminum"),
                {"name": "Waveguide", "preset": "silicon_nitride", "match": "contains"},
            ],
        )
        script = script_path.read_text(encoding="utf-8")

        assert "MATERIAL_OVERRIDES = [" in script
        assert "'name': 'Metal1'" in script
        assert "'metallic': 0.88" in script
        assert "'match': 'contains'" in script
        assert "def apply_material_overrides" in script
        assert "Principled BSDF" in script
        assert "Transmission Weight" in script

    def test_explicit_inputs_override_preset(self, tmp_path, source_glb):
        script_path = export_blender_script(
            tmp_path / "render.blender.py",
            source_glb=source_glb,
            material_overrides=[
                {
                    "name": "Waveguide",
                    "preset": "silicon",
                    "roughness": 0.05,
                    "base_color": "#3344aa",
                }
            ],
        )
        script = script_path.read_text(encoding="utf-8")

        assert "'roughness': 0.05" in script
        assert "0.2" in script  # base_color red channel ≈ 0x33/255
        assert "Principled BSDF" in script

    def test_material_overrides_from_layer_styles(self, tmp_path, source_glb):
        layer_styles = {
            (1, 0): {
                "name": "RIB",
                "material_preset": "silicon",
                "color": "#6f747a",
                "roughness": 0.32,
            },
            (8, 0): {
                "name": "Metal1",
                "material_preset": "aluminum",
                "color": "#bcc4cc",
                "metallic": 0.92,
            },
            (105, 0): {
                "name": "M2_filler",
                "material_preset": "copper",
                "color": "#b46843",
            },
        }
        script_path = export_blender_script(
            tmp_path / "render.blender.py",
            source_glb=source_glb,
            layer_styles=layer_styles,
        )
        script = script_path.read_text(encoding="utf-8")

        assert "'name': 'RIB'" in script
        assert "'name': 'Metal1'" in script
        assert "'metallic': 0.92" in script

    def test_layer_styles_and_explicit_overrides_compose(self, tmp_path, source_glb):
        script_path = export_blender_script(
            tmp_path / "render.blender.py",
            source_glb=source_glb,
            layer_styles={
                (1, 0): {"name": "RIB", "material_preset": "silicon"},
            },
            material_overrides=[
                {"name": "RIB", "preset": "silicon_nitride", "roughness": 0.18},
            ],
        )
        script = script_path.read_text(encoding="utf-8")

        # both overrides land in the payload (RIB appears twice, last one wins at runtime)
        assert script.count("'name': 'RIB'") == 2
        assert "'roughness': 0.18" in script

    def test_unknown_preset_in_override_raises(self, tmp_path, source_glb):
        with pytest.raises(KeyError):
            export_blender_script(
                tmp_path / "render.blender.py",
                source_glb=source_glb,
                material_overrides=[{"name": "Metal1", "preset": "unobtanium"}],
            )

    def test_invalid_match_mode_raises(self, tmp_path, source_glb):
        with pytest.raises(ValueError, match="material override match"):
            export_blender_script(
                tmp_path / "render.blender.py",
                source_glb=source_glb,
                material_overrides=[{"name": "Metal1", "preset": "gold", "match": "fuzzy"}],
            )

    def test_override_must_carry_payload(self, tmp_path, source_glb):
        with pytest.raises(ValueError, match="material override must supply"):
            export_blender_script(
                tmp_path / "render.blender.py",
                source_glb=source_glb,
                material_overrides=[{"name": "Metal1"}],
            )


class TestExtendedCameraPresets:
    @pytest.mark.parametrize(
        "preset",
        ["isometric", "top", "front", "side", "cross_section", "free_space_table"],
    )
    def test_each_preset_writes_into_script(self, tmp_path, source_glb, preset):
        script_path = export_blender_script(
            tmp_path / f"render_{preset}.blender.py",
            source_glb=source_glb,
            camera_preset=preset,
        )
        script = script_path.read_text(encoding="utf-8")
        assert f"CAMERA_PRESET = '{preset}'" in script
        assert "CAMERA_DIRECTIONS = {" in script
        assert preset in script

    def test_unknown_preset_rejected(self, tmp_path, source_glb):
        with pytest.raises(ValueError, match="camera_preset"):
            export_blender_script(
                tmp_path / "render.blender.py",
                source_glb=source_glb,
                camera_preset="overhead",
            )


class TestBlenderGdsAddonHook:
    def test_addon_invocation_emitted_in_script(self, tmp_path, source_glb):
        script_path = export_blender_script(
            tmp_path / "render.blender.py",
            source_glb=source_glb,
            addon_invocation=BlenderAddonInvocation(
                operator="blendergds.import_gdsii",
                kwargs={"filepath": "/tmp/chip.gds", "layer_config": "stack.yaml"},
                module="blendergds",
            ),
        )
        script = script_path.read_text(encoding="utf-8")

        assert "ADDON_INVOCATION = {" in script
        assert "'operator': 'blendergds.import_gdsii'" in script
        assert "'module': 'blendergds'" in script
        assert "'layer_config': 'stack.yaml'" in script
        assert "def invoke_optional_addon" in script
        assert "addon_utils.enable" in script

    def test_addon_invocation_from_dict_form(self, tmp_path, source_glb):
        script_path = export_blender_script(
            tmp_path / "render.blender.py",
            source_glb=source_glb,
            addon_invocation={
                "operator": "blendergds.import_gdsii",
                "kwargs": {"filepath": "chip.gds"},
                "enable_first": False,
            },
        )
        script = script_path.read_text(encoding="utf-8")

        assert "'enable_first': False" in script
        assert "'filepath': 'chip.gds'" in script

    def test_invalid_addon_operator_rejected(self, tmp_path, source_glb):
        with pytest.raises(ValueError, match="addon invocation operator"):
            export_blender_script(
                tmp_path / "render.blender.py",
                source_glb=source_glb,
                addon_invocation={"operator": "no_dot_operator"},
            )

    def test_no_addon_invocation_keeps_payload_none(self, tmp_path, source_glb):
        script_path = export_blender_script(
            tmp_path / "render.blender.py",
            source_glb=source_glb,
        )
        script = script_path.read_text(encoding="utf-8")
        assert "ADDON_INVOCATION = None" in script

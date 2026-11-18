"""Tests for roadmap-completion features."""

from typing import Any, cast

import pytest

from optodraw import (
    Scene,
    AsphericLens,
    Mirror,
    CylindricalLens,
    ConcaveMirror,
    ConvexMirror,
    BiconcaveMirror,
    BiconvexMirror,
    CustomModel,
    Analyzer,
    ApertureStop,
    DichroicMirror,
    FiberCollimator,
    FiberPort,
    FourFSystem,
    GDSModel,
    HalfWavePlate,
    Iris,
    NonPolarizingBeamSplitter,
    PBS,
    Pinhole,
    Polarizer,
    Prism,
    QuarterWavePlate,
    SLM,
    Technology,
    Telescope,
    build_gds_sections,
    describe_component,
    list_presets,
    build_preset,
    export_blender_script,
    get_material_preset,
    load_gds_layout,
    list_components,
    list_material_presets,
    parse_gds3d_techfile,
    plot_gds_top_view,
    trace_ray,
    threejs_iframe_html,
)


class TestPresets:
    def test_list_presets(self):
        presets = list_presets()
        assert "confocal_pl" in presets
        assert "ring_resonator_chip" in presets
        assert "wdm_delay_weight_bank_chip" in presets

    def test_build_free_space_preset(self):
        scene = build_preset("confocal_pl")
        assert scene.platform == "free_space"
        assert sum(1 for _ in scene.walk()) > 0

    def test_build_onchip_preset(self):
        scene = build_preset("ring_resonator_chip")
        assert scene.platform == "on_chip"
        assert sum(1 for _ in scene.walk()) > 0

    def test_build_wdm_delay_weight_bank_preset(self):
        scene = build_preset("wdm_delay_weight_bank_chip")
        assert scene.platform == "on_chip"
        assert sum(1 for _ in scene.walk()) > 20
        svg = scene.render_svg().as_svg()
        assert "WDM" in svg
        assert "MZM" in svg
        assert "Weight bank" in svg
        assert "BPD" in svg


class TestRayTracing:
    def test_trace_ray_mirror_reflection(self):
        mirror = Mirror(center=(0, 0), angle=45)
        result = trace_ray(start=(-20, 0), direction_deg=0, optics=[mirror], exit_length=10)
        assert len(result.points) == 3
        assert round(result.direction_deg) in (-90, 270)

    def test_scene_trace_ray_adds_beam(self):
        scene = Scene()
        mirror = scene.add(Mirror(center=(0, 0), angle=45))
        beam = scene.trace_ray(start=(-20, 0), direction_deg=0, optics=[mirror], exit_length=10)
        assert beam in list(scene.walk())


class TestFreeSpaceOpticsCoverage:
    def test_new_free_space_optics_have_1d_2d_3d_and_metadata(self, assert_1d_symbol):
        components = [
            Prism(label="Prism"),
            Polarizer(label="Pol"),
            Analyzer(),
            HalfWavePlate(),
            QuarterWavePlate(),
            PBS(label="PBS"),
            NonPolarizingBeamSplitter(label="NPBS"),
            DichroicMirror(cutoff_wavelength=650, label="DM"),
            FiberPort(label="Fiber"),
            FiberCollimator(focal_length=8, label="Collimator"),
            Iris(aperture_diameter=3, label="Iris"),
            Pinhole(aperture_diameter=0.5),
            ApertureStop(aperture_diameter=4),
            SLM(resolution=(1024, 768), mode="phase", label="SLM"),
            AsphericLens(focal_length=12, numerical_aperture=0.4, label="Asphere"),
            CylindricalLens(focal_length=35, cylinder_axis="y", label="Cyl"),
            Telescope(focal_length_1=20, focal_length_2=40, label="Telescope"),
            FourFSystem(focal_length_1=20, focal_length_2=30, label="4f"),
        ]

        for component in components:
            assert_1d_symbol(component)
            assert component.geometry_2d()
            assert component.geometry_3d()["shape"] in {"box", "group", "cylinder", "extruded_polygon"}
            assert component.physics_metadata()["domain"] == "free_space"

    def test_new_free_space_optics_are_discoverable(self):
        optics = list_components(category="optics")
        for name in [
            "Prism",
            "ConcaveMirror",
            "ConvexMirror",
            "BiconcaveMirror",
            "BiconvexMirror",
            "Polarizer",
            "Analyzer",
            "HalfWavePlate",
            "QuarterWavePlate",
            "PBS",
            "NonPolarizingBeamSplitter",
            "DichroicMirror",
            "FiberPort",
            "FiberCollimator",
            "Iris",
            "Pinhole",
            "ApertureStop",
            "SLM",
            "AsphericLens",
            "CylindricalLens",
            "Telescope",
            "FourFSystem",
        ]:
            assert name in optics
            assert describe_component(name)["platform"] == "free_space"

    def test_mirror_surface_variants_have_visual_profiles(self, assert_1d_symbol):
        variants = [
            (ConcaveMirror(), "concave"),
            (ConvexMirror(), "convex"),
            (BiconcaveMirror(), "biconcave"),
            (BiconvexMirror(), "biconvex"),
        ]

        for mirror, surface_type in variants:
            assert mirror.surface_type == surface_type
            assert_1d_symbol(mirror)
            geometry_3d = mirror.geometry_3d()
            assert geometry_3d["shape"] == "group"
            assert geometry_3d["surface_profile"]["type"] == surface_type
            assert any(child.get("material", {}).get("clearcoat") == 1.0 for child in geometry_3d["children"] if child.get("shape") in {"box", "sphere"})

    def test_new_free_space_optics_render_in_svg_and_threejs(self):
        scene = Scene(title="Polarization Bench", width=220, height=130, platform="free_space")
        scene.add(Prism(center=(-75, 0), label="Prism"))
        scene.add(HalfWavePlate(center=(-45, 0)))
        scene.add(Polarizer(center=(-15, 0), label="Pol"))
        scene.add(PBS(center=(20, 0), label="PBS"))
        scene.add(FiberCollimator(center=(58, 0), label="Fiber"))
        scene.add(SLM(center=(92, 0), label="SLM"))

        svg = scene.render_svg().as_svg()
        html = scene.render_threejs(show_grid=False)

        assert "Polarization Bench" not in svg
        assert "Prism" in svg
        assert "SLM" in html
        assert "spatial_light_modulator" in SLM().physics_metadata()["component"]


class TestTikzAndNotebook:
    def test_render_tikz(self):
        scene = build_preset("confocal_pl")
        tikz = scene.render_tikz()
        assert "\\begin{tikzpicture}" in tikz
        assert "\\draw" in tikz or "\\path" in tikz

    def test_notebook_iframe_html(self):
        scene = build_preset("ring_resonator_chip")
        iframe = threejs_iframe_html(scene, height=320)
        assert "<iframe" in iframe
        assert "srcdoc=" in iframe


class TestImportedModels:
    def test_custom_model_geometry(self):
        model = CustomModel("assets/mock-device.glb", footprint=(20, 10), height=8)
        geo2d = model.geometry_2d()
        geo3d = model.geometry_3d()
        assert geo2d["type"] == "group"
        assert geo3d["shape"] == "external_model"
        assert geo3d["format"] == "glb"

    def test_gds_model_geometry(self):
        model = GDSModel("assets/mock-chip.gds", footprint=(40, 20))
        geo2d = model.geometry_2d()
        geo3d = model.geometry_3d()
        assert geo2d["type"] == "group"
        assert geo3d["shape"] == "box"

    def test_gds_model_loads_real_polygons(self, tmp_path):
        gdstk = pytest.importorskip("gdstk")

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_CHIP")
        cell.add(gdstk.rectangle((0, 0), (10, 4), layer=1, datatype=0))
        cell.add(gdstk.rectangle((2, 1), (8, 3), layer=2, datatype=0))

        gds_path = tmp_path / "test_chip.gds"
        lib.write_gds(gds_path.as_posix())

        model = GDSModel(gds_path)
        geo2d = model.geometry_2d()
        geo3d = model.geometry_3d()

        assert model.footprint == pytest.approx((10.0, 4.0))
        assert geo2d["type"] == "group"
        assert sum(1 for child in geo2d["children"] if child["type"] == "polygon") == 2
        assert geo3d["shape"] == "group"
        assert sum(1 for child in geo3d["children"] if child["shape"] == "extruded_polygon") == 2

    def test_gds_model_layer_stack_overrides(self, tmp_path):
        gdstk = pytest.importorskip("gdstk")

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_STACK")
        cell.add(gdstk.rectangle((0, 0), (10, 4), layer=1, datatype=0))
        cell.add(gdstk.rectangle((2, 1), (8, 3), layer=2, datatype=0))

        gds_path = tmp_path / "test_stack.gds"
        lib.write_gds(gds_path.as_posix())

        model = GDSModel(
            gds_path,
            layer_stack={
                (2, 0): {
                    "color": "#ff4d4f",
                    "opacity": 0.45,
                    "thickness": 0.9,
                    "z_offset": 1.25,
                    "material_preset": "gold",
                }
            },
        )

        geo2d = model.geometry_2d()
        geo3d = model.geometry_3d()

        highlighted_2d = next(child for child in geo2d["children"] if child["fill"] == "#ff4d4f")
        highlighted_3d = next(child for child in geo3d["children"] if child["material"]["color"] == "#ff4d4f")

        assert highlighted_2d["opacity"] == pytest.approx(0.45)
        assert highlighted_3d["height"] == pytest.approx(0.9)
        assert highlighted_3d["position"] == [0.0, 1.25, 0.0]
        assert highlighted_3d["material"]["preset"] == "gold"

    def test_gds_model_infers_generic_pdk_layer_depths(self, tmp_path):
        pytest.importorskip("gdsfactory")
        gdstk = pytest.importorskip("gdstk")

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_PDK")
        cell.add(gdstk.rectangle((0, 0), (10, 4), layer=1, datatype=0))
        cell.add(gdstk.rectangle((1, 1), (9, 3), layer=41, datatype=0))
        cell.add(gdstk.rectangle((0, 0), (10, 2), layer=20, datatype=0))   # an implant: no generic height

        gds_path = tmp_path / "test_pdk.gds"
        lib.write_gds(gds_path.as_posix())

        model = GDSModel(gds_path)
        geo3d = model.geometry_3d()
        assert model.layers_without_height() == ["20/0"]
        assert len(geo3d["children"]) == 2                                    # the implant is left out

        silicon_child = next(child for child in geo3d["children"] if child["material"]["preset"] == "silicon")
        metal_child = next(child for child in geo3d["children"] if child["material"]["preset"] == "aluminum")

        assert silicon_child["height"] == pytest.approx(0.22)
        assert "position" not in silicon_child
        assert metal_child["height"] == pytest.approx(0.7)
        assert metal_child["position"] == pytest.approx([0.0, 1.1, 0.0])

    def test_gds_model_accepts_gdsfactory_like_component(self):
        class DummyGdsComponent:
            name = "ring_test"
            dxsize = 12.5
            dysize = 4.0

        model = GDSModel(DummyGdsComponent(), scale=2.0)

        assert model.label == "ring_test"
        assert model.footprint == (25.0, 8.0)

    def test_load_gds_layout_surfaces_layer_descriptions(self, tmp_path):
        pytest.importorskip("gdsfactory")
        gdstk = pytest.importorskip("gdstk")

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_LAYOUT")
        cell.add(gdstk.rectangle((0, 0), (10, 4), layer=20, datatype=0))
        cell.add(gdstk.rectangle((1, 1), (9, 3), layer=41, datatype=0))

        gds_path = tmp_path / "test_layout.gds"
        lib.write_gds(gds_path.as_posix())

        layout = load_gds_layout(gds_path)
        summary = layout.summary()
        layer_descriptions = layout.describe_layers()
        sections = build_gds_sections(layout, count=3)

        assert summary["polygon_count"] == 2
        assert summary["matched_pdk_layers"] == 2
        assert summary["fallback_layers"] == 0
        assert summary["footprint_um"] == pytest.approx((10.0, 4.0))
        assert [entry["spec"] for entry in layer_descriptions] == [(20, 0), (41, 0)]
        assert all(entry["description"] for entry in layer_descriptions)
        assert [section.label for section in sections] == ["A", "B", "C"]

    def test_gds_layout_builds_scene_and_exports_mesh(self, tmp_path):
        pytest.importorskip("gdsfactory")
        gdstk = pytest.importorskip("gdstk")
        pytest.importorskip("shapely")
        pytest.importorskip("trimesh")

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_EXPORT")
        cell.add(gdstk.rectangle((0, 0), (10, 4), layer=20, datatype=0))
        cell.add(gdstk.rectangle((2, 1), (8, 3), layer=2, datatype=0))

        gds_path = tmp_path / "test_export.gds"
        lib.write_gds(gds_path.as_posix())

        layout = load_gds_layout(
            gds_path,
            layer_style_overrides={
                (2, 0): {
                    "name": "contact_overlay",
                    "color": "#ff4d4f",
                    "opacity": 0.45,
                    "thickness": 0.9,
                    "zmin": 1.25,
                    "material_preset": "gold",
                    "description": "contact overlay: gold, z=1.250 um, t=0.900 um, override",
                }
            },
        )

        scene, model = layout.build_scene()
        exports = layout.export_mesh(tmp_path, stem="test_export")
        geo3d = model.geometry_3d()
        highlighted = next(child for child in geo3d["children"] if child["material"]["color"] == "#ff4d4f")

        assert scene.platform == "on_chip"
        assert layout.gdsfactory_layer_stack is not None
        assert layout.gdsfactory_layer_views is not None
        assert geo3d["shape"] == "group"
        assert highlighted["height"] == pytest.approx(0.9)
        assert highlighted["position"] == [0.0, 1.25, 0.0]
        assert exports["stl"].exists()
        assert exports["glb"].exists()
        assert exports["backend"] in {"gdsfactory", "trimesh"}
        assert exports["faces"] > 0
        assert exports["layers"] == 2

    def test_load_gds_layout_accepts_gds3d_techfile(self, tmp_path):
        pytest.importorskip("gdsfactory")
        gdstk = pytest.importorskip("gdstk")
        pytest.importorskip("shapely")
        pytest.importorskip("trimesh")

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_GDS3D")
        cell.add(gdstk.rectangle((0, 0), (12, 4), layer=7, datatype=0))

        gds_path = tmp_path / "test_gds3d.gds"
        lib.write_gds(gds_path.as_posix())

        techfile_path = tmp_path / "process.txt"
        techfile_path.write_text(
            "\n".join(
                [
                    "LayerStart: Metal 1",
                    "Layer: 7",
                    "Datatype: 0",
                    "Height: 620",
                    "Thickness: 150",
                    "Red: 0.00",
                    "Green: 0.00",
                    "Blue: 1.00",
                    "Filter: 0.25",
                    "Material: Al",
                    "Show: 1",
                    "LayerEnd",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        styles = parse_gds3d_techfile(techfile_path)
        assert styles[(7, 0)]["zmin"] == pytest.approx(0.62)
        assert styles[(7, 0)]["thickness"] == pytest.approx(0.15)
        assert styles[(7, 0)]["color"] == "#0000ff"
        assert styles[(7, 0)]["material_preset"] == "aluminum"

        layout = load_gds_layout(gds_path, gds3d_techfile=techfile_path)
        report = layout.layer_report()
        assert isinstance(report, list)
        first = cast(dict[str, Any], report[0])
        assert first["style_source"] == "gds3d-techfile"
        assert first["material_preset"] == "aluminum"

        mesh = layout.build_trimesh()
        assert mesh.bounds[0][2] == pytest.approx(0.62)
        assert mesh.bounds[1][2] == pytest.approx(0.77)

    def test_export_mesh_prefers_gdsfactory_backend_for_gds3d_techfile(self, tmp_path):
        pytest.importorskip("gdsfactory")
        gdstk = pytest.importorskip("gdstk")
        pytest.importorskip("shapely")
        pytest.importorskip("trimesh")

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_GDS3D_EXPORT_BACKEND")
        cell.add(gdstk.rectangle((0, 0), (12, 4), layer=7, datatype=0))

        gds_path = tmp_path / "test_gds3d_export_backend.gds"
        lib.write_gds(gds_path.as_posix())

        techfile_path = tmp_path / "process_backend.txt"
        techfile_path.write_text(
            "\n".join(
                [
                    "LayerStart: Metal 1",
                    "Layer: 7",
                    "Datatype: 0",
                    "Height: 620",
                    "Thickness: 150",
                    "Red: 0.00",
                    "Green: 0.00",
                    "Blue: 1.00",
                    "Filter: 0.25",
                    "Material: Al",
                    "Show: 1",
                    "LayerEnd",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        layout = load_gds_layout(gds_path, gds3d_techfile=techfile_path)

        exports = layout.export_mesh(tmp_path, stem="test_gds3d_export_backend")

        assert exports["backend"] == "gdsfactory"
        assert exports["stl"].exists()
        assert exports["glb"].exists()

    def test_load_gds_layout_accepts_local_layer_container(self, tmp_path):
        pytest.importorskip("matplotlib")
        gdstk = pytest.importorskip("gdstk")

        class FoundryLayers:
            RIB = (10, 0)
            WG = RIB
            MT1 = (105, 0)

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_LAYERS")
        cell.add(gdstk.rectangle((0, 0), (10, 4), layer=10, datatype=0))
        cell.add(gdstk.rectangle((2, 1), (8, 3), layer=105, datatype=0))

        gds_path = tmp_path / "test_layers.gds"
        lib.write_gds(gds_path.as_posix())

        layout = load_gds_layout(
            gds_path,
            layers=FoundryLayers(),
            layer_style_overrides={(105, 0): {"material_preset": "aluminum"}},
        )
        layer_report = layout.layer_report()

        assert isinstance(layer_report, list)
        layer_report = cast(list[dict[str, object]], layer_report)
        first_entry = cast(dict[str, Any], layer_report[0])
        second_entry = cast(dict[str, Any], layer_report[1])

        assert [entry["name"] for entry in layer_report] == ["RIB", "MT1"]
        assert all(entry["matched_pdk"] is False for entry in layer_report)
        assert first_entry["style_source"] == "fallback"
        assert second_entry["style_source"] == "override"
        assert first_entry["material_preset"] == "silicon"
        assert second_entry["material_preset"] == "aluminum"
        assert float(second_entry["zmin"]) > float(first_entry["zmin"])

        import matplotlib.pyplot as plt

        _, ax = plt.subplots()
        plot_gds_top_view(layout, ax=ax, label_layers=True)
        labels = [text.get_text() for text in ax.texts]
        assert any("RIB" in label for label in labels)
        assert any("MT1" in label for label in labels)
        plt.close("all")

    def test_load_gds_layout_accepts_technology_object(self, tmp_path):
        gdstk = pytest.importorskip("gdstk")

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_TECHNOLOGY")
        cell.add(gdstk.rectangle((0, 0), (10, 4), layer=10, datatype=0))
        cell.add(gdstk.rectangle((2, 1), (8, 3), layer=105, datatype=0))

        gds_path = tmp_path / "test_technology.gds"
        lib.write_gds(gds_path.as_posix())

        technology = Technology.from_layer_styles(
            {
                (10, 0): {
                    "name": "RIB",
                    "color": "#2a9d6f",
                    "thickness": 0.22,
                    "zmin": 0.0,
                    "material_preset": "silicon",
                },
                (105, 0): {
                    "name": "MT1",
                    "color": "#d6a43a",
                    "thickness": 0.7,
                    "zmin": 1.0,
                    "material_preset": "aluminum",
                },
            },
            name="foundry-demo",
        )

        layout = load_gds_layout(gds_path, technology=technology)
        report = cast(list[dict[str, Any]], layout.layer_report())

        assert layout.summary()["technology"] == "foundry-demo"
        assert [entry["name"] for entry in report] == ["RIB", "MT1"]
        assert all(entry["matched_pdk"] is True for entry in report)
        assert report[1]["zmin"] == pytest.approx(1.0)
        assert report[1]["material_preset"] == "aluminum"

    def test_load_gds_layout_can_crop_region(self, tmp_path):
        gdstk = pytest.importorskip("gdstk")

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_CROP")
        cell.add(gdstk.rectangle((0, 0), (10, 10), layer=10, datatype=0))
        cell.add(gdstk.rectangle((20, 20), (30, 30), layer=10, datatype=0))

        gds_path = tmp_path / "test_crop.gds"
        lib.write_gds(gds_path.as_posix())

        layout = load_gds_layout(gds_path, crop_region=(2, 2, 8, 6))
        record = layout.layer_records[0]

        assert layout.bounds == pytest.approx((2, 2, 8, 6))
        assert layout.footprint_um == pytest.approx((6, 4))
        assert record.polygon_count == 1
        assert record.total_area_um2 == pytest.approx(24.0)
        assert all(2 <= x <= 8 and 2 <= y <= 6 for x, y in record.polygons[0])

    def test_load_gds_layout_can_merge_layer_polygons(self, tmp_path):
        gdstk = pytest.importorskip("gdstk")

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_IMPORT_MERGE")
        cell.add(gdstk.rectangle((0, 0), (6, 4), layer=10, datatype=0))
        cell.add(gdstk.rectangle((4, 0), (10, 4), layer=10, datatype=0))

        gds_path = tmp_path / "test_import_merge.gds"
        lib.write_gds(gds_path.as_posix())

        unmerged = load_gds_layout(gds_path)
        merged = load_gds_layout(gds_path, merge_polygons=True)

        assert unmerged.layer_records[0].polygon_count == 2
        assert merged.layer_records[0].polygon_count == 1
        assert merged.layer_records[0].total_area_um2 == pytest.approx(40.0)

    def test_export_mesh_can_merge_polygons(self, tmp_path):
        gdstk = pytest.importorskip("gdstk")
        pytest.importorskip("shapely")
        pytest.importorskip("trimesh")

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_EXPORT_MERGE")
        cell.add(gdstk.rectangle((0, 0), (6, 4), layer=10, datatype=0))
        cell.add(gdstk.rectangle((4, 0), (10, 4), layer=10, datatype=0))

        gds_path = tmp_path / "test_export_merge.gds"
        lib.write_gds(gds_path.as_posix())

        layout = load_gds_layout(gds_path)
        mesh = layout.build_trimesh(backend="trimesh", merge_polygons=True)
        exports = layout.export_mesh(
            tmp_path,
            stem="test_export_merge",
            backend="trimesh",
            merge_polygons=True,
        )

        assert mesh.bounds[1][0] - mesh.bounds[0][0] == pytest.approx(10.0)
        assert exports["backend"] == "trimesh"
        assert exports["merged_polygons"] is True
        assert exports["stl"].exists()

    def test_export_blender_script_writes_headless_import_script(self, tmp_path):
        source_glb = tmp_path / "scene.glb"
        source_glb.write_bytes(b"glTF")
        output_image = tmp_path / "render.png"

        script_path = export_blender_script(
            tmp_path / "render.blender.py",
            source_glb=source_glb,
            output_image=output_image,
            camera_preset="top",
            resolution=(800, 600),
            background_color="#f8fafc",
        )
        script = script_path.read_text(encoding="utf-8")

        assert "blender --background --python" in script
        assert "bpy.ops.import_scene.gltf" in script
        assert source_glb.resolve().as_posix() in script
        assert output_image.resolve().as_posix() in script
        assert "CAMERA_PRESET = 'top'" in script
        assert "RESOLUTION = (800, 600)" in script

    def test_gds_layout_exports_blender_script_for_existing_glb(self, tmp_path):
        gdstk = pytest.importorskip("gdstk")

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_BLENDER_SCRIPT")
        cell.add(gdstk.rectangle((0, 0), (10, 4), layer=10, datatype=0))

        gds_path = tmp_path / "test_blender_script.gds"
        lib.write_gds(gds_path.as_posix())
        source_glb = tmp_path / "test_blender_script.glb"
        source_glb.write_bytes(b"glTF")

        layout = load_gds_layout(gds_path)
        script_path = layout.export_blender_script(
            tmp_path / "layout_render.blender.py",
            source_glb=source_glb,
            render_path=tmp_path / "layout_render.png",
            camera_preset="isometric",
        )

        script = script_path.read_text(encoding="utf-8")
        assert source_glb.resolve().as_posix() in script
        assert "CAMERA_PRESET = 'isometric'" in script

    def test_gds_layout_exports_layer_report_csv_and_markdown(self, tmp_path):
        gdstk = pytest.importorskip("gdstk")

        class FoundryLayers:
            RIB = (10, 0)
            MT1 = (105, 0)

        lib = gdstk.Library()
        cell = lib.new_cell("TEST_REPORT")
        cell.add(gdstk.rectangle((0, 0), (10, 4), layer=10, datatype=0))
        cell.add(gdstk.rectangle((2, 1), (8, 3), layer=105, datatype=0))

        gds_path = tmp_path / "test_report.gds"
        lib.write_gds(gds_path.as_posix())

        layout = load_gds_layout(gds_path, layers=FoundryLayers())
        csv_text = layout.layer_report(format="csv")
        markdown_text = layout.layer_report(format="markdown")
        assert isinstance(csv_text, str)
        assert isinstance(markdown_text, str)
        csv_path = layout.export_layer_report(tmp_path / "test_report_layers.csv")
        markdown_path = layout.export_layer_report(tmp_path / "test_report_layers.md")

        assert "layer,datatype,name,style_source" in csv_text
        assert "RIB" in csv_text
        assert "MT1" in csv_text
        assert markdown_text.startswith("# Layer Assignment Sheet: test_report.gds")
        assert "| Layer | Datatype | Name |" in markdown_text
        assert "fallback" in markdown_text
        assert csv_path.read_text() == csv_text
        assert markdown_path.read_text() == markdown_text

    def test_material_catalog_includes_compound_semiconductors(self):
        presets = set(list_material_presets())

        assert {"germanium", "indium_phosphide", "gallium_arsenide", "indium_tin_oxide", "titanium_nitride", "air"}.issubset(presets)
        assert get_material_preset("germanium")["label"] == "Germanium"
        assert get_material_preset("indium_phosphide")["label"] == "Indium Phosphide"
        assert get_material_preset("gallium_arsenide")["label"] == "Gallium Arsenide"

    def test_threejs_html_includes_model_loader(self):
        scene = Scene(platform="free_space")
        scene.add(CustomModel("assets/mock-device.glb", center=(0, 0), label="Model"))
        html = scene.render_threejs()
        assert "GLTFLoader" in html
        assert "external_model" in html

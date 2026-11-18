"""Tests for multi-format publication bundles, templates, captions, manifests."""

from __future__ import annotations

import json

import pytest

from optodraw import (
    Laser,
    Lens,
    MicroringResonator,
    Mirror,
    OnChipPhotodetector,
    PublicationBundle,
    Scene,
    TemplateSpec,
    VerticalGratingCoupler,
    Waveguide,
    build_caption,
    build_publication_bundle,
    get_publication_template,
    list_publication_templates,
)


STUB_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 5"><rect width="10" height="5"/></svg>'


def _free_space_scene() -> Scene:
    scene = Scene(title="Michelson Pub Demo", width=180, height=100, platform="free_space")
    scene.add(Laser(center=(-60, 0), wavelength=633, label="Pump laser"))
    scene.add(Lens(center=(-20, 0), focal_length=50, aperture=12.0, label="L1"))
    scene.add(Mirror(center=(40, 0), angle=45, label="M1"))
    return scene


def _on_chip_scene() -> Scene:
    scene = Scene(title="Ring filter publication", platform="on_chip", width=220, height=110)
    gc_in = scene.add(VerticalGratingCoupler(center=(-90, 0), label="GC In"))
    gc_in._id = "gc_in"
    wg_in = scene.add(Waveguide(center=(-40, 0), length=40.0, label="WG1"))
    wg_in._id = "wg_in"
    ring = scene.add(MicroringResonator(center=(0, 12), ring_radius=10, label="Ring"))
    ring._id = "ring"
    wg_out = scene.add(Waveguide(center=(40, 0), length=40.0, label="WG2"))
    wg_out._id = "wg_out"
    pd = scene.add(OnChipPhotodetector(center=(90, 0), length=40.0, label="PD"))
    pd._id = "pd"
    scene.route((gc_in, "o1"), (wg_in, "o1"))
    scene.route((wg_in, "o2"), (wg_out, "o1"))
    scene.route((wg_out, "o2"), (pd, "o1"))
    return scene


class TestTemplateRegistry:
    def test_list_templates_contains_named_set(self):
        names = set(list_publication_templates())
        for required in (
            "single_figure",
            "two_panel_horizontal",
            "two_panel_vertical",
            "four_panel_grid",
            "device_plus_xsection",
        ):
            assert required in names

    def test_get_template_returns_spec(self):
        spec = get_publication_template("four_panel_grid")
        assert isinstance(spec, TemplateSpec)
        assert spec.panel_count == 4
        assert spec.rows == 2
        assert spec.columns == 2
        assert all(panel.role for panel in spec.panels)

    def test_unknown_template_raises(self):
        with pytest.raises(KeyError, match="Unknown publication template"):
            get_publication_template("ten_panel")


class TestBuildCaption:
    def test_caption_contains_components_and_routes(self):
        scene = _on_chip_scene()
        caption = build_caption(scene)
        assert "Ring filter publication" in caption
        assert "integrated photonic" in caption.lower()
        assert "Ring" in caption
        assert "Routes:" in caption
        assert "µm" in caption

    def test_free_space_caption_lists_devices(self):
        scene = _free_space_scene()
        caption = build_caption(scene)
        assert "free-space" in caption.lower()
        assert "Pump laser" in caption
        assert "L1" in caption

    def test_extra_notes_appended(self):
        scene = _free_space_scene()
        caption = build_caption(scene, extra_notes="See SI for alignment procedure.")
        assert "alignment procedure" in caption


class TestSingleFigureTemplate:
    def test_single_figure_bundle_emits_svg_tikz_json(self, tmp_path):
        scene = _free_space_scene()
        bundle = build_publication_bundle(
            scene,
            tmp_path,
            template="single_figure",
            formats=("svg", "tikz", "json"),
        )
        assert isinstance(bundle, PublicationBundle)
        assert bundle.template.name == "single_figure"
        assert set(bundle.primary_paths) == {"svg", "tikz", "json"}
        for fmt, path in bundle.primary_paths.items():
            assert path.exists(), f"{fmt} not written"

    def test_caption_and_manifest_written(self, tmp_path):
        scene = _free_space_scene()
        bundle = build_publication_bundle(
            scene,
            tmp_path,
            template="single_figure",
            formats=("svg",),
        )
        assert bundle.caption_path is not None and bundle.caption_path.exists()
        caption_text = bundle.caption_path.read_text(encoding="utf-8")
        assert "Michelson Pub Demo" in caption_text

        assert bundle.manifest_path is not None and bundle.manifest_path.exists()
        manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
        assert manifest["title"] == "Michelson Pub Demo"
        assert manifest["template"]["name"] == "single_figure"
        assert manifest["scene_hash_sha256"]
        assert len(manifest["scene_hash_sha256"]) == 64
        assert manifest["optodraw_version"]
        assert manifest["render_timestamp"]
        types = {entry["type"] for entry in manifest["components"]}
        assert {"Laser", "Mirror", "Lens"} <= types


class TestTwoPanelTemplates:
    def test_two_panel_horizontal_renders_two_panels(self, tmp_path):
        scene = _free_space_scene()
        bundle = build_publication_bundle(
            scene,
            tmp_path,
            template="two_panel_horizontal",
            formats=("svg", "json"),
        )
        assert len(bundle.panels) == 2
        labels = [panel["label"] for panel in bundle.panels]
        assert labels == ["(a)", "(b)"]
        assert bundle.panels[0]["row"] == 0 and bundle.panels[0]["column"] == 0
        assert bundle.panels[1]["column"] == 1
        for panel in bundle.panels:
            assert panel["paths"]["svg"].exists()
            assert panel["paths"]["json"].exists()

    def test_two_panel_vertical_stacks_panels(self, tmp_path):
        scene = _free_space_scene()
        bundle = build_publication_bundle(
            scene,
            tmp_path,
            template="two_panel_vertical",
            formats=("svg",),
        )
        assert len(bundle.panels) == 2
        assert bundle.panels[0]["row"] == 0
        assert bundle.panels[1]["row"] == 1

    def test_extra_scene_used_for_second_panel(self, tmp_path):
        scene_a = _free_space_scene()
        scene_b = Scene(title="Detail View", width=120, height=80, platform="free_space")
        scene_b.add(Lens(center=(0, 0), focal_length=10, aperture=6, label="Detail Lens"))
        bundle = build_publication_bundle(
            scene_a,
            tmp_path,
            template="two_panel_horizontal",
            formats=("svg",),
            extra_scenes=[scene_b],
        )
        assert bundle.panels[0]["scene_title"] == "Michelson Pub Demo"
        assert bundle.panels[1]["scene_title"] == "Detail View"


class TestFourPanelGrid:
    def test_four_panel_grid_emits_four_outputs(self, tmp_path):
        scene = _free_space_scene()
        bundle = build_publication_bundle(
            scene,
            tmp_path,
            template="four_panel_grid",
            formats=("svg",),
        )
        assert len(bundle.panels) == 4
        rows = {panel["row"] for panel in bundle.panels}
        columns = {panel["column"] for panel in bundle.panels}
        assert rows == {0, 1}
        assert columns == {0, 1}
        for panel in bundle.panels:
            assert panel["paths"]["svg"].exists()
            assert panel["width_mm"] < scene.width  # smaller than figure canvas


class TestDevicePlusXSection:
    def test_device_plus_xsection_needs_a_bundle(self, tmp_path):
        """The template has a cross-section panel, so an empty one is refused, before any file is written."""
        scene = _on_chip_scene()
        with pytest.raises(ValueError, match="requires a cross-section bundle"):
            build_publication_bundle(
                scene,
                tmp_path / "out",
                template="device_plus_xsection",
                formats=("svg",),
            )
        assert not (tmp_path / "out").exists()

    def test_device_plus_xsection_refuses_a_bundle_with_no_drawing(self, tmp_path):
        scene = _on_chip_scene()

        class _EmptyXSection:
            composite_path = tmp_path / "missing.svg"
            png_paths = {}
            layer_paths = {}
            manifest_path = None
            mode = "expert"

        with pytest.raises(FileNotFoundError, match="no existing composite"):
            build_publication_bundle(
                scene,
                tmp_path / "out",
                template="device_plus_xsection",
                formats=("svg",),
                xsection=_EmptyXSection(),
            )

    def test_device_plus_xsection_attaches_bundle(self, tmp_path):
        scene = _on_chip_scene()

        composite_path = tmp_path / "ext_composite.svg"
        composite_path.write_text(STUB_SVG, encoding="utf-8")
        ext_manifest = tmp_path / "ext_manifest.json"
        ext_manifest.write_text(json.dumps({"process": "stub"}), encoding="utf-8")

        class _DummyXSection:
            def __init__(self):
                self.composite_path = composite_path
                self.layer_paths = {}
                self.manifest_path = ext_manifest
                self.png_paths = {}
                self.mode = "expert"

        bundle = build_publication_bundle(
            scene,
            tmp_path / "out",
            template="device_plus_xsection",
            formats=("svg", "json"),
            xsection=_DummyXSection(),
        )
        # The bundle is self-contained: the cross-section files are copied into it,
        # and the manifest names them relative to the bundle folder.
        out_dir = tmp_path / "out"
        device_panel, xsection_panel = bundle.panels
        assert device_panel["role"] == "device"
        assert device_panel["paths"]["svg"].exists()
        assert xsection_panel["role"] == "xsection"
        copied_svg = xsection_panel["paths"]["svg"]
        copied_json = xsection_panel["paths"]["json"]
        assert copied_svg.parent == out_dir and copied_json.parent == out_dir
        assert copied_svg.read_text(encoding="utf-8") == STUB_SVG
        assert json.loads(copied_json.read_text(encoding="utf-8")) == {"process": "stub"}
        assert composite_path.exists()                      # the source is copied, not moved

        manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
        assert manifest["xsection"]["composite"] == copied_svg.name
        assert manifest["xsection"]["manifest"] == copied_json.name
        assert manifest["xsection"]["mode"] == "expert"


class TestProvenanceManifest:
    def test_components_recorded_with_positions(self, tmp_path):
        scene = _on_chip_scene()
        bundle = build_publication_bundle(
            scene,
            tmp_path,
            template="single_figure",
            formats=("svg",),
        )
        manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
        types = [c["type"] for c in manifest["components"]]
        assert "MicroringResonator" in types
        assert "VerticalGratingCoupler" in types
        # Routes are not skipped from component log
        assert "WaveguideRoute" in types

    def test_extras_propagated_to_manifest(self, tmp_path):
        scene = _free_space_scene()
        bundle = build_publication_bundle(
            scene,
            tmp_path,
            template="single_figure",
            formats=("svg",),
            extras={"figure_number": "1", "doi": "10.0/example"},
        )
        manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
        assert manifest["extras"]["figure_number"] == "1"
        assert manifest["extras"]["doi"] == "10.0/example"

    def test_custom_caption_overrides_autobuilder(self, tmp_path):
        scene = _free_space_scene()
        bundle = build_publication_bundle(
            scene,
            tmp_path,
            template="single_figure",
            formats=("svg",),
            caption="Custom caption used for the figure.",
        )
        assert bundle.caption_path.read_text(encoding="utf-8") == "Custom caption used for the figure."


class TestFormatValidation:
    def test_unsupported_format_raises(self, tmp_path):
        scene = _free_space_scene()
        with pytest.raises(ValueError, match="Unsupported publication bundle format"):
            build_publication_bundle(
                scene,
                tmp_path,
                template="single_figure",
                formats=("svg", "pdf"),
            )

    def test_scene_size_restored_after_bundle(self, tmp_path):
        scene = Scene(title="Original Dims", width=200, height=120)
        scene.add(Laser(center=(0, 0)))
        build_publication_bundle(
            scene,
            tmp_path,
            template="two_panel_horizontal",
            formats=("svg",),
        )
        assert scene.width == pytest.approx(200.0)
        assert scene.height == pytest.approx(120.0)


class TestComposedFigure:
    def test_template_makes_a_page(self):
        from optodraw import Page

        scene = _on_chip_scene()
        page = Page.from_template(get_publication_template("two_panel_horizontal"), [scene, scene], width_mm=120.0)
        insets = [n for n in page.walk() if type(n).__name__ == "Inset"]
        assert len(insets) == 2
        assert insets[0].box()[1] == pytest.approx(insets[1].box()[1], abs=1e-3)      # one row, one shared height
        assert insets[0].w_mm == pytest.approx(insets[1].w_mm, rel=1e-6)              # shares 0.5 and 0.5 of the row
        assert insets[0].box()[2] < insets[1].box()[0]
        assert page.width_mm == 120.0

    def test_width_fraction_sets_the_share(self):
        from optodraw import Page, PanelSpec

        template = TemplateSpec(name="uneven", description="", columns=2, panels=(
            PanelSpec(name="a", width_fraction=0.25, column=0), PanelSpec(name="b", width_fraction=0.75, column=1)))
        scene = _on_chip_scene()
        page = Page.from_template(template, [scene, scene], width_mm=100.0)
        first, second = [n for n in page.walk() if type(n).__name__ == "Inset"]
        assert second.w_mm / first.w_mm == pytest.approx(3.0, rel=1e-3)

    def test_template_rows_stack(self):
        from optodraw import Page

        scene = _on_chip_scene()
        page = Page.from_template(get_publication_template("four_panel_grid"), [scene] * 4, width_mm=120.0)
        tops = sorted({round(n.box()[3], 2) for n in page.walk() if type(n).__name__ == "Inset"})
        assert len(tops) == 2

    def test_bundle_writes_one_composed_figure(self, tmp_path):
        bundle = build_publication_bundle(_on_chip_scene(), tmp_path, template="two_panel_horizontal",
                                          formats=("svg",), stem="demo")
        figure = tmp_path / "demo_figure.svg"
        assert figure.is_file() and "<svg" in figure.read_text(encoding="utf-8")
        assert bundle.figure_path == figure
        manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
        assert manifest["figure"] == "demo_figure.svg"
        assert (tmp_path / "demo_left.svg").is_file() and (tmp_path / "demo_right.svg").is_file()

    def test_bundle_with_a_cross_section_composes(self, tmp_path):
        composite = tmp_path / "x.svg"
        composite.write_text(STUB_SVG, encoding="utf-8")

        class _X:
            composite_path = composite
            layer_paths = {}
            manifest_path = None
            png_paths = {}
            mode = "expert"

        bundle = build_publication_bundle(_on_chip_scene(), tmp_path / "out", template="device_plus_xsection",
                                          formats=("svg",), xsection=_X(), stem="demo")
        assert bundle.figure_path.is_file()

    def test_a_section_png_composes_as_a_drawn_picture(self, tmp_path):
        from PIL import Image as PilImage

        from optodraw import figure_rasters

        composite = tmp_path / "x.png"
        PilImage.new("RGB", (400, 200), "white").save(composite)

        class _X:
            composite_path = None
            layer_paths = {}
            manifest_path = None
            png_paths = {"composite": composite}
            mode = "expert"

        bundle = build_publication_bundle(_on_chip_scene(), tmp_path / "out", template="device_plus_xsection",
                                          formats=("svg",), xsection=_X(), stem="demo")
        assert [kind for kind, _ in figure_rasters(bundle.figure_path)] == ["drawn"]   # a drawn section, as pixels

    def test_single_figure_writes_no_extra_file(self, tmp_path):
        bundle = build_publication_bundle(_on_chip_scene(), tmp_path, template="single_figure",
                                          formats=("svg",), stem="demo")
        assert bundle.figure_path is None
        assert not (tmp_path / "demo_figure.svg").exists()
        assert "figure" not in json.loads(bundle.manifest_path.read_text(encoding="utf-8"))


def _bench():
    from optodraw import Beam, Photodiode, Polarizer, QuarterWavePlate

    scene = Scene(title="Polarization bench", width=160, height=60, platform="free_space")
    laser = scene.add(Laser(center=(-60, 0), wavelength=633))
    pol = scene.add(Polarizer(center=(-20, 0), axis_angle=0.0))
    plate = scene.add(QuarterWavePlate(center=(10, 0), design_wavelength_nm=633.0, fast_axis_angle=45.0))
    det = scene.add(Photodiode(center=(50, 0)))
    scene.add(Beam.through(laser, pol, plate, det, wavelength=633))
    return scene


class TestComposedFigureAgreesWithPanels:
    def test_text_prints_at_the_preset_size(self, tmp_path):
        from xml.etree import ElementTree as ET

        from optodraw.check import _read_page

        build_publication_bundle(_free_space_scene(), tmp_path, template="two_panel_horizontal", formats=("svg",),
                                 stem="demo", preset="single_column")
        texts = _read_page(ET.parse(tmp_path / "demo_figure.svg").getroot(), "demo_figure.svg").texts
        names = [t for t in texts if t.words in ("Pump laser", "L1", "M1")]
        assert names and all(t.pt == pytest.approx(8.0, abs=0.1) for t in names)    # the preset's 8 pt, as the panels
        # (_fitted_svg settles the label size in four passes: within 1 percent)

    def test_the_view_reaches_the_composed_figure(self, tmp_path):
        for view, art in (("2d", True), ("1d", False)):
            out = tmp_path / view
            build_publication_bundle(_free_space_scene(), out, template="two_panel_horizontal", formats=("svg",),
                                     stem="demo", view=view)
            assert ("data-art" in (out / "demo_left.svg").read_text(encoding="utf-8")) is art
            assert ("data-art" in (out / "demo_figure.svg").read_text(encoding="utf-8")) is art

    def test_polarization_reaches_the_composed_figure(self, tmp_path):
        for pol, marks in ((True, True), (False, False)):
            out = tmp_path / str(pol)
            build_publication_bundle(_bench(), out, template="two_panel_horizontal", formats=("svg",), stem="demo",
                                     include_polarization=pol)
            assert ("<ellipse" in (out / "demo_left.svg").read_text(encoding="utf-8")) is marks
            assert ("<ellipse" in (out / "demo_figure.svg").read_text(encoding="utf-8")) is marks

    def test_labels_become_the_letters(self, tmp_path):
        from optodraw import Page

        scene = _on_chip_scene()
        page = Page.from_template(get_publication_template("two_panel_horizontal"), [scene, scene], width_mm=120.0)
        svg = page.svg()
        assert ">(a)</text>" in svg and ">(b)</text>" in svg and ">a</text>" not in svg

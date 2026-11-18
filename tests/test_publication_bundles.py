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
    VerticalGratingCoupler,
    Waveguide,
    build_caption,
    build_publication_bundle,
    get_publication_template,
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


    def test_unknown_template_raises(self):
        with pytest.raises(KeyError, match="Unknown publication template"):
            get_publication_template("ten_panel")


class TestBuildCaption:


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


class TestTwoPanelTemplates:


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


class TestComposedFigure:


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
        # (_fitted_svg settles the label size in four passes: within 1 percent)


    def test_polarization_reaches_the_composed_figure(self, tmp_path):
        for pol, marks in ((True, True), (False, False)):
            out = tmp_path / str(pol)
            build_publication_bundle(_bench(), out, template="two_panel_horizontal", formats=("svg",), stem="demo",
                                     include_polarization=pol)
            assert ("<ellipse" in (out / "demo_left.svg").read_text(encoding="utf-8")) is marks
            assert ("<ellipse" in (out / "demo_figure.svg").read_text(encoding="utf-8")) is marks


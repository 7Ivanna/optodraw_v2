"""Tests for expanded free-space optics components."""

import pytest

from optodraw import describe_component, list_components
from optodraw.components.optics import (
    AOM,
    AsphericLens,
    BeamExpanderTelescope,
    Breadboard,
    CMOSCamera,
    CameraSensor,
    CryostatWindow,
    CylindricalLens,
    DMD,
    EMCCD,
    EOM,
    FourFSystem,
    GalvoMirror,
    KinematicMount,
    Monochromator,
    NonPolarizingBeamSplitter,
    OpticalTable,
    PowerMeter,
    PBS,
    RotationStage,
    RightAnglePrism,
    SPADArray,
    SpectrometerSlit,
    Telescope,
    TranslationStage,
    VacuumChamber,
    WedgePlate,
)

NEW_OPTICS = {
    "PBS": (PBS, 4, "polarizing_beam_splitter"),
    "NonPolarizingBeamSplitter": (NonPolarizingBeamSplitter, 4, "non_polarizing_beam_splitter"),
    "RightAnglePrism": (RightAnglePrism, 2, "right_angle_prism"),
    "WedgePlate": (WedgePlate, 2, "wedge_plate"),
    "BeamExpanderTelescope": (BeamExpanderTelescope, 2, "beam_expander_telescope"),
    "AsphericLens": (AsphericLens, 2, "aspheric_lens"),
    "CylindricalLens": (CylindricalLens, 2, "cylindrical_lens"),
    "Telescope": (Telescope, 2, "telescope"),
    "FourFSystem": (FourFSystem, 3, "four_f_system"),
}


NEW_LAB_OPTICS = {
    "GalvoMirror": (GalvoMirror, 2, "galvo_mirror"),
    "AOM": (AOM, 2, "acousto_optic_modulator"),
    "EOM": (EOM, 3, "electro_optic_modulator"),          # in, out and the RF drive
    "DMD": (DMD, 2, "digital_micromirror_device"),
    "CameraSensor": (CameraSensor, 2, "camera_sensor"),
    "CMOSCamera": (CMOSCamera, 2, "cmos_camera"),
    "EMCCD": (EMCCD, 2, "emccd_camera"),
    "SPADArray": (SPADArray, 2, "spad_array"),
    "PowerMeter": (PowerMeter, 2, "power_meter"),
    "OpticalTable": (OpticalTable, 2, "optical_table"),
    "Breadboard": (Breadboard, 2, "optical_table"),
}


NEW_MOTION_OPTICS = {
    "TranslationStage": (TranslationStage, 2, "translation_stage"),
    "RotationStage": (RotationStage, 2, "rotation_stage"),
    "KinematicMount": (KinematicMount, 2, "kinematic_mount"),
    "CryostatWindow": (CryostatWindow, 2, "cryostat_window"),
    "VacuumChamber": (VacuumChamber, 2, "vacuum_chamber"),
    "SpectrometerSlit": (SpectrometerSlit, 2, "spectrometer_slit"),
    "Monochromator": (Monochromator, 2, "monochromator"),
}


class TestExpandedOpticsInstantiation:


    @pytest.mark.parametrize("registry_name,spec", NEW_OPTICS.items())
    def test_geometry_keys(self, registry_name, spec, assert_1d_symbol):
        cls, _, _ = spec
        component = cls()
        geometry_2d = component.geometry_2d()
        geometry_3d = component.geometry_3d()

        assert_1d_symbol(component)
        assert geometry_2d
        assert geometry_2d.get("type") in {"group", "path", "rect", "polyline"}
        assert geometry_3d["shape"] in {"group", "extruded_polygon", "box", "cylinder"}

    @pytest.mark.parametrize("registry_name,spec", NEW_OPTICS.items())
    def test_physics_metadata(self, registry_name, spec):
        cls, _, component_key = spec
        metadata = cls().physics_metadata()
        assert metadata["domain"] == "free_space"
        assert metadata["component"] == component_key

    @pytest.mark.parametrize("registry_name", NEW_OPTICS.keys())
    def test_registry_presence(self, registry_name):
        optics = list_components(category="optics")
        assert registry_name in optics
        info = describe_component(registry_name)
        assert info["platform"] == "free_space"
        assert info["category"] == "optics"


class TestLabSystemOpticsInstantiation:


    @pytest.mark.parametrize("registry_name,spec", NEW_LAB_OPTICS.items())
    def test_geometry_and_metadata(self, registry_name, spec, assert_1d_symbol):
        cls, _, component_key = spec
        component = cls()
        geometry_2d = component.geometry_2d()
        geometry_3d = component.geometry_3d()

        assert_1d_symbol(component)
        assert geometry_2d
        assert geometry_2d.get("type") in {"group", "path", "rect", "polyline"}
        assert geometry_3d["shape"] in {"group", "extruded_polygon", "box", "cylinder"}
        assert component.physics_metadata()["component"] == component_key

    @pytest.mark.parametrize("registry_name", NEW_LAB_OPTICS.keys())
    def test_registry_presence(self, registry_name):
        optics = list_components(category="optics")
        assert registry_name in optics
        info = describe_component(registry_name)
        assert info["platform"] == "free_space"
        assert info["category"] == "optics"


class TestMotionAndInstrumentOpticsInstantiation:


    @pytest.mark.parametrize("registry_name,spec", NEW_MOTION_OPTICS.items())
    def test_geometry_and_metadata(self, registry_name, spec, assert_1d_symbol):
        cls, _, component_key = spec
        component = cls()
        geometry_2d = component.geometry_2d()
        geometry_3d = component.geometry_3d()

        assert_1d_symbol(component)
        assert geometry_2d
        assert geometry_2d.get("type") in {"group", "path", "rect", "polyline"}
        assert geometry_3d["shape"] in {"group", "extruded_polygon", "box", "cylinder"}
        assert component.physics_metadata()["component"] == component_key


class TestExpandedOpticsSerialization:
    def test_beam_expander_to_dict_includes_magnification(self):
        component = BeamExpanderTelescope(input_aperture=2.0, output_aperture=10.0, length=20.0)
        data = component.to_dict()
        assert data["type"] == "BeamExpanderTelescope"
        assert data["input_aperture"] == 2.0
        assert data["output_aperture"] == 10.0
        assert data["magnification"] == pytest.approx(5.0)
        assert "in" in data["ports"]
        assert "out" in data["ports"]

    def test_wedge_plate_to_dict_includes_wedge_angle(self):
        component = WedgePlate(wedge_angle_deg=3.5)
        data = component.to_dict()
        assert data["wedge_angle_deg"] == 3.5
        assert data["refractive_index"] == 1.52


    def test_four_f_system_to_dict_includes_relay_metadata(self):
        component = FourFSystem(focal_length_1=25.0, focal_length_2=50.0, aperture=12.0)
        data = component.to_dict()
        assert data["type"] == "FourFSystem"
        assert data["lens_spacing"] == 75.0
        assert data["system_length"] == 150.0
        assert data["magnification"] == pytest.approx(-2.0)
        assert set(data["ports"]) == {"object", "image", "fourier"}

    def test_aspheric_lens_serializes_asphere_coefficients(self):
        component = AsphericLens(asphere_coefficients=(1e-4, -2e-7), numerical_aperture=0.42)
        data = component.to_dict()
        assert data["asphere_coefficients"] == [1e-4, -2e-7]
        assert data["numerical_aperture"] == 0.42

    def test_optical_table_to_dict_includes_hole_grid_metadata(self):
        component = OpticalTable(length=80.0, width=50.0, thickness=3.0, hole_pitch=2.5, include_holes=False)
        data = component.to_dict()
        assert data["type"] == "OpticalTable"
        assert data["length"] == 80.0
        assert data["width"] == 50.0
        assert data["thickness"] == 3.0
        assert data["hole_pitch"] == 2.5
        assert data["include_holes"] is False



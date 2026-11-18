"""Electro-optic drive and readout scene recipes."""

from __future__ import annotations

from typing import Any

from optodraw.components.electronics import SignalArrow
from optodraw.components.onchip import ADC, DACDriver, MZM, OnChipPhotodetector, TIA
from optodraw.core.scene import Scene


def build_modulator_drive_chain(
    title: str = "Modulator Drive Chain",
    *,
    width: float = 320,
    height: float = 160,
    drive_style: str = "gsg",
    **kwargs,
) -> dict[str, Any]:
    """Build DACDriver → MZM electrical drive with optical path stub metadata."""

    scene = Scene(title=title, width=width, height=height, platform="on_chip")
    driver = scene.add(
        DACDriver(
            center=kwargs.get("driver_center", (-120, 40)),
            label=kwargs.get("driver_label", "DAC"),
        )
    )
    mod = scene.add(
        MZM(
            center=kwargs.get("mzm_center", (-20, 0)),
            drive_style=drive_style,
            label=kwargs.get("mzm_label", "MZM"),
        )
    )

    # Leave the DAC east on unique first-leg lengths, then drop to each GSG y
    # on that unique x. A vertical at the shared GSG x would T-join the other
    # net's final eastbound run and short the drive.
    ground_pad = "gnd1" if drive_style == "gsg" else "gnd"
    gnd_port = mod.world_ports()[ground_pad]
    sig_y = float(mod.world_ports()["sig"].center.y)
    pos_route = scene.route(
        (driver, "e3"),
        (mod, "sig"),
        kind="electrical",
        path_type="L",
        start_straight_length=8.0,
        end_straight_length=3.0,
        width=1.4,
        steps=[{"y": sig_y}],
        signal="rf",
    )
    neg_route = scene.route(
        (driver, "e4"),
        (mod, ground_pad),
        kind="electrical",
        path_type="L",
        start_straight_length=14.0,
        end_straight_length=3.0,
        width=2.4,
        steps=[{"y": float(gnd_port.center.y)}],
        signal="rf",
    )
    drive_routes = [pos_route, neg_route]

    rf_arrow = scene.add(
        SignalArrow(
            center=kwargs.get("drive_arrow_center", (-70, 52)),
            start=(-18, 0),
            end=(18, 0),
            signal="rf",
            label=kwargs.get("drive_arrow_label", "RF drive"),
        )
    )

    optical_stub = {
        "input_port": "o1",
        "output_port": "o3",
        "modulator": getattr(mod, "component_type", "MZM"),
        "drive_style": drive_style,
        "wavelength_nm": float(kwargs.get("wavelength_nm", 1550.0)),
        "Vpi_stub_v": float(kwargs.get("Vpi", 4.0)),
    }

    return {
        "scene": scene,
        "driver": driver,
        "mzm": mod,
        "routes": drive_routes,
        "annotations": [rf_arrow],
        "optical_stub": optical_stub,
    }


def build_detector_readout_chain(
    title: str = "Detector Readout Chain",
    *,
    width: float | None = None,
    height: float | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Build OnChipPhotodetector → TIA → ADC with SignalArrow annotations."""

    scene = Scene(
        title=title,
        width=360 if width is None else width,
        height=160 if height is None else height,
        platform="on_chip",
    )
    pd = scene.add(
        OnChipPhotodetector(
            center=kwargs.get("pd_center", (20, 0)),
            angle=kwargs.get("pd_angle", 0),
            label=kwargs.get("pd_label", "PD"),
        )
    )
    tia = scene.add(
        TIA(
            center=kwargs.get("tia_center", (100, 35)),
            label=kwargs.get("tia_label", "TIA"),
        )
    )
    adc = scene.add(
        ADC(
            center=kwargs.get("adc_center", (180, 35)),
            label=kwargs.get("adc_label", "ADC"),
        )
    )

    pd_route = scene.route((pd, "e1"), (tia, "e1"), kind="electrical", width=1.4, signal="photocurrent")
    tia_route = scene.route((tia, "e2"), (adc, "e1"), kind="electrical", width=1.4, signal="analog")
    readout_routes = [pd_route, tia_route]

    current_arrow = scene.add(
        SignalArrow(
            center=kwargs.get("current_arrow_center", (60, 52)),
            start=(-14, 0),
            end=(14, 0),
            signal="current",
            label=kwargs.get("current_arrow_label", "I_photo"),
        )
    )
    voltage_arrow = scene.add(
        SignalArrow(
            center=kwargs.get("voltage_arrow_center", (140, 52)),
            start=(-14, 0),
            end=(14, 0),
            signal="voltage",
            label=kwargs.get("voltage_arrow_label", "V_out"),
        )
    )
    digital_arrow = scene.add(
        SignalArrow(
            center=kwargs.get("digital_arrow_center", (180, 10)),
            start=(0, -10),
            end=(0, 10),
            angle=90,
            signal="digital",
            label=kwargs.get("digital_arrow_label", "ADC"),
        )
    )
    annotations = [current_arrow, voltage_arrow, digital_arrow]

    # The ADC is 42 wide and sits at x=180, so a hand-picked 360 frame cut 21
    # units off it in every export. The chain knows its own extent; the frame
    # follows it, unless the caller asked for a size.
    if width is None and height is None:
        scene.fit_frame()

    return {
        "scene": scene,
        "photodetector": pd,
        "tia": tia,
        "adc": adc,
        "routes": readout_routes,
        "annotations": annotations,
    }


__all__ = ["build_modulator_drive_chain", "build_detector_readout_chain"]

"""Generate visual galleries of native electronics and package components."""

from pathlib import Path

from optodraw import (
    ADCBlock,
    BalancedPhotodetector,
    CoherentReceiver,
    DAC,
    EIC,
    ElectricalPad,
    GSGProbePad,
    HeaterPad,
    ElectricalIOBank,
    MEMSActuator,
    MetalRoute,
    Microcontroller,
    PCB,
    ReceiverMacro,
    RFDriver,
    Scene,
    SignalArrow,
    TIABlock,
    TransmitterMacro,
)


def build_gallery(*, visual_style: str = "publication") -> Scene:
    scene = Scene(title="Electronics Component Gallery", width=250, height=275, platform="mixed")
    columns = [-96, -48, 0, 48, 96]
    rows = [108, 72, 36, 0, -36, -72, -108]
    components = [
        RFDriver(visual_style=visual_style, label="RF driver"),
        Microcontroller(visual_style=visual_style, package_style="qfp", pin_count=12, label="uC QFP"),
        EIC(visual_style=visual_style, package_style="qfn", role="eic", label="EIC QFN"),
        EIC(visual_style=visual_style, package_style="bga", role="processor", label="EIC BGA"),
        EIC(visual_style=visual_style, package_style="die", role="tia", label="Bare die"),
        DAC(visual_style=visual_style, label="DAC"),
        ADCBlock(visual_style=visual_style, label="ADC"),
        ElectricalIOBank(visual_style=visual_style, visual_scale=0.72, count=6, bank_kind="mixed", signal_kinds=("dc", "rf", "clock", "digital", "dc", "rf"), label="I/O bank"),
        BalancedPhotodetector(visual_style=visual_style, visual_scale=0.72, label="balanced PD"),
        CoherentReceiver(visual_style=visual_style, visual_scale=0.55, label="coherent Rx"),
        TransmitterMacro(visual_style=visual_style, visual_scale=0.5, label="Tx macro"),
        ReceiverMacro(visual_style=visual_style, visual_scale=0.58, label="Rx macro"),
        TIABlock(visual_style=visual_style, visual_scale=0.78, label="TIA op-amp"),
        TIABlock(visual_style=visual_style, visual_scale=0.78, mode="integrator", label="integrator"),
        MEMSActuator(visual_style=visual_style, label="MEMS"),
        PCB(visual_style=visual_style, visual_scale=0.62, label="PCB"),
        ElectricalPad(label="pad"),
        GSGProbePad(label="GSG"),
        MetalRoute(points=((-14, -5), (-4, 5), (14, 5)), label="route"),
        HeaterPad(label="heater"),
        SignalArrow(signal="digital", label="signal"),
    ]
    for index, component in enumerate(components):
        row_index, column_index = divmod(index, len(columns))
        component.transform.position.x = columns[column_index]
        component.transform.position.y = rows[row_index]
        scene.add(component)
    return scene


def main() -> None:
    out = Path(__file__).parent / "generated"
    out.mkdir(parents=True, exist_ok=True)
    scene = build_gallery()
    symbolic_scene = build_gallery(visual_style="symbolic")
    scene.render_svg(out / "electronics_component_gallery.svg")
    symbolic_scene.render_svg(out / "electronics_component_gallery_symbolic.svg")
    (out / "electronics_component_gallery.html").write_text(
        scene.render_threejs(show_grid=True, camera_distance=210),
        encoding="utf-8",
    )
    print(out / "electronics_component_gallery.html")
    print(out / "electronics_component_gallery.svg")
    print(out / "electronics_component_gallery_symbolic.svg")


if __name__ == "__main__":
    main()

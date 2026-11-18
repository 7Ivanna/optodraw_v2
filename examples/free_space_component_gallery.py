"""Generate visual galleries of native free-space optics components."""

from pathlib import Path

from optodraw import (
    AOM,
    ApertureStop,
    BeamSplitter,
    BiconcaveMirror,
    Breadboard,
    CMOSCamera,
    ConcaveMirror,
    ConvexMirror,
    CryostatWindow,
    DMD,
    DichroicMirror,
    EOM,
    FiberCollimator,
    FiberLaser,
    FiberPort,
    Filter,
    GalvoMirror,
    Grating,
    HalfWavePlate,
    Iris,
    KinematicMount,
    Lens,
    Mirror,
    Monochromator,
    NonPolarizingBeamSplitter,
    Objective,
    PowerMeter,
    PBS,
    Pinhole,
    Polarizer,
    Prism,
    QuarterWavePlate,
    RotationStage,
    SLM,
    Scene,
    SpectrometerSlit,
    TranslationStage,
    VacuumChamber,
)


def build_gallery() -> Scene:
    scene = Scene(title="Free-space Optics Gallery", width=190, height=150, platform="free_space")
    columns = [-56, -28, 0, 28, 56]
    components = [
        Lens(label="Lens"),
        Mirror(angle=20, label="Mirror"),
        ConcaveMirror(angle=20, label="Concave M"),
        ConvexMirror(angle=20, label="Convex M"),
        BiconcaveMirror(angle=20, label="Diconcave M"),
        BeamSplitter(label="Plate BS"),
        Filter(label="Filter"),
        Grating(label="Grating"),
        Objective(label="Objective"),
        Prism(label="Prism"),
        Polarizer(label="Polarizer"),
        HalfWavePlate(label="HWP"),
        QuarterWavePlate(label="QWP"),
        PBS(label="PBS"),
        NonPolarizingBeamSplitter(label="NPBS"),
        DichroicMirror(angle=-15, cutoff_wavelength=650, label="Dichroic"),
        FiberPort(label="Fiber"),
        FiberCollimator(label="Collimator"),
        FiberLaser(label="Fiber Laser"),
        Iris(label="Iris"),
        Pinhole(label="Pinhole"),
        ApertureStop(label="Stop"),
        SLM(label="SLM"),
        GalvoMirror(label="Galvo"),
        AOM(label="AOM"),
        EOM(label="EOM"),
        DMD(label="DMD"),
        CMOSCamera(label="CMOS"),
        PowerMeter(label="Power Meter"),
        Breadboard(label="Breadboard"),
        TranslationStage(label="Translation Stage"),
        RotationStage(label="Rotation Stage"),
        KinematicMount(label="Kinematic Mount"),
        CryostatWindow(label="Cryo Window"),
        VacuumChamber(label="Vacuum Chamber"),
        SpectrometerSlit(label="Spec Slit"),
        Monochromator(label="Monochromator"),
    ]
    row_count = (len(components) + len(columns) - 1) // len(columns)
    row_spacing = 24
    rows = [row_spacing * (row_count - 1) / 2.0 - index * row_spacing for index in range(row_count)]
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
    scene.render_svg(out / "free_space_component_gallery.svg")
    (out / "free_space_component_gallery.html").write_text(
        scene.render_threejs(show_grid=True, camera_distance=185),
        encoding="utf-8",
    )
    print(out / "free_space_component_gallery.html")
    print(out / "free_space_component_gallery.svg")


if __name__ == "__main__":
    main()
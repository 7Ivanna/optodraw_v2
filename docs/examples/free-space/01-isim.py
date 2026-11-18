# An instant structured illumination microscope, after Curd et al., Methods 88, 37-47 (2015), Fig. 1A
from optodraw import (AOM, Beam, BeamSplitter, CMOSCamera, Filter, GalvoMirror, HalfWavePlate, Laser, Lens,
                      Mirror, Objective, Periscope, Pinhole, Sample, Scene, WedgePlate)
from optodraw.layout import aim

scene = Scene(title="iSIM", platform="free_space")
scene.set_view_layout({"1d": {"spacing": 1.0}, "3d": {"spacing": "auto"}})   # 1D follows the figure; 3D spreads
at = {}


def put(key, part, side=None):
    """Place a part (positions from the figure, shifted so the drawing centres on the origin)."""
    part.transform.position.x -= 103
    part.transform.position.y += 65
    if side:
        part.label_side = side
    at[key] = scene.add(part)
    return at[key]


# excitation: the 488 nm laser, up through the AOTF and the periscope, expanded, to the scanning mirror
put("l488", Laser(center=(10, -90), wavelength=488, label="488 nm laser"))
put("hwp488", HalfWavePlate(center=(22, -90), label="λ/2"), "bottom")
put("dm1", BeamSplitter(center=(33, -90), dichroic=True, cutoff_wavelength=520, label="Dichroic mirror 1"), "right")
put("l561", Laser(center=(10, -121), wavelength=561, label="561 nm laser"))
put("hwp561", HalfWavePlate(center=(22, -121), label="λ/2"), "bottom")
put("pm2", Mirror(center=(33, -108), angle=135, label="Plane mirror 2"), "right")
put("pm1", Mirror(center=(49, -121), angle=135, label="Plane mirror 1"), "right")
put("aotf", AOM(center=(33, -63), angle=90, label="AOTF"), "left")
put("periscope", Periscope(center=(33, -28), angle=90, output_angle_deg=50, rise=20, label="Plane mirror 3,4"), "left")
put("pm5", Mirror(center=(20, -17), label="Plane mirror 5"), "left")
put("be1", Lens(center=(43, -17), focal_length=45, label="Beam expander 1"))
put("be2", Lens(center=(88, -17), focal_length=400, aperture=16, label="Beam expander 2"))
# a second periscope, not in the paper, brings the beam down after the raised expander
put("return_periscope", Periscope(center=(118, -17), rise=-20, label="Return periscope"), "top")
put("pm6", Mirror(center=(148, -17), label="Plane mirror 6"), "right")
put("pm7", Mirror(center=(129, -9), label="Plane mirror 7"))
put("lenslets1", Lens(center=(129, -28), angle=90, focal_length=1.86, label="Lenslet array 1"), "right")
put("pinholes", Pinhole(center=(129, -34), angle=90, label="Pinhole array"), "right")
put("plate", WedgePlate(center=(129, -40), angle=90, label="Compensator plate"), "right")
put("dm2", BeamSplitter(center=(129, -48), dichroic=True, cutoff_wavelength=500, label="Dichroic mirror 2"), "right")
put("scan1", Lens(center=(129, -57), angle=90, label="Scan lens 1"), "right")
put("galvo", GalvoMirror(center=(129, -75), label="Scanning mirror"), "top-left")
put("scan2", Lens(center=(157, -75), label="Scan lens 2"))
put("pm8", Mirror(center=(182, -75), label="Plane mirror 8"))
put("pm9", Mirror(center=(172, -113), label="Plane mirror 9"), "left")
put("tube", Lens(center=(184, -113), focal_length=350, label="Tube lens"), "bottom")
put("pm_obj", Mirror(center=(210, -113)))
put("objective", Objective(center=(210, -92), angle=90, label="Objective"), "left")
put("sample", Sample(center=(210, -80), angle=90, label="Sample"))
# emission: back through the scanning mirror and dichroic 2, relayed, re-scanned onto the camera
put("relay1", Lens(center=(89, -48), label="Relay lens 1"))
put("pm10", Mirror(center=(45, -48), label="Plane mirror 10"), "top")
put("pm11", Mirror(center=(57, -40), label="Plane mirror 11"), "top")
put("relay2", Lens(center=(57, -61), angle=90, label="Relay lens 2"), "right")
put("pm12", Mirror(center=(57, -75), label="Plane mirror 12"), "bottom-left")
put("lenslets2", Lens(center=(70, -75), focal_length=0.93, label="Lenslet array 2"), "bottom")
put("scan3", Lens(center=(102, -75), label="Scan lens 3"))
put("scan4", Lens(center=(129, -105), angle=90, label="Scan lens 4"), "right")
put("filters", Filter(center=(129, -124), angle=90, label="Filter wheel"), "left")
put("camera", CMOSCamera(center=(129, -134), angle=-90, label="CMOS camera"), "bottom")

for key, a, b in (("pm1", "hwp561", "pm2"), ("pm2", "pm1", "dm1"), ("dm1", "l488", "aotf"),
                  ("pm5", "periscope", "be1"), ("pm6", "be2", "pm7"), ("pm7", "pm6", "lenslets1"),
                  ("dm2", "scan1", "relay1"), ("galvo", "scan1", "scan2"), ("pm8", "scan2", "pm9"),
                  ("pm9", "pm8", "tube"), ("pm_obj", "tube", "objective"), ("pm10", "relay1", "pm11"),
                  ("pm11", "pm10", "relay2"), ("pm12", "relay2", "lenslets2")):
    aim(at[key], at[a], at[b])
excitation = ["l488", "hwp488", "dm1", "aotf", "periscope", "pm5", "be1", "be2", "return_periscope", "pm6",
              "pm7", "lenslets1", "pinholes", "plate", "dm2", "scan1", "galvo", "scan2", "pm8", "pm9", "tube",
              "pm_obj", "objective", "sample"]
emission = ["galvo", "scan1", "dm2", "relay1", "pm10", "pm11", "relay2", "pm12", "lenslets2", "scan3", "galvo",
            "scan4", "filters", "camera"]
# Beam.through attaches the light at each part's faces: it climbs inside the periscopes
scene.add(Beam.through(*[at[k] for k in excitation], wavelength=488, width=1.0))
excitation561 = ["l561", "hwp561", "pm1", "pm2", *excitation[2:]]
scene.add(Beam.through(*[at[k] for k in excitation561], wavelength=561, width=0.8))
scene.add(Beam.through(*[at[k] for k in emission], wavelength=520, width=0.8))
scene.fit_frame(margin=10)
scene

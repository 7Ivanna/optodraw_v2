"""Free-space optics components (split into family modules)."""

# Shared helpers stay importable from the package root: sibling modules such as
# optodraw.components.instruments have always imported them from here.
from optodraw.components.optics._shared import (  # noqa: F401
	_set_common_free_space_fields,
)

from optodraw.components.optics.lenses import (
	Lens,
	AsphericLens,
	CylindricalLens,
	Telescope,
	FourFSystem,
	BeamExpanderTelescope,
)
from optodraw.components.optics.mirrors import (
	Mirror,
	FlipMirror,
	ConcaveMirror,
	ConvexMirror,
	BiconcaveMirror,
	BiconvexMirror,
	DichroicMirror,
	GalvoMirror,
)
from optodraw.components.optics.beamsplitters import (
	BeamSplitter,
	PartialMirror,
	PBS,
	NonPolarizingBeamSplitter,
)
from optodraw.components.optics.filters_modulators import (
	Filter,
	NDFilter,
	Grating,
	AOM,
	EOM,
	OpticalIsolator,
	OpticalChopper,
	NonlinearCrystal,
)
from optodraw.components.optics.polarization_optics import (
	GlanLaserPolarizer,
	Polarizer,
	Analyzer,
	WavePlate,
	HalfWavePlate,
	QuarterWavePlate,
	WedgePlate,
	BrewsterWindow,
	WollastonPrism,
)
from optodraw.components.optics.objectives_displays import (
	Objective,
	SLM,
	SpatialLightModulator,
	DMD,
)
from optodraw.components.optics.sensors import (
	CameraSensor,
	CMOSCamera,
	EMCCD,
	SPADArray,
	PowerMeter,
)
from optodraw.components.optics.fibers import (
	FiberPort,
	FiberCollimator,
	PolarizationController,
	FiberAmplifier,
	FiberCirculator,
	FiberCoupler,
	FiberSpool,
	VariableAttenuator,
)
from optodraw.components.optics.apertures_spectroscopy import (
	Iris,
	Pinhole,
	ApertureStop,
	SpectrometerSlit,
	Monochromator,
)
from optodraw.components.optics.prisms import (
	Prism,
	RightAnglePrism,
	Pentaprism,
	Retroreflector,
)
from optodraw.components.optics.optomech import (
	OpticalTable,
	Breadboard,
	Baseplate,
	Periscope,
	OpticalPost,
	BeamDump,
	LensTube,
	PlatformMount,
	TranslationStage,
	RotationStage,
	KinematicMount,
	CryostatWindow,
	VacuumChamber,
)

# Wave-2 parts: the Faraday rotator, the roof mirror and the mode cleaner.
from optodraw.components.optics.filters_modulators import FaradayRotator  # noqa: E402
from optodraw.components.optics.cavities import ModeCleaner  # noqa: E402
from optodraw.components.optics.mirrors import RoofMirror  # noqa: E402
# 30 mm cage-system parts, the stepper-motor mirror and the cryostat cabinet a bench sits on.
from optodraw.components.optics.cage import CageCube, CageRods, CageRightAngleMirror, CageTower, CageWavePlate, CryostatCabinet, MotorizedMirror  # noqa: E402

__all__ = [
	"Lens",
	"AsphericLens",
	"CylindricalLens",
	"Telescope",
	"FourFSystem",
	"Mirror",
	"FlipMirror",
	"ConcaveMirror",
	"ConvexMirror",
	"BiconcaveMirror",
	"BiconvexMirror",
	"BeamSplitter",
	"PartialMirror",
	"Filter",
	"NDFilter",
	"Grating",
	"Objective",
	"Prism",
	"GlanLaserPolarizer",
	"Polarizer",
	"Analyzer",
	"WavePlate",
	"HalfWavePlate",
	"QuarterWavePlate",
	"PBS",
	"NonPolarizingBeamSplitter",
	"DichroicMirror",
	"FiberPort",
	"FiberCollimator",
	"PolarizationController",
	"FiberAmplifier",
	"FiberCirculator",
	"FiberCoupler",
	"FiberSpool",
	"VariableAttenuator",
	"Iris",
	"Pinhole",
	"ApertureStop",
	"SLM",
	"SpatialLightModulator",
	"RightAnglePrism",
	"WedgePlate",
	"BeamExpanderTelescope",
	"GalvoMirror",
	"AOM",
	"EOM",
	"DMD",
	"CameraSensor",
	"CMOSCamera",
	"EMCCD",
	"SPADArray",
	"PowerMeter",
	"OpticalTable",
	"Breadboard",
	"Baseplate",
	"Periscope",
	"OpticalPost",
	"Retroreflector",
	"BeamDump",
	"OpticalChopper",
	"Pentaprism",
	"OpticalIsolator",
	"NonlinearCrystal",
	"WollastonPrism",
	"LensTube",
	"BrewsterWindow",
	"PlatformMount",
	"TranslationStage",
	"RotationStage",
	"KinematicMount",
	"CryostatWindow",
	"VacuumChamber",
	"SpectrometerSlit",
	"Monochromator",
	"FaradayRotator",
	"ModeCleaner",
	"RoofMirror",
	"CageCube",
	"CageRods",
	"CageRightAngleMirror",
	"CageWavePlate",
	"MotorizedMirror",
	"CageTower",
	"CryostatCabinet",
]

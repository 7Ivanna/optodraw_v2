# browser: no (the table and the plot need numpy and matplotlib)
# An MZI of two couplers simulated with fieldrt: imported S-parameters in a circuit
from optodraw import DirectionalCoupler, OnChipLaser, OnChipPhotodetector, Page, Scene, Source
from optodraw.animation_engine import spectrum
from optodraw.sparameters import SParameters

# a 2D directional coupler (gap 0.2 um, 10 um long) run in Meep on fieldrt: data/coupler_fieldrt.py
TABLE = SParameters.load("docs/examples/models/data/coupler_fieldrt.npz", source=Source(
    "simulated", "Meep on fieldrt, 2D effective index, 45 px/um, float64",
    "largest singular value 1.0043 at 30 px/um, 1.0020 at 45: grid error, converging; the file's meta has the rest"))

mzi = Scene(title="MZI of imported couplers", platform="on_chip")
laser = mzi.add(OnChipLaser(center=(-120, 7), label="Laser"))
split = mzi.add(DirectionalCoupler(center=(0, 0), label="Coupler"))
join = mzi.add(DirectionalCoupler(center=(150, 0), label="Coupler"))
split.model = join.model = TABLE                         # the table replaces each coupler's closed form
bar = mzi.add(OnChipPhotodetector(center=(270, 30), label="Bar"))
cross = mzi.add(OnChipPhotodetector(center=(270, -30), label="Cross", label_side="bottom"))
mzi.route((laser, "o1"), (split, "o1"), kind="waveguide")
mzi.route((split, "o3"), (join, "o1"), kind="waveguide")                       # the short arm
mzi.route((split, "o4"), (join, "o2"), kind="waveguide", path_type="manhattan",  # the long arm, 20 um longer
          steps=[{"y": -17.0}])
mzi.route((join, "o3"), (bar, "o1"), kind="waveguide", path_type="smooth")
mzi.route((join, "o4"), (cross, "o1"), kind="waveguide", path_type="smooth")
mzi.fit_frame(margin=6)

m = spectrum(mzi, start_nm=1500, stop_nm=1600, points=1001)
fig, ax = plt.subplots(figsize=(3.0, 1.9), layout="constrained")
ax.plot(m.wavelengths_nm, m.of(bar, "o1"), color="#0072B2", lw=0.9, label="bar")
ax.plot(m.wavelengths_nm, m.of(cross, "o1"), color="#D55E00", lw=0.9, label="cross")
ax.set(xlabel="Wavelength (nm)", ylabel="Power (norm.)", ylim=(0, 1.05), xticks=range(1500, 1601, 25))
ax.legend(frameon=False, fontsize=6, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
print("\n".join(m.notes))
imported = Page(width_mm=183)
imported.row([mzi, fig], shares=[0.6, None])
imported

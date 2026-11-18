# browser: no (the spectrum plot needs matplotlib)
# Ring spectra from sourced numbers: an all-pass and an add-drop ring on one chip
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from optodraw import MicroringResonator, OnChipLaser, OnChipPhotodetector, Page, Scene, Source, Sourced
from optodraw.animation_engine import spectrum

# a 480 x 220 nm silicon strip: n_g from the paper's n_eff and its slope, n_g = n_eff - lambda dn_eff/dlambda
N_G = Sourced(2.411 + 1.55 * 1.078, Source(
    "literature", "James et al., arXiv:2301.01689 (2023), sec. II-E: n_eff 2.411, dn_eff/dlambda -1.078 per um",
    "n_g at 1.55 um; the paper does not state the wavelength of its reference fringe"))
LOSS_DB_PER_UM = 2.4e-4                                  # 2.4 dB/cm, photonic wires
BOGAERTS = "Bogaerts et al., J. Lightwave Technol. 23, 401 (2005): 2.4 dB/cm for photonic wires"
KAPPA = Sourced(0.05, Source("model", note="a design value: over-coupled, so the resonances are wide enough to see"))


def sourced_ring(**kwargs):
    ring = MicroringResonator(**kwargs)
    trip = 2 * math.pi * ring.ring_radius                # the loop, um
    ring.group_index = N_G
    ring.round_trip_amplitude = Sourced(10 ** (-LOSS_DB_PER_UM * trip / 20), Source(
        "literature", BOGAERTS, f"amplitude after one {trip:.1f} um round trip"))
    ring.power_coupling = KAPPA
    if ring.add_drop:
        ring.drop_power_coupling = KAPPA
    return ring


chip = Scene(title="Two rings", platform="on_chip")
laser_a = chip.add(OnChipLaser(center=(-90, 50), label="Laser"))
allpass = chip.add(sourced_ring(center=(0, 50), label="All-pass"))
through_a = chip.add(OnChipPhotodetector(center=(90, 50), label="Through"))
laser_b = chip.add(OnChipLaser(center=(-90, -50), label="Laser", label_side="bottom"))
adddrop = chip.add(sourced_ring(center=(0, -50), add_drop=True, label="Add-drop"))
through_b = chip.add(OnChipPhotodetector(center=(90, -50), label="Through"))
drop_b = chip.add(OnChipPhotodetector(center=(-90, -5), angle=180, label="Drop"))
for a, b in (((laser_a, "o1"), (allpass, "o1")), ((allpass, "o2"), (through_a, "o1")),
             ((laser_b, "o1"), (adddrop, "o1")), ((adddrop, "o2"), (through_b, "o1")),
             ((adddrop, "o3"), (drop_b, "o1"))):
    chip.route(a, b, kind="waveguide", path_type="smooth")
chip.fit_frame(margin=6)

s = spectrum(chip, start_nm=1540, stop_nm=1560, points=2001)
plt.rcParams.update({"font.size": 6, "axes.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False})
fig, ax = plt.subplots(figsize=(3.0, 1.9), layout="constrained")
for part, colour, name in ((through_a, "#0072B2", "all-pass, through"), (through_b, "#E69F00", "add-drop, through"),
                           (drop_b, "#009E73", "add-drop, drop")):
    ax.plot(s.wavelengths_nm, s.of(part, "o1"), color=colour, lw=0.9, label=name)
ax.set(xlabel="Wavelength (nm)", ylabel="Power (norm.)", ylim=(0, 1.05), xticks=range(1540, 1561, 5))
ax.legend(frameon=False, fontsize=6, loc="center")
page = Page(width_mm=183)
page.row([chip, fig])
print("\n".join(s.notes))
page

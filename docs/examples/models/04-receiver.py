# browser: no (the signal chain and the plot need numpy and matplotlib)
# A receiver that computes its signal: drop light, photodiode, the TIA drawn as an op amp, a 12-bit ADC, the scope
import numpy as np
from optodraw import ADCBlock, Capacitor, ElectricalPad, Ground, OpAmp, Oscilloscope, Resistor
from optodraw.animation_engine import Waveform, signal_chain

VIVIEN = Source("literature", "Vivien et al., Opt. Express 20, 1096 (2012): 0.8 A/W at 1550 nm, Ge waveguide diode")
rx = Scene(title="A receiver", platform="on_chip")
laser = rx.add(OnChipLaser(center=(-150, 12.2), label="Laser", power_mw=Sourced(0.1, Source(
    "model", note="a design value: the drop peak fills most of the ADC range"))))
ring = rx.add(sourced_ring(center=(0, 0), add_drop=True, with_heater=True, label="Ring"))
ring.flip_vertical = True                                # in on the top bus, the drop on the lower left
pd = rx.add(OnChipPhotodetector(center=(-60, -60), angle=-90, label="PD", label_side="left",   # o1 up, pads down
                                responsivity_a_per_w=Sourced(0.8, VIVIEN)))
bias = rx.add(ElectricalPad(center=(-95, -100), width=6, height=6, label="V_{bias}", label_side="bottom"))
amp = rx.add(OpAmp(center=(-10, -112), label="TIA", label_side="bottom"))
r_f = rx.add(Resistor(center=(-10, -99), length=26, label="R_f", value="10 kΩ"))   # the TIA example's values
c_f = rx.add(Capacitor(center=(-10, -77), length=26, label="C_f", value="0.2 pF"))
ground = rx.add(Ground(center=(-19, -122)))
adc = rx.add(ADCBlock(center=(50, -112), bit_count=12, label="ADC", label_side="bottom",
                      sample_rate_hz=Sourced(1e6, Source("model", note="a design value")),
                      full_scale_v=Sourced(1.0, Source("model", note="a design value"))))
scope = rx.add(Oscilloscope(center=(118, -102), label="Scope"))
rx.route((laser, "o1"), (ring, "o1"), kind="waveguide")
rx.route((ring, "o3"), (pd, "o1"), kind="waveguide", path_type="smooth")
for a, b in (((pd, "e2"), (bias, "e1")), ((pd, "e1"), (amp, "in_n")), ((r_f, "e1"), (amp, "in_n")),
             ((c_f, "e1"), (r_f, "e1")), ((r_f, "e2"), (amp, "out")), ((c_f, "e2"), (r_f, "e2")),
             ((amp, "in_p"), (ground, "e1")), ((amp, "out"), (adc, "in")), ((adc, "dout"), (scope, "ch1"))):
    rx.route(a, b, kind="electrical", width=0.25)
rx.fit_frame(margin=6)

t = np.linspace(0.0, 1e6, 2001)                          # 1 ms, in ns
ramp = Waveform(t, np.linspace(0.0, 30.0, t.size), "mW")  # the heater, as in the sweep above
chain = signal_chain(rx, t_ns=t, inputs=[((ring, "heater"), ramp)])
chain.show(scope)                                        # the codes on the scope's screen
codes = chain.at(adc, "dout")

fig, ax = plt.subplots(figsize=(3.0, 1.9), layout="constrained")
ax.plot(codes.t_ns / 1e3, codes.values, color="#009E73", lw=0.9, drawstyle="steps-post")
ax.set(xlabel="Time (µs)", ylabel="ADC code", ylim=(0, 4096), yticks=range(0, 4097, 1024))
print("\n".join(chain.notes))
print("heater: its thermal delay is not modelled; the ramp sets its power at each instant (model)")
print(f"peak: code {codes.values.max()} of 4095 at {codes.t_ns[codes.values.argmax()] / 1e3:.0f} µs")
received = Page(width_mm=183)
received.row([rx, fig], shares=[0.6, None])
received

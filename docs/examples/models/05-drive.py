# browser: no (the signal chain and the plot need numpy and matplotlib)
# A transmitter that computes its signal: DAC codes, a driver, the modulator, a photodiode, the scope
from optodraw import DAC, MZM, Amplifier, TIABlock

DESIGN = Source("model", note="a design value")
tx = Scene(title="A transmitter", platform="on_chip")
source = tx.add(OnChipLaser(center=(-150, 0), label="Laser", power_mw=Sourced(1.0, DESIGN)))
mzm = tx.add(MZM(center=(0, 0), label="MZM"))
dac = tx.add(DAC(center=(-120, 50), bit_count=8, label="DAC", sample_rate_hz=Sourced(1e9, DESIGN)))
driver = tx.add(Amplifier(center=(-62, 54.2), label="Driver", gain=Sourced(2.0, DESIGN),     # 1 V of DAC to V_pi
                          bandwidth_hz=Sourced(5e9, DESIGN)))
detector = tx.add(OnChipPhotodetector(center=(110, 0), label="PD", label_side="bottom",
                                      responsivity_a_per_w=Sourced(0.8, VIVIEN)))
bias_tx = tx.add(ElectricalPad(center=(150, 30), width=6, height=6, label="V_{bias}"))
tia = tx.add(TIABlock(center=(170, -9), label="TIA", label_side="bottom", gain_ohm=Sourced(1e3, DESIGN),
                      bandwidth_hz=Sourced(10e9, DESIGN)))
scope_tx = tx.add(Oscilloscope(center=(225, 20), label="Scope"))
tx.route((source, "o1"), (mzm, "o1"), kind="waveguide")
tx.route((mzm, "o3"), (detector, "o1"), kind="waveguide")
for a, b in (((dac, "out"), (driver, "in")), ((driver, "out"), (mzm, "sig")), ((detector, "e1"), (bias_tx, "e1")),
             ((detector, "e2"), (tia, "in")), ((tia, "out"), (scope_tx, "ch1"))):
    tx.route(a, b, kind="electrical", width=0.25)
tx.fit_frame(margin=6)

symbols = [0, 3, 1, 2, 3, 0, 2, 1, 1, 3, 0, 2, 2, 0, 3, 1]          # four levels, one symbol per ns
codes = Waveform(np.arange(16) * 1.0, np.array(symbols) * 85, "code")
t = np.linspace(0.0, 16.0, 801)                                    # ns
chain_tx = signal_chain(tx, t_ns=t, inputs=[((dac, "din"), codes)])
chain_tx.show(scope_tx)
drive, received_v = chain_tx.at(driver, "out"), chain_tx.at(tia, "out")

fig, ax = plt.subplots(figsize=(3.0, 1.9), layout="constrained")
ax.plot(t, drive.values, color="#0072B2", lw=0.9, label="drive")
ax.plot(t, received_v.values, color="#009E73", lw=0.9, label="received")
ax.set(xlabel="Time (ns)", ylabel="Voltage (V)", ylim=(0, 2.1), xticks=range(0, 17, 4))
ax.legend(frameon=False, fontsize=6, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
print("\n".join(chain_tx.notes))
sent = Page(width_mm=183)
sent.row([tx, fig], shares=[0.6, None])
sent

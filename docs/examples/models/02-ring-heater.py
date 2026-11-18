# browser: no (the plots need matplotlib)
# The heater moves the resonance onto the laser line: the animation's own numbers, plotted
from optodraw.animation_engine import Animation, Flow, Plot, Quantity, Sweep

heater = f"heater:{s.sids[id(adddrop)]}"                 # the add-drop ring's heater, in mW
light = Animation(chip, view="2d", mode="cw", strict=True)
light.play(Flow(mode="cw")).click()
light.play(Sweep(heater, 0, 30, seconds=4, samples=301), Plot(Quantity(drop_b), against=heater))
sweep = light.to_json()["assets"]["plot:1"]               # what the editor plays, frame by frame
best = sweep["x"][max(range(len(sweep["y"])), key=sweep["y"].__getitem__)]

fig_a, ax = plt.subplots(figsize=(3.0, 1.9), layout="constrained")
ax.plot(sweep["x"], sweep["y"], color="#009E73", lw=0.9)
ax.set(xlabel="Heater power (mW)", ylabel="Drop power (norm.)", ylim=(0, 1.05))
fig_b, ax = plt.subplots(figsize=(3.0, 1.9), layout="constrained")
for mw, colour in ((0.0, "#BBBBBB"), (best, "#009E73")):
    hot = spectrum(chip, start_nm=1540, stop_nm=1560, points=2001, params={heater: mw})
    ax.plot(hot.wavelengths_nm, hot.of(drop_b, "o1"), color=colour, lw=0.9, label=f"{mw:.1f} mW")
ax.axvline(1550, color="black", lw=0.6, ls=":")           # the laser line
ax.set(xlabel="Wavelength (nm)", ylabel="Drop power (norm.)", ylim=(0, 1.05), xticks=range(1540, 1561, 5))
ax.legend(frameon=False, fontsize=6, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
print(f"heater: a phase of pi per 20 mW (model: the engine's default); the drop peaks at {best:.1f} mW")
heated = Page(width_mm=183)
heated.row([fig_a, fig_b])
heated

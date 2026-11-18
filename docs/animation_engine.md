# Animation authoring and chip behaviours

The new authoring API builds a validated timeline as JSON.
Import it from `optodraw.animation_engine`. It does not require Manim.
The browser player and export integration are separate work.

`Animation.scene_parts()` returns the bound parts in stable order.
Use `input(part, port)` to supply light at an existing optical input.
`auto().click()` adds a flow section and a click boundary.
`Timeline.from_json()` restores the timeline without running Python from the file.

## Unconnected optical ports

Light leaves an unconnected port along its outward direction.
The warning names the part and port. `strict=True` raises an error instead.
Connect an external detector when the test setup measures an output.
Electrical ports do not carry optical travelling waves.

## Rings

Missing coupling and loss values use illustrative defaults.
Each ring bus has power coupling 0.1.
The ring has round-trip amplitude transmission 0.99.
The value 0.99 is an amplitude, not a power-loss fraction.
Missing values and `None` both select these defaults.
Explicit values must be finite and between zero and one.

An add-drop ring has two couplers and two half-loop states.
The solver sums repeated turns coherently. Pulses use the actual path transit times.
Through and drop ports remain distinct in both propagation directions.
These defaults are not measured device parameters.

## Star couplers

The ideal star uses a normalized Fourier transfer matrix.
Its reverse matrix is the transpose, which preserves reciprocity.
Rectangular stars are passive submatrices, not arbitrary split ratios.
Paths follow the aperture tapers and slab.
A common physical length represents a balanced schematic slab.

## Wavelength inputs and weight banks

The preset wavelength input declares numeric wavelengths and channel powers.
Its illustrative defaults are 1549, 1550, and 1551 nm, each with power 1 W.
Set `wavelengths_nm` and `channel_powers` when you construct the input.
The arrays must have matching nonempty lengths.
Wavelengths must be positive. Powers must be nonnegative. Values must be finite.
Colours in a drawing do not define wavelengths or measured weights.

The weight bank models serial add-drop rings and the drawn return loop.
The lower bus carries through light. Dropped light follows the upper bus and return loop.
The unmatched upper-bus end absorbs light in this schematic model.
The `dN` marks locate ring couplers. They do not create extra split ratios.

Per-ring overrides add a `ringN` suffix to the part ID.
For example, `heater:bank:ring2` sets the second ring's heater power in mW.
The illustrative heater relation gives a pi phase change at 20 mW.
`phase:bank:ring2` adds an explicit phase in radians.
`power_coupling:bank:ring2` sets lower-bus power coupling.
`drop_power_coupling:bank:ring2` sets upper-bus power coupling.
`round_trip_amplitude:bank:ring2` sets amplitude transmission.
Bank-wide coupling, phase, and loss values provide defaults for individual rings.
Saved scenes preserve explicit wavelength and power arrays.

## Coherent receivers

The ideal ninety-degree hybrid produces four internal detector fields:

```text
ip = (signal + lo) / 2
in = (signal - lo) / 2
qp = (signal + i * lo) / 2
qn = (signal - i * lo) / 2
```

Both Jones components use this matrix. The internal photodiodes absorb the fields.
The total absorbed power equals the signal power plus the local-oscillator power.
The balanced physical length represents a schematic hybrid, not a measured receiver.

The receiver behaviour's `currents()` method converts absorption records to currents.
It uses `responsivity_a_per_w` and returns `i_a`, `q_a`, and `absorbed_w`.
Pass records for the same time sample when you calculate instantaneous pulse currents.
Use `sid=` when the records contain multiple receivers.
This version does not generate electrical travelling waveforms.

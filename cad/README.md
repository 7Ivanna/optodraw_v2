# CAD reference models

optodraw draws its 3D from primitive dicts (`{"shape": "cylinder", ...}`), not
from CAD files. These scripts exist to **measure** real hardware so those
primitives are proportioned correctly, rather than guessed by eye.

The workflow:

1. Model the part to catalogue dimensions with `build123d` (mm).
2. Print the ratios optodraw actually needs — everything relative to the optic
   diameter, since components are parameterised by `aperture`.
3. Encode those ratios as class constants on the component, with the source
   noted, so the drawn part scales correctly at any aperture.

`km100_mount.py` — a Ø1in kinematic mirror mount. Its ratios feed
`Periscope._PLATE`, `_FRONT_T`, `_PLATE_GAP`, `_BACK_T`, `_ADJ_R`, `_KNOB_D`
and `_KNOB_T`. Eyeballing them had the mount 3.6x too shallow with pinhead
adjusters.

Requires `build123d` (pulls the OpenCascade kernel). It is a development
dependency for authoring components — optodraw itself does not import it.

`post_assembly.py` — Ø1/2in post, post holder and pedestal base. Its ratios feed
the renderer's `OPTIC_UNIT`/`POST_R`/`HOLDER_R`/`PED_BASE_R` constants and the
mounting-hole pitch on boards. All of that mounting hardware was ~4x too small
against the optics it carries.

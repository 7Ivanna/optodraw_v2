# The figure plan

Write this file as `figure_plan.md` beside the script that builds the figure,
before the first line of drawing code. Keep it short: a reviewer reads it in a
minute. Update it when a choice changes, and write the review findings into
it before you fix them.

## Template

```
# <figure name>

Assumptions: setup=..., views=..., size=..., depth=..., source=...

## Takeaway
One sentence a reader must take from the figure.
Must not imply: ...

## Skeleton
A setup with its signal: the bench, with the state of the light on each arm.

## Light path
Beam 1: laser (out) -> BS1 (front, transmits) -> sample -> M2 -> BS2 (in) -> PD1
Beam 2: BS1 (reflects) -> M1 -> BS2 (tap) -> PD2
Wavelength: 633 nm. Polarization: not shown.

## Parts
| part | class | label (exact) |
|---|---|---|
| laser | Laser | HeNe laser |

## Conventions
Light runs left to right; arms are symmetric; the sample arm is the lower one.

## Electrical nets (a chip or an instrument)
Net 1: PD1 e1 -> pad G1; PD1 out -> pad S1 (one row of pads on the north edge)
Every pad a real device needs, and where its wire runs.

## Unknowns
What the source does not say, and what you asked the user.

## Gaps
What the source draws that optodraw has no part for, and the part used instead.

## Review
Findings, scores and fixes (filled in at step 6).
```

On a plate splitter the entry beam and the reflected beam share the coated
front face, so a printed stop list can read `refl` where you expected `in`.
The order of the parts is what the review compares.

## Rubric for a full-depth review

Score each item from 1 to 5 and fix anything under 4.

| item | the question |
|---|---|
| Reads at final size | Is every label legible at 100 % at the preset width? |
| Takeaway | Can a reader state the takeaway from the figure alone in 5 seconds? |
| Faithful | Does every part, beam, count and order match the plan and the source? |
| Correct | Is the physics right: arms, focal planes, detectors facing their beams, polarization? |
| Labels | Does each label name a thing in 2 to 4 words and touch its part, off every beam? |
| Links | Do the panels share one colour key, and does each inset show where it comes from? |
| Economy | Is everything that explains or qualifies in the caption, not on the figure? |
| Craft | Are parts aligned, arms symmetric, beams straight, gaps even, nothing overlapping? |

Authors score their own figures high: measure, do not judge by eye. Equal
things are equal in points, and aligned things share one coordinate.

At full depth, build two arrangements (for example the arms stacked or side by
side), render both, write what a journal's art editor would flag in each, and
keep the one with fewer and smaller problems. Two drawings of one source differ
by more than polish can recover, so the choice is worth more than a second pass.

## Revising a figure

Change exactly what was asked. Save `scene.to_spec()` before the change and
compare it after: any part that moved or changed and that the request did not
name is a change nobody asked for. Undo it, or say why the request forced it.

## Redrawing a published figure

Match the reference's content, arrangement and proportions by eye and by
ruler. Never trace or vectorise its pixels. Cite it in the caption.

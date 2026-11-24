# Figure plan: cryostat microscope bench (3D mockup)

Assumptions: setup=fiber-coupled confocal-style microscope over a cryostat, views=3D (2D for checking),
size=bench render (not a paper column), depth=draft, source=5 lab photos + user's description

## Takeaway
Fiber-coupled light is steered by stepper-motor mirrors into a 30 mm cage line, turned down a vertical
cage tower onto a sample in a cryostat under the breadboard; light from the sample comes back up the same
tower and out to a collection fiber. An LED and a camera on the tower image the sample.

Must not imply: true distances, true part sizes, or the exact number of fibers (see Unknowns).

## Skeleton
A setup with its signal: one bench, three light paths (excitation, collection, imaging).

## Light path (all through 30 mm cage cubes holding beamsplitters, per user)
1. Excitation: Fiber 1 collimator -> motorized mirror MM1 -> cage cube BS0 (in -> trans) -> 30 mm cage rods
   -> tower base cube BS1 (reflects down) -> objective -> sample in cryostat.
2. Collection: sample -> objective -> BS1 -> cage rods -> BS0 (trans -> tap) -> motorized mirror MM2
   -> Fiber 3 collimator.
3. Imaging: LED (side of upper tower cube BS2) -> BS2 -> BS1 -> objective -> sample; sample -> up the
   tower through BS1, BS2 -> tube lens -> camera (top).

## Parts (new parts are marked *)
| part | class | label |
|---|---|---|
| breadboard over the cryostat, with a through hole | *BoardWithHole | Breadboard |
| legs of the breadboard | *BenchLegs | (none) |
| fiber collimators x4 | FiberCollimator | Fiber 1..4 |
| stepper-motor mirror mounts x2 | *MotorizedMirror | MM1, MM2 |
| 30 mm cage cube + beamsplitter | *CageCube | BS0 |
| 30 mm cage rods | *CageRods | (none) |
| vertical 30 mm cage tower: BS1, BS2, LED, tube lens, camera, objective | *CageTower | Cage tower |
| cryostat under the board | *CryostatBelow | Cryostat |

## Unknowns (drawn as stated guesses; ask the user)
- How many fiber ports and how many motorized mirrors (photos suggest ~4 fibers, 2 motors): drawn 4 and 2.
- How the motorized mirrors make any fiber excitation OR collection: drawn as MM1 choosing the excitation
  fiber (1 or 2) and MM2 choosing the collection fiber (3 or 4). The active choice is a script setting.
- Wavelengths: excitation 532 nm, collection 700 nm, LED 590 nm are placeholders for beam colour only.
- Whether the horizontal cage carries lenses or filters: none drawn.
- Objective position (above the cryostat window, through the board): assumed.

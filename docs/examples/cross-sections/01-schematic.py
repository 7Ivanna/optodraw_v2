# browser: no (the cross-section engine needs shapely and PyYAML, which the browser Python does not load)
# The PN rib phase shifter of the gdsfactory generic PDK, cut across its rib
from pathlib import Path

from optodraw.gds import GDSLayerRecord, GDSLayout, cross_section


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def layer(spec, *shapes):
    return GDSLayerRecord(spec=spec, name="", description="", color="#000000",
                          opacity=1.0, thickness=0.0, zmin=0.0, material_preset="",
                          polygons=list(shapes), matched_pdk=False)


# straight_pn(length=20) with its default via_stack_slab_m3: a 500 nm rib on a 90 nm
# slab, P and N either side, P++ and N++ from 1 um out, contacts up through M1 and M2
# to M3, the pad metal; the oxide opens on PADOPEN, 1.5 um inside each pad, down to M3
pads = [rect(0, 1, 20, 11), rect(0, -11, 20, -1)]
openings = [rect(1.5, 2.5, 18.5, 9.5), rect(1.5, -9.5, 18.5, -2.5)]
contacts = [rect(x - 0.35, y - 0.35, x + 0.35, y + 0.35)
            for x in range(2, 20, 2) for y in (-9, -7, -5, -3, 3, 5, 7, 9)]
records = [
    layer((1, 0), rect(0, -0.25, 20, 0.25)),           # WG
    layer((3, 0), rect(0, -3.5, 20, 3.5), *pads),      # SLAB90
    layer((20, 0), rect(0, -8, 20, 0)),                # N
    layer((21, 0), rect(0, 0, 20, 8)),                 # P
    layer((24, 0), rect(0, -8, 20, -1)),               # N++
    layer((25, 0), rect(0, 1, 20, 8)),                 # P++
    layer((40, 0), *contacts),                         # VIAC
    layer((41, 0), *pads),                             # M1
    layer((44, 0), *contacts),                         # VIA1
    layer((45, 0), *pads),                             # M2
    layer((43, 0), *contacts),                         # VIA2
    layer((49, 0), *pads),                             # M3, the bond pads
    layer((46, 0), *openings),                         # PADOPEN: the etch down to the pads
]
layout = GDSLayout(source_path=Path("straight_pn.gds"), cell_name="straight_pn",
                   bounds=(0, -11, 20, 11), layer_records=records)
# the cut: across the rib at x = 2 um, through a row of contacts
xs = cross_section(layout, "gdsfactory_generic", ((2, 12), (2, -12)))
assert xs.check() == [], xs.check()
xs.svg()

"""Dimensions of vendor parts, in millimetres, read from the vendors' published drawings and specification pages.

Each table maps a part number (or, for Edmund Optics, the stock number) to the numbers its part family needs. A
value read off a drawing is plain; a value worked out from a thread standard, from the part's name, or from a
sibling part's drawing says so in ``"source"``. Thorlabs drawings: www.thorlabs.com, "CAD PDF" of each item.
Edmund Optics: the specification table of each product page.

These are dimensions (facts) for drawing to scale. No vendor CAD geometry is stored here.
"""

from __future__ import annotations

# --------------------------------------------------------------------------------------------- thread sizes
# Major diameters of the external threads, from the thread standards (inches converted).
THREAD_OD = {
    "SM05": 13.6,      # 0.535"-40
    "SM1": 26.3,       # 1.035"-40
    "SM1.5": 39.0,     # 1.535"-40
    "SM2": 51.7,       # 2.035"-40
    "RMS": 20.3,       # 0.800"-36
    "C": 25.4,         # C-mount 1.000"-32
    "M32": 32.0,
    "M12": 12.0,
    "M11": 11.0,
    "M9": 9.0,
}

# --------------------------------------------------------------------------------------------- lenses
# type: "pcx" (plano-convex, R1 on the curved face) or "achromat" (cemented doublet R1, R2, R3, CT1 + CT2).
# Radii carry their signs: positive when the centre of curvature lies behind the surface (toward +x).
LENSES = {
    # Edmund Optics (stock numbers), from the product pages
    "65-436": {"title": "12mm Dia. x 15mm FL, NIR II Coated, Achromatic Lens", "type": "achromat", "d": 12.0, "ct1": 6.5, "ct2": 2.0, "et": 6.06, "efl": 15.0, "bfl": 9.95, "r": [9.55, -9.55, -57.30]},
    "45-792": {"title": "12mm Dia. x 20mm FL, NIR II Coated, Achromatic Lens", "type": "achromat", "d": 12.0, "ct1": 8.0, "ct2": 2.5, "et": 8.65, "efl": 20.0, "bfl": 14.18, "r": [13.13, -9.59, -45.11]},
    "67-549": {"title": "25.0mm Dia. x 85.0mm FL, NIR II Coated, Plano-Convex Lens", "type": "pcx", "d": 25.0, "ct": 4.30, "et": 2.48, "efl": 85.0, "bfl": 82.17, "r": [43.93]},
    "33-363": {"title": "25.0mm Dia. x 200.0mm FL, NIR II Coated, Plano-Convex Lens", "type": "pcx", "d": 25.0, "ct": 3.20, "et": 2.44, "efl": 200.0, "bfl": 197.89, "r": [103.36]},
    "67-555": {"title": "25.0mm Dia. x 250.0mm FL, NIR II Coated, Plano-Convex Lens", "type": "pcx", "d": 25.0, "ct": 3.00, "et": 2.59, "efl": 250.0, "bfl": 248.02, "r": [129.20]},
    "67-556": {"title": "25.0mm Dia. x 300.0mm FL, NIR II Coated, Plano-Convex Lens", "type": "pcx", "d": 25.0, "ct": 3.00, "et": 2.50, "efl": 300.0, "bfl": 298.02, "r": [155.04]},
    "33-369": {"title": "25.0mm Dia. x 400.0mm FL, NIR II Coated, Plano-Convex Lens", "type": "pcx", "d": 25.0, "ct": 3.20, "et": 2.82, "efl": 400.0, "bfl": 397.89, "r": [206.72]},
    "67-558": {"title": "25.0mm Dia. x 500.0mm FL, NIR II Coated, Plano-Convex Lens", "type": "pcx", "d": 25.0, "ct": 3.20, "et": 2.90, "efl": 500.0, "bfl": 497.89, "r": [258.40]},
    "67-560": {"title": "25.4mm Dia. x 25.4mm FL, NIR II Coated, Plano-Convex Lens", "type": "pcx", "d": 25.4, "ct": 7.00, "et": 2.43, "efl": 25.4, "bfl": 21.48, "r": [19.93]},
    "67-562": {"title": "25.4mm Dia. x 50.8mm FL, NIR II Coated, Plano-Convex Lens", "type": "pcx", "d": 25.4, "ct": 5.00, "et": 1.72, "efl": 50.8, "bfl": 47.5, "r": [26.25]},
    "67-563": {"title": "25.4mm Dia. x 63.5mm FL, NIR II Coated, Plano-Convex Lens", "type": "pcx", "d": 25.4, "ct": 4.75, "et": 2.19, "efl": 63.5, "bfl": 60.37, "r": [32.82]},
    "38-379": {"title": "25.4mm Dia. x 100.0mm FL, NIR I Coated, Plano-Convex Lens", "type": "pcx", "d": 25.4, "ct": 3.00, "et": 1.42, "efl": 100.0, "bfl": 98.02, "r": [51.68]},
    "38-425": {"title": "25.4mm Dia. x 100.0mm FL, NIR II Coated, Plano-Convex Lens", "type": "pcx", "d": 25.4, "ct": 3.00, "et": 1.42, "efl": 100.0, "bfl": 98.02, "r": [51.68]},
    "38-432": {"title": "25.4mm Dia. x 150.0mm FL, NIR II Coated, Plano-Convex Lens", "type": "pcx", "d": 25.4, "ct": 3.00, "et": 1.95, "efl": 150.0, "bfl": 148.02, "r": [77.52]},
    "45-800": {"title": "25mm Dia. x 35mm FL, NIR II Coated, Achromatic Lens", "type": "achromat", "d": 25.0, "ct1": 11.0, "ct2": 4.0, "et": 10.48, "efl": 35.0, "bfl": 26.87, "r": [23.40, -20.11, -87.52]},
    "45-801": {"title": "25mm Dia. x 40mm FL, NIR II Coated, Achromatic Lens", "type": "achromat", "d": 25.0, "ct1": 11.0, "ct2": 4.0, "et": 11.09, "efl": 40.0, "bfl": 31.74, "r": [26.27, -22.26, -105.93]},
    "45-803": {"title": "25mm Dia. x 50mm FL, NIR II Coated, Achromatic Lens", "type": "achromat", "d": 25.0, "ct1": 8.0, "ct2": 4.0, "et": 8.94, "efl": 50.0, "bfl": 43.29, "r": [31.69, -28.45, -161.05]},
    "45-804": {"title": "25mm Dia. x 60mm FL, NIR II Coated, Achromatic Lens", "type": "achromat", "d": 25.0, "ct1": 8.0, "ct2": 4.0, "et": 9.46, "efl": 60.0, "bfl": 52.96, "r": [36.27, -33.80, -248.86]},
    "45-806": {"title": "25mm Dia. x 100mm FL, NIR II Coated, Achromatic Lens", "type": "achromat", "d": 25.0, "ct1": 6.0, "ct2": 4.0, "et": 8.49, "efl": 100.0, "bfl": 93.89, "r": [57.01, -56.72, -656.51]},
    "47-380": {"title": "25mm Dia. x 150mm FL, NIR II Coated, Achromatic Lens", "type": "achromat", "d": 25.0, "ct1": 6.0, "ct2": 4.0, "et": 9.00, "efl": 150.0, "bfl": 143.90, "r": [84.66, -84.66, -1071.91]},
    "47-271": {"title": "25mm Dia. x 200mm FL, NIR II Coated, Achromatic Lens", "type": "achromat", "d": 25.0, "ct1": 6.0, "ct2": 4.0, "et": 9.25, "efl": 200.0, "bfl": 193.76, "r": [112.88, -112.88, -1415.62]},
    # Thorlabs, from the drawings (radius signs are not printed: the usual doublet form, R1 > 0, R2 and R3 < 0)
    "AC127-019-C": {"title": "f=19 mm, Ø1/2\" Achromatic Doublet, ARC: 1050-1700 nm", "type": "achromat", "d": 12.7, "ct1": 5.0, "ct2": 2.0, "efl": 19.0, "r": [12.9, -11.0, -59.3], "source": "outline as AC127-025-B (drawing); radii and EFL from the catalogue value, not a drawing"},
    "AC127-025-B": {"title": "f=25 mm, Ø1/2\" Achromatic Doublet, ARC: 650-1050 nm", "type": "achromat", "d": 12.7, "ct1": 5.0, "ct2": 2.0, "efl": 25.0, "bfl": 21.1, "r": [16.2, -13.3, -68.5]},
    "AC254-030-C": {"title": "f=30 mm, Ø1\" Achromatic Doublet, ARC: 1050-1700 nm", "type": "achromat", "d": 25.4, "ct1": 13.0, "ct2": 1.8, "efl": 30.4, "bfl": 22.2, "r": [21.1, -15.2, -71.1]},
    "AC080-016-B-ML": {"title": "f=16 mm, Ø8 mm Achromatic Doublet, M12x0.5 Threaded Mount", "type": "achromat", "d": 8.0, "ct1": 3.0, "ct2": 1.0, "efl": 16.0, "bfl": 14.0, "r": [10.0, -8.0, -40.0],
                       "cell": {"od": 12.2, "length": 8.0, "aperture": 7.5}, "source": "CT 4.0, EFL, BFL and the M12 cell from the drawing; the split of CT and the radii are not printed (illustrative)"},
}

# --------------------------------------------------------------------------------------------- lens tubes
# body: outer diameter, overall length (thread depth + 3.8: the 3.0 male stub and the 0.8 lip, from SM1L10),
# clear aperture.
def _sm1_tube(depth_in: float, title: str) -> dict:
    return {"title": title, "od": 30.5, "length": depth_in * 25.4 + 3.8, "stub": 3.0, "stub_od": THREAD_OD["SM1"],
            "lip": 2.0, "clear": 22.9, "source": "SM1L10 drawing; length = thread depth + 3.8 mm"}


TUBES = {
    "SM1L03": _sm1_tube(0.30, "SM1 Lens Tube, 0.30\" Thread Depth"),
    "SM1L03V": _sm1_tube(0.30, "Vacuum-Compatible SM1 Lens Tube, 0.30\" Thread Depth"),
    "SM1L05": _sm1_tube(0.50, "SM1 Lens Tube, 0.50\" Thread Depth"),
    "SM1L10": {**_sm1_tube(1.00, "SM1 Lens Tube, 1.00\" Thread Depth"), "length": 29.2, "source": "drawing"},
    "SM1L10V": _sm1_tube(1.00, "Vacuum-Compatible SM1 Lens Tube, 1.00\" Thread Depth"),
    "SM1L20": _sm1_tube(2.00, "SM1 Lens Tube, 2.00\" Thread Depth"),
    "SM1L25": _sm1_tube(2.50, "SM1 Lens Tube, 2.50\" Thread Depth"),
    "SM1L30": _sm1_tube(3.00, "SM1 Lens Tube, 3.00\" Thread Depth"),
    "SM1L40": _sm1_tube(4.00, "SM1 Lens Tube, 4.00\" Thread Depth"),
    # adjustable: an outer housing and a sliding inner tube; the length shown is one setting (SM1V10 drawing)
    "SM1V05": {"title": "Ø1\" Adjustable Lens Tube, 0.31\" Travel", "od": 30.5, "length": 26.2, "stub": 3.0, "stub_od": THREAD_OD["SM1"], "lip": 2.0, "clear": 22.9, "adjustable": True, "housing": 13.5,
               "source": "SM1V10 drawing, length shortened by 12.7 mm per 0.5\" less travel (estimated)"},
    "SM1V10": {"title": "Ø1\" Adjustable Lens Tube, 0.81\" Travel", "od": 30.5, "length": 38.9, "stub": 3.0, "stub_od": THREAD_OD["SM1"], "lip": 2.0, "clear": 22.9, "adjustable": True, "housing": 13.5, "source": "drawing"},
    "SM1V10V": {"title": "Vacuum-Compatible Ø1\" Adjustable Lens Tube, 0.81\" Travel", "od": 30.5, "length": 38.9, "stub": 3.0, "stub_od": THREAD_OD["SM1"], "lip": 2.0, "clear": 22.9, "adjustable": True, "housing": 13.5, "source": "as SM1V10"},
    "SM1V15": {"title": "Ø1\" Adjustable Lens Tube, 1.31\" Travel", "od": 30.5, "length": 51.6, "stub": 3.0, "stub_od": THREAD_OD["SM1"], "lip": 2.0, "clear": 22.9, "adjustable": True, "housing": 13.5,
               "source": "SM1V10 drawing, lengthened by 12.7 mm per 0.5\" more travel (estimated)"},
    "SM05L10": {"title": "SM05 Lens Tube, 1\" Thread Depth", "od": 17.8, "length": 28.2, "stub": 2.0, "stub_od": THREAD_OD["SM05"], "lip": 1.7, "clear": 10.9, "source": "drawing"},
}

# --------------------------------------------------------------------------------------------- thread adapters
# An axial stack, front to back: (length, outer diameter, inner diameter). "fiber" marks a fiber connector side.
ADAPTERS = {
    "AD11F": {"title": "SM1-Threaded Adapter for Ø11 mm Cylindrical Components", "stack": [(8.9, THREAD_OD["SM1"], 11.0)], "source": "SM1 thread and the ≥8.9 mm length in the name (estimated)"},
    "AD11NT": {"title": "Ø1\" Unthreaded Adapter for Ø11 mm Cylindrical Components", "stack": [(6.4, 25.4, 11.0)], "source": "Ø1\" and Ø11 mm in the name; length estimated"},
    "AD12F": {"title": "SM1-Threaded Adapter for Ø12 mm Cylindrical Components", "stack": [(8.9, THREAD_OD["SM1"], 12.0)], "source": "as AD11F (estimated)"},
    "AD12NT": {"title": "Ø1\" Unthreaded Adapter for Ø12 mm Cylindrical Components", "stack": [(6.4, 25.4, 12.0)], "source": "as AD11NT (estimated)"},
    "AD1109F": {"title": "SM05-Threaded Adapter for M11 x 0.5 or M9 x 0.5 Components", "stack": [(6.4, THREAD_OD["SM05"], 9.0)], "source": "SM05 and M9 threads in the name; length estimated"},
    "AP8E25E": {"title": "Adapter with External 8-32 and External 1/4\"-20 Threads", "stack": [(6.4, 6.35, 0.0), (4.8, 4.2, 0.0)], "source": "the two thread sizes; lengths estimated"},
    "ERSCB": {"title": "Rod Adapter for Ø6 mm ER Rods, L = 0.27\"", "stack": [(6.9, 6.0, 0.0)], "source": "Ø6 mm and L in the name"},
    "ERSCB05": {"title": "Rod Adapter for Ø6 mm ER Rods, L = 0.50\"", "stack": [(12.7, 6.0, 0.0)], "source": "Ø6 mm and L in the name"},
    "FS201-PM": {"title": "FC-Type Connector Adapter for FS201 Fiber Inspection Scope", "stack": [(12.0, 15.0, 2.5)], "fiber": True, "source": "estimated"},
    "KAD1F": {"title": "SM1.5-Threaded Kinematic Pitch/Yaw Adapter for Ø1\" Optics", "stack": [(2.8, 44.5, 26.3), (17.0, 39.0, 26.3)], "source": "drawing (SM1.5 body Ø39.0 x 19.8, SM1.5NT ring Ø44.5 x 2.8)"},
    "LMRA6": {"title": "Ø1/2\" Adapter for Ø6 mm Optics", "stack": [(3.0, 12.7, 5.5)], "source": "Ø1/2\" and Ø6 mm in the name; length estimated"},
    "MSA8": {"title": "Mini-Series Adapter, External 8-32 and Internal 4-40", "stack": [(6.4, 4.2, 0.0)], "source": "8-32 thread; length estimated"},
    "S1TM12": {"title": "SM1 to M12 x 0.5 Lens Cell Adapter", "stack": [(7.6, THREAD_OD["SM1"], THREAD_OD["M12"])], "source": "the two threads; length estimated"},
    "S120-APC": {"title": "FC/APC Fiber Adapter Cap with Internal SM1 Threads", "stack": [(7.6, 30.5, 22.9), (8.0, 9.0, 2.5)], "fiber": True, "source": "SM1 cap and FC barrel (estimated)"},
    "SM1A3": {"title": "Adapter with External SM1 and Internal RMS Threads", "stack": [(5.1, THREAD_OD["SM1"], THREAD_OD["RMS"])], "source": "drawing (5.1 thick), thread diameters"},
    "SM1A6T": {"title": "Adapter with External SM1 and Internal SM05 Threads, 0.40\" Long", "stack": [(10.2, THREAD_OD["SM1"], THREAD_OD["SM05"])], "source": "threads and 0.40\" in the name"},
    "SM1A9": {"title": "Adapter with External C-Mount and Internal SM1 Threads, 4.4 mm Spacer", "stack": [(4.4, 30.5, THREAD_OD["SM1"]), (3.8, THREAD_OD["C"], 22.9)], "source": "threads and the 4.4 mm spacer in the name; flange estimated"},
    "SM1A34": {"title": "Adapter with External SM1 and Internal M32 x 0.75 Threads", "stack": [(5.0, 35.6, THREAD_OD["M32"]), (3.0, THREAD_OD["SM1"], 22.9)], "source": "threads; lengths estimated"},
    "SM1A69": {"title": "Adapter with External SM1 and Internal SM1.5 Threads", "stack": [(6.4, 44.5, THREAD_OD["SM1.5"]), (3.0, THREAD_OD["SM1"], 22.9)], "source": "threads; lengths estimated"},
    "SM1FC2": {"title": "FC/PC Fiber Adapter Plate, External SM1 Threads, Narrow Key", "stack": [(3.0, THREAD_OD["SM1"], 0.0), (8.0, 9.0, 2.5)], "fiber": True, "source": "SM1 plate and FC barrel (estimated)"},
    "SM1FCA2": {"title": "FC/APC Fiber Adapter Plate, External SM1 Threads, Narrow Key", "stack": [(3.0, THREAD_OD["SM1"], 0.0), (8.0, 9.0, 2.5)], "fiber": True, "source": "as SM1FC2 (estimated)"},
    "SM1T1": {"title": "SM1 Coupler, Internal Threads", "stack": [(7.6, 30.5, THREAD_OD["SM1"])], "source": "SM1 thread; length estimated"},
    "SM1T2": {"title": "SM1 Coupler, External Threads, 0.5\" Long, Two Locking Rings", "stack": [(2.8, 31.8, 24.0), (7.1, THREAD_OD["SM1"], 24.0), (2.8, 31.8, 24.0)], "source": "drawing"},
}

# --------------------------------------------------------------------------------------------- filters
# Ø25 mm filters in an unthreaded ring (FELH0800 drawing: Ø25.0 x 3.5, clear Ø21.1).
FILTERS = {pn: {"title": t, "od": 25.0, "thickness": 3.5, "clear": 21.1, "band": band, "edge": edge,
                "source": "FELH0800 drawing" if pn == "FELH0800" else "as FELH0800 (same ring)"}
           for pn, t, band, edge in (
               ("FELH0800", "Ø25.0 mm Longpass Filter, Cut-On 800 nm", "longpass", 800),
               ("FELH0900", "Ø25.0 mm Longpass Filter, Cut-On 900 nm", "longpass", 900),
               ("FELH1200", "Ø25.0 mm Longpass Filter, Cut-On 1200 nm", "longpass", 1200),
               ("FELH1250", "Ø25.0 mm Longpass Filter, Cut-On 1250 nm", "longpass", 1250),
               ("FELH1500", "Ø25.0 mm Longpass Filter, Cut-On 1500 nm", "longpass", 1500),
               ("FESH0800", "Ø25.0 mm Shortpass Filter, Cut-Off 800 nm", "shortpass", 800),
               ("FESH0950", "Ø25.0 mm Shortpass Filter, Cut-Off 950 nm", "shortpass", 950))}

# Ø25 mm absorptive ND filters in an engraved SM1L03-style mount (NE05A-B and NENIR10A drawings: Ø30.5 x 11.4,
# 3.0 male stub, clear Ø20.0). NDC-50C-4M-B: the variable wheel.
ND_FILTERS = {pn: {"title": t, "od": 30.5, "length": 11.4, "stub": 3.0, "clear": 20.0, "od_value": od,
                   "source": "drawing" if pn in ("NE05A-B", "NENIR10A") else "as NE05A-B / NENIR10A (same mount)"}
              for pn, t, od in (
                  ("NE05A-B", "Ø25 mm Absorptive ND Filter, OD 0.5", 0.5), ("NE09A-B", "Ø25 mm Absorptive ND Filter, OD 0.9", 0.9),
                  ("NE10A-B", "Ø25 mm Absorptive ND Filter, OD 1.0", 1.0), ("NE15A-B", "Ø25 mm Absorptive ND Filter, OD 1.5", 1.5),
                  ("NE20A-B", "Ø25 mm Absorptive ND Filter, OD 2.0", 2.0), ("NE30A-B", "Ø25 mm Absorptive ND Filter, OD 3.0", 3.0),
                  ("NE40A-B", "Ø25 mm Absorptive ND Filter, OD 4.0", 4.0), ("NE50A-B", "Ø25 mm Absorptive ND Filter, OD 5.0", 5.0),
                  ("NE60A-B", "Ø25 mm Absorptive ND Filter, OD 6.0", 6.0), ("NENIR03C", "Ø25 mm NIR Absorptive ND Filter, OD 0.3", 0.3),
                  ("NENIR10A", "Ø25 mm NIR Absorptive ND Filter, OD 1.0", 1.0), ("NENIR20A", "Ø25 mm NIR Absorptive ND Filter, OD 2.0", 2.0),
                  ("NENIR40A", "Ø25 mm NIR Absorptive ND Filter, OD 4.0", 4.0), ("NENIR50A", "Ø25 mm NIR Absorptive ND Filter, OD 5.0", 5.0))}
ND_FILTERS["NDC-50C-4M-B"] = {"title": "Mounted Continuously Variable ND Filter, Ø50 mm, OD 0.04 - 4.0", "wheel": True,
                              "od": 63.5, "glass_d": 46.2, "ring_t": 9.3, "glass_t": 4.3, "axle_d": 9.5, "block": 13.2,
                              "depth": 35.7, "od_value": 2.0, "source": "drawing (best reading of the wheel's rim and glass)"}

# --------------------------------------------------------------------------------------------- wave plates
def _wp(pn: str) -> dict:
    half = pn.startswith("WPH")
    small = "05M" in pn
    nm = int(pn.split("-")[1])
    if small:   # Ø1/2" plate in a Ø1" unthreaded ring (WPH05M-780 drawing)
        return {"title": f"Ø1/2\" Zero-Order {'Half' if half else 'Quarter'}-Wave Plate, Ø1\" Mount, {nm} nm", "plate": "half" if half else "quarter",
                "wavelength": nm, "od": 25.4, "length": 5.8, "stub": 0.0, "optic_d": 12.7, "clear": 10.0,
                "source": "WPH05M-780 drawing"}
    return {"title": f"Ø1\" Zero-Order {'Half' if half else 'Quarter'}-Wave Plate, SM1-Threaded Mount, {nm} nm", "plate": "half" if half else "quarter",
            "wavelength": nm, "od": 30.5, "length": 12.7, "stub": 3.0, "optic_d": 25.4, "clear": 22.6, "source": "WPH10M-915 drawing"}


WAVE_PLATES = {pn: _wp(pn) for pn in ("WPH05M-780", "WPH05M-915", "WPH05M-1550", "WPH10M-915", "WPH10M-1550",
                                      "WPQ05M-915", "WPQ05M-1550", "WPQ10M-915", "WPQ10M-1550")}

# --------------------------------------------------------------------------------------------- polarizers
GLAN_POLARIZERS = {
    "GT10": {"title": "Glan-Taylor Polarizer, 10 mm Clear Aperture, Uncoated", "w": 15.9, "h": 15.9, "length": 19.1, "window": 12.2, "escape": 13.3, "clear": 10.0, "source": "drawing"},
    "GT10-C": {"title": "Glan-Taylor Polarizer, 10 mm CA, Coating 1050 - 1700 nm", "w": 15.9, "h": 15.9, "length": 19.1, "window": 12.2, "escape": 13.3, "clear": 10.0, "source": "as GT10"},
}
POLARIZERS = {
    "LPNIR050-MP2": {"title": "Ø12.5 mm SM05-Mounted Linear Polarizer, 650 - 2000 nm", "od": 17.8, "length": 10.4, "stub": 2.0, "stub_od": THREAD_OD["SM05"], "clear": 10.9, "source": "drawing"},
}

# --------------------------------------------------------------------------------------------- beamsplitters
CUBE_SPLITTERS = {
    "BS013": {"title": "50:50 Non-Polarizing Beamsplitter Cube, 400 - 700 nm, 1\"", "edge": 25.4, "rt": (50, 50), "pol": False, "source": "drawing"},
    "BS014": {"title": "50:50 Non-Polarizing Beamsplitter Cube, 700 - 1100 nm, 1\"", "edge": 25.4, "rt": (50, 50), "pol": False, "source": "as BS013"},
    "BS020": {"title": "30:70 (R:T) Non-Polarizing Beamsplitter Cube, 700 - 1100 nm, 1\"", "edge": 25.4, "rt": (30, 70), "pol": False, "source": "as BS013"},
    "BS021": {"title": "30:70 (R:T) Non-Polarizing Beamsplitter Cube, 1100 - 1600 nm, 1\"", "edge": 25.4, "rt": (30, 70), "pol": False, "source": "as BS013"},
    "BS024": {"title": "70:30 (R:T) Non-Polarizing Beamsplitter Cube, 1100 - 1600 nm, 1\"", "edge": 25.4, "rt": (70, 30), "pol": False, "source": "as BS013"},
    "BS030": {"title": "90:10 (R:T) Non-Polarizing Beamsplitter Cube, 1100 - 1600 nm, 1\"", "edge": 25.4, "rt": (90, 10), "pol": False, "source": "as BS013"},
    "BS044": {"title": "10:90 (R:T) Non-Polarizing Beamsplitter Cube, 700 - 1100 nm, 20 mm", "edge": 20.0, "rt": (10, 90), "pol": False, "source": "drawing"},
    "BS045": {"title": "10:90 (R:T) Non-Polarizing Beamsplitter Cube, 1100 - 1600 nm, 20 mm", "edge": 20.0, "rt": (10, 90), "pol": False, "source": "as BS044"},
    "PBS122": {"title": "1/2\" Polarizing Beamsplitter Cube, 620 - 1000 nm", "edge": 12.7, "rt": (50, 50), "pol": True, "source": "drawing"},
    "PBS124": {"title": "1/2\" Polarizing Beamsplitter Cube, 1200 - 1600 nm", "edge": 12.7, "rt": (50, 50), "pol": True, "source": "as PBS122"},
    "PBS255": {"title": "1\" Polarizing Beamsplitter Cube, 700 - 1300 nm", "edge": 25.4, "rt": (50, 50), "pol": True, "source": "the 1\" size in the name (BS013 outline)"},
    "25mm 50R/50T NPBS 1100-1620nm": {"title": "25mm 1100-1620nm, 50R/50T, Non-Polarizing Cube Beamsplitter", "edge": 25.0, "rt": (50, 50), "pol": False, "source": "the 25 mm size in the name (no part number given)"},
    "25mm 30R/70T NPBS NIR": {"title": "25mm NIR, 30R/70T, Non-Polarizing Cube Beamsplitter", "edge": 25.0, "rt": (30, 70), "pol": False, "source": "the 25 mm size in the name (no part number given)"},
}
PLATE_SPLITTERS = {
    "BSN11R": {"title": "25 x 36 mm 10:90 (R:T) UVFS Plate Beamsplitter, t = 1 mm", "shape": "rect", "w": 36.0, "h": 25.0, "t": 1.0, "rt": (10, 90), "source": "drawing"},
    "BSW29": {"title": "Ø1\" 50:50 UVFS Plate Beamsplitter, t = 5.0 mm", "shape": "round", "d": 25.4, "t": 5.0, "rt": (50, 50), "source": "drawing"},
    "BSW29R": {"title": "25 x 36 mm 50:50 UVFS Plate Beamsplitter, t = 1.0 mm", "shape": "rect", "w": 36.0, "h": 25.0, "t": 1.0, "rt": (50, 50), "source": "as BSN11R (same size in the name)"},
    "BP108": {"title": "Ø1\" Pellicle Beamsplitter, 8:92 (R:T), 400 - 2400 nm", "shape": "pellicle", "d": 25.4, "frame_d": 34.9, "frame_t": 4.8, "t": 0.002, "rt": (8, 92), "source": "drawing"},
    "BP145B3": {"title": "Ø1\" Pellicle Beamsplitter, 45:55 (R:T), 1 - 2 µm", "shape": "pellicle", "d": 25.4, "frame_d": 34.9, "frame_t": 4.8, "t": 0.002, "rt": (45, 55), "source": "as BP108 (same frame)"},
}

# --------------------------------------------------------------------------------------------- mirrors, dichroics
MIRRORS = {
    "PF10-03-P01": {"title": "Ø1\" Protected Silver Mirror", "d": 25.4, "t": 6.0, "shape": "round", "source": "Ø1\" in the name; 6 mm thickness of the PF10 series"},
    "PF20-03-P01": {"title": "Ø2\" Protected Silver Mirror", "d": 50.8, "t": 12.0, "shape": "round", "source": "Ø2\" in the name; 12 mm thickness of the PF20 series"},
    "PFD10-03-P01": {"title": "Ø1\" Protected Silver D-Shaped Mirror", "d": 25.4, "t": 6.0, "shape": "D", "source": "Ø1\" in the name; 6 mm thickness of the PF10 series"},
}
DICHROICS = {
    "DMLP805": {"title": "Ø1\" Longpass Dichroic Mirror, 805 nm Cut-On", "d": 25.4, "t": 3.0, "band": "longpass", "edge": 805, "source": "drawing"},
    "DMSP650": {"title": "Ø1\" Shortpass Dichroic Mirror, 650 nm Cutoff", "d": 25.4, "t": 3.0, "band": "shortpass", "edge": 650, "source": "as DMLP805 (same size)"},
}

# --------------------------------------------------------------------------------------------- bench hardware
# Table clamps and clamping forks that hold a post or a base down on the table. Boxes (x along the clamp, y across,
# z up); "h" is the height of the clamping arm's top, "slot" the length of its counterbored slot.
CLAMPS = {
    # CF125 drawing (rev K, stainless): a waisted fork 73.8 long, 36.3 across the tines; the Ø26.0 bore for a Ø25
    # pedestal is centred 3.8 from the tines' tips, the tines 5.2 wide; Ø32.5 recess underneath for the pedestal's
    # flange; 23.0 wide round end, 24.3 at the waist 37 from the tips; a counterbored 1/4"-20 slot with centres 11.7
    # and 43.2 from the round end; 11.2 thick over the tines, 12.2 at the round end
    "CF125": {"title": "Clamping Fork, 1.24\" Counterbored Slot, Universal", "kind": "fork", "l": 73.8, "w": 36.3, "t": 11.2,
              "t_end": 12.2, "slot": 31.5, "slot_from_end": (11.7, 43.2), "bore": 26.0, "post_from_tip": 3.8, "tine": 5.2,
              "end_w": 23.0, "waist": 24.3, "waist_at": 37.0, "source": "drawing"},
    "CL4": {"title": "Table Clamp, Tight Space Applications", "kind": "clamp", "l": 38.1, "w": 15.9, "h": 12.7, "t": 6.4, "slot": 19.0, "source": "outline as CL8 (estimated)"},
    "CL5": {"title": "Table Clamp, L-Shape", "kind": "clamp", "l": 50.8, "w": 19.1, "h": 17.3, "t": 6.4, "slot": 29.2, "source": "drawing"},
    "CL5A": {"title": "Table Clamp, L-Shape, Rounded Lip", "kind": "clamp", "l": 50.8, "w": 19.1, "h": 17.3, "t": 6.4, "slot": 29.2, "source": "as CL5"},
    "CL6": {"title": "Table Clamp, RLA Series Optical Rails", "kind": "clamp", "l": 50.8, "w": 25.4, "h": 17.3, "t": 6.4, "slot": 29.2, "source": "as CL5, wider (estimated)"},
    "CL8": {"title": "Ø1\" and Ø1.5\" Pedestal Post Table Clamp", "kind": "clamp", "l": 33.3, "w": 15.9, "h": 12.1, "t": 6.4, "slot": 12.7, "source": "drawing"},
}

# Optical-table hardware: brackets, platform mounts. Boxes (x along the part's length, y across, z up).
HARDWARE = {
    "AB90A": {"title": "Right-Angle Bracket with Counterbored Slots & 1/4\"-20 Tapped Holes", "kind": "angle", "l": 50.8, "w": 38.1, "h": 50.8, "t": 8.9, "source": "drawing"},
    "BSH05": {"title": "Platform Mount for 1/2\" or 12.5 mm Beamsplitters and Prisms", "kind": "platform", "l": 18.8, "w": 17.8, "t": 8.3, "pocket": 12.8, "floor": 6.4, "source": "drawing"},
    "BSH1": {"title": "Platform Mount for 1\" or 25.0 mm Beamsplitters and Prisms", "kind": "platform", "l": 38.1, "w": 38.1, "t": 8.3, "pocket": 25.4, "floor": 6.4, "source": "drawing"},
    "BSH20": {"title": "Platform Mount for 20 mm Beamsplitters and Prisms", "kind": "platform", "l": 28.5, "w": 27.9, "t": 8.3, "pocket": 20.0, "floor": 6.4, "source": "drawing"},
    "BP107": {"title": "Ø1\" Fixed Pellicle Mount", "kind": "fork_mount", "w": 42.8, "h": 27.2, "t": 7.0, "base_t": 11.4, "inner_d": 36.3, "axis": 24.1, "source": "drawing (axis height is a best reading)"},
    "DMM1": {"title": "Fixed Mount for Ø1\" D-Shaped Mirrors", "kind": "cradle", "w": 43.2, "h": 21.6, "t": 7.5, "inner_d": 25.4, "axis": 15.2, "source": "drawing (axis height is a best reading)"},
    "ADAFCB6": {"title": "FC/APC to FC/APC Quadruple L-Bracket Mating Sleeve, Narrow Key", "kind": "sleeve_bracket", "w": 69.1, "d": 25.4, "h": 27.9, "t": 2.3, "pitch": 18.0, "axis": 17.5, "count": 4, "source": "drawing"},
    "ADAFCPMB6": {"title": "Quadruple L-Bracket Mating Sleeve, Narrow Key (PM)", "kind": "sleeve_bracket", "w": 69.1, "d": 25.4, "h": 27.9, "t": 2.3, "pitch": 18.0, "axis": 17.5, "count": 4, "source": "as ADAFCB6"},
}

# Fiber mating sleeves (butt couplers) with a square flange (ADAFC2 drawing: 15.0 square flange, Ø8.4 barrel, 15.0 long).
SLEEVES = {name: {"title": t, "flange": 15.0, "flange_t": 2.0, "barrel_d": 8.4, "length": 15.0,
                  "source": "ADAFC2 drawing" if name == "ADAFC2" else "the ADAFC2 square-flange sleeve (no part number given)"}
           for name, t in (("ADAFC2", "FC/PC to FC/PC Mating Sleeve, Square Flange"),
                           ("FC/APC PM butt coupler (narrow key, square)", "FC/APC PM Diamond-Aligned Butt Coupler (Narrow Key, Square)"),
                           ("FC/PC butt coupler (narrow key, square)", "FC/PC Diamond-Aligned Butt Coupler (Narrow Key, Square)"),
                           ("FC/APC SM butt coupler (<0.1 dB)", "FC/APC to FC/APC SM Butt Coupler (<0.1 dB Insertion Loss)"),
                           ("FC/APC square adapter with flange", "FC/APC to FC/APC Square Fiber Optic Adapter/Butt Coupler with Flange"),
                           ("FC/UPC square adapter with flange", "FC/UPC to FC/UPC Square Fiber Optic Adapter/Butt Coupler with Flange"))}

# --------------------------------------------------------------------------------------------- cameras
CAMERAS = {
    "Alvium 1800 U-130 VSWIR": {"title": "Allied Vision Alvium 1800 U-130 SWIR Camera", "body": (38.0, 29.0, 29.0), "mount": "C", "source": "Edmund Optics product page (38 x 29 x 29 mm)"},
    "Alvium 1800 U-500c": {"title": "Allied Vision Alvium 1800 U-500c Color Camera", "body": (38.0, 29.0, 29.0), "mount": "C", "source": "Edmund Optics product page (38 x 29 x 29 mm)"},
}

# --------------------------------------------------------------------------------------------- 30 and 60 mm cage parts
# kind: "plate" (square cage plate), "rotation" (a plate with a rotating graduated ring), "xy" (translating mount
# with two knobs), "dropin" (snap-on plate, wider than tall), "pivot" (CP360Q), "bracket" (CP33C), "adapter_60"
# (LCP33, 30 to 60 mm), "dual" (DLM1), "dropin_cell" (LCP360R: a rotating cell hung from the top rods),
# "drop_adapter" (CDA1: snaps onto the top rods of both cages), "alignment" (CPA1, VRC*CPT: a thin T-shaped target
# hung from the top rods, its pinhole on the axis), "rod_stop" (ERCPS, round its own rod), "rod" (ER8, a single rod
# along the beam), "cover" (C30L24: the four snap-on covers closing the cage). w x h across the beam, depth
# along it; bore = clear aperture through it; rod = the cage size (the rod spacing).
CAGE_MOUNTS = {
    "CP32": {"title": "SM05-Threaded 30 mm Cage Plate, 0.35\" Thick", "kind": "plate", "w": 40.6, "h": 40.6, "depth": 8.9, "bore": 13.6, "clear": 10.9, "rod": 30.0, "source": "drawing"},
    "CP33": {"title": "SM1-Threaded 30 mm Cage Plate, 0.35\" Thick", "kind": "plate", "w": 40.6, "h": 40.6, "depth": 8.9, "bore": 26.3, "clear": 22.9, "rod": 30.0, "source": "drawing"},
    "CP33T": {"title": "SM1-Threaded 30 mm Cage Plate, 0.50\" Thick", "kind": "plate", "w": 40.6, "h": 40.6, "depth": 12.7, "bore": 26.3, "clear": 22.9, "rod": 30.0, "source": "drawing"},
    "CP36": {"title": "30 mm Cage Plate, Ø1.2\" Double Bore for SM1 and C-Mount Lens Tubes", "kind": "plate", "w": 40.6, "h": 40.6, "depth": 8.9, "bore": 30.6, "clear": 30.6, "rod": 30.0, "source": "drawing"},
    "CP42": {"title": "RMS-Threaded 30 mm Cage Plate, 0.35\" Thick", "kind": "plate", "w": 40.6, "h": 40.6, "depth": 8.9, "bore": 20.3, "clear": 17.0, "rod": 30.0, "source": "drawing (RMS thread; clear aperture estimated)"},
    "DCP1": {"title": "Drop-In 30 mm Cage Mount, Flexure Lock, SM1, 0.40\" Thick", "kind": "dropin", "w": 53.0, "h": 30.5, "depth": 10.2, "bore": 26.3, "clear": 22.9, "rod": 30.0, "source": "drawing"},
    "CP33C": {"title": "30 mm Cage Mounting Bracket with 8-32 Captive Screw", "kind": "bracket", "w": 44.5, "h": 12.1, "depth": 12.7, "bore": 0.0, "clear": 0.0, "rod": 30.0, "source": "drawing"},
    "CRM1T": {"title": "Cage Rotation Mount for Ø1\" Optics, SM1 Threaded", "kind": "rotation", "w": 40.6, "h": 40.6, "depth": 8.6, "bore": 26.3, "clear": 22.9, "rod": 30.0, "ring_d": 35.9, "ring_l": 7.4, "source": "drawing"},
    "CRM1LT": {"title": "Cage Rotation Mount for Ø1\" Optics, Double Bored with Setscrew", "kind": "rotation", "w": 40.6, "h": 40.6, "depth": 8.6, "bore": 25.4, "clear": 24.0, "rod": 30.0, "ring_d": 35.9, "ring_l": 7.4, "source": "drawing"},
    "CP360Q": {"title": "Pivoting, Quick-Release, Ø1\" Optic Mount for 30 mm Cage System", "kind": "pivot", "w": 40.6, "h": 37.8, "depth": 14.0, "bore": 30.0, "clear": 22.9, "rod": 30.0, "axis_y": -3.9, "ring_d": 30.0, "ring_l": 11.4, "knob_d": 14.5, "knob_l": 8.3, "source": "drawing (height and axis offset worked out)"},
    "CXY1A": {"title": "30 mm Cage System, XY Translating Lens Mount for Ø1\" Optics", "kind": "xy", "w": 54.6, "h": 54.6, "depth": 15.2, "bore": 26.3, "clear": 22.9, "rod": 30.0, "knob_d": 10.4, "knob_l": 14.4, "source": "drawing (knob diameter as CXYZ05A)"},
    "CXYZ05A": {"title": "XYZ Translation Mount for Ø1/2\" Optics", "kind": "xy", "w": 54.6, "h": 54.6, "depth": 19.0, "bore": 13.6, "clear": 10.7, "rod": 30.0, "knob_d": 10.4, "knob_l": 14.2, "dial_d": 24.0, "dial_l": 4.4, "source": "drawing (zoom dial diameter estimated)"},
    "LCP33": {"title": "30 mm to 60 mm Cage Plate Adapter", "kind": "adapter_60", "w": 70.6, "h": 70.6, "depth": 12.7, "bore": 26.3, "clear": 22.9, "rod": 30.0, "rod_outer": 60.0, "source": "drawing"},
    "DLM1": {"title": "Dual Rotation Mount for Ø1\" Optics, Two Rotating Carriages", "kind": "dual", "w": 44.5, "h": 48.9, "depth": 24.6, "bore": 26.3, "clear": 22.9, "rod": 0.0, "axis_y": 1.0, "ring_d": 41.7, "ring_l": 4.8, "source": "drawing"},
    "C45M1": {"title": "Right-Angle Nested Rotation Mount for Ø1\" Optics, 30 mm Cage", "kind": "rotation45", "w": 40.5, "h": 29.9, "depth": 31.8, "bore": 30.5, "clear": 22.9, "rod": 30.0, "axis_y": 3.25, "ring_d": 30.5, "ring_l": 8.0, "source": "drawing (axis offset worked out; cell length estimated)"},
    "LCP6S": {"title": "60 mm Cage Plate, SM2 Threads, 6 mm Thick", "kind": "plate", "w": 71.1, "h": 71.1, "depth": 6.0, "bore": THREAD_OD["SM2"], "clear": 48.3, "rod": 60.0, "source": "drawing"},
    "LCP360R": {"title": "Pivoting, Quick-Release, Ø2\" Optic Mount for 60 mm Cage System", "kind": "dropin_cell", "w": 70.4, "h": 7.8, "depth": 14.0, "bore": 60.0, "clear": 48.3, "rod": 60.0, "ring_d": 60.0, "ring_l": 12.1, "knob_d": 14.5, "knob_l": 8.0, "source": "drawing"},
    "CDA1": {"title": "Drop-In 30 mm to 60 mm Cage System Adapter", "kind": "drop_adapter", "w": 70.6, "h": 37.8, "depth": 6.4, "bore": 31.8, "clear": 31.8, "rod": 30.0, "rod_outer": 60.0, "lower_w": 40.6, "lower_h": 25.4, "source": "drawing"},
    "CPA1": {"title": "30 mm Cage Alignment Plate with Ø0.9 mm Hole", "kind": "alignment", "w": 40.6, "h": 34.4, "depth": 1.3, "bore": 0.9, "clear": 0.9, "rod": 30.0, "top": 29.3, "bar_h": 11.3, "stem_w": 22.9, "source": "drawing"},
    "VRC2CPT": {"title": "30 mm Cage Alignment Plate with Visible and IR Disk (400 - 640 nm, 800 - 1700 nm)", "kind": "alignment", "w": 40.6, "h": 34.4, "depth": 1.3, "bore": 0.9, "clear": 0.9, "rod": 30.0, "top": 29.3, "bar_h": 11.3, "stem_w": 22.9, "disk_d": 12.7, "disk_t": 1.1, "disk_color": "#8a4a3c", "source": "drawing"},
    "VRC8CPT": {"title": "30 mm Cage Alignment Plate with NIR Disk (720 - 820 nm, 890 - 1065 nm, 1490 - 1590 nm)", "kind": "alignment", "w": 40.6, "h": 34.4, "depth": 1.3, "bore": 0.9, "clear": 0.9, "rod": 30.0, "top": 29.3, "bar_h": 11.3, "stem_w": 22.9, "disk_d": 12.7, "disk_t": 1.1, "disk_color": "#c9b458", "source": "drawing (same plate as VRC2CPT)"},
    "ERCPS": {"title": "Cage Plate Stop for ER Rods (one of a 4 pack)", "kind": "rod_stop", "w": 11.7, "h": 12.7, "depth": 3.6, "bore": 0.0, "clear": 0.0, "rod": 30.0, "source": "drawing"},
    "ER8": {"title": "Cage Assembly Rod, 8\" Long, Ø6 mm", "kind": "rod", "w": 6.0, "h": 6.0, "depth": 203.2, "bore": 0.0, "clear": 0.0, "rod": 30.0, "source": "drawing"},
    "C30L24": {"title": "30 mm Cage System Cover, 24\" Long (a set of four, round the cage)", "kind": "cover", "w": 44.9, "h": 44.9, "depth": 609.6, "bore": 0.0, "clear": 30.0, "rod": 30.0, "wall": 1.7, "source": "drawing"},
}

# 30 mm cage cubes (cube side, the face bores; "insert" says what the cube holds). BS20CAM is the adapter that
# holds a 20 mm cube inside a cage cube.
CAGE_CUBES = {
    "CCM1-4ER": {"title": "Compact Clamping 4-Port Prism/Mirror 30 mm Cage Cube", "side": 38.1, "bore": 26.3, "clear": 22.9, "rod": 30.0, "insert": "mirror", "source": "drawing"},
    "CM1-DCH": {"title": "30 mm Cage Cube with Dichroic Filter Mount", "side": 38.1, "bore": 26.3, "clear": 22.9, "rod": 30.0, "insert": "dichroic", "boss": 2.7, "source": "drawing (cube 38.1; 2.7 mm mounting boss below)"},
    "DFM1BS": {"title": "Kinematic Beamsplitter Cage Cube", "side": 50.8, "bore": 26.3, "clear": 22.9, "rod": 30.0, "insert": "plate", "axis_y": 6.3, "cap": 10.1, "source": "drawing (axis height worked out from the 31.7 mm axis height)"},
    "BS20CAM": {"title": "20 mm Beamsplitter Cube Adapter for Compact 30 mm Cage Cube", "side": 38.1, "bore": 26.3, "clear": 16.0, "rod": 30.0, "insert": "cube20", "source": "drawing gives only 25.4 x 25.4; shown fitted in a CCM1 cube"},
}

# Right-angle kinematic cage mounts (KCB1C drawing: a 48.3 mm triangular block, Ø22.4 SM1 ports; KCB2C: 76.2 mm,
# 60 mm cage, Ø41.9 ports).
RIGHT_ANGLE_MOUNTS = {
    "KCB1C": {"title": "Right-Angle Kinematic Mirror Mount, Smooth Cage Rod Bores, 30 mm Cage", "side": 48.3, "bore": 22.4, "clear": 16.0, "rod": 30.0, "knob_d": 7.9, "knob_l": 9.5, "source": "drawing (knob size estimated)"},
    "KCB2C": {"title": "Right-Angle Kinematic Mirror Mount, Smooth Cage Rod Bores, 60 mm Cage, SM2", "side": 76.2, "bore": 41.9, "clear": 32.0, "rod": 60.0, "knob_d": 12.0, "knob_l": 12.0, "source": "drawing (knob size estimated)"},
}

# --------------------------------------------------------------------------------------------- detectors
# kind: "can" (a bare TO can with leads), "sm05" (SM05-threaded housing with an SMA connector), "sphere"
# (integrating-sphere sensor), "console" (handheld power meter console with its sensor).
DETECTORS = {
    "FDS100": {"title": "Si Photodiode, 350 - 1100 nm, 3.6 x 3.6 mm Active Area", "kind": "can", "cap_d": 8.3, "cap_l": 2.5, "flange_d": 9.1, "flange_l": 1.0, "lead_l": 12.0, "range": (350, 1100), "source": "drawing (leads shortened from 38.1 for the view)"},
    "FGA01": {"title": "InGaAs Photodiode, 800 - 1700 nm, Ø0.12 mm Active Area", "kind": "can", "cap_d": 5.4, "cap_l": 3.6, "flange_d": 5.8, "flange_l": 0.6, "lead_l": 12.0, "range": (800, 1700), "source": "TO-46 can (estimated, no drawing read)"},
    "FGA015": {"title": "InGaAs Photodiode, 800 - 1700 nm, Ø150 µm Active Area", "kind": "can", "cap_d": 5.4, "cap_l": 3.6, "flange_d": 5.8, "flange_l": 0.6, "lead_l": 12.0, "range": (800, 1700), "source": "TO-46 can (estimated, no drawing read)"},
    "SM05PD4A": {"title": "Mounted InGaAs Photodiode, 900 - 1700 nm, Cathode Grounded", "kind": "sm05", "stack": [(9.3, THREAD_OD["SM05"]), (5.9, 11.2), (2.0, 9.5), (6.5, 6.4)], "range": (900, 1700), "source": "drawing (thread diameter from the SM05 standard)"},
    "S144C": {"title": "Integrating Sphere Photodiode Power Sensor, InGaAs, 800 - 1700 nm", "kind": "sphere", "sphere_d": 33.0, "port_d": 12.0, "range": (800, 1700), "source": "estimated (the drawing was not at the usual address)"},
    "PM121D": {"title": "Digital Power & Energy Console, Si Sensor, 400 - 1100 nm", "kind": "console", "box": (40.0, 77.0, 22.0), "range": (400, 1100), "source": "estimated (no drawing read)"},
}

# --------------------------------------------------------------------------------------------- LEDs
# Mounted LEDs (M660L4 / M730L5 drawings): the emitter board ahead of an SM1-threaded Ø30.5 housing, a finned
# heat sink and a cable boss. Fiber-coupled LEDs (M680F4 / M1300F1): a finned box with an SMA port.
def _mounted_led(nm: int | None, title: str, src: str) -> dict:
    return {"title": title, "kind": "mounted", "nm": nm, "board_d": 25.8, "board_l": 4.0, "core_d": 21.8, "core_l": 6.5,
            "sleeve_d": 30.5, "sleeve_l": 21.3, "fins": 12, "fin_d": 30.5, "root_d": 13.4, "fin_t": 1.1, "pitch": 2.4,
            "fin_l": 27.4, "boss_d": 6.9, "boss_l": 10.0, "source": src}


def _fiber_led(nm: int, title: str, src: str) -> dict:
    return {"title": title, "kind": "fiber", "nm": nm, "w": 35.0, "h": 32.0, "front_l": 9.0, "fin_l": 34.1, "slots": 12,
            "flange": (65.0, 6.0, 34.0), "port_d": 6.5, "port_l": 4.3, "axis_h": 15.0, "source": src}


LEDS = {
    "M660L4": _mounted_led(660, "660 nm, 940 mW (Min) Mounted LED, 1200 mA", "drawing"),
    "M730L5": _mounted_led(730, "730 nm, 540 mW (Min) Mounted LED, 1000 mA", "drawing"),
    "M1300L4": _mounted_led(1300, "1300 nm, 122.8 mW (Min) Mounted LED, 1000 mA", "as M660L4 (same housing)"),
    "M1450L4": _mounted_led(1450, "1450 nm, 81.8 mW (Min) Mounted LED, 1000 mA", "as M660L4 (same housing)"),
    "MNWHL4": _mounted_led(None, "4900 K, 740 mW (Min) Mounted White LED, 1225 mA", "as M660L4 (same housing)"),
    "M680F4": _fiber_led(680, "680 nm, 5.9 mW (Min) Fiber-Coupled LED, SMA", "drawing"),
    "M1300F1": _fiber_led(1300, "1300 nm, 1.42 mW (Min) Fiber-Coupled LED, SMA", "drawing"),
}

# --------------------------------------------------------------------------------------------- fiber collimators
# A Ø11 stainless barrel with an M11 x 0.5 front, then the FC or SMA adapter at the back.
def _col(title: str, f: float, length: float, conn: str, src: str) -> dict:
    return {"title": title, "d": 11.0, "length": length, "f": f, "connector": conn, "conn_d": 8.8 if conn == "FC" else 6.5,
            "conn_l": 5.2 if conn == "FC" else 7.7, "source": src}


COLLIMATORS = {
    "F220APC-980": _col("980 nm, f = 11.16 mm, NA = 0.25 FC/APC Fiber Collimation Pkg.", 11.16, 15.6, "FC", "drawing"),
    "F280APC-980": _col("980 nm, f = 18.53 mm, NA = 0.15 FC/APC Fiber Collimation Pkg.", 18.53, 22.1, "FC", "drawing"),
    "F280APC-1550": _col("1550 nm, f = 18.75 mm, NA = 0.15 FC/APC Fiber Collimation Pkg.", 18.75, 22.1, "FC", "as F280APC-980 (same housing)"),
    "F280FC-980": _col("980 nm, f = 18.53 mm, NA = 0.15 FC/PC Fiber Collimation Pkg.", 18.53, 22.1, "FC", "as F280APC-980 (same housing)"),
    "F280SMA-B": _col("633 nm, f = 18.24 mm, NA = 0.15 SMA905 Fiber Collimation Pkg.", 18.24, 22.1, "SMA", "drawing"),
    "F280SMA-C": _col("1310 nm, f = 18.67 mm, NA = 0.15 SMA905 Fiber Collimation Pkg.", 18.67, 22.1, "SMA", "as F280SMA-B (same housing)"),
}

CAMERAS["CS165MU"] = {"title": "Zelux 1.6 MP Monochrome CMOS Camera, 1/4\"-20 Taps", "body": (15.0, 43.7, 47.2), "mount": "SM1", "cage": 30.0, "source": "drawing"}

# --------------------------------------------------------------------------------------------- breadboards
# Positions in mm from the drawing's top-left corner, x across the long side, y down the drawing. "taps" and
# "pockets" are grids (first centre, count, pitch); "holes" are through holes (x, y, diameter).
def _attocube_holes():
    sides = [(x, y, 6.6) for x in (16.5, 483.5) for y in (50, 125, 200, 275, 350, 425)]      # fixing holes, two edges
    corners = [(x, y, 5.5) for x in (11.0, 489.0) for y in (11.0, 464.0)]
    centre = [(250.0, 400.0, 31.0)] + [(250.0 + sx * 15.0, 400.0 + sy * 15.0, 6.0) for sx in (-1, 1) for sy in (-1, 1)]
    return sides + corners + [(250.0, 21.0, 4.0), (250.0, 470.0, 4.0)] + centre


BREADBOARDS = {
    "attocube 1011879-2": {
        "title": "attocube Breadboard, 25 mm Raster, for the attoDRY Optical Table",
        "length": 500.0, "width": 475.0, "thickness": 10.0, "corner_r": 5.0,
        "taps": {"d": 6.0, "x0": 50.0, "y0": 50.0, "cols": 17, "rows": 16, "pitch": 25.0},        # M6, 400 x 375
        "pockets": {"d": 22.0, "x0": 37.5, "y0": 37.5, "cols": 18, "rows": 17, "pitch": 25.0},    # blind, drawn filled
        "holes": _attocube_holes(),                         # the Ø31 hole 75 mm from the near edge, 4 x M6 on □30
        "keep_clear": (250.0, 400.0, 28.0),                 # no tap or pocket this close to the Ø31 hole
        "source": "attocube customer drawing 1011879-2 (sizes dimensioned; fixing-hole positions read off the drawing)",
    },
}

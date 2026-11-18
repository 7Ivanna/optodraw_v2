# browser: no (the cross-section engine needs shapely and PyYAML, which the browser Python does not load)
# The left end of the device from above, tilted 40 degrees, as a finished chip
from optodraw.gds import top_view

chip = top_view(layout, "gdsfactory_generic", (-3, -5, 7, 5), stage="chip")
assert chip.check() == [], chip.check()
chip.png(tilt=40.0, width_px=1000)

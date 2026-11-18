# browser: no (the plot needs matplotlib and the section needs shapely)
# A page of insets: a bench, a plot, a picture and a section, with a callout
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from optodraw import Callout, Image, Page, SectionView
from optodraw.gds import stack_section
from PIL import Image as Pixels

page = Page(width_mm=183)
plt.rcParams.update({"font.size": 6})
fig, ax = plt.subplots(figsize=(1.8, 1.4), layout="constrained")
ax.plot([0, 1, 2, 3], [0, 1, 4, 9])
ax.set_xlabel("x (a.u.)")
ax.set_ylabel("y (a.u.)")
# the same waveguide as an SEM-like render, 12 um wide: pixels, kind="render" (a photo is kind="measured", 300 ppi up)
wide = stack_section("gdsfactory_generic", (1, 0), width=0.5, window=(0.0, 12.0))
picture = Image(np.asarray(Pixels.open(io.BytesIO(wide.png(width_px=900)))), kind="render")
section = SectionView(stack_section("gdsfactory_generic", (1, 0), width=0.5))
bench, chart, photo, cut = page.row([scene, fig, picture, section])
page.add(Callout("Core", center=cut.at(7.4, 2.2), target=cut.at(6.0, 0.11)))
page

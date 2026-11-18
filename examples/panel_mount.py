''' Laser cut design file
    A panel with 3 SMA connectors and a through hole for mounting
    See below for options on staggering connectors
'''
import drawsvg as draw
from optodraw import *

d = draw.Drawing(2.8, 1, font_family='Helvetica')

cuts = dict(fill='none', stroke_width=0.01, stroke='black')
etch = dict(fill='none', stroke_width=0.01, stroke='red')

d.append(draw.Rectangle(0, 0, 2.8, 1, **cuts)) # outline
d.append(draw.Circle(.48, .5, 0.125 + .01, **cuts)) # mount hole
d.append(draw.Line(1,1,1,0,**etch))

# Simple backward-compatible drawsvg Transformable adapter
class Transformable(draw.Group):
    def __init__(self, center=(0, 0), angle=0, **kwargs):
        super().__init__(transform=f"translate({center[0]},{center[1]}) rotate({angle})", **kwargs)

class SMAFlange(Transformable):
    def __init__(self, label=None, flip_label=False, **kwargs):
        super().__init__(**kwargs)
        if not isinstance(flip_label, bool):
            flip_label = flip_label < 0
        # flip_label = -1 if flip_label else 1
        self.append(draw.Circle(0, 0, 0.125 + .01, **cuts))
        for NS in [-1, 1]:
            for EW in [-1, 1]:
                self.append(draw.Circle(NS * .17, EW * .17, 0.051, **cuts))
        self.append(draw.Rectangle(-.25, -.25, .5, .5, **etch))
        if label is not None:
            if flip_label:
                posn_args = (-.3, .1)
                posn_kws = dict(
                    text_anchor='end',
                    dominant_baseline='auto',
                )
            else:
                posn_args = (.3, .1)
                posn_kws = dict(
                    text_anchor='start',
                    dominant_baseline='auto',
                )
            self.append(draw.Text(
                label, .3, *posn_args, **posn_kws,
                **etch
            ))

vpitch = 0.575
stagger = .2
origin = (1.35, 0.5)
do_flipping = True
for i in range(3):
    side = (-1) ** (i % 2)
    label = ['X', 'Y', 'Z'][::-1][i]
    cent = [origin[0] + i * vpitch, -origin[1] + side * stagger]
    # Invert stagger / origin to draw properly on standard SVG top-left coordinates if cent y is negative
    cent = [origin[0] + i * vpitch, origin[1] - side * stagger]
    flange = SMAFlange(center=cent, angle=90, label=label, flip_label=(do_flipping and (i % 2) == 1))
    d.append(flange)


d.set_render_size(400)
d.save_svg('3sma_panel.svg')

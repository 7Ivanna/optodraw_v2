optodraw can show light moving through a setup: as an animated GIF, as an MP4 video, or live in the 3D
view.

## A GIF in one line

```python
scene.render_gif("setup.gif")      # the parts appear in order, then the light runs
```

The `gif` extra needs the Cairo library on your system (`brew install cairo` on a Mac,
`apt install libcairo2` on Ubuntu).

## A timeline with captions

```python
tl = scene.timeline()
tl.show(laser, caption="The pump laser")
tl.trace(beam, caption="The beam reaches the sample")
tl.absorb(beam, caption="The detector absorbs it")
tl.render_gif("story.gif", fps=6)
tl.render_video("story.mp4")       # the same steps through Manim
```

| Step | What it shows |
|---|---|
| `show` | One part appears |
| `trace` | A beam or route grows along its path |
| `wave_travel` | A bright packet moves along a path |
| `cavity_power` | A resonator builds up energy |
| `absorb` | Light arrives and disappears at a detector |
| `pause` | The picture holds |

## Live in 3D

The 3D page draws the light from the same physics engine. Press Light, or pass `animate=True`. The Light look
shows pulses inside the guides at the speed the medium gives them. The Field look shows the steady-state field.
Play tour visits each device in turn, and `scene.render_tour_video("tour.mp4")` saves the tour as a video.

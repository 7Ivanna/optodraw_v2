# The x8.9 beam expander of Curd et al., Methods 88, 37-47 (2015), Fig. 1A, traced (1 unit = 4 mm)
from optodraw import Laser, Lens, Scene
from optodraw.core.raytrace import trace_bundle

scene = Scene(title="Beam expander", platform="free_space")
laser = scene.add(Laser(center=(-78, 0), wavelength=488, label="488 nm laser"))
lens1 = scene.add(Lens(center=(-58, 0), focal_length=45 / 4, aperture=6, label="f = 45 mm"))
lens2 = scene.add(Lens(center=(-58 + (45 + 400) / 4, 0), focal_length=400 / 4, aperture=24, label="f = 400 mm"))
rays = trace_bundle(scene, (laser, "out"), rays=7, width=2.0, exit_length=16)
for ray in rays:
    scene.add(ray.as_beam(wavelength=488, width=0.25))
scene.fit_frame(margin=8)
scene

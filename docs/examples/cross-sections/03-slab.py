# browser: no (the cross-section engine needs shapely and PyYAML, which the browser Python does not load)
# The same cut as a 3D slab, 16 µm deep: drag to turn it
slab = xs.slab(depth=16)                               # the scene that holds the slab
slab.render_threejs(show_labels=False, camera_direction=(0.55, -1.0, 1.1))

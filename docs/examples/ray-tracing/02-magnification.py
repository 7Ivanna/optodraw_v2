# How much wider is the beam after the expander?
start = max(abs(ray.points[0].y) for ray in rays)
end = max(abs(ray.points[-1].y) for ray in rays)
print(f"{end / start:.1f} times wider (400 mm / 45 mm = {400 / 45:.1f})")

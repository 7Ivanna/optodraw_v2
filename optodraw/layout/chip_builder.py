"""On-chip layout helpers using physical spacing and schematic components."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from optodraw.components.onchip import (
    MZM,
    DirectionalCoupler,
    MicroringResonator,
    MicroringWeightBank,
    OnChipPhotodetector,
    Terminator,
    VerticalGratingCoupler,
    Waveguide,
)
from optodraw.core.scene import Scene
from optodraw.core.routing import Route
from optodraw.core.transform import Vec3


CellKwargs = Mapping[tuple[int, int], Mapping[str, Any]] | Callable[[int, int], Mapping[str, Any] | None]


def _physical_extent_um(component) -> tuple[float, float]:
    """Return conservative (width, height) in physical µm for placement spacing."""

    spec = component.physical_spec()
    values = spec.values if hasattr(spec, "values") else spec
    component_type = getattr(component, "component_type", component.__class__.__name__)

    if component_type == "VerticalGratingCoupler":
        length = float(values.get("length", getattr(component, "length", 40.0)))
        width = float(values.get("width", getattr(component, "width", 26.0)))
        return length, width
    if component_type == "MicroringResonator":
        radius = float(values.get("ring_radius", getattr(component, "ring_radius", 10.0)))
        gap = float(values.get("gap", getattr(component, "gap", 0.2)))
        wg_width = float(values.get("waveguide_width", getattr(component, "waveguide_width", 0.5)))
        diameter = 2.0 * radius
        bus_span = diameter + 2.0 * (gap + wg_width)
        return diameter, bus_span
    if component_type == "OnChipPhotodetector":
        length = float(values.get("length", getattr(component, "length", 40.0)))
        width = float(values.get("footprint_width", getattr(component, "footprint_width", 25.0)))
        return length, width
    if component_type == "MMI1x2":
        body = float(values.get("body_length", getattr(component, "body_length", 5.5)))
        taper = float(values.get("taper_length", getattr(component, "taper_length", 10.0)))
        width = float(values.get("body_width", getattr(component, "body_width", 2.5)))
        return body + 2.0 * taper, width
    if component_type == "MZM":
        arm = float(values.get("arm_length", getattr(component, "arm_length", 40.0)))
        gap = float(values.get("arm_gap", getattr(component, "arm_gap", 8.0)))
        coupler = float(values.get("coupler_length", getattr(component, "coupler_length", 16.0)))
        return arm + 2.0 * coupler, arm + gap + 4.0
    if component_type == "Waveguide":
        length = float(values.get("length", getattr(component, "length", 20.0)))
        width = float(values.get("width", getattr(component, "width", 0.5)))
        return length, width

    from optodraw.layout import estimate_component_size

    return estimate_component_size(component)


def _place_line_physical(
    components: list[Any],
    *,
    origin: tuple[float, float] = (0.0, 0.0),
    spacing_um: float = 8.0,
) -> None:
    """Place components along +x using physical footprints plus margin."""

    cursor_x = origin[0]
    previous_half = 0.0
    for index, component in enumerate(components):
        width, _height = _physical_extent_um(component)
        half = width / 2.0
        if index == 0:
            center_x = cursor_x + half
        else:
            center_x = cursor_x + previous_half + spacing_um + half
        component.transform.position = Vec3(center_x, origin[1], component.transform.position.z)
        cursor_x = center_x
        previous_half = half


def build_ring_filter(
    scene: Scene | None = None,
    *,
    title: str = "Ring Filter",
    add_drop: bool = True,
    spacing_um: float = 12.0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a GC → microring → photodetector filter using physical spacing.

    Components render with schematic-default geometry; ports and routes stay in
    true µm.  Pass ``render_physical=True`` on any component kwargs to draw PDK
    footprints instead.
    """

    chip = scene or Scene(title=title, width=320, height=140, platform="on_chip")
    gc = chip.add(
        VerticalGratingCoupler(
            center=(0, 0),
            angle=180,  # a coupler's waveguide leaves along -x, so face it into the chain
            label=kwargs.get("gc_label", "GC"),
            material_preset=kwargs.get("material_preset", "silicon"),
            **kwargs.get("gc_kwargs", {}),
        )
    )
    ring = chip.add(
        MicroringResonator(
            center=(0, 0),
            ring_radius=float(kwargs.get("ring_radius", 10.0)),
            gap=float(kwargs.get("gap", 0.2)),
            add_drop=add_drop,
            label=kwargs.get("ring_label", "Ring"),
            material_preset=kwargs.get("material_preset", "silicon"),
            **kwargs.get("ring_kwargs", {}),
        )
    )
    pd = chip.add(
        OnChipPhotodetector(
            center=(0, 0),
            label=kwargs.get("pd_label", "PD"),
            material_preset=kwargs.get("material_preset", "silicon"),
            **kwargs.get("pd_kwargs", {}),
        )
    )
    # Chain by PORTS, not by footprint: the ring's bus sits well below its centre,
    # so lining the three parts up on their centres left every link with a jog.
    from optodraw.layout import chain_ports  # local: optodraw.layout imports this module

    out_port = "o4" if add_drop else "o2"
    origin_x, origin_y = kwargs.get("origin", (-120.0, 0.0))
    gc.transform.position = Vec3(float(origin_x), float(origin_y), 0.0)
    links = [(gc, "o1", ring, "o1"), (ring, out_port, pd, "o1")]
    if add_drop:
        term = chip.add(Terminator(label="term"))
        add = chip.add(Terminator(angle=180, label="add"))
        links.extend([(ring, "o2", term, "o1"), (ring, "o3", add, "o1")])
    chain_ports(links, gap=spacing_um)

    route_in = chip.route((gc, "o1"), (ring, "o1"), kind="waveguide", path_type="straight")
    routes: list[Route] = [route_in]
    routes.append(chip.route((ring, out_port), (pd, "o1"), kind="waveguide", path_type="straight"))
    if add_drop:
        routes.append(chip.route((ring, "o2"), (term, "o1"), kind="waveguide", path_type="straight"))
        routes.append(chip.route((ring, "o3"), (add, "o1"), kind="waveguide", path_type="straight"))

    return {
        "scene": chip,
        "grating_coupler": gc,
        "ring": ring,
        "photodetector": pd,
        "routes": routes,
    }


def build_mzm_coupler_mesh(
    scene: Scene | None = None,
    *,
    title: str = "MZM Coupler Mesh",
    modes: int = 4,
    layers: int | None = None,
    drive_style: str = "gsg",
    mode_pitch_um: float = 32.0,
    stage_pitch_um: float = 68.0,
    origin: tuple[float, float] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a programmable photonic **mesh**: per-mode MZM modulators interleaved
    with staggered directional couplers that mix adjacent modes (Clements-style).

    Unlike :func:`build_mzm_mesh` (a routed grid), this is a real interferometric
    mesh — N input modes pass through alternating modulator/coupler stages, where the
    directional couplers connect adjacent modes in the brick pattern. Returns
    ``{scene, mzms, couplers, routes, inputs, outputs, modes, layers}``.
    """

    n = max(2, int(modes))
    depth = max(1, int(layers) if layers else n)
    width = max(300, (2 * depth + 2) * stage_pitch_um + 80)
    height = max(160, n * mode_pitch_um + 80)
    chip = scene or Scene(title=title, width=width, height=height, platform="on_chip")
    # The mesh grows to the RIGHT of its origin, so a fixed origin pushed larger
    # meshes off the right edge of their own frame. Start half a span to the left
    # and the layout lands centred whatever its size.
    ox, oy = origin if origin is not None else (-(width - 80.0) / 2.0, 0.0)

    def mode_y(mode: int) -> float:
        return oy + (mode - (n - 1) / 2.0) * mode_pitch_um

    mzms: list[MZM] = []
    couplers: list[DirectionalCoupler] = []
    routes: list[Route] = []
    inputs: list[Waveguide] = []
    outputs: list[Waveguide] = []
    last: dict[int, tuple[Any, str]] = {}
    # Local smooth (rounded-manhattan) routing — the gdsfactory backend loops the
    # converging guides around the small couplers; the local backend gives the clean
    # symmetric fan-in/out seen on real mesh layouts.
    route_kw: dict[str, Any] = dict(kind="waveguide", path_type="manhattan", smooth=True, backend="local", bend_radius=8.0)
    # uniform waveguide width across the mesh: match the I/O stubs to the MZM/DC ports
    # so every route (port-derived width) renders at the same thickness.
    wg_w = MZM(arm_length=22.0, arm_gap=7.0, coupler_length=12.0, drive_style=drive_style, visual_scale=0.66).ports()["o1"].width

    x = ox
    for w in range(n):
        stub = chip.add(Waveguide(center=(x, mode_y(w)), length=14.0, width=wg_w, label=f"in {w + 1}"))
        inputs.append(stub)
        last[w] = (stub, "o2")

    for stage in range(depth):
        x += stage_pitch_um
        for w in range(n):
            # compact MZM (shorter I/O ends) + compact DC below leave real gaps
            # between columns so the converging guides have room to route cleanly.
            mzm = chip.add(MZM(center=(x, mode_y(w)), arm_length=22.0, arm_gap=7.0, coupler_length=12.0, drive_style=drive_style, visual_scale=0.66, label=f"M{stage + 1}.{w + 1}"))
            routes.append(chip.route(last[w], (mzm, "o1"), **route_kw))
            last[w] = (mzm, "o3")
            mzms.append(mzm)
        x += stage_pitch_um
        for w in range(stage % 2, n - 1, 2):
            cy = (mode_y(w) + mode_y(w + 1)) / 2.0
            dc = chip.add(DirectionalCoupler(center=(x, cy), coupling_length=10.0, port_spacing=mode_pitch_um, visual_scale=0.7, label=""))
            # mode w sits below mode w+1, so wire the lower mode to the DC's lower
            # ports (o2/o4) and the upper mode to the upper ports (o1/o3) — pairing
            # them the other way makes the router loop the guides around.
            routes.append(chip.route(last[w], (dc, "o2"), **route_kw))
            routes.append(chip.route(last[w + 1], (dc, "o1"), **route_kw))
            last[w] = (dc, "o4")
            last[w + 1] = (dc, "o3")
            couplers.append(dc)

    x += stage_pitch_um
    for w in range(n):
        stub = chip.add(Waveguide(center=(x, mode_y(w)), length=14.0, width=wg_w, label=f"out {w + 1}"))
        outputs.append(stub)
        routes.append(chip.route(last[w], (stub, "o1"), **route_kw))

    return {"scene": chip, "mzms": mzms, "couplers": couplers, "routes": routes, "inputs": inputs, "outputs": outputs, "modes": n, "layers": depth}


def _mesh_size(rows: int, cols: int) -> tuple[int, int]:
    """Normalize user-requested mesh size while preserving historical one-cell fallback."""

    return max(int(rows), 1), max(int(cols), 1)


def _mesh_topology(topology: str) -> str:
    normalized = topology.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "2d": "rectangular",
        "full": "rectangular",
        "grid": "rectangular",
        "rows": "row",
        "horizontal": "row",
        "columns": "column",
        "vertical": "column",
        "snake": "serpentine",
        "path": "serpentine",
        "none": "none",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"rectangular", "row", "column", "serpentine", "none"}:
        raise ValueError("topology must be rectangular, row, column, serpentine, or none")
    return normalized


def _cell_kwargs(source: CellKwargs | None, row: int, col: int) -> dict[str, Any]:
    if source is None:
        return {}
    if callable(source):
        return dict(source(row, col) or {})
    return dict(source.get((row, col), {}))


def _append_mesh_route(
    chip: Scene,
    routes: list[Route],
    links: list[dict[str, Any]],
    *,
    source: Any,
    source_rc: tuple[int, int],
    source_port: str,
    target: Any,
    target_rc: tuple[int, int],
    target_port: str,
    direction: str,
    link_width_um: float | None,
    link_path_type: str,
    bend_radius_um: float,
    start_straight_um: float,
    end_straight_um: float,
    routing_backend: str,
) -> Route:
    route = chip.route(
        (source, source_port),
        (target, target_port),
        kind="waveguide",
        path_type=link_path_type,
        width=link_width_um,
        bend_radius=bend_radius_um,
        start_straight_length=start_straight_um,
        end_straight_length=end_straight_um,
        backend=routing_backend,
    )
    routes.append(route)
    links.append(
        {
            "direction": direction,
            "source": source_rc,
            "source_port": source_port,
            "target": target_rc,
            "target_port": target_port,
            "route": route,
        }
    )
    return route


def _mzm_link_pairs(topology: str, rows: int, cols: int) -> list[dict[str, Any]]:
    if topology == "none":
        return []
    if topology == "serpentine":
        path: list[tuple[int, int]] = []
        for row in range(rows):
            col_range = range(cols) if row % 2 == 0 else range(cols - 1, -1, -1)
            path.extend((row, col) for col in col_range)
        pairs: list[dict[str, Any]] = []
        for source, target in zip(path, path[1:]):
            sr, sc = source
            tr, tc = target
            if sr == tr and sc < tc:
                source_port, target_port, direction = "o3", "o1", "east"
            elif sr == tr:
                source_port, target_port, direction = "o1", "o3", "west"
            else:
                source_port, target_port, direction = "o4", "o2", "south"
            pairs.append(
                {
                    "source": source,
                    "target": target,
                    "source_port": source_port,
                    "target_port": target_port,
                    "direction": direction,
                }
            )
        return pairs

    pairs = []
    if topology in {"rectangular", "row"}:
        for row in range(rows):
            for col in range(cols - 1):
                pairs.append(
                    {
                        "source": (row, col),
                        "target": (row, col + 1),
                        "source_port": "o3",
                        "target_port": "o1",
                        "direction": "east",
                    }
                )
    if topology in {"rectangular", "column"}:
        for row in range(rows - 1):
            for col in range(cols):
                pairs.append(
                    {
                        "source": (row, col),
                        "target": (row + 1, col),
                        "source_port": "o4",
                        "target_port": "o2",
                        "direction": "south",
                    }
                )
    return pairs


def _add_mzm_edge_io(
    chip: Scene,
    grid: list[list[MZM]],
    routes: list[Route],
    *,
    topology: str,
    io_stub_length_um: float,
    io_gap_um: float,
    link_width_um: float | None,
    link_path_type: str,
    bend_radius_um: float,
    routing_backend: str,
) -> tuple[list[Waveguide], list[Waveguide], list[Route]]:
    inputs: list[Waveguide] = []
    outputs: list[Waveguide] = []
    io_routes: list[Route] = []
    rows = len(grid)

    if topology == "serpentine":
        entry = grid[0][0]
        exit_row = rows - 1
        exit_col = len(grid[exit_row]) - 1 if exit_row % 2 == 0 else 0
        exit_cell = grid[exit_row][exit_col]
        exit_port = "o3" if exit_row % 2 == 0 else "o1"
        entry_port = entry.world_port("o1")
        input_wg = chip.add(
            Waveguide(
                center=(entry_port.center.x - io_gap_um - io_stub_length_um / 2.0, entry_port.center.y),
                length=io_stub_length_um,
                width=link_width_um or entry_port.width,
                label="mesh input",
            )
        )
        exit_world_port = exit_cell.world_port(exit_port)
        output_sign = 1.0 if exit_port == "o3" else -1.0
        output_wg = chip.add(
            Waveguide(
                center=(
                    exit_world_port.center.x + output_sign * (io_gap_um + io_stub_length_um / 2.0),
                    exit_world_port.center.y,
                ),
                length=io_stub_length_um,
                width=link_width_um or exit_world_port.width,
                label="mesh output",
            )
        )
        inputs.append(input_wg)
        outputs.append(output_wg)
        io_routes.append(
            chip.route(
                (input_wg, "o2"),
                (entry, "o1"),
                kind="waveguide",
                path_type=link_path_type,
                width=link_width_um,
                bend_radius=bend_radius_um,
                backend=routing_backend,
            )
        )
        output_start = (exit_cell, exit_port)
        output_end = (output_wg, "o1" if exit_port == "o3" else "o2")
        io_routes.append(
            chip.route(
                output_start,
                output_end,
                kind="waveguide",
                path_type=link_path_type,
                width=link_width_um,
                bend_radius=bend_radius_um,
                backend=routing_backend,
            )
        )
        routes.extend(io_routes)
        return inputs, outputs, io_routes

    for row, row_cells in enumerate(grid):
        left_cell = row_cells[0]
        right_cell = row_cells[-1]
        left_port = left_cell.world_port("o1")
        right_port = right_cell.world_port("o3")
        input_wg = chip.add(
            Waveguide(
                center=(left_port.center.x - io_gap_um - io_stub_length_um / 2.0, left_port.center.y),
                length=io_stub_length_um,
                width=link_width_um or left_port.width,
                label=f"mesh input {row + 1}",
            )
        )
        output_wg = chip.add(
            Waveguide(
                center=(right_port.center.x + io_gap_um + io_stub_length_um / 2.0, right_port.center.y),
                length=io_stub_length_um,
                width=link_width_um or right_port.width,
                label=f"mesh output {row + 1}",
            )
        )
        inputs.append(input_wg)
        outputs.append(output_wg)
        io_routes.append(
            chip.route(
                (input_wg, "o2"),
                (left_cell, "o1"),
                kind="waveguide",
                path_type=link_path_type,
                width=link_width_um,
                bend_radius=bend_radius_um,
                backend=routing_backend,
            )
        )
        io_routes.append(
            chip.route(
                (right_cell, "o3"),
                (output_wg, "o1"),
                kind="waveguide",
                path_type=link_path_type,
                width=link_width_um,
                bend_radius=bend_radius_um,
                backend=routing_backend,
            )
        )
    routes.extend(io_routes)
    return inputs, outputs, io_routes


def build_mzm_mesh(
    scene: Scene | None = None,
    *,
    title: str = "MZM Mesh",
    rows: int = 2,
    cols: int = 2,
    row_pitch_um: float = 90.0,
    col_pitch_um: float = 110.0,
    origin: tuple[float, float] = (-80.0, 40.0),
    drive_style: str = "gs",
    topology: str = "rectangular",
    include_io: bool = False,
    cell_kwargs: CellKwargs | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a routed 2D mesh of Mach-Zehnder modulators.

    ``topology="rectangular"`` links adjacent columns and rows. Use ``"row"``
    for old row-cascade behavior, ``"column"`` for vertical-only meshes, and
    ``"serpentine"`` for a single snake path through every cell.
    """

    row_count, col_count = _mesh_size(rows, cols)
    mesh_topology = _mesh_topology(topology)
    # A cell is as wide as its arms, and every link needs a straight lead-in at
    # each end. Pitch the columns from the real footprint, or neighbouring cells
    # end up closer than their own links can span and the routes double back.
    _probe = MZM(
        arm_length=float(kwargs.get("arm_length", 36.0)),
        arm_gap=float(kwargs.get("arm_gap", 8.0)),
        drive_style=drive_style,
    )
    _cell_width = abs(float(_probe.ports()["o3"].center.x) - float(_probe.ports()["o1"].center.x))
    _lead_in = float(kwargs.get("link_straight_length_um", kwargs.get("link_length_um", 5.0)))
    col_pitch_um = max(float(col_pitch_um), _cell_width + 2.0 * _lead_in + 8.0)
    chip = scene or Scene(
        title=title,
        width=max(260, col_count * col_pitch_um + 120),
        height=max(160, row_count * row_pitch_um + 100),
        platform="on_chip",
    )
    mzms: list[MZM] = []
    grid: list[list[MZM]] = []
    routes: list[Route] = []
    links: list[dict[str, Any]] = []
    ox, oy = origin
    base_mzm_kwargs = dict(kwargs.get("mzm_kwargs", {}))

    for row in range(row_count):
        grid_row: list[MZM] = []
        for col in range(col_count):
            label = f"MZM {row + 1}.{col + 1}"
            per_cell_kwargs = {**base_mzm_kwargs, **_cell_kwargs(cell_kwargs, row, col)}
            arm_length = float(per_cell_kwargs.pop("arm_length", kwargs.get("arm_length", 36.0)))
            arm_gap = float(per_cell_kwargs.pop("arm_gap", kwargs.get("arm_gap", 8.0)))
            mzm_label = per_cell_kwargs.pop("label", label)
            material_preset = per_cell_kwargs.pop("material_preset", kwargs.get("material_preset", "silicon"))
            mzm = chip.add(
                MZM(
                    center=(ox + col * col_pitch_um, oy - row * row_pitch_um),
                    arm_length=arm_length,
                    arm_gap=arm_gap,
                    drive_style=per_cell_kwargs.pop("drive_style", drive_style),
                    label=mzm_label,
                    material_preset=material_preset,
                    **per_cell_kwargs,
                )
            )
            mzms.append(mzm)
            grid_row.append(mzm)
        grid.append(grid_row)

    link_width_um = kwargs.get("link_width_um")
    if link_width_um is not None:
        link_width_um = float(link_width_um)
    link_path_type = kwargs.get("link_path_type", kwargs.get("route_path_type", "straight"))
    bend_radius_um = float(kwargs.get("bend_radius_um", kwargs.get("bend_radius", 10.0)))
    link_straight_um = float(kwargs.get("link_straight_length_um", kwargs.get("link_length_um", 5.0)))
    routing_backend = kwargs.get("routing_backend", "local")

    for pair in _mzm_link_pairs(mesh_topology, row_count, col_count):
        source_row, source_col = pair["source"]
        target_row, target_col = pair["target"]
        _append_mesh_route(
            chip,
            routes,
            links,
            source=grid[source_row][source_col],
            source_rc=pair["source"],
            source_port=pair["source_port"],
            target=grid[target_row][target_col],
            target_rc=pair["target"],
            target_port=pair["target_port"],
            direction=pair["direction"],
            link_width_um=link_width_um,
            link_path_type=link_path_type,
            bend_radius_um=bend_radius_um,
            start_straight_um=link_straight_um,
            end_straight_um=link_straight_um,
            routing_backend=routing_backend,
        )

    inputs: list[Waveguide] = []
    outputs: list[Waveguide] = []
    io_routes: list[Route] = []
    if include_io:
        inputs, outputs, io_routes = _add_mzm_edge_io(
            chip,
            grid,
            routes,
            topology=mesh_topology,
            io_stub_length_um=float(kwargs.get("io_stub_length_um", 18.0)),
            io_gap_um=float(kwargs.get("io_gap_um", 8.0)),
            link_width_um=link_width_um,
            link_path_type=link_path_type,
            bend_radius_um=bend_radius_um,
            routing_backend=routing_backend,
        )

    return {
        "scene": chip,
        "mzms": mzms,
        "grid": grid,
        "routes": routes,
        "links": links,
        "inputs": inputs,
        "outputs": outputs,
        "io_routes": io_routes,
        "rows": row_count,
        "cols": col_count,
        "topology": mesh_topology,
    }


def build_microring_weight_mesh(
    scene: Scene | None = None,
    *,
    title: str = "Microring Weight Mesh",
    rows: int = 2,
    cols: int = 2,
    row_pitch_um: float = 120.0,
    col_pitch_um: float = 170.0,
    origin: tuple[float, float] = (-90.0, 50.0),
    topology: str = "rectangular",
    ring_count: int = 4,
    with_heaters: bool = True,
    cell_kwargs: CellKwargs | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a 2D grid of microring weight banks with row and drop-bus links."""

    row_count, col_count = _mesh_size(rows, cols)
    mesh_topology = _mesh_topology(topology)
    # A bank is as wide as its ring row; at the old fixed pitch neighbouring banks
    # physically OVERLAPPED, so each link ran backwards from one bus to the next.
    _probe = MicroringWeightBank(
        ring_count=int(ring_count),
        ring_pitch=float(kwargs.get("ring_pitch", 22.0)),
        ring_radius=float(kwargs.get("ring_radius", 8.0)),
    )
    _bank_width = abs(float(_probe.ports()["o2"].center.x) - float(_probe.ports()["o1"].center.x))
    _lead_in = float(kwargs.get("link_straight_length_um", kwargs.get("link_length_um", 5.0)))
    col_pitch_um = max(float(col_pitch_um), _bank_width + 2.0 * _lead_in + 10.0)
    chip = scene or Scene(
        title=title,
        width=max(300, col_count * col_pitch_um + 140),
        height=max(180, row_count * row_pitch_um + 120),
        platform="on_chip",
    )
    banks: list[MicroringWeightBank] = []
    grid: list[list[MicroringWeightBank]] = []
    routes: list[Route] = []
    links: list[dict[str, Any]] = []
    ox, oy = origin
    base_bank_kwargs = dict(kwargs.get("bank_kwargs", {}))

    for row in range(row_count):
        grid_row: list[MicroringWeightBank] = []
        for col in range(col_count):
            per_cell_kwargs = {**base_bank_kwargs, **_cell_kwargs(cell_kwargs, row, col)}
            bank_ring_pitch = float(per_cell_kwargs.pop("ring_pitch", kwargs.get("ring_pitch", 22.0)))
            bank_ring_radius = float(per_cell_kwargs.pop("ring_radius", kwargs.get("ring_radius", 8.0)))
            material_preset = per_cell_kwargs.pop("material_preset", kwargs.get("material_preset", "silicon"))
            bank = chip.add(
                MicroringWeightBank(
                    center=(ox + col * col_pitch_um, oy - row * row_pitch_um),
                    ring_count=int(per_cell_kwargs.pop("ring_count", ring_count)),
                    ring_pitch=bank_ring_pitch,
                    ring_radius=bank_ring_radius,
                    with_heaters=bool(per_cell_kwargs.pop("with_heaters", with_heaters)),
                    label=per_cell_kwargs.pop("label", f"Ring bank {row + 1}.{col + 1}"),
                    material_preset=material_preset,
                    **per_cell_kwargs,
                )
            )
            banks.append(bank)
            grid_row.append(bank)
        grid.append(grid_row)

    link_width_um = kwargs.get("link_width_um")
    if link_width_um is not None:
        link_width_um = float(link_width_um)
    link_path_type = kwargs.get("link_path_type", kwargs.get("route_path_type", "manhattan"))
    bend_radius_um = float(kwargs.get("bend_radius_um", kwargs.get("bend_radius", 10.0)))
    link_straight_um = float(kwargs.get("link_straight_length_um", kwargs.get("link_length_um", 5.0)))
    routing_backend = kwargs.get("routing_backend", "local")
    vertical_drop_port = kwargs.get("vertical_drop_port", "d1")

    for pair in _mzm_link_pairs(mesh_topology, row_count, col_count):
        source_row, source_col = pair["source"]
        target_row, target_col = pair["target"]
        if pair["direction"] in {"east", "west"}:
            source_port = "o2" if pair["direction"] == "east" else "o1"
            target_port = "o1" if pair["direction"] == "east" else "o2"
        else:
            source_port = vertical_drop_port
            target_port = "o1"
        _append_mesh_route(
            chip,
            routes,
            links,
            source=grid[source_row][source_col],
            source_rc=pair["source"],
            source_port=source_port,
            target=grid[target_row][target_col],
            target_rc=pair["target"],
            target_port=target_port,
            direction=pair["direction"],
            link_width_um=link_width_um,
            link_path_type=link_path_type,
            bend_radius_um=bend_radius_um,
            start_straight_um=link_straight_um,
            end_straight_um=link_straight_um,
            routing_backend=routing_backend,
        )

    return {
        "scene": chip,
        "banks": banks,
        "grid": grid,
        "routes": routes,
        "links": links,
        "rows": row_count,
        "cols": col_count,
        "topology": mesh_topology,
    }


__all__ = ["build_ring_filter", "build_microring_weight_mesh", "build_mzm_mesh"]

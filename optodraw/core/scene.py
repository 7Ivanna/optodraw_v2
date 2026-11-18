"""Scene — the root container and render dispatcher."""

from __future__ import annotations

import math
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from optodraw.animation import AnimationTimeline

from optodraw.core.beam import DEFAULT_BEAM_STYLE, BeamStyle
from optodraw.core.component import ANNOTATION_TYPES, Component, Group
from optodraw.core.transform import Transform, Vec3

_PHYSICS_WARNINGS_EMITTED: set[tuple[str, str]] = set()


def _default_units() -> dict[str, str]:
    from optodraw.schema import UNITS

    return dict(UNITS)


class Scene:
    """The top-level container for an optical setup.

    Usage::

        scene = Scene(title="My PL Setup")
        scene.add(Laser(center=(0, 0)))
        scene.render_svg("out.svg")
        scene.render_threejs("out.html")
    """

    def __init__(
        self,
        title: str = "Optical Setup",
        width: float = 200,
        height: float = 100,
        platform: str = "free_space",
        units: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
        layout: dict[str, dict[str, Any]] | None = None,
        beam_style: BeamStyle | None = None,
    ):
        self.title = title
        self.width = width
        self.height = height
        self.frame_center: tuple[float, float] = (0.0, 0.0)   # the middle of the export frame, in scene units
        self.platform = platform
        self._units = dict(_default_units() if units is None else units)
        if units is not None:
            from optodraw.schema import validate_units

            self._units = validate_units(self._units)
        self.root = Group(label="root")
        self._background = "#ffffff"
        self.metadata: dict[str, Any] = dict(metadata) if metadata else {}
        self.foundry_stack: str | None = None  # name/path of the applied z-stack
        if layout is not None:
            self.set_view_layout(layout)
        if beam_style is not None:
            self.beam_style = beam_style

    @property
    def units(self) -> dict[str, str]:
        """Scene length/angle/wavelength units from the product contract."""

        return dict(self._units)

    @property
    def beam_style(self) -> BeamStyle:
        """The look all the light of this scene shares: see :class:`~optodraw.core.beam.BeamStyle`."""

        return getattr(self.root, "beam_style", None) or DEFAULT_BEAM_STYLE

    @beam_style.setter
    def beam_style(self, style: BeamStyle) -> None:
        self.root.beam_style = style                      # beams walk up to find this

    # -- component management ----------------------------------------------
    def set_foundry_stack(self, name_or_path: str) -> dict[str, float]:
        """Apply a foundry layer stack as the scene's single z-truth.

        On-chip components (MZIs, rings, heaters, pads) extrude their metals and
        vias at the SAME real heights the stack gives an imported GDS — one
        consistent chip stack instead of per-component heuristics. Accepts a
        bundled stack name (e.g. "siepic_ebeam") or a YAML path. Returns the
        resolved component heights."""

        from optodraw.gds.parsers import load_layer_stack

        spec = load_layer_stack(name_or_path)
        heights = spec.component_heights()
        self.root.foundry_heights = heights  # components walk up to find this
        self.root.foundry_core = spec.component_core()   # and the materials of their core
        self.foundry_stack = str(name_or_path)
        return heights

    def add(self, component: Component) -> Component:
        """Add a component to the scene root."""
        return self.root.add(component)

    def group(self, label: str = "", **kwargs) -> Group:
        """Create and add a new group."""
        g = Group(label=label, transform=Transform(**kwargs) if kwargs else Transform())
        return self.root.add(g)

    def walk(self):
        """Iterate over all components depth-first."""
        yield from self.root.walk()

    def lens_beam(self, *stops, **kwargs) -> list[Component]:
        """Add a beam whose drawn width follows the lenses on its way: see :func:`optodraw.core.beam.lens_beam`."""

        from optodraw.core.beam import lens_beam

        return [self.add(piece) for piece in lens_beam(*stops, **kwargs)]

    def route(self, port1, port2, **kwargs):
        """Create, add, and return a port-routed interconnect."""
        from optodraw.core.routing import route_ports

        route = route_ports(port1, port2, **kwargs)
        route._request = (port1, port2, dict(kwargs))      # a spaced 3D view routes it again between moved parts
        return self.add(route)

    def route_bundle(self, ports1, ports2, **kwargs):
        """Create, add, and return a bundle of routed interconnects."""
        from optodraw.core.routing import route_bundle

        routes = route_bundle(ports1, ports2, **kwargs)
        for route in routes:
            self.add(route)
        return routes

    def _parts(self, components=None) -> list:
        """The components in this scene, without the links between them.

        ``None`` means "everything drawable": beams, routes, the grid and group
        wrappers are not parts to lay out or validate."""

        if components is not None:
            return list(components)
        from optodraw.core.component import NON_PART_TYPES

        return [
            node for node in self.walk()
            if getattr(node, "component_type", "") not in NON_PART_TYPES
        ]

    def arrange_line(self, components=None, **kwargs):
        """Arrange components linearly for quick setup building."""
        from optodraw.layout import arrange_line

        items = self._parts(components)
        return arrange_line(items, **kwargs)

    def arrange_grid(self, components=None, **kwargs):
        """Arrange components on a simple grid."""
        from optodraw.layout import arrange_grid

        items = self._parts(components)
        return arrange_grid(items, **kwargs)

    def content_bounds(self, margin: float = 0.0) -> tuple[float, float, float, float]:
        """``(min_x, min_y, max_x, max_y)`` around everything drawn, plus ``margin``."""

        from optodraw.layout import _bounds_from_geometry, estimate_component_size
        from optodraw.renderers.svg_renderer import stage_mark_box
        from optodraw.symbols.art import art_bounds, union

        xs: list[float] = []
        ys: list[float] = []
        for node in self.walk():
            ctype = getattr(node, "component_type", "")
            if ctype in ANNOTATION_TYPES:                 # a mark's text has its own place in the frame
                for x, y in node.drawn_points():
                    xs.append(x)
                    ys.append(y)
                continue
            if not ctype or ctype in {"Grid", "Group"}:
                continue
            if hasattr(node, "resolve_points"):           # a beam or a route: the light counts where it runs
                try:
                    points = node.resolve_points()
                except Exception:  # pragma: no cover - an unresolved link has no place yet
                    points = []
                half = float(getattr(node, "width", 0.0) or 0.0) / 2.0
                for point in points:
                    xs.extend((point[0] - half, point[0] + half))
                    ys.extend((point[1] - half, point[1] + half))
                continue
            try:
                local = union(_bounds_from_geometry(node.geometry_2d()), art_bounds(node))   # the art may reach further
                if local is None:
                    width, height = estimate_component_size(node)
                    local = (-width / 2.0, -height / 2.0, width / 2.0, height / 2.0)
            except Exception:  # pragma: no cover - a component with no drawable size
                continue
            mark = stage_mark_box(node)                   # a part on a stage shows a motion mark beside it
            if mark is not None:
                sx = -1.0 if getattr(node, "flip_horizontal", False) else 1.0   # the mark flips with the part
                sy = -1.0 if getattr(node, "flip_vertical", False) else 1.0
                xs_m, ys_m = sorted((sx * mark[0], sx * mark[2])), sorted((sy * mark[1], sy * mark[3]))
                local = union(local, (xs_m[0], ys_m[0], xs_m[1], ys_m[1]))
            # The local box, not a box centred on the origin. A component is
            # free to draw itself off centre, and several do on purpose: an AWG
            # puts its single input port on y=0 so a caller can route to it
            # without arithmetic, which leaves its whole arm bundle above the
            # point it was placed at. Assuming symmetry framed such a part with
            # half of it outside the picture.
            transform = node.world_transform
            corners = [(local[0], local[1]), (local[2], local[1]),
                       (local[2], local[3]), (local[0], local[3])]
            for corner in corners:
                point = transform.apply_to_point(Vec3(corner[0], corner[1], 0.0))
                xs.append(point.x)
                ys.append(point.y)
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)

    def fit_frame(self, margin: float = 12.0, *, grid: float = 10.0) -> "Scene":
        """Size the export frame around what the scene actually contains, and centre it there.

        A layout built from code — a mesh sized by its mode count, a bank sized
        by its ring count — does not know its own extent until it is built, so a
        hand-picked width eventually clips something off the edge of the figure.
        Dimensions land on ``grid`` so they stay round numbers."""

        min_x, min_y, max_x, max_y = self.content_bounds(margin)
        from optodraw.check import _label_box                 # the labels too: a long one at the edge stays in

        for node in self.walk():
            if getattr(node, "label", "") and callable(getattr(node, "ports", None)) and hasattr(node, "world_position"):
                try:
                    x0, y0, x1, y1 = _label_box(node, 8.0)
                except Exception:                              # a part the label rules cannot place: its box rules
                    continue
                min_x, min_y = min(min_x, x0 - 2.0), min(min_y, y0 - 2.0)
                max_x, max_y = max(max_x, x1 + 2.0), max(max_y, y1 + 2.0)
        step = grid or 1.0
        half = step / 2.0
        # the frame stands round the content where it is (content far from the origin is not framed twice over);
        # its centre lands on half a grid step, so a drawing round the origin keeps a frame centred on it
        cx = round((min_x + max_x) / 2.0 / half) * half
        cy = round((min_y + max_y) / 2.0 / half) * half
        self.width = math.ceil(2.0 * max(max_x - cx, cx - min_x) / step) * step
        self.height = math.ceil(2.0 * max(max_y - cy, cy - min_y) / step) * step
        self.frame_center = (float(cx), float(cy))
        return self

    def optimize_layout(self, components=None, **kwargs):
        """Apply a lightweight layout heuristic while building setups."""
        from optodraw.layout import optimize_layout

        items = self._parts(components)
        return optimize_layout(items, **kwargs)

    # -- render entry points -----------------------------------------------
    def set_view_layout(self, layout: dict[str, dict[str, Any]]) -> "Scene":
        """Set display spacing once for all exports and notebook tabs.

        Example: ``scene.set_view_layout({"3d": {"spacing": "auto", "clearance": 5}})``.
        The 1D view then follows source positions rather than automatic graph placement.
        Omitted views use spacing 1. Component sizes and beam heights do not scale.
        Settings are stored in scene metadata, not in component coordinates.
        """
        from optodraw.core.view_layout import validate_layout

        self.metadata["view_layout"] = validate_layout(layout)
        return self

    def render_svg(self, filename: str | None = None, **kwargs) -> Any:
        """Render the scene to SVG (2D). Returns the drawsvg Drawing."""
        from optodraw.renderers.svg_renderer import SvgRenderer

        from optodraw.core.view_layout import display_scene

        renderer = SvgRenderer(display_scene(self, "2d"), **kwargs)
        return renderer.render(filename)

    def render_threejs(self, filename: str | None = None, **kwargs) -> str:
        """Render the scene to an interactive Three.js HTML page (3D).

        The light follows ``metadata["animation"]`` (``look``, ``params``, ``inputs``) as the editor saves it; a
        ``look``, ``params`` or ``inputs`` argument takes its place."""
        from optodraw.animation3d.payload import animation_settings
        from optodraw.renderers.threejs_renderer import ThreeJsRenderer

        look, params, inputs = animation_settings(self.metadata)
        for name, value in (("look", look), ("params", params), ("inputs", inputs)):
            kwargs.setdefault(name, value)

        from optodraw.core.view_layout import display_scene

        renderer = ThreeJsRenderer(display_scene(self, "3d"), **kwargs)
        return renderer.render(filename)

    def render_tour_video(self, path: str, **options) -> Path:
        """Save the camera tour of the 3D view as a video (MP4 with ffmpeg, else WebM), frame by frame in headless
        Chrome (``render_video`` is the Manim animation). ``tour`` is ``"auto"`` or a ``Tour``; ``look``, ``params`` and ``inputs`` follow
        ``metadata["animation"]`` unless given; ``width``, ``height`` and ``fps`` set the size (1920 x 1080, 30)."""
        from optodraw.animation3d.payload import animation_settings
        from optodraw.animation3d.video import render_video
        from optodraw.core.view_layout import display_scene

        look, params, inputs = animation_settings(self.metadata)
        for name, value in (("look", look), ("params", params), ("inputs", inputs)):
            options.setdefault(name, value)
        return render_video(display_scene(self, "3d"), path, **options)

    def render_3d_image(self, filename: str, *, background: str = "none",
                        camera: str | tuple[float, float, float] = "isometric",
                        width: int = 1600, height: int = 1000, scale: float = 2.0, labels: bool = False,
                        engine: str = "studio", samples: int = 4, quality: str = "final",
                        chrome: str | None = None) -> Path:
        """Save the 3D view as a PNG (``width`` x ``height`` times ``scale`` pixels).

        ``background`` is ``"none"`` (transparent, no floor; the default, for papers), ``"light"`` or
        ``"dark"``. ``camera`` is a preset name or a direction ``(x, y, z)`` toward the camera (z up).
        ``engine="studio"`` (the default) is optodraw's own renderer: studio light, soft
        shadows, ambient occlusion and reflections, on the CPU of any machine, with ``samples`` per
        pixel; ``quality="draft"`` is a quick look. ``engine="viewer"`` saves the viewer's real-time
        render. Both need Chrome, Chromium or Edge (``OPTODRAW_CHROME`` names one).
        """
        from optodraw.renderers.capture3d import render_3d_image

        from optodraw.core.view_layout import display_scene

        return render_3d_image(display_scene(self, "3d"), filename, background=background, camera=camera, width=width,
                               height=height, scale=scale, labels=labels, engine=engine, samples=samples,
                               quality=quality, chrome=chrome)

    def render_3d_svg(self, path: str | Path, **options: Any) -> Path:
        """Save the 3D view as one vector SVG, with no Chrome: the viewer's solids with their hidden parts cut away.

        ``options`` go to :func:`optodraw.renderers.vector3d.render_3d_svg`: ``direction`` (a camera preset name or
        ``(x, y, z)`` toward the camera, z up), ``projection`` (``"perspective"`` or ``"parallel"``), ``style``,
        ``width_mm`` (120 by default; the height follows the content), ``shadows`` (True by default),
        ``camera="home"`` (the viewer's framed pose) and ``face_limit`` (``FACE_LIMIT`` front faces by default). A
        part the vector view cannot draw, or a view over the face limit, raises ``Vector3DError``, which names the
        part or the ways out. As an inset of a figure, use ``View3D``."""

        from optodraw.renderers.vector3d import render_3d_svg

        return render_3d_svg(self, path, **options)

    def preview(
        self,
        width: int = 900,
        height: int = 520,
        *,
        title: str | None = None,
        show_3d: bool = True,
        layout: dict[str, dict[str, Any]] | None = None,
        **kwargs,
    ):
        """A fixed size, zoomable notebook view with 2D and 3D tabs.

        Returns an object that renders itself in a notebook cell, so the usual
        call is simply the last line of a cell::

            scene.preview()
            scene.preview(width=1100, height=600)
            scene.preview(show_3d=False)          # 2D only, much smaller output
            scene.preview().save("viewer.html")   # standalone file

        The pane keeps the size you give it however large the drawing is: scroll
        to zoom, drag to pan, double click to fit. Rendering a scene any other
        way in a notebook produces an SVG that grows to the size of the layout,
        which for a chip floorplan means scrolling the page instead of the view.
        """
        from optodraw.viewer import ScenePreview

        scene = self
        if layout is not None:
            from copy import deepcopy

            scene = deepcopy(self).set_view_layout(layout)
        return ScenePreview(scene, width=width, height=height, title=title,
                            show_3d=show_3d, **kwargs)

    def render_interactive_html(self, filename: str | None = None, **kwargs) -> str:
        """Render an authoring-oriented Three.js page with component sidebar."""
        from optodraw.renderers.interactive_scene import export_interactive_html

        return export_interactive_html(self, filename, **kwargs)

    def render_tikz(self, filename: str | None = None, **kwargs) -> str:
        """Render the scene to TikZ/PGF for LaTeX."""
        from optodraw.renderers.tikz_renderer import TikzRenderer

        renderer = TikzRenderer(self, **kwargs)
        return renderer.render(filename)

    def render_gif(
        self,
        filename: str = "scene.gif",
        *,
        fps: int = 6,
        mode: str = "build_up",
        dwell: float = 1.5,
    ) -> None:
        """Render an animated GIF of the scene build-up.

        Requires ``pip install optodraw[gif]`` (pillow + cairosvg).

        Parameters
        ----------
        filename : str
            Output GIF path.
        fps : int
            Playback frame rate (default 6).
        mode : str
            ``"build_up"`` – components appear one by one; beams draw in full.
            ``"beam_trace"`` – same build-up but beams grow step by step.
        dwell : float
            Extra hold time (seconds) on the final frame.
        """
        from optodraw.renderers.gif_renderer import GifRenderer

        GifRenderer(self).render(filename, fps=fps, mode=mode, dwell=dwell)

    def timeline(self) -> "AnimationTimeline":
        """Return an :class:`~optodraw.animation.AnimationTimeline` for this scene.

        Use the timeline to define per-step ordering and captions, then call
        :meth:`~optodraw.animation.AnimationTimeline.render_gif` or
        :meth:`~optodraw.animation.AnimationTimeline.render_video`.
        """
        from optodraw.animation import AnimationTimeline

        return AnimationTimeline(self)

    def render_video(self, filename: str = "scene.mp4", **kwargs) -> None:
        """Render an animated video using the Manim backend.

        Requires ``pip install optodraw[manim]``.
        """
        from optodraw.renderers.manim_renderer import ManimRenderer

        renderer = ManimRenderer(self, **kwargs)
        renderer.render(filename)

    def render_notebook_widget(self, **kwargs):
        """Return an inline notebook widget/HTML viewer for the 3D scene."""
        from optodraw.notebook import threejs_widget

        return threejs_widget(self, **kwargs)

    def _warn_physics_contract(self, optics, trace_mode: str) -> None:
        from optodraw.registry import component_registry

        registry = component_registry()
        warned_types: set[str] = set()
        for optic in optics:
            component_type = getattr(optic, "component_type", type(optic).__name__)
            if component_type in warned_types:
                continue
            warned_types.add(component_type)
            spec = registry.get(component_type)
            if spec is None:
                continue

            warning_key = (component_type, trace_mode)
            if warning_key in _PHYSICS_WARNINGS_EMITTED:
                continue

            if spec.visual_only:
                warnings.warn(
                    f"{component_type} is visual-only; {trace_mode} tracing may be misleading.",
                    stacklevel=3,
                )
                _PHYSICS_WARNINGS_EMITTED.add(warning_key)
                continue

            if trace_mode == "paraxial" and "paraxial" not in spec.physics_modes:
                warnings.warn(
                    f"{component_type} does not declare paraxial physics support; "
                    "paraxial tracing may be approximate.",
                    stacklevel=3,
                )
                _PHYSICS_WARNINGS_EMITTED.add(warning_key)
            elif trace_mode == "ray" and "ray" not in spec.physics_modes:
                warnings.warn(
                    f"{component_type} does not declare ray physics support; "
                    "ray tracing may be approximate.",
                    stacklevel=3,
                )
                _PHYSICS_WARNINGS_EMITTED.add(warning_key)
            elif trace_mode == "polarization" and "polarization" not in spec.physics_modes:
                warnings.warn(
                    f"{component_type} does not declare polarization physics support; "
                    "Jones tracing may be approximate.",
                    stacklevel=3,
                )
                _PHYSICS_WARNINGS_EMITTED.add(warning_key)

    def _resolve_wavelength_kwargs(self, kwargs: dict, *, api_name: str) -> float | None:
        """Merge the ``wavelength`` / ``wavelength_nm`` aliases.

        Both names are accepted for history's sake; they are the same quantity
        in nm. Passing both with different values is almost certainly a mistake
        (one of them silently losing was the old behavior), so it raises.
        """

        wavelength = kwargs.get("wavelength")
        wavelength_nm = kwargs.get("wavelength_nm")
        if wavelength is not None and wavelength_nm is not None:
            if float(wavelength) != float(wavelength_nm):
                raise ValueError(
                    f"{api_name}() got conflicting 'wavelength' ({wavelength}) and "
                    f"'wavelength_nm' ({wavelength_nm}); they are aliases for the "
                    "same quantity in nm — pass one."
                )
        return wavelength_nm if wavelength_nm is not None else wavelength

    def trace_ray(self, start, direction_deg: float, optics, **kwargs):
        """Trace a beam through ordered optics and add the resulting beam."""
        self._warn_physics_contract(optics, "ray")
        from optodraw.core.raytrace import trace_ray

        unknown = set(kwargs) - {
            "exit_length",
            "beamsplitter_mode",
            "wavelength_nm",
            "wavelength",
            "diffraction_order",
            "width",
            "label",
        }
        if unknown:
            warnings.warn(
                f"trace_ray() ignored unknown argument(s): {', '.join(sorted(unknown))}",
                stacklevel=2,
            )

        resolved_nm = self._resolve_wavelength_kwargs(kwargs, api_name="trace_ray")

        trace_kwargs = {}
        for key in ("exit_length", "beamsplitter_mode", "diffraction_order"):
            if key in kwargs:
                trace_kwargs[key] = kwargs[key]
        if resolved_nm is not None:
            trace_kwargs["wavelength_nm"] = resolved_nm

        result = trace_ray(start, direction_deg, optics, **trace_kwargs)
        beam = result.as_beam(
            wavelength=resolved_nm if resolved_nm is not None else 633.0,
            width=kwargs.get("width", 0.8),
            label=kwargs.get("label", ""),
        )
        self.add(beam)
        return beam

    def trace_paraxial_beam(self, start, direction_deg: float, optics, **kwargs):
        """Trace Gaussian beam metadata through ordered paraxial optics."""
        self._warn_physics_contract(optics, "paraxial")
        from optodraw.core.physics import trace_paraxial_beam

        unknown = set(kwargs) - {
            "input_beam",
            "exit_length",
            "beamsplitter_mode",
            "wavelength_nm",
            "wavelength",
            "add_beam",
            "width",
            "label",
        }
        if unknown:
            warnings.warn(
                f"trace_paraxial_beam() ignored unknown argument(s): {', '.join(sorted(unknown))}",
                stacklevel=2,
            )

        resolved_nm = self._resolve_wavelength_kwargs(kwargs, api_name="trace_paraxial_beam")

        trace_kwargs = {}
        for key in ("input_beam", "exit_length", "beamsplitter_mode"):
            if key in kwargs:
                trace_kwargs[key] = kwargs[key]

        result = trace_paraxial_beam(start, direction_deg, optics, **trace_kwargs)
        if kwargs.get("add_beam", True):
            self.add(
                result.as_beam(
                    wavelength_nm=resolved_nm if resolved_nm is not None else 633.0,
                    width=kwargs.get("width"),
                    label=kwargs.get("label", ""),
                )
            )
        return result

    def trace_guided_path(self, components_or_route=None, **kwargs):
        """Trace guided-mode path length over on-chip waveguides and routes."""

        from optodraw.core.guided import trace_guided_path

        if components_or_route is None:
            guided_types = {
                "Waveguide",
                "Route",
                "WaveguideRoute",
                "FiberRoute",
                "VerticalGratingCoupler",
                "FocusedApodizedGratingCoupler",
                "EdgeCoupler",
                "OnChipPhotodetector",
            }
            components_or_route = [
                node
                for node in self.walk()
                if getattr(node, "component_type", "") in guided_types
            ]
        return trace_guided_path(components_or_route, **kwargs)

    def trace_interferometer(self, component, **kwargs):
        """Trace a lightweight MZI/MZM interferometer stub for ``component``."""

        from optodraw.core.interferometer import trace_mzi_power, trace_mzm_transfer
        from optodraw.registry import component_registry

        component_type = getattr(component, "component_type", component.__class__.__name__)
        spec = component_registry().get(component_type)

        if spec is not None and "guided" not in spec.physics_modes:
            warnings.warn(
                f"{component_type} does not declare guided physics support; "
                "interferometer tracing uses diagram fallback stubs.",
                stacklevel=2,
            )

        if not hasattr(component, "physics_metadata"):
            warnings.warn(
                f"{component_type} lacks physics_metadata(); using diagram fallback stubs.",
                stacklevel=2,
            )

        if component_type == "MZI":
            return trace_mzi_power(component, **kwargs)
        if component_type == "MZM":
            return trace_mzm_transfer(component, **kwargs)
        raise ValueError("component must be an MZI or MZM instance")

    def trace_resonator(self, component, **kwargs):
        """Trace a Lorentzian microring / racetrack resonance stub for ``component``."""

        from optodraw.core.resonator import is_resonator_component, trace_ring_resonance
        from optodraw.registry import component_registry

        component_type = getattr(component, "component_type", component.__class__.__name__)
        if not is_resonator_component(component):
            raise ValueError(
                "component must be MicroringResonator, PNMicroringModulator, "
                "RacetrackResonator, or RacetrackModulator"
            )

        spec = component_registry().get(component_type)
        if spec is not None and "modulation" not in spec.physics_modes:
            warnings.warn(
                f"{component_type} does not declare modulation physics support; "
                "resonator tracing uses diagram fallback stubs.",
                stacklevel=2,
            )

        if not hasattr(component, "physics_metadata"):
            warnings.warn(
                f"{component_type} lacks physics_metadata(); using diagram fallback stubs.",
                stacklevel=2,
            )

        return trace_ring_resonance(component, **kwargs)

    def trace_readout_chain(self, components=None, **kwargs):
        """Trace a lightweight detector readout stub over scene components."""

        from optodraw.core.interferometer import trace_readout_chain

        if components is None:
            tracked_types = {
                "OnChipPhotodetector",
                "TIA",
                "ADC",
                "Route",
                "WaveguideRoute",
                "FiberRoute",
            }
            components = [
                node
                for node in self.walk()
                if getattr(node, "component_type", "") in tracked_types
            ]
        return trace_readout_chain(components, **kwargs)

    def trace_polarization(self, components, *, jones_in=None, wavelength_nm: float = 633.0, **kwargs):
        """Trace Jones-vector polarization through ordered free-space components."""

        self._warn_physics_contract(components, "polarization")
        from optodraw.core.polarization import JonesVector, trace_jones_through

        if jones_in is None:
            state_in = None
        elif isinstance(jones_in, JonesVector):
            state_in = jones_in
        else:
            ex, ey = jones_in
            state_in = JonesVector(ex, ey)

        return trace_jones_through(
            components,
            state_in,
            wavelength_nm=wavelength_nm,
            unpolarized=bool(kwargs.get("unpolarized", False)),
        )

    def trace_stokes_polarization(
        self,
        components,
        *,
        stokes_in=None,
        wavelength_nm: float = 633.0,
        **kwargs,
    ):
        """Trace Mueller/Stokes polarization through ordered free-space components."""

        self._warn_physics_contract(components, "polarization")
        from optodraw.core.polarization import StokesVector, trace_stokes_through

        if stokes_in is None:
            state_in = None
        elif isinstance(stokes_in, StokesVector):
            state_in = stokes_in
        else:
            state_in = StokesVector(*stokes_in)

        return trace_stokes_through(
            components,
            state_in,
            wavelength_nm=wavelength_nm,
            unpolarized=bool(kwargs.get("unpolarized", False)),
        )

    def animate_polarization(self, components, **kwargs):
        """Convenience wrapper for :func:`~optodraw.animation.animate_polarization`."""

        from optodraw.animation import animate_polarization

        return animate_polarization(self, components, **kwargs)

    def animate_interference(self, arm1, arm2, combiner, **kwargs):
        """Convenience wrapper for :func:`~optodraw.animation_recipes.animate_interference`."""

        from optodraw.animation_recipes import animate_interference

        return animate_interference(self, arm1, arm2, combiner, **kwargs)

    def animate_resonance_scan(self, resonator, **kwargs):
        """Convenience wrapper for :func:`~optodraw.animation_recipes.animate_resonance_scan`."""

        from optodraw.animation_recipes import animate_resonance_scan

        return animate_resonance_scan(self, resonator, **kwargs)

    def animate_focus(self, lens, **kwargs):
        """Convenience wrapper for :func:`~optodraw.animation_recipes.animate_focus`."""

        from optodraw.animation_recipes import animate_focus

        return animate_focus(self, lens, **kwargs)

    def animate_modulation(self, mzm, **kwargs):
        """Convenience wrapper for :func:`~optodraw.animation_recipes.animate_modulation`."""

        from optodraw.animation_recipes import animate_modulation

        return animate_modulation(self, mzm, **kwargs)

    def animate_layer_stack(self, gds_layout_or_scene=None, **kwargs):
        """Convenience wrapper for :func:`~optodraw.animation_recipes.animate_layer_stack`."""

        from optodraw.animation_recipes import animate_layer_stack

        target = self if gds_layout_or_scene is None else gds_layout_or_scene
        return animate_layer_stack(target, **kwargs)

    def animate_dispersion(self, dispersive_element, **kwargs):
        """Convenience wrapper for :func:`~optodraw.animation_recipes.animate_dispersion`."""

        from optodraw.animation_recipes import animate_dispersion

        return animate_dispersion(self, dispersive_element, **kwargs)

    def compile_physics_animation(self, **kwargs):
        """Compile physics trace hints into an :class:`~optodraw.animation.AnimationTimeline`."""

        from optodraw.core.physics_compiler import compile_physics_animation

        return compile_physics_animation(self, **kwargs)

    def validate_electrical(self, *, components=None) -> list[str]:
        """Return electrical validation warnings for routed scene components."""

        from optodraw.core.electrical import validate_electrical_chain

        if components is None:
            components = list(self.walk())
        return validate_electrical_chain(components)

    def validate_physics(self, mode: str = "mixed", *, components=None, **kwargs) -> list[str]:
        """Return validation warnings for a physics mode over scene components.

        Supported modes:

        - ``paraxial``: components lacking declared paraxial support
        - ``ray``: visual-only or ray-unsupported components
        - ``coupling``: grating coupler angle vs pitch/wavelength stub
        - ``polarization``: components lacking declared polarization support
        - ``mixed`` (default): combine paraxial and ray warnings
        """

        from optodraw.core.guided import validate_coupler_transition
        from optodraw.core.physics import validate_paraxial_chain, validate_ray_chain
        from optodraw.core.polarization import validate_polarization_chain

        if components is None:
            components = self._parts(None)

        normalized = mode.strip().lower()
        if normalized == "paraxial":
            return validate_paraxial_chain(components)
        if normalized == "ray":
            return validate_ray_chain(components)
        if normalized == "coupling":
            warnings: list[str] = []
            wavelength_nm = float(kwargs.get("wavelength_nm", 1550.0))
            coupler_types = {"VerticalGratingCoupler", "FocusedApodizedGratingCoupler"}
            for component in components:
                component_type = getattr(component, "component_type", component.__class__.__name__)
                if component_type in coupler_types:
                    warnings.extend(
                        validate_coupler_transition(component, wavelength_nm=wavelength_nm)
                    )
            return warnings
        if normalized == "polarization":
            return validate_polarization_chain(components)
        if normalized in {"mixed", "all"}:
            warnings = validate_paraxial_chain(components)
            warnings.extend(validate_ray_chain(components))
            return warnings
        raise ValueError(
            "mode must be one of: 'paraxial', 'ray', 'coupling', 'polarization', 'mixed'"
        )

    # -- serialization (for MCP / AI tools) --------------------------------
    def to_spec(self) -> dict[str, Any]:
        from optodraw.schema import scene_to_spec

        return scene_to_spec(self)

    def save(self, path: str | Path) -> None:
        from optodraw.schema import save_scene

        save_scene(self, path)

    def export_figure(self, path: str | Path, *, width_mm: float, **kwargs) -> dict[str, Path]:
        """Write SVG, PDF and PNG at their size on the page: see :func:`optodraw.publication.export_figure`."""

        from optodraw.publication import export_figure

        return export_figure(self, path, width_mm=width_mm, **kwargs)

    def export_paper_figures(self, output_dir: str | Path, **kwargs) -> dict[str, Path]:
        """Export SVG, HTML, and JSON publication figures to ``output_dir``."""

        from optodraw.publication import export_paper_figures

        return export_paper_figures(self, output_dir, **kwargs)

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> Scene:
        from optodraw.schema import scene_from_spec

        return scene_from_spec(spec)

    def apply_authoring_patch(self, patch: dict[str, Any]) -> Scene:
        """Apply an interactive authoring patch to this scene in place."""

        from optodraw.schema import apply_authoring_patch

        return apply_authoring_patch(self, patch)

    @classmethod
    def load(cls, path: str | Path) -> Scene:
        from optodraw.schema import load_scene

        return load_scene(path)

    def to_dict(self) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`to_spec`."""
        return self.to_spec()

    def __repr__(self) -> str:
        n = sum(1 for _ in self.walk())
        return f"Scene('{self.title}', {n} components)"

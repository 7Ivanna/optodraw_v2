"""Base Component class — a node in the scene graph."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from optodraw.core.transform import Transform, Vec3

if TYPE_CHECKING:
    from optodraw.core.ports import Port


# Things that CONNECT parts rather than being parts. Layout, checks and exports
# all want to skip them, and each used to spell the list out again. Every copy
# in Scene named "Route" but not the three subclasses the router actually
# builds, so a waveguide link counted as a component to lay out.
LINK_TYPES = frozenset(
    {"Beam", "FocusingBeam", "Route", "WaveguideRoute", "FiberRoute", "MetalRoute"}
)

# Marks a figure adds round its parts: text, and the lines that go with it.
ANNOTATION_TYPES = frozenset({"Note", "Callout", "Bracket", "DashedLink", "SectionMark", "Region", "Glyph", "Inset",
                              "ZoomLink", "CutLink"})

# Links plus scenery: what "the parts in this scene" excludes.
NON_PART_TYPES = LINK_TYPES | ANNOTATION_TYPES | {"Grid", "Group"}


@dataclass
class Component:
    """Base class for every optical element.

    Parameters
    ----------
    center : tuple
        (x, y) or (x, y, z) position.
    angle : float
        Rotation in degrees (about Z for 2D setups).
    label : str
        Optional text label shown in renders.
    color : str
        CSS/hex color for this component.
    opacity : float
        0–1 opacity.
    """

    component_type: ClassVar[str] = "Component"
    label: str = ""
    color: str = "#888888"
    opacity: float = 1.0
    # 3D base mount the renderer draws under a beam-plane optic: "post" or "stage".
    # Editable per-component; set via component_from_spec / _set_common_free_space_fields.
    base_mount: str = "post"
    # Absolute device-bottom height above 0 for the 3D post (None = auto from beam plane
    # and aperture). Lets you pick a real TR post from the drawer so every optic
    # can share one beam height even with mixed apertures.
    mount_height: float | None = None  # type: ignore[assignment]
    # The height of the beam at this part above the table, in 3D (None = follow the beam that reaches it:
    # the scene's beam height, or the exit height of a periscope before it). A part given one sets the
    # height of its whole run between periscopes, and the periscopes follow (core/beam_heights.py).
    beam_height: float | None = None  # type: ignore[assignment]
    # Where the 2D and TikZ drawings put the part's name: "top" (default), "bottom", "left" or "right".
    label_side: str = "top"
    # Per-component 3D animation choices (e.g. {"ring_coupling": "critical",
    # "junction": "pn"}). Empty/None = physics defaults. Post-construction attribute
    # like base_mount; the timeline compiler reads it.
    anim_params: dict | None = None

    transform: Transform = field(default_factory=Transform)

    # Scene graph linkage (set by Scene.add / Group.add)
    _parent: Group | None = field(default=None, repr=False)
    _id: str = field(default="", repr=False)

    def anim_behaviors(self) -> list[dict]:
        """The device's behavioural animation controls (the per-device protocol).

        Each entry: {"key", "label", "options": [[value, label], ...]} — the key is
        stored in ``anim_params`` ("auto" removes it), the timeline compiler reads
        it, and the editor renders these controls generically. Override per device
        to declare what can be switched (resonance, coupling, bias, drive...)."""

        return []

    def optical_interfaces(self):
        """Free-space surface protocol for physical-mode ray tracing.

        Override to return a list of ``optodraw.core.raytrace.OpticalInterface``
        (typed line segments in the local drawing frame: lens / mirror /
        beam_splitter / dichroic / absorber). ``None`` (the default) lets the
        tracer synthesize a standard single-surface model from the component
        type; ``[]`` opts out entirely (rays pass by untouched)."""

        return None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Every subclass gets a component_type name for serialization
        if "component_type" not in cls.__dict__:
            cls.component_type = cls.__name__
        # Most parts write their own __init__ and set only the fields they know; the side of the label is
        # every part's, so it is applied here and no constructor can drop it.
        init = cls.__dict__.get("__init__")
        if init is not None and not getattr(init, "_keeps_label_side", False):
            def __init__(self, *args, _init=init, **kw):
                side = kw.pop("label_side", None)
                _init(self, *args, **kw)
                if side is not None:
                    self.label_side = side
            __init__.__wrapped__ = init
            __init__.__doc__ = init.__doc__
            __init__._keeps_label_side = True
            cls.__init__ = __init__

    # -- convenience init helpers ------------------------------------------
    @classmethod
    def _parse_center(cls, center) -> Vec3:
        if isinstance(center, Vec3):
            return center
        if len(center) == 2:
            return Vec3(center[0], center[1], 0)
        return Vec3(*center[:3])

    # -- world transform ---------------------------------------------------
    @property
    def world_transform(self) -> Transform:
        """Compute the global transform by walking up the scene graph."""
        if self._parent is None:
            return self.transform
        return self._parent.world_transform.compose(self.transform)

    @property
    def world_position(self) -> Vec3:
        return self.world_transform.position

    def beam_anchor_point(self) -> Vec3:
        """Return the default world-space anchor for free-space beams."""

        return self.world_position

    def drawn_box(self) -> tuple[float, float, float, float]:
        """The world box ``(x0, y0, x1, y1)``, y up, that the part's 2D drawing covers: its art (or its shapes) and
        its ports, turned with the part. The figure checks, a zoom region and a :class:`Region` read this box."""

        import math

        from optodraw.layout import estimate_component_bounds

        x0, y0, x1, y1 = estimate_component_bounds(self)
        turn = math.radians(float(self.world_transform.rotation_deg.z))
        c, s = math.cos(turn), math.sin(turn)
        p = self.world_position
        corners = [(p.x + c * x - s * y, p.y + s * x + c * y) for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
        return (float(min(x for x, _ in corners)), float(min(y for _, y in corners)),
                float(max(x for x, _ in corners)), float(max(y for _, y in corners)))

    def anchors(self) -> dict[str, tuple[float, float]]:
        """The named places on the part, in the world, y up: ``"center"`` and the places the part names in
        ``_anchor_points()`` (a ring's centre, a coupler's gap, a pad's centre). A mark takes one as its target:
        ``Callout("gap", center=..., target=ring.anchor("gap"))``. The places are read now: ask after the part is
        in place."""

        local = {"center": (0.0, 0.0), **self._anchor_points()}
        transform = self.world_transform
        out = {}
        for name, (x, y) in local.items():
            point = transform.apply_to_point(Vec3(float(x), float(y), 0.0))
            out[name] = (float(point.x), float(point.y))
        return out

    def anchor(self, name: str) -> tuple[float, float]:
        """One named place on the part, in the world: see :meth:`anchors`."""

        places = self.anchors()
        if name not in places:
            raise KeyError(f"{self.component_type} has no anchor {name!r}: it has {', '.join(sorted(places))}")
        return places[name]

    def _anchor_points(self) -> dict[str, tuple[float, float]]:
        """The part's own named places in its local frame, y up. A part that a figure points into overrides this."""

        return {}

    # -- ports -------------------------------------------------------------
    def ports(self) -> dict[str, "Port"]:
        """Return local named ports for port-aware routing.

        The default gives an inline free-space optic ``in``/``out`` ports on the
        optical axis, sized from its aperture, so any transmissive optic is
        routable without bespoke code. Sources, detectors, splitters, mirrors,
        and on-chip/electrical components override this with their own ports.
        Components with no aperture-like dimension return no ports.
        """
        aperture = (
            getattr(self, "aperture", None)
            or getattr(self, "box_size", None)
            or getattr(self, "outer_diameter", None)
            or getattr(self, "active_height", None)
            or getattr(self, "size", None)
            or getattr(self, "cladding_diameter", None)
        )
        if not aperture:
            return {}
        from optodraw.core.ports import Port

        half = max(
            (
                getattr(self, "thickness", None)
                or getattr(self, "length", None)
                or getattr(self, "center_thickness", None)
                or aperture * 0.18
            )
            * 0.5,
            aperture * 0.06,
        )
        return {
            "in": Port("in", Vec3(-half, 0.0, 0.0), orientation_deg=180.0, width=float(aperture), kind="free_space"),
            "out": Port("out", Vec3(half, 0.0, 0.0), orientation_deg=0.0, width=float(aperture), kind="free_space"),
        }

    def get_port(self, name: str) -> "Port":
        ports = self.ports()
        if name not in ports:
            raise KeyError(f"Component {self.component_type} has no port '{name}'")
        return ports[name]

    def world_ports(self) -> dict[str, "Port"]:
        return {name: port.transformed(self.world_transform) for name, port in self.ports().items()}

    def world_port(self, name: str) -> "Port":
        ports = self.world_ports()
        if name not in ports:
            raise KeyError(f"Component {self.component_type} has no world port '{name}'")
        return ports[name]

    # -- serialization (for MCP / AI) --------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (JSON-friendly)."""
        data = {
            "type": self.component_type,
            "label": self.label,
            "color": self.color,
            "opacity": self.opacity,
            "position": self.transform.position.as_tuple(),
            "rotation": self.transform.rotation_deg.as_tuple(),
        }
        # 3D base mount choice (post/stage) — only persist when set away from default
        base_mount = getattr(self, "base_mount", "post")
        if base_mount and base_mount != "post":
            data["base_mount"] = base_mount
        mount_height = getattr(self, "mount_height", None)
        if mount_height is not None:
            data["mount_height"] = float(mount_height)
        beam_height = getattr(self, "beam_height", None)
        if beam_height is not None and not getattr(self, "_scene_beam", False):
            data["beam_height"] = float(beam_height)
        anim_params = getattr(self, "anim_params", None)
        if anim_params:
            data["anim_params"] = dict(anim_params)
        ports = self.world_ports()
        if ports:
            data["ports"] = {name: port.to_dict() for name, port in ports.items()}
        return data

    # -- geometry data for renderers (override in subclasses) ---------------
    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        """The 1D symbol of this part: ``(pic name, parameters)``.

        None selects the class's default row in ``optodraw/symbols/variants.toml``.
        Override this when a constructor argument changes the symbol.
        """
        return None

    def geometry_2d(self) -> dict[str, Any]:
        """Return 2D drawing primitives (paths, rects, etc.)."""
        return {}

    def geometry_3d(self) -> dict[str, Any]:
        """Return 3D mesh data (vertices, faces, or parametric shape)."""
        return {}

    # -- convenience preview helpers --------------------------------------
    def set_material_preset(self, name: str):
        self.material_preset = name
        return self

    def preview_scene(self, *, padding: float = 30.0, width: float | None = None, height: float | None = None, platform: str | None = None):
        import math

        from optodraw.core.scene import Scene
        from optodraw.layout import estimate_component_bounds
        from optodraw.registry import component_registry

        component = copy.deepcopy(self)
        rotation = component.transform.rotation_deg
        component._parent = None
        component.transform = Transform(position=Vec3(0.0, 0.0, 0.0), rotation_deg=rotation)

        left, bottom, right, top = estimate_component_bounds(component)
        theta = math.radians(float(rotation.z))
        cosine, sine = math.cos(theta), math.sin(theta)
        corners = ((left, bottom), (left, top), (right, bottom), (right, top))
        xs = [x * cosine - y * sine for x, y in corners]
        ys = [x * sine + y * cosine for x, y in corners]
        size_x = 2.0 * max(abs(value) for value in xs)
        size_y = 2.0 * max(abs(value) for value in ys)
        spec = component_registry().get(component.component_type)
        mixed_chip_types = {"SignalArrow", "RFDriver", "Microcontroller", "PCB"}
        inferred_platform = "on_chip" if (spec and spec.platform == "on_chip") or component.component_type in mixed_chip_types else "free_space"
        scene = Scene(
            title=component.label or component.component_type,
            width=width or (size_x + 2 * padding),
            height=height or (size_y + 2 * padding),
            platform=platform or inferred_platform,
        )
        scene.add(component)
        return scene

    def render_svg(
        self,
        filename: str | None = None,
        *,
        padding: float = 30.0,
        width: float | None = None,
        height: float | None = None,
        platform: str | None = None,
        **renderer_kwargs,
    ):
        return self.preview_scene(padding=padding, width=width, height=height, platform=platform).render_svg(filename, **renderer_kwargs)

    def render_threejs(
        self,
        filename: str | None = None,
        *,
        padding: float = 30.0,
        width: float | None = None,
        height: float | None = None,
        platform: str | None = None,
        **renderer_kwargs,
    ):
        return self.preview_scene(padding=padding, width=width, height=height, platform=platform).render_threejs(filename, **renderer_kwargs)

    def render_tikz(
        self,
        filename: str | None = None,
        *,
        padding: float = 30.0,
        width: float | None = None,
        height: float | None = None,
        platform: str | None = None,
        **renderer_kwargs,
    ):
        return self.preview_scene(padding=padding, width=width, height=height, platform=platform).render_tikz(filename, **renderer_kwargs)

    def render_notebook_widget(
        self,
        *,
        padding: float = 30.0,
        width: float | None = None,
        height: float | None = None,
        platform: str | None = None,
    ):
        return self.preview_scene(padding=padding, width=width, height=height, platform=platform).render_notebook_widget()


@dataclass
class Group(Component):
    """A group of components sharing a common transform frame."""

    children: list[Component] = field(default_factory=list)

    def add(self, child: Component) -> Component:
        child._parent = self
        self.children.append(child)
        return child

    def __iter__(self):
        return iter(self.children)

    def walk(self):
        """Yield all descendants depth-first."""
        for child in self.children:
            yield child
            if isinstance(child, Group):
                yield from child.walk()

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["children"] = [c.to_dict() for c in self.children]
        return d

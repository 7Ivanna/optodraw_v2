"""Base chip component class and PDK defaults."""

from __future__ import annotations

import inspect
import math
from copy import copy
from functools import lru_cache
from typing import Any

from optodraw.components.onchip.geometry import _chip_extruded_polygon, _cut_footprints, _plan
from optodraw.components.onchip.layer_stack import StackCore
from optodraw.components.onchip.schematic_tables import SCHEMATIC_TABLES
from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.schematic_geometry import (
    PhysicalSpec,
    SchematicDims,
    resolve_schematic_dims,
    schematic_material_preset,
)
from optodraw.core.transform import Transform, Vec3

# Silicon in 2D and 3D: the AWGR blue, one colour for every on-chip part.
SILICON = "#2b6cb0"
SILICON_EDGE = "#1a4373"


def _style_key(visual_style: str) -> str:
    """Normalize visual style aliases to ``symbolic``, ``publication``, ``presentation``, or ``physical``."""

    style = (visual_style or "publication").strip().lower().replace("-", "_")
    aliases = {
        "1d": "symbolic",
        "line": "symbolic",
        "black_line": "symbolic",
        "paper": "publication",
        "schematic": "publication",
    }
    style = aliases.get(style, style)
    if style not in {"symbolic", "publication", "presentation", "physical"}:
        raise ValueError("visual_style must be one of: symbolic, publication, presentation, physical")
    return style


def _numeric_signature_defaults(factory: Any, names: list[str]) -> dict[str, float | int | bool]:
    values: dict[str, float | int | bool] = {}
    try:
        params = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return values

    for name in names:
        param = params.get(name)
        if param is None:
            continue
        default = param.default
        if isinstance(default, (int, float, bool)):
            values[name] = default
    return values


@lru_cache(maxsize=1)
def _generic_pdk_defaults() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "strip": {"width": 0.5, "radius": 10.0},
        "grating_coupler": {
            "footprint_length": 40.195,
            "footprint_width": 26.174,
            "taper_length": 16.6,
            "taper_angle": 40.0,
            "line_width": 0.343,
            "periods": 30,
            "fiber_port_width": 10.0,
        },
        "mmi": {
            "footprint_length": 25.5,
            "footprint_width": 2.5,
            "length_taper": 10.0,
            "length_mmi": 5.5,
            "width_mmi": 2.5,
            "gap_mmi": 0.25,
            "width_taper": 1.0,
        },
        "ring": {
            "radius": 10.0,
            "gap": 0.2,
            "length_x": 4.0,
            "length_y": 0.6,
        },
        "heater": {
            "length": 320.0,
            "electrode_width": 11.0,
        },
        "detector": {
            "absorber_length": 40.0,
            "taper_length": 20.0,
            "pad_width": 10.0,
            "pad_length": 40.0,
            "footprint_width": 25.0,
            "taper_width": 0.8,
        },
    }

    try:
        import gdsfactory as gf
    except ImportError:
        defaults["grating_coupler"]["pitch"] = (
            defaults["grating_coupler"]["footprint_length"] - defaults["grating_coupler"]["taper_length"]
        ) / defaults["grating_coupler"]["periods"]
        return defaults

    try:
        strip = gf.get_cross_section("strip")
        defaults["strip"]["width"] = float(strip.width)
        strip_radius = getattr(strip, "radius", None)
        if strip_radius is not None:
            defaults["strip"]["radius"] = float(strip_radius)
    except Exception:
        pass

    component_specs = {
        "grating_coupler": (
            "grating_coupler_elliptical_te",
            ["taper_length", "taper_angle", "grating_line_width", "n_periods"],
        ),
        "mmi": ("mmi1x2", ["length_taper", "length_mmi", "width_mmi", "gap_mmi", "width_taper"]),
        "ring": ("ring_single", ["gap", "radius", "length_x", "length_y"]),
        "heater": ("straight_heater_metal", ["length"]),
        "detector": (
            "ge_detector_straight_si_contacts",
            ["length", "taper_length", "via_stack_width", "taper_width"],
        ),
    }

    for key, (name, signature_names) in component_specs.items():
        factory = getattr(gf.components, name, None)
        if factory is None:
            continue
        values = _numeric_signature_defaults(factory, signature_names)
        if key == "grating_coupler":
            if "grating_line_width" in values:
                defaults[key]["line_width"] = float(values["grating_line_width"])
            if "n_periods" in values:
                defaults[key]["periods"] = int(values["n_periods"])
            if "taper_length" in values:
                defaults[key]["taper_length"] = float(values["taper_length"])
            if "taper_angle" in values:
                defaults[key]["taper_angle"] = float(values["taper_angle"])
        elif key == "detector":
            if "length" in values:
                defaults[key]["absorber_length"] = float(values["length"])
            if "taper_length" in values:
                defaults[key]["taper_length"] = float(values["taper_length"])
            if "via_stack_width" in values:
                defaults[key]["pad_width"] = float(values["via_stack_width"])
            if "taper_width" in values:
                defaults[key]["taper_width"] = float(values["taper_width"])
        elif key == "heater":
            if "length" in values:
                defaults[key]["length"] = float(values["length"])
        else:
            for field_name, value in values.items():
                defaults[key][field_name] = float(value) if isinstance(value, (float, int)) else value

        try:
            component = factory()
        except Exception:
            continue

        try:
            defaults[key]["footprint_length"] = float(component.dxsize)
            defaults[key]["footprint_width"] = float(component.dysize)
        except Exception:
            continue

        if key == "grating_coupler":
            try:
                for port in component.ports:
                    if port.name != "o1":
                        defaults[key]["fiber_port_width"] = float(port.dwidth)
                        break
            except Exception:
                pass
        elif key == "heater":
            try:
                widths = [float(port.dwidth) for port in component.ports if str(port.port_type) == "electrical"]
                if widths:
                    defaults[key]["electrode_width"] = max(widths)
            except Exception:
                pass
        elif key == "detector":
            try:
                widths = [float(port.dwidth) for port in component.ports if str(port.port_type) == "electrical"]
                if widths:
                    defaults[key]["pad_length"] = max(widths)
            except Exception:
                pass

    defaults["grating_coupler"]["pitch"] = (
        defaults["grating_coupler"]["footprint_length"] - defaults["grating_coupler"]["taper_length"]
    ) / max(defaults["grating_coupler"]["periods"], 1)
    return defaults


# Draw units each side of a core that stands on a slab: the slab's width is a mask choice, which no stack gives.
_SLAB_MARGIN = 1.0


def _solid_leaves(node: dict[str, Any]):
    """The boxes and extruded polygons of a part's 3D tree. A part's groups carry no offset of their own."""

    if node.get("shape") == "group":
        for child in node.get("children", []):
            yield from _solid_leaves(child)
    elif node.get("shape") in ("box", "extruded_polygon"):
        yield node


def _restacked(node: dict[str, Any], bottom: float, height: float, color: str, preset: str) -> dict[str, Any]:
    """A copy of a box or an extruded polygon with the same plan, from ``bottom`` up ``height``, in another look."""

    solid = {**node, "height": height, "material": {**(node.get("material") or {}), "color": color, "preset": preset}}
    x, _, z = node.get("position") or [0.0, 0.0, 0.0]
    solid["position"] = [x, bottom + height / 2.0 if node["shape"] == "box" else bottom, z]
    return solid


class ChipComponent(Component):
    """Base class for integrated photonic components.

    **Two truths:** schematic ``geometry_2d`` / ``geometry_3d`` default to legible
    diagram dimensions; ``ports()``, routing, and GDS export stay physical µm.
    Pass ``render_physical=True`` to draw true PDK footprints.
    """

    chip_thickness: float = 0.22
    pdk: str = "generic"
    cross_section: str = "strip"
    flip_horizontal: bool = False
    flip_vertical: bool = False
    visual_style: str = "publication"
    visual_scale: float = 1.0
    render_physical: bool = False
    schematic_family: str = "waveguide"
    # Feature exaggeration (3D view aids; ports/routing stay physical). Mirrors
    # GDSModel.z_exaggeration: thin films/waveguides are invisible at 1.0.
    z_exaggeration: float = 1.0       # vertical (height/thickness + layer stack)
    width_exaggeration: float = 1.0   # lateral draw width (cross-axis)
    length_exaggeration: float = 1.0  # axial draw length (set <1 to compress, e.g. MZI)
    # Hard floor so waveguides/features never render sub-visibly thin (schematic only).
    _MIN_DRAW_WIDTH: float = 0.6

    def _init_chip(self, center=(0, 0), angle=0, **kwargs):
        orientation_alias = kwargs.pop("orientation_deg", None)
        if orientation_alias is not None:
            if angle not in (0, 0.0, None) and float(angle) != float(orientation_alias):
                raise ValueError("Pass either angle or orientation_deg, not both with different values")
            angle = float(orientation_alias)
        self.color = kwargs.get("color", SILICON)
        self.material_preset = kwargs.get("material_preset", "silicon")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "")
        self.chip_thickness = kwargs.get("chip_thickness", 0.22)
        self.pdk = kwargs.get("pdk", "generic")
        self.cross_section = kwargs.get("cross_section", "strip")
        self.flip_horizontal = bool(kwargs.get("flip_horizontal", False))
        self.flip_vertical = bool(kwargs.get("flip_vertical", False))
        self.visual_style = _style_key(kwargs.get("visual_style", "publication"))
        self.visual_scale = max(float(kwargs.get("visual_scale", 1.0)), 0.05)
        self.render_physical = bool(kwargs.get("render_physical", False))
        # A drawing copy is built physical in draw units, but keeps its source part's schematic stack.
        self._schematic_stack = bool(kwargs.get("schematic_stack", not self.render_physical))
        self.z_exaggeration = max(float(kwargs.get("z_exaggeration", 1.0)), 0.05)
        self.width_exaggeration = max(float(kwargs.get("width_exaggeration", 1.0)), 0.05)
        self.length_exaggeration = max(float(kwargs.get("length_exaggeration", 1.0)), 0.05)
        # A drawing copy has no parent in the scene: it carries its source part's foundry stack.
        self.foundry_heights = kwargs.get("foundry_heights")
        self.foundry_core = kwargs.get("foundry_core")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def _flip_local_point(self, point: Vec3) -> Vec3:
        return Vec3(
            -point.x if self.flip_horizontal else point.x,
            -point.y if self.flip_vertical else point.y,
            point.z,
        )

    def _flip_local_port(self, port: Port) -> Port:
        center = self._flip_local_point(port.center)
        normal = port.normal()
        flipped_normal = Vec3(
            -normal.x if self.flip_horizontal else normal.x,
            -normal.y if self.flip_vertical else normal.y,
            normal.z,
        ).normalized()
        orientation = math.degrees(math.atan2(flipped_normal.y, flipped_normal.x))
        return Port(
            name=port.name,
            center=center,
            orientation_deg=orientation,
            width=port.width,
            kind=port.kind,
            layer=port.layer,
        )

    def get_port(self, name: str) -> Port:
        ports = self.ports()
        if name not in ports:
            raise KeyError(f"Component {self.component_type} has no port '{name}'")
        return self._flip_local_port(ports[name])

    def world_ports(self) -> dict[str, Port]:
        return {name: self._flip_local_port(port).transformed(self.world_transform) for name, port in self.ports().items()}

    def drawing_world_ports(self) -> dict[str, Port]:
        """Port anchors at the ends of the geometry shown in the current view."""

        return self.world_ports()

    def physical_world_ports(self) -> dict[str, Port]:
        """Port anchors at physical dimensions, independent of schematic scale."""

        if self.render_physical:
            return self.world_ports()
        physical = copy(self)
        physical.render_physical = True
        return {
            name: physical._flip_local_port(port).transformed(self.world_transform)
            for name, port in physical.ports().items()
        }

    def world_port(self, name: str) -> Port:
        ports = self.world_ports()
        if name not in ports:
            raise KeyError(f"Component {self.component_type} has no world port '{name}'")
        return ports[name]

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        if self.flip_horizontal:
            data["flip_horizontal"] = True
        if self.flip_vertical:
            data["flip_vertical"] = True
        if self.render_physical:
            data["render_physical"] = True
        for knob in ("z_exaggeration", "width_exaggeration", "length_exaggeration"):
            value = getattr(self, knob, 1.0)
            if value != 1.0:
                data[knob] = value
        return data

    def physical_spec(self) -> PhysicalSpec:
        """Return true PDK/user dimensions (µm) for metadata and routing."""

        return PhysicalSpec(device_family=self.schematic_family, values={})

    def schematic_dims(self) -> SchematicDims:
        """Resolved legible draw dimensions for this device family.

        ``_dim_overrides`` is how a component says "the caller asked for this
        one, do not substitute the family default". Without it a table entry
        wins over every constructor argument, which reads as the drawing
        ignoring what it was told."""

        return resolve_schematic_dims(
            self.schematic_family,
            self.physical_spec(),
            visual_scale=self.visual_scale,
            overrides=getattr(self, "_dim_overrides", None) or None,
        )

    def _draw(self, key: str, default: float | None = None) -> float:
        """Dimension for 2D/3D art — schematic unless ``render_physical``.

        In schematic mode the resolved value is exaggerated: ``*length*`` keys by
        ``length_exaggeration`` (set <1 to compress) and ``*width*`` keys by
        ``width_exaggeration`` (with a hard minimum so features stay visible).
        """

        if self.render_physical:
            if hasattr(self, key):
                return float(getattr(self, key))
            if default is not None:
                return float(default)
        dims = self.schematic_dims()
        value = dims.get(key)
        if value is None:
            if hasattr(self, key):
                value = float(getattr(self, key))
            elif default is not None:
                value = float(default)
            else:
                raise KeyError(f"No draw dimension '{key}' for {self.component_type}")
        else:
            value = float(value)
        return self._exaggerate_dim(key, value)

    def _exaggerate_dim(self, key: str, value: float) -> float:
        """Apply lateral/axial exaggeration + a min-width floor (schematic only)."""

        if self.render_physical:
            return value
        lowered = key.lower()
        if "length" in lowered:
            value = value * self.length_exaggeration
        elif "width" in lowered:
            value = max(value * self.width_exaggeration, self._MIN_DRAW_WIDTH)
        return value

    def _base_thickness(self) -> float:
        """Un-exaggerated core thickness (visual_scale-scaled in schematic mode)."""

        foundry = self._foundry_heights()
        core = float(foundry.get("chip_thickness", self.chip_thickness)) if foundry else float(self.chip_thickness)
        if self.render_physical:
            # a drawing copy is already in draw units: its chip_thickness is its source's drawn core
            return float(self.chip_thickness) if self._schematic_layer_stack() else core
        films = self._foundry_core()
        if films is not None and films.width:
            # one scale across and up: the stack's guide is drawn as wide as every part draws its guide
            return float(SCHEMATIC_TABLES["_shared"]["waveguide_width"]) * self.visual_scale * core / films.width
        return float(self.schematic_dims().thickness) * core / float(self.chip_thickness)

    def _draw_thickness(self) -> float:
        # z_exaggeration lifts the otherwise-invisible thin film into view (2D unaffected).
        return self._base_thickness() * self.z_exaggeration

    def _foundry_heights(self) -> dict[str, float] | None:
        """The scene's unified foundry z-heights, if a stack was set (walks up the
        scene graph — the same LayerStackSpec that drives GDS extrusion)."""

        return self._from_the_scene("foundry_heights")

    def _foundry_core(self) -> StackCore | None:
        """The materials the scene's foundry stack makes the core of, if a stack was set."""

        return self._from_the_scene("foundry_core")

    def _from_the_scene(self, name: str) -> Any:
        node = self
        while node is not None:
            value = getattr(node, name, None)
            if value:
                return value
            node = getattr(node, "_parent", None)
        return None

    def _core(self, color: str | None = None, preset: str | None = None) -> dict[str, Any]:
        """The keywords that put a solid of this part's core on its stack: the level the stack starts the core on,
        and the colour and material it makes the core of (the material table's, as a section draws them). With no
        foundry stack the core keeps the part's own look, or ``color`` and ``preset`` where it draws a region of
        the core in a tint of its own."""

        z = self._draw_layer_stack()["core_z"]
        films = self._foundry_core()
        if films is None:
            return {"color": color or self.color, "preset": preset or self._draw_material_preset(), "z_offset": z}
        return {"color": films.fills[films.core], "preset": films.core, "z_offset": z}

    def _slab(self, color: str, preset: str = "silicon") -> dict[str, Any]:
        """The keywords of a solid in the slab: its level, and the stack's slab material. With no foundry stack the
        part's own ``color`` and ``preset``."""

        z = self._draw_layer_stack()["rib_z"]
        films = self._foundry_core()
        if films is None:
            return {"color": color, "preset": preset, "z_offset": z}
        return {"color": films.fills[films.slab], "preset": films.slab, "z_offset": z}

    def _slab_under_core(self) -> dict[str, Any] | None:
        """The slab a core stands on (thin-film lithium niobate: the ridge on its slab), as the keywords of a slab
        solid with its ``height`` and the ``margin`` it runs out each side of the core; None where the core stands
        on the oxide."""

        stack = self._draw_layer_stack()
        if self._foundry_core() is None or stack["core_z"] <= 1e-9 \
                or abs(stack["rib_z"] + stack["rib_height"] - stack["core_z"]) > 1e-6:
            return None
        return {**self._slab(self.color), "height": stack["rib_height"], "margin": _SLAB_MARGIN}

    def _on_the_stack(self, children: list[dict[str, Any]]) -> dict[str, Any]:
        """The part's solids as one group, with what its stack adds round the core solids (those drawn with
        ``**self._core()``): the slab under a core that stands on one (thin-film lithium niobate), and the films
        over a core film that the core etch patterns with it (InP). The default stack adds nothing."""

        tree = {"shape": "group", "children": list(children)}
        films = self._foundry_core()
        under = self._slab_under_core()
        if films is None or (under is None and not films.over):
            return tree
        stack = self._draw_layer_stack()
        core = self._core()
        solids = list(_solid_leaves(tree))
        cores = []
        for node in solids:
            plan, bottom, top = _plan(node)
            material = node.get("material") or {}
            if (material.get("color"), material.get("preset")) == (core["color"], core["preset"]) \
                    and abs(bottom - core["z_offset"]) < 1e-9:
                cores.append((plan, abs(top - bottom - stack["core_height"]) < 1e-9, node))
        scale = self._draw_thickness() / float(self._foundry_heights()["chip_thickness"])
        over = [_restacked(node, z * scale, height * scale, films.fills[material], material)
                for _, full, node in cores if full             # an etched part of the core lost the films over it
                for z, height, material in films.over]
        added = _cut_footprints(over, solids)              # a solid the part sets on the core top owns its patch
        if under is not None and cores:
            import shapely

            look = {key: under[key] for key in ("color", "preset", "z_offset")}
            outline = shapely.union_all([plan for plan, _, _ in cores]).buffer(under["margin"], join_style="mitre")
            slab = []
            for piece in shapely.get_parts(outline):
                solid = _chip_extruded_polygon(piece.exterior.coords[:-1], under["height"], **look)
                if piece.interiors:
                    solid["holes"] = [ring.coords[:-1] for ring in piece.interiors]
                slab.append(solid)
            added += _cut_footprints(slab, solids)        # a slab-level solid of the part owns its patch
        tree["children"] += added
        return tree

    def _draw_layer_stack(self) -> dict[str, float]:
        """Metal/via/pad z-stack with every height + z-offset scaled by z_exaggeration.

        When the scene carries a foundry stack, the REAL layer heights override the
        heuristic ones — schematic components and imported GDS share one z-truth."""

        from optodraw.components.onchip.layer_stack import component_stack

        foundry = self._foundry_heights()
        overrides = {}
        if foundry:
            factor = self._base_thickness() / float(foundry.get("chip_thickness", self.chip_thickness))
            for key, value in foundry.items():
                if key.endswith(("_z", "_height")):
                    overrides[key] = float(value) * factor
            films = self._foundry_core()
            if films is not None and films.cladding and not {"metal_z", "heater_z"} & set(foundry):
                overrides["heater_z"] = films.cladding[1] * factor     # no level of its own: on the top dielectric
        stack = component_stack(self._base_thickness(), schematic=self._schematic_layer_stack(),
                                overrides=overrides)
        if self.z_exaggeration == 1.0:
            return stack
        return {key: value * self.z_exaggeration for key, value in stack.items()}

    def _draw_material_preset(self) -> str:
        return schematic_material_preset(self.material_preset, schematic=not self.render_physical)

    def _draw_variant_kwargs(self) -> dict[str, Any]:
        """Style kwargs for render-local components whose attrs are draw dims."""

        return {
            "color": self.color,
            "opacity": self.opacity,
            "chip_thickness": self._draw_thickness(),
            "material_preset": self._draw_material_preset(),
            "render_physical": True,
            "schematic_stack": self._schematic_layer_stack(),
            "visual_scale": self.visual_scale,
            **self._stack_kwargs(),
        }

    def _stack_kwargs(self) -> dict[str, Any]:
        """The scene's foundry stack, for a part this part builds to draw: that part has no parent in the scene."""

        return {"foundry_heights": self._foundry_heights(), "foundry_core": self._foundry_core()}

    def _schematic_layer_stack(self) -> bool:
        return getattr(self, "_schematic_stack", not self.render_physical)

    def geometry_3d(self) -> dict[str, Any]:
        return {"shape": "group", "children": []}

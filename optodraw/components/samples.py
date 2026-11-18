"""Sample-stage components used in free-space and cryostat diagrams."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optodraw.components.optics.optomech import BEAM_HEIGHT
from optodraw.core.component import Component
from optodraw.core.ports import Port
from optodraw.core.transform import Transform, Vec3

_GLOW = "#9be7ff"  # emission spot on the sample face


@dataclass
class Sample(Component):
    """A chip on its holder, optionally in a cryostat. There is one drawing: the face of the chip looks toward the
    ``in`` port, and ``angle`` turns it to the light, in every view."""

    component_type = "Sample"
    aperture: float = 20.0
    in_cryostat: bool = False
    _art_scale_from_ports = True                # the ports lie on the faces of the drawn chip

    def __init__(self, center=(0, 0), angle=0, aperture=20.0, in_cryostat=False, **kwargs):
        """Create a sample chip with optional cryostat envelope.

        Parameters
        ----------
        angle : float
            Turns the chip. At 0 it faces left, along local -x, where ``in`` lies. An objective above it on the page
            needs ``angle=-90``, a beam from the right ``angle=180``. On the bench in 3D the same angle turns it on
            the table, so it stands face on to the light.
        aperture : float
            Visual scale for the sample footprint and cryostat shell.
        in_cryostat : bool
            When true, the chip stands in a cryostat behind a window toward the light.
        **kwargs
            Supports ``material_preset``, ``color``, ``opacity``, and ``label``.
        """

        if kwargs.get("mount_orientation") == "flat":         # a saved scene: the same chip, its face up the page
            angle -= 90
        self.aperture = aperture
        self.in_cryostat = in_cryostat
        # in a cryostat the can stands on the table and holds the sample at the beam: no post
        self.base_mount = kwargs.get("base_mount", "none" if in_cryostat else "post")
        self.material_preset = kwargs.get("material_preset", "silicon")
        self.color = kwargs.get("color", "#000000")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "Sample")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def symbol_1d(self) -> tuple[str, dict[str, Any]] | None:
        return ("sample", {"kind": "cryostat"}) if self.in_cryostat else None

    def ports(self) -> dict[str, Port]:
        a = self.aperture
        # "in" is the face of the chip. "out" is the far side, for light that goes through the sample.
        # Scenes and the FTIR preset anchor a beam on it.
        front, back = (-0.05, 0.05) if self.in_cryostat else (-0.03, 0.07)
        ports = {
            "in": Port("in", Vec3(front * a, 0.0, 0.0), orientation_deg=180.0, width=a * 0.1, kind="free_space"),
            "out": Port("out", Vec3(back * a, 0.0, 0.0), orientation_deg=0.0, width=a * 0.1, kind="free_space"),
        }
        if not self.in_cryostat:                              # the edges of the chip, for light along its face
            ports["side_in"] = Port("side_in", Vec3(-0.01 * a, -0.25 * a, 0.0), orientation_deg=270.0,
                                    width=0.06 * a, kind="free_space")
            ports["side_out"] = Port("side_out", Vec3(-0.01 * a, 0.25 * a, 0.0), orientation_deg=90.0,
                                     width=0.06 * a, kind="free_space")
        # a contact: under the copper holder, or under the can of the cryostat
        ports["e1"] = Port("e1", Vec3(0.02 * a, -0.36 * a, 0.0) if self.in_cryostat else Vec3(0.04 * a, -0.31 * a, 0.0),
                           orientation_deg=270.0, width=0.05 * a, kind="electrical")
        return ports

    @property
    def window_reach(self) -> float:
        """How far the outside of the cryostat window lies from the middle of the sample: an objective stays beyond it."""

        return -Cryostat(radius=self.aperture * 0.35).ports()["in"].center.x

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(aperture=self.aperture, in_cryostat=self.in_cryostat)
        return data

    def geometry_2d(self) -> dict[str, Any]:
        """The chip on its copper holder, as in 3D; in a cryostat, the can and its window round it."""

        a = self.aperture
        chip = {"fill": "#11161c", "stroke": "#3a4654", "stroke_width": 0.06}
        copper = {"fill": "#b87333", "stroke": "#7a4a1e", "stroke_width": 0.05}
        if not self.in_cryostat:
            # as in 3D: the chip in a thin copper holder, a steel clip at each end
            return {"type": "group", "children": [
                {"type": "rect", "cx": a * 0.04, "cy": 0.0, "w": a * 0.06, "h": a * 0.62, **copper},
                {"type": "rect", "cx": -a * 0.01, "cy": 0.0, "w": a * 0.04, "h": a * 0.5, **chip},
                *[{"type": "rect", "cx": -a * 0.025, "cy": side * a * 0.27, "w": a * 0.07, "h": a * 0.06, "fill": "#b9bfc6"} for side in (-1.0, 1.0)],
            ]}
        return {"type": "group", "children": [
            # vacuum dewar shell + inner radiation shield
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": a * 0.7, "h": a * 0.7, "fill": "#1b2733", "stroke": "#0b1b2b", "stroke_width": 0.1, "opacity": 0.92},
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": a * 0.56, "h": a * 0.56, "fill": "#0e1a26", "stroke": "#24506b", "stroke_width": 0.06, "opacity": 0.85},
            # optical access window on the entry face (-x)
            {"type": "rect", "cx": -a * 0.35, "cy": 0.0, "w": a * 0.06, "h": a * 0.22, "fill": "#bae6fd", "stroke": "#0891b2", "stroke_width": 0.06, "opacity": 0.5},
            # copper cold-finger / sample mount from the back
            {"type": "rect", "cx": a * 0.2, "cy": 0.0, "w": a * 0.3, "h": a * 0.12, **copper},
            # the sample chip itself (active face toward -x)
            {"type": "rect", "cx": 0.0, "cy": 0.0, "w": a * 0.1, "h": a * 0.4, **chip},
            # emission / focus spot
            {"type": "circle", "cx": -a * 0.05, "cy": 0.0, "r": a * 0.03, "fill": _GLOW, "opacity": 0.95},
        ]}

    def geometry_3d(self) -> dict[str, Any]:
        """The chip face on to local -x, on its copper holder; in a cryostat, the Cryostat's can, windows and block."""

        a = self.aperture
        if self.in_cryostat:
            # The Cryostat part, lowered so its sample sits at this anchor (the beam): the can stands on the
            # table. A glass tube lying on its side, on a post, read as nothing a lab has.
            cryostat = Cryostat(radius=a * 0.35)                  # the can of the 2D drawing
            beam = cryostat.beam_height
            children = [{**child, "position": [child["position"][0], child["position"][1] - beam, child["position"][2]]}
                        for child in cryostat.geometry_3d()["children"]]
            children.append({"shape": "sphere", "radius": a * 0.03, "position": [-a * 0.05, 0.0, 0.0],
                             "material": {"color": _GLOW, "emissive": "#3aa0d0", "emissiveIntensity": 0.8}})
            return {"shape": "group", "children": children}
        # Out of a cryostat the chip is clipped to the front of a thin copper holder plate on a stem.
        copper = {"color": "#b87333", "metalness": 0.7, "roughness": 0.3, "preset": "copper"}
        clip = {"color": "#b9bfc6", "metalness": 0.9, "roughness": 0.18, "preset": "steel"}
        children: list[dict[str, Any]] = [
            {"shape": "box", "width": a * 0.06, "height": a * 0.62, "depth": a * 0.62, "position": [a * 0.04, 0.0, 0.0], "material": copper},
            {"shape": "box", "width": a * 0.04, "height": a * 0.5, "depth": a * 0.5, "position": [-a * 0.01, 0.0, 0.0], "material": {"color": "#11161c", "metalness": 0.3, "roughness": 0.4, "preset": self.material_preset}},
            {"shape": "sphere", "radius": a * 0.04, "position": [-a * 0.03, 0.0, 0.0], "material": {"color": _GLOW, "emissive": "#3aa0d0", "emissiveIntensity": 0.8}},
            *[{"shape": "box", "role": "clip", "width": a * 0.03, "height": a * 0.06, "depth": a * 0.1, "position": [-a * 0.045, up * a * 0.27, side * a * 0.2], "material": clip}
              for up in (-1.0, 1.0) for side in (-1.0, 1.0)],
            {"shape": "box", "width": a * 0.1, "height": a * 0.1, "depth": a * 0.16, "position": [a * 0.04, -a * 0.36, 0.0], "material": copper},
        ]
        return {"shape": "group", "children": children}


@dataclass
class Cryostat(Component):
    """A cryostat the sample sits inside: vacuum shroud, radiation shield, and a
    cold-finger stage carrying the sample at the bench beam height.

    Optical access is real hardware here: a wide window on the in side, which the
    sample faces and the objective outside focuses through, and a small window on
    the out side, both on the beam axis with glass in them. The shroud is drawn
    see-through so the stage and sample read from outside, the way a cutaway
    figure shows them.

    It carries its own stage, so a sample does not have to be stacked on top of
    the cryostat as a separate component; ``with_sample=False`` leaves the stage
    bare for one placed at the ``sample`` port."""

    component_type = "Cryostat"
    radius: float = 14.0
    with_sample: bool = True

    def __init__(self, center=(0, 0), angle=0, radius=14.0, with_sample=True, **kwargs):
        self.radius = float(radius)
        self.with_sample = bool(with_sample)
        # the windows sit at the bench beam height: a cryostat stands on the
        # table on its own feet, it is not raised to the beam on a post
        self._scene_beam = "beam_height" not in kwargs      # unset: the 3D view gives it the scene's beam height
        self.beam_height = float(kwargs.get("beam_height", BEAM_HEIGHT))
        self.color = kwargs.get("color", "#aeb7c2")
        self.opacity = kwargs.get("opacity", 1.0)
        self.label = kwargs.get("label", "Cryostat")
        self.material_preset = kwargs.get("material_preset", "steel")
        self.transform = Transform.from_2d(*self._parse_center(center).as_2d(), angle)
        self._parent = None
        self._id = ""

    def symbol_1d(self) -> tuple[str, dict[str, Any]]:
        return "cryostat", ({} if self.with_sample else {"sample": "no"})

    def symbol_2d(self) -> tuple[str, dict[str, Any]]:
        # the 1D symbol is a side view; 2D is seen from above. Without its own sample the stage stays bare and no
        # axis runs through the windows: a sample placed inside draws itself and its beam
        return "cryostat", ({"view": "top"} if self.with_sample else {"view": "top", "sample": "no"})

    def ports(self) -> dict[str, Port]:
        r = self.radius
        return {
            "in": Port("in", Vec3(-r * 1.18, 0.0, 0.0), orientation_deg=180.0, width=r * 0.3, kind="free_space"),
            "out": Port("out", Vec3(r * 1.18, 0.0, 0.0), orientation_deg=0.0, width=r * 0.3, kind="free_space"),
            # the cold-finger stage: where a sample goes if you place your own
            "sample": Port("sample", Vec3(0.0, 0.0, 0.0), orientation_deg=90.0, width=r * 0.3, kind="free_space"),
            # the wiring feedthrough at the bottom of the can, where the top view draws its rim
            "e1": Port("e1", Vec3(0.0, -r * 1.062, 0.0), orientation_deg=270.0, width=r * 0.1, kind="electrical"),
        }

    def geometry_2d(self) -> dict[str, Any]:
        r = self.radius
        children = [
            {"type": "rect", "cx": -r * 1.09, "cy": 0.0, "w": r * 0.22, "h": r * 0.34, "fill": "#8b95a1", "stroke": "#5d6570", "stroke_width": 0.1, "opacity": self.opacity},
            {"type": "rect", "cx": r * 1.09, "cy": 0.0, "w": r * 0.22, "h": r * 0.34, "fill": "#8b95a1", "stroke": "#5d6570", "stroke_width": 0.1, "opacity": self.opacity},
            {"type": "circle", "cx": 0.0, "cy": 0.0, "r": r, "fill": self.color, "stroke": "#5d6570", "stroke_width": 0.16, "opacity": self.opacity},
            {"type": "circle", "cx": 0.0, "cy": 0.0, "r": r * 0.72, "fill": "#cfd6dd", "stroke": "#8b95a1", "stroke_width": 0.12, "opacity": self.opacity},
            *[{"type": "circle", "cx": r * 0.88 * math.cos(math.radians(a)), "cy": r * 0.88 * math.sin(math.radians(a)), "r": r * 0.035, "fill": "#5d6570", "opacity": self.opacity} for a in range(15, 360, 45)],
            # cold finger down onto the sample stage
            {"type": "rect", "cx": 0.0, "cy": r * 0.46, "w": r * 0.12, "h": r * 0.52, "fill": "#8b95a1", "opacity": self.opacity},
            {"type": "rect", "cx": 0.0, "cy": r * 0.17, "w": r * 0.5, "h": r * 0.12, "fill": "#7c8794", "stroke": "#5d6570", "stroke_width": 0.08, "opacity": self.opacity},
        ]
        if self.with_sample:
            children.append({"type": "rect", "cx": 0.0, "cy": 0.0, "w": r * 0.28, "h": r * 0.22,
                             "fill": "#2b3038", "stroke": "#14181e", "stroke_width": 0.1, "opacity": self.opacity})
        children += [
            # glass in the beam-axis windows
            {"type": "rect", "cx": -r * 0.86, "cy": 0.0, "w": r * 0.56, "h": r * 0.18, "fill": "#e6f2f8", "stroke": "#8b95a1", "stroke_width": 0.08, "opacity": self.opacity * 0.9},
            {"type": "rect", "cx": r * 0.86, "cy": 0.0, "w": r * 0.56, "h": r * 0.18, "fill": "#e6f2f8", "stroke": "#8b95a1", "stroke_width": 0.08, "opacity": self.opacity * 0.9},
        ]
        return {"type": "group", "children": children}

    @staticmethod
    def _tube(inner_r: float, outer_r: float, length: float, material, position, axis: str):
        """A real tube: a lathed annulus with an open bore, so you can see THROUGH
        it. A cylinder is a solid plug — putting glass inside one buries it."""

        half = length / 2.0
        spin = [0.0, 0.0, 1.5708] if axis == "x" else [1.5708, 0.0, 0.0]
        return {
            "shape": "lathe_profile",
            "points": [[inner_r, -half], [outer_r, -half], [outer_r, half], [inner_r, half], [inner_r, -half]],
            "segments": 36,
            "rotation": spin,
            "position": list(position),
            "material": material,
        }

    def geometry_3d(self) -> dict[str, Any]:
        r = self.radius
        beam = self.beam_height
        body_h = beam * 1.75
        # The shroud is a vacuum can drawn as a cutaway: it still reads as metal, and the chip
        # and its block show through it.
        shell = {"color": self.color, "preset": self.material_preset, "metalness": 0.6,
                 "roughness": 0.28, "opacity": 0.42, "transparent": True}
        metal = {"color": "#8b95a1", "preset": self.material_preset, "metalness": 0.6, "roughness": 0.35}
        copper = {"color": "#b87a4b", "metalness": 0.75, "roughness": 0.3}
        # real optical-access glass: you look straight through it
        glass = {"color": "#eaf7ff", "metalness": 0.05, "roughness": 0.01, "opacity": 0.12,
                 "transparent": True, "clearcoat": 1.0, "envMapIntensity": 2.4}

        # The chip stands on the beam and faces the -x window, on a copper block that the cold finger comes down to,
        # so the light that comes through the window meets its face. A sample's "in" port is this face.
        chip, chip_t = r * 1.1, r * 0.06
        block, block_t = r * 1.25, r * 0.2
        front = -r / 7.0
        block_x = front + chip_t + block_t / 2.0
        finger_bottom = beam + block / 2.0
        finger_h = max(body_h - finger_bottom, r * 0.2) * 1.01      # its top just inside the flange, off the shell's

        children = [
            {"shape": "cylinder", "radius": r, "height": body_h,
             "position": [0.0, body_h / 2.0, 0.0], "material": shell},
            {"shape": "cylinder", "radius": r * 1.04, "height": r * 0.14,
             "position": [0.0, body_h, 0.0], "material": metal},
            {"shape": "cylinder", "radius": r * 0.5, "height": r * 0.5,
             "position": [0.0, body_h + r * 0.32, 0.0], "material": metal},
            # cold finger, landing ON the block rather than hovering over it
            {"shape": "cylinder", "radius": r * 0.09, "height": finger_h, "role": "finger",
             "position": [block_x, finger_bottom + finger_h / 2.0, 0.0], "material": metal},
            # the cold block the sample is mounted to
            {"shape": "box", "width": block_t, "height": block, "depth": block, "role": "stage",
             "position": [block_x, beam, 0.0], "material": copper},
        ]
        if self.with_sample:
            children.append({"shape": "box", "width": chip_t, "height": chip, "depth": chip,
                             "role": "sample", "position": [front + chip_t / 2.0, beam, 0.0],
                             "material": {"color": "#2b3038", "metalness": 0.3, "roughness": 0.5}})

        # The out window: an open tube through the wall with the glass across its OUTER face, so the light path is clear.
        snout_len = r * 0.22
        bore_r = r * 0.17
        children += [
            self._tube(bore_r, bore_r * 1.4, snout_len, metal, [r + snout_len * 0.35, beam, 0.0], "x"),
            {"shape": "cylinder", "radius": bore_r * 1.36, "height": r * 0.04, "role": "window",
             "rotation": [0.0, 0.0, 1.5708], "position": [r + snout_len * 0.8, beam, 0.0], "material": glass},
        ]

        # The main window on the in side, which the sample faces: the objective outside focuses through it, so it is
        # the wide one. A wide bore through the wall, a bezel, and clear glass across the outside. It sat on the side
        # at +z, at 90 degrees to the chip's face, so a beam through it would meet the chip edge on.
        # The bore and its outer collar are one lathed solid: two tubes on one bore z-fought.
        view_r = r * 0.34
        wide = self._tube(view_r, view_r * 1.3, r * 0.55, metal, [-(r - r * 0.05), beam, 0.0], "x")
        collar = (r + snout_len * 0.3) - (r - r * 0.05)          # the collar's centre along the tube, whose +y is world -x
        a, b = collar - snout_len * 0.45, collar + snout_len * 0.45
        wide["points"][2:2] = [[view_r * 1.3, a], [view_r * 1.32, a], [view_r * 1.32, b], [view_r * 1.3, b]]
        children += [
            wide,
            {"shape": "torus", "radius": view_r * 1.16, "tube": r * 0.04, "rotation": [0.0, 1.5708, 0.0],
             "position": [-(r + snout_len * 0.72), beam, 0.0], "material": metal},
            {"shape": "cylinder", "radius": view_r * 1.12, "height": r * 0.035, "role": "window",
             "rotation": [0.0, 0.0, 1.5708], "position": [-(r + snout_len * 0.74), beam, 0.0], "material": glass},
        ]
        return {"shape": "group", "children": children}

    def physics_metadata(self) -> dict[str, Any]:
        return {"domain": "free_space", "component": "cryostat", "radius": self.radius,
                "beam_height": self.beam_height, "with_sample": self.with_sample}

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(radius=self.radius, with_sample=self.with_sample)
        return data

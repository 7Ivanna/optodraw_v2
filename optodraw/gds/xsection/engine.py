"""Cross-section process engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import MultiPolygon
from shapely.ops import unary_union

from optodraw.gds.xsection.masks import LayoutCut
from optodraw.gds.xsection.operations import (
    apply_deposit,
    apply_etch,
    apply_fill,
    apply_flip,
    apply_implant,
    apply_planarize,
    apply_snapshot,
)
from optodraw.gds.palette import canonical, doping_label, material_label
from optodraw.gds.xsection.regions import RegionStack, rectangle, repair
from optodraw.gds.xsection.schema import ProcessDefinition, load_process_definition


@dataclass
class OutputLayer:
    name: str
    geometry: MultiPolygon
    color: str
    hatch: str
    opacity: float
    stroke: str
    z_order: int


@dataclass
class OutputStack:
    process_name: str
    cut_label: str
    layers: list[OutputLayer]
    internal_regions: dict[str, MultiPolygon] = field(default_factory=dict)
    debug_steps: dict[str, dict[str, MultiPolygon]] = field(default_factory=dict)
    steps: list[tuple[str, str, dict[str, MultiPolygon]]] = field(default_factory=list)
    materials: dict[str, str] = field(default_factory=dict)
    doping: dict[str, MultiPolygon] = field(default_factory=dict)


class XSectionEngine:
    def __init__(self, process: ProcessDefinition):
        self.process = process
        self._last_debug_steps: dict[str, dict[str, MultiPolygon]] = {}

    @classmethod
    def from_yaml(cls, path: str | Path) -> XSectionEngine:
        return cls(load_process_definition(path))

    @classmethod
    def from_json(cls, path: str | Path) -> XSectionEngine:
        return cls(load_process_definition(path))

    def run(self, cut: LayoutCut, *, debug: bool = False) -> OutputStack:
        stack = self._initial_stack(cut)
        steps = [("start", self._start_caption(), {name: repair(geom) for name, geom in stack.regions.items()})]
        for step in self.process.process:
            mask = cut.evaluate_mask(step.mask) if step.mask is not None else None
            if step.etch is not None:
                apply_etch(stack, cut, mask, step.etch)
            if step.deposit is not None:
                apply_deposit(stack, cut, mask, step.deposit)
            if step.fill is not None:
                apply_fill(stack, cut, step.fill)
            if step.implant is not None:
                apply_implant(stack, cut, mask, step.implant)
            if step.planarize is not None:
                apply_planarize(stack, cut, step.planarize)
            if step.flip:
                apply_flip(stack)
            if step.snapshot is not None:
                apply_snapshot(stack, step.snapshot)
            steps.append((step.id, step.caption or _caption(step),
                          {name: repair(geom) for name, geom in stack.regions.items()}))
        debug_steps = {step_id: regions for step_id, _, regions in steps[1:]} if debug else {}
        self._last_debug_steps = debug_steps
        return OutputStack(
            process_name=self.process.name,
            cut_label=cut.label,
            layers=self._build_output_layers(stack),
            internal_regions={name: repair(geom) for name, geom in stack.regions.items()},
            debug_steps=debug_steps,
            steps=steps,
            materials=dict(stack.materials),
            doping={name: repair(geom) for name, geom in stack.doping.items()},
        )

    def _initial_stack(self, cut: LayoutCut) -> RegionStack:
        y0, y1 = cut.y_extent(self.process.render.y_margin_um)
        stack = RegionStack()
        for layer in self.process.wafer:
            stack.add(layer.name, rectangle(y0, y1, layer.z0, layer.z1), layer.material)
        return stack

    def _start_caption(self) -> str:
        """The first caption: "SOI wafer" for a silicon core on oxide, else the core on the band under it."""

        wafer = list(self.process.wafer)
        core = self.process.device
        at = wafer.index(core)
        under = wafer[at - 1].material if at > 0 else None
        if canonical(core.material) == "silicon" and under is not None and canonical(under) == "sio2":
            return "SOI wafer"
        name = material_label(core.material) or core.material
        return f"{name} on {material_label(under) or under}" if under is not None else f"{name} wafer"

    def _build_output_layers(self, stack: RegionStack) -> list[OutputLayer]:
        layers: list[OutputLayer] = []
        for spec in sorted(self.process.output_layers, key=lambda item: item.z_order):
            if not self.process.render.show_substrate and (
                spec.from_region in {"box", "handle"}
                or (spec.union and set(spec.union).issubset({"box", "handle"}))
            ):
                continue
            geometry = self._resolve_output_geometry(stack, spec)
            layers.append(
                OutputLayer(
                    name=spec.name,
                    geometry=geometry,
                    color=spec.color,
                    hatch=spec.hatch,
                    opacity=spec.opacity,
                    stroke=spec.stroke,
                    z_order=spec.z_order,
                )
            )
        return layers

    def _resolve_output_geometry(self, stack: RegionStack, spec) -> MultiPolygon:
        if spec.union:
            pieces = [stack.get(name) for name in spec.union]
            nonempty = [piece for piece in pieces if not piece.is_empty]
            if not nonempty:
                return MultiPolygon([])
            return repair(unary_union(nonempty))
        if spec.from_region:
            return repair(stack.get(spec.from_region))
        return MultiPolygon([])

    def export_debug_svg(self, step_id: str, output_path: str | Path) -> Path:
        from optodraw.gds.xsection.renderer_svg import render_output_stack_to_svg

        if step_id not in self._last_debug_steps:
            raise KeyError(f"No debug snapshot for step {step_id!r}")
        regions = self._last_debug_steps[step_id]
        layers = [
            OutputLayer(
                name=name,
                geometry=geom,
                color="#888888",
                hatch="none",
                opacity=0.8,
                stroke="#1f2937",
                z_order=index,
            )
            for index, (name, geom) in enumerate(regions.items())
            if not geom.is_empty
        ]
        stack = OutputStack(
            process_name=self.process.name,
            cut_label=step_id,
            layers=layers,
            internal_regions=regions,
        )
        return render_output_stack_to_svg(stack, self.process, Path(output_path))


def _caption(step) -> str:
    """A short caption for a step the process file did not caption."""

    if step.fill is not None:
        return f"Fill {step.fill.get('material', '')} and CMP".replace("  ", " ")
    if step.deposit is not None:
        return f"Deposit {step.deposit.get('material', '')}, {_size(step.deposit.get('thickness', 0.0))}"
    if step.etch is not None:
        return f"Etch {_size(step.etch['depth'])}" if step.etch.get("depth") is not None else "Etch to the stop layer"
    if step.implant is not None:
        return f"{doping_label(step.implant.get('species', ''))} implant".strip()
    if step.planarize is not None:
        return "CMP"
    return step.id


def _size(um: float) -> str:
    return f"{um * 1000:.0f} nm" if abs(um) < 1.0 else f"{um:g} µm"

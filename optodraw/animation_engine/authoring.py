"""Bind authoring descriptors to scene IDs and physical signal tables."""

from copy import copy, deepcopy
from dataclasses import replace
import json

from .errors import AnimationError
from .graph import build_graph
from .ids import scene_ids
from .inputs import InputSignal
from .primitives import Action, Flow, Lagged, Quantity, Sequence, number
from .parameters import compile_sweep, plot_values, sample_values
from .styles import Style, resolve_style
from .tables import compile_table, extent_time_ps, terminal_time_ps
from .timeline import Timeline


class Animation:
    def __init__(self, scene, *, view="2d", style="photons", mode="cw",
                 transit_seconds=2.5, time_scale_s_per_ps=None, floor=None, strict=False):
        if mode not in {"pulse", "cw"}:
            raise ValueError("mode must be pulse or cw")
        if not isinstance(strict, bool):
            raise ValueError("strict must be a boolean")
        self.scene = scene
        self.mode = mode
        self.strict = strict
        self.floor = floor
        self.transit_seconds = number(transit_seconds, "transit_seconds", positive=True)
        self._scale = (None if time_scale_s_per_ps is None else
                       number(time_scale_s_per_ps, "time_scale_s_per_ps", positive=True))
        self._style = resolve_style(style)
        self.timeline = Timeline(view=view, style=self._style)
        self._scene_spec = deepcopy(scene.to_spec())
        self._ids = scene_ids(scene)
        self._graph = build_graph(scene)
        self._inputs = []
        self._params = {}
        self._cache = {}
        self._has_state = False
        self._active_paths = []
        self._all_paths = False

    def scene_parts(self):
        """Return the bound graph's parts in stable order, without running physics."""
        return tuple(self._graph.parts.values())

    def _check_scene(self):
        if self.scene.to_spec() != self._scene_spec:
            raise ValueError("the scene changed after animation binding")

    def _at_boundary(self):
        return abs(self.timeline.cursor - self.timeline._section_start) < 1e-12

    def _target(self, target, *, paths=()):
        if target is None:
            return None
        if isinstance(target, tuple) and len(target) == 2 and id(target[0]) in self._ids:
            target = f"port:{self._ids[id(target[0])]}:{target[1]}"
        elif not isinstance(target, str):
            sid = self._ids.get(id(target))
            if sid is None:
                raise ValueError("target does not belong to this scene")
            target = f"{'route' if sid.startswith('route') else 'part'}:{sid}"
        if target in self.timeline.assets or target in paths:
            return target
        if target.startswith("part:") and target[5:] in self._graph.parts:
            return target
        if target.startswith("port:"):
            fields = target.split(":")
            if len(fields) == 3 and fields[1] in self._graph.parts:
                try:
                    self._graph.parts[fields[1]].world_port(fields[2])
                except (KeyError, ValueError):
                    raise ValueError(f"target {target} does not belong to this scene") from None
                return target
        if target in {link.id for link in self._graph.links}:
            return target
        raise ValueError(f"target {target} does not belong to this scene")

    def _value(self, value):
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return self._target(value) if value.startswith(("part:", "port:", "route:", "text:", "plot:")) else value
        if isinstance(value, dict):
            return {key: self._value(item) for key, item in value.items()}
        if isinstance(value, tuple) and len(value) == 2 and id(value[0]) in self._ids:
            return self._target(value)
        if isinstance(value, (list, tuple)):
            return [self._value(item) for item in value]
        return self._target(value)

    def _register_state(self, data):
        data = deepcopy(data)
        if self._scale is None:
            terminal = data.get("terminal_time_ps") if "samples" in data else terminal_time_ps(data)
            self._scale = self.transit_seconds / terminal if terminal > 0 else 1.0
        data["time_scale_s_per_ps"] = self._scale
        if not self._has_state:
            self.timeline.signal_state = data
            self._has_state = True
            return "base"
        ref = f"q{len(self.timeline.signal_states) + 2}"
        self.timeline.signal_states[ref] = data
        return ref

    def _state(self, mode):
        key = json.dumps([mode, self._params, [item.to_json() for item in self._inputs]], sort_keys=True)
        if key not in self._cache:
            data = compile_table(self.scene, mode=mode, params=self._params, inputs=self._inputs,
                                 floor=self.floor, strict=self.strict)
            for link in self._graph.links:
                if link.medium != "electrical" and link.id not in data["edges"]:
                    data["edges"][link.id] = {"points": [list(point) for point in link.points],
                                              "length_um": link.length, "group_index": link.group_index,
                                              "cw": [], "packets": []}
            self._cache[key] = self._register_state(data)
        ref = self._cache[key]
        return ref, self.timeline.signal_state if ref == "base" else self.timeline.signal_states[ref]

    def _flow(self, action):
        args = deepcopy(action.args)
        mode = args.get("mode") or self.mode
        ref, state = self._state(mode)
        style = Style.from_json(args["style"]) if args.get("style") else self._style
        if style.name == "bits":
            sid = next(iter(self._graph.parts), "scene")
            raise AnimationError(f"{sid}: Flow bits requires an electrical signal table")
        paths = args.get("paths")
        available = set(state["edges"]) | {link.id for link in self._graph.links}
        paths = list(state["edges"]) if paths is None else [self._target(path, paths=available) for path in paths]
        for path in paths:
            if path not in available:
                raise ValueError(f"unknown optical path {path}")
        exits = [item["id"] for item in state.get("exits", [])] if action.args.get("paths") is None else []
        seconds = action.seconds
        if seconds is None:
            seconds = extent_time_ps(state) * self._scale
            if seconds <= 0:
                seconds = self.transit_seconds
            if exits:
                seconds = max(seconds, max(item["display_duration_s"] for item in state["exits"]))
        args.update(paths=paths, exits=exits, state=ref, mode=mode, style=style.to_json(),
                    settled=bool(args.get("settled", False)))
        if mode == "cw":
            self._all_paths = self._all_paths or action.args.get("paths") is None
            self._active_paths = list(dict.fromkeys([*self._active_paths, *paths]))
        return replace(action, seconds=seconds, args=args)

    def _asset(self, kind, data):
        index = 1 + sum(key.startswith(f"{kind}:") for key in self.timeline.assets)
        target = f"{kind}:{index}"
        self.timeline.assets[target] = data
        return target

    def _bind_parallel(self, actions):
        prepared = {}
        for index, action in enumerate(actions):
            if (isinstance(action, Action) and action.type == "Flow"
                    and (action.args.get("mode") or self.mode) == "cw"):
                prepared[index] = self._bind(action)
        return [prepared[index] if index in prepared else self._bind(action)
                for index, action in enumerate(actions)]

    def _bind(self, action):
        if isinstance(action, Sequence):
            children = (self._bind_parallel(action.children)
                        if isinstance(action, Lagged) and action.lag == 0
                        else [self._bind(child) for child in action.children])
            return Lagged(*children, lag=action.lag) if isinstance(action, Lagged) else Sequence(*children)
        if not isinstance(action, Action):
            raise TypeError("play requires animation descriptors")
        if action.type == "Flow":
            return self._flow(action)
        if action.type == "Set":
            self._params[action.target] = deepcopy(action.args["value"])
            return action
        if action.type == "Sweep":
            return self._sweep(action)
        if action.type == "Plot":
            return self._plot(action)
        args = self._value(action.args)
        target = self._target(action.target)
        if action.type in {"Write", "Label"}:
            near = args.pop("near", target)
            text = args.pop("text", "")
            target = self._asset("text", {"kind": "text", "text": text, "near": near})
        return replace(action, target=target, args=args)

    def _layout(self, actions, start=0.0):
        rows, end = [], start
        for action in actions:
            if isinstance(action, Sequence):
                cursor, finish = start, start
                for child in action.children:
                    children, child_end = self._layout([child], cursor)
                    rows.extend(children)
                    finish = max(finish, child_end)
                    cursor = cursor + action.lag if isinstance(action, Lagged) else child_end
                end = max(end, finish)
            elif isinstance(action, Action):
                finish = start + (action.seconds or 0.0)
                rows.append((action, start, finish))
                end = max(end, finish)
            else:
                raise TypeError("play requires animation descriptors")
        return rows, end

    @staticmethod
    def _overlap(left, right):
        _, a, b = left
        _, c, d = right
        if a == b and c == d:
            return a == c
        if a == b:
            return c <= a < d
        if c == d:
            return a <= c < b
        return max(a, c) < min(b, d)

    def _preflight(self, actions, *, bound=False):
        rows, _ = self._layout(actions)
        writers = [row for row in rows if row[0].type in {"Set", "Sweep"}]
        for index, left in enumerate(writers):
            if left[0].type == "Set" and (not self._at_boundary() or left[1] != 0):
                raise ValueError("Set requires a section boundary")
            for right in writers[index + 1:]:
                if self._overlap(left, right):
                    if left[0].target == right[0].target:
                        raise ValueError(f"conflicting writers for {left[0].target}")
                    if left[0].type == right[0].type == "Sweep":
                        raise ValueError("overlapping sweeps require a multidimensional table")
        sweeps = [row for row in rows if row[0].type == "Sweep"]
        for flow in (row for row in rows if row[0].type == "Flow"):
            if (flow[0].args.get("mode") or self.mode) == "pulse":
                for sweep in sweeps:
                    if self._overlap(flow, sweep) or (flow[0].seconds is None and flow[1] == sweep[1]):
                        raise ValueError("a sweep cannot overlap pulse Flow")
        if bound:
            return rows, sweeps
        self._plot_sweeps = {}
        for action, _, _ in rows:
            if action.type == "Plot":
                matching = [row[0] for row in sweeps if row[0].target == action.args["against"]]
                if len(matching) != 1:
                    raise ValueError("Plot requires exactly one matching sweep")
                sweep = matching[0]
                if action.seconds is not None and (action.seconds != sweep.seconds or action.easing != sweep.easing):
                    raise ValueError("Plot duration and easing must match its sweep")
                quantity = action.args.get("quantity", action.args.get("qty"))
                if not isinstance(quantity, Quantity):
                    raise ValueError("Plot requires a Quantity")
                target = (quantity.target, quantity.port) if quantity.port is not None else quantity.target
                self._target(target)
                self._plot_sweeps[id(action)] = sweep
        return rows, sweeps

    def _sweep(self, action):
        if id(action) in self._prepared_sweeps:
            return self._prepared_sweeps[id(action)]
        values = sample_values(action.args["start"], action.args["stop"],
                               samples=action.args["samples"], easing=action.easing)
        table = compile_sweep(self.scene, action.target, values, params=self._params,
                              inputs=self._inputs, floor=self.floor, strict=self.strict)
        ref = self._register_state(table)
        self._params[action.target] = values[-1]
        terminal, _ = self._state("cw")
        args = deepcopy(action.args)
        paths = list(table["edges"]) if self._all_paths else [path for path in self._active_paths if path in table["edges"]]
        args.update(state=ref, terminal_state=terminal, paths=paths,
                    exits=[item["id"] for item in table["exits"]] if self._all_paths else [], mode="cw")
        bound = replace(action, args=args)
        self._prepared_sweeps[id(action)] = bound
        return bound

    def _plot(self, action):
        sweep = self._sweep(self._plot_sweeps[id(action)])
        quantity = action.args.get("quantity", action.args.get("qty"))
        target = (quantity.target, quantity.port) if quantity.port is not None else quantity.target
        data = {"target": self._target(target), "name": quantity.name}
        ref = sweep.args["state"]
        table = self.timeline.signal_state if ref == "base" else self.timeline.signal_states[ref]
        asset = {"kind": "plot", "quantity": data, "against": action.args["against"],
                 "x": list(table["samples"]), "y": plot_values(table, data)}
        target = self._asset("plot", asset)
        return replace(action, target=target, seconds=sweep.seconds, easing=sweep.easing,
                       args={"quantity": data, "against": action.args["against"], "state": ref})

    def play(self, *actions):
        self._check_scene()
        staged = copy(self)
        staged.timeline = deepcopy(self.timeline)
        staged._cache = dict(self._cache)
        staged._params = deepcopy(self._params)
        rows, sweeps = staged._preflight(actions)
        staged._prepared_sweeps = {}
        for action, _, _ in rows:
            if action.type == "Set":
                staged._params[action.target] = deepcopy(action.args["value"])
        if sweeps and not any(track.type == "Flow" and track.args["mode"] == "cw" for track in self.timeline.tracks):
            if not any(action.type == "Flow" and (action.args.get("mode") or self.mode) == "cw" for action, _, _ in rows):
                flow = Flow(mode="cw", style=self._style, seconds=max(row[2] for row in sweeps))
                actions = (replace(flow, args={**flow.args, "settled": True}), *actions)
        prepared = staged._bind_parallel(actions)
        staged._preflight(prepared, bound=True)
        staged.timeline.play(*prepared)
        timeline = self.timeline
        self.__dict__.update(staged.__dict__)
        timeline.__dict__.update(staged.timeline.__dict__)
        self.timeline = timeline
        return self

    def input(self, part, port, **kwargs):
        self._check_scene()
        if not self._at_boundary():
            raise ValueError("inputs can change only at a section boundary")
        signal = InputSignal(self._target((part, port)), **kwargs)
        signal.validate(self._graph)
        self._inputs.append(signal)
        return self

    def auto(self, *, mode=None, paths=None):
        return self.play(Flow(paths=paths, style=self._style, mode=mode or self.mode))

    def wait(self, seconds):
        from .primitives import Wait
        return self.play(Wait(seconds))

    def click(self):
        from .primitives import Click
        return self.play(Click())

    def set_style(self, style):
        if not self._at_boundary():
            raise ValueError("style can change only at a section boundary")
        self._style = resolve_style(style)
        return self

    def to_json(self):
        self._check_scene()
        return self.timeline.to_json()

    def dumps(self):
        self._check_scene()
        return self.timeline.dumps()

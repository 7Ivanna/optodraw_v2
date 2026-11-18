"""Timed actions and click sections, without scene or physics dependencies."""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import asdict, dataclass

from .primitives import EASINGS, PRIMITIVES, Action, Lagged, Sequence, Wait, number
from .styles import Style, resolve_style


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def encode_document(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _fields(data, names, label):
    if not isinstance(data, dict) or set(data) != set(names.split()):
        raise ValueError(f"invalid {label} fields")


def _numeric(value, label, *, minimum=0, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    if value < minimum or (positive and value == minimum):
        raise ValueError(f"invalid {label}")


def _json_values(value):
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON keys must be strings")
        for item in value.values():
            _json_values(item)
    elif isinstance(value, list):
        for item in value:
            _json_values(item)
    elif isinstance(value, float):
        _numeric(value, "JSON number", minimum=-math.inf)
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise ValueError("values must use JSON types")


def _identifier(value, pattern, label):
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError(f"invalid {label} id: {value}")


def _reference(value, assets, *, required=False):
    if value is None:
        if required:
            raise ValueError("missing target reference")
        return
    _identifier(value, r"(?:part|port|route|beam|path|text|plot|exit):\S+", "target")
    if value.startswith(("text:", "plot:")) and value not in assets:
        raise ValueError(f"missing asset reference: {value}")


def _vector(value):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("Jones vector requires four real numbers")
    for item in value:
        _numeric(item, "Jones value", minimum=-math.inf)


def _sample_field(value, count, label, *, positive=False, nullable=False, signed=False):
    if count is None:
        _numeric(value, label, minimum=-math.inf if signed else 0, positive=positive)
        return
    if not isinstance(value, list) or len(value) != count:
        raise ValueError(f"{label} sample-array length mismatch")
    for item in value:
        if nullable and item is None:
            continue
        _numeric(item, label, minimum=-math.inf if signed else 0, positive=positive)


def _points(points, label):
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError(f"{label} requires points")
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError(f"invalid {label} point")
        for value in point:
            _numeric(value, f"{label} point", minimum=-math.inf)


def _state(data, assets):
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("unsupported signal-state version")
    if data.get("mode") not in {"pulse", "cw"}:
        raise ValueError("invalid signal-state mode")
    _numeric(data.get("duration_ps"), "physical duration")
    _numeric(data.get("time_scale_s_per_ps"), "time scale", positive=True)
    if not isinstance(data.get("params"), dict) or not isinstance(data.get("inputs"), list):
        raise ValueError("invalid signal-state parameters or inputs")
    count = None
    if "samples" in data:
        if not isinstance(data["samples"], list) or len(data["samples"]) < 2:
            raise ValueError("invalid state samples")
        count = len(data["samples"])
        _sample_field(data["samples"], count, "state samples", signed=True)
        if not isinstance(data.get("param"), str) or not data["param"]:
            raise ValueError("sampled state requires a parameter")
    for signal in data["inputs"]:
        if not isinstance(signal, dict):
            raise ValueError("invalid input")
        _reference(signal.get("target"), assets, required=True)
        _vector(signal.get("jones"))
        for key in ("wavelength_nm", "width_ps"):
            _numeric(signal.get(key), key, positive=True)
        _numeric(signal.get("t0_ps"), "input time")
        if signal.get("direction") not in {"in", "out"}:
            raise ValueError("invalid input direction")
    if not isinstance(data.get("edges"), dict):
        raise ValueError("invalid state edges")
    for edge_id, edge in data["edges"].items():
        _reference(edge_id, assets)
        if not isinstance(edge, dict):
            raise ValueError(f"invalid edge {edge_id}")
        _points(edge.get("points"), edge_id)
        for key in ("length_um", "group_index", "ng", "n_g"):
            if key in edge:
                value = edge[key]
                _sample_field(value, count if isinstance(value, list) else None, key,
                              positive=key != "length_um", nullable=True)
        for kind in ("packets", "cw"):
            records = edge.get(kind, [])
            if not isinstance(records, list):
                raise ValueError(f"invalid edge {kind}")
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError("invalid physical record")
                _reference(record.get("from"), assets, required=True)
                _reference(record.get("to"), assets, required=True)
                record_count = count if kind == "cw" else None
                if record_count is None:
                    _vector(record.get("jones"))
                else:
                    vectors = record.get("jones")
                    if not isinstance(vectors, list) or len(vectors) != record_count:
                        raise ValueError("Jones sample-array length mismatch")
                    for vector in vectors:
                        _vector(vector)
                    if record.get("samples") != data["samples"]:
                        raise ValueError("record samples differ from state samples")
                _sample_field(record.get("wavelength_nm"), record_count, "wavelength", positive=True)
                for key in ("t0", "t1"):
                    _sample_field(record.get(key), record_count, key, nullable=True)
                pairs = zip(record["t0"], record["t1"]) if record_count is not None else [(record["t0"], record["t1"])]
                if any(a is not None and b is not None and a > b for a, b in pairs):
                    raise ValueError("reversed physical times")
                if "reverse" in record and not isinstance(record["reverse"], bool):
                    raise ValueError("reverse must be a boolean")
                for key in ("width", "width_ps"):
                    if key in record:
                        _numeric(record[key], key, positive=True)
    for name in ("absorbed", "exits"):
        if not isinstance(data.get(name), list):
            raise ValueError(f"invalid {name}")
        for record in data[name]:
            if not isinstance(record, dict) or not all(isinstance(record.get(key), str) and record[key] for key in ("part", "port")):
                raise ValueError(f"invalid {name} part or port")
            _sample_field(record.get("power"), count, "sink power")
            _sample_field(record.get("wavelength_nm"), count, "sink wavelength", positive=True)
            _sample_field(record.get("t_ps"), count, "sink time", nullable=True)
            if name == "exits":
                _reference(record.get("id"), assets, required=True)
                _points(record.get("points"), "exit")
                if record.get("visual_only") is not True:
                    raise ValueError("exit geometry must be visual-only")
                _numeric(record.get("display_duration_s"), "exit display duration", positive=True)
                if count is None:
                    _vector(record.get("jones"))
                else:
                    if not isinstance(record.get("jones"), list) or len(record["jones"]) != count:
                        raise ValueError("exit Jones sample-array length mismatch")
                    for vector in record["jones"]:
                        _vector(vector)
    notices = data.get("warnings", [])
    if not isinstance(notices, list):
        raise ValueError("invalid exit warnings")
    for notice in notices:
        if not isinstance(notice, dict) or not all(isinstance(notice.get(key), str) and notice[key] for key in ("part", "port", "message")):
            raise ValueError("invalid named exit warning")
    if any(not any(notice["part"] == record["part"] and notice["port"] == record["port"] for notice in notices) for record in data["exits"]):
        raise ValueError("an exit requires a named warning")


def validate_document(data):
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("unsupported timeline version")
    _fields(data, "version view duration sections tracks style signal_state signal_states assets", "root")
    _json_values(data)
    if data["view"] not in ("1d", "2d"):
        raise ValueError("invalid view")
    _numeric(data["duration"], "duration")
    try:
        Style.from_json(data["style"])
    except (TypeError, KeyError, ValueError) as error:
        raise ValueError(f"invalid style: {error}") from None
    if not all(isinstance(data[key], dict) for key in ("assets", "signal_states")):
        raise ValueError("invalid assets or signal states")
    assets = data["assets"]
    if not isinstance(data["tracks"], list) or not isinstance(data["sections"], list):
        raise ValueError("tracks and sections must be lists")
    seen = set()
    previous = 0
    for section in data["sections"]:
        _fields(section, "id start end", "section")
        _identifier(section["id"], r"s[1-9][0-9]*", "section")
        if section["id"] in seen:
            raise ValueError("duplicate section id")
        seen.add(section["id"])
        _numeric(section["start"], "section start")
        _numeric(section["end"], "section end")
        if section["start"] < previous or section["end"] <= section["start"] or section["end"] > data["duration"]:
            raise ValueError("overlapping or reversed section")
        previous = section["end"]
    if "base" in data["signal_states"]:
        raise ValueError("base is a reserved signal-state id")
    states = {"base": data["signal_state"], **data["signal_states"]}
    for ref, state in states.items():
        if ref != "base":
            _identifier(ref, r"q(?:[2-9]|[1-9][0-9]+)", "state")
        _state(state, assets)
        if state["time_scale_s_per_ps"] != data["signal_state"]["time_scale_s_per_ps"]:
            raise ValueError("signal states must share one time scale")
    for track in data["tracks"]:
        _fields(track, "id type target start duration easing args", "track")
        _identifier(track["id"], r"t[1-9][0-9]*", "track")
        if track["id"] in seen:
            raise ValueError("duplicate track id")
        seen.add(track["id"])
        if not isinstance(track["type"], str) or track["type"] not in PRIMITIVES:
            raise ValueError("unknown primitive")
        if not isinstance(track["easing"], str) or track["easing"] not in EASINGS:
            raise ValueError("unknown easing")
        _numeric(track["start"], "track start")
        _numeric(track["duration"], "track duration")
        if track["start"] + track["duration"] > data["duration"] + 1e-12:
            raise ValueError("track exceeds timeline duration")
        if track["type"] in {"Set", "Sweep"}:
            if not isinstance(track["target"], str) or not track["target"]:
                raise ValueError("invalid parameter target")
        else:
            _reference(track["target"], assets)
        args = track["args"]
        if not isinstance(args, dict):
            raise ValueError("track args must be an object")
        for key in ("state", "terminal_state"):
            if key in args and (not isinstance(args[key], str) or args[key] not in states):
                raise ValueError(f"missing signal-state reference: {args[key]}")
        if track["type"] in {"Flow", "Sweep", "Plot"}:
            if "state" not in args:
                raise ValueError("light track requires a state reference")
            state = states[args["state"]]
            paths = args.get("paths", [])
            if not isinstance(paths, list):
                raise ValueError("paths must be a list")
            for path in paths:
                if not isinstance(path, str) or path not in state["edges"]:
                    raise ValueError(f"missing edge reference: {path}")
            for exit_id in args.get("exits", []):
                if not any(record.get("id") == exit_id for record in state["exits"]):
                    raise ValueError(f"missing exit reference: {exit_id}")
            if track["type"] == "Flow":
                if args.get("mode") != state["mode"] or not isinstance(args.get("settled"), bool):
                    raise ValueError("invalid Flow mode or settled flag")
                Style.from_json(args.get("style"))
    for asset_id, asset in assets.items():
        _identifier(asset_id, r"(?:text|plot):[1-9][0-9]*", "asset")
        if not isinstance(asset, dict):
            raise ValueError("invalid asset")
        if asset.get("kind") == "text":
            if not isinstance(asset.get("text"), str):
                raise ValueError("invalid text asset")
            _reference(asset.get("near"), assets)
        elif asset.get("kind") == "plot":
            x, y = asset.get("x"), asset.get("y")
            if not isinstance(x, list) or len(x) < 2 or not isinstance(y, list) or len(x) != len(y):
                raise ValueError("invalid plot sample lengths")
            _sample_field(x, len(x), "plot x", signed=True)
            _sample_field(y, len(x), "plot y")
            quantity = asset.get("quantity")
            if not isinstance(quantity, dict) or quantity.get("name") != "power":
                raise ValueError("invalid plot quantity")
            target = quantity.get("target")
            _reference(target, assets, required=True)
            if target.startswith(("route:", "beam:", "path:")) and not any(target in state["edges"] for state in states.values()):
                raise ValueError(f"missing quantity edge reference: {target}")
        else:
            raise ValueError("unknown asset kind")


@dataclass
class Track:
    id: str
    type: str
    target: str | None
    start: float
    duration: float
    easing: str
    args: dict


@dataclass
class Section:
    id: str
    start: float
    end: float


def expand(action, start):
    """Return scheduled descriptors and their end, without changing a timeline."""
    if isinstance(action, Action):
        if action.type == "Click":
            raise ValueError("Click cannot occur inside composition")
        if action.seconds is None:
            raise ValueError(f"{action.type}: seconds must be resolved")
        number(action.seconds, "seconds")
        return [(action, start)], start + action.seconds
    if not isinstance(action, Sequence):
        raise ValueError("play requires action descriptors")
    result, end = [], start
    for index, child in enumerate(action.children):
        child_start = start + index * action.lag if isinstance(action, Lagged) else end
        scheduled, child_end = expand(child, child_start)
        result.extend(scheduled)
        end = max(end, child_end)
    return result, end


class Timeline:
    def __init__(self, *, view="2d", style="photons"):
        if view not in ("1d", "2d"):
            raise ValueError("view must be 1d or 2d")
        self.view = view
        self.style = resolve_style(style).to_json()
        self.tracks: list[Track] = []
        self.sections: list[Section] = []
        self.assets: dict = {}
        self.signal_state = {
            "version": 1, "mode": "cw", "duration_ps": 0.0, "time_scale_s_per_ps": 1.0,
            "params": {}, "inputs": [], "edges": {}, "exits": [], "absorbed": [],
        }
        self.signal_states: dict = {}
        self._cursor = 0.0
        self._section_start = 0.0
        self._track_counter = 0
        self._section_counter = 0

    @property
    def cursor(self):
        return max(self._cursor, max((t.start + t.duration for t in self.tracks), default=0.0))

    @property
    def duration(self):
        return self.cursor

    def play(self, *actions):
        if any(isinstance(a, Action) and a.type == "Click" for a in actions):
            if len(actions) != 1:
                raise ValueError("Click must be played alone")
            return self.click()
        pending, end = [], self.cursor
        for action in actions:
            scheduled, action_end = expand(action, self.cursor)
            pending.extend(scheduled)
            end = max(end, action_end)
        tracks = []
        for index, (action, start) in enumerate(pending, start=1):
            if action.target is not None and not isinstance(action.target, str):
                raise ValueError("timeline targets must be bound strings")
            args = copy.deepcopy(action.args)
            json.dumps(args, allow_nan=False)
            tracks.append(Track(f"t{self._track_counter + index}", action.type, action.target,
                                float(start), float(action.seconds), action.easing, args))
        self.tracks.extend(tracks)
        self._track_counter += len(tracks)
        self._cursor = end
        return self

    def wait(self, seconds):
        return self.play(Wait(seconds))

    def click(self):
        if self.cursor > self._section_start:
            self._section_counter += 1
            self.sections.append(Section(f"s{self._section_counter}", self._section_start, self.cursor))
            self._section_start = self.cursor
        return self

    def to_json(self):
        sections = [asdict(section) for section in self.sections]
        if self.duration > self._section_start:
            sections.append({"id": f"s{self._section_counter + 1}",
                             "start": self._section_start, "end": self.duration})
        data = {
            "version": 1, "view": self.view, "duration": self.duration, "sections": sections,
            "tracks": [asdict(track) for track in self.tracks], "style": self.style,
            "signal_state": self.signal_state, "signal_states": self.signal_states, "assets": self.assets,
        }
        self._validate(data)
        return copy.deepcopy(data)

    _validate = staticmethod(validate_document)

    def dumps(self):
        return encode_document(self.to_json())

    @classmethod
    def from_json(cls, data):
        data = json.loads(data, object_pairs_hook=unique_object) if isinstance(data, str) else copy.deepcopy(data)
        cls._validate(data)
        result = cls(view=data["view"], style=resolve_style("photons"))
        result.style = data["style"]
        result.tracks = [Track(**track) for track in data["tracks"]]
        result.sections = [Section(**section) for section in data["sections"]]
        result._cursor = data["duration"]
        result._section_start = result.sections[-1].end if result.sections else 0.0
        result._track_counter = max((int(t.id[1:]) for t in result.tracks), default=0)
        result._section_counter = max((int(s.id[1:]) for s in result.sections), default=0)
        result.assets = data["assets"]
        result.signal_state = data["signal_state"]
        result.signal_states = data["signal_states"]
        return result

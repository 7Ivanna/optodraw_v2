"""Sample physical states and align their amplitudes without player physics."""

from copy import deepcopy

from .errors import AnimationError
from .graph import build_graph
from .primitives import ease, number, parameter
from .solver import Network
from .tables import compile_table, extent_time_ps, terminal_time_ps


def sample_values(start, stop, *, samples=120, easing="linear"):
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 2:
        raise ValueError("samples must be an integer of at least two")
    start = number(start, "start", minimum=-float("inf"))
    stop = number(stop, "stop", minimum=-float("inf"))
    return [start + (stop - start) * ease(easing, index / (samples - 1)) for index in range(samples)]


def _channels(graph, params, inputs):
    network = Network(graph, params, inputs)
    emissions = list(network.emissions()) + list(network.injections())
    groups = {}
    for index, (_, emission) in enumerate(emissions):
        groups.setdefault(emission.wavelength_nm, []).append(index)
    partition = tuple(tuple(indices) for indices in groups.values())
    channels = {wavelength: f"source:{indices[0] + 1}" for wavelength, indices in groups.items()}
    return partition, channels, emissions


def _channel_wavelengths(groups, channel):
    return [next(wavelength for wavelength, name in group.items() if name == channel) for group in groups]


def _series(record, param, values, channel, count, groups):
    result = deepcopy(record)
    result.update(channel=channel, param=param, samples=list(values),
                  wavelength_nm=_channel_wavelengths(groups, channel), jones=[[0.0] * 4 for _ in values],
                  t0=[None] * count, t1=[None] * count)
    return result


def _terminals(states, groups, name, param, values):
    union = {}
    count = len(values)
    for index, (state, channels) in enumerate(zip(states, groups)):
        for record in state.get(name, []):
            channel = channels[record["wavelength_nm"]]
            key = record["part"], record["port"], channel
            if key not in union:
                result = deepcopy(record)
                result.update(channel=channel, param=param, samples=list(values),
                              wavelength_nm=_channel_wavelengths(groups, channel), power=[0.0] * count, t_ps=[None] * count)
                if "jones" in record:
                    result["jones"] = [[0.0] * 4 for _ in values]
                union[key] = result
            result = union[key]
            if "points" in record and result["points"] != record["points"]:
                raise AnimationError(f"{record['part']}: parameter {param} changes exit geometry")
            result["wavelength_nm"][index] = record["wavelength_nm"]
            result["power"][index] += record["power"]
            result["t_ps"][index] = record["t_ps"]
            if "jones" in record:
                result["jones"][index] = [a + b for a, b in zip(result["jones"][index], record["jones"])]
    return list(union.values())


def compile_sweep(scene, param, values, *, params=None, inputs=(), floor=None, strict=False):
    parameter(param)
    values = [number(value, "sample", minimum=-float("inf")) for value in values]
    if len(values) < 2:
        raise ValueError("a sweep requires at least two samples")
    inputs = tuple(inputs)
    graph = build_graph(scene)
    states, groups = [], []
    partition = None
    for value in values:
        sample_params = dict(params or {})
        sample_params[param] = value
        current, channels, emissions = _channels(graph, sample_params, inputs)
        if partition is not None and current != partition:
            sid = emissions[0][0] if emissions else "scene"
            raise AnimationError(f"{sid}: parameter {param} changes coherent wavelength groups")
        partition = current
        states.append(compile_table(scene, mode="cw", params=sample_params, inputs=inputs,
                                    floor=floor, strict=strict))
        groups.append(channels)
    count = len(values)
    edges, series, geometry = {}, {}, {}
    for index, (state, channels) in enumerate(zip(states, groups)):
        for edge_id, edge in state["edges"].items():
            if edge_id not in edges:
                edges[edge_id] = deepcopy(edge)
                edges[edge_id]["cw"] = []
                geometry[edge_id] = [None] * count
            elif edges[edge_id]["points"] != edge["points"]:
                raise AnimationError(f"{edge_id}: parameter {param} changes edge geometry")
            geometry[edge_id][index] = edge
            for record in edge.get("cw", []):
                channel = channels[record["wavelength_nm"]]
                key = edge_id, record["from"], record["to"], channel
                if key not in series:
                    series[key] = _series(record, param, values, channel, count, groups)
                    edges[edge_id]["cw"].append(series[key])
                result = series[key]
                result["wavelength_nm"][index] = record["wavelength_nm"]
                result["jones"][index] = [a + b for a, b in zip(result["jones"][index], record["jones"])]
                for timing in ("t0", "t1"):
                    previous = result[timing][index]
                    result[timing][index] = record[timing] if previous is None else (
                        min(previous, record[timing]) if timing == "t0" else max(previous, record[timing]))
    for edge_id, samples in geometry.items():
        for key in ("length_um", "group_index", "ng"):
            if any(sample is not None and key in sample for sample in samples):
                values_at = [sample.get(key) if sample is not None else None for sample in samples]
                present = [value for value in values_at if value is not None]
                if present and any(value != present[0] for value in present):
                    edges[edge_id][key] = values_at
    notices = {}
    for state in states:
        for notice in state.get("warnings", []):
            notices[(notice["part"], notice["port"])] = deepcopy(notice)
    return {"version": 1, "mode": "cw", "param": param, "samples": values,
            "params": deepcopy(params or {}), "inputs": [item.to_json() for item in inputs],
            "duration_ps": max(extent_time_ps(state) for state in states),
            "terminal_time_ps": max(terminal_time_ps(state) for state in states),
            "edges": edges, "absorbed": _terminals(states, groups, "absorbed", param, values),
            "exits": _terminals(states, groups, "exits", param, values), "warnings": list(notices.values())}


def plot_values(table, quantity):
    if quantity.get("name") != "power":
        raise ValueError("only solved power quantities are supported")
    target = quantity["target"]
    count = len(table["samples"])
    result = [0.0] * count
    fields = target.split(":")
    sinks = [record for record in table["absorbed"]
             if ((fields[0] == "part" and record["part"] == fields[1]) or
                 (fields[0] == "port" and f"port:{record['part']}:{record['port']}" == target))]
    if sinks:
        for record in sinks:
            result = [a + b for a, b in zip(result, record["power"])]
        return result
    records = []
    if target in table["edges"]:
        records = table["edges"][target].get("cw", [])
    elif fields[0] in {"part", "port"}:
        all_records = [record for edge in table["edges"].values() for record in edge.get("cw", [])]
        prefix = f"port:{fields[1]}:" if fields[0] == "part" else target
        incoming = [record for record in all_records if
                    (record["to"].startswith(prefix) if fields[0] == "part" else record["to"] == prefix)]
        records = incoming or [record for record in all_records if
                               (record["from"].startswith(prefix) if fields[0] == "part" else record["from"] == prefix)]
    for record in records:
        result = [a + sum(float(value) ** 2 for value in vector) for a, vector in zip(result, record["jones"])]
    return result

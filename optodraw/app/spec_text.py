"""The scene spec as YAML text for the editor's Code tab, and back.

The text is the spec the session holds, less the data the editor makes from it: the drawn fragment of each inset,
the source record of each inset that reads a file or holds a scene, and the rays that Trace draws. They come back by
id when the text is read. Reading uses the safe loader only, so no Python runs. A source of a kind on the safe list
(words, a mathtext formula, an empty box, a timing, a scene) builds when the text changes it; that reads no file and
runs no tool."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import yaml

from optodraw.app.session import _entries, inset_fragment, new_record, print_scale

HEADER = ("# The scene spec. Cmd+Enter (Ctrl+Enter) applies it.\n"
          "# Left out: the drawing of each inset, the source of a file, GDS or scene inset (double-click a scene inset "
          "to edit its scene), and the rays that Trace draws.\n")
INSET_KEYS = ("source", "fragment")                 # an inset's record and its last drawing
SAFE_KINDS = ("Text", "Equation", "EmptyBox", "Timing", "SceneView")    # the sources the text may name: data only
SHOWN_KINDS = ("Text", "Equation", "EmptyBox", "Timing")                # and shows: a scene opens by double-click
LINKS = ("routes", "beams")
LISTS = ("components", *LINKS, "children")          # the lists whose entries carry an id


class SpecTextError(ValueError):
    """Text that does not read as a spec. ``line`` is its line, counted from 1, or None."""

    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.line = line


class _Dumper(yaml.SafeDumper):
    """Block style, with a list of plain values (a point, a size) on one line."""


def _list(dumper: yaml.SafeDumper, value: list[Any]) -> yaml.Node:
    flat = all(not isinstance(item, (list, dict)) for item in value)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", value, flow_style=flat)


_Dumper.add_representer(list, _list)


class _Loader(yaml.SafeLoader):
    """The safe loader, with a date left as text: the spec is JSON."""


_Loader.yaml_implicit_resolvers = {
    first: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()}


def _traced(beam: Any) -> bool:
    return isinstance(beam, dict) and bool(beam.get("traced_from"))


def spec_text(spec: dict[str, Any]) -> dict[str, Any]:
    """``{"text": ..., "blocks": {id: [first, last]}}``: the spec as YAML, and the lines of each entry that has an id
    (a part, a link, a child of a group), counted from 1."""

    shown = json.loads(json.dumps(spec, default=_number))   # a preset's numpy numbers become plain numbers
    for entry in _entries(shown.get("components")):
        if entry.get("type") == "Inset":
            entry.pop("fragment", None)
            if not (isinstance(entry.get("source"), dict) and entry["source"].get("kind") in SHOWN_KINDS):
                entry.pop("source", None)
    if isinstance(shown.get("beams"), list):
        shown["beams"] = [beam for beam in shown["beams"] if not _traced(beam)]
    text = HEADER + _dumped(shown, allow_unicode=True)
    if yaml.load(text, Loader=_Loader) != shown:        # a character YAML reads as a line break (U+0085): escape all
        text = HEADER + _dumped(shown, allow_unicode=False)
    return {"text": text, "blocks": _blocks(text)}


def _number(value: Any) -> Any:
    """A numpy number as a plain one, for JSON; anything else as its text."""

    return value.item() if hasattr(value, "item") else str(value)


def _dumped(shown: dict[str, Any], *, allow_unicode: bool) -> str:
    return yaml.dump(shown, Dumper=_Dumper, sort_keys=False, allow_unicode=allow_unicode, width=110)


def _key(name: Any) -> Any:
    return name.value if isinstance(name, yaml.ScalarNode) else None


def _last(node: yaml.Node) -> int:
    """The last line of ``node``, from 1. A block ends where the next token starts, on a later line, so the last line
    of a block is the last line of its last value."""

    if isinstance(node, (yaml.MappingNode, yaml.SequenceNode)) and node.value and not node.flow_style:
        last = node.value[-1]
        return _last(last[1] if isinstance(node, yaml.MappingNode) else last)
    end = node.end_mark
    return end.line + (1 if end.column else 0)


def _blocks(text: str) -> dict[str, list[int]]:
    blocks: dict[str, list[int]] = {}

    def walk(node: yaml.Node, key: Any = None) -> None:
        if isinstance(node, yaml.MappingNode):
            for name, value in node.value:
                walk(value, _key(name))
        elif isinstance(node, yaml.SequenceNode) and key in LISTS:
            for item in node.value:
                if isinstance(item, yaml.MappingNode):
                    ident = next((value.value for name, value in item.value
                                  if _key(name) == "id" and isinstance(value, yaml.ScalarNode)), None)
                    if ident:
                        blocks[str(ident)] = [item.start_mark.line + 1, _last(item)]
                    walk(item)

    walk(yaml.compose(text, Loader=yaml.SafeLoader))
    return blocks


def _starts(text: str) -> dict[str, list[int]]:
    """The first line of each entry of the top-level lists, by list name and place."""

    root = yaml.compose(text, Loader=yaml.SafeLoader)
    starts: dict[str, list[int]] = {}
    for name, value in root.value if isinstance(root, yaml.MappingNode) else ():
        if _key(name) in LISTS and isinstance(value, yaml.SequenceNode):
            starts[_key(name)] = [item.start_mark.line + 1 for item in value.value]
    return starts


def spec_from_text(text: str, held: dict[str, Any]) -> dict[str, Any]:
    """The spec ``text`` gives, with what the text leaves out taken from ``held`` (the spec the session holds): each
    inset's source and drawing by its id, and the traced rays at their places among the beams. An inset's ``source``
    in the text is a kind of :data:`SAFE_KINDS`: a new or changed one builds once, an unchanged one keeps its drawing.
    Another kind, a drawing in the text, a new inset with no source and a source that does not build raise
    :class:`SpecTextError` at the inset's line."""

    try:
        for event in yaml.parse(text, Loader=_Loader):  # an alias shares one value, and a few nest to any size
            if isinstance(event, yaml.AliasEvent):
                raise SpecTextError("the text uses an alias (*name): write the value out", event.start_mark.line + 1)
        spec = yaml.load(text, Loader=_Loader)          # safe: plain data only, no Python object
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        words = " ".join(part for part in (error.context, error.problem) if part)
        raise SpecTextError(words or "the text is not YAML", None if mark is None else mark.line + 1) from error
    except yaml.YAMLError as error:
        raise SpecTextError(f"the text is not YAML: {error}") from error
    if not isinstance(spec, dict):
        raise SpecTextError("the text is one mapping: title, width, height, components, routes, beams", 1)
    try:
        json.dumps(spec, allow_nan=False)
    except ValueError as error:
        raise SpecTextError("a number is not finite (.nan or .inf): give a plain number") from error
    except TypeError as error:
        raise SpecTextError(f"a value is not text, a number, a list or a mapping ({error}): put it in quotes") from error
    blocks = _blocks(text)
    seen: set[Any] = set()
    links = [entry for key in LINKS if isinstance(spec.get(key), list) for entry in spec[key]]
    for entry in [*_entries(spec.get("components")), *links]:
        ident = entry.get("id") if isinstance(entry, dict) else None
        if ident is not None and ident in seen:
            raise SpecTextError(f"the id {ident!r} is used twice: give each part and link its own id",
                                blocks.get(str(ident), [None])[0])
        seen.add(ident)
    old = {entry.get("id"): entry for entry in _entries(held.get("components")) if entry.get("type") == "Inset"}
    for entry in _entries(spec.get("components")):
        if entry.get("type") != "Inset":
            continue
        line = blocks.get(str(entry.get("id")), [None])[0]
        if "fragment" in entry:
            raise SpecTextError("the drawing of an inset stays out of the text: the editor draws it from the source",
                                line)
        was, source = old.get(entry.get("id")), entry.get("source")
        if source is None:
            if was is None:
                raise SpecTextError(f"a new inset in the text names its source, one of {', '.join(SAFE_KINDS)}: a "
                                    "file, a GDS view or a 3D view is made in the palette or in Python", line)
            entry.update({key: deepcopy(was[key]) for key in INSET_KEYS if key in was})
            continue
        kind = source.get("kind") if isinstance(source, dict) else None
        if kind not in SAFE_KINDS:
            raise SpecTextError(f"the text names an inset source of {', '.join(SAFE_KINDS)} only, not {kind}: a file, "
                                "a GDS view or a 3D view is made in the palette or in Python", line)
        entry["source"] = new_record(kind, source)
        if was is not None and was.get("source") == entry["source"]:
            if "fragment" in was:                           # unchanged: no build, as a loaded inset never rebuilds
                entry["fragment"] = deepcopy(was["fragment"])
            continue
        try:
            entry["fragment"] = inset_fragment(entry, print_scale(spec, was or entry), None)
        except Exception as error:                          # typed values can fail in any way: say how, and where
            raise SpecTextError(f"the inset does not build: {error}", line) from error
    beams = spec.get("beams")
    if isinstance(beams, list) and not any(_traced(beam) for beam in beams):
        given, merged = list(beams), []
        for beam in held.get("beams") or []:                # each traced ray keeps its place among the others
            if _traced(beam):
                merged.append(deepcopy(beam))
            elif given:
                merged.append(given.pop(0))
        spec["beams"] = merged + given
    return spec


def error_line(spec: dict[str, Any], text: str) -> int | None:
    """The first line in ``text`` of the first part, route or beam of ``spec`` (read from ``text``) that does not
    build, found by halving. None when the fault is in no entry: the scene's own fields, or nothing at all."""

    from optodraw.schema import scene_from_spec

    rest = {key: value for key, value in spec.items() if key not in ("components", *LINKS)}
    lists = {key: spec.get(key) if isinstance(spec.get(key), list) else [] for key in ("components", *LINKS)}

    def builds(**given: list[Any]) -> bool:
        try:
            scene_from_spec(deepcopy({**rest, **{key: [] for key in LINKS}, **given}))
        except Exception:
            return False
        return True

    if not builds(components=[]):
        return None
    starts, before = _starts(text), {}
    for key, items in lists.items():
        if not builds(**before, **{key: items}):
            low, high = 1, len(items)                       # the shortest head of the list that does not build
            while low < high:
                middle = (low + high) // 2
                low, high = (middle + 1, high) if builds(**before, **{key: items[:middle]}) else (low, middle)
            bad = items[low - 1]
            if _traced(bad):
                return None
            place = [item for item in items if not _traced(item)].index(bad) if key == "beams" else low - 1
            lines = starts.get(key, [])
            return lines[place] if place < len(lines) else None
        before[key] = items
    return None

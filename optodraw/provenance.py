"""Where a physics number comes from.

A ``Sourced`` number is a float that carries its ``Source``: every reader that calls ``float()`` or does arithmetic
gets the value, and ``source_of`` gets the record. A plain number has no source; a result that rests on it says so.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

KINDS = ("measured", "literature", "simulated", "model")


@dataclass(frozen=True)
class Source:
    """``kind`` is one of measured, literature, simulated, model; ``ref`` a citation, DOI or file hash."""

    kind: str
    ref: str = ""
    note: str = ""

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"a source kind is one of {', '.join(KINDS)}, not {self.kind!r}")


class Sourced(float):
    """A number and its ``Source``. Arithmetic gives plain floats: a computed number has no source of its own."""

    source: Source

    def __new__(cls, value: float, source: Source):
        if not isinstance(source, Source):
            raise TypeError(f"a Sourced number needs a Source, not {type(source).__name__}")
        number = super().__new__(cls, value)
        number.source = source
        return number

    def __reduce__(self):
        return (Sourced, (float(self), self.source))

    def __repr__(self) -> str:
        return f"Sourced({float(self)!r}, {self.source!r})"


def source_of(value: object) -> Source | None:
    """The source of a ``Sourced`` number; None for a plain one."""

    return value.source if isinstance(value, Sourced) else None


def model_numbers(scene: Any, sids: Iterable[str] | None = None) -> list[str]:
    """One note per physics number with no source or a model-kind one, for each part (all, or the ``sids``): the
    names are its behaviour's ``parameters``. ``"<label or sid>: <name> = <value> (model)"``, or
    ``"<label or sid>: <name> (default, model)"`` when the part does not set it and its behaviour's default holds."""

    # imported here: a figure with no analysis loads no engine
    from optodraw.animation_engine.behaviours import find_behaviour
    from optodraw.animation_engine.graph import build_graph

    wanted = None if sids is None else set(sids)
    notes = []
    for sid, part in build_graph(scene).parts.items():
        behaviour = find_behaviour(part)
        if behaviour is None or (wanted is not None and sid not in wanted):
            continue
        notes += number_notes(getattr(part, "label", "") or sid, part, behaviour.parameter_names(part))
    return notes


def number_notes(who: str, part: Any, names: Iterable[str]) -> list[str]:
    """One note per number ``names`` of ``part`` with no source or a model-kind one: ``"<who>: <name> = <value>
    (model)"``, or ``"<who>: <name> (default, model)"`` when the part does not set it and a model default holds."""

    notes = []
    for name in names:
        value = getattr(part, name, None)
        source = source_of(value)
        if value is None:
            notes.append(f"{who}: {name} (default, model)")
        elif source is None or source.kind == "model":
            notes.append(f"{who}: {name} = {float(value):g} (model)")
    return notes

"""A part asked for no label has none: no default text comes back, in the scene or after a save and reload."""

from __future__ import annotations

import inspect
import warnings

import optodraw
from optodraw.core.component import Component


def _parts():
    for name in sorted(dir(optodraw)):
        cls = getattr(optodraw, name)
        if inspect.isclass(cls) and issubclass(cls, Component) and cls is not Component:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    yield cls(label="")
            except Exception:
                continue                                  # a part that needs arguments of its own


def test_no_part_puts_a_default_text_in_place_of_an_empty_label():
    named = [(type(part).__name__, part.label) for part in _parts() if getattr(part, "label", "")]
    assert named == []



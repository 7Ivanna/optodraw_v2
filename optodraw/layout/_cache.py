"""Private state keys for conservative layout cache invalidation."""

from __future__ import annotations

import copyreg
import io
import pickle

from optodraw.core.component import Component


_CACHE_FIELDS = frozenset({"_layout_bounds_cache", "_routing_obstacle_cache"})


def _instance_state(component, *, ancestor: bool = False):
    excluded = _CACHE_FIELDS | {"_parent"}
    if ancestor:
        excluded = excluded | {"children"}
    return {key: value for key, value in vars(component).items() if key not in excluded}


class _StatePickler(pickle.Pickler):
    def reducer_override(self, value):
        if not isinstance(value, Component):
            return NotImplemented
        parents = []
        parent = getattr(value, "_parent", None)
        while parent is not None:
            parents.append(_instance_state(parent, ancestor=True))
            parent = getattr(parent, "_parent", None)
        # Nested endpoint references must not serialize their scene or caches.
        return (copyreg.__newobj__, (type(value),), (_instance_state(value), parents))


def _component_state(component, contexts: dict | None = None) -> bytes | None:
    """Capture mutable parameters and ancestor context without serializing caches.

    Nested dictionaries, lists, transforms, and arrays retain their full values.
    Values that cannot be serialized keep the original uncached behavior.
    The bytes stay private and are never deserialized or exported.
    """

    try:
        context = []
        parent = getattr(component, "_parent", None)
        while parent is not None:
            identity = id(parent)
            if contexts is not None and identity in contexts:
                state = contexts[identity]
            else:
                state = _instance_state(parent, ancestor=True)
                if contexts is not None:
                    contexts[identity] = state
            context.append(state)
            parent = getattr(parent, "_parent", None)
        methods = tuple(id(getattr(type(component), name, None)) for name in ("geometry_2d", "geometry_3d", "symbol_2d", "symbol_1d"))
        output = io.BytesIO()
        _StatePickler(output, protocol=5).dump((_instance_state(component), context, methods))
        return output.getvalue()
    except Exception:
        return None

"""The public API is a snapshot, and internal work is not allowed to move it.

``optodraw.__all__`` and the keyword arguments of everything in it are what a
user's script depends on. Refactoring is free to move any of the code behind
them; it is not free to rename ``focal_length`` or drop ``Periscope``, and the
difference is easy to miss halfway through splitting a 4,500-line module.

The snapshot lives in ``tests/public_api.json``. Adding a name or an argument
never fails a test: that is how the library grows. Removing or renaming one
fails, with the command to update the snapshot on purpose:

    python tests/test_public_api.py --update
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import optodraw

SNAPSHOT = Path(__file__).parent / "public_api.json"


def _signature(obj) -> list[str]:
    """The keyword arguments a caller can pass, in order.

    ``self`` and ``**kwargs`` are dropped: the first is not a caller's business
    and the second is a promise to accept anything, which nothing can break.
    """

    target = obj.__init__ if inspect.isclass(obj) else obj
    try:
        parameters = inspect.signature(target).parameters
    except (TypeError, ValueError):  # pragma: no cover - C-level callables
        return []
    return [
        name
        for name, parameter in parameters.items()
        if name != "self" and parameter.kind is not inspect.Parameter.VAR_KEYWORD
    ]


def current_api() -> dict[str, list[str]]:
    """Every public name, mapped to the arguments it takes."""

    api: dict[str, list[str]] = {}
    for name in optodraw.__all__:
        obj = getattr(optodraw, name, None)
        if obj is None:
            continue
        api[name] = _signature(obj) if callable(obj) else []
    return api


def _load() -> dict[str, list[str]]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_the_snapshot_covers_what_the_package_exports():
    """A name in __all__ that does not resolve is already broken for users."""

    missing = [name for name in optodraw.__all__ if getattr(optodraw, name, None) is None]
    assert not missing, f"__all__ promises names that do not exist: {missing}"


def test_no_public_name_disappears():
    gone = sorted(set(_load()) - set(current_api()))
    assert not gone, (
        f"{len(gone)} public name(s) removed: {gone[:10]}\n"
        "Users import these. Keep them, or deprecate for a release first.\n"
        "If the removal is deliberate: python tests/test_public_api.py --update"
    )


def test_no_public_argument_is_renamed_or_dropped():
    snapshot, current = _load(), current_api()
    broken = []
    for name, arguments in snapshot.items():
        if name not in current:
            continue  # the test above owns that failure
        lost = [a for a in arguments if a not in current[name]]
        if lost:
            broken.append(f"{name}({', '.join(lost)})")
    assert not broken, (
        f"{len(broken)} public signature(s) lost arguments: {broken[:10]}\n"
        "Adding arguments is fine; renaming or dropping one breaks callers.\n"
        "If the change is deliberate: python tests/test_public_api.py --update"
    )


def test_the_snapshot_is_not_stale_in_the_boring_way():
    """New public names are welcome, but the snapshot should not drift for long."""

    added = sorted(set(current_api()) - set(_load()))
    if added:
        pytest.skip(f"{len(added)} new public name(s) since the snapshot: {added[:5]}")


if __name__ == "__main__":  # pragma: no cover - maintenance entry point
    import sys

    if "--update" in sys.argv:
        SNAPSHOT.write_text(json.dumps(current_api(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {SNAPSHOT} with {len(current_api())} public names")
    else:
        print(__doc__)

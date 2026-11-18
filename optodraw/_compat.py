"""Compatibility helpers: deprecate without breaking.

Renames go through :func:`deprecated`, which keeps the old name working for
two releases while pointing callers at the replacement. Removal happens only
after the sunset version passes, and the public API snapshot test enforces
the timeline: dropping a name early fails the suite.
"""

from __future__ import annotations

import functools
import warnings
from typing import Any, Callable, TypeVar

_F = TypeVar("_F", bound=Callable[..., Any])


def deprecated(name: str, *, replacement: str, sunset: str) -> Callable[[_F], _F]:
    """Mark ``name`` as deprecated in favor of ``replacement``.

    The decorated object keeps working and emits one :class:`DeprecationWarning`
    per call site naming the ``sunset`` release that removes it.
    """

    def _wrap(func: _F) -> _F:
        @functools.wraps(func)
        def _inner(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(
                f"{name} is deprecated and will be removed in {sunset}; "
                f"use {replacement} instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return func(*args, **kwargs)

        return _inner  # type: ignore[return-value]

    return _wrap

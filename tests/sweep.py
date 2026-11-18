"""One test over many cases: it runs a check on each case and names every failing case in one message."""

from __future__ import annotations

from collections.abc import Callable, Iterable

import pytest


def sweep(check: Callable[..., object], cases: Iterable) -> None:
    """Run ``check(*case)`` for each case (a bare value is one argument). A case that skips itself is passed over;
    an assertion or any other error is that case's failure, and the sweep goes on to the next."""

    cases = list(cases)
    failures = []
    for case in cases:
        if hasattr(case, "values") and hasattr(case, "marks"):     # a pytest.param: its values are the case
            case = tuple(case.values)
        args = case if isinstance(case, tuple) else (case,)
        try:
            check(*args)
        except pytest.skip.Exception:
            continue
        except Exception as error:
            failures.append(f"{args}: {type(error).__name__}: {error}"[:500])
    assert not failures, f"{len(failures)} of {len(cases)} cases fail:\n" + "\n".join(failures)

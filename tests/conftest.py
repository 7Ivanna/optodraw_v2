"""Shared test fixtures/config.

Point editor workspaces at a throwaway dir so the suite never writes to the
real ``~/.optodraw``. Set here (conftest is imported before test modules) so it
applies before ``optodraw.app`` creates its module-level session store.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# A workspace this run makes is removed at the end; one you set in the environment stays.
_OWN_WORKSPACE = None if "OPTODRAW_WORKSPACE_DIR" in os.environ else tempfile.mkdtemp(prefix="optodraw_ws_test_")
if _OWN_WORKSPACE:
    os.environ["OPTODRAW_WORKSPACE_DIR"] = _OWN_WORKSPACE
# A test must not start LaTeX by accident. A test that wants a compile sets this to "1".
os.environ.setdefault("OPTODRAW_SYMBOL_COMPILE", "0")


@pytest.fixture
def assert_1d_symbol():
    """A part's 1D symbol is a drawing that carries the part's ports: its own symbol or the labeled block."""

    from optodraw.symbols import lookup

    def check(component) -> None:
        symbol = lookup(component)
        assert symbol.svg.startswith("<svg") and symbol.width > 0 and symbol.height > 0
        assert {name: port.kind for name, port in symbol.ports.items()} == {
            name: port.kind for name, port in component.ports().items()
        }

    return check


def pytest_sessionfinish(session, exitstatus):
    if _OWN_WORKSPACE:
        shutil.rmtree(_OWN_WORKSPACE, ignore_errors=True)


SLOW_LIST = Path(__file__).with_name("slow_tests.txt")


def pytest_collection_modifyitems(config, items):
    """Three runs. The default run leaves out the tests that took 1 s or more (``slow_tests.txt``, written by
    ``scripts/slow_tests.py`` from a timed run): about 6 % of the tests and 90 % of the time. ``OPTODRAW_FULL=1``,
    the run before a merge, keeps them. ``OPTODRAW_SLOW=1`` also runs the tests marked ``slow``, which take minutes."""

    everything = os.environ.get("OPTODRAW_SLOW") == "1"
    if not everything:
        skip = pytest.mark.skip(reason="slow: set OPTODRAW_SLOW=1 to run it")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip)
    if everything or os.environ.get("OPTODRAW_FULL") == "1":
        return
    listed = {line.strip() for line in SLOW_LIST.read_text(encoding="utf-8").splitlines()
              if line.strip() and not line.startswith("#")}
    left_out = [item for item in items if item.nodeid in listed]
    if left_out:
        config.hook.pytest_deselected(items=left_out)
        items[:] = [item for item in items if item.nodeid not in listed]

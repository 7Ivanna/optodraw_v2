"""Write tests/slow_tests.txt from a timed run: the tests whose setup, call and teardown took 1 s or more.

    OPTODRAW_FULL=1 python -m pytest tests -q --durations=0 > timed.log
    python scripts/slow_tests.py timed.log

The default run skips the listed tests; OPTODRAW_FULL=1, the run before a merge, runs them (tests/conftest.py).
"""

from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

LIMIT = 1.0                                   # seconds
LINE = re.compile(r"^([0-9.]+)s (?:setup|call|teardown) +(\S+)$")
OUT = Path(__file__).resolve().parents[1] / "tests" / "slow_tests.txt"


def slow(log: str, limit: float = LIMIT) -> list[str]:
    """The node ids in a ``--durations=0`` log whose phases add up to ``limit`` seconds or more."""

    total: dict[str, float] = collections.defaultdict(float)
    for line in log.splitlines():
        match = LINE.match(line.strip())
        if match:
            total[match.group(2)] += float(match.group(1))
    return sorted(node for node, seconds in total.items() if seconds >= limit)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    nodes = slow(Path(argv[1]).read_text(encoding="utf-8", errors="replace"))
    if not nodes:
        print("no timed tests in that log: run pytest with --durations=0")
        return 1
    head = (f"# The tests that took {LIMIT:g} s or more (setup, call and teardown) in a timed run, one node id a line.\n"
            "# The default run skips them; OPTODRAW_FULL=1, the run before a merge, runs them. Made by\n"
            "# scripts/slow_tests.py from a pytest log with --durations=0: run it again when the tests change.\n")
    OUT.write_text(head + "\n".join(nodes) + "\n", encoding="utf-8")
    print(f"{len(nodes)} tests -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

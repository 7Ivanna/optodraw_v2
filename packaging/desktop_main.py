"""Entry point for native desktop bundles (PyInstaller / Briefcase).

Launches the optodraw editor in a native PyWebView window (no browser tab). The
FastAPI server runs in a background thread; see ``optodraw.app.launcher``. Build
instructions live in ``packaging/README.md``.
"""

from __future__ import annotations

import sys


def run() -> int:
    from optodraw.app.launcher import main

    # A double-click gets the native window; a command line gets what it asked
    # for. Hard-coding ["--desktop"] threw every argument away, so the frozen
    # app could not be told a port, could not be started headless, and could not
    # even answer --help — which is also why nothing could smoke-test it.
    args = list(sys.argv[1:])
    if not {"--desktop", "--no-browser", "--hosted", "--help", "-h"} & set(args):
        args.insert(0, "--desktop")
    return main(args)


if __name__ == "__main__":
    sys.exit(run())

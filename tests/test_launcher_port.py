"""The editor has to start even when port 8000 is already taken."""

from __future__ import annotations

import socket

import pytest

from optodraw.app import launcher


@pytest.fixture
def held_port():
    """Hold a real listening socket, the way another dev server would."""

    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    yield holder.getsockname()[1]
    holder.close()


def test_free_port_reads_as_free():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    assert launcher._port_is_free("127.0.0.1", port)


def test_busy_port_reads_as_busy(held_port):
    assert not launcher._port_is_free("127.0.0.1", held_port)


def test_default_walks_past_a_busy_port(monkeypatch, held_port):
    monkeypatch.setattr(launcher, "DEFAULT_PORT", held_port)
    assert launcher._resolve_port("127.0.0.1", None) == held_port + 1


def test_explicit_port_is_never_moved(held_port):
    # An explicit --port is a decision: the bind failure belongs to the user,
    # not to a silent relocation onto some other port.
    assert launcher._resolve_port("127.0.0.1", held_port) == held_port


def test_parser_leaves_the_port_unresolved_by_default():
    assert launcher._build_parser().parse_args([]).port is None
    assert launcher._build_parser().parse_args(["--port", "9100"]).port == 9100

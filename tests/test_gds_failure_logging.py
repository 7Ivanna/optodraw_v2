"""GDS import failures must be visible.

``load_gds_layout`` helpers return ``None`` on malformed input so callers can
fall back, but silence made a bad file indistinguishable from an empty one.
The failures now carry a logger warning; these tests pin that contract.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

gdstk = pytest.importorskip("gdstk")

from optodraw.gds.layout import (  # noqa: E402
    load_bounds_from_path,
    load_gds_geometry_from_path,
)


def _corrupt_gds(tmp_path: Path) -> Path:
    path = tmp_path / "broken.gds"
    path.write_bytes(b"not-a-gds-file")
    return path


class TestGdsFailureLogging:
    def test_corrupt_file_returns_none_and_warns_for_geometry(self, tmp_path, caplog):
        path = _corrupt_gds(tmp_path)
        with caplog.at_level(logging.WARNING, logger="optodraw.gds.layout"):
            result = load_gds_geometry_from_path(str(path), None, scale=1.0)
        assert result is None
        assert any("could not read geometry" in record.message for record in caplog.records)

    def test_corrupt_file_returns_none_and_warns_for_bounds(self, tmp_path, caplog):
        path = _corrupt_gds(tmp_path)
        with caplog.at_level(logging.WARNING, logger="optodraw.gds.layout"):
            result = load_bounds_from_path(str(path), None, scale=1.0)
        assert result is None
        assert any("could not read bounds" in record.message for record in caplog.records)

    def test_valid_sample_file_stays_silent(self, caplog):
        asset = Path(__file__).resolve().parents[1] / "examples" / "assets" / "demo_mask.gds"
        if not asset.is_file():
            pytest.skip("sample GDS not present")
        with caplog.at_level(logging.WARNING, logger="optodraw.gds.layout"):
            geometry = load_gds_geometry_from_path(str(asset), "DEMO_MASK", scale=1.0)
        assert geometry is not None
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

"""Optical signals: a Jones amplitude (Ex, Ey) as a complex 2-vector; 2 x 2 Jones matrices."""

from __future__ import annotations

import math

import numpy as np

C_UM_PER_PS = 299.792458                # the speed of light in um per ps


def jones(ex: complex, ey: complex = 0.0) -> np.ndarray:
    return np.array([ex, ey], dtype=complex)


def linear(angle_deg: float, amplitude: float = 1.0) -> np.ndarray:
    a = math.radians(angle_deg)
    return jones(amplitude * math.cos(a), amplitude * math.sin(a))


def power(vector: np.ndarray) -> float:
    return float(np.vdot(vector, vector).real)


def scalar(value: complex) -> np.ndarray:
    """A polarisation-independent 2 x 2 matrix: ``value`` times the identity."""

    return np.eye(2, dtype=complex) * value


def to_json(vector: np.ndarray) -> list[float]:
    return [float(vector[0].real), float(vector[0].imag), float(vector[1].real), float(vector[1].imag)]


def from_json(values: list[float]) -> np.ndarray:
    return jones(complex(values[0], values[1]), complex(values[2], values[3]))

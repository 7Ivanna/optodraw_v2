"""S-parameter tables imported from heavy simulations: the model slot of one part instance (``part.model``).

optodraw stores exp(-i omega t) phasors, as SAX: a length L of index n gives exp(+i 2 pi n L / lambda). A reader that
knows its file's convention converts it: Touchstone files use exp(+j omega t), so the reader conjugates them, as
``fieldrt.sax`` does. Phase 1 keeps TE only: mode ``@0``; a port with no mode suffix is TE.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from optodraw.animation_engine.errors import AnimationError
from optodraw.animation_engine.signals import C_UM_PER_PS
from optodraw.provenance import Source

C_M_PER_S = 299792458.0
_HZ_PER_UNIT = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9, "thz": 1e12}
_EDGE_NM = 1e-9                       # a wavelength this close to a table edge is inside (a frequency round trip)


@dataclass(eq=False)
class SParameters:
    """``s[(out_port, in_port)]``: complex amplitudes at ``wavelengths_nm``, exp(-i omega t) phasors, TE.

    The constructor sorts the wavelengths and drops an entry that is zero at every wavelength.
    """

    wavelengths_nm: np.ndarray
    s: dict[tuple[str, str], np.ndarray]
    source: Source
    sha256: str = ""

    def __post_init__(self):
        if not isinstance(self.source, Source):
            raise TypeError(f"an S-parameter table needs a Source, not {type(self.source).__name__}")
        wl = np.asarray(self.wavelengths_nm, dtype=float)
        if wl.ndim != 1 or wl.size < 2 or not np.all(np.isfinite(wl)) or np.any(wl <= 0):
            raise ValueError("an S-parameter table needs two or more finite, positive wavelengths")
        order = np.argsort(wl)
        wl = wl[order]
        if np.any(np.diff(wl) <= 0):
            raise ValueError("an S-parameter table lists a wavelength twice")
        table = {}
        for (out, into), values in self.s.items():
            values = np.asarray(values, dtype=complex)
            if values.shape != wl.shape or not np.all(np.isfinite(values)):
                raise ValueError(f"S({out}, {into}) needs one finite value per wavelength")
            if np.any(values):
                table[(str(out), str(into))] = values[order]
        if not table:
            raise ValueError("an S-parameter table needs a nonzero entry")
        self.wavelengths_nm, self.s = wl, table
        omega = 2.0 * math.pi * C_UM_PER_PS / (wl / 1000.0)                    # rad/ps
        self._amplitude = {key: np.abs(values) for key, values in table.items()}
        self._phase = {key: np.unwrap(np.angle(values)) for key, values in table.items()}
        # exp(-i omega t): the phase grows with omega, so the group delay is +d(phase)/d(omega)
        self._delay_ps = {key: np.gradient(phase, omega) for key, phase in self._phase.items()}

    @classmethod
    def load(cls, path, *, ports: dict[str, str] | None = None, source: Source | None = None) -> SParameters:
        """Read a table from ``.npz`` (SAX keys) or Touchstone ``.sNp``.

        The npz layout, as ``fieldrt.sax`` gives it:

        - ``wavelengths_um``: a float array, the wavelengths in micrometres (SAX's unit);
        - one complex array per port pair, one value per wavelength, named ``"<out>,<in>"``: the key of
          ``fieldrt.sax.sdict`` (output port first) joined by a comma, with SAX port and mode names. ``"o2@0,o1@0"``
          is the light that leaves ``o2`` in mode 0 for light that enters ``o1`` in mode 0;
        - other arrays (no comma in the name) are not read.

        From fieldrt: ``s = fieldrt.sax.sdict(scattering, ports, phasor=...)``, then
        ``np.savez(path, wavelengths_um=wavelengths_um, **{",".join(key): value for key, value in s.items()})``.

        A Touchstone 1 file names its ports ``"1"`` to ``"N"``. Its option line gives the frequency unit, the format
        (RI, MA or DB) and the reference impedance; the impedance has no optical meaning and is not used.

        ``ports`` maps file port names (with or without the mode suffix) to the part's port names; a file name it
        leaves out stays as it is, and ``check`` refuses a name the part does not have. Mode ``@0`` is TE; TM (``@1``)
        and cross-mode entries are dropped in phase 1. With no ``source``, the table gets a model-kind record that
        holds the file's SHA-256.
        """

        path = Path(path)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        suffix = path.suffix.lower()
        if suffix == ".npz":
            wavelengths_nm, table = _read_npz(raw, path.name)
        elif re.fullmatch(r"\.s\d+p", suffix):
            wavelengths_nm, table = _read_touchstone(raw.decode("latin-1"), int(suffix[2:-1]), path.name)
        else:
            raise ValueError(f"{path.name}: optodraw reads S-parameters from .npz (SAX keys) or Touchstone .sNp")
        if source is None:
            source = Source("model", f"sha256:{digest}", f"{path.name}: imported with no source given")
        return cls(wavelengths_nm, _te_ports(table, ports or {}, path.name), source, digest)

    def at(self, wavelength_nm: float) -> dict[tuple[str, str], complex]:
        """Each entry at ``wavelength_nm``: amplitude and unwrapped phase, each interpolated linearly. A wavelength
        outside the table is refused, not extrapolated."""

        wl = self._inside(wavelength_nm)
        return {key: complex(np.interp(wl, self.wavelengths_nm, self._amplitude[key])
                             * np.exp(1j * np.interp(wl, self.wavelengths_nm, self._phase[key])))
                for key in self.s}

    def group_delay_ps(self, wavelength_nm: float) -> dict[tuple[str, str], float]:
        """Each entry's group delay at ``wavelength_nm``, in ps: d(phase)/d(omega) by central difference on the table,
        interpolated linearly."""

        wl = self._inside(wavelength_nm)
        return {key: float(np.interp(wl, self.wavelengths_nm, delay)) for key, delay in self._delay_ps.items()}

    def _inside(self, wavelength_nm: float) -> float:
        lo, hi, wl = float(self.wavelengths_nm[0]), float(self.wavelengths_nm[-1]), float(wavelength_nm)
        if not lo - _EDGE_NM <= wl <= hi + _EDGE_NM:
            raise AnimationError(f"{wl:g} nm is outside the imported table, {lo:g} to {hi:g} nm")
        return wl


def check(sp: SParameters, part: Any, name: str = "") -> list[str]:
    """Check a table against the part that holds it. Errors raise ``AnimationError``; warnings come back as text.

    Errors: a table port the part does not have (both lists named); a largest singular value of S above 1.05.
    Warnings: a largest singular value above 1 + 1e-6; a phase step over pi/4 between neighbouring wavelengths, where
    the table may be too coarse for a feature in it. ``name`` starts each message (default: the part's label or type).
    """

    name = name or getattr(part, "label", "") or getattr(part, "component_type", "") or type(part).__name__
    table_ports = sorted({port for pair in sp.s for port in pair})
    part_ports = sorted(port for port, spec in part.ports().items() if spec.kind not in ("electrical", "thermal"))
    if not set(table_ports) <= set(part_ports):
        raise AnimationError(f"{name}: the table's ports {', '.join(table_ports)} do not match the part's ports "
                             f"{', '.join(part_ports)}; map them with SParameters.load(path, ports={{...}})")
    wl = sp.wavelengths_nm
    index = {port: k for k, port in enumerate(table_ports)}
    matrix = np.zeros((wl.size, len(table_ports), len(table_ports)), dtype=complex)
    for (out, into), values in sp.s.items():
        matrix[:, index[out], index[into]] = values
    gain = np.linalg.svd(matrix, compute_uv=False)[:, 0]
    k = int(np.argmax(gain))
    if gain[k] > 1.05:
        raise AnimationError(f"{name}: the imported table gives out more power than it takes in "
                             f"(largest singular value {gain[k]:.6g} at {wl[k]:g} nm)")
    warnings = []
    if gain[k] > 1.0 + 1e-6:
        warnings.append(f"{name}: the imported table is not passive within 1e-6 "
                        f"(largest singular value {gain[k]:.6g} at {wl[k]:g} nm)")
    worst, where = 0.0, None
    for key, phase in sp._phase.items():
        steps = np.abs(np.diff(phase))
        amplitude = sp._amplitude[key]
        steps[np.minimum(amplitude[:-1], amplitude[1:]) < 1e-3] = 0.0      # almost no light: its phase is noise
        j = int(np.argmax(steps))
        if steps[j] > worst:
            worst, where = float(steps[j]), (key, j)
    if worst > math.pi / 4:
        (out, into), j = where
        warnings.append(f"{name}: the phase from {into} to {out} steps {worst:.2f} rad between {wl[j]:g} and "
                        f"{wl[j + 1]:g} nm (over pi/4); the table may be too coarse for a feature there")
    return warnings


def _read_npz(raw: bytes, name: str) -> tuple[np.ndarray, dict[tuple[str, str], np.ndarray]]:
    with np.load(io.BytesIO(raw)) as archive:
        if "wavelengths_um" not in archive.files:
            raise ValueError(f"{name}: no 'wavelengths_um' array (the wavelengths in micrometres, as SAX)")
        table = {}
        for key in archive.files:
            if "," in key:
                pair = tuple(key.split(","))
                if len(pair) != 2:
                    raise ValueError(f"{name}: {key!r} is not one port pair '<out>,<in>'")
                table[pair] = archive[key]
        return np.asarray(archive["wavelengths_um"], dtype=float) * 1000.0, table


def _read_touchstone(text: str, n: int, name: str) -> tuple[np.ndarray, dict[tuple[str, str], np.ndarray]]:
    """Touchstone 1: the option line ``# <unit> S <RI|MA|DB> R <ohm>`` (defaults GHz, MA, 50 ohm), then per frequency
    the frequency and n x n pairs. A 2-port file lists S11 S21 S12 S22; more ports list the matrix row by row."""

    unit, form, seen_option, numbers = "ghz", "ma", False, []
    for line in text.splitlines():
        line = line.split("!", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            raise ValueError(f"{name}: Touchstone 2 keywords are not read; save the file as Touchstone 1")
        if line.startswith("#"):
            if seen_option:                                   # the standard reads the first option line only
                continue
            seen_option = True
            words = iter(line[1:].lower().split())
            for word in words:
                if word in _HZ_PER_UNIT:
                    unit = word
                elif word in ("ri", "ma", "db"):
                    form = word
                elif word == "r":
                    if not float(next(words, "nan")) > 0:
                        raise ValueError(f"{name}: the reference impedance must be a positive number")
                elif word != "s":
                    raise ValueError(f"{name}: the option line has {word!r}; optodraw reads S parameters only")
            continue
        numbers += [float(word) for word in line.split()]
    width = 1 + 2 * n * n
    if not numbers or len(numbers) % width:
        raise ValueError(f"{name}: {len(numbers)} numbers do not make records of one frequency and {n} x {n} pairs")
    rows = np.array(numbers).reshape(-1, width)
    hz = rows[:, 0] * _HZ_PER_UNIT[unit]
    if np.any(hz <= 0) or np.any(np.diff(hz) <= 0):
        raise ValueError(f"{name}: the frequencies must be positive and increase (noise data is not read)")
    first, second = rows[:, 1::2], rows[:, 2::2]
    if form == "ri":
        values = first + 1j * second
    else:
        magnitude = first if form == "ma" else 10.0 ** (first / 20.0)
        values = magnitude * np.exp(1j * np.radians(second))
    values = values.reshape(-1, n, n)
    if n == 2:
        values = values.transpose(0, 2, 1)                    # a 2-port file lists S11 S21 S12 S22
    values = values.conj()                                     # Touchstone is exp(+j omega t)
    names = [str(k + 1) for k in range(n)]
    table = {(names[i], names[j]): values[:, i, j] for i in range(n) for j in range(n)}
    return C_M_PER_S / hz * 1e9, table


def _te_ports(table: dict, ports: dict[str, str], name: str) -> dict[tuple[str, str], np.ndarray]:
    """The TE entries (mode 0, or no mode suffix), renamed by ``ports``: a full name ``o1@0`` or a base name ``o1``."""

    def split(port: str) -> tuple[str, str]:
        base, _, mode = port.partition("@")
        return base, mode or "0"

    file_names = {label for pair in table for port in pair for label in (port, split(port)[0])}
    unknown = sorted(set(ports) - file_names)
    if unknown:
        raise ValueError(f"{name}: the port map names {', '.join(unknown)}, which the file does not have "
                         f"(its ports: {', '.join(sorted(file_names))})")
    te = [(out, into) for out, into in table if split(out)[1] == split(into)[1] == "0"]
    if not te:
        raise ValueError(f"{name}: the file has no TE (mode 0) entry")
    kept = {}
    for out, into in te:
        renamed = tuple(ports.get(port, ports.get(split(port)[0], split(port)[0])) for port in (out, into))
        kept[renamed] = table[(out, into)]
    if len(kept) < len(te):
        raise ValueError(f"{name}: the port map gives two file ports the same part port")
    return kept

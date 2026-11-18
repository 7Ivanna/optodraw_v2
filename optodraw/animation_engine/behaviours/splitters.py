"""Splitters and couplers: lossless 2 x 2 and 1 x 2 scattering, with the cross path's phase i."""

from __future__ import annotations

import math
import cmath

from ..signals import scalar
from . import Behaviour, Transfer, polyline_length, register
from ..ids import path_id
from .geometry import (Rail, Section, drawn_points, reads, index_of, optical_path_points, port_xy, splice, straight,
                       through_anchor, to_local)


@register("BeamSplitter", "NonPolarizingBeamSplitter")
class BeamSplitter(Behaviour):
    """Inputs {in, tap} scatter to outputs {trans, refl}, and back (reciprocal).

    in -> trans and tap -> refl transmit; in -> refl and tap -> trans reflect. A dichroic transmits at
    and above ``cutoff_wavelength`` and reflects below it.
    """

    _TRANSMIT = {"in": "trans", "trans": "in", "tap": "refl", "refl": "tap"}
    _REFLECT = {"in": "refl", "refl": "in", "tap": "trans", "trans": "tap"}

    def ratios(self, part, wavelength_nm) -> tuple[float, float]:
        """(transmitted, reflected) power fractions: from ``split_ratio`` (transmitted, reflected), else
        from ``transmission`` in percent (90 means 90/10)."""

        if getattr(part, "dichroic", False) and getattr(part, "cutoff_wavelength", None) is not None:
            transmit = 1.0 if wavelength_nm >= float(part.cutoff_wavelength) else 0.0
            return transmit, 1.0 - transmit
        split = getattr(part, "split_ratio", None)
        if split is not None:
            transmit, reflect = (float(v) for v in split)
        else:
            transmit = float(getattr(part, "transmission", 50.0))
            reflect = 100.0 - transmit
        return transmit / (transmit + reflect), reflect / (transmit + reflect)

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if in_port not in self._TRANSMIT:
            return []
        transmit, reflect = self.ratios(part, wavelength_nm)
        ports = part.ports()
        found = []
        for out, amplitude in ((self._TRANSMIT[in_port], math.sqrt(transmit)), (self._REFLECT[in_port], 1j * math.sqrt(reflect))):
            if out in ports:
                found.append(Transfer(in_port, out, scalar(amplitude), through_anchor(part, in_port, out), index_of(part, in_port)))
        return found


@register("DichroicMirror")
class DichroicMirror(BeamSplitter):
    """A beam splitter that splits by colour: a longpass one transmits at and above ``cutoff_wavelength`` and
    reflects below it, a shortpass one the other way round. With no edge set it splits evenly."""

    def ratios(self, part, wavelength_nm) -> tuple[float, float]:
        cutoff = getattr(part, "cutoff_wavelength", None)
        if cutoff is None:
            return 0.5, 0.5
        long = wavelength_nm >= float(cutoff)
        transmit = long if str(getattr(part, "pass_band", "longpass")) != "shortpass" else not long
        return (1.0, 0.0) if transmit else (0.0, 1.0)


@register("MMI1x4")
class OneToFour(Behaviour):
    """1 x 4: o1 splits equally into o2 to o5; each output couples a quarter of its power back into o1."""

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        outs = [name for name in part.ports() if name != "o1"]
        a = 1.0 / math.sqrt(len(outs))
        targets = outs if in_port == "o1" else (["o1"] if in_port in outs else [])
        return [Transfer(in_port, out, scalar(a), _points(part, in_port, out), index_of(part, in_port)) for out in targets]


@register("AWG")
class ArrayedWaveguideGrating(Behaviour):
    """A multiplexer: channel k passes its own band (``center_wavelength_nm`` plus (k - (N + 1) / 2) channel
    spacings, repeating every free spectral range) to the common port ``i1``, and ``i1`` sends each colour to
    its channel. Light of another colour in a channel goes nowhere.

    A passband is the channel centre plus or minus half a spacing, edges included to 1e-9 nm (float noise
    must not move a wavelength). A wavelength exactly midway between two channels goes to the lower channel,
    so the choice is deterministic."""

    common = "i1"                                   # the port every channel shares

    def channel(self, part, wavelength_nm) -> str | None:
        count = int(part.channel_count)
        spacing = float(part.channel_spacing_nm)
        fsr = float(getattr(part, "free_spectral_range_nm", 0.0) or 0.0)
        for k in range(1, count + 1):
            offset = wavelength_nm - (float(part.center_wavelength_nm) + (k - (count + 1) / 2.0) * spacing)
            if fsr > 0.0:
                offset = (offset + fsr / 2.0) % fsr - fsr / 2.0
            if abs(offset) <= spacing / 2.0 + 1e-9:
                return f"o{k}"
        return None

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        match = self.channel(part, wavelength_nm)
        if in_port == self.common:
            targets = [match] if match is not None else []
        else:
            targets = [self.common] if in_port == match else []
        return [Transfer(in_port, out, scalar(1.0), _points(part, in_port, out), index_of(part, in_port)) for out in targets]


@register("YBranch", "MMI1x2")
class YJunction(Behaviour):
    """1 x 2: o1 splits equally into o2 and o3; each of o2, o3 couples half its power back into o1."""

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        a = 1.0 / math.sqrt(2.0)
        outs = ("o2", "o3") if in_port == "o1" else (("o1",) if in_port in ("o2", "o3") else ())
        return [Transfer(in_port, out, scalar(a), _points(part, in_port, out), index_of(part, in_port)) for out in outs]


@register("MMI2x2", "MMI2x2PowerSplitter", "TapCoupler", "FiberCoupler")
class Coupler2x2(Behaviour):
    """2 x 2: power ``kappa`` crosses (phase i), the rest stays on the bar port (the output on the input's side).

    Every path gets the same physical length, the mean of the drawn paths, so the matrix stays unitary.
    """

    def kappa(self, part) -> float:
        for name in ("tap_ratio", "ratio", "coupling_ratio"):
            value = getattr(part, name, None)
            if value is not None:
                return float(value)
        return 0.5

    def sides(self, part) -> tuple[list[str], list[str]]:
        ports = {n: p for n, p in part.ports().items() if p.kind != "electrical"}
        names = sorted(ports, key=lambda n: (ports[n].center.x, n))
        return names[:2], names[2:]

    def paths(self, part, in_port) -> tuple[tuple[str, tuple], tuple[str, tuple]]:
        """(bar port, path) and (cross port, path). A drawn cross path that starts inside the part
        follows the input's own guide to the middle of the coupling region, then hops the gap there."""

        left, right = self.sides(part)
        outs = right if in_port in left else left
        ports = part.ports()
        side = ports[in_port].center.y
        bar = min(outs, key=lambda n: abs(ports[n].center.y - side))
        cross = next(n for n in outs if n != bar)
        bar_path, cross_path = _points(part, in_port, bar), _points(part, in_port, cross)
        if math.dist(cross_path[0], port_xy(part, in_port)) > 1e-6:
            local = to_local(part, cross_path)
            middle = cross_path[min(range(len(cross_path)), key=lambda k: abs(local[k][0]))]
            cross_path = splice(bar_path, cross_path, middle)
        return (bar, bar_path), (cross, cross_path)

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        left, right = self.sides(part)
        if in_port not in left + right:
            return []
        lengths = [polyline_length(path) for port in left + right for _, path in self.paths(part, port)]
        mean = sum(lengths) / len(lengths)
        (bar, bar_path), (cross, cross_path) = self.paths(part, in_port)
        k = self.kappa(part)
        return [Transfer(in_port, bar, scalar(math.sqrt(1.0 - k)), bar_path, index_of(part, in_port), physical_length=mean),
                Transfer(in_port, cross, scalar(1j * math.sqrt(k)), cross_path, index_of(part, in_port), physical_length=mean)]

    def sections(self, part, sid, params):
        """Two drawn rails with a gap (a directional or tap coupler): per direction of travel, one section over the
        whole of both rails, each rail from its input to the output on its side. An MMI has no gap: []."""

        found = []
        for ins in self.sides(part):
            first, second = ins
            (bar1, rail1), (cross1, _) = self.paths(part, first)
            (bar2, rail2), (cross2, _) = self.paths(part, second)
            if math.dist(_points(part, first, cross1)[0], port_xy(part, first)) <= 1e-6:
                return []
            length1, length2 = polyline_length(rail1), polyline_length(rail2)
            ends = {bar1: (0, length1), bar2: (1, length2)}
            found.append(Section((Rail(rail1, (0.0, length1), (0.0, length1)), Rail(rail2, (0.0, length2), (0.0, length2))),
                                 (reads(self, part, sid, params, first, (0, 0.0), ends),
                                  reads(self, part, sid, params, second, (1, 0.0), ends)),
                                 frozenset(path_id(sid, a, b) for a, b in ((first, bar1), (first, cross1), (second, bar2),
                                                                           (second, cross2))),
                                 kappa=self.kappa(part), cross=1j))
        return found


@register("DirectionalCoupler")
class DirectionalCoupling(Coupler2x2):
    """A directional coupler: the 2 x 2 coupler, its power coupling read from ``coupling_ratio``."""

    parameters = ("coupling_ratio", "group_index")


@register("FiberCirculator")
class Circulator(Behaviour):
    _NEXT = {"p1": "p2", "p2": "p3"}

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        out = self._NEXT.get(in_port)
        return [Transfer(in_port, out, scalar(1.0), straight(part, in_port, out), index_of(part, in_port))] if out else []

    def sinks(self, part, port):
        return port == "p3"                       # light that comes back into p3 is absorbed


@register("WaveguideCrossing")
class Crossing(Behaviour):
    """Straight through: the output is the port facing the opposite way."""

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        ports = part.ports()
        if in_port not in ports:
            return []
        facing = ports[in_port].orientation_deg
        out = min((n for n in ports if n != in_port),
                  key=lambda n: abs(abs((ports[n].orientation_deg - facing) % 360.0) - 180.0))
        return [Transfer(in_port, out, scalar(1.0), _points(part, in_port, out), index_of(part, in_port))]


def _points(part, in_port, out_port):
    """The part's own drawn path where it has one, else a straight line through the part."""

    return drawn_points(part, in_port, out_port, straight(part, in_port, out_port))


@register("StarCoupler")
class FourierStar(Behaviour):
    """Generic reciprocal Fourier slab; unequal counts use a passive submatrix."""

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        inputs = [f"i{i+1}" for i in range(part.input_count)]
        outputs = [f"o{i+1}" for i in range(part.output_count)]
        source, destinations = (inputs, outputs) if in_port in inputs else (outputs, inputs)
        if in_port not in source:
            return []
        n = max(len(inputs), len(outputs))
        paths = optical_path_points(part, in_port)
        lengths = [polyline_length(points) for port in inputs
                   for values in optical_path_points(part, port).values() for points in values]
        length = sum(lengths)/len(lengths)
        i = source.index(in_port)
        return [Transfer(in_port, out, scalar(cmath.exp(2j*math.pi*i*j/n)/math.sqrt(n)),
                         paths[out][0], index_of(part, in_port), physical_length=length)
                for j, out in enumerate(destinations)]


@register("PartialMirror")
class PartialReflector(BeamSplitter):
    """A cavity mirror at normal incidence: light at ``front`` passes to ``back`` with ``transmission`` per cent and
    comes back out of ``front`` with the rest, and the same from ``back``. The 45 degree ports split as a beam
    splitter's do."""

    fold_ports = frozenset({"front", "back"})

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if in_port not in self.fold_ports:
            return super().transfers(part, sid, in_port, wavelength_nm, params)
        transmit, reflect = self.ratios(part, wavelength_nm)
        other = "back" if in_port == "front" else "front"
        n = index_of(part, in_port)
        return [Transfer(in_port, other, scalar(math.sqrt(transmit)), through_anchor(part, in_port, other), n),
                Transfer(in_port, in_port, scalar(1j * math.sqrt(reflect)), through_anchor(part, in_port, in_port), n)]


@register("MMI1x3")
class OneToThree(OneToFour):
    """1 x 3: o1 splits equally into o2, o3 and o4; each output couples a third of its power back into o1."""


@register("AdiabaticCoupler")
class AdiabaticSplitter(Coupler2x2):
    """A broadband 3 dB coupler: the slow transition splits the power evenly across its band."""


@register("EchelleGrating")
class EchelleDemux(ArrayedWaveguideGrating):
    """An echelle grating sorts the colours as an AWG does, from its common port ``in`` to the channels ``oK``."""

    common = "in"


@register("AWGR")
class CyclicRouter(ArrayedWaveguideGrating):
    """An N x N cyclic router. The colour of channel j (found as for an AWG, repeating every free spectral range) goes
    from input ``iK`` to output o((K + j - 2) mod N + 1), and back the other way: each input reaches every output on
    its own colour, and no two inputs share an output on one colour."""

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        match, count = self.channel(part, wavelength_nm), int(part.channel_count)
        if match is None or in_port not in part.ports() or in_port[:1] not in ("i", "o"):
            return []
        j, k = int(match[1:]) - 1, int(in_port[1:]) - 1
        out = f"o{(k + j) % count + 1}" if in_port[0] == "i" else f"i{(k - j) % count + 1}"
        return [Transfer(in_port, out, scalar(1.0), _points(part, in_port, out), index_of(part, in_port))]

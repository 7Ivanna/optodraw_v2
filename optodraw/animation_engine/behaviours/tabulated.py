"""A part whose light follows an imported S-parameter table (``part.model``) in place of its own behaviour."""

from __future__ import annotations

import numpy as np

from optodraw.sparameters import SParameters, check

from ..errors import AnimationError
from ..signals import C_UM_PER_PS
from . import Behaviour, Transfer, polyline_length
from .geometry import drawn_points, index_of, through_anchor


class TabulatedBehaviour(Behaviour):
    """One transfer per table entry, along the drawn path. The table's phase is the whole phase from port to port, so
    the solver adds none. TE only: the Jones matrix is diag(S, 0). The packet delay is the table's group delay. A
    tabulated part has no ring, and no phase or heater of its own to sweep."""

    passive = False              # ``check`` holds a table to the spec's passivity tolerance, not the solver's 1e-9
    parameters: tuple[str, ...] = ()

    def __init__(self, sp: SParameters):
        self.sp = sp
        self._checked = False
        self._paths: dict[tuple, tuple] = {}         # (in, out, where the part is) -> (drawn path, its length)

    def transfers(self, part, sid, in_port, wavelength_nm, params):
        if any(str(key).split(":")[:2] in (["phase", sid], ["heater", sid]) for key in params):
            raise AnimationError(f"{sid} has an imported model: its phase and heater cannot be swept")
        if not self._checked:
            check(self.sp, part, sid)
            self._checked = True
        try:
            values, delays = self.sp.at(wavelength_nm), self.sp.group_delay_ps(wavelength_nm)
        except AnimationError as error:
            raise AnimationError(f"{sid}: {error}") from None
        found = []
        for (out, into), value in values.items():
            if into != in_port:
                continue
            where = (into, out, part.transform.position.as_tuple(), float(part.transform.rotation_deg.z))
            if where not in self._paths:                       # the path does not change with the wavelength
                points = drawn_points(part, into, out, through_anchor(part, into, out))
                self._paths[where] = (points, polyline_length(points))
            points, length = self._paths[where]
            index = C_UM_PER_PS * delays[(out, into)] / length if length > 0 else 0.0
            if index <= 0:
                # shortcut: a group delay of zero or less (fast light near a resonance) plays at the part's own index;
                # upgrade when a figure must show fast light
                index = index_of(part, into)
            found.append(Transfer(into, out, np.array([[value, 0], [0, 0]], dtype=complex), points, index,
                                  phase_included=True))
        return found

    def notes(self, part, sid):
        name = getattr(part, "label", "") or sid
        return [f"{name}: TE only (imported table)"] + check(self.sp, part, name)

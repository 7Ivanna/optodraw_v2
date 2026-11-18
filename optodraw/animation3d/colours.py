"""Light colours: the true colour of a visible wavelength, white for one infrared line, a palette for channels."""

from __future__ import annotations

from optodraw.core.beam import wavelength_to_hex

CHANNEL_PALETTE: tuple[str, ...] = ("#4fc3ff", "#ff8a4c", "#7ee787", "#ffd75e", "#d2a8ff", "#ff6b9e", "#5eead4",
                                    "#f0f6fc")
VISIBLE_NM = (380.0, 750.0)


def channel_colors(wavelengths_nm: list[float]) -> dict[float, str]:
    """One colour per wavelength.

    A visible wavelength gets its true colour. One hidden line is white.
    Several hidden lines get palette colours in wavelength order.
    """

    ordered = sorted(set(float(nm) for nm in wavelengths_nm))
    hidden = [nm for nm in ordered if not VISIBLE_NM[0] <= nm <= VISIBLE_NM[1]]
    colors = {}
    for nm in ordered:
        if nm not in hidden:
            colors[nm] = wavelength_to_hex(nm)
        elif len(hidden) == 1:
            colors[nm] = "#ffffff"
        else:
            colors[nm] = CHANNEL_PALETTE[hidden.index(nm) % len(CHANNEL_PALETTE)]
    return colors

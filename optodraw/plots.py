"""House-style matplotlib helpers for a figure page: a small figure, and an eye diagram of the author's samples.

They are helpers, not a plot library. Each returns a plain matplotlib figure, which an :class:`~optodraw.Inset` takes as
a :class:`~optodraw.figure.Plot`. No helper makes up data.
"""

from __future__ import annotations

from typing import Any

MM_IN = 25.4                # mm per inch
FONT_PT = 7.0               # the page's default font_pt
LINE_PT = 0.6               # research-figures: thin lines, 0.6 to 1.0 pt
TICK_PT = 2.0               # small outward ticks
EYE_MM = (60.0, 40.0)       # the size of a new eye figure; an inset gives it its own
BLUE = "#0072B2"            # research-figures: Okabe-Ito blue, the primary condition


def house_figure(width_mm: float, height_mm: float) -> tuple[Any, Any]:
    """A figure ``width_mm`` by ``height_mm`` with one axes in the house look: text at 7 pt, thin lines, small outward
    ticks, the top and right spines off and no title. It is a plain :class:`matplotlib.figure.Figure`, not a pyplot
    figure, so it keeps no global state. Returns ``(fig, ax)``."""

    from matplotlib.figure import Figure

    fig = Figure(figsize=(width_mm / MM_IN, height_mm / MM_IN), layout="constrained")
    ax = fig.add_subplot()
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_linewidth(LINE_PT)
    ax.tick_params(direction="out", length=TICK_PT, width=LINE_PT, labelsize=FONT_PT)
    ax.xaxis.label.set_fontsize(FONT_PT)
    ax.yaxis.label.set_fontsize(FONT_PT)
    return fig, ax


def eye_diagram(samples: Any, samples_per_ui: int, uis: int = 2, ax: Any = None, color: str = BLUE,
                alpha: float = 0.3) -> Any:
    """The eye of ``samples``: windows ``uis`` unit intervals (UI) long, laid over each other. Window ``k`` starts at
    sample ``k * samples_per_ui``. The x axis is time in UI, from 0 to ``uis``. It draws in ``ax`` when given, else in
    a new :func:`house_figure`. Returns the figure.

    ``samples_per_ui`` is a whole number of 2 or more, ``uis`` a whole number of 1 or more, and the samples fill two
    or more windows. Anything else raises ValueError."""

    import numpy as np

    data = np.asarray(samples, dtype=float).ravel()
    if isinstance(samples_per_ui, bool) or int(samples_per_ui) != samples_per_ui or samples_per_ui < 2:
        raise ValueError(f"samples_per_ui is a whole number of 2 or more, got {samples_per_ui!r}")
    if isinstance(uis, bool) or int(uis) != uis or uis < 1:
        raise ValueError(f"uis is a whole number of 1 or more, got {uis!r}")
    step, wide = int(samples_per_ui), int(samples_per_ui) * int(uis)
    count = (len(data) - wide) // step + 1
    if count < 2:
        raise ValueError(f"an eye needs two or more windows to lay over each other: {len(data)} samples fill "
                         f"{max(count, 0)} windows of {uis} UI ({wide} samples)")
    if ax is None:
        _, ax = house_figure(*EYE_MM)
    x = np.arange(wide) / step
    for k in range(count):
        ax.plot(x, data[k * step:k * step + wide], color=color, alpha=alpha, linewidth=LINE_PT)
    ax.set_xlim(0.0, float(uis))
    ax.set_xlabel("Time (UI)")
    return ax.figure

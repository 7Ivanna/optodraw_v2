"""Preset setup library.

Each preset is a published figure, rebuilt as a compact optodraw scene: the module in
:mod:`optodraw.literature` draws it and cites the paper. The presets keep their old names, so
``build_preset("raman")`` and ``raman_setup()`` still work.
"""

from __future__ import annotations

from typing import Any

from optodraw.core.scene import Scene


def _objective_focus(objective) -> tuple[float, float]:
    """Where an objective's focus lands, in scene coordinates."""

    return objective.focus_point()


def _figure(name: str, title: str | None, **kwargs: Any) -> Scene:
    from optodraw import literature

    if title is not None:
        kwargs["title"] = title
    return literature.build(name, **kwargs)


def confocal_pl_setup(title: str | None = None) -> Scene:
    """Micro-photoluminescence setup (Sahoo et al. 2026, Fig. 5)."""

    return _figure("sahoo2026_confocal_pl", title)


def raman_setup(title: str | None = None) -> Scene:
    """Raman micro-spectroscopy setup (McNairn et al. 2021, Fig. 2a)."""

    return _figure("mcnairn2021_raman", title)


def ftir_setup(title: str | None = None) -> Scene:
    """Michelson FTIR interferometer (Ni et al. 2020, Fig. 1)."""

    return _figure("ni2020_ftir", title)


def ring_resonator_chip(title: str | None = None) -> Scene:
    """Fifth-order microring filter (Mak et al. 2015, Fig. 1a and 7)."""

    return _figure("mak2015_ring_filter", title)


def wdm_delay_weight_bank_chip(title: str | None = None) -> Scene:
    """Broadcast-and-weight network (Tait et al. 2017, Fig. 1a)."""

    return _figure("tait2017_broadcast_weight", title)


def qwp_circular_lab(title: str | None = None) -> Scene:
    """Rotating quarter-wave plate polarimeter (Schaefer et al. 2007, Fig. 3)."""

    return _figure("schaefer2007_qwp_polarimeter", title)


def build_qwp_circular_lab(**kwargs) -> Scene:
    """Alias for :func:`qwp_circular_lab`."""

    return qwp_circular_lab(**kwargs)


def mzm_mesh_chip(title: str = "MZM Mesh", modes: int = 4, layers: int = 4, **kwargs: Any) -> Scene:
    """Build a programmable photonic **MZM mesh** (Clements-style).

    N input modes pass through alternating columns of per-mode MZM modulators and
    staggered **directional couplers** that mix adjacent modes — a real
    interferometric mesh of MZMs + couplers, not a cascade of independent MZMs.
    """

    from optodraw.layout import build_mzm_coupler_mesh

    return build_mzm_coupler_mesh(
        title=title,
        modes=modes,
        layers=layers,
        drive_style=kwargs.pop("drive_style", "gsg"),
        **kwargs,
    )["scene"]


def free_space_breadboard(title: str | None = None) -> Scene:
    """Self-calibrating polarimeter (Wirthl et al. 2021, Fig. 3a)."""

    return _figure("wirthl2021_polarimeter", title)


def coherent_receiver_chip(title: str | None = None) -> Scene:
    """Coherent receiver without waveguide crossing (Faralli et al. 2015, Fig. 1)."""

    return _figure("faralli2015_receiver", title)


PRESETS = {
    "confocal_pl": confocal_pl_setup,
    "raman": raman_setup,
    "ftir": ftir_setup,
    "free_space_breadboard": free_space_breadboard,
    "ring_resonator_chip": ring_resonator_chip,
    "wdm_delay_weight_bank_chip": wdm_delay_weight_bank_chip,
    "mzm_mesh_chip": mzm_mesh_chip,
    "coherent_receiver_chip": coherent_receiver_chip,
    "qwp_circular_lab": qwp_circular_lab,
}

# names that say what the figure is; build_preset takes them, the list shows each figure once
ALIASES = {
    "self_calibrating_polarimeter": "free_space_breadboard",
    "broadcast_weight_network_chip": "wdm_delay_weight_bank_chip",
}


def list_presets() -> list[str]:
    """Return the names of all built-in setup presets."""

    return list(PRESETS.keys())


def build_preset(name: str, **kwargs) -> Scene:
    """Build one preset scene by name, forwarding keyword overrides."""

    name = ALIASES.get(name, name)
    if name not in PRESETS:
        raise KeyError(f"Unknown preset '{name}'. Available presets: {', '.join(list_presets())}")
    return PRESETS[name](**kwargs)
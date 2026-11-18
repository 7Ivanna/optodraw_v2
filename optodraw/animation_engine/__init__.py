"""The animation engine (M1: the physics core). Renamed to ``optodraw.animation`` in M6."""

from .errors import AnimationError
from .graph import build_graph
from .state import SignalState, compile_signal_state, sweep_steady_state
from .authoring import Animation
from .timeline import Timeline
from .spectrum import Spectrum, spectrum
from .waveform import Waveform
from .chain import Chain, signal_chain
from .styles import Style
from .primitives import (
    Quantity, Create, FadeIn, FadeOut, Indicate, Dim, Label, Arrow, Write, Transform,
    MoveAlong, Flow, Zoom, Pan, Fit, Morph, Set, Sweep, Plot, Wait, Click, Sequence, Lagged,
)

__all__ = [
    "AnimationError", "SignalState", "build_graph", "compile_signal_state", "sweep_steady_state",
    "Animation", "Timeline", "Spectrum", "spectrum", "Waveform", "Chain", "signal_chain",
    "Style", "Quantity", "Create", "FadeIn", "FadeOut", "Indicate",
    "Dim", "Label", "Arrow", "Write", "Transform", "MoveAlong", "Flow", "Zoom", "Pan", "Fit",
    "Morph", "Set", "Sweep", "Plot", "Wait", "Click", "Sequence", "Lagged",
]

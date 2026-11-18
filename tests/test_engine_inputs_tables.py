
import pytest

import optodraw
from optodraw.animation_engine import AnimationError, compile_signal_state
from optodraw.animation_engine.inputs import InputSignal
from optodraw.animation_engine.tables import compile_table


def test_invalid_input_and_missing_behaviour_are_named_errors():
    scene = optodraw.Scene(width=240, height=80, platform="on_chip")
    part = scene.add(optodraw.VerticalGratingCoupler())
    with pytest.raises(AnimationError, match="verticalgratingcoupler1.*missing"):
        compile_table(scene, mode="cw", inputs=[InputSignal("port:verticalgratingcoupler1:missing")])
    part.component_type = "UnknownInput"
    with pytest.raises(AnimationError, match="unknowninput1.*no behaviour"):
        compile_table(scene, mode="cw", inputs=[InputSignal("port:unknowninput1:f1")])


@pytest.mark.parametrize("mode", ["pulse", "cw"])
def test_strict_open_port_is_an_error_not_absorption(mode):
    scene = optodraw.Scene(width=120, height=80, platform="on_chip")
    scene.add(optodraw.OnChipLaser())
    with pytest.raises(AnimationError, match="onchiplaser1.*o1"):
        compile_signal_state(scene, mode=mode, strict=True)



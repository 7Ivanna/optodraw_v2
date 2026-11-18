"""Public authoring API and strict preset acceptance, without Manim."""
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from optodraw import Beam, OnChipPhotodetector, Photodiode, presets
import optodraw.animation_engine as engine


def _attach_output_detectors(scene, name):
    """Measure intentional external outputs without changing the presets."""
    parts = tuple(scene.walk())
    if name == 'ring_resonator_chip':
        outputs = [(part, 'f1') for part in parts if part.label == 'Thru']
        assert len(outputs) == 1
    elif name == 'mzm_mesh_chip':
        outputs = [(part, 'o2') for part in parts
                   if part.component_type == 'Waveguide' and part.label.startswith('out ')]
        assert len(outputs) == 4
    elif name == 'raman':                                   # the LED splitter's spare half, open in the figure
        outputs = [(part, 'trans') for part in parts if part.label == 'BS']
        assert len(outputs) == 1
    else:
        return
    for index, (part, port_name) in enumerate(outputs):
        port = part.world_port(port_name)
        angle = math.radians(port.orientation_deg)
        center = (port.center.x + 60 * math.cos(angle), port.center.y + 60 * math.sin(angle))
        detector_type = OnChipPhotodetector if name == 'mzm_mesh_chip' else Photodiode
        detector = scene.add(detector_type(center=center, angle=port.orientation_deg,
                                           label=f'Acceptance detector {index + 1}'))
        if name == 'mzm_mesh_chip':
            scene.route((part, port_name), (detector, 'o1'), kind='waveguide', path_type='smooth')
        else:
            scene.add(Beam((part, port_name), (detector, 'in')))


def test_authoring_public_api_without_manim():
    names = ('Animation Timeline Style Quantity AnimationError SignalState build_graph '
             'compile_signal_state sweep_steady_state Create FadeIn FadeOut Indicate Dim Label '
             'Arrow Write Transform MoveAlong Flow Zoom Pan Fit Morph Set Sweep Plot Wait Click Sequence Lagged').split()
    assert all(hasattr(engine, name) for name in names)
    assert set(names) <= set(engine.__all__)
    result = subprocess.run([sys.executable, '-c',
                             'import sys; import optodraw.animation_engine; assert "manim" not in sys.modules'],
                            cwd=Path(__file__).parents[1], env=os.environ.copy(), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('name', list(presets.PRESETS))
def test_every_preset_strict_auto_click_round_trip(name):
    scene = presets.PRESETS[name]()
    _attach_output_detectors(scene, name)
    animation = engine.Animation(scene, strict=True)
    parts = animation.scene_parts()
    assert isinstance(parts, tuple)
    assert parts
    if name == 'ring_resonator_chip':
        targets = [part for part in parts if part.label == 'In']
        assert len(targets) == 1
        animation.input(targets[0], 'f1')
    elif name == 'coherent_receiver_chip':
        targets = [part for part in parts if part.label in ('Signal', 'LO')]
        assert len(targets) == 2
        for part in targets:
            animation.input(part, 'f1')
    elif name == 'free_space_breadboard':                     # the light under test enters through iris 1
        targets = [part for part in parts if part.label == 'Iris 1']
        assert len(targets) == 1
        animation.input(targets[0], 'in', wavelength_nm=1090.0)
    elif name == 'mzm_mesh_chip':
        targets = [part for part in parts if part.component_type == 'Waveguide' and part.label.startswith('in ')]
        assert len(targets) == 4
        for part in targets:
            animation.input(part, 'o1')
    animation.auto().click()
    data = animation.timeline.to_json()
    assert data['signal_state']['edges']
    assert data['sections']
    assert engine.Timeline.from_json(data).to_json() == data

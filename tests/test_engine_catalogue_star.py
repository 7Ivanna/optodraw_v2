"""The generic star matrix is reciprocal and cannot amplify coherent inputs."""
import numpy as np
import pytest

import optodraw
from optodraw.animation_engine.behaviours import behaviour_for
from optodraw.animation_engine.behaviours.geometry import port_xy


@pytest.mark.parametrize("inputs,outputs", [(4, 4), (1, 8), (8, 3)])
def test_fourier_star_is_passive_reciprocal_and_uses_apertures(inputs, outputs):
    part = optodraw.StarCoupler(input_count=inputs, output_count=outputs)
    behaviour = behaviour_for(part, "star1")
    matrix = np.zeros((outputs, inputs), dtype=complex)
    lengths = set()
    for i in range(inputs):
        port = f"i{i+1}"
        for transfer in behaviour.transfers(part, "star1", port, 1550, {}):
            j = int(transfer.out_port[1:])-1
            matrix[j, i] = transfer.matrix[0, 0]
            lengths.add(transfer.length)
            assert len(transfer.points) == 4
            assert transfer.points[0] == pytest.approx(port_xy(part, port))
            assert transfer.points[-1] == pytest.approx(port_xy(part, transfer.out_port))
            reverse = next(t for t in behaviour.transfers(part, "star1", transfer.out_port, 1550, {})
                           if t.out_port == port)
            assert reverse.matrix[0, 0] == pytest.approx(transfer.matrix[0, 0])
    n = max(inputs, outputs)
    expected = np.exp(2j*np.pi*np.arange(outputs)[:, None]*np.arange(inputs)/n)/np.sqrt(n)
    assert np.allclose(matrix, expected)
    assert np.linalg.svd(matrix, compute_uv=False)[0] <= 1+1e-12
    assert len(lengths) == 1
    coherent = np.ones(inputs)/np.sqrt(inputs)
    assert np.linalg.norm(matrix@coherent)**2 <= 1+1e-12
    if inputs == outputs:
        assert np.allclose(matrix.conj().T@matrix, np.eye(inputs))

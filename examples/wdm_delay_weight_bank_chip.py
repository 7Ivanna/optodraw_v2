"""Render the broadcast-and-weight network chip (Tait et al. 2017), the ``wdm_delay_weight_bank_chip`` preset."""

from optodraw import build_preset


def main() -> None:
    scene = build_preset("wdm_delay_weight_bank_chip")
    scene.render_svg("examples/wdm_delay_weight_bank_chip.svg")
    scene.render_threejs("examples/wdm_delay_weight_bank_chip.html", camera_distance=220)


if __name__ == "__main__":
    main()
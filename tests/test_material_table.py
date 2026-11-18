"""One material table: the old colours stay, and every material the spec names has a fill and a label."""

from __future__ import annotations

from pathlib import Path

from optodraw.core.markup import plain
from optodraw.gds import palette, styles

# The eleven entries of the old section palette, as they were before the merge.
OLD = {
    "silicon": ("#9aa9bd", "Si"),
    "polysilicon": ("#b6a8c9", "Poly-Si"),
    "sio2": ("#e6eff7", "SiO2"),
    "silicon_nitride": ("#93c9a0", "SiN"),
    "germanium": ("#c9a0d6", "Ge"),
    "aluminum": ("#c3c8cf", "Al"),
    "aluminium": ("#c3c8cf", "Al"),
    "copper": ("#d08b5b", "Cu"),
    "tungsten": ("#7d8590", "W"),
    "titanium_nitride": ("#b08d57", "TiN"),
    "gold": ("#e0b84f", "Au"),
}
SPEC = ("lithium_niobate", "lithium_tantalate", "indium_phosphide", "ingaasp", "ingaas", "gallium_arsenide",
        "aluminum_nitride", "barium_titanate", "indium_tin_oxide", "silicon_carbide", "platinum", "titanium", "bcb",
        "polyimide", "sapphire", "air")
# The union of the old metal sets: the section palette, the process steps and the stack loader.
OLD_METALS = {"aluminum", "aluminium", "copper", "gold", "tungsten", "titanium", "titanium_nitride", "metal",
              "nichrome", "platinum"}


def test_one_material_table():
    # Mutants that must fail it: one old fill changed; one spec material taken out; two keys given one fill;
    # an old metal no longer a metal.
    assert {name: (palette.material_fill(name), plain(palette.material_label(name))) for name in OLD} == OLD
    for name in SPEC:
        entry = palette.MATERIALS.get(name)
        assert entry is not None and entry.fill and entry.label, name
    fills = [entry.fill for entry in palette.MATERIALS.values()]
    assert len(set(fills)) == len(fills)
    assert all(palette.is_metal(name) for name in OLD_METALS)
    assert styles.GDS_MATERIAL_ALIASES is palette.ALIASES
    assert palette.canonical("LiNbO3") == "lithium_niobate"
    assert not (Path(palette.__file__).parent / "xsection" / "palette.py").exists()

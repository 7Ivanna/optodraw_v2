#!/usr/bin/env python3
"""Bake an open gdsfactory PDK's layer stack into a bundled optodraw stack YAML.

This is a *maintainer* tool — run it once when adding a foundry, commit the YAML,
and every optodraw user gets that PDK with no install (PhotonForge-style curation).
The PDK package is only needed here, at extraction time, not at runtime.

Usage
-----
    # install the open PDK once (in a dev env), then extract:
    pip install ubcpdk
    python scripts/extract_pdk_stack.py ubcpdk --name siepic_ebeam --label "SiEPIC EBeam (UBC)"

    # built-in gdsfactory generic (no extra package):
    python scripts/extract_pdk_stack.py generic --name gdsfactory_generic --label "gdsfactory generic (open)"

    # CornerStone (cspdk):
    python scripts/extract_pdk_stack.py cspdk.si500 --name cornerstone_si500 --label "CornerStone Si 500 nm (open)"

The output is written to optodraw/gds/stacks/<name>.yaml.
"""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

_STACKS_DIR = Path(__file__).resolve().parent.parent / "optodraw" / "gds" / "stacks"


def _load_pdk(module: str):
    if module in ("generic", "", "gdsfactory"):
        try:
            from gdsfactory.gpdk import PDK as pdk
        except Exception:
            from gdsfactory.generic_tech import get_generic_pdk

            pdk = get_generic_pdk()
        return pdk
    mod = importlib.import_module(module)
    pdk = getattr(mod, "PDK", None)
    if pdk is None:
        raise SystemExit(f"module '{module}' has no PDK object")
    return pdk


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("module", help="PDK module path (e.g. ubcpdk, cspdk.si500) or 'generic'")
    ap.add_argument("--name", required=True, help="output stack file stem (-> stacks/<name>.yaml)")
    ap.add_argument("--label", default="", help="human label stored as the stack 'name'")
    ap.add_argument("--units", default="um")
    args = ap.parse_args()

    from optodraw.gds.technology import get_gdsfactory_layer_styles

    pdk = _load_pdk(args.module)
    pdk.activate()
    styles = get_gdsfactory_layer_styles(pdk=pdk)

    rows: list[str] = []
    for spec, st in sorted(styles.items(), key=lambda kv: (kv[1].get("zmin") or 0.0, kv[0])):
        thickness = st.get("thickness")
        if not thickness or thickness <= 0:
            continue  # skip drawing-only / zero-thickness layers
        key = f"{spec[0]}/{spec[1]}"
        name = st.get("name") or key
        zmin = round(float(st.get("zmin") or 0.0), 4)
        th = round(float(thickness), 4)
        mat = st.get("material_preset") or "silicon"
        color = st.get("color") or "#888888"
        rows.append(
            f'  "{key}": {{name: {name}, zmin: {zmin}, thickness: {th}, '
            f'material: {mat}, color: "{color}"}}'
        )

    if not rows:
        raise SystemExit(f"PDK '{args.module}' produced no layers with thickness")

    label = args.label or getattr(pdk, "name", args.name)
    text = (
        f"# Auto-extracted from gdsfactory PDK '{args.module}' by scripts/extract_pdk_stack.py.\n"
        f"# z + thickness in microns (z = 0 = bottom of the device layer). Open PDK — safe to bundle.\n\n"
        f"name: {label}\n"
        f"units: {args.units}\n"
        f"layers:\n" + "\n".join(rows) + "\n"
    )
    out = _STACKS_DIR / f"{args.name}.yaml"
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}  ({len(rows)} layers)")


if __name__ == "__main__":
    main()

# Bundled GDS layer stacks

These YAML files give imported GDS layouts real **z-offset + thickness** (per GDS
layer) so the 3D view and cross-sections are physically correct. They ship with
optodraw, so users never install a PDK — pick one from the **Foundry stack**
dropdown in the GDS inspector. (PhotonForge-style curation, not gdsfactory-style
`pip install`.)

## What's here
- `gdsfactory_generic.yaml`, `cornerstone_si500.yaml`, `cornerstone_sin300.yaml` —
  open PDKs, extracted from their packages (accurate, redistributable).
- `lnoi400.yaml`, `ltoi300.yaml`: thin-film lithium niobate and lithium tantalate on
  insulator, from Luxtelligence's open PDK (lxt_pdk_gf, MIT, commit d16db6a). Each
  entry cites its line in `tech.py` or `layers.yaml`; the file keeps the MIT notice.
- `inp_generic.yaml`: literature stack, the passive InP generic-integration wafer
  (COBRA), from Augustin's thesis Table 2.1 and Smit et al. 2014. No oxide: InP under
  and over the InGaAsP core, and a polyimide fill.
- `bto_generic.yaml`: literature stack, BaTiO3 on silicon under a Si strip waveguide,
  from Eltes et al., arXiv:1904.10902.
- `_template.yaml` — the blank template (files starting with `_` are download-only,
  not shown in the apply dropdown). Served at `GET /api/stacks/template`.

A PDK or literature stack gives `source:` and `provenance:` (`pdk`, `literature` or
`model`) on every entry with a number. A literature stack starts with
`# literature stack` and names in its header what is model.

## Adding a foundry (maintainer workflow)
Open PDKs ship as gdsfactory packages. Extract once, commit the YAML, ship to all:

```bash
pip install ubcpdk                                   # SiEPIC EBeam (one-time, dev only)
python scripts/extract_pdk_stack.py ubcpdk \
    --name siepic_ebeam --label "SiEPIC EBeam (UBC)"
```

The PDK package is **not** a runtime dependency — only needed for this extraction.
Installed PDKs are also auto-listed live in the **Installed PDK** dropdown
(`_KNOWN_PDKS` in `optodraw/app/api.py`).

## NDA foundries
Never bundled. Users copy `_template.yaml`, fill in their process numbers, and load
it privately via **Attach tech / stack file**.

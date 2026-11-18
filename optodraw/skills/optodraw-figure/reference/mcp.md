# optodraw over MCP

`pip install optodraw`, then run `optodraw-mcp` as a stdio MCP server.
Its tools take a scene spec: `title`, `components` as
`{type, center, angle, ...}`, and `beams` as `{path, wavelength}`.

| tool | what it does |
|---|---|
| `optodraw_list_components`, `optodraw_list_onchip_components` | the catalog |
| `optodraw_list_presets`, `optodraw_list_workflows` | presets, workflows, templates |
| `optodraw_create_setup` | builds a scene and writes its SVG and 3D page |
| `optodraw_render_3d`, `optodraw_export_interactive_html` | the 3D view |
| `optodraw_build_publication_bundle` | a paper figure bundle |
| `optodraw_export_xsection_bundle` | a process cross-section from a process YAML |
| `optodraw_physics_timeline_hints`, `optodraw_compile_physics_animation` | the older animation timeline, not the engine of the `optodraw-animation` skill |

When you can run Python, prefer the Python API: it has every option, the
checks (`run_checks`, `check_stack`, `check_part_3d`) and the objects you need
for the review.

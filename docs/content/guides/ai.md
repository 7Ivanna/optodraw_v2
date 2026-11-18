optodraw ships agent skills and an MCP server, so an AI assistant can build, check and render scenes
for you.

## Agent skills

Skills are instructions that Claude Code, Codex and other agents read before they use optodraw. Install
them once:

```bash
optodraw-skills install             # or --project for one project
```

`optodraw-figure` makes a paper figure and checks it, `optodraw-layout` keeps chip layouts right,
`optodraw-component` makes a part of your own, `optodraw-gds-3d` turns a GDS file into 3D and checks
its layer stack, and `optodraw-animation` animates the light. Every example in them runs in the test
suite.

## The MCP server

Install the `mcp` extra and add the server to your assistant's MCP settings:

```json
{
  "mcpServers": {
    "optodraw": { "command": "optodraw-mcp", "args": [] }
  }
}
```

## What the assistant can do

- `optodraw_list_components`: find parts by name, kind or platform.
- `optodraw_create_setup`: build a scene from a description.
- `optodraw_render_3d`: render the scene in 3D.

The assistant writes ordinary optodraw scenes. Open them in Python or in the [editor](/guides/editor/)
and check them as you would check your own: the [layout rules](/chips/) still apply.

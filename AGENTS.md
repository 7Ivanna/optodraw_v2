# Agent instructions

Do not commit unless the user asks. Prefer split PRs for review. No proprietary PDK content in the repository.

## Building or debugging a scene

Read **[optodraw/skills/optodraw-layout/SKILL.md](optodraw/skills/optodraw-layout/SKILL.md)**
before placing components or writing routes. Optodraw renders a broken layout
exactly as cleanly as a correct one, and that skill collects the failures that
look fine in code: components placed on port spacing instead of drawn extent,
rotated components whose port order reverses, channel spacing that puts
waveguides off the slab, and ports nobody connected.

## Agent skills

The skills in `optodraw/skills/` ship in the package (`optodraw-skills install`); `.claude/skills/` and
`.agents/skills/` link to them. `tests/test_skills.py` runs every python block in them, so an API change
that breaks a skill fails the suite: fix the skill in the same change.

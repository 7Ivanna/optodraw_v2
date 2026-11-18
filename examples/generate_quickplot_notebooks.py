"""Generate quickplot notebooks for Optodraw component smoke checks."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def _source(text: str) -> list[str]:
    body = dedent(text).strip("\n")
    return [f"{line}\n" for line in body.splitlines()]


def _markdown(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _source(text)}


def _code(text: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": _source(text),
    }


def _notebook(cells: list[dict]) -> dict:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "pygments_lexer": "ipython3",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _registry_notebook(
    *,
    title: str,
    group: str,
    platform: str,
    columns: int,
    output_name: str,
) -> dict:
    return _notebook(
        [
            _markdown(
                f"""
                # {title}

                Registry-driven quickplot for this component family. Run the notebook after editing
                component geometry, ports, schematic tables, or renderer dispatch to catch visual
                smoke-test failures quickly.
                """
            ),
            _code(
                """
                from pathlib import Path
                import sys

                repo = Path.cwd()
                if (repo / "examples").exists():
                    sys.path.insert(0, str(repo))
                    sys.path.insert(0, str(repo / "examples"))
                """
            ),
            _code(
                f"""
                from quickplot_helpers import build_quickplot_scene, registry_component_names

                names = registry_component_names("{group}")
                print(f"Component count: {{len(names)}}")
                names
                """
            ),
            _code(
                f"""
                scene, failures = build_quickplot_scene(
                    names,
                    title="{title}",
                    platform="{platform}",
                    columns={columns},
                )
                assert not failures, failures
                drawing = scene.render_svg()
                drawing
                """
            ),
            _code(
                f"""
                output_dir = Path("examples/generated/quickplots")
                output_dir.mkdir(parents=True, exist_ok=True)
                scene.render_svg((output_dir / "{output_name}.svg").as_posix())
                print(output_dir / "{output_name}.svg")
                """
            ),
        ]
    )


def main() -> None:
    notebooks = {
        "quickplot_free_space_components.ipynb": _registry_notebook(
            title="Free-Space Component Quickplot",
            group="free_space",
            platform="free_space",
            columns=6,
            output_name="quickplot_free_space_components",
        ),
        "quickplot_onchip_components.ipynb": _registry_notebook(
            title="On-Chip Component Quickplot",
            group="on_chip",
            platform="on_chip",
            columns=5,
            output_name="quickplot_onchip_components",
        ),
        "quickplot_electronics_packaging_components.ipynb": _registry_notebook(
            title="Electronics And Packaging Component Quickplot",
            group="electronics",
            platform="mixed",
            columns=5,
            output_name="quickplot_electronics_packaging_components",
        ),
    }
    for filename, notebook in notebooks.items():
        path = EXAMPLES / filename
        path.write_text(json.dumps(notebook, indent=2) + "\n", encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()

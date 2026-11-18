"""Notebook helpers for inline interactive display."""

from __future__ import annotations

import html


def threejs_iframe_html(scene, *, height: int = 480, width: str = "100%", **kwargs) -> str:
    """Return an HTML iframe containing the scene's Three.js renderer output."""

    height_px = int(height)
    if height_px <= 0:
        raise ValueError("height must be positive")
    rendered = scene.render_threejs(**kwargs)
    srcdoc = html.escape(rendered, quote=True)
    safe_width = html.escape(str(width), quote=True)
    return (
        f'<iframe title="Interactive Optodraw 3D scene" srcdoc="{srcdoc}" '
        f'style="width:{safe_width};height:{height_px}px;border:1px solid #d0d7de;border-radius:8px;" '
        'sandbox="allow-scripts allow-same-origin"></iframe>'
    )


def threejs_widget(scene, *, height: int = 480, width: str = "100%", **kwargs):
    """Return an ipywidgets output widget, falling back to raw IPython HTML."""

    iframe = threejs_iframe_html(scene, height=height, width=width, **kwargs)
    try:
        import ipywidgets as widgets

        output = widgets.Output(layout=widgets.Layout(width=width, height=f"{height}px"))
        with output:
            from IPython.display import HTML, display

            display(HTML(iframe))
        return output
    except Exception:
        from IPython.display import HTML

        return HTML(iframe)

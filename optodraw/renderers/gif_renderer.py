"""GIF renderer — lightweight animated GIF output via SVG frames + Pillow.

Requires ``pip install optodraw[gif]`` (pillow + cairosvg).

Two built-in animation modes:

- ``"build_up"``: components appear one by one (solids then beams at full length).
- ``"beam_trace"``: same build-up for solids then beams grow step by step.

For structured tutoring videos with per-step captions use
:class:`~optodraw.animation.AnimationTimeline` and call
``timeline.render_gif("out.gif")``.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from optodraw.animation import AnimationTimeline

from optodraw.renderers.frame_states import build_auto_frames, collect_frame_components


class GifRenderer:
    """Renders a Scene to an animated GIF.

    Parameters
    ----------
    scene : Scene
        The optodraw scene to render.
    width : int
        Output raster width in pixels (default 800).
    """

    def __init__(self, scene, **kwargs):
        self.scene = scene
        self.width: int = kwargs.get("width", 800)

    # -- public entry points --------------------------------------------------

    def render(
        self,
        filename: str,
        *,
        fps: int = 6,
        mode: str = "build_up",
        dwell: float = 1.5,
    ) -> None:
        """Render the scene as an animated GIF.

        Parameters
        ----------
        filename : str
            Output file path.
        fps : int
            Playback frame rate (default 6).
        mode : str
            ``"build_up"`` or ``"beam_trace"``.
        dwell : float
            Extra hold time (seconds) on the final frame.
        """
        if fps <= 0:
            raise ValueError("fps must be > 0")
        frames = self._build_frames(mode)
        images = self._render_frames(frames)
        self._save_gif(images, filename, fps=fps, dwell=dwell)

    def render_from_timeline(
        self, filename: str, timeline: "AnimationTimeline", *, fps: int = 6, dwell: float = 1.0
    ) -> None:
        """Render using an explicit :class:`~optodraw.animation.AnimationTimeline`."""
        if fps <= 0:
            raise ValueError("fps must be > 0")
        frames = timeline._to_frame_states()
        images = self._render_frames(frames)
        self._save_gif(images, filename, fps=fps, dwell=dwell)

    # -- automatic frame building ---------------------------------------------

    def _collect_components(self) -> tuple[list, list]:
        """Separate scene components into (solids, beams_and_routes)."""
        return collect_frame_components(self.scene)

    def _build_frames(self, mode: str) -> list[dict]:
        """Return ordered list of frame-state dicts ``{hidden_ids, partial_beams}``."""
        return build_auto_frames(self.scene, mode)

    def _render_frames(self, frames: list[dict]) -> list:
        """Rasterize each frame state to a PIL Image."""
        try:
            import cairosvg
            from PIL import Image
        except ImportError as error:
            raise ImportError(
                "Pillow and cairosvg are required for GIF output.\n"
                "Install with: pip install optodraw[gif]"
            ) from error
        except OSError as error:
            # cairosvg installs from a wheel but binds the SYSTEM cairo library,
            # which macOS does not ship. "install optodraw[gif]" is useless
            # advice to somebody who just did exactly that.
            raise ImportError(
                f"cairosvg could not load the native cairo library ({error}).\n"
                "macOS: brew install cairo · Debian/Ubuntu: apt install libcairo2\n"
                "Windows: install GTK runtime, or use SVG output instead."
            ) from error

        from optodraw.renderers.svg_renderer import SvgRenderer

        images = []
        for state in frames:
            renderer = SvgRenderer(
                self.scene,
                hidden_ids=state.get("hidden_ids", set()),
                partial_beams=state.get("partial_beams", {}),
                traveling_waves=state.get("traveling_waves", {}),
                highlight_levels=state.get("highlight_levels", {}),
                show_polarization_overlay=bool(state.get("polarization_overlays")),
                polarization_overlays=state.get("polarization_overlays", {}),
                polarization_caption=state.get("polarization_caption", ""),
            )
            svg_drawing = renderer.render()
            svg_str = svg_drawing.as_svg()
            png_bytes = cairosvg.svg2png(
                bytestring=svg_str.encode(), output_width=self.width
            )
            img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
            # The SVG background is transparent and a GIF palette frame drops alpha: put it on white.
            images.append(Image.alpha_composite(Image.new("RGBA", img.size, "white"), img).convert("RGB"))
        return images

    def _save_gif(self, images: list, filename: str, *, fps: int, dwell: float) -> None:
        from PIL import Image

        if not images:
            return
        if fps <= 0:
            raise ValueError("fps must be > 0")

        # GIF frame delays use centiseconds; keep the closest representable rate.
        frame_ms = max(10, round(100 / fps) * 10)
        dwell_ms = max(frame_ms, round(dwell * 100) * 10)

        palette = [img.convert("P", palette=Image.ADAPTIVE, colors=256) for img in images]
        durations = [frame_ms] * (len(palette) - 1) + [dwell_ms]

        palette[0].save(
            filename,
            save_all=True,
            append_images=palette[1:],
            loop=0,
            duration=durations,
            optimize=True,
        )

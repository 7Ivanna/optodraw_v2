"""Script-context escaping in Three.js HTML export.

Scene titles, component labels and layer legend fields flow into the exported
HTML. A raw value such as ``</script><script>alert(1)</script>`` used to close
the page's own script element; every JSON payload and text interpolation must
be inert.
"""

from __future__ import annotations

from optodraw import Scene
from optodraw.components.devices import Laser

PAYLOAD = '</script><script>alert("xss")</script>'


class TestThreeJsHtmlEscaping:
    def test_hostile_title_cannot_break_out_of_script(self):
        scene = Scene(title=PAYLOAD, platform="free_space")
        scene.add(Laser(center=(0, 0), label="Laser"))

        html = scene.render_threejs()

        assert "</script><script" not in html
        assert "</title><script>" not in html
        assert "&lt;/script&gt;&lt;script&gt;" in html or "&lt;/script" in html

    def test_hostile_component_label_is_escaped_in_scene_data(self):
        scene = Scene(platform="free_space")
        scene.add(Laser(center=(0, 0), label=PAYLOAD))

        html = scene.render_threejs()

        # the payload can never close a real script element and open its own
        assert "</script><script" not in html
        assert 'alert("xss")' not in html

    def test_json_payload_uses_unicode_escapes(self):
        from optodraw.renderers.threejs_renderer import _json_script_safe

        text = _json_script_safe({"label": PAYLOAD})
        assert "<" not in text
        assert ">" not in text
        assert "&" not in text
        assert "\\u003c" in text
        # stays valid JSON
        import json

        assert json.loads(text)["label"] == PAYLOAD

    def test_layer_legend_fields_are_html_escaped(self):
        scene = Scene(platform="free_space")
        scene.add(Laser(center=(0, 0), label="Laser"))

        html = scene.render_threejs(
            layer_legend=[
                {
                    "label": '<img src=x onerror="alert(1)">',
                    "color": '#ff0000"><script>',
                    "description": '"></textarea>',
                }
            ]
        )

        assert '<img src=x' not in html
        assert '" onerror' not in html.split("layer-legend")[1].split("</div>")[0]
        escaped_label = "&lt;img src=x onerror=&#x27;alert(1)&#x27;&gt;"
        assert escaped_label in html or "&lt;img src=x" in html

    def test_benign_titles_render_readable_text(self):
        scene = Scene(title="Fold & focus", platform="free_space")
        scene.add(Laser(center=(0, 0)))

        html = scene.render_threejs()

        assert "Fold &amp; focus" in html

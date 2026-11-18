"""Schema 3 carries immutable user definitions without an installed library."""

import base64
import json

import pytest

from optodraw import Component, PartLibrary, Scene, UserPart, define_part, register_part
from optodraw.app.workspaces import WorkspaceStore
from optodraw.schema import component_from_spec, component_to_spec


SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -5 20 10"><path d="M-10 0L10 0L0 5Z"/></svg>'
PORTS = [{"name": "in", "center": [-10, 0], "orientation_deg": 180, "width": 0.5},
         {"name": "out", "center": [10, 0], "orientation_deg": 0, "width": 0.5}]


def factory(library=None, **kwargs):
    fields = {"ports": PORTS, "symbol_2d": SVG,
              "parameters": {"gain": {"type": "float", "default": 1, "min": 0, "unit": "dB"}}}
    fields.update(kwargs)
    return define_part("user:example/Tap", platform="on_chip", library=library or PartLibrary(), **fields)


def scene_spec():
    scene = Scene(platform="on_chip")
    source = factory()
    a = scene.add(source(center=(0, 0), label="first", gain=0.5, scale=2))
    b = scene.add(source(center=(70, 0), label="second"))
    scene.route((a, "out"), (b, "in"), backend="local")
    return scene.to_spec()


def test_component_round_trip_and_nested_group_keep_variant_and_placement():
    definition = factory(ports=None, symbol_2d=None, variants={
        "a": {"ports": PORTS, "symbol_2d": SVG},
        "b": {"ports": PORTS, "symbol_2d": SVG.replace("L0 5", "L0 4")}}, default_variant="a")
    node = definition(center=(20, 30, 4), angle=90, scale=2, variant="b")
    spec = component_to_spec(node)
    restored = component_from_spec(json.loads(json.dumps(spec)))
    assert restored.variant == "b" and restored.transform.position.z == 4
    assert restored.world_port("out").center.y == pytest.approx(50)
    scene = Scene()
    group = scene.group(label="group")
    group.transform.position.z = 5
    group.add(node)
    copy = Scene.from_spec(scene.to_spec())
    assert copy.to_spec() == scene.to_spec()
    copied_part = next(node for node in copy.walk() if isinstance(node, UserPart))
    assert copied_part.world_transform.position.z == 9


@pytest.mark.parametrize("case", ["asset_data", "asset_hash", "definition", "reference", "missing_asset", "type"])
def test_corrupt_or_missing_portable_data_is_a_named_error(case):
    spec = scene_spec()
    digest = next(iter(spec["part_definitions"]))
    asset_hash = next(iter(spec["assets"]))
    if case == "asset_data":
        spec["assets"][asset_hash]["data"] = base64.b64encode(b"wrong").decode()
    elif case == "asset_hash":
        spec["assets"]["../outside"] = spec["assets"].pop(asset_hash)
    elif case == "definition":
        spec["part_definitions"][digest]["description"] = "modified"
    elif case == "reference":
        spec["components"][0]["part_definition"] = "0" * 64
    elif case == "missing_asset":
        spec["assets"].clear()
    else:
        spec["components"][0]["type"] = "Lens"
    with pytest.raises(ValueError, match="asset|definition|hash|type"):
        Scene.from_spec(spec)


def test_trusted_python_part_reloads_as_portable_art_without_importing_its_class():
    library = PartLibrary()

    @register_part("user:example/Trusted", library=library,
                   parameters={"length": {"type": "float", "default": 20, "min": 1}})
    class Trusted(Component):
        def __init__(self, length=20, **kwargs):
            super().__init__(**kwargs)
            self.length = length

        def portable_definition(self, params):
            return factory(symbol_2d=SVG.replace("L0 5", f'L0 {params["length"] / 4:g}')).definition

    source = library.get("user:example/Trusted")(length=12)
    scene = Scene()
    scene.add(source)
    from optodraw.renderers.threejs_renderer import ThreeJsRenderer

    assert any(item.get("geometry", {}).get("schematic")
               for item in ThreeJsRenderer(scene)._collect_scene_data())
    copy = Scene.from_spec(scene.to_spec())
    restored = next(node for node in copy.walk() if isinstance(node, UserPart))
    assert not isinstance(restored, Trusted)
    assert restored.parameters["length"] == 12
    assert "L0 3" in restored.geometry_2d()["svg"]


def test_embedded_scenes_cannot_resolve_workspace_hashes_as_files(tmp_path):
    store = WorkspaceStore(tmp_path)
    store.save("Example", scene_spec())
    references = json.loads((tmp_path / "Example.json").read_text())
    with pytest.raises(ValueError, match="embedded bytes"):
        Scene.from_spec(references)


def test_individual_user_part_preview_keeps_immutable_definition():
    node = factory()(center=(50, 20), gain=0.5)
    scene = node.preview_scene()
    assert scene.platform == "on_chip"
    copy = next(part for part in scene.walk() if isinstance(part, UserPart))
    assert copy is not node and copy.definition is node.definition
    assert copy.parameters == node.parameters
    assert copy.transform.position.x == 0
    assert node.transform.position.x == 50


def test_failed_blob_write_preserves_the_previous_workspace(tmp_path, monkeypatch):
    import optodraw.parts.serialization as serialization

    store = WorkspaceStore(tmp_path)
    store.save("Example", scene_spec())
    previous = (tmp_path / "Example.json").read_bytes()
    new_scene = Scene()
    new_scene.add(factory(symbol_2d=SVG.replace("L0 5", "L0 4"))())

    def fail(*args):
        raise OSError("blob write failed")

    monkeypatch.setattr(serialization.os, "link", fail)
    with pytest.raises(OSError, match="blob write failed"):
        store.save("Example", new_scene.to_spec())
    assert (tmp_path / "Example.json").read_bytes() == previous
    assert not list((tmp_path / ".assets").glob(".blob-*"))


def test_workspace_asset_symlink_cannot_leave_the_asset_folder(tmp_path):
    from optodraw.parts.serialization import AssetStore

    spec = scene_spec()
    digest = next(iter(spec["assets"]))
    directory = tmp_path / "assets"
    directory.mkdir()
    outside = tmp_path / "outside.svg"
    outside.write_bytes(base64.b64decode(spec["assets"][digest]["data"]))
    (directory / digest).symlink_to(outside)
    spec["assets"][digest] = {"media_type": "image/svg+xml", "ref": digest}
    with pytest.raises(ValueError, match="leaves the asset folder"):
        AssetStore(directory).hydrate(spec)

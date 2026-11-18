"""Lossless shared geometry and material records for browser scenes."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import marshal
import sys
from typing import Any


def pack_scene_data(items: list[dict[str, Any]], *, copy_records: bool = True) -> dict[str, Any]:
    """Pack without mutation; immediate serializers can borrow nested records."""
    geometries: dict[str, Any] = {}
    materials: dict[str, Any] = {}
    geometry_ids: dict[int, str] = {}
    material_ids: dict[int, str] = {}
    encoded_ids: dict[Any, str] = {}
    scalar_types = frozenset((str, int, bool, type(None)))
    field_order = {}

    def flat_value(value):
        kind = type(value)
        if kind in scalar_types:
            return (kind, value)
        if kind is float:
            return (kind, repr(value)) if value == 0 else (kind, value)
        if kind in (list, tuple) and len(value) <= 4:
            values = tuple(flat_value(item) for item in value)
            if all(item is not None for item in values):
                return (list, values)
        return None

    def intern(record: Any, table: dict[str, Any]) -> str:
        # Fingerprints stay in memory. Saved records still use canonical JSON hashes.
        lookup = None
        if sys.version_info >= (3, 13):
            try:
                lookup = marshal.dumps(record, 2, allow_code=False)
            except (ValueError, TypeError):
                pass
        simple = False
        if lookup is None:
            names = tuple(record)
            order = field_order.get(names)
            if order is None:
                order = tuple(sorted(names))
                field_order[names] = order
            flat = tuple((name, flat_value(record[name])) for name in order)
            simple = all(isinstance(name, str) and value is not None for name, value in flat)
            lookup = flat if simple else json.dumps(
                record, sort_keys=True, separators=(",", ":"), default=str
            )
        key = encoded_ids.get(lookup)
        if key is None:
            encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str) if not isinstance(lookup, str) else lookup
            key = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            encoded_ids[lookup] = key
        table.setdefault(key, record)
        return key

    def geometry(record: dict[str, Any]) -> str:
        identity = id(record)
        if identity in geometry_ids:
            return geometry_ids[identity]
        record = dict(record)
        if isinstance(record.get("material"), dict):
            material = record.pop("material")
            material_identity = id(material)
            key = material_ids.get(material_identity)
            if key is None:
                key = intern(material, materials)
                material_ids[material_identity] = key
            record["materialRef"] = key
        if isinstance(record.get("children"), list):
            record["children"] = [{"geometryRef": geometry(child)} for child in record["children"]]
        key = intern(record, geometries)
        geometry_ids[identity] = key
        return key

    packed = []
    for original in items:
        item = dict(original)
        if isinstance(item.get("geometry"), dict):
            item["geometryRef"] = geometry(item.pop("geometry"))
        packed.append(item)
    # Copy only the deduplicated packet, not thousands of repeated source records.
    packet = {"schema": 1, "items": packed, "geometries": geometries, "materials": materials}
    return deepcopy(packet) if copy_records else packet


def expand_scene_data(data: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return deepcopy(data)

    def geometry(key: str) -> dict[str, Any]:
        try:
            record = deepcopy(data["geometries"][key])
        except KeyError as error:
            raise ValueError(f"missing geometry reference: {key}") from error
        if "materialRef" in record:
            material_key = record.pop("materialRef")
            try:
                record["material"] = deepcopy(data["materials"][material_key])
            except KeyError as error:
                raise ValueError(f"missing material reference: {material_key}") from error
        if isinstance(record.get("children"), list):
            record["children"] = [geometry(child["geometryRef"]) for child in record["children"]]
        return record

    items = deepcopy(data["items"])
    for item in items:
        if "geometryRef" in item:
            item["geometry"] = geometry(item.pop("geometryRef"))
    return items

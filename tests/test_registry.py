"""Tests for the unified component registry."""

from __future__ import annotations


from optodraw.catalog import list_components
from optodraw.registry import (
    creatable_component_names,
)


class TestRegistryCatalogAlignment:
    def test_catalog_and_registry_same_keys(self):
        catalog_names = set(list_components())
        registry_names = set(creatable_component_names())
        assert catalog_names == registry_names



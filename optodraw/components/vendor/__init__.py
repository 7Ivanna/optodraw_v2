"""Vendor catalogue parts drawn to scale from the vendors' published drawings (Thorlabs) and specification pages
(Edmund Optics, Allied Vision). Each family takes a ``part`` number; :mod:`.data` holds the dimensions."""

from optodraw.components.vendor.parts import (
    FAMILIES,
    CatalogAdapter,
    CatalogCageCube,
    CatalogCageMount,
    CatalogCamera,
    CatalogCollimator,
    CatalogCubeSplitter,
    CatalogDichroic,
    CatalogFilter,
    CatalogGlanPolarizer,
    CatalogHardware,
    CatalogLED,
    CatalogLens,
    CatalogLensTube,
    CatalogMirror,
    CatalogNDFilter,
    CatalogPhotodiode,
    CatalogPlateSplitter,
    CatalogPolarizer,
    CatalogRightAngleMount,
    CatalogSleeve,
    CatalogTableClamp,
    CatalogWavePlate,
)

__all__ = [cls.__name__ for cls in FAMILIES] + ["FAMILIES"]

import ipfs_datasets_py.logic.types as types
from ipfs_datasets_py.logic.types import bridge_types
from ipfs_datasets_py.logic.common import converters


def test_bridge_conversion_aliases_point_to_bridge_types() -> None:
    assert types.BridgeConversionStatus is bridge_types.ConversionStatus
    assert types.BridgeConversionResult is bridge_types.ConversionResult

    # Backward-compat: existing exports still refer to bridge conversion types.
    assert types.ConversionStatus is bridge_types.ConversionStatus
    assert types.ConversionResult is bridge_types.ConversionResult


def test_converter_and_bridge_conversion_types_are_distinct() -> None:
    assert converters.ConversionStatus is not bridge_types.ConversionStatus
    assert converters.ConversionResult is not bridge_types.ConversionResult

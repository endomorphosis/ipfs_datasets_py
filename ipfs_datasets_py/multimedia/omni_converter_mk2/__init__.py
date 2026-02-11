"""Deprecated shim for `ipfs_datasets_py.multimedia.omni_converter_mk2`.

Canonical location:
    `ipfs_datasets_py.data_transformation.multimedia.omni_converter_mk2`
"""

from __future__ import annotations

import warnings


warnings.warn(
    "`ipfs_datasets_py.multimedia.omni_converter_mk2` is deprecated; "
    "use `ipfs_datasets_py.data_transformation.multimedia.omni_converter_mk2`.",
    DeprecationWarning,
    stacklevel=2,
)


def __getattr__(name: str):
    from ipfs_datasets_py.data_transformation.multimedia import omni_converter_mk2 as _canonical

    return getattr(_canonical, name)


def __dir__() -> list[str]:
    from ipfs_datasets_py.data_transformation.multimedia import omni_converter_mk2 as _canonical

    return sorted(set(globals().keys()) | set(dir(_canonical)))

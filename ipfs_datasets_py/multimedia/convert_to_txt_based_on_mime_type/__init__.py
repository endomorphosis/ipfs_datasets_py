"""Deprecated shim for `ipfs_datasets_py.multimedia.convert_to_txt_based_on_mime_type`.

Canonical location:
    `ipfs_datasets_py.data_transformation.multimedia.convert_to_txt_based_on_mime_type`
"""

from __future__ import annotations

import warnings


warnings.warn(
    "`ipfs_datasets_py.multimedia.convert_to_txt_based_on_mime_type` is deprecated; "
    "use `ipfs_datasets_py.data_transformation.multimedia.convert_to_txt_based_on_mime_type`.",
    DeprecationWarning,
    stacklevel=2,
)


def __getattr__(name: str):
    from ipfs_datasets_py.data_transformation.multimedia import (
        convert_to_txt_based_on_mime_type as _canonical,
    )

    return getattr(_canonical, name)


def __dir__() -> list[str]:
    from ipfs_datasets_py.data_transformation.multimedia import (
        convert_to_txt_based_on_mime_type as _canonical,
    )

    return sorted(set(globals().keys()) | set(dir(_canonical)))

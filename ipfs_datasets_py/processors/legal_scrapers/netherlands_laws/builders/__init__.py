"""Builder entry points for Netherlands laws datasets and indexes."""

from .ipfs_indexes import main as build_ipfs_indexes
from .ipfs_package import main as build_ipfs_package
from .normalized_package import main as build_normalized_package

__all__ = [
    "build_ipfs_indexes",
    "build_ipfs_package",
    "build_normalized_package",
]

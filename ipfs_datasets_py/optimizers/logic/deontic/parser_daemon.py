"""Compatibility wrapper for the canonical legal parser daemon module."""

from ipfs_datasets_py.optimizers.todo_daemon import legal_parser_daemon as _impl

__all__ = getattr(_impl, "__all__", [])


def __getattr__(name: str):
    return getattr(_impl, name)


def __dir__():
    return sorted(set(globals()) | set(dir(_impl)))

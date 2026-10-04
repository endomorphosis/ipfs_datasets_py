"""MCP dependency access backed by the shared lazy resolver."""

from ipfs_datasets_py.lazy_dependencies import LazyDependencyProxy


_MCP_DEPENDENCIES = (
    "playsound3",
    "openai",
    "duckdb",
    "pandas",
    "pydantic",
    "numpy",
    "tiktoken",
    "multiformats",
)


class _Dependencies(LazyDependencyProxy):
    """Compatibility name retained for MCP utility imports."""


dependencies = _Dependencies(_MCP_DEPENDENCIES, critical_dependencies=())

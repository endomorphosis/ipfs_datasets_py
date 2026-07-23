"""Municipal citation-validator dependencies, resolved only when accessed."""

from ipfs_datasets_py.lazy_dependencies import LazyDependencyProxy


_VALIDATOR_DEPENDENCIES = (
    "bs4",
    "duckdb",
    "jinja2",
    "pandas",
    "pyarrow",
    "pydantic",
    "tqdm",
    "yaml",
)


class _Dependencies(LazyDependencyProxy):
    """Compatibility name retained for validator imports."""


dependencies = _Dependencies(
    _VALIDATOR_DEPENDENCIES,
    critical_dependencies=_VALIDATOR_DEPENDENCIES,
)

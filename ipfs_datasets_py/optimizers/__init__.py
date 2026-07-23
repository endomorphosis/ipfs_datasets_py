"""
IPFS Datasets Python — Optimizers sub-package.

Provides GraphRAG, Logic Theorem, and Agentic optimizer modules.
"""

try:
    from ipfs_datasets_py import __version__
except (ImportError, ModuleNotFoundError, AttributeError):
    __version__ = "unknown"

__all__ = [
    "__version__",
    "LogicPortDaemonConfig",
    "LogicPortDaemonOptimizer",
    "parse_llm_patch_response",
]


def __getattr__(name):
    if name in {"LogicPortDaemonConfig", "LogicPortDaemonOptimizer", "parse_llm_patch_response"}:
        from ipfs_datasets_py.optimizers.logic_port_daemon import (
            LogicPortDaemonConfig,
            LogicPortDaemonOptimizer,
            parse_llm_patch_response,
        )

        return {
            "LogicPortDaemonConfig": LogicPortDaemonConfig,
            "LogicPortDaemonOptimizer": LogicPortDaemonOptimizer,
            "parse_llm_patch_response": parse_llm_patch_response,
        }[name]
    raise AttributeError(name)

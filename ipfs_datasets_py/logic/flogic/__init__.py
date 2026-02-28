"""
F-logic (Frame Logic) integration module.

This package integrates F-logic reasoning into the ipfs_datasets_py logic
stack.  It provides:

* Pure-Python F-logic data types (:mod:`flogic_types`) for representing
  frames, classes, and ontologies — usable without any external binary.
* A wrapper (:mod:`ergoai_wrapper`) for the ErgoAI/ErgoEngine theorem prover
  (submodule at ``ipfs_datasets_py/logic/ErgoAI``).  The wrapper degrades
  gracefully when the binary is absent.
* A proof cache (:mod:`flogic_proof_cache`) using the shared
  :class:`~ipfs_datasets_py.logic.common.proof_cache.ProofCache` so that
  repeated identical queries are never recomputed.
* A ZKP bridge (:mod:`flogic_zkp_integration`) that optionally attests
  F-logic query results with zero-knowledge proofs.

Quick start::

    from ipfs_datasets_py.logic.flogic import (
        CachedErgoAIWrapper, FLogicClass, FLogicFrame,
    )

    ergo = CachedErgoAIWrapper()
    ergo.add_class(FLogicClass("Animal"))
    ergo.add_class(FLogicClass("Dog", superclasses=["Animal"]))
    ergo.add_frame(FLogicFrame("rex", scalar_methods={"name": '"Rex"'}, isa="Dog"))

    # First call — evaluated; subsequent calls with identical goal+ontology
    # are served from the proof cache.
    result = ergo.query("?X : Dog")
    print(result.status, result.from_cache, result.bindings)

See :doc:`README` for full documentation and the ErgoAI tutorial at
https://sites.google.com/coherentknowledge.com/ergoai-tutorial/ergoai-tutorial.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ergoai_wrapper import ErgoAIWrapper, ERGOAI_AVAILABLE, ERGOAI_SUBMODULE_PATH
    from .flogic_types import (
        FLogicStatus,
        FLogicFrame,
        FLogicClass,
        FLogicQuery,
        FLogicOntology,
    )
    from .flogic_proof_cache import (
        FLogicCachedQueryResult,
        CachedErgoAIWrapper,
        get_global_cached_wrapper,
    )
    from .flogic_zkp_integration import (
        FLogicProvingMethod,
        ZKPFLogicResult,
        ZKPFLogicProver,
    )

__all__ = [
    # ErgoAI wrapper
    "ErgoAIWrapper",
    "ERGOAI_AVAILABLE",
    "ERGOAI_SUBMODULE_PATH",
    # F-logic types
    "FLogicStatus",
    "FLogicFrame",
    "FLogicClass",
    "FLogicQuery",
    "FLogicOntology",
    # Proof cache
    "FLogicCachedQueryResult",
    "CachedErgoAIWrapper",
    "get_global_cached_wrapper",
    # ZKP integration
    "FLogicProvingMethod",
    "ZKPFLogicResult",
    "ZKPFLogicProver",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "ErgoAIWrapper": (".ergoai_wrapper", "ErgoAIWrapper"),
    "ERGOAI_AVAILABLE": (".ergoai_wrapper", "ERGOAI_AVAILABLE"),
    "ERGOAI_SUBMODULE_PATH": (".ergoai_wrapper", "ERGOAI_SUBMODULE_PATH"),
    "FLogicStatus": (".flogic_types", "FLogicStatus"),
    "FLogicFrame": (".flogic_types", "FLogicFrame"),
    "FLogicClass": (".flogic_types", "FLogicClass"),
    "FLogicQuery": (".flogic_types", "FLogicQuery"),
    "FLogicOntology": (".flogic_types", "FLogicOntology"),
    "FLogicCachedQueryResult": (".flogic_proof_cache", "FLogicCachedQueryResult"),
    "CachedErgoAIWrapper": (".flogic_proof_cache", "CachedErgoAIWrapper"),
    "get_global_cached_wrapper": (".flogic_proof_cache", "get_global_cached_wrapper"),
    "FLogicProvingMethod": (".flogic_zkp_integration", "FLogicProvingMethod"),
    "ZKPFLogicResult": (".flogic_zkp_integration", "ZKPFLogicResult"),
    "ZKPFLogicProver": (".flogic_zkp_integration", "ZKPFLogicProver"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value

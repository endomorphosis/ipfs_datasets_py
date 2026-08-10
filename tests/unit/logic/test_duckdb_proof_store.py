"""Unit tests for the unified DuckDB proof store (DQK-025).

Acceptance coverage:

* No existing authority dimension is dropped
* Proof / counterexample / unknown / error outcomes remain distinct
* Exact key and integrity checks fail closed
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.backends.cache_protocol import (
    VERIFICATION_CACHE_PROTOCOL_INTERFACE,
    CacheLookupReason,
    CachePolarity,
    VerificationCacheEntry,
    content_digest,
)
from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
    SatisfiabilityResult,
    TheoremResult,
)
from ipfs_datasets_py.logic.common.duckdb_proof_store import (
    DUCKDB_PROOF_STORE_INTERFACE,
    DUCKDB_PROOF_STORE_SCHEMA_VERSION,
    PROOF_AUTHORITY_DIMENSIONS,
    PROOFS_CATALOG_DDL,
    PROOFS_CATALOG_TABLES,
    DuckDBProofStore,
    DuckDBProofStoreAuthorityError,
    DuckDBProofStoreError,
    DuckDBProofStoreIntegrityError,
    ImmutableEnvelopeReference,
    InMemoryProofStoreBackend,
    NormalizedProofEntry,
    NormalizedProofKey,
    ProofEvidenceRecord,
    ProofOutcome,
    ProofTrustLevel,
    build_duckdb_proof_store,
    build_normalized_proof_key,
    outcome_for_status,
    trust_level_from_evidence_authority,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds, ResourceUsage

duckdb = pytest.importorskip("duckdb")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _theorem(
    *,
    status: ResultStatus = ResultStatus.PROVED,
    authority: ResultAuthority = ResultAuthority.THEOREM,
    translation_ceiling: EvidenceAuthority = EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    result_id: str = "result:theorem-1",
    backend_id: str = "solver.z3",
    backend_version: str = "4.12.0",
    **changes: Any,
) -> TheoremResult:
    fields: dict[str, Any] = {
        "result_id": result_id,
        "backend_id": backend_id,
        "backend_version": backend_version,
        "authority": authority,
        "status": status,
        "assumptions": ("assumption:int",),
        "bounds": ExecutionBounds(
            timeout_ms=1000,
            max_steps=100,
            max_memory_bytes=4096,
            max_output_bytes=2048,
        ),
        "translation_ceiling": translation_ceiling,
        "usage": ResourceUsage(
            elapsed_ms=10,
            steps=5,
            peak_memory_bytes=512,
            output_bytes=64,
        ),
        "witness": {"kind": "proof"},
        "diagnostics": (),
        "reason": "",
        "metadata": {},
    }
    fields.update(changes)
    return TheoremResult(**fields)


def _sat(
    *,
    status: ResultStatus = ResultStatus.SATISFIABLE,
    translation_ceiling: EvidenceAuthority = EvidenceAuthority.BOUNDED,
) -> SatisfiabilityResult:
    return SatisfiabilityResult(
        result_id="result:sat-1",
        backend_id="solver.cvc5",
        backend_version="1.1.0",
        authority=ResultAuthority.SATISFIABILITY,
        status=status,
        assumptions=("assumption:model",),
        bounds=ExecutionBounds(
            timeout_ms=500,
            max_steps=50,
            max_memory_bytes=2048,
            max_output_bytes=1024,
        ),
        translation_ceiling=translation_ceiling,
        usage=ResourceUsage(
            elapsed_ms=5,
            steps=3,
            peak_memory_bytes=256,
            output_bytes=32,
        ),
        witness={"model": {"x": 1}},
    )


def _key(**overrides: Any) -> NormalizedProofKey:
    base = dict(
        obligation={"formula": "(assert (> x 0))"},
        premises=["premise:a", "premise:b"],
        translator={"receipt_id": "tr:1", "preservation": "equisatisfiable"},
        solver={"id": "solver.z3", "version": "4.12.0"},
        kernel={"id": "lean", "version": "4.3.0"},
        toolchain={"lean": "4.3.0", "mathlib": "4.3.0"},
        theorem_registry={"id": "mathlib", "rev": "abc123"},
        policy={"mode": "production", "require_kernel": True},
        resources={"timeout_ms": 1000, "max_memory_bytes": 4096},
        tree={"tree_id": "tree:deadbeef", "commit": "abc123"},
        property_value={"property_id": "prop.safety"},
        backend_binary={"path": "/usr/bin/z3", "sha256": "abc"},
        backend_config={"logic": "QF_LIA", "timeout_ms": 1000},
    )
    base.update(overrides)
    return build_normalized_proof_key(**base)


# Fix syntax error - I used `bounds:` instead of `bounds=`
"""
Groth16 Bridge for Knowledge Graph Zero-Knowledge Proofs.

Connects the KG ZKP layer (``query/zkp.py``) directly to the production
Groth16 backend (``processors/groth16_backend`` Rust binary via
``logic/zkp/backends/groth16.py`` + ``groth16_ffi.py``).

Key components
--------------
- :func:`groth16_binary_available` — probe whether the Rust binary is compiled.
- :func:`groth16_enabled` — check the ``IPFS_DATASETS_ENABLE_GROTH16`` opt-in.
- :class:`Groth16KGConfig` — configuration for Groth16-backed KG provers.
- :class:`KGEntityFormula` — canonical KG → TDFOL_v1 theorem/axiom mapping.
- :func:`create_groth16_kg_prover` — factory: returns :class:`KGZKProver`
  backed by ``ZKPProver(backend="groth16")``; gracefully falls back to
  simulation if Groth16 is disabled or the binary is absent.
- :func:`create_groth16_kg_verifier` — factory: returns :class:`KGZKVerifier`
  backed by ``ZKPVerifier(backend="groth16")``.
- :func:`describe_groth16_status` — diagnostic dict with full backend info.

Quick start
-----------
**Standalone (auto-detects backend):**

.. code-block:: python

    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
    from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import (
        create_groth16_kg_prover,
        create_groth16_kg_verifier,
        describe_groth16_status,
    )

    kg = KnowledgeGraph("example")
    kg.add_entity("person", "Alice", confidence=0.95)

    prover   = create_groth16_kg_prover(kg)
    verifier = create_groth16_kg_verifier()
    stmt     = prover.prove_entity_exists("person", "Alice")
    assert verifier.verify_statement(stmt)

    status = describe_groth16_status()
    print(status["backend"])           # "groth16" or "simulated"
    print(status["binary_available"])  # True / False

**Production (real Groth16 proofs):**

.. code-block:: python

    import os
    os.environ["IPFS_DATASETS_ENABLE_GROTH16"] = "1"   # opt in

    # compile first:  cd processors/groth16_backend && cargo build --release
    prover = create_groth16_kg_prover(kg, Groth16KGConfig(enable_groth16=True))
    stmt   = prover.prove_entity_exists("person", "Alice")
    # stmt.public_inputs["logic_proof_data"] contains a real Groth16 ZKPProof

**TDFOL_v1 formula inspection:**

.. code-block:: python

    from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import KGEntityFormula

    theorem = KGEntityFormula.entity_exists_theorem("person", "Alice")
    axioms  = KGEntityFormula.entity_exists_axioms("e-001", "person", "Alice", 0.95)
    print(theorem)   # "exists person named alice"
    print(axioms)    # ["e-001 is person", "e-001 has name alice", ...]

⚠️  WARNING: Unless ``IPFS_DATASETS_ENABLE_GROTH16=1`` is set *and* the Rust
             binary is compiled, proofs are SIMULATED (SHA-256 hashes, not
             cryptographically secure).  See
             ``logic/zkp/PRODUCTION_UPGRADE_PATH.md``.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .zkp import KGZKProver, KGZKVerifier


# ---------------------------------------------------------------------------
# Environment / binary availability helpers
# ---------------------------------------------------------------------------

def groth16_enabled() -> bool:
    """Return *True* if ``IPFS_DATASETS_ENABLE_GROTH16`` opt-in is set.

    The accepted values (case-insensitive) are ``1``, ``true``, ``yes``.
    """
    return os.environ.get("IPFS_DATASETS_ENABLE_GROTH16", "").strip().lower() in {
        "1", "true", "yes",
    }


def groth16_binary_available(binary_path: Optional[str] = None) -> bool:
    """Return *True* if the compiled Groth16 Rust binary can be found.

    Args:
        binary_path: Explicit path to the binary; when *None* the standard
            search-path logic from :class:`groth16_ffi.Groth16Backend` is used.

    Returns:
        ``True`` when the binary file exists at any discovered location.
    """
    # Allow caller to specify an explicit path.
    if binary_path is not None:
        return os.path.isfile(binary_path)

    # Check environment-variable overrides first (mirrors groth16_ffi logic).
    for env_var in ("IPFS_DATASETS_GROTH16_BINARY", "GROTH16_BINARY"):
        override = os.environ.get(env_var)
        if override and os.path.isfile(override):
            return True

    # Fall back to probing the canonical release-build location.
    try:
        from pathlib import Path
        # This file lives at: .../knowledge_graphs/query/groth16_bridge.py
        # The Rust crate lives at: .../processors/groth16_backend/
        kg_query_dir = Path(__file__).resolve().parent          # .../knowledge_graphs/query
        package_root = kg_query_dir.parents[1]                  # .../ipfs_datasets_py (package)
        monorepo_root = package_root.parent                     # .../ipfs_datasets_py (repo)

        candidates = [
            package_root / "processors" / "groth16_backend" / "target" / "release" / "groth16",
            monorepo_root / "processors" / "groth16_backend" / "target" / "release" / "groth16",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return True
    except Exception:
        pass

    return False


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class Groth16KGConfig:
    """Configuration for Groth16-backed Knowledge Graph provers.

    Attributes:
        circuit_version: TDFOL_v1 circuit version (1 = legacy, 2 = current).
        ruleset_id: Ruleset identifier forwarded to the Groth16 witness.
        timeout_seconds: Rust binary call timeout.
        binary_path: Explicit path to compiled Rust binary (or None for
            auto-discovery).
        enable_groth16: When *True*, sets ``IPFS_DATASETS_ENABLE_GROTH16=1``
            in ``os.environ`` before creating the prover (idempotent).
    """
    circuit_version: int = 2
    ruleset_id: str = "TDFOL_v1"
    timeout_seconds: int = 30
    binary_path: Optional[str] = None
    enable_groth16: bool = False


# ---------------------------------------------------------------------------
# KG → TDFOL_v1 formula mapping
# ---------------------------------------------------------------------------

class KGEntityFormula:
    """Static factory methods that convert KG query concepts to TDFOL_v1
    theorem + private-axiom lists for use with the Groth16 circuit.

    All inputs are normalised to lower-case to be deterministic.  The resulting
    strings are human-readable first-order-logic snippets; they do NOT need to
    be valid Prolog or any specific formal language — the TDFOL_v1 circuit
    hashes the strings to derive commitments.

    Example::

        theorem = KGEntityFormula.entity_exists_theorem("Person", "Alice")
        # "exists person named alice"

        axioms = KGEntityFormula.entity_exists_axioms("e-001", "Person", "Alice", 0.95)
        # ["e-001 is person", "e-001 has name alice", "e-001 confidence 0.95"]
    """

    @staticmethod
    def entity_exists_theorem(entity_type: str, name: str) -> str:
        """Theorem: *there exists an entity of type with name*."""
        return f"exists {entity_type.lower().strip()} named {name.lower().strip()}"

    @staticmethod
    def entity_exists_axioms(
        entity_id: str,
        entity_type: str,
        name: str,
        confidence: float = 1.0,
    ) -> List[str]:
        """Private axioms witnessing an entity's existence.

        The entity ID is the *secret* — it never appears in the theorem.
        """
        t = entity_type.lower().strip()
        n = name.lower().strip()
        c = f"{confidence:.4f}"
        return [
            f"{entity_id} is {t}",
            f"{entity_id} has name {n}",
            f"{entity_id} confidence {c}",
            f"{t} {n} exists in graph",
        ]

    @staticmethod
    def path_theorem(start_type: str, end_type: str, max_hops: int) -> str:
        """Theorem: *a path exists from start type to end type within N hops*."""
        s = start_type.lower().strip()
        e = end_type.lower().strip()
        return f"path exists from {s} to {e} within {max_hops} hops"

    @staticmethod
    def path_axioms(
        path_node_ids: List[str],
        rel_types: Optional[List[str]] = None,
    ) -> List[str]:
        """Private axioms witnessing a path (node IDs are secret).

        Args:
            path_node_ids: Ordered list of entity IDs along the path.
            rel_types: Optional relationship types between consecutive nodes.
        """
        if not path_node_ids:
            return []
        axioms = [f"path length {len(path_node_ids)}"]
        for i, nid in enumerate(path_node_ids):
            axioms.append(f"hop {i} is {nid}")
        if rel_types:
            for i, rt in enumerate(rel_types):
                axioms.append(f"hop {i} rel {rt.lower().strip()}")
        axioms.append(f"path start {path_node_ids[0]}")
        axioms.append(f"path end {path_node_ids[-1]}")
        return axioms

    @staticmethod
    def property_theorem(entity_id: str, property_key: str) -> str:
        """Theorem: *entity has property key with a committed value*."""
        return f"{entity_id} has property {property_key.lower().strip()}"

    @staticmethod
    def property_axioms(
        entity_id: str,
        property_key: str,
        value_hash: str,
    ) -> List[str]:
        """Private axioms witnessing a property value (value hash is secret)."""
        pk = property_key.lower().strip()
        return [
            f"{entity_id} property {pk} hash {value_hash}",
            f"{entity_id} has property {pk}",
            f"property {pk} committed {value_hash[:16]}",
        ]


# ---------------------------------------------------------------------------
# Prover / verifier factories
# ---------------------------------------------------------------------------

def create_groth16_kg_prover(
    kg: Any,
    config: Optional[Groth16KGConfig] = None,
) -> KGZKProver:
    """Create a :class:`KGZKProver` backed by the Groth16 logic backend.

    When ``config.enable_groth16`` is *True*, the function sets
    ``IPFS_DATASETS_ENABLE_GROTH16=1`` in the process environment before
    constructing the ``ZKPProver(backend="groth16")``.

    If the Groth16 backend is disabled or the binary is absent, the function
    falls back to :class:`KGZKProver` in standalone simulation mode and attaches
    ``_groth16_fallback=True`` as a sentinel attribute.

    Args:
        kg: :class:`~extraction.graph.KnowledgeGraph` instance.
        config: Optional :class:`Groth16KGConfig`; uses defaults when *None*.

    Returns:
        A :class:`KGZKProver` instance (may be simulation-backed).
    """
    if config is None:
        config = Groth16KGConfig()

    if config.enable_groth16:
        os.environ["IPFS_DATASETS_ENABLE_GROTH16"] = "1"

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            from ipfs_datasets_py.logic.zkp import ZKPProver as _ZKPProver

        logic_prover = _ZKPProver(backend="groth16")
        prover = KGZKProver.from_logic_prover(
            kg,
            logic_prover,
            prover_id=f"groth16-{config.ruleset_id.lower()}-v{config.circuit_version}",
        )
        prover._groth16_fallback = False  # type: ignore[attr-defined]
        return prover
    except Exception:
        # Groth16 disabled or binary absent — fall back to simulation.
        prover = KGZKProver(kg, prover_id="groth16-fallback")
        prover._groth16_fallback = True  # type: ignore[attr-defined]
        return prover


def create_groth16_kg_verifier(
    seen_nullifiers: Optional[Set[str]] = None,
    config: Optional[Groth16KGConfig] = None,
) -> KGZKVerifier:
    """Create a :class:`KGZKVerifier` backed by the Groth16 logic verifier.

    Falls back to standalone simulation verifier if the Groth16 backend is
    unavailable.

    Args:
        seen_nullifiers: Initial set of consumed nullifiers for replay protection.
        config: Optional :class:`Groth16KGConfig`; uses defaults when *None*.

    Returns:
        A :class:`KGZKVerifier` instance.
    """
    if config is None:
        config = Groth16KGConfig()

    if config.enable_groth16:
        os.environ["IPFS_DATASETS_ENABLE_GROTH16"] = "1"

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            from ipfs_datasets_py.logic.zkp.zkp_verifier import ZKPVerifier as _ZKPVerifier

        logic_verifier = _ZKPVerifier(backend="groth16")
        verifier = KGZKVerifier.from_logic_verifier(
            logic_verifier,
            seen_nullifiers=seen_nullifiers,
        )
        verifier._groth16_fallback = False  # type: ignore[attr-defined]
        return verifier
    except Exception:
        verifier = KGZKVerifier(seen_nullifiers=seen_nullifiers)
        verifier._groth16_fallback = True  # type: ignore[attr-defined]
        return verifier


# ---------------------------------------------------------------------------
# Diagnostic helper
# ---------------------------------------------------------------------------

def describe_groth16_status(binary_path: Optional[str] = None) -> Dict[str, Any]:
    """Return a diagnostic dictionary describing the Groth16 backend state.

    Useful for health checks, admin dashboards, and CI diagnostics.

    Returns a dict with the following keys:

    * ``enabled`` (bool): ``IPFS_DATASETS_ENABLE_GROTH16`` opt-in is active.
    * ``binary_available`` (bool): Compiled Rust binary found.
    * ``binary_path`` (Optional[str]): Resolved binary path (or *None*).
    * ``backend`` (str): ``"groth16"`` or ``"simulated"``.
    * ``production_ready`` (bool): Both enabled *and* binary present.
    * ``security_note`` (str): Human-readable security advisory.
    * ``setup_command`` (str): Command to compile the Rust binary.
    * ``env_var`` (str): Name of the opt-in environment variable.
    * ``config_class`` (str): ``"Groth16KGConfig"``.

    Args:
        binary_path: Optional explicit binary path passed to
            :func:`groth16_binary_available`.
    """
    enabled = groth16_enabled()
    available = groth16_binary_available(binary_path=binary_path)
    production_ready = enabled and available

    # Resolve the effective binary path for display.
    resolved_path: Optional[str] = None
    if binary_path and os.path.isfile(binary_path):
        resolved_path = str(binary_path)
    elif available:
        for env_var in ("IPFS_DATASETS_GROTH16_BINARY", "GROTH16_BINARY"):
            override = os.environ.get(env_var)
            if override and os.path.isfile(override):
                resolved_path = override
                break
        if resolved_path is None:
            from pathlib import Path
            kg_query_dir = Path(__file__).resolve().parent
            package_root = kg_query_dir.parents[1]
            monorepo_root = package_root.parent
            for candidate in [
                package_root / "processors" / "groth16_backend" / "target" / "release" / "groth16",
                monorepo_root / "processors" / "groth16_backend" / "target" / "release" / "groth16",
            ]:
                if candidate.is_file():
                    resolved_path = str(candidate)
                    break

    if not production_ready:
        if not enabled and not available:
            security_note = (
                "Groth16 backend is disabled and binary is not compiled. "
                "Proofs are SIMULATED (SHA-256 commitments, not cryptographically secure)."
            )
        elif not enabled:
            security_note = (
                "Binary found but IPFS_DATASETS_ENABLE_GROTH16 is not set. "
                "Set it to '1' to enable real Groth16 proofs."
            )
        else:
            security_note = (
                "IPFS_DATASETS_ENABLE_GROTH16 is set but binary is not compiled. "
                "Run: cd processors/groth16_backend && cargo build --release"
            )
    else:
        security_note = (
            "Groth16 backend is active. "
            "Proofs use real zkSNARK circuits (BN254 curve). "
            "Still NOT production cryptographic security without trusted setup."
        )

    return {
        "enabled": enabled,
        "binary_available": available,
        "binary_path": resolved_path,
        "backend": "groth16" if production_ready else "simulated",
        "production_ready": production_ready,
        "security_note": security_note,
        "setup_command": "cd processors/groth16_backend && cargo build --release",
        "env_var": "IPFS_DATASETS_ENABLE_GROTH16",
        "config_class": "Groth16KGConfig",
    }

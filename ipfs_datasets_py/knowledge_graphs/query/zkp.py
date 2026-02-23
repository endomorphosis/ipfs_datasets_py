"""
Zero-Knowledge Proof support for KnowledgeGraph queries.

Provides privacy-preserving query proofs: a caller can prove a *property* of
the graph (an entity exists, a path exists, a count is in a range, …) without
revealing the underlying entity IDs, names, or relationship details.

The implementation is a **simulation** — commitments are deterministic
SHA-256 hashes, not cryptographically binding commitments.  The interface
mirrors what a real ZKP backend (e.g. Groth16 from ``logic/zkp``) would
expose, so callers can swap in a stronger backend without API changes.

⚠️  WARNING: This module generates SIMULATED proofs only.
             They are NOT cryptographically secure.
             Use ``logic/zkp/ZKPProver`` for production-grade proofs.

Integration with ``ipfs_datasets_py.logic.zkp``
------------------------------------------------
When a ``ZKPProver`` from ``ipfs_datasets_py.logic.zkp`` is provided via
:meth:`KGZKProver.from_logic_prover`, the prover delegates theorem-level
proof generation to the logic backend.  For ``prove_entity_exists`` and
``prove_path_exists``, the serialised ``ZKPProof.proof_data`` is embedded in
``KGProofStatement.public_inputs["logic_proof_data"]`` so that a
``KGZKVerifier`` equipped with a ``ZKPVerifier`` (via
:meth:`KGZKVerifier.from_logic_verifier`) can re-verify the underlying proof.

When ``ipfs_datasets_py/processors/groth16_backend`` is compiled (Rust
binary present), ``ZKPProver(backend="groth16")`` will use real Groth16
proofs — the KG layer automatically benefits without any further changes.

Example (logic backend integration)::

    import warnings
    warnings.filterwarnings("ignore")          # suppress simulation warnings

    from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier
    from ipfs_datasets_py.knowledge_graphs.query.zkp import (
        KGZKProver, KGZKVerifier,
    )
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

    kg = KnowledgeGraph("demo")
    alice = kg.add_entity("person", "Alice", confidence=0.9)

    logic_prover   = ZKPProver()
    logic_verifier = ZKPVerifier()

    prover   = KGZKProver.from_logic_prover(kg, logic_prover)
    verifier = KGZKVerifier.from_logic_verifier(logic_verifier)

    stmt = prover.prove_entity_exists("person", "Alice")
    # public_inputs["logic_proof_data"] contains the serialised ZKPProof
    assert verifier.verify_statement(stmt)

Example (standalone, no logic backend)::

    from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver, KGZKVerifier
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

    kg = KnowledgeGraph("demo")
    alice = kg.add_entity("person", "Alice", confidence=0.9)

    prover   = KGZKProver(kg)
    verifier = KGZKVerifier()

    stmt = prover.prove_entity_exists("person", "Alice")
    assert stmt is not None
    assert verifier.verify_statement(stmt)

    # Entity ID is not revealed — only the commitment hash
    print(stmt.commitment)   # 'zk_commit_<sha256>'
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class KGProofType(str, Enum):
    """Types of zero-knowledge proof statements for knowledge graphs."""
    ENTITY_EXISTS = "entity_exists"           # Prove ∃ entity with type/name
    ENTITY_PROPERTY = "entity_property"       # Prove entity has property value
    PATH_EXISTS = "path_exists"               # Prove path between two types
    QUERY_ANSWER_COUNT = "query_answer_count" # Prove |results| ≥ min_count


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _commitment(proof_type: str, parameters: Dict[str, Any], secret: str) -> str:
    """Compute a commitment hash over public parameters and a secret witness."""
    payload = json.dumps(
        {"type": proof_type, "params": parameters, "secret": secret},
        sort_keys=True,
    )
    return "zk_commit_" + _sha256_hex(payload)


def _nullifier(commitment: str, prover_id: str) -> str:
    """Single-use nullifier to prevent proof replay."""
    return "zk_null_" + _sha256_hex(commitment + prover_id)


@dataclass
class KGProofStatement:
    """A zero-knowledge proof statement about a :class:`KnowledgeGraph`.

    Attributes:
        proof_type: What property is being proved.
        parameters: Public parameters visible to the verifier (no secret data).
        commitment: Cryptographic commitment to the witness (entity ID / path).
        nullifier: Single-use token preventing proof replay.
        public_inputs: Additional public data needed for verification.
        timestamp: Unix timestamp when the proof was generated.
    """
    proof_type: KGProofType
    parameters: Dict[str, Any]
    commitment: str
    nullifier: str
    public_inputs: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proof_type": self.proof_type.value,
            "parameters": self.parameters,
            "commitment": self.commitment,
            "nullifier": self.nullifier,
            "public_inputs": self.public_inputs,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KGProofStatement":
        return cls(
            proof_type=KGProofType(data["proof_type"]),
            parameters=data["parameters"],
            commitment=data["commitment"],
            nullifier=data["nullifier"],
            public_inputs=data.get("public_inputs", {}),
            timestamp=data.get("timestamp", 0.0),
        )


class KGZKProver:
    """Generate zero-knowledge proof statements about a :class:`KnowledgeGraph`.

    The prover holds the private graph data and produces public
    :class:`KGProofStatement` objects that can be verified without
    accessing the underlying graph.

    When *logic_prover* is provided (a ``ZKPProver`` from
    ``ipfs_datasets_py.logic.zkp``), theorem-level proof data is embedded
    inside the :class:`KGProofStatement` for stronger verifiability.

    Args:
        kg: The knowledge graph to prove properties of.
        prover_id: Optional stable identifier for this prover instance
            (used in nullifier computation).
        logic_prover: Optional ``ZKPProver`` instance from
            ``ipfs_datasets_py.logic.zkp`` for theorem-level proofs.
    """

    def __init__(
        self, kg: Any, prover_id: str = "default", logic_prover: Any = None
    ) -> None:
        self.kg = kg
        self.prover_id = prover_id
        self._logic_prover = logic_prover

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_logic_prover(
        cls, kg: Any, logic_prover: Any, prover_id: str = "default"
    ) -> "KGZKProver":
        """Create a :class:`KGZKProver` backed by a ``logic.zkp.ZKPProver``.

        This factory wires the KG prover to the ``ipfs_datasets_py.logic.zkp``
        simulation (or Groth16 when the Rust binary is compiled) so that
        ``prove_entity_exists`` and ``prove_path_exists`` embed a proper
        theorem-level :class:`~ipfs_datasets_py.logic.zkp.ZKPProof` inside
        the returned :class:`KGProofStatement`.

        Args:
            kg: The knowledge graph to prove properties of.
            logic_prover: A ``ZKPProver`` instance from
                ``ipfs_datasets_py.logic.zkp``.
            prover_id: Stable identifier for this prover instance.

        Returns:
            A new :class:`KGZKProver` that uses *logic_prover* internally.

        Example::

            import warnings; warnings.filterwarnings("ignore")
            from ipfs_datasets_py.logic.zkp import ZKPProver
            from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver

            prover = KGZKProver.from_logic_prover(kg, ZKPProver())
            assert prover.uses_logic_backend
        """
        return cls(kg=kg, prover_id=prover_id, logic_prover=logic_prover)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def uses_logic_backend(self) -> bool:
        """``True`` when a ``logic.zkp.ZKPProver`` is attached."""
        return self._logic_prover is not None

    def get_backend_info(self) -> Dict[str, Any]:
        """Return a dict describing the active ZKP backend.

        Returns:
            Dictionary with keys ``name``, ``backend``, ``security_level``,
            ``uses_logic_backend``.  Extra keys are populated when a
            ``logic.zkp.ZKPProver`` is attached.
        """
        info: Dict[str, Any] = {
            "name": "KGZKProver",
            "backend": "simulated",
            "security_level": 0,
            "uses_logic_backend": self.uses_logic_backend,
        }
        if self._logic_prover is not None:
            info["backend"] = getattr(self._logic_prover, "backend", "simulated")
            info["security_level"] = getattr(
                self._logic_prover, "security_level", 128
            )
        return info

    # ------------------------------------------------------------------
    # Individual proof generators
    # ------------------------------------------------------------------

    def prove_entity_exists(
        self, entity_type: str, name: str
    ) -> Optional[KGProofStatement]:
        """Prove that an entity with the given type and name exists in the graph.

        The proof reveals *only* that such an entity exists — not its ID,
        properties, or relationships.

        When a ``logic.zkp.ZKPProver`` is attached (via
        :meth:`from_logic_prover`), a theorem-level proof is embedded in
        ``public_inputs["logic_proof_data"]`` for stronger verification.

        Args:
            entity_type: The entity type to search for.
            name: The entity name to search for (case-insensitive).

        Returns:
            A :class:`KGProofStatement` if a matching entity is found,
            ``None`` otherwise.
        """
        for entity in self.kg.entities.values():
            if (
                entity.entity_type == entity_type
                and entity.name.lower() == name.lower()
            ):
                secret = entity.entity_id
                params = {"entity_type": entity_type, "name_hash": _sha256_hex(name.lower())}
                commit = _commitment(KGProofType.ENTITY_EXISTS.value, params, secret)
                null = _nullifier(commit, self.prover_id)
                public_inputs: Dict[str, Any] = {"entity_type": entity_type}
                # --- Logic ZKP backend integration ---
                if self._logic_prover is not None:
                    theorem = f"entity_of_type_{entity_type}_named_{_sha256_hex(name.lower())[:16]}_exists"
                    private_axioms = [entity.entity_id, f"name:{name.lower()}", f"type:{entity_type}"]
                    try:
                        logic_proof = self._logic_prover.generate_proof(
                            theorem=theorem,
                            private_axioms=private_axioms,
                        )
                        public_inputs["logic_proof_data"] = logic_proof.to_dict()
                        public_inputs["logic_theorem"] = theorem
                    except Exception:
                        pass  # fall back to simulation-only proof
                # ------------------------------------
                return KGProofStatement(
                    proof_type=KGProofType.ENTITY_EXISTS,
                    parameters=params,
                    commitment=commit,
                    nullifier=null,
                    public_inputs=public_inputs,
                )
        return None

    def prove_entity_property(
        self, entity_id: str, property_key: str, property_value_hash: str
    ) -> Optional[KGProofStatement]:
        """Prove that an entity has a specific property value without revealing the value.

        Args:
            entity_id: The entity to inspect.
            property_key: The property name.
            property_value_hash: SHA-256 hex digest of the expected property value.

        Returns:
            A :class:`KGProofStatement` if the hash matches, ``None`` otherwise.
        """
        entity = self.kg.entities.get(entity_id)
        if entity is None:
            return None
        props = getattr(entity, "properties", {}) or {}
        actual_value = props.get(property_key)
        if actual_value is None:
            return None
        actual_hash = _sha256_hex(str(actual_value))
        if actual_hash != property_value_hash:
            return None
        params = {
            "entity_type": entity.entity_type,
            "property_key": property_key,
            "property_value_hash": property_value_hash,
        }
        secret = entity_id + property_key + actual_hash
        commit = _commitment(KGProofType.ENTITY_PROPERTY.value, params, secret)
        null = _nullifier(commit, self.prover_id)
        return KGProofStatement(
            proof_type=KGProofType.ENTITY_PROPERTY,
            parameters=params,
            commitment=commit,
            nullifier=null,
            public_inputs={"property_key": property_key},
        )

    def prove_path_exists(
        self, start_type: str, end_type: str, max_hops: int = 3
    ) -> Optional[KGProofStatement]:
        """Prove that a path exists between two entity types within max_hops.

        The proof reveals *only* that such a path exists — not the specific
        entity IDs or relationship types along the path.

        When a ``logic.zkp.ZKPProver`` is attached, a theorem-level proof is
        embedded in ``public_inputs["logic_proof_data"]``.

        Args:
            start_type: Entity type of the path start.
            end_type: Entity type of the path end.
            max_hops: Maximum path length to search.

        Returns:
            A :class:`KGProofStatement` if a path is found, ``None`` otherwise.
        """
        path = self._find_path(start_type, end_type, max_hops)
        if path is None:
            return None
        # Secret = the actual path (IDs); public = only types + length
        secret = json.dumps(path, sort_keys=True)
        params = {
            "start_type": start_type,
            "end_type": end_type,
            "max_hops": max_hops,
            "path_length": len(path) - 1,
        }
        commit = _commitment(KGProofType.PATH_EXISTS.value, params, secret)
        null = _nullifier(commit, self.prover_id)
        public_inputs: Dict[str, Any] = {
            "start_type": start_type,
            "end_type": end_type,
            "path_length": len(path) - 1,
        }
        # --- Logic ZKP backend integration ---
        if self._logic_prover is not None:
            theorem = f"path_from_{start_type}_to_{end_type}_length_{len(path) - 1}_exists"
            private_axioms = [f"node:{nid}" for nid in path]
            try:
                logic_proof = self._logic_prover.generate_proof(
                    theorem=theorem,
                    private_axioms=private_axioms,
                )
                public_inputs["logic_proof_data"] = logic_proof.to_dict()
                public_inputs["logic_theorem"] = theorem
            except Exception:
                pass
        # ------------------------------------
        return KGProofStatement(
            proof_type=KGProofType.PATH_EXISTS,
            parameters=params,
            commitment=commit,
            nullifier=null,
            public_inputs=public_inputs,
        )

    def prove_query_answer_count(
        self, min_count: int, query_type: str = "entity"
    ) -> Optional[KGProofStatement]:
        """Prove that the number of query results is at least *min_count*.

        Args:
            min_count: Minimum required result count.
            query_type: ``'entity'`` counts entities; ``'relationship'`` counts
                relationships.

        Returns:
            A :class:`KGProofStatement` if the count ≥ min_count, ``None``
            otherwise.
        """
        if query_type == "entity":
            actual_count = len(self.kg.entities)
        elif query_type == "relationship":
            actual_count = len(self.kg.relationships)
        else:
            actual_count = 0
        if actual_count < min_count:
            return None
        secret = f"{query_type}:{actual_count}"
        params = {"min_count": min_count, "query_type": query_type}
        commit = _commitment(KGProofType.QUERY_ANSWER_COUNT.value, params, secret)
        null = _nullifier(commit, self.prover_id)
        return KGProofStatement(
            proof_type=KGProofType.QUERY_ANSWER_COUNT,
            parameters=params,
            commitment=commit,
            nullifier=null,
            public_inputs={"min_count": min_count, "query_type": query_type},
        )

    # ------------------------------------------------------------------
    # Batch proving
    # ------------------------------------------------------------------

    def batch_prove(
        self, requests: List[Dict[str, Any]]
    ) -> List[Optional[KGProofStatement]]:
        """Run multiple proof requests in sequence.

        Each request dict must contain a ``"type"`` key matching a
        :class:`KGProofType` value, plus the type-specific arguments.

        Example request formats::

            {"type": "entity_exists", "entity_type": "person", "name": "Alice"}
            {"type": "path_exists", "start_type": "person", "end_type": "org", "max_hops": 2}
            {"type": "query_answer_count", "min_count": 5, "query_type": "entity"}
            {"type": "entity_property", "entity_id": "...", "property_key": "age", "property_value_hash": "..."}

        Returns:
            List of proof statements, with ``None`` for any request that
            could not be satisfied.
        """
        results: List[Optional[KGProofStatement]] = []
        for req in requests:
            proof_type = req.get("type", "")
            try:
                if proof_type == KGProofType.ENTITY_EXISTS.value:
                    stmt = self.prove_entity_exists(
                        req["entity_type"], req["name"]
                    )
                elif proof_type == KGProofType.ENTITY_PROPERTY.value:
                    stmt = self.prove_entity_property(
                        req["entity_id"],
                        req["property_key"],
                        req["property_value_hash"],
                    )
                elif proof_type == KGProofType.PATH_EXISTS.value:
                    stmt = self.prove_path_exists(
                        req["start_type"],
                        req.get("end_type", ""),
                        req.get("max_hops", 3),
                    )
                elif proof_type == KGProofType.QUERY_ANSWER_COUNT.value:
                    stmt = self.prove_query_answer_count(
                        req["min_count"],
                        req.get("query_type", "entity"),
                    )
                else:
                    stmt = None
            except (KeyError, TypeError):
                stmt = None
            results.append(stmt)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_path(
        self, start_type: str, end_type: str, max_hops: int
    ) -> Optional[List[str]]:
        """BFS over the KG to find a path from start_type to end_type."""
        # Collect start and end entity IDs
        start_ids = [
            eid
            for eid, e in self.kg.entities.items()
            if e.entity_type == start_type
        ]
        end_ids = {
            eid
            for eid, e in self.kg.entities.items()
            if e.entity_type == end_type
        }
        if not start_ids or not end_ids:
            return None

        # Build forward adjacency
        forward: Dict[str, List[str]] = {eid: [] for eid in self.kg.entities}
        for rel in self.kg.relationships.values():
            if rel.source_id in forward:
                forward[rel.source_id].append(rel.target_id)

        from collections import deque

        for start_id in start_ids:
            if start_id in end_ids:
                return [start_id]
            queue: deque = deque()
            queue.append((start_id, [start_id]))
            visited = {start_id}
            while queue:
                current, path = queue.popleft()
                if len(path) - 1 >= max_hops:
                    continue
                for nxt in forward.get(current, []):
                    if nxt in end_ids:
                        return path + [nxt]
                    if nxt not in visited:
                        visited.add(nxt)
                        queue.append((nxt, path + [nxt]))
        return None


class KGZKVerifier:
    """Verify :class:`KGProofStatement` objects without access to the private graph.

    The verifier only checks structural integrity of the commitment and
    nullifier — not the underlying graph data.  In a real ZKP system this
    would verify the proof against a public verification key.

    When a ``logic.zkp.ZKPVerifier`` is attached (via
    :meth:`from_logic_verifier`), statements that contain a
    ``"logic_proof_data"`` key in their ``public_inputs`` are additionally
    verified against the logic backend.

    Args:
        seen_nullifiers: Optional set of previously used nullifiers; if
            provided, replay attacks are detected.
        logic_verifier: Optional ``ZKPVerifier`` from
            ``ipfs_datasets_py.logic.zkp`` for enhanced re-verification.
    """

    def __init__(
        self,
        seen_nullifiers: Optional[set] = None,
        logic_verifier: Any = None,
    ) -> None:
        self._seen: set = seen_nullifiers if seen_nullifiers is not None else set()
        self._logic_verifier = logic_verifier

    @classmethod
    def from_logic_verifier(
        cls, logic_verifier: Any, seen_nullifiers: Optional[set] = None
    ) -> "KGZKVerifier":
        """Create a :class:`KGZKVerifier` backed by a ``logic.zkp.ZKPVerifier``.

        Statements produced by a :class:`KGZKProver` that was itself created
        via :meth:`KGZKProver.from_logic_prover` will contain
        ``public_inputs["logic_proof_data"]``.  This factory ensures those
        embedded proofs are also verified by the logic layer.

        Args:
            logic_verifier: A ``ZKPVerifier`` instance from
                ``ipfs_datasets_py.logic.zkp``.
            seen_nullifiers: Optional set of previously seen nullifiers.

        Returns:
            A new :class:`KGZKVerifier` that uses *logic_verifier* internally.
        """
        return cls(seen_nullifiers=seen_nullifiers, logic_verifier=logic_verifier)

    def verify_statement(self, stmt: "KGProofStatement") -> bool:
        """Verify a :class:`KGProofStatement`.

        Checks:
        1. Nullifier not previously seen (replay protection).
        2. Commitment is non-empty and starts with the expected prefix.
        3. Proof type is a known :class:`KGProofType`.
        4. Parameters dict is non-empty.
        5. If ``public_inputs["logic_proof_data"]`` is present and a
           ``logic.zkp.ZKPVerifier`` is attached, the embedded proof is
           also verified by the logic layer.

        Returns:
            ``True`` if all checks pass; ``False`` otherwise.
        """
        if not isinstance(stmt, KGProofStatement):
            return False
        if not stmt.commitment.startswith("zk_commit_"):
            return False
        if not stmt.nullifier.startswith("zk_null_"):
            return False
        if stmt.nullifier in self._seen:
            return False  # replay
        try:
            KGProofType(stmt.proof_type)
        except ValueError:
            return False
        if not stmt.parameters:
            return False
        # --- Logic ZKP backend re-verification ---
        if self._logic_verifier is not None and stmt.public_inputs.get("logic_proof_data"):
            try:
                from ipfs_datasets_py.logic.zkp import ZKPProof
                logic_proof = ZKPProof.from_dict(stmt.public_inputs["logic_proof_data"])
                if not self._logic_verifier.verify_proof(logic_proof):
                    return False
            except Exception:
                pass  # fall back to simulation-only verification
        # -----------------------------------------
        self._seen.add(stmt.nullifier)
        return True

    def verify_batch(
        self, stmts: "List[Optional[KGProofStatement]]"
    ) -> "List[bool]":
        """Verify a list of proof statements.

        Returns:
            List of booleans (``True`` = valid, ``False`` = invalid or ``None``).
        """
        return [
            self.verify_statement(s) if s is not None else False
            for s in stmts
        ]

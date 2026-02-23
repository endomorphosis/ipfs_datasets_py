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

Example::

    from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver, KGZKVerifier
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

    kg = KnowledgeGraph("demo")
    alice = kg.add_entity("person", "Alice", confidence=0.9)
    carol = kg.add_entity("org",    "ACME")
    kg.add_relationship("works_at", alice, carol)

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

    Args:
        kg: The knowledge graph to prove properties of.
        prover_id: Optional stable identifier for this prover instance
            (used in nullifier computation).
    """

    def __init__(self, kg: Any, prover_id: str = "default") -> None:
        self.kg = kg
        self.prover_id = prover_id

    # ------------------------------------------------------------------
    # Individual proof generators
    # ------------------------------------------------------------------

    def prove_entity_exists(
        self, entity_type: str, name: str
    ) -> Optional[KGProofStatement]:
        """Prove that an entity with the given type and name exists in the graph.

        The proof reveals *only* that such an entity exists — not its ID,
        properties, or relationships.

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
                return KGProofStatement(
                    proof_type=KGProofType.ENTITY_EXISTS,
                    parameters=params,
                    commitment=commit,
                    nullifier=null,
                    public_inputs={"entity_type": entity_type},
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
        return KGProofStatement(
            proof_type=KGProofType.PATH_EXISTS,
            parameters=params,
            commitment=commit,
            nullifier=null,
            public_inputs={
                "start_type": start_type,
                "end_type": end_type,
                "path_length": len(path) - 1,
            },
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

    Args:
        seen_nullifiers: Optional set of previously used nullifiers; if
            provided, replay attacks are detected.
    """

    def __init__(self, seen_nullifiers: Optional[set] = None) -> None:
        self._seen: set = seen_nullifiers if seen_nullifiers is not None else set()

    def verify_statement(self, stmt: KGProofStatement) -> bool:
        """Verify a :class:`KGProofStatement`.

        Checks:
        1. Nullifier not previously seen (replay protection).
        2. Commitment is non-empty and starts with the expected prefix.
        3. Proof type is a known :class:`KGProofType`.
        4. Parameters dict is non-empty.

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
        self._seen.add(stmt.nullifier)
        return True

    def verify_batch(
        self, stmts: List[Optional[KGProofStatement]]
    ) -> List[bool]:
        """Verify a list of proof statements.

        Returns:
            List of booleans (``True`` = valid, ``False`` = invalid or ``None``).
        """
        return [
            self.verify_statement(s) if s is not None else False
            for s in stmts
        ]

"""
TDFOL_v1 Witness Builder for Knowledge Graph Zero-Knowledge Proofs.

Bridges the KG domain (entity types, names, IDs, relationships) to the
TDFOL_v1 circuit expected by the Groth16 Rust backend in
``processors/groth16_backend``.

The Rust backend requires:
- **theorem**: a single TDFOL_v1 atom (ASCII-letter start, alphanumeric + ``_``).
- **private_axioms**: list of atoms or implications ``"atom -> atom"``.
- **intermediate_steps** (circuit v2 only): non-empty list of atoms forming a
  derivation trace.
- **axioms_commitment_hex**: 64-hex-char SHA-256 commitment over axioms.
- **theorem_hash_hex**: 64-hex-char SHA-256 hash of the theorem atom.

This module provides:

- :class:`KGAtomEncoder` — normalize arbitrary KG strings (entity types, names,
  relationship types, entity IDs) into valid single-word TDFOL_v1 atoms.
- :class:`KGWitnessBuilder` — build complete TDFOL_v1 witness input dicts ready
  for submission to the Groth16 binary.

Quick start
-----------

.. code-block:: python

    from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
        KGAtomEncoder,
        KGWitnessBuilder,
    )

    enc = KGAtomEncoder()

    # Encode KG concepts to valid TDFOL_v1 atoms
    print(enc.encode_entity_type("Person"))         # "person"
    print(enc.encode_name("Acme Corp"))             # "acme_corp"
    print(enc.encode_name("Alice-Jane O'Brien"))    # "alice_jane_o_brien"

    # Build a witness for entity_exists proof
    builder = KGWitnessBuilder()
    witness = builder.entity_exists(
        entity_type="Person",
        name="Alice",
        entity_id="eid_001",
        confidence=0.95,
    )
    # witness["theorem"]        → "person_alice_exists"
    # witness["private_axioms"] → ["eid_001_is_person", "eid_001_has_name_alice", ...]

    # Build a witness for path_exists proof
    witness = builder.path_exists(
        path_ids=["eid_001", "eid_002", "eid_003"],
        rel_types=["knows", "works_at"],
        start_type="Person",
        end_type="Organization",
    )

    # Build a witness for entity_property proof
    import hashlib
    value_hash = hashlib.sha256(b"30").hexdigest()
    witness = builder.entity_property(
        entity_id="eid_001",
        property_key="age",
        value_hash=value_hash,
    )

Integration with the Groth16 backend
-------------------------------------

.. code-block:: python

    import os, json
    os.environ["IPFS_DATASETS_ENABLE_GROTH16"] = "1"

    from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend
    from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import KGWitnessBuilder

    backend = Groth16Backend()
    builder = KGWitnessBuilder(circuit_version=1)
    witness = builder.entity_exists("Person", "Alice", "eid_001", 0.95)
    proof_json = backend.prove(json.dumps(witness))
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_hex(data: str) -> str:
    """Return 64-char hex SHA-256 of *data*."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _is_tdfol_atom(s: str) -> bool:
    """Return *True* if *s* is a valid TDFOL_v1 atom.

    A TDFOL_v1 atom starts with an ASCII letter and contains only
    alphanumeric characters or underscores (no spaces, hyphens, dots, …).
    """
    if not s:
        return False
    if not s[0].isascii() or not s[0].isalpha():
        return False
    return all(c.isascii() and (c.isalnum() or c == "_") for c in s)


# ---------------------------------------------------------------------------
# KGAtomEncoder
# ---------------------------------------------------------------------------

class KGAtomEncoder:
    """Normalize Knowledge Graph strings to valid TDFOL_v1 atoms.

    TDFOL_v1 atoms must:
    - Start with an ASCII letter.
    - Contain only ASCII alphanumeric characters or underscores.
    - Be non-empty.

    This encoder handles entity types, entity names, relationship types,
    entity IDs, and property keys — converting any input string into a
    compliant atom.

    Args:
        max_length: Maximum atom length (default 64).  Atoms are truncated
            (never left-padded) when they exceed this limit.

    Example::

        enc = KGAtomEncoder()

        enc.encode_entity_type("Person")          # "person"
        enc.encode_entity_type("AIModel")         # "aimodel"
        enc.encode_name("Alice-Jane O'Brien")     # "alice_jane_o_brien"
        enc.encode_name("Acme Corp (Ltd)")        # "acme_corp__ltd_"
        enc.encode_relationship_type("works_at")  # "works_at"
        enc.encode_entity_id("eid-abc/123")       # "eid_abc_123"
        enc.atom_for_entity("Person", "Alice")    # "person_alice"
    """

    def __init__(self, max_length: int = 64) -> None:
        self.max_length = max_length

    # ------------------------------------------------------------------
    # Core normalizer
    # ------------------------------------------------------------------

    def normalize(self, s: str) -> str:
        """Normalize an arbitrary string to a valid TDFOL_v1 atom.

        Steps:
        1. Strip leading/trailing whitespace.
        2. Lower-case everything.
        3. Replace any non-(alphanumeric|underscore) run with ``_``.
        4. Remove leading underscores and digits (atom must start with a letter).
        5. Truncate to ``max_length``.
        6. Fall back to ``"entity"`` if the result is empty.

        Args:
            s: Input string (any content).

        Returns:
            A non-empty valid TDFOL_v1 atom string.
        """
        s = s.strip().lower()
        # Replace runs of invalid chars with single underscore
        s = re.sub(r"[^a-z0-9_]+", "_", s)
        # Remove leading chars that are not ASCII letters
        s = s.lstrip("_0123456789")
        # Truncate
        s = s[:self.max_length]
        # Remove trailing underscores for neatness
        s = s.rstrip("_")
        return s if s else "entity"

    # ------------------------------------------------------------------
    # Domain-specific encoders
    # ------------------------------------------------------------------

    def encode_entity_type(self, entity_type: str) -> str:
        """Encode an entity type string to a TDFOL_v1 atom.

        Args:
            entity_type: e.g. ``"Person"``, ``"AIModel"``, ``"legal_document"``.

        Returns:
            Normalized atom, e.g. ``"person"``, ``"aimodel"``, ``"legal_document"``.
        """
        return self.normalize(entity_type)

    def encode_name(self, name: str) -> str:
        """Encode an entity name string to a TDFOL_v1 atom.

        Args:
            name: e.g. ``"Alice"``, ``"Acme Corp (Ltd.)"``

        Returns:
            Normalized atom, e.g. ``"alice"``, ``"acme_corp__ltd_"``.
        """
        return self.normalize(name)

    def encode_relationship_type(self, rel_type: str) -> str:
        """Encode a relationship type string to a TDFOL_v1 atom.

        Args:
            rel_type: e.g. ``"works_at"``, ``"KNOWS"``, ``"related-to"``.

        Returns:
            Normalized atom, e.g. ``"works_at"``, ``"knows"``, ``"related_to"``.
        """
        return self.normalize(rel_type)

    def encode_entity_id(self, entity_id: str) -> str:
        """Encode an entity ID to a TDFOL_v1 atom.

        Entity IDs often contain hyphens or slashes (e.g. UUID format).
        This encoder preserves as much of the original as possible.

        Args:
            entity_id: e.g. ``"eid-abc-123"``, ``"entity/456"``.

        Returns:
            Normalized atom, e.g. ``"eid_abc_123"``, ``"entity_456"``.
        """
        return self.normalize(entity_id)

    def encode_property_key(self, property_key: str) -> str:
        """Encode a property key to a TDFOL_v1 atom.

        Args:
            property_key: e.g. ``"age"``, ``"first-name"``, ``"confidence_score"``.

        Returns:
            Normalized atom, e.g. ``"age"``, ``"first_name"``, ``"confidence_score"``.
        """
        return self.normalize(property_key)

    # ------------------------------------------------------------------
    # Compound atoms
    # ------------------------------------------------------------------

    def atom_for_entity(self, entity_type: str, name: str) -> str:
        """Return a compound atom combining entity type and name.

        The result is ``"{type}_{name}"``, truncated to ``max_length``.

        Args:
            entity_type: Entity type string.
            name: Entity name string.

        Returns:
            Compound atom, e.g. ``"person_alice"``.
        """
        t = self.encode_entity_type(entity_type)
        n = self.encode_name(name)
        combined = f"{t}_{n}"
        return combined[:self.max_length]

    def atom_for_entity_exists(self, entity_type: str, name: str) -> str:
        """Return the canonical theorem atom for an entity-exists proof.

        Args:
            entity_type: Entity type string.
            name: Entity name string.

        Returns:
            Atom, e.g. ``"person_alice_exists"``.
        """
        base = self.atom_for_entity(entity_type, name)
        suffix = "_exists"
        return (base[:self.max_length - len(suffix)] + suffix)

    def atom_for_path_exists(self, start_type: str, end_type: str) -> str:
        """Return the canonical theorem atom for a path-exists proof.

        Args:
            start_type: Start entity type string.
            end_type: End entity type string.

        Returns:
            Atom, e.g. ``"path_person_to_organization_exists"``.
        """
        s = self.encode_entity_type(start_type)
        e = self.encode_entity_type(end_type)
        raw = f"path_{s}_to_{e}_exists"
        return raw[:self.max_length]

    def atom_for_entity_property(self, entity_id: str, property_key: str) -> str:
        """Return the canonical theorem atom for an entity-property proof.

        Args:
            entity_id: Entity ID string.
            property_key: Property name string.

        Returns:
            Atom, e.g. ``"eid_001_has_age"``.
        """
        eid = self.encode_entity_id(entity_id)
        pk = self.encode_property_key(property_key)
        raw = f"{eid}_has_{pk}"
        return raw[:self.max_length]


# ---------------------------------------------------------------------------
# Axiom commitment helper (mirrors Rust's commit_axioms_v1 for v1 circuit)
# ---------------------------------------------------------------------------

def _commit_axioms_v1(private_axioms: List[str]) -> str:
    """Compute the v1 axioms commitment as a 64-char hex SHA-256 string.

    The v1 circuit simply hashes the JSON-encoded sorted list of axioms.
    This mirrors the logic in :mod:`ipfs_datasets_py.logic.zkp.canonicalization`.

    Args:
        private_axioms: List of TDFOL_v1 axiom strings.

    Returns:
        64-character lowercase hex string.
    """
    # Use the same canonicalization as the Python logic layer (SHA-256 of
    # JSON-encoded sorted axiom list).
    payload = json.dumps(sorted(private_axioms), separators=(",", ":"))
    return _sha256_hex(payload)


# ---------------------------------------------------------------------------
# KGWitnessBuilder
# ---------------------------------------------------------------------------

class KGWitnessBuilder:
    """Build TDFOL_v1 witness input dicts for Knowledge Graph ZK proofs.

    Produces dictionaries compatible with the ``WitnessInput`` struct
    in the Groth16 Rust backend:

    .. code-block:: json

        {
            "private_axioms": ["..."],
            "theorem": "...",
            "intermediate_steps": ["..."],
            "axioms_commitment_hex": "64-char hex",
            "theorem_hash_hex": "64-char hex",
            "circuit_version": 1,
            "ruleset_id": "TDFOL_v1"
        }

    Args:
        circuit_version: TDFOL_v1 circuit version (1 or 2).  Circuit v2
            requires non-empty ``intermediate_steps``.
        ruleset_id: Ruleset identifier (default ``"TDFOL_v1"``).
        encoder: Optional :class:`KGAtomEncoder` instance.  A default one
            is created when not provided.

    Example::

        builder = KGWitnessBuilder()
        witness = builder.entity_exists("Person", "Alice", "eid_001", 0.95)
        # witness["theorem"] == "person_alice_exists"
    """

    def __init__(
        self,
        circuit_version: int = 1,
        ruleset_id: str = "TDFOL_v1",
        encoder: Optional[KGAtomEncoder] = None,
    ) -> None:
        self.circuit_version = circuit_version
        self.ruleset_id = ruleset_id
        self.encoder = encoder or KGAtomEncoder()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build(
        self,
        theorem: str,
        private_axioms: List[str],
        intermediate_steps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Assemble a complete witness dict.

        Validates that *theorem* and all *private_axioms* are valid TDFOL_v1
        atoms (or valid implications for axioms).  Computes
        ``theorem_hash_hex`` and ``axioms_commitment_hex`` automatically.

        Args:
            theorem: TDFOL_v1 theorem atom.
            private_axioms: List of TDFOL_v1 axiom atoms or implications.
            intermediate_steps: Derivation trace atoms for circuit v2.

        Returns:
            A witness dict ready to be JSON-serialized and passed to the
            Groth16 binary.
        """
        if not _is_tdfol_atom(theorem):
            raise ValueError(
                f"theorem must be a valid TDFOL_v1 atom, got: {theorem!r}"
            )
        for axiom in private_axioms:
            # Axioms may be "atom" or "atom -> atom"
            if " -> " in axiom:
                parts = axiom.split(" -> ", 1)
                if not _is_tdfol_atom(parts[0]) or not _is_tdfol_atom(parts[1]):
                    raise ValueError(
                        f"axiom implication contains invalid atoms: {axiom!r}"
                    )
            elif not _is_tdfol_atom(axiom):
                raise ValueError(
                    f"axiom must be a valid TDFOL_v1 atom or implication, got: {axiom!r}"
                )

        steps: List[str] = intermediate_steps or []
        if self.circuit_version == 2 and not steps:
            # Auto-derive a minimal trace: just the theorem itself
            steps = [theorem]

        theorem_hash = _sha256_hex(theorem)
        axioms_commitment = _commit_axioms_v1(private_axioms)

        return {
            "private_axioms": private_axioms,
            "theorem": theorem,
            "intermediate_steps": steps,
            "axioms_commitment_hex": axioms_commitment,
            "theorem_hash_hex": theorem_hash,
            "circuit_version": self.circuit_version,
            "ruleset_id": self.ruleset_id,
        }

    # ------------------------------------------------------------------
    # Public proof-type builders
    # ------------------------------------------------------------------

    def entity_exists(
        self,
        entity_type: str,
        name: str,
        entity_id: str,
        confidence: float = 1.0,
        intermediate_steps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build a witness proving that an entity with *entity_type* and *name* exists.

        The entity ID and confidence are encoded as private axioms; the theorem
        is the public claim.

        Args:
            entity_type: Entity type (e.g. ``"Person"``).
            name: Entity name (e.g. ``"Alice"``).
            entity_id: Private entity ID (not revealed in the theorem).
            confidence: Confidence score in [0.0, 1.0].
            intermediate_steps: Optional derivation trace (required for v2).

        Returns:
            Witness input dict.

        Example::

            builder = KGWitnessBuilder()
            w = builder.entity_exists("Person", "Alice", "eid_001", 0.95)
            assert w["theorem"] == "person_alice_exists"
        """
        enc = self.encoder
        type_atom = enc.encode_entity_type(entity_type)
        name_atom = enc.encode_name(name)
        eid_atom = enc.encode_entity_id(entity_id)
        theorem = enc.atom_for_entity_exists(entity_type, name)

        # Confidence encoded as a 4-digit fixed-point atom: e.g. "conf_0950"
        conf_int = max(0, min(9999, int(round(confidence * 1000))))
        conf_atom = f"conf_{conf_int:04d}"
        # Ensure conf_atom is valid (starts with letter — "conf" does)

        # Private axioms: entity ID is the witness
        axioms = [
            f"{eid_atom}_is_{type_atom}",
            f"{eid_atom}_has_name_{name_atom}",
            conf_atom,
            f"{type_atom}_{name_atom}_exists",
        ]

        return self._build(theorem, axioms, intermediate_steps)

    def path_exists(
        self,
        path_ids: List[str],
        rel_types: Optional[List[str]] = None,
        start_type: str = "entity",
        end_type: str = "entity",
        intermediate_steps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build a witness proving that a path between entity types exists.

        The actual node IDs along the path are private axioms.

        Args:
            path_ids: Ordered list of entity IDs forming the path.
            rel_types: Optional list of relationship types between consecutive
                nodes (must have ``len(path_ids) - 1`` entries).
            start_type: Type of the starting entity.
            end_type: Type of the ending entity.
            intermediate_steps: Optional derivation trace (required for v2).

        Returns:
            Witness input dict.

        Raises:
            ValueError: When *path_ids* is empty.

        Example::

            builder = KGWitnessBuilder()
            w = builder.path_exists(
                path_ids=["eid_001", "eid_002"],
                rel_types=["knows"],
                start_type="Person",
                end_type="Person",
            )
            assert w["theorem"] == "path_person_to_person_exists"
        """
        if not path_ids:
            raise ValueError("path_ids must be non-empty")

        enc = self.encoder
        theorem = enc.atom_for_path_exists(start_type, end_type)

        # Encode path length as an atom: "path_len_N"
        length_atom = f"path_len_{len(path_ids)}"

        axioms: List[str] = [length_atom]
        for i, nid in enumerate(path_ids):
            nid_atom = enc.encode_entity_id(nid)
            hop_atom = f"hop_{i}_{nid_atom}"
            # Truncate to max_length
            axioms.append(hop_atom[:enc.max_length])

        if rel_types:
            for i, rt in enumerate(rel_types):
                rt_atom = enc.encode_relationship_type(rt)
                hop_rel_atom = f"hop_{i}_rel_{rt_atom}"
                axioms.append(hop_rel_atom[:enc.max_length])

        # Start / end nodes
        start_atom = enc.encode_entity_id(path_ids[0])
        end_atom = enc.encode_entity_id(path_ids[-1])
        axioms.append(f"path_start_{start_atom}"[:enc.max_length])
        axioms.append(f"path_end_{end_atom}"[:enc.max_length])

        return self._build(theorem, axioms, intermediate_steps)

    def entity_property(
        self,
        entity_id: str,
        property_key: str,
        value_hash: str,
        intermediate_steps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build a witness proving that an entity has a specific property value.

        The actual value is never revealed; only its SHA-256 hash is encoded.

        Args:
            entity_id: Entity ID.
            property_key: Property name.
            value_hash: 64-char hex SHA-256 of the property value.
            intermediate_steps: Optional derivation trace (required for v2).

        Returns:
            Witness input dict.

        Example::

            import hashlib
            vh = hashlib.sha256(b"30").hexdigest()
            builder = KGWitnessBuilder()
            w = builder.entity_property("eid_001", "age", vh)
            assert w["theorem"] == "eid_001_has_age"
        """
        enc = self.encoder
        eid_atom = enc.encode_entity_id(entity_id)
        pk_atom = enc.encode_property_key(property_key)
        theorem = enc.atom_for_entity_property(entity_id, property_key)

        # Encode value hash as a short commitment atom using first 16 hex chars
        hash_prefix = value_hash[:16] if value_hash else "unknown"
        # hash_prefix may start with digits, prefix with "h"
        commit_atom = f"h{hash_prefix}"

        axioms = [
            f"{eid_atom}_property_{pk_atom}",
            commit_atom,
            f"{eid_atom}_has_{pk_atom}",
        ]

        return self._build(theorem, axioms, intermediate_steps)

    def query_answer_count(
        self,
        min_count: int,
        actual_count: int,
        query_type: str = "entity",
        intermediate_steps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build a witness proving the result count of a query is at least *min_count*.

        Args:
            min_count: Public minimum count threshold.
            actual_count: Private actual count (kept secret as an axiom).
            query_type: ``"entity"`` or ``"relationship"``.
            intermediate_steps: Optional derivation trace (required for v2).

        Returns:
            Witness input dict.

        Raises:
            ValueError: When *actual_count* is less than *min_count*.

        Example::

            builder = KGWitnessBuilder()
            w = builder.query_answer_count(min_count=3, actual_count=5)
            assert w["theorem"] == "count_at_least_3"
        """
        if actual_count < min_count:
            raise ValueError(
                f"actual_count ({actual_count}) < min_count ({min_count})"
            )

        enc = self.encoder
        qt_atom = enc.normalize(query_type)
        theorem = f"count_at_least_{min_count}"
        if not _is_tdfol_atom(theorem):
            theorem = f"count_ge_{min_count}"

        actual_atom = f"actual_{qt_atom}_count_{actual_count}"
        min_atom = f"min_count_is_{min_count}"
        satisfies_atom = f"count_satisfies_min"

        axioms = [
            actual_atom[:enc.max_length],
            min_atom[:enc.max_length],
            satisfies_atom,
        ]

        return self._build(theorem, axioms, intermediate_steps)


# ---------------------------------------------------------------------------
# Convenience exports
# ---------------------------------------------------------------------------

__all__ = [
    "KGAtomEncoder",
    "KGWitnessBuilder",
]

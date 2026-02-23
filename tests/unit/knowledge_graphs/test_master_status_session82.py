"""
Tests for Session 82: KGAtomEncoder + KGWitnessBuilder (TDFOL_v1 witness
construction for the Groth16 Rust backend).

Session 82 (v3.22.36):
- query/groth16_kg_witness.py  — KGAtomEncoder + KGWitnessBuilder
- groth16_bridge.py updated   — KGEntityFormula.to_tdfol_atoms() added
- query/__init__.py updated    — KGAtomEncoder + KGWitnessBuilder exported
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_BASE = pathlib.Path(__file__).parent.parent.parent.parent
_KG_ROOT = _BASE / "ipfs_datasets_py" / "knowledge_graphs"
_MASTER = _KG_ROOT / "MASTER_STATUS.md"
_CHANGELOG = _KG_ROOT / "CHANGELOG_KNOWLEDGE_GRAPHS.md"
_ROADMAP = _KG_ROOT / "ROADMAP.md"
_DEFERRED = _KG_ROOT / "DEFERRED_FEATURES.md"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _is_tdfol_atom(s: str) -> bool:
    if not s:
        return False
    if not s[0].isascii() or not s[0].isalpha():
        return False
    return all(c.isascii() and (c.isalnum() or c == "_") for c in s)


# ---------------------------------------------------------------------------
# 1. KGAtomEncoder — import and instantiation
# ---------------------------------------------------------------------------
class TestKGAtomEncoderImport:
    def test_importable_from_module(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGAtomEncoder,
        )
        assert KGAtomEncoder is not None

    def test_importable_from_query_package(self):
        from ipfs_datasets_py.knowledge_graphs.query import KGAtomEncoder
        assert KGAtomEncoder is not None

    def test_in_query_all(self):
        from ipfs_datasets_py.knowledge_graphs import query
        assert "KGAtomEncoder" in query.__all__

    def test_instantiation_defaults(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGAtomEncoder,
        )
        enc = KGAtomEncoder()
        assert enc.max_length == 64

    def test_instantiation_custom_max_length(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGAtomEncoder,
        )
        enc = KGAtomEncoder(max_length=32)
        assert enc.max_length == 32


# ---------------------------------------------------------------------------
# 2. KGAtomEncoder.normalize
# ---------------------------------------------------------------------------
class TestKGAtomEncoderNormalize:
    @pytest.fixture
    def enc(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGAtomEncoder,
        )
        return KGAtomEncoder()

    def test_simple_lowercase(self, enc):
        assert enc.normalize("Person") == "person"

    def test_spaces_replaced_by_underscore(self, enc):
        assert enc.normalize("Acme Corp") == "acme_corp"

    def test_hyphens_replaced(self, enc):
        assert enc.normalize("alice-jane") == "alice_jane"

    def test_special_chars_replaced(self, enc):
        result = enc.normalize("O'Brien & Co.")
        assert _is_tdfol_atom(result)

    def test_leading_digit_stripped(self, enc):
        result = enc.normalize("123abc")
        assert result[0].isalpha()

    def test_empty_string_fallback(self, enc):
        assert enc.normalize("") == "entity"

    def test_all_digits_fallback(self, enc):
        result = enc.normalize("12345")
        assert result[0].isalpha()

    def test_truncation(self, enc):
        long_str = "a" * 100
        result = enc.normalize(long_str)
        assert len(result) <= 64

    def test_output_is_valid_tdfol_atom(self, enc):
        cases = ["Person", "Acme Corp", "alice-jane", "AI Model", "works_at", "eid-001"]
        for case in cases:
            result = enc.normalize(case)
            assert _is_tdfol_atom(result), f"{case!r} → {result!r} is not a valid atom"


# ---------------------------------------------------------------------------
# 3. KGAtomEncoder domain methods
# ---------------------------------------------------------------------------
class TestKGAtomEncoderDomainMethods:
    @pytest.fixture
    def enc(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGAtomEncoder,
        )
        return KGAtomEncoder()

    def test_encode_entity_type_simple(self, enc):
        assert enc.encode_entity_type("Person") == "person"

    def test_encode_entity_type_multiword(self, enc):
        result = enc.encode_entity_type("AI Model")
        assert _is_tdfol_atom(result)

    def test_encode_name_simple(self, enc):
        assert enc.encode_name("Alice") == "alice"

    def test_encode_name_with_space(self, enc):
        result = enc.encode_name("Acme Corp")
        assert _is_tdfol_atom(result)
        assert "acme" in result

    def test_encode_relationship_type(self, enc):
        assert enc.encode_relationship_type("works_at") == "works_at"

    def test_encode_relationship_type_camel(self, enc):
        result = enc.encode_relationship_type("worksAt")
        assert _is_tdfol_atom(result)

    def test_encode_entity_id_uuid_like(self, enc):
        result = enc.encode_entity_id("eid-abc-123")
        assert _is_tdfol_atom(result)

    def test_encode_entity_id_slash(self, enc):
        result = enc.encode_entity_id("entity/456")
        assert _is_tdfol_atom(result)

    def test_encode_property_key(self, enc):
        assert enc.encode_property_key("age") == "age"

    def test_encode_property_key_hyphen(self, enc):
        result = enc.encode_property_key("first-name")
        assert _is_tdfol_atom(result)


# ---------------------------------------------------------------------------
# 4. KGAtomEncoder compound atoms
# ---------------------------------------------------------------------------
class TestKGAtomEncoderCompound:
    @pytest.fixture
    def enc(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGAtomEncoder,
        )
        return KGAtomEncoder()

    def test_atom_for_entity(self, enc):
        result = enc.atom_for_entity("Person", "Alice")
        assert result == "person_alice"
        assert _is_tdfol_atom(result)

    def test_atom_for_entity_exists(self, enc):
        result = enc.atom_for_entity_exists("Person", "Alice")
        assert result == "person_alice_exists"
        assert _is_tdfol_atom(result)

    def test_atom_for_path_exists(self, enc):
        result = enc.atom_for_path_exists("Person", "Organization")
        assert _is_tdfol_atom(result)
        assert "person" in result
        assert "organization" in result

    def test_atom_for_entity_property(self, enc):
        result = enc.atom_for_entity_property("eid_001", "age")
        assert _is_tdfol_atom(result)
        assert "age" in result

    def test_atom_for_entity_truncates(self, enc):
        result = enc.atom_for_entity("A" * 50, "B" * 50)
        assert len(result) <= 64


# ---------------------------------------------------------------------------
# 5. KGWitnessBuilder — import and instantiation
# ---------------------------------------------------------------------------
class TestKGWitnessBuilderImport:
    def test_importable_from_module(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGWitnessBuilder,
        )
        assert KGWitnessBuilder is not None

    def test_importable_from_query_package(self):
        from ipfs_datasets_py.knowledge_graphs.query import KGWitnessBuilder
        assert KGWitnessBuilder is not None

    def test_in_query_all(self):
        from ipfs_datasets_py.knowledge_graphs import query
        assert "KGWitnessBuilder" in query.__all__

    def test_instantiation_defaults(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGWitnessBuilder,
        )
        b = KGWitnessBuilder()
        assert b.circuit_version == 1
        assert b.ruleset_id == "TDFOL_v1"

    def test_instantiation_v2(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGWitnessBuilder,
        )
        b = KGWitnessBuilder(circuit_version=2)
        assert b.circuit_version == 2


# ---------------------------------------------------------------------------
# 6. KGWitnessBuilder.entity_exists
# ---------------------------------------------------------------------------
class TestKGWitnessBuilderEntityExists:
    @pytest.fixture
    def builder(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGWitnessBuilder,
        )
        return KGWitnessBuilder()

    def test_returns_dict(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001", 0.95)
        assert isinstance(w, dict)

    def test_has_required_keys(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001")
        for key in ("private_axioms", "theorem", "intermediate_steps",
                    "axioms_commitment_hex", "theorem_hash_hex",
                    "circuit_version", "ruleset_id"):
            assert key in w, f"missing key: {key}"

    def test_theorem_is_valid_atom(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001")
        assert _is_tdfol_atom(w["theorem"])

    def test_theorem_contains_entity_type(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001")
        assert "person" in w["theorem"]

    def test_theorem_contains_name(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001")
        assert "alice" in w["theorem"]

    def test_private_axioms_are_valid(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001", 0.9)
        for axiom in w["private_axioms"]:
            if " -> " in axiom:
                parts = axiom.split(" -> ", 1)
                assert _is_tdfol_atom(parts[0]) and _is_tdfol_atom(parts[1])
            else:
                assert _is_tdfol_atom(axiom), f"invalid axiom: {axiom!r}"

    def test_circuit_version_1(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001")
        assert w["circuit_version"] == 1

    def test_ruleset_id(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001")
        assert w["ruleset_id"] == "TDFOL_v1"

    def test_theorem_hash_is_64_hex(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001")
        assert len(w["theorem_hash_hex"]) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", w["theorem_hash_hex"])

    def test_theorem_hash_matches_theorem(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001")
        expected = _sha256_hex(w["theorem"])
        assert w["theorem_hash_hex"] == expected

    def test_axioms_commitment_is_64_hex(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001")
        assert len(w["axioms_commitment_hex"]) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", w["axioms_commitment_hex"])


# ---------------------------------------------------------------------------
# 7. KGWitnessBuilder.path_exists
# ---------------------------------------------------------------------------
class TestKGWitnessBuilderPathExists:
    @pytest.fixture
    def builder(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGWitnessBuilder,
        )
        return KGWitnessBuilder()

    def test_basic_path(self, builder):
        w = builder.path_exists(
            path_ids=["eid_001", "eid_002"],
            rel_types=["knows"],
            start_type="Person",
            end_type="Person",
        )
        assert isinstance(w, dict)

    def test_theorem_is_valid_atom(self, builder):
        w = builder.path_exists(["eid_001", "eid_002"], start_type="Person", end_type="Org")
        assert _is_tdfol_atom(w["theorem"])

    def test_axioms_reference_path_ids(self, builder):
        w = builder.path_exists(["eid_001", "eid_002"], start_type="Person", end_type="Org")
        axioms_text = " ".join(w["private_axioms"])
        assert "eid_001" in axioms_text or "eid001" in axioms_text

    def test_empty_path_raises(self, builder):
        with pytest.raises(ValueError, match="non-empty"):
            builder.path_exists([])

    def test_path_with_rel_types(self, builder):
        w = builder.path_exists(
            ["a", "b", "c"],
            rel_types=["knows", "works_at"],
            start_type="person",
            end_type="org",
        )
        axioms_text = " ".join(w["private_axioms"])
        assert "knows" in axioms_text or "works_at" in axioms_text

    def test_long_path(self, builder):
        ids = [f"eid_{i:03d}" for i in range(10)]
        w = builder.path_exists(ids, start_type="person", end_type="org")
        assert len(w["private_axioms"]) >= 2

    def test_axioms_all_valid(self, builder):
        w = builder.path_exists(["eid_a", "eid_b"], start_type="person", end_type="org")
        for axiom in w["private_axioms"]:
            if " -> " in axiom:
                parts = axiom.split(" -> ", 1)
                assert _is_tdfol_atom(parts[0]) and _is_tdfol_atom(parts[1])
            else:
                assert _is_tdfol_atom(axiom), f"invalid: {axiom!r}"


# ---------------------------------------------------------------------------
# 8. KGWitnessBuilder.entity_property
# ---------------------------------------------------------------------------
class TestKGWitnessBuilderEntityProperty:
    @pytest.fixture
    def builder(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGWitnessBuilder,
        )
        return KGWitnessBuilder()

    def test_basic_property(self, builder):
        vh = _sha256_hex("30")
        w = builder.entity_property("eid_001", "age", vh)
        assert isinstance(w, dict)

    def test_theorem_is_valid_atom(self, builder):
        vh = _sha256_hex("30")
        w = builder.entity_property("eid_001", "age", vh)
        assert _is_tdfol_atom(w["theorem"])

    def test_theorem_contains_property_key(self, builder):
        vh = _sha256_hex("30")
        w = builder.entity_property("eid_001", "age", vh)
        assert "age" in w["theorem"]

    def test_axioms_valid(self, builder):
        vh = _sha256_hex("hello")
        w = builder.entity_property("eid_001", "name", vh)
        for axiom in w["private_axioms"]:
            if " -> " in axiom:
                parts = axiom.split(" -> ", 1)
                assert _is_tdfol_atom(parts[0]) and _is_tdfol_atom(parts[1])
            else:
                assert _is_tdfol_atom(axiom), f"invalid: {axiom!r}"


# ---------------------------------------------------------------------------
# 9. KGWitnessBuilder.query_answer_count
# ---------------------------------------------------------------------------
class TestKGWitnessBuilderQueryAnswerCount:
    @pytest.fixture
    def builder(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGWitnessBuilder,
        )
        return KGWitnessBuilder()

    def test_basic_count(self, builder):
        w = builder.query_answer_count(min_count=3, actual_count=5)
        assert isinstance(w, dict)

    def test_theorem_contains_min(self, builder):
        w = builder.query_answer_count(min_count=3, actual_count=5)
        assert "3" in w["theorem"]

    def test_exact_count_passes(self, builder):
        w = builder.query_answer_count(min_count=5, actual_count=5)
        assert isinstance(w, dict)

    def test_below_min_raises(self, builder):
        with pytest.raises(ValueError, match="actual_count"):
            builder.query_answer_count(min_count=10, actual_count=3)

    def test_theorem_is_valid_atom(self, builder):
        w = builder.query_answer_count(min_count=1, actual_count=3)
        assert _is_tdfol_atom(w["theorem"])


# ---------------------------------------------------------------------------
# 10. KGWitnessBuilder circuit version 2
# ---------------------------------------------------------------------------
class TestKGWitnessBuilderV2:
    @pytest.fixture
    def builder(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGWitnessBuilder,
        )
        return KGWitnessBuilder(circuit_version=2)

    def test_circuit_version_2_in_witness(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001")
        assert w["circuit_version"] == 2

    def test_intermediate_steps_non_empty_for_v2(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001")
        assert len(w["intermediate_steps"]) >= 1

    def test_intermediate_steps_valid_atoms(self, builder):
        w = builder.entity_exists("Person", "Alice", "eid_001")
        for step in w["intermediate_steps"]:
            assert _is_tdfol_atom(step), f"invalid step: {step!r}"

    def test_custom_intermediate_steps(self, builder):
        w = builder.entity_exists(
            "Person", "Alice", "eid_001",
            intermediate_steps=["person_alice_exists"],
        )
        assert w["intermediate_steps"] == ["person_alice_exists"]


# ---------------------------------------------------------------------------
# 11. KGEntityFormula.to_tdfol_atoms (groth16_bridge.py update)
# ---------------------------------------------------------------------------
class TestKGEntityFormulaToTDFOLAtoms:
    def test_entity_exists_returns_dict(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import (
            KGEntityFormula,
        )
        result = KGEntityFormula.to_tdfol_atoms("entity_exists", "Person", "Alice", "eid_001")
        assert isinstance(result, dict)

    def test_entity_exists_theorem_is_atom(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import (
            KGEntityFormula,
        )
        result = KGEntityFormula.to_tdfol_atoms("entity_exists", "Person", "Alice", "eid_001")
        assert _is_tdfol_atom(result["theorem"])

    def test_entity_exists_axioms_are_valid(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import (
            KGEntityFormula,
        )
        result = KGEntityFormula.to_tdfol_atoms("entity_exists", "Person", "Alice", "eid_001")
        for axiom in result["axioms"]:
            assert _is_tdfol_atom(axiom), f"invalid axiom: {axiom!r}"

    def test_path_exists_returns_dict(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import (
            KGEntityFormula,
        )
        result = KGEntityFormula.to_tdfol_atoms("path_exists", "Person", "Organization")
        assert isinstance(result, dict)
        assert _is_tdfol_atom(result["theorem"])

    def test_entity_property_returns_dict(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import (
            KGEntityFormula,
        )
        result = KGEntityFormula.to_tdfol_atoms(
            "entity_property", "eid_001", "age", entity_id="eid_001"
        )
        assert isinstance(result, dict)
        assert _is_tdfol_atom(result["theorem"])

    def test_proof_type_in_result(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import (
            KGEntityFormula,
        )
        result = KGEntityFormula.to_tdfol_atoms("entity_exists", "Person", "Alice")
        assert result["proof_type"] == "entity_exists"

    def test_unknown_proof_type_fallback(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import (
            KGEntityFormula,
        )
        result = KGEntityFormula.to_tdfol_atoms("unknown_type", "x", "y")
        assert isinstance(result, dict)
        assert "theorem" in result


# ---------------------------------------------------------------------------
# 12. Integration: witness compatible with groth16_bridge describe_groth16_status
# ---------------------------------------------------------------------------
class TestWitnessIntegration:
    def test_describe_groth16_status_still_works(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import (
            describe_groth16_status,
        )
        status = describe_groth16_status()
        assert isinstance(status, dict)
        assert "backend" in status

    def test_create_prover_with_witness_builder(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import (
            create_groth16_kg_prover,
        )
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGWitnessBuilder,
        )
        kg = KnowledgeGraph("witness_test")
        alice = kg.add_entity("person", "Alice", confidence=0.9)
        prover = create_groth16_kg_prover(kg)
        builder = KGWitnessBuilder()
        witness = builder.entity_exists("person", "Alice", alice.entity_id, 0.9)
        # The witness should have a theorem that matches the prover's domain
        assert "alice" in witness["theorem"]

    def test_witness_builder_and_zkp_prover_compatible(self):
        """Witness theorem should overlap conceptually with KGZKProver proof."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
            KGWitnessBuilder,
        )
        kg = KnowledgeGraph("compat_test")
        alice = kg.add_entity("person", "Alice", confidence=0.95)

        prover = KGZKProver(kg)
        stmt = prover.prove_entity_exists("person", "Alice")
        assert stmt is not None

        builder = KGWitnessBuilder()
        witness = builder.entity_exists("person", "Alice", alice.entity_id, 0.95)
        # Both should agree on entity type and name
        assert "person" in witness["theorem"]
        assert "alice" in witness["theorem"]


# ---------------------------------------------------------------------------
# 13. Documentation integrity
# ---------------------------------------------------------------------------
class TestDocumentationIntegrity:
    def test_master_status_has_v3_22_36(self):
        # v3.22.36 may appear in CHANGELOG but MASTER_STATUS advances to 3.22.37+
        # Accept either MASTER_STATUS or CHANGELOG containing the version
        ms_content = _read(_MASTER)
        cl_content = _read(_CHANGELOG)
        assert "3.22.36" in ms_content or "3.22.36" in cl_content, \
            "3.22.36 should appear in MASTER_STATUS.md or CHANGELOG"

    def test_roadmap_has_v3_22_36(self):
        content = _read(_ROADMAP)
        assert "3.22.36" in content, "ROADMAP.md should mention v3.22.36"

    def test_deferred_has_p13(self):
        content = _read(_DEFERRED)
        assert "P13" in content, "DEFERRED_FEATURES.md should have P13 section"

    def test_deferred_mentions_witness_builder(self):
        content = _read(_DEFERRED)
        assert "KGWitnessBuilder" in content or "witness" in content.lower()

    def test_changelog_has_session_82(self):
        content = _read(_CHANGELOG)
        assert "session 82" in content.lower() or "82" in content

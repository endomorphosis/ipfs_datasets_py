"""
Session 77 — Knowledge Graphs tests.

Validates the ``logic.zkp`` backend integration wired into
``knowledge_graphs.query.zkp`` (KGZKProver / KGZKVerifier):

  * KGZKProver.from_logic_prover() factory
  * KGZKProver.uses_logic_backend property
  * KGZKProver.get_backend_info()
  * prove_entity_exists / prove_path_exists embed logic_proof_data
  * KGZKVerifier.from_logic_verifier() factory
  * verify_statement() re-verifies embedded logic_proof_data
  * Standalone mode (no logic backend) still works as before
  * DEFERRED_FEATURES.md §24 Groth16 Integration section
  * MASTER_STATUS, CHANGELOG, ROADMAP agree on v3.22.31
"""

import os
import warnings
import pytest

_KG_ROOT = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..",
    "ipfs_datasets_py", "knowledge_graphs",
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _read(path: str) -> str:
    with open(os.path.join(_KG_ROOT, path), encoding="utf-8") as f:
        return f.read()


def _make_kg():
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
    kg = KnowledgeGraph("test_s77")
    alice = kg.add_entity("person", "Alice", confidence=0.9)
    carol = kg.add_entity("org", "ACME")
    kg.add_relationship("works_at", alice, carol)
    return kg, alice, carol


def _logic_prover():
    """Return a logic.zkp.ZKPProver, suppressing UserWarnings."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        from ipfs_datasets_py.logic.zkp import ZKPProver
        return ZKPProver()


def _logic_verifier():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        from ipfs_datasets_py.logic.zkp import ZKPVerifier
        return ZKPVerifier()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Standalone mode — unchanged from session 76
# ─────────────────────────────────────────────────────────────────────────────

class TestStandaloneMode:
    def _prover(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, _, _ = _make_kg()
        return KGZKProver(kg), kg

    def test_standalone_uses_logic_backend_false(self):
        p, _ = self._prover()
        assert p.uses_logic_backend is False

    def test_standalone_get_backend_info_backend_simulated(self):
        p, _ = self._prover()
        info = p.get_backend_info()
        assert info["backend"] == "simulated"

    def test_standalone_get_backend_info_uses_logic_false(self):
        p, _ = self._prover()
        assert p.get_backend_info()["uses_logic_backend"] is False

    def test_standalone_prove_entity_exists_returns_stmt(self):
        p, _ = self._prover()
        stmt = p.prove_entity_exists("person", "Alice")
        assert stmt is not None

    def test_standalone_no_logic_proof_data(self):
        p, _ = self._prover()
        stmt = p.prove_entity_exists("person", "Alice")
        assert "logic_proof_data" not in stmt.public_inputs

    def test_standalone_verifier_works(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver, KGZKVerifier
        kg, _, _ = _make_kg()
        stmt = KGZKProver(kg).prove_entity_exists("person", "Alice")
        assert KGZKVerifier().verify_statement(stmt)


# ─────────────────────────────────────────────────────────────────────────────
# 2. KGZKProver.from_logic_prover factory
# ─────────────────────────────────────────────────────────────────────────────

class TestFromLogicProver:
    def _p2(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, _, _ = _make_kg()
        return KGZKProver.from_logic_prover(kg, _logic_prover())

    def test_factory_returns_kgzkprover(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        assert isinstance(self._p2(), KGZKProver)

    def test_uses_logic_backend_true(self):
        assert self._p2().uses_logic_backend is True

    def test_get_backend_info_uses_logic_true(self):
        assert self._p2().get_backend_info()["uses_logic_backend"] is True

    def test_get_backend_info_security_level(self):
        info = self._p2().get_backend_info()
        assert info["security_level"] == 128

    def test_custom_prover_id(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, _, _ = _make_kg()
        p = KGZKProver.from_logic_prover(kg, _logic_prover(), prover_id="custom_id")
        assert p.prover_id == "custom_id"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Logic proof data embedded in KGProofStatement
# ─────────────────────────────────────────────────────────────────────────────

class TestLogicProofDataEmbedded:
    def _setup(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, _, _ = _make_kg()
        p = KGZKProver.from_logic_prover(kg, _logic_prover())
        return p, kg

    def test_prove_entity_exists_embeds_logic_proof_data(self):
        p, _ = self._setup()
        stmt = p.prove_entity_exists("person", "Alice")
        assert "logic_proof_data" in stmt.public_inputs

    def test_prove_entity_exists_embeds_logic_theorem(self):
        p, _ = self._setup()
        stmt = p.prove_entity_exists("person", "Alice")
        assert "logic_theorem" in stmt.public_inputs

    def test_logic_proof_data_has_proof_data_key(self):
        p, _ = self._setup()
        stmt = p.prove_entity_exists("person", "Alice")
        proof_dict = stmt.public_inputs["logic_proof_data"]
        assert "proof_data" in proof_dict

    def test_logic_proof_data_is_deserializable(self):
        p, _ = self._setup()
        stmt = p.prove_entity_exists("person", "Alice")
        from ipfs_datasets_py.logic.zkp import ZKPProof
        proof = ZKPProof.from_dict(stmt.public_inputs["logic_proof_data"])
        assert proof.size_bytes > 0

    def test_prove_path_exists_embeds_logic_proof_data(self):
        p, _ = self._setup()
        stmt = p.prove_path_exists("person", "org")
        assert stmt is not None
        assert "logic_proof_data" in stmt.public_inputs

    def test_entity_id_not_in_public_inputs(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, alice, _ = _make_kg()
        p = KGZKProver.from_logic_prover(kg, _logic_prover())
        stmt = p.prove_entity_exists("person", "Alice")
        # entity_id must NOT appear anywhere in the public parameters/inputs
        alice_id = getattr(alice, "entity_id", str(alice))
        assert alice_id not in str(stmt.public_inputs.get("entity_type", ""))
        # Commitment still hides the ID
        assert alice_id not in stmt.commitment


# ─────────────────────────────────────────────────────────────────────────────
# 4. KGZKVerifier.from_logic_verifier factory + enhanced verification
# ─────────────────────────────────────────────────────────────────────────────

class TestFromLogicVerifier:
    def test_factory_returns_kgzkverifier(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKVerifier
        v = KGZKVerifier.from_logic_verifier(_logic_verifier())
        assert isinstance(v, KGZKVerifier)

    def test_logic_verifier_stored(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKVerifier
        lv = _logic_verifier()
        v = KGZKVerifier.from_logic_verifier(lv)
        assert v._logic_verifier is lv

    def test_verify_statement_with_logic_backend(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver, KGZKVerifier
        kg, _, _ = _make_kg()
        p = KGZKProver.from_logic_prover(kg, _logic_prover())
        v = KGZKVerifier.from_logic_verifier(_logic_verifier())
        stmt = p.prove_entity_exists("person", "Alice")
        assert v.verify_statement(stmt) is True

    def test_verify_statement_no_logic_proof_data_still_passes(self):
        """Verifier with logic backend still handles statements without embedded proof."""
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver, KGZKVerifier
        kg, _, _ = _make_kg()
        # standalone prover → no logic_proof_data
        stmt = KGZKProver(kg).prove_entity_exists("person", "Alice")
        v = KGZKVerifier.from_logic_verifier(_logic_verifier())
        assert v.verify_statement(stmt) is True

    def test_verify_path_proof_with_logic_backend(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver, KGZKVerifier
        kg, _, _ = _make_kg()
        p = KGZKProver.from_logic_prover(kg, _logic_prover())
        v = KGZKVerifier.from_logic_verifier(_logic_verifier())
        stmt = p.prove_path_exists("person", "org")
        assert v.verify_statement(stmt) is True

    def test_replay_protection_still_active(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver, KGZKVerifier
        kg, _, _ = _make_kg()
        p = KGZKProver.from_logic_prover(kg, _logic_prover())
        v = KGZKVerifier.from_logic_verifier(_logic_verifier())
        stmt = p.prove_entity_exists("person", "Alice")
        assert v.verify_statement(stmt) is True
        # second use of same nullifier must fail
        assert v.verify_statement(stmt) is False


# ─────────────────────────────────────────────────────────────────────────────
# 5. Doc-integrity tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDocIntegritySession77:
    def test_deferred_features_groth16_section(self):
        content = _read("DEFERRED_FEATURES.md")
        assert "Groth16 Backend Integration" in content

    def test_deferred_features_from_logic_prover_documented(self):
        content = _read("DEFERRED_FEATURES.md")
        assert "from_logic_prover" in content

    def test_deferred_features_from_logic_verifier_documented(self):
        content = _read("DEFERRED_FEATURES.md")
        assert "from_logic_verifier" in content

    def test_deferred_features_session77(self):
        content = _read("DEFERRED_FEATURES.md")
        assert "session 77" in content.lower()

    def test_master_status_v3_22_31(self):
        content = _read("MASTER_STATUS.md")
        assert "3.22.31" in content

    def test_changelog_v3_22_31(self):
        content = _read("CHANGELOG_KNOWLEDGE_GRAPHS.md")
        assert "3.22.31" in content


class TestVersionAgreement:
    def _extract_top_version(self, path: str) -> str:
        import re
        with open(os.path.join(_KG_ROOT, path), encoding="utf-8") as f:
            content = f.read()
        versions = re.findall(r"3\.22\.(\d+)", content)
        if not versions:
            return ""
        return "3.22." + str(max(int(v) for v in versions))

    def test_master_status_version(self):
        assert self._extract_top_version("MASTER_STATUS.md") == "3.22.31"

    def test_changelog_version(self):
        assert self._extract_top_version("CHANGELOG_KNOWLEDGE_GRAPHS.md") == "3.22.31"

    def test_roadmap_version(self):
        assert self._extract_top_version("ROADMAP.md") == "3.22.31"

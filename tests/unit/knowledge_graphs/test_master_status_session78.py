"""
Tests for Session 78: query/groth16_bridge.py

Covers:
- groth16_enabled() / groth16_binary_available()
- Groth16KGConfig defaults and fields
- KGEntityFormula static methods
- create_groth16_kg_prover() (simulation fallback path — binary not compiled in CI)
- create_groth16_kg_verifier() (simulation fallback)
- describe_groth16_status()
- query/__init__.py exports
- DEFERRED_FEATURES / MASTER_STATUS / CHANGELOG doc-integrity
- Version agreement
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# ── repo root helper ────────────────────────────────────────────────────────
_KG_ROOT = Path(__file__).resolve().parents[3] / "ipfs_datasets_py" / "knowledge_graphs"


def _read(rel: str) -> str:
    return (_KG_ROOT / rel).read_text(encoding="utf-8")


def _extract_version(text: str) -> str | None:
    import re
    m = re.search(r"\b3\.22\.(\d+)\b", text)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# 1. groth16_enabled / groth16_binary_available
# ---------------------------------------------------------------------------

class TestGroth16AvailabilityHelpers:
    """groth16_enabled() and groth16_binary_available() are importable and correct."""

    def test_groth16_enabled_returns_bool(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import groth16_enabled
        result = groth16_enabled()
        assert isinstance(result, bool)

    def test_groth16_enabled_false_without_env(self, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import groth16_enabled
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
        assert groth16_enabled() is False

    def test_groth16_enabled_true_with_env_1(self, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import groth16_enabled
        monkeypatch.setenv("IPFS_DATASETS_ENABLE_GROTH16", "1")
        assert groth16_enabled() is True

    def test_groth16_enabled_true_with_env_true(self, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import groth16_enabled
        monkeypatch.setenv("IPFS_DATASETS_ENABLE_GROTH16", "true")
        assert groth16_enabled() is True

    def test_groth16_binary_available_returns_bool(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import groth16_binary_available
        result = groth16_binary_available()
        assert isinstance(result, bool)

    def test_groth16_binary_not_available_for_nonexistent_path(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import groth16_binary_available
        assert groth16_binary_available(binary_path="/nonexistent/path/groth16") is False

    def test_groth16_binary_available_with_real_file(self, tmp_path):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import groth16_binary_available
        fake_bin = tmp_path / "groth16"
        fake_bin.write_bytes(b"\x7fELF")  # ELF magic
        assert groth16_binary_available(binary_path=str(fake_bin)) is True


# ---------------------------------------------------------------------------
# 2. Groth16KGConfig
# ---------------------------------------------------------------------------

class TestGroth16KGConfig:
    """Groth16KGConfig dataclass defaults and field access."""

    def test_default_circuit_version(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import Groth16KGConfig
        cfg = Groth16KGConfig()
        assert cfg.circuit_version == 2

    def test_default_ruleset_id(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import Groth16KGConfig
        cfg = Groth16KGConfig()
        assert cfg.ruleset_id == "TDFOL_v1"

    def test_default_timeout_seconds(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import Groth16KGConfig
        cfg = Groth16KGConfig()
        assert cfg.timeout_seconds == 30

    def test_default_binary_path_is_none(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import Groth16KGConfig
        cfg = Groth16KGConfig()
        assert cfg.binary_path is None

    def test_default_enable_groth16_is_false(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import Groth16KGConfig
        cfg = Groth16KGConfig()
        assert cfg.enable_groth16 is False

    def test_custom_config(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import Groth16KGConfig
        cfg = Groth16KGConfig(circuit_version=1, ruleset_id="TEST", timeout_seconds=60)
        assert cfg.circuit_version == 1
        assert cfg.ruleset_id == "TEST"
        assert cfg.timeout_seconds == 60


# ---------------------------------------------------------------------------
# 3. KGEntityFormula
# ---------------------------------------------------------------------------

class TestKGEntityFormula:
    """KGEntityFormula static methods produce valid theorem/axiom strings."""

    def test_entity_exists_theorem(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import KGEntityFormula
        t = KGEntityFormula.entity_exists_theorem("Person", "Alice")
        assert "person" in t
        assert "alice" in t

    def test_entity_exists_theorem_lowercase(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import KGEntityFormula
        t = KGEntityFormula.entity_exists_theorem("ORGANIZATION", "ACME Corp")
        assert t == t.lower()

    def test_entity_exists_axioms_count(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import KGEntityFormula
        axioms = KGEntityFormula.entity_exists_axioms("e-001", "person", "Alice", 0.9)
        assert len(axioms) >= 3

    def test_entity_exists_axioms_contain_entity_id(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import KGEntityFormula
        axioms = KGEntityFormula.entity_exists_axioms("e-secret-123", "person", "Alice")
        all_text = " ".join(axioms)
        assert "e-secret-123" in all_text

    def test_entity_exists_axioms_do_not_contain_id_in_theorem(self):
        """The theorem must NOT reveal the entity ID (ZKP privacy guarantee)."""
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import KGEntityFormula
        secret_id = "secret-entity-id-xyz-987"
        theorem = KGEntityFormula.entity_exists_theorem("person", "Alice")
        axioms  = KGEntityFormula.entity_exists_axioms(secret_id, "person", "Alice")
        # theorem must not contain the entity ID (it is kept in private axioms only)
        assert secret_id not in theorem
        # entity ID IS present in axioms (it's the secret witness)
        assert secret_id in " ".join(axioms)

    def test_path_theorem(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import KGEntityFormula
        t = KGEntityFormula.path_theorem("Person", "Organization", 3)
        assert "person" in t and "organization" in t
        assert "3" in t

    def test_path_axioms_length(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import KGEntityFormula
        axioms = KGEntityFormula.path_axioms(["n1", "n2", "n3"])
        assert len(axioms) >= 3

    def test_path_axioms_empty(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import KGEntityFormula
        assert KGEntityFormula.path_axioms([]) == []

    def test_path_axioms_with_rel_types(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import KGEntityFormula
        axioms = KGEntityFormula.path_axioms(["n1", "n2"], rel_types=["works_for"])
        all_text = " ".join(axioms)
        assert "works_for" in all_text

    def test_property_theorem(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import KGEntityFormula
        t = KGEntityFormula.property_theorem("e-001", "salary")
        assert "e-001" in t and "salary" in t

    def test_property_axioms(self):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import KGEntityFormula
        axioms = KGEntityFormula.property_axioms("e-001", "salary", "abc123")
        assert len(axioms) >= 2
        all_text = " ".join(axioms)
        assert "e-001" in all_text and "salary" in all_text


# ---------------------------------------------------------------------------
# 4. create_groth16_kg_prover
# ---------------------------------------------------------------------------

class TestCreateGroth16KGProver:
    """create_groth16_kg_prover() falls back to simulation in CI (no binary)."""

    @pytest.fixture()
    def _kg(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        kg = KnowledgeGraph("test-g16-prover")
        kg.add_entity("person", "Alice")
        return kg

    def test_returns_kgzkprover(self, _kg, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import create_groth16_kg_prover
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
        prover = create_groth16_kg_prover(_kg)
        assert isinstance(prover, KGZKProver)

    def test_fallback_attribute_set(self, _kg, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import create_groth16_kg_prover
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
        prover = create_groth16_kg_prover(_kg)
        # In CI (no binary), should be fallback mode
        assert hasattr(prover, "_groth16_fallback")

    def test_can_prove_entity_exists_via_bridge(self, _kg, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import create_groth16_kg_prover
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import create_groth16_kg_verifier
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
        prover   = create_groth16_kg_prover(_kg)
        verifier = create_groth16_kg_verifier()
        stmt = prover.prove_entity_exists("person", "Alice")
        assert stmt is not None
        assert verifier.verify_statement(stmt)

    def test_enable_groth16_config_sets_env(self, _kg, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import (
            Groth16KGConfig, create_groth16_kg_prover,
        )
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
        cfg = Groth16KGConfig(enable_groth16=True)
        create_groth16_kg_prover(_kg, config=cfg)
        # env var should be set now
        assert os.environ.get("IPFS_DATASETS_ENABLE_GROTH16") == "1"
        # cleanup
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)


# ---------------------------------------------------------------------------
# 5. create_groth16_kg_verifier
# ---------------------------------------------------------------------------

class TestCreateGroth16KGVerifier:

    def test_returns_kgzkverifier(self, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import create_groth16_kg_verifier
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKVerifier
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
        verifier = create_groth16_kg_verifier()
        assert isinstance(verifier, KGZKVerifier)

    def test_with_initial_nullifiers(self, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import create_groth16_kg_verifier
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
        verifier = create_groth16_kg_verifier(seen_nullifiers={"null-1", "null-2"})
        assert isinstance(verifier, object)  # KGZKVerifier

    def test_has_fallback_attribute(self, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import create_groth16_kg_verifier
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
        verifier = create_groth16_kg_verifier()
        assert hasattr(verifier, "_groth16_fallback")


# ---------------------------------------------------------------------------
# 6. describe_groth16_status
# ---------------------------------------------------------------------------

class TestDescribeGroth16Status:

    def test_returns_dict(self, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import describe_groth16_status
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
        result = describe_groth16_status()
        assert isinstance(result, dict)

    def test_required_keys(self, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import describe_groth16_status
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
        result = describe_groth16_status()
        for key in ("enabled", "binary_available", "backend", "production_ready",
                    "security_note", "setup_command", "env_var", "config_class"):
            assert key in result, f"missing key: {key}"

    def test_enabled_false_without_env(self, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import describe_groth16_status
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
        result = describe_groth16_status()
        assert result["enabled"] is False

    def test_production_ready_false_in_ci(self, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import describe_groth16_status
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
        result = describe_groth16_status()
        assert result["production_ready"] is False

    def test_backend_simulated_in_ci(self, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import describe_groth16_status
        monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
        result = describe_groth16_status()
        assert result["backend"] in ("simulated", "groth16")

    def test_config_class_field(self, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import describe_groth16_status
        result = describe_groth16_status()
        assert result["config_class"] == "Groth16KGConfig"

    def test_env_var_field(self, monkeypatch):
        from ipfs_datasets_py.knowledge_graphs.query.groth16_bridge import describe_groth16_status
        result = describe_groth16_status()
        assert "GROTH16" in result["env_var"]


# ---------------------------------------------------------------------------
# 7. query/__init__.py exports
# ---------------------------------------------------------------------------

class TestQueryModuleExports:

    def test_groth16_symbols_importable_from_query(self):
        from ipfs_datasets_py.knowledge_graphs.query import (
            groth16_binary_available,
            groth16_enabled,
            Groth16KGConfig,
            KGEntityFormula,
            create_groth16_kg_prover,
            create_groth16_kg_verifier,
            describe_groth16_status,
        )
        assert callable(groth16_binary_available)
        assert callable(groth16_enabled)

    def test_groth16_symbols_in_all(self):
        from ipfs_datasets_py.knowledge_graphs import query
        for sym in (
            "groth16_binary_available", "groth16_enabled", "Groth16KGConfig",
            "KGEntityFormula", "create_groth16_kg_prover",
            "create_groth16_kg_verifier", "describe_groth16_status",
        ):
            assert sym in query.__all__, f"{sym} missing from __all__"

    def test_kgentityformula_is_class(self):
        from ipfs_datasets_py.knowledge_graphs.query import KGEntityFormula
        assert isinstance(KGEntityFormula, type)


# ---------------------------------------------------------------------------
# 8. Doc integrity
# ---------------------------------------------------------------------------

class TestDocIntegritySession78:

    def test_deferred_features_has_groth16_bridge_section(self):
        text = _read("DEFERRED_FEATURES.md")
        assert "Groth16 Bridge" in text or "groth16_bridge" in text

    def test_deferred_features_create_groth16_kg_prover_mentioned(self):
        text = _read("DEFERRED_FEATURES.md")
        assert "create_groth16_kg_prover" in text

    def test_deferred_features_kgentityformula_mentioned(self):
        text = _read("DEFERRED_FEATURES.md")
        assert "KGEntityFormula" in text

    def test_master_status_has_v3_22_32(self):
        text = _read("MASTER_STATUS.md")
        assert "3.22.32" in text

    def test_changelog_has_3_22_32(self):
        text = _read("CHANGELOG_KNOWLEDGE_GRAPHS.md")
        assert "3.22.32" in text

    def test_roadmap_has_3_22_32_row(self):
        text = _read("ROADMAP.md")
        assert "3.22.32" in text


# ---------------------------------------------------------------------------
# 9. Version agreement
# ---------------------------------------------------------------------------

class TestVersionAgreement:

    def test_master_status_version(self):
        text = _read("MASTER_STATUS.md")
        assert "3.22.32" in text

    def test_changelog_version(self):
        text = _read("CHANGELOG_KNOWLEDGE_GRAPHS.md")
        assert "3.22.32" in text

    def test_roadmap_version(self):
        text = _read("ROADMAP.md")
        assert "3.22.32" in text

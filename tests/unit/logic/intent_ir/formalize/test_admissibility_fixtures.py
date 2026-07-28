"""Offline Intent formalization fixtures for admissibility gate inputs (LIG-006).

These fixtures freeze Intent IR documents and their deterministic formalization
artifacts.  The manifest binds formal artifact CIDs and expected gate outcomes
(allow / reject / abstain with closed reason codes).  Rebuild from Intent IR
must reproduce the pinned identities byte-for-byte.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.admissibility.profiles import (
    is_known_profile,
    parse_profile_id,
)
from ipfs_datasets_py.logic.admissibility.reasons import (
    AdmissibilityStatus,
    default_status_for_reason,
    parse_reason_code,
    parse_status,
    reason_code_set,
)
from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.intent_ir.canonicalize import (
    canonical_intent_ir_json,
    intent_ir_sha256,
)
from ipfs_datasets_py.logic.intent_ir.decoder import decode_intent_ir
from ipfs_datasets_py.logic.intent_ir.formalize.compiler import (
    INTENT_FORMALIZATION_COMPILER_VERSION,
    INTENT_FORMALIZATION_DOMAIN,
    INTENT_FORMALIZATION_PRODUCER_ID,
    IntentFormalizationCompiler,
)
from ipfs_datasets_py.logic.intent_ir.schema import IntentKind, validate_intent_ir


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "intent_ir"
    / "admissibility"
)

REQUIRED_CASE_IDS = (
    "benign_skill",
    "legally_risky_effect",
    "security_sensitive_resource",
    "incomplete_unsupported_semantics",
)

REQUIRED_STRATA = (
    "benign",
    "legal_risk",
    "security_risk",
    "incomplete",
)

REQUIRED_CASE_FIELDS = (
    "case_id",
    "stratum",
    "source_kind",
    "description",
    "profile_id",
    "intent_ir_path",
    "formal_artifact_path",
    "document_id",
    "intent_ir_sha256",
    "intent_file_sha256",
    "formal_artifact_cid",
    "formal_artifact_digest",
    "formal_artifact_sha256",
    "formal_artifact_file_sha256",
    "sample_id",
    "declaration_digest",
    "proof_obligation_count",
    "unsupported_diagnostic_count",
    "formula_count",
    "expected_gate_status",
    "expected_gate_reason_codes",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_hex_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> dict[str, Any]:
    return _load_json(FIXTURE_ROOT / "manifest.json")


def _cases() -> list[dict[str, Any]]:
    cases = _manifest()["cases"]
    assert isinstance(cases, list)
    return cases


def _case_map() -> dict[str, dict[str, Any]]:
    return {str(case["case_id"]): case for case in _cases()}


def _intent_document(case: dict[str, Any]):
    path = FIXTURE_ROOT / str(case["intent_ir_path"])
    return decode_intent_ir(_load_json(path))


def _compile(case: dict[str, Any]) -> FormalizationArtifact:
    compiler = IntentFormalizationCompiler()
    return compiler.compile(_intent_document(case))


# ---------------------------------------------------------------------------
# Manifest inventory and closed gate vocabulary
# ---------------------------------------------------------------------------


def test_manifest_lists_required_strata_and_cases() -> None:
    manifest = _manifest()
    assert manifest["schema_version"] == "intent-admissibility-fixtures/v1"
    assert manifest["interface"] == "IntentAdmissibilityFixtures@1"
    assert manifest["default_profile_id"] == "legal-strict"
    assert is_known_profile(manifest["default_profile_id"])

    formalization = manifest["formalization_compiler"]
    assert formalization["producer_id"] == INTENT_FORMALIZATION_PRODUCER_ID
    assert formalization["producer_version"] == INTENT_FORMALIZATION_COMPILER_VERSION
    assert formalization["domain"] == INTENT_FORMALIZATION_DOMAIN

    case_ids = tuple(manifest["case_ids"])
    assert set(REQUIRED_CASE_IDS) <= set(case_ids)
    assert len(case_ids) == len(set(case_ids))
    assert len(case_ids) >= 4

    cases = _cases()
    assert [case["case_id"] for case in cases] == list(case_ids)
    strata = {case["stratum"] for case in cases}
    assert set(REQUIRED_STRATA) <= strata
    assert set(manifest["expected_strata"]) == strata

    for case in cases:
        for field in REQUIRED_CASE_FIELDS:
            assert field in case, f"{case.get('case_id')}: missing {field}"
        intent_path = FIXTURE_ROOT / str(case["intent_ir_path"])
        artifact_path = FIXTURE_ROOT / str(case["formal_artifact_path"])
        assert intent_path.is_file(), intent_path
        assert artifact_path.is_file(), artifact_path
        assert _sha256_hex_of_file(intent_path) == case["intent_file_sha256"]
        assert _sha256_hex_of_file(artifact_path) == case["formal_artifact_file_sha256"]


@pytest.mark.parametrize("case_id", REQUIRED_CASE_IDS)
def test_manifest_binds_valid_gate_outcomes(case_id: str) -> None:
    case = _case_map()[case_id]
    status = parse_status(case["expected_gate_status"])
    assert isinstance(status, AdmissibilityStatus)
    assert is_known_profile(case["profile_id"])
    parse_profile_id(case["profile_id"])

    reason_codes = case["expected_gate_reason_codes"]
    assert isinstance(reason_codes, list) and reason_codes
    assert len(reason_codes) == len(set(reason_codes))
    for raw in reason_codes:
        code = parse_reason_code(raw)
        assert code.value in reason_code_set()
        # Expected primary disposition must be consistent with default mapping
        # for at least one listed reason (join may combine later).
        if len(reason_codes) == 1:
            assert default_status_for_reason(code) is status


def test_expected_outcomes_cover_allow_legal_reject_security_reject_abstain() -> None:
    cases = _case_map()
    assert cases["benign_skill"]["expected_gate_status"] == "allow"
    assert cases["benign_skill"]["expected_gate_reason_codes"] == [
        "obligations_supported"
    ]
    assert cases["legally_risky_effect"]["expected_gate_status"] == "reject"
    assert cases["legally_risky_effect"]["expected_gate_reason_codes"] == [
        "legal_hard_constraint"
    ]
    assert cases["security_sensitive_resource"]["expected_gate_status"] == "reject"
    assert cases["security_sensitive_resource"]["expected_gate_reason_codes"] == [
        "security_hard_constraint"
    ]
    assert cases["incomplete_unsupported_semantics"]["expected_gate_status"] == (
        "abstain"
    )
    assert set(cases["incomplete_unsupported_semantics"]["expected_gate_reason_codes"]) == {
        "semantics_unsupported",
        "missing_evidence",
    }


# ---------------------------------------------------------------------------
# Intent IR decode + formalization rebuild determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", REQUIRED_CASE_IDS)
def test_intent_ir_decodes_and_matches_pinned_digest(case_id: str) -> None:
    case = _case_map()[case_id]
    document = _intent_document(case)
    validated = validate_intent_ir(document)

    assert validated.document_id == case["document_id"]
    assert intent_ir_sha256(validated) == case["intent_ir_sha256"]
    assert case["intent_ir_sha256"].startswith("sha256:")
    assert case["declaration_digest"] == case["intent_ir_sha256"]

    # Canonical wire form is stable across re-serialization.
    reloaded = decode_intent_ir(json.loads(canonical_intent_ir_json(validated)))
    assert intent_ir_sha256(reloaded) == case["intent_ir_sha256"]
    assert reloaded.document_id == validated.document_id


@pytest.mark.parametrize("case_id", REQUIRED_CASE_IDS)
def test_formalization_rebuild_is_deterministic_and_matches_manifest(
    case_id: str,
) -> None:
    case = _case_map()[case_id]
    compiler = IntentFormalizationCompiler()
    document = _intent_document(case)

    first = compiler.compile(document)
    second = compiler.compile(document)
    via_sample = compiler.compile(
        compiler.adapt_sample(document),
        compiler.default_config(document),
    )

    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.canonical_bytes() == via_sample.canonical_bytes()
    assert first.artifact_id == second.artifact_id == via_sample.artifact_id
    assert first.digest == second.digest == via_sample.digest
    assert first.sha256 == second.sha256 == via_sample.sha256

    assert first.artifact_id == case["formal_artifact_cid"]
    assert first.digest == case["formal_artifact_digest"]
    assert first.sha256 == case["formal_artifact_sha256"]
    assert first.sample_id == case["sample_id"]
    assert first.declaration_digest == case["declaration_digest"]
    assert len(first.proof_obligations) == case["proof_obligation_count"]
    assert len(first.unsupported_diagnostics) == case["unsupported_diagnostic_count"]
    assert len(first.formulas) == case["formula_count"]
    assert first.artifact_id.startswith("b")
    assert first.digest.startswith("sha256:")


@pytest.mark.parametrize("case_id", REQUIRED_CASE_IDS)
def test_frozen_formal_artifact_reloads_with_same_cid(case_id: str) -> None:
    case = _case_map()[case_id]
    frozen_path = FIXTURE_ROOT / str(case["formal_artifact_path"])
    payload = _load_json(frozen_path)
    restored = FormalizationArtifact.from_dict(payload)
    rebuilt = _compile(case)

    assert restored.artifact_id == case["formal_artifact_cid"]
    assert restored.digest == case["formal_artifact_digest"]
    assert restored.sha256 == case["formal_artifact_sha256"]
    assert restored.canonical_bytes() == rebuilt.canonical_bytes()
    assert restored.to_dict() == rebuilt.to_dict()


# ---------------------------------------------------------------------------
# Stratum-specific formalization shape
# ---------------------------------------------------------------------------


def test_benign_skill_has_grounded_obligations_without_unsupported() -> None:
    case = _case_map()["benign_skill"]
    document = _intent_document(case)
    artifact = _compile(case)

    assert document.intent_kind is IntentKind.PROCEDURE
    assert document.actions
    assert artifact.proof_obligations
    assert len(artifact.unsupported_diagnostics) == 0
    assert case["proof_obligation_count"] >= 1
    assert case["unsupported_diagnostic_count"] == 0
    assert case["expected_gate_status"] == "allow"


def test_legally_risky_effect_exports_disclosure_effect() -> None:
    case = _case_map()["legally_risky_effect"]
    document = _intent_document(case)
    artifact = _compile(case)

    effect_texts = {
        statement.normalized_text.lower()
        for statement in document.statements
        if statement.kind.value == "effect"
    }
    assert any("pii" in text or "third party" in text for text in effect_texts)
    assert any(
        "export" in action.verb or "export" in action.action_id
        for action in document.actions
    )
    assert artifact.formulas
    assert case["expected_gate_status"] == "reject"
    assert "legal_hard_constraint" in case["expected_gate_reason_codes"]


def test_security_sensitive_resource_access_is_source_grounded() -> None:
    case = _case_map()["security_sensitive_resource"]
    document = _intent_document(case)
    artifact = _compile(case)

    verbs = {action.verb for action in document.actions}
    objects = {
        ref
        for action in document.actions
        for ref in action.object_refs
    }
    assert any("secret" in verb or "vault" in verb for verb in verbs)
    assert any("secret" in ref or "vault" in ref for ref in objects)
    assert artifact.proof_obligations
    assert all(formula.source_ref_ids for formula in artifact.formulas)
    assert case["expected_gate_status"] == "reject"
    assert "security_hard_constraint" in case["expected_gate_reason_codes"]


def test_incomplete_semantics_surface_unsupported_diagnostics() -> None:
    case = _case_map()["incomplete_unsupported_semantics"]
    document = _intent_document(case)
    artifact = _compile(case)

    assert document.intent_kind is IntentKind.DECLARATIVE
    assert not document.actions
    assert case["proof_obligation_count"] == 0
    assert case["unsupported_diagnostic_count"] >= 1
    assert len(artifact.unsupported_diagnostics) == case["unsupported_diagnostic_count"]
    assert any(formula.opaque for formula in artifact.formulas)
    assert all(
        diagnostic.location.traceable
        for diagnostic in artifact.unsupported_diagnostics
    )
    assert case["expected_gate_status"] == "abstain"


def test_all_cases_rebuild_to_unique_artifact_cids() -> None:
    cids = []
    for case in _cases():
        artifact = _compile(case)
        cids.append(artifact.artifact_id)
        assert artifact.artifact_id == case["formal_artifact_cid"]
    assert len(cids) == len(set(cids))
    assert len(cids) >= 4

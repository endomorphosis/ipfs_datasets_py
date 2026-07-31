"""Unit tests for PLAT2-035 intervention roles, capabilities, and ablations."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.semantic_roundtrip.constructors.causal_autoencoder_guidance import (
    UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER,
)
from benchmarks.semantic_roundtrip.holdout_baseline import (
    PRODUCTION_ARM_ID,
)
from benchmarks.semantic_roundtrip.holdout_interventions import (
    ADVISORY_AE_GUIDANCE,
    DEFAULT_REGISTRY_RELATIVE_PATH,
    HoldoutInterventionError,
    INTERVENTION_DET_FIELD_CONTRADICTORY,
    INTERVENTION_DET_FIELD_MISSING,
    INTERVENTION_DET_MISSING_RULE,
    INTERVENTION_EVIDENCE_ID,
    INTERVENTION_GOAL_ID,
    INTERVENTION_TASK_ID,
    METHOD_AUTOENCODER,
    METHOD_CVC5,
    METHOD_DETERMINISTIC_COMPILER,
    METHOD_HAMMER,
    METHOD_IDS,
    METHOD_LEAN,
    METHOD_LEANSTRAL,
    METHOD_ROLE_BY_ID,
    METHOD_SPACY,
    METHOD_STATUS_NOT_MEASURED,
    METHOD_STATUS_NOT_SELECTED,
    METHOD_STATUS_SEMANTIC_SCORED,
    METHOD_STATUS_TERMINAL_UNSUPPORTED,
    METHOD_STATUSES,
    METHOD_SYMAI,
    NEGATIVE_CONTROL_NO_EDIT,
    PLATEAU2_INTERVENTION_REGISTRY_INTERFACE,
    PLATEAU2_INTERVENTION_REGISTRY_SCHEMA,
    ROLE_CAUSAL_GUIDANCE,
    ROLE_NON_AUTHORITATIVE_DIAGNOSTICS,
    ROLE_ORCHESTRATION_ROUTING,
    ROLE_PRODUCTION_EDIT_TARGET,
    ROLE_PROPOSAL_TEACHER,
    ROLE_STRUCTURAL_GATE,
    SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_INTERFACE,
    assert_health_only_cannot_establish_model_inference,
    build_all_method_records,
    build_intervention_registry,
    build_method_capability_record,
    full_matrix_override_policy,
    health_only_establishes_model_inference,
    load_intervention_registry,
    map_residual_to_intervention,
    method_record_by_id,
    parse_intervention_registry,
    parse_method_capability_record,
    residual_identity_key,
    select_primary_intervention_kind,
    validate_full_matrix_override,
    write_intervention_registry,
)
from benchmarks.semantic_roundtrip.holdout_protocol import (
    BLIND_SEAL_RELATIVE_PATH,
)
from benchmarks.semantic_roundtrip.residual_catalog import (
    DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH,
    POPULATION_KIND_REPAIR_DEVELOPMENT,
    load_repair_dev_residual_catalog,
)


ROOT = Path(__file__).resolve().parents[4]
REGISTRY_PATH = ROOT / DEFAULT_REGISTRY_RELATIVE_PATH
REGISTRY_DOCS = ROOT / "docs/benchmarks/semantic_roundtrip_plateau2_interventions.md"


# ---------------------------------------------------------------------------
# Frozen constants / doctrine
# ---------------------------------------------------------------------------


def test_interfaces_and_method_roles_are_frozen() -> None:
    assert (
        PLATEAU2_INTERVENTION_REGISTRY_INTERFACE
        == "Plateau2InterventionRegistry@1"
    )
    assert (
        PLATEAU2_INTERVENTION_REGISTRY_SCHEMA
        == "ipfs-datasets.semantic-roundtrip-plateau2-intervention-registry.v1"
    )
    assert (
        SEMANTIC_ROUNDTRIP_CAPABILITY_RECORD_INTERFACE
        == "SemanticRoundtripCapabilityRecord@1"
    )
    assert INTERVENTION_TASK_ID == "PLAT2-035"
    assert INTERVENTION_GOAL_ID == "PLAT2-G035"
    assert INTERVENTION_EVIDENCE_ID == "PLAT2EV035INT"
    assert METHOD_ROLE_BY_ID[METHOD_DETERMINISTIC_COMPILER] == (
        ROLE_PRODUCTION_EDIT_TARGET
    )
    assert METHOD_ROLE_BY_ID[METHOD_AUTOENCODER] == ROLE_CAUSAL_GUIDANCE
    assert METHOD_ROLE_BY_ID[METHOD_SPACY] == ROLE_NON_AUTHORITATIVE_DIAGNOSTICS
    assert METHOD_ROLE_BY_ID[METHOD_SYMAI] == ROLE_ORCHESTRATION_ROUTING
    assert METHOD_ROLE_BY_ID[METHOD_LEANSTRAL] == ROLE_PROPOSAL_TEACHER
    assert METHOD_ROLE_BY_ID[METHOD_HAMMER] == ROLE_STRUCTURAL_GATE
    assert METHOD_ROLE_BY_ID[METHOD_CVC5] == ROLE_STRUCTURAL_GATE
    assert METHOD_ROLE_BY_ID[METHOD_LEAN] == ROLE_STRUCTURAL_GATE
    assert METHOD_STATUSES == {
        "semantic_scored",
        "not_measured",
        "runtime_failed",
        "terminal_unsupported",
        "not_selected",
    }
    assert tuple(METHOD_IDS) == (
        METHOD_DETERMINISTIC_COMPILER,
        METHOD_AUTOENCODER,
        METHOD_SPACY,
        METHOD_SYMAI,
        METHOD_LEANSTRAL,
        METHOD_HAMMER,
        METHOD_CVC5,
        METHOD_LEAN,
    )


def test_health_only_cannot_establish_model_inference() -> None:
    assert (
        health_only_establishes_model_inference(
            health_only=True, model_inference_performed=True
        )
        is False
    )
    assert (
        health_only_establishes_model_inference(
            health_only=False, model_inference_performed=True
        )
        is True
    )
    assert (
        health_only_establishes_model_inference(
            health_only=False, model_inference_performed=False
        )
        is False
    )
    with pytest.raises(
        HoldoutInterventionError, match="health-only probes cannot establish"
    ):
        assert_health_only_cannot_establish_model_inference(
            {
                "health_only": True,
                "model_inference_established": True,
                "checks": {"health_only": True, "model_inference_performed": True},
            }
        )


# ---------------------------------------------------------------------------
# Method capability records
# ---------------------------------------------------------------------------


def test_build_method_records_classify_roles_and_statuses() -> None:
    records = build_all_method_records(repo_root=ROOT)
    assert len(records) == len(METHOD_IDS)
    by_id = {item["method_id"]: item for item in records}

    det = by_id[METHOD_DETERMINISTIC_COMPILER]
    assert det["role"] == ROLE_PRODUCTION_EDIT_TARGET
    assert det["semantic_authority"] is True
    assert det["is_production_edit_target"] is True
    assert det["status"] == METHOD_STATUS_SEMANTIC_SCORED
    assert det["identity"]["arm_id"] == PRODUCTION_ARM_ID
    assert det["identity"]["constructor_identity"]
    assert det["identity"]["realizer_identity"]

    ae = by_id[METHOD_AUTOENCODER]
    assert ae["role"] == ROLE_CAUSAL_GUIDANCE
    assert ae["semantic_authority"] is False
    assert ae["status"] in {
        METHOD_STATUS_TERMINAL_UNSUPPORTED,
        METHOD_STATUS_NOT_MEASURED,
    }
    assert ae["status"] != METHOD_STATUS_SEMANTIC_SCORED
    assert UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER in str(
        ae["status_reason"]
    ) or "terminal_unsupported" in str(ae["status_reason"])

    spacy = by_id[METHOD_SPACY]
    assert spacy["role"] == ROLE_NON_AUTHORITATIVE_DIAGNOSTICS
    assert spacy["semantic_authority"] is False
    assert spacy["status"] in METHOD_STATUSES
    assert spacy["identity"]["model"]
    assert spacy["identity"]["version"]

    symai = by_id[METHOD_SYMAI]
    assert symai["role"] == ROLE_ORCHESTRATION_ROUTING
    assert symai["semantic_authority"] is False
    assert symai["identity"]["route"]
    assert symai["identity"].get("proof_credit") is False

    leanstral = by_id[METHOD_LEANSTRAL]
    assert leanstral["role"] == ROLE_PROPOSAL_TEACHER
    assert leanstral["semantic_authority"] is False
    assert leanstral["identity"]["model"]
    assert leanstral["identity"]["route"]
    # Health-only cannot establish inference; when smoke is real, flag is set.
    if leanstral.get("health_only") is True:
        assert leanstral["model_inference_established"] is not True
    if leanstral["status"] == METHOD_STATUS_NOT_SELECTED:
        assert leanstral["model_inference_established"] is True

    for gate_id in (METHOD_HAMMER, METHOD_CVC5, METHOD_LEAN):
        gate = by_id[gate_id]
        assert gate["role"] == ROLE_STRUCTURAL_GATE
        assert gate["semantic_authority"] is False
        assert gate["may_substitute_for_e2e"] is False
        assert gate["status"] in METHOD_STATUSES
        assert gate["identity"]["toolchain"] or gate["identity"].get("version")

    for item in records:
        parse_method_capability_record(item)


def test_method_record_requires_exact_identity_fields() -> None:
    det = build_method_capability_record(
        METHOD_DETERMINISTIC_COMPILER, repo_root=ROOT
    )
    assert det["identity"]["version"]
    assert det["identity"]["toolchain"]
    assert det["evidence"]["kind"] == "plat_baseline"

    spacy = build_method_capability_record(METHOD_SPACY, repo_root=ROOT)
    assert spacy["identity"]["model"]
    assert spacy["identity"]["version"]
    assert spacy["capability_inventory_id"] == "spacy_pipeline"


def test_parse_method_record_rejects_semantic_authority_for_advisors() -> None:
    ae = build_method_capability_record(METHOD_AUTOENCODER, repo_root=ROOT)
    tampered = copy.deepcopy(ae)
    tampered["semantic_authority"] = True
    with pytest.raises(HoldoutInterventionError, match="semantic_authority"):
        parse_method_capability_record(tampered)


def test_parse_method_record_rejects_health_only_inference_claim() -> None:
    leanstral = build_method_capability_record(
        METHOD_LEANSTRAL, repo_root=ROOT
    )
    tampered = copy.deepcopy(leanstral)
    tampered["health_only"] = True
    tampered["model_inference_established"] = True
    tampered["checks"] = {
        **dict(tampered.get("checks") or {}),
        "health_only": True,
        "model_inference_performed": True,
    }
    with pytest.raises(HoldoutInterventionError, match="health-only"):
        parse_method_capability_record(tampered)


# ---------------------------------------------------------------------------
# Residual → intervention mapping
# ---------------------------------------------------------------------------


def test_select_primary_intervention_kind_is_preregistered() -> None:
    assert (
        select_primary_intervention_kind(
            {
                "case_id": "c",
                "field_path": "rules[1]",
                "residual_kind": "missing_rule",
                "suggested_trigger_kind": "missing",
            }
        )
        == INTERVENTION_DET_MISSING_RULE
    )
    assert (
        select_primary_intervention_kind(
            {
                "case_id": "c",
                "field_path": "rules[1].conditions",
                "residual_kind": "field_mismatch",
                "suggested_trigger_kind": "missing",
            }
        )
        == INTERVENTION_DET_FIELD_MISSING
    )
    assert (
        select_primary_intervention_kind(
            {
                "case_id": "c",
                "field_path": "rules[1].object",
                "residual_kind": "field_mismatch",
                "suggested_trigger_kind": "contradictory",
            }
        )
        == INTERVENTION_DET_FIELD_CONTRADICTORY
    )


def test_each_repair_dev_residual_maps_to_intervention_and_ablations() -> None:
    catalog = load_repair_dev_residual_catalog(
        ROOT / DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH, repo_root=ROOT
    )
    residuals = list(catalog["residuals"])
    assert residuals
    methods = build_all_method_records(repo_root=ROOT)
    prior: list[str] = []
    for wave_index, residual in enumerate(
        sorted(
            residuals,
            key=lambda row: (
                str(row["case_id"]),
                str(row["field_path"]),
                str(row["residual_kind"]),
            ),
        )
    ):
        mapping = map_residual_to_intervention(
            residual,
            method_records=methods,
            wave_index=wave_index,
            prior_mapping_ids=prior,
        )
        assert mapping["population_kind"] == POPULATION_KIND_REPAIR_DEVELOPMENT
        assert mapping["blind_data_used"] is False
        assert mapping["outcome_dependent_selection"] is False
        assert mapping["primary_intervention"]["method_id"] == (
            METHOD_DETERMINISTIC_COMPILER
        )
        assert mapping["primary_intervention"]["edit_target"] is True
        assert mapping["primary_intervention"]["semantic_authority"] is True
        control_ids = {
            item["control_id"] for item in mapping["negative_controls"]
        }
        assert NEGATIVE_CONTROL_NO_EDIT in control_ids
        assert mapping["per_wave_ablation"]["units"]
        assert mapping["cumulative_ablation"]["included_mapping_ids"][-1] == (
            mapping["mapping_id"]
        )
        # AE advisory is never eligible without scored_supported adapter.
        ae_adv = [
            item
            for item in mapping["optional_advisories"]
            if item["advisory_id"] == ADVISORY_AE_GUIDANCE
        ]
        assert ae_adv
        assert ae_adv[0]["eligible"] is False
        # Structural gates declared, non-authoritative.
        gate_ids = {item["method_id"] for item in mapping["structural_gates"]}
        assert {METHOD_HAMMER, METHOD_CVC5, METHOD_LEAN} <= gate_ids
        for gate in mapping["structural_gates"]:
            assert gate["semantic_authority"] is False
        prior.append(mapping["mapping_id"])


# ---------------------------------------------------------------------------
# Registry freeze
# ---------------------------------------------------------------------------


def test_build_and_parse_intervention_registry() -> None:
    registry = build_intervention_registry(ROOT)
    parsed = parse_intervention_registry(registry)
    assert parsed["interface"] == PLATEAU2_INTERVENTION_REGISTRY_INTERFACE
    assert parsed["schema_version"] == PLATEAU2_INTERVENTION_REGISTRY_SCHEMA
    assert parsed["task_id"] == INTERVENTION_TASK_ID
    assert parsed["population_kind"] == POPULATION_KIND_REPAIR_DEVELOPMENT
    assert parsed["blind_holdout"]["access_receipt_count"] == 0
    assert parsed["blind_holdout"]["blind_seal_unopened"] is True
    assert parsed["selection_policy"]["blind_data_permitted"] is False
    assert (
        parsed["selection_policy"]["outcome_dependent_selection_permitted"]
        is False
    )
    assert parsed["selection_policy"]["full_matrix_requires_override"] is True
    assert (
        parsed["full_matrix_policy"]["full_matrix_rerun_default_allowed"]
        is False
    )
    assert (
        parsed["full_matrix_policy"][
            "requires_explicit_evidence_backed_override"
        ]
        is True
    )

    catalog = load_repair_dev_residual_catalog(
        ROOT / DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH, repo_root=ROOT
    )
    assert len(parsed["residual_mappings"]) == len(catalog["residuals"])
    assert parsed["catalog_cid"] == catalog["catalog_cid"]
    assert parsed["registry_cid"].startswith("baguqeera")

    # CID identity stability.
    identity = {
        key: value
        for key, value in registry.items()
        if key
        not in {
            "registry_cid",
            "registry_cid_codec",
            "registry_cid_scope",
        }
    }
    assert registry["registry_cid"] == cid_for_dag_json(identity)


def test_registry_doctrine_matches_capability_policy() -> None:
    registry = build_intervention_registry(ROOT)
    roles = registry["doctrine"]
    assert roles["deterministic_compiler_ir_decompiler"] == (
        ROLE_PRODUCTION_EDIT_TARGET
    )
    assert roles["autoencoder"] == ROLE_CAUSAL_GUIDANCE
    assert roles["spacy"] == ROLE_NON_AUTHORITATIVE_DIAGNOSTICS
    assert roles["symai"] == ROLE_ORCHESTRATION_ROUTING
    assert roles["leanstral"] == ROLE_PROPOSAL_TEACHER
    assert roles["hammer_cvc5_lean"] == ROLE_STRUCTURAL_GATE

    det = method_record_by_id(registry, METHOD_DETERMINISTIC_COMPILER)
    assert det["status"] == METHOD_STATUS_SEMANTIC_SCORED
    ae = method_record_by_id(registry, METHOD_AUTOENCODER)
    assert ae["status"] != METHOD_STATUS_SEMANTIC_SCORED


def test_registry_rejects_blind_access_receipts() -> None:
    registry = build_intervention_registry(ROOT)
    tampered = copy.deepcopy(registry)
    tampered["blind_holdout"]["access_receipt_count"] = 1
    # Rebind CID so only semantic check fails.
    identity = {
        key: value
        for key, value in tampered.items()
        if key
        not in {
            "registry_cid",
            "registry_cid_codec",
            "registry_cid_scope",
        }
    }
    tampered["registry_cid"] = cid_for_dag_json(identity)
    with pytest.raises(HoldoutInterventionError, match="access_receipt_count"):
        parse_intervention_registry(tampered)


def test_registry_rejects_outcome_dependent_selection_flag() -> None:
    registry = build_intervention_registry(ROOT)
    tampered = copy.deepcopy(registry)
    tampered["selection_policy"]["outcome_dependent_selection_permitted"] = True
    identity = {
        key: value
        for key, value in tampered.items()
        if key
        not in {
            "registry_cid",
            "registry_cid_codec",
            "registry_cid_scope",
        }
    }
    tampered["registry_cid"] = cid_for_dag_json(identity)
    with pytest.raises(
        HoldoutInterventionError, match="outcome-dependent selection"
    ):
        parse_intervention_registry(tampered)


def test_registry_rejects_non_det_edit_target() -> None:
    registry = build_intervention_registry(ROOT)
    tampered = copy.deepcopy(registry)
    primary = tampered["residual_mappings"][0]["primary_intervention"]
    primary["method_id"] = METHOD_SPACY
    primary["edit_target"] = True
    identity = {
        key: value
        for key, value in tampered.items()
        if key
        not in {
            "registry_cid",
            "registry_cid_codec",
            "registry_cid_scope",
        }
    }
    tampered["registry_cid"] = cid_for_dag_json(identity)
    with pytest.raises(
        HoldoutInterventionError, match="deterministic compiler"
    ):
        parse_intervention_registry(tampered)


def test_full_matrix_override_requires_evidence() -> None:
    registry = build_intervention_registry(ROOT)
    policy = full_matrix_override_policy()
    assert policy["full_matrix_rerun_default_allowed"] is False
    assert policy["requires_explicit_evidence_backed_override"] is True

    mapping_id = registry["residual_mappings"][0]["mapping_id"]
    evidence_cid = cid_for_dag_json(
        {"kind": "full_matrix_override_evidence", "note": "test"}
    )
    override = {
        "override_id": "test-override-1",
        "evidence_cid": evidence_cid,
        "justification": "attribution ambiguity on shared hotspot",
        "authorizer": "plat2-055-candidate-freeze",
        "residual_mapping_ids_in_scope": [mapping_id],
        "experiment_id": registry["experiment_id"],
        "registry_cid": registry["registry_cid"],
        "outcome_dependent_selection": False,
        "blind_data_used": False,
    }
    validated = validate_full_matrix_override(override, registry=registry)
    assert validated["override_id"] == "test-override-1"

    bad = copy.deepcopy(override)
    del bad["evidence_cid"]
    with pytest.raises(HoldoutInterventionError, match="evidence_cid"):
        validate_full_matrix_override(bad, registry=registry)

    outcome_dep = copy.deepcopy(override)
    outcome_dep["outcome_dependent_selection"] = True
    with pytest.raises(
        HoldoutInterventionError, match="outcome-dependent selection"
    ):
        validate_full_matrix_override(outcome_dep, registry=registry)


def test_checked_in_registry_artifact_parses() -> None:
    assert REGISTRY_PATH.is_file(), (
        "repair_dev_intervention_registry.json must be written by PLAT2-035"
    )
    loaded = load_intervention_registry(REGISTRY_PATH, repo_root=ROOT)
    assert loaded["interface"] == PLATEAU2_INTERVENTION_REGISTRY_INTERFACE
    assert len(loaded["method_records"]) == len(METHOD_IDS)
    assert loaded["residual_mappings"]
    # Fresh rebuild must match checked-in CID (freeze stability).
    rebuilt = build_intervention_registry(ROOT)
    assert rebuilt["registry_cid"] == loaded["registry_cid"]
    assert rebuilt["catalog_cid"] == loaded["catalog_cid"]


def test_write_intervention_registry_round_trip(tmp_path: Path) -> None:
    registry = build_intervention_registry(ROOT)
    out = tmp_path / "repair_dev_intervention_registry.json"
    written = write_intervention_registry(
        out, registry=registry, repo_root=ROOT
    )
    assert out.is_file()
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded["registry_cid"] == written["registry_cid"]
    parse_intervention_registry(reloaded)


def test_docs_artifact_exists_and_covers_doctrine() -> None:
    assert REGISTRY_DOCS.is_file()
    text = REGISTRY_DOCS.read_text(encoding="utf-8")
    for needle in (
        "PLAT2-035",
        "production_edit_target",
        "scored_supported",
        "non_authoritative_diagnostics",
        "orchestration",
        "proposal_teacher",
        "structural_gate",
        "health-only",
        "full matrix",
        "negative control",
        "ablation",
        "blind",
    ):
        assert needle.lower() in text.lower(), f"docs missing {needle!r}"


def test_blind_seal_remains_unopened_in_registry() -> None:
    registry = build_intervention_registry(ROOT)
    assert registry["blind_holdout"]["status"] == "sealed_unopened"
    seal_path = ROOT / BLIND_SEAL_RELATIVE_PATH
    raw = json.loads(seal_path.read_text(encoding="utf-8"))
    for forbidden in (
        "case_ids",
        "source_text",
        "gold_ir",
        "labels",
        "per_case_digests",
        "semantic_hints",
    ):
        assert forbidden not in raw


def test_residual_identity_key_is_stable() -> None:
    residual = {
        "case_id": "legal_doc_2",
        "field_path": "rules[2]",
        "residual_kind": "missing_rule",
    }
    assert residual_identity_key(residual) == (
        "legal_doc_2::rules[2]::missing_rule"
    )

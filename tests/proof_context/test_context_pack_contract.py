"""ASEH-030: closed DatasetsContextPackAuthority contract vectors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.audit_contracts import (
    RouteTier,
)
from ipfs_datasets_py.proof_context.context_pack import (
    AUTHORITY,
    CONSUMER_INTERFACE,
    CONTEXT_PACK_SCHEMA,
    DatasetsContextPackAuthority,
    ENVELOPE_FIELDS,
    INTERFACE,
    SCHEMA_PATH,
    ContextPackConstructionError,
    build_context_pack,
    get_authority,
    load_context_pack_schema,
    validate_context_pack_envelope,
)
from ipfs_datasets_py.proof_context.contracts import StaleContextError
import ipfs_datasets_py.proof_context.context_pack as context_pack_mod


TREE_OID = "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f"
OTHER_TREE = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _kwargs(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "repository_state_cid": _cid("repo-state"),
        "task_id": "ASEH-030",
        "target_source_cid": _cid("target"),
        "surrounding_source_cid": _cid("surround"),
        "test_source_cid": _cid("test"),
        "scanned_tree_oid": TREE_OID,
        "source_tree_oid": TREE_OID,
        "capsule_cids": (_cid("capsule"),),
    }
    fields.update(overrides)
    return fields


def _complete_scope() -> dict[str, object]:
    return {
        "affected_files": ["target.py"],
        "affected_symbols": ["target"],
        "dependency_cone": ["surrounding"],
        "reverse_dependencies": ["test"],
        "explicitly_excluded_paths": ["vendor/"],
        "changed_interfaces_and_schemas": ["ContextPack@1"],
        "semantic_diff_summary": "bind route tier into identity",
    }


def test_authority_is_datasets_type_not_a_competitor() -> None:
    authority = get_authority()
    assert isinstance(authority, DatasetsContextPackAuthority)
    assert authority.interface == INTERFACE
    assert INTERFACE == "DatasetsContextPackAuthority@0.1"
    assert authority.consumer_interface == CONSUMER_INTERFACE == "ContextPack@1"
    assert not hasattr(context_pack_mod, "SupervisorContextPack")
    assert "SupervisorContextPack" not in INTERFACE


def test_canonical_bytes_and_cid_round_trip() -> None:
    record = build_context_pack(**_kwargs())
    payload = record.canonical_payload()
    assert record.pack_cid == cid_for_structured(payload)
    assert record.canonical_bytes() == canonical_dag_json_bytes(payload)
    assert decode_and_recompute_structured(record.pack_cid, payload) == record.pack_cid
    assert record.verify_identity() == record.pack_cid
    envelope = record.to_dict()
    assert envelope["pack_cid"] == record.pack_cid
    assert set(envelope) == set(ENVELOPE_FIELDS)
    assert validate_context_pack_envelope(envelope)["pack_cid"] == record.pack_cid


def test_identical_inputs_yield_identical_pack_cid() -> None:
    authority = DatasetsContextPackAuthority()
    a = authority.build(**_kwargs())
    b = build_context_pack(**_kwargs())
    assert a.pack_cid == b.pack_cid
    assert a.producer == AUTHORITY
    assert a.schema == CONTEXT_PACK_SCHEMA
    assert a.view.context_pack_cid == a.pack_cid
    assert a.view.route_tier == RouteTier.SMALL.value
    assert a.required_source_cids["target_source"] == _cid("target")


def test_route_tier_and_view_changing_inputs_bind_identity() -> None:
    baseline = build_context_pack(**_kwargs()).pack_cid
    variants: list[dict[str, object]] = [
        {"route_tier": RouteTier.DETERMINISTIC},
        {"route_tier": "frontier"},
        {"task_class": "cross_repo"},
        {"risk_class": "high"},
        {"task_id": "ASEH-030-b"},
        {"repository_state_cid": _cid("other-repo")},
        {"target_source_cid": _cid("other-target")},
        {"surrounding_source_cid": _cid("other-surround")},
        {"test_source_cid": _cid("other-test")},
        {"capsule_cids": (_cid("other-capsule"),)},
        {"scanned_tree_oid": OTHER_TREE, "source_tree_oid": OTHER_TREE},
        {"source_tree_oid": OTHER_TREE},
        {"opaque": True},
        {"objective_revision": "rev-2"},
        {"creation_time": "2026-08-30T00:00:00Z"},
        {"scope": _complete_scope()},
        {"contracts": {
            "applicable_api_contracts": ["ContextPack@1"],
            "assumptions_and_guarantees": ["datasets-owned"],
            "invariants": ["closed-schema"],
            "security_constraints": ["no-private-fields"],
            "side_effect_classes": ["none"],
            "allowed_mutation_scope": ["declared-outputs"],
        }},
        {"validation": {
            "known_tests": ["test_context_pack_contract.py"],
            "selected_tests": ["test_route_tier_and_view_changing_inputs_bind_identity"],
            "type_static_schema_checks": ["context_pack.schema.json"],
            "proof_obligations": ["cid-round-trip"],
            "required_full_suite_conditions": ["promotion"],
            "current_authoritative_receipts": [_cid("receipt")],
        }},
        {"history": {
            "relevant_prior_failures": ["stale-pack"],
            "relevant_counterexamples": [_cid("cex")],
            "prior_accepted_patches": [_cid("patch")],
            "stale_or_invalidated_receipts": [_cid("old-receipt")],
            "retry_and_rescue_history": ["retry-1"],
        }},
        {"questions": {
            "named_unresolved_questions": ["missing-obligation"],
            "missing_evidence": ["proof-cid"],
            "completeness_witness": None,
            "expansion_references": ["obligation:proof"],
        }},
        {"budgets": {
            "maximum_bytes": 4096,
            "maximum_tokens": 800,
            "maximum_retrieval_operations": 4,
            "maximum_model_class": "small",
            "maximum_wall_time": 30,
            "validation_reserve_models_cannot_consume": True,
        }},
        {"freshness_bindings": {
            "file_and_symbol_identities": ["target.py:target"],
            "schema_identities": [CONTEXT_PACK_SCHEMA],
            "toolchain_identities": ["python3.12"],
            "environment_requirements": ["hermetic"],
            "reusable_until_conditions": ["tree-unchanged"],
        }},
        {"invalidation": {
            "invalidation_triggers": ["tree-change"],
            "reusable_until_conditions": ["objective-unchanged"],
        }},
        {
            "parent_context_pack_cid": _cid("parent-pack"),
            "delta_cid": _cid("delta"),
            "incremental": True,
        },
        {"execution_mode": "replay"},
    ]
    seen = {baseline}
    for variant in variants:
        pack_cid = build_context_pack(**_kwargs(**variant)).pack_cid
        assert pack_cid not in seen
        seen.add(pack_cid)
    assert build_context_pack(**_kwargs(route_tier="small")).pack_cid == baseline


def test_fixture_live_and_synthetic_real_identities_remain_distinct() -> None:
    live = build_context_pack(**_kwargs())
    fixture = build_context_pack(
        **_kwargs(
            identity_kind="fixture",
            evidence_kind="fixture",
            execution_mode="simulated",
        )
    )
    synthetic = build_context_pack(
        **_kwargs(
            identity_kind="synthetic",
            evidence_kind="synthetic",
            execution_mode="simulated",
        )
    )
    cids = {live.pack_cid, fixture.pack_cid, synthetic.pack_cid}
    assert len(cids) == 3
    assert live.canonical_payload()["identity_kind"] == "live"
    assert live.canonical_payload()["evidence_kind"] == "real"
    assert fixture.canonical_payload()["execution_mode"] == "simulated"
    assert synthetic.canonical_payload()["identity_kind"] == "synthetic"


def test_fixture_as_live_fails_closed() -> None:
    with pytest.raises(ContextPackConstructionError, match="fixture/live"):
        build_context_pack(
            **_kwargs(
                identity_kind="fixture",
                evidence_kind="fixture",
                execution_mode="live",
            )
        )
    with pytest.raises(ContextPackConstructionError, match="fixture/live"):
        build_context_pack(
            **_kwargs(
                identity_kind="live",
                evidence_kind="fixture",
                execution_mode="live",
            )
        )


def test_synthetic_identity_cannot_be_accepted_as_complete() -> None:
    with pytest.raises(ContextPackConstructionError, match="synthetic identity"):
        build_context_pack(
            **_kwargs(
                identity_kind="synthetic",
                evidence_kind="synthetic",
                execution_mode="simulated",
                questions={
                    "named_unresolved_questions": [],
                    "missing_evidence": [],
                    "completeness_witness": _cid("complete"),
                    "expansion_references": [],
                },
            )
        )
    with pytest.raises(ContextPackConstructionError, match="synthetic/real"):
        build_context_pack(
            **_kwargs(
                identity_kind="synthetic",
                evidence_kind="real",
                execution_mode="live",
            )
        )


def test_omitted_view_input_fails_closed() -> None:
    incomplete = dict(_complete_scope())
    incomplete.pop("affected_symbols")
    with pytest.raises(ContextPackConstructionError, match="omitted view input"):
        build_context_pack(**_kwargs(scope=incomplete))
    with pytest.raises(ContextPackConstructionError, match="omitted view input"):
        build_context_pack(**_kwargs(parent={}))


def test_unknown_field_fails_closed() -> None:
    extra = dict(_complete_scope())
    extra["unexpected"] = "nope"
    with pytest.raises(ContextPackConstructionError, match="unknown field"):
        build_context_pack(**_kwargs(scope=extra))
    record = build_context_pack(**_kwargs())
    envelope = record.to_dict()
    envelope["extra"] = True
    with pytest.raises(ContextPackConstructionError, match="unknown field"):
        validate_context_pack_envelope(envelope)


def test_weak_freshness_and_stale_fail_closed() -> None:
    with pytest.raises(StaleContextError):
        build_context_pack(**_kwargs(freshness="stale"))
    with pytest.raises(ContextPackConstructionError, match="weak freshness"):
        build_context_pack(**_kwargs(freshness="assumed_fresh"))
    with pytest.raises(ContextPackConstructionError, match="weak freshness"):
        build_context_pack(**_kwargs(freshness="probably_fresh"))


def test_ownership_drift_fails_closed() -> None:
    record = build_context_pack(**_kwargs())
    identity = dict(record.canonical_payload()["identity"])
    identity["schema_and_interface_version"] = "SupervisorContextPack@1"
    identity["builder_identity"] = "SupervisorContextPack@1"
    with pytest.raises(ContextPackConstructionError, match="ownership drift"):
        build_context_pack(**_kwargs(identity=identity))
    envelope = record.to_dict()
    envelope["interface"] = "SupervisorContextPack@1"
    with pytest.raises(ContextPackConstructionError, match="ownership drift"):
        validate_context_pack_envelope(envelope)


def test_closed_schema_accepts_envelope_and_rejects_unknowns() -> None:
    schema = load_context_pack_schema()
    record = build_context_pack(**_kwargs(scope=_complete_scope()))
    envelope = record.to_dict()
    validate_context_pack_envelope(envelope)
    assert SCHEMA_PATH.is_file()
    assert SCHEMA_PATH.name == "context_pack.schema.json"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["interface"]["const"] == INTERFACE
    assert schema["properties"]["schema"]["const"] == CONTEXT_PACK_SCHEMA
    try:
        import jsonschema
    except ImportError:
        return
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    validator.validate(envelope)
    bad = dict(envelope)
    bad["unexpected"] = "field"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(bad)
    floaty = dict(envelope)
    floaty["budgets"] = dict(envelope["budgets"])
    floaty["budgets"]["maximum_tokens"] = 1.25
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(floaty)


def test_schema_file_is_packaged_beside_module() -> None:
    module_path = Path(context_pack_mod.__file__).resolve().parent
    assert SCHEMA_PATH.parent == module_path / "schemas"
    document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert document["required"] == list(ENVELOPE_FIELDS)


def test_unavailable_budget_is_null_not_zero() -> None:
    record = build_context_pack(**_kwargs())
    budgets = record.canonical_payload()["budgets"]
    assert budgets["maximum_tokens"] is None
    assert budgets["maximum_bytes"] is None
    bounded = build_context_pack(
        **_kwargs(
            budgets={
                "maximum_bytes": 0,
                "maximum_tokens": 0,
                "maximum_retrieval_operations": 0,
                "maximum_model_class": None,
                "maximum_wall_time": 0,
                "validation_reserve_models_cannot_consume": True,
            }
        )
    )
    assert bounded.canonical_payload()["budgets"]["maximum_tokens"] == 0
    assert bounded.pack_cid != record.pack_cid
    with pytest.raises(ContextPackConstructionError, match="validation reserve"):
        build_context_pack(
            **_kwargs(
                budgets={
                    "maximum_bytes": None,
                    "maximum_tokens": None,
                    "maximum_retrieval_operations": None,
                    "maximum_model_class": None,
                    "maximum_wall_time": None,
                    "validation_reserve_models_cannot_consume": False,
                }
            )
        )

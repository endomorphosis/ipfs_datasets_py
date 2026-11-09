"""Combined-use signatures cover a new assumption, never legal authority."""

from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_graph_review as signatures
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


def fixture_module(filename, name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_USE = fixture_module(
    "test_corpus_definition_use_v2.py", "authored_use_for_combined_review"
)
_REVIEW = fixture_module(
    "test_corpus_definition_review_v2.py", "synthetic_keys_for_combined_review"
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False).encode()


def reseal(record):
    return contracts.seal_record(
        {k: v for k, v in record.items() if k not in {"record_cid", "cid_scope"}}
    )


def component(family="fol"):
    from ipfs_datasets_py.logic.autoformal import corpus_definition_use_v2 as use

    case = _USE.fixture(use, family)
    request_raw, kwargs = _USE.arguments(case)
    record = use.prepare_definition_use_v2(request_raw, **kwargs)
    raw = canonical_dag_json_bytes(record)
    pin = {
        "component_sha256": sha(raw),
        "component_cid": record["record_cid"],
        "graph_cid": record["graph"]["record_cid"],
        "joint_ast_sha256": sha(
            canonical_dag_json_bytes(record["joint_native"]["native_ast"])
        ),
    }
    return {
        "record": record,
        "case": case,
        "component_raw": raw,
        "expected_component_pin": pin,
        "use_inputs": {"request_raw": request_raw, **kwargs},
    }


def arguments(data):
    return {
        key: data[key]
        for key in ("component_raw", "expected_component_pin", "use_inputs")
    }


def materialize(owner, data):
    prep = owner.prepare_definition_use_review_evidence_v2(**arguments(data))
    manifest = dependencies.build_dependency_manifest(
        prep["artifacts"],
        prep["edges"],
        expected_artifact_ids=prep["expected_artifact_ids"],
    )
    subject = owner.build_definition_use_review_subject_v2(
        prep,
        manifest,
        **arguments(data),
        expected_manifest_sha256=manifest["manifest_sha256"],
        required_dependency_ids=prep["required_dependency_ids"],
    )
    return {
        "component": data,
        "arguments": arguments(data),
        "preparation": prep,
        "manifest": manifest,
        "subject": subject,
    }


@pytest.fixture(scope="module")
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_definition_use_review_v2

    return corpus_definition_use_review_v2


@pytest.fixture(scope="module")
def base_component():
    return component()


@pytest.fixture
def case(base_component):
    return deepcopy(base_component)


@pytest.fixture(scope="module")
def base_materialized(owner, base_component):
    return materialize(owner, base_component)


@pytest.fixture
def signed(owner, base_materialized):
    # Reuse the existing synthetic legal/formal credential constructor; the new
    # owner supplies its distinct claim/action/audience and exact combined scope.
    return _REVIEW.signed.__wrapped__(owner, base_materialized)


def assessment_arguments(data):
    return _REVIEW.assessment_arguments(data)


def assess(owner, data):
    args, kwargs = assessment_arguments(data)
    return owner.assess_definition_use_reviews_v2(*args, **kwargs)


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_new_subject_covers_joint_ast_all_contexts_and_original_dependency_closure(
    owner, family
):
    data = component(family)
    original = deepcopy(data["record"])
    prepared = materialize(owner, data)
    prep, subject = prepared["preparation"], prepared["subject"]
    assert data["record"] == original
    assert prep["native_ast"] == original["joint_native"]["native_ast"]
    assert prep["ast_sha256"] == data["expected_component_pin"]["joint_ast_sha256"]
    assert prep["alias_ast_sha256"] == sha(
        canonical_dag_json_bytes(original["alias_native"]["native_ast"])
    )
    assert prep["contexts"] == original["context_population"]
    assert (
        prep["context_slot_ids"]
        == subject["context_slot_ids"]
        == original["context_slot_ids"]
    )
    assert len(prep["context_slot_ids"]) == len(set(prep["context_slot_ids"])) == 78
    assert prep["binding_record"] == original["binding_record"]
    assert prep["alias_record"] == original["alias_record"]
    assert subject["scope_id"] == prep["scope_binding"]["record_cid"]
    original_scopes = [
        data["case"][key]["candidate"]["scope_record"]["record_cid"]
        for key in ("donor", "consumer")
    ]
    assert subject["scope_id"] not in original_scopes
    for scope in original_scopes:
        assert scope in wire(prep["scope_binding"]).decode()
    assert (
        original["binding_record"]["record_cid"] in wire(prep["scope_binding"]).decode()
    )
    assert prep["scope_id"] == subject["scope_id"]
    assert subject["native_binding"] == prep
    assert subject["required_dependency_ids"] == prep["required_dependency_ids"]
    artifact_count = len(original["dependency_manifest"]["artifacts"])
    edge_count = len(original["dependency_manifest"]["edges"])
    assert (
        prep["artifacts"][:artifact_count]
        == original["dependency_manifest"]["artifacts"]
    )
    assert prep["edges"][:edge_count] == original["dependency_manifest"]["edges"]
    assert len(prep["artifacts"]) == artifact_count + 4
    assert len(prep["edges"]) == edge_count + 4
    assert prep["component_canonical_sha256"] == sha(canonical_dag_json_bytes(original))
    assert (
        prep["policy_binding"]["review_contract"]
        == prep["review_contract"]
        == owner.REVIEW_CONTRACT
    )
    assert prep["review_contract"]["alias_assumed_not_proved"] is True
    assert (
        prep["review_contract"]["original_endpoint_reviews_authorize_combination"]
        is False
    )
    assert all(prep[key] is False for key in owner.FALSE_FLAGS)
    owner.validate_definition_use_review_evidence_v2(prep, **arguments(data))


def test_new_combined_domain_authenticates_synthetic_bytes_without_admission(
    owner, signed
):
    result = assess(owner, signed)
    assert result["schema"] == owner.SCHEMA
    assert result["authenticated_evidence_count"] == 2
    assert result["evidence_assessment_status"] == "authenticated"
    assert all(row["signed_context_declaration_complete"] for row in result["reviews"])
    assert "production_trust_registry_unavailable" in result["blockers"]
    assert all(result[key] is False for key in signatures.FALSE_AUTHORITY)
    assert result["accepted_view_eligible"] is False
    args, kwargs = assessment_arguments(signed)
    assert (
        owner.validate_definition_use_review_assessment_v2(result, *args, **kwargs)
        == result
    )


def test_component_transport_hash_remains_distinct_from_full_canonical_record_hash(
    owner, case
):
    canonical_hash = sha(canonical_dag_json_bytes(case["record"]))
    case["component_raw"] = wire(case["record"]) + b"\n"
    transport_hash = sha(case["component_raw"])
    assert transport_hash != canonical_hash
    case["expected_component_pin"]["component_sha256"] = transport_hash
    prepared = materialize(owner, case)
    prep = prepared["preparation"]
    assert prep["component_pin"]["component_sha256"] == transport_hash
    assert prep["component_canonical_sha256"] == canonical_hash
    assert prep["graph_id"] == case["record"]["graph"]["record_cid"]
    assert prep["ast_sha256"] == case["expected_component_pin"]["joint_ast_sha256"]
    artifacts = {row["artifact_id"]: row for row in prep["artifacts"]}
    assert artifacts[case["record"]["record_cid"]]["artifact_sha256"] == transport_hash
    assert (
        artifacts["v2-use-review-component-canonical:sha256:" + canonical_hash][
            "artifact_sha256"
        ]
        == canonical_hash
    )


def test_external_shaped_fixture_keys_do_not_prove_humans_meaning_or_lean(
    owner, signed
):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    _REVIEW.refresh(signed)
    result = assess(owner, signed)
    assert result["review_prerequisites_satisfied_under_selected_trust"] is True
    assert result["accepted_view_eligible"] is False
    assert all(result[key] is False for key in signatures.FALSE_AUTHORITY)
    assert set(result["blockers"]) == {
        "downstream_Lean_kernel_admission_required",
        "downstream_semantic_validation_required",
    }


@pytest.mark.parametrize(
    "field", ["component_sha256", "component_cid", "graph_cid", "joint_ast_sha256"]
)
def test_each_independent_component_pin_is_required_before_review(owner, case, field):
    case["expected_component_pin"][field] = (
        _USE.cid("foreign-component") if field.endswith("_cid") else "0" * 64
    )
    with pytest.raises(ValueError):
        owner.prepare_definition_use_review_evidence_v2(**arguments(case))


@pytest.mark.parametrize(
    "damage", ["alias_ast", "joint_ast", "body_roles", "graph", "authority"]
)
def test_resealed_component_must_match_original_complete_use_regeneration(
    owner, case, damage
):
    record = case["record"]
    if damage == "alias_ast":
        record["alias_native"]["native_ast"]["formula"]["operator"]["value"] = "→"
    elif damage == "joint_ast":
        record["joint_native"]["native_ast"]["operator"]["value"] = "∨"
    elif damage == "body_roles":
        record["binding_record"]["body_roles"].pop()
        record["binding_record"] = reseal(record["binding_record"])
    elif damage == "graph":
        record["graph"]["edges"].pop()
        record["graph"] = reseal(record["graph"])
    else:
        record["source_semantics_verified"] = True
    record = reseal(record)
    case["component_raw"] = canonical_dag_json_bytes(record)
    case["expected_component_pin"].update(
        component_sha256=sha(case["component_raw"]),
        component_cid=record["record_cid"],
        graph_cid=record["graph"]["record_cid"],
        joint_ast_sha256=sha(
            canonical_dag_json_bytes(record["joint_native"]["native_ast"])
        ),
    )
    with pytest.raises(ValueError):
        owner.prepare_definition_use_review_evidence_v2(**arguments(case))


@pytest.mark.parametrize("damage", ["query_pin", "preparation_pin", "omitted_context"])
def test_new_review_replays_original_lookup_and_both_definition_context_populations(
    owner, case, damage
):
    if damage == "query_pin":
        case["use_inputs"]["expected_query_sha256"] = "0" * 64
    elif damage == "preparation_pin":
        case["use_inputs"]["donor_evidence_inputs"]["expected_preparation_cid"] = (
            _USE.cid("foreign-preparation")
        )
    else:
        evidence = case["use_inputs"]["consumer_evidence_inputs"]
        evidence["context_inputs"].pop()
        evidence["expected_context_population"].pop()
    with pytest.raises(ValueError):
        owner.prepare_definition_use_review_evidence_v2(**arguments(case))


@pytest.mark.parametrize("damage", ["alias_digest", "scope", "contexts", "artifacts"])
def test_repaired_preparation_seal_cannot_substitute_combined_review_evidence(
    owner, base_materialized, damage
):
    prep = deepcopy(base_materialized["preparation"])
    if damage == "alias_digest":
        prep["alias_ast_sha256"] = "0" * 64
    elif damage == "scope":
        prep["scope_id"] = base_materialized["component"]["case"]["consumer"][
            "candidate"
        ]["scope_record"]["record_cid"]
    elif damage == "contexts":
        prep["contexts"].pop()
    else:
        prep["artifacts"].pop()
    with pytest.raises(ValueError):
        owner.validate_definition_use_review_evidence_v2(
            reseal(prep), **base_materialized["arguments"]
        )


@pytest.mark.parametrize(
    "damage", ["omit_required", "reverse_required", "omit_edge", "graph_hash"]
)
def test_new_subject_preserves_every_source_lookup_and_review_policy_dependency(
    owner, base_materialized, damage
):
    prep = base_materialized["preparation"]
    artifacts, edges = deepcopy(prep["artifacts"]), deepcopy(prep["edges"])
    required = list(prep["required_dependency_ids"])
    if damage == "omit_required":
        required.pop()
    elif damage == "reverse_required":
        required[1:] = reversed(required[1:])
    elif damage == "omit_edge":
        edges.pop()
        required.pop()
    else:
        artifacts[0]["artifact_sha256"] = "0" * 64
    manifest = dependencies.build_dependency_manifest(
        artifacts, edges, expected_artifact_ids=prep["expected_artifact_ids"]
    )
    with pytest.raises(ValueError):
        owner.build_definition_use_review_subject_v2(
            prep,
            manifest,
            **base_materialized["arguments"],
            expected_manifest_sha256=manifest["manifest_sha256"],
            required_dependency_ids=required,
        )


@pytest.mark.parametrize("old_domain", ["v2_definition", "v1_definition_norm"])
@pytest.mark.parametrize("field", ["schema", "action", "audience"])
def test_old_definition_domains_do_not_authorize_new_combined_assumption(
    owner, signed, old_domain, field
):
    if old_domain == "v2_definition":
        from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as old
    else:
        from ipfs_datasets_py.logic.autoformal import corpus_definition_review as old
    foreign = {
        "schema": old.CLAIM_SCHEMA,
        "action": old.ACTION,
        "audience": old.AUDIENCE,
    }[field]
    assert signed["reviews"][0][field] != foreign
    signed["reviews"][0][field] = foreign
    _REVIEW.refresh(signed)
    with pytest.raises(ValueError):
        assess(owner, signed)


@pytest.mark.parametrize(
    "damage,blocker",
    [
        ("signature", "signature_invalid"),
        ("role", "unauthorized_review_role"),
        ("revoked", "key_revoked"),
        ("time", "review_not_current"),
        ("original_scopes", "unauthorized_legal_scope"),
    ],
)
def test_existing_auth_engine_requires_current_roles_and_exact_new_combined_scope(
    owner, signed, damage, blocker
):
    if damage == "signature":
        signed["reviews"][0]["interpretation"]["rationale"] += " unsigned mutation"
    else:
        key = signed["registry"]["keys"][0]
        if damage == "role":
            key["roles"] = ["formal_review"]
        elif damage == "revoked":
            key["revoked_at_utc"] = _REVIEW.NOW
        elif damage == "time":
            signed["reviews"][0]["expires_at_utc"] = _REVIEW.NOW
        else:
            source = signed["component"]["case"]
            key["scope_ids"] = [
                source[role]["candidate"]["scope_record"]["record_cid"]
                for role in ("donor", "consumer")
            ]
        _REVIEW.refresh(signed)
    result = assess(owner, signed)
    assert blocker in result["reviews"][0]["blockers"]
    assert result["reviews"][0]["status"] == "rejected"
    assert result["accepted_view_eligible"] is False


def test_one_authorized_principal_cannot_supply_both_combined_review_roles(
    owner, signed
):
    first = signed["registry"]["keys"][0]["principal_id"]
    signed["registry"]["keys"][1]["principal_id"] = first
    signed["reviews"][1]["principal_id"] = first
    _REVIEW.refresh(signed)
    result = assess(owner, signed)
    assert result["authenticated_evidence_count"] == 2
    assert "distinct_authorized_review_principals_missing" in result["blockers"]


@pytest.mark.parametrize("damage", ["missing", "open", "changed_evidence"])
def test_complete_signed_context_declarations_cover_both_sources_and_all_repeated_uses(
    owner, signed, damage
):
    closure = signed["reviews"][0]["context_closure"]
    if damage == "missing":
        closure["obligations"].pop()
    elif damage == "open":
        closure["obligations"][-1]["disposition"] = "open"
    else:
        signed["evidence"]["fixture:v2-context"] += b" changed body"
    _REVIEW.refresh(signed)
    result = assess(owner, signed)
    assert result["authenticated_evidence_count"] == 2
    assert "authenticated_complete_context_declarations_missing" in result["blockers"]
    assert result["context_closure_verified"] is False


@pytest.mark.parametrize("kind", ["lookup", "context"])
def test_current_lookup_and_context_dependency_changes_block_combined_prerequisites(
    owner, signed, kind
):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    _REVIEW.refresh(signed)
    artifacts = signed["manifest"]["artifacts"]
    if kind == "lookup":
        identity = next(
            row["artifact_id"]
            for row in artifacts
            if row["artifact_id"].startswith("definition-lookup:")
        )
    else:
        identity = next(
            row["artifact_id"]
            for row in artifacts
            if row["artifact_id"].startswith("v2-definition-review-context:")
        )
    signed["observed_artifact_sha256s"][identity] = "0" * 64
    result = assess(owner, signed)
    assert result["authenticated_evidence_count"] == 2
    assert "required_dependency_closure_not_current" in result["blockers"]
    assert result["review_prerequisites_satisfied_under_selected_trust"] is False


def test_unavailable_reviews_remain_pending_without_synthesized_signers(owner, signed):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "unavailable"
    signed["registry"]["keys"] = []
    signed["reviews"] = []
    _REVIEW.refresh(signed)
    result = assess(owner, signed)
    assert result["evidence_assessment_status"] == "pending"
    assert result["authenticated_evidence_count"] == 0
    assert "trust_registry_unavailable" in result["blockers"]
    assert all(result[key] is False for key in signatures.FALSE_AUTHORITY)


def test_resigned_subject_with_only_alias_ast_hash_cannot_replace_full_joint_semantics(
    owner, signed
):
    signed["subject"]["ast_sha256"] = signed["preparation"]["alias_ast_sha256"]
    for claim in signed["reviews"]:
        claim["subject"] = deepcopy(signed["subject"])
        claim["interpretation"]["reviewed_ast_sha256"] = signed["subject"]["ast_sha256"]
    _REVIEW.refresh(signed)
    with pytest.raises(ValueError):
        assess(owner, signed)


@pytest.mark.parametrize("damage", ["component", "component_pin", "aggregate"])
def test_combined_input_bounds_precede_authentication_native_and_resolver_owners(
    owner, case, damage
):
    if damage == "component":
        case["component_raw"] = b" " * (contracts.MAX_RECORD_BYTES + 1)
        case["expected_component_pin"]["component_sha256"] = sha(case["component_raw"])
    elif damage == "component_pin":
        case["expected_component_pin"]["joint_ast_sha256"] = "x" * (
            contracts.MAX_RECORD_BYTES + 1
        )
    else:
        for role in ("donor_evidence_inputs", "consumer_evidence_inputs"):
            evidence = case["use_inputs"][role]
            large = b" " * (25 * 1024 * 1024)
            evidence["candidate_inputs"]["sampling_report_raw"] = large
            evidence["expected_candidate_pin"]["sampling_report_sha256"] = sha(large)
    original_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        blocked = {
            "legal_graph_review",
            "legal_family_routes",
            "scoped_definition_resolution",
            "corpus_definition_review_v2",
        }
        if name.rsplit(".", 1)[-1] in blocked or blocked.intersection(fromlist or ()):
            raise AssertionError(
                "operation owner imported before complete combined bounds"
            )
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", guarded):
        with pytest.raises(ValueError):
            owner.prepare_definition_use_review_evidence_v2(**arguments(case))


def test_rehashed_assessment_cannot_promote_combined_meaning_or_drop_blockers(
    owner, signed
):
    report = assess(owner, signed)
    report["accepted_view_eligible"] = report["source_semantics_verified"] = True
    report["blockers"] = []
    report["assessment_sha256"] = signatures.digest(
        {k: v for k, v in report.items() if k != "assessment_sha256"}
    )
    args, kwargs = assessment_arguments(signed)
    with pytest.raises(ValueError):
        owner.validate_definition_use_review_assessment_v2(report, *args, **kwargs)


def test_combined_review_import_loads_no_optional_operation_owners():
    script = """
import importlib,sys
module=importlib.import_module('ipfs_datasets_py.logic.autoformal.corpus_definition_use_review_v2')
for name in ('legal_graph_review','legal_family_routes','scoped_definition_resolution','corpus_definition_review_v2'):
    assert 'ipfs_datasets_py.logic.autoformal.'+name not in sys.modules,name
assert callable(module.prepare_definition_use_review_evidence_v2)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr

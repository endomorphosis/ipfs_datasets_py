"""Source-only review declarations authenticate custody, never reviewed law."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_parent_alignment_adapter as alignment_adapter
from ipfs_datasets_py.logic.autoformal import legal_candidate_context_inventory as context_owner
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust_owner
from ipfs_datasets_py.logic.autoformal import legal_source_review_handoff as handoff_owner
from ipfs_datasets_py.logic.profile_g import Ed25519Signer
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

NOW = "2026-10-14T09:00:00Z"
ISSUED = "2026-10-14T08:00:00Z"
EXPIRES = "2026-10-15T08:00:00Z"
START = "2026-10-01T00:00:00Z"
END = "2026-11-01T00:00:00Z"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def pretty(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()


def fixture_helper():
    spec = importlib.util.spec_from_file_location(
        "authored_full_source_alignment_for_source_review",
        Path(__file__).with_name("test_corpus_parent_alignment_adapter.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def case(tmp_path, **options):
    options.setdefault("parent_texts", [
        " Prelude aa aaaa under section 12. Historical and Revision Notes aa. Tail ",
        " Snow 雪 aa under paragraph (a)! ",
    ])
    data = fixture_helper().case(tmp_path, **options)
    aligned = alignment_adapter.build_parent_alignment_corpus(**data["arguments"])
    sentence_report = data["base_data"]["reports"]["parent_sentence_candidates"]
    parent_pin = data["arguments"]["expected_base_report_pins"]["parent_text_views"]["canonical_sha256"]
    sentence_inputs = {
        "expected_parent_text_views_report_sha256": parent_pin,
        "parent_text_views_inputs": data["arguments"]["base_replay_inputs"]["parent_text_views_inputs"],
    }
    alignment_inputs = {
        **sentence_inputs,
        "document_inputs": data["arguments"]["document_inputs"],
        "expected_document_population_sha256": data["arguments"]["expected_document_population_sha256"],
    }
    context_arguments = {
        "expected_sentence_candidates_report_sha256": sha(canonical(sentence_report)),
        "sentence_inputs": sentence_inputs,
        "expected_alignment_report_sha256": sha(canonical(data["alignment"])),
        "alignment_inputs": alignment_inputs,
    }
    context = context_owner.prepare_candidate_context_inventory(
        sentence_report, data["alignment"], **context_arguments
    )
    handoff = handoff_owner.prepare_source_review_handoff(
        context,
        expected_candidate_context_inventory_report_sha256=sha(canonical(context)),
        context_inputs={
            "sentence_candidates_report": sentence_report,
            "alignment_report": data["alignment"],
            **context_arguments,
        },
    )
    corpus_bytes = {
        "manifest": pretty(aligned["manifest"]) + b"\n",
        "pages": b"".join(canonical(page) + b"\n" for page in aligned["pages"]),
        "records": b"".join(canonical(record) + b"\n" for record in aligned["records"]),
    }
    source_reports = {"context": context, "handoff": handoff}
    report_bytes = {key: pretty(value) + b"\n" for key, value in source_reports.items()}
    return {
        "alignment_data": data,
        "alignment_corpus": aligned,
        "source_reports": source_reports,
        "arguments": {
            "alignment_corpus_bytes": corpus_bytes,
            "expected_alignment_corpus_pins": {key: sha(raw) for key, raw in corpus_bytes.items()},
            "alignment_replay_inputs": data["arguments"],
            "source_report_bytes": report_bytes,
            "expected_source_report_pins": {
                key: {"raw_sha256": sha(report_bytes[key]), "canonical_sha256": sha(canonical(value))}
                for key, value in source_reports.items()
            },
        },
    }


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_source_review

    return corpus_source_review


def prepare(owner, data, **options):
    return owner.prepare_source_review_requests(**data["arguments"], **options)


def reseal(record):
    return contracts.seal_record(
        {key: deepcopy(value) for key, value in record.items() if key not in {"record_cid", "cid_scope"}}
    )


def repin_source(data, key, mutate):
    value = json.loads(data["arguments"]["source_report_bytes"][key])
    mutate(value)
    seal = "context_inventory_sha256" if key == "context" else "review_handoff_sha256"
    value[seal] = sha(canonical({key: item for key, item in value.items() if key != seal}))
    raw = pretty(value) + b"\n"
    data["arguments"]["source_report_bytes"][key] = raw
    data["arguments"]["expected_source_report_pins"][key] = {
        "raw_sha256": sha(raw), "canonical_sha256": sha(canonical(value))
    }


def dependency_observations(manifest):
    pins = {kind: {} for kind in dependencies.PIN_KINDS}
    for row in manifest["artifacts"]:
        for kind, references in row["dependency_pins"].items():
            pins[kind].update({ref["key"]: ref["sha256"] for ref in references})
    return {
        "observed_artifact_sha256s": {row["artifact_id"]: row["artifact_sha256"] for row in manifest["artifacts"]},
        "observed_pins": pins,
    }


def group_pins(groups):
    return [{
        "request_cid": group["request_cid"],
        "reviews_sha256": sha(canonical(group["reviews"])),
        "evidence_sha256s": {key: sha(raw) for key, raw in group["evidence_artifacts"].items()},
        "observed_artifacts_sha256": sha(canonical(group["observed_artifact_sha256s"])),
        "observed_pins_sha256": sha(canonical(group["observed_pins"])),
    } for group in groups]


def signed_case(owner, tmp_path, *, trust_mode="synthetic_fixture", sign_all=False, **options):
    options.setdefault("parent_texts", [" aa under section 12. ", "aa."])
    data = case(tmp_path, **options)
    preparation = prepare(owner, data)
    signers = [Ed25519Signer.generate("did:example:source-review-legal"), Ed25519Signer.generate("did:example:source-review-formal")]
    roles = list(trust_owner.ROLES)
    scopes = list(dict.fromkeys(subject["scope_id"] for subject in preparation["subjects"]))
    keys = [{
        "key_id": "fixture:source-key:" + str(index),
        "signer_did": signer.did,
        "public_key_hex": signer.public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex(),
        "principal_id": "fixture:source-principal:" + str(index),
        "roles": [role], "scope_ids": scopes,
        "valid_from_utc": START, "valid_until_utc": END, "revoked_at_utc": None,
    } for index, (signer, role) in enumerate(zip(signers, roles, strict=True))]
    registry = {
        "schema": trust_owner.REGISTRY_SCHEMA, "mode": trust_mode,
        "process_id": "fixture:source-review-process", "generation": 1, "revocation_generation": 1,
        "valid_from_utc": START, "valid_until_utc": END, "keys": keys, "revoked_principals": [],
    }
    policy = {
        "schema": trust_owner.POLICY_SCHEMA, "mode": trust_mode,
        "policy_id": "fixture:source-policy", "process_id": registry["process_id"],
        "registry_sha256": sha(canonical(registry)), "action": owner.ACTION, "audience": owner.AUDIENCE,
        "required_roles": roles, "valid_from_utc": START, "valid_until_utc": END, "max_review_age_seconds": 86400,
    }
    evidence = {"fixture:source-declaration": b"Synthetic source-review engineering fixture; no human review or law authority."}
    groups = []
    for ordinal, (request, subject, manifest) in enumerate(zip(
        preparation["requests"], preparation["subjects"], preparation["dependency_manifests"], strict=True
    )):
        closure = {
            "status": "declared_complete", "unresolved": [],
            "obligations": [{
                "slot_id": slot, "disposition": "not_applicable",
                "evidence_refs": [{"artifact_id": "fixture:source-declaration", "sha256": sha(evidence["fixture:source-declaration"])}],
            } for slot in subject["context_slot_ids"]],
        }
        reviews = []
        if ordinal == 0 or sign_all:
            reviews = [signer.sign({
                "schema": owner.CLAIM_SCHEMA, "action": owner.ACTION, "audience": owner.AUDIENCE,
                "review_id": f"fixture:source-review:{ordinal}:{index}", "key_id": keys[index]["key_id"],
                "principal_id": keys[index]["principal_id"], "role": role,
                "registry_sha256": sha(canonical(registry)), "policy_sha256": sha(canonical(policy)),
                "issued_at_utc": ISSUED, "expires_at_utc": EXPIRES, "subject": deepcopy(subject),
                "interpretation": {
                    "decision": "support", "reviewed_graph_sha256": subject["graph_sha256"],
                    "reviewed_ast_sha256": subject["ast_sha256"], "rationale": "Synthetic source declarations only.", "ambiguity": [],
                },
                "context_closure": deepcopy(closure),
            }) for index, (signer, role) in enumerate(zip(signers, roles, strict=True))]
        groups.append({
            "request_cid": request["record_cid"], "reviews": reviews,
            "evidence_artifacts": deepcopy(evidence) if reviews else {},
            **dependency_observations(manifest),
        })
    return {"data": data, "preparation": preparation, "registry": registry, "policy": policy,
            "groups": groups, "signers": signers, "at_time_utc": NOW}


def refresh_signatures(data):
    data["policy"]["registry_sha256"] = sha(canonical(data["registry"]))
    for group in data["groups"]:
        for index, old in enumerate(group["reviews"]):
            body = {key: deepcopy(value) for key, value in old.items() if key not in {"signer_did", "signature_alg", "signature"}}
            body["registry_sha256"] = sha(canonical(data["registry"]))
            body["policy_sha256"] = sha(canonical(data["policy"]))
            group["reviews"][index] = data["signers"][index].sign(body)


def assess_arguments(data):
    return {
        **data["data"]["arguments"],
        "expected_preparation_manifest_sha256": sha(canonical(data["preparation"]["manifest"])),
        "expected_registry_sha256": sha(canonical(data["registry"])),
        "expected_policy_sha256": sha(canonical(data["policy"])),
        "expected_review_group_pins": group_pins(data["groups"]),
        "at_time_utc": data["at_time_utc"],
    }


def assess(owner, data, **options):
    arguments = {**assess_arguments(data), **options}
    return owner.assess_source_review_groups(
        data["preparation"], data["registry"], data["policy"], data["groups"], **arguments
    )


def assert_inventory(preparation):
    assert set(preparation) == {"manifest", "pages", "requests", "subjects", "dependency_manifests"}
    entries = [entry for page in preparation["pages"] for entry in page["entries"]]
    assert len(entries) == len(preparation["requests"]) == len(preparation["subjects"]) == len(preparation["dependency_manifests"])
    assert [entry["ordinal"] for entry in entries] == list(range(len(entries)))
    for entry, request, subject, manifest in zip(entries, preparation["requests"], preparation["subjects"], preparation["dependency_manifests"], strict=True):
        assert entry["request_cid"] == request["record_cid"]
        assert entry["subject_cid"] == subject["record_cid"]
        assert entry["request_sha256"] == sha(canonical_dag_json_bytes(request))
        assert entry["subject_sha256"] == sha(canonical_dag_json_bytes(subject))
        assert entry["dependency_manifest_sha256"] == manifest["manifest_sha256"]
        assert reseal(request) == request and reseal(subject) == subject
        assert len(canonical_dag_json_bytes(request)) <= contracts.MAX_RECORD_BYTES
        assert len(canonical_dag_json_bytes(subject)) <= contracts.MAX_RECORD_BYTES
        dependencies.validate_dependency_manifest(manifest, expected_manifest_sha256=manifest["manifest_sha256"])
    for record in [preparation["manifest"], *preparation["pages"]]:
        assert reseal(record) == record
        assert len(canonical_dag_json_bytes(record)) <= contracts.MAX_RECORD_BYTES


def assert_no_authority(owner, result):
    for record in [result["manifest"], *result["pages"], *result["records"]]:
        for flag in owner.FALSE_FLAGS:
            assert record[flag] is False
        assert record["selected_occurrence"] is record["governing_source_binding"] is None
    for row in result["records"]:
        assert row["deferred_questions_remain_pending"] is True
        assert len(row["deferred_review_slot_ids"]) == 7
        assert row["assessment"]["accepted_view_eligible"] is False
        for flag in trust_owner.FALSE_AUTHORITY:
            assert row["assessment"][flag] is False


def test_each_request_preserves_six_context_ten_review_questions_and_explicit_source_only_hashes(owner, tmp_path):
    data = case(tmp_path)
    prepared = prepare(owner, data)
    units = data["source_reports"]["handoff"]["queue_units"]
    for request, subject, original in zip(prepared["requests"], prepared["subjects"], units, strict=True):
        assert request["queue_ordinal"] == original["queue_ordinal"]
        assert request["review_unit_id"] == original["review_unit_id"]
        assert request["unit_kind"] == original["unit_kind"]
        questions = request["review_questions"]
        assert len(questions) == len({row["slot_id"] for row in questions}) == 16
        assert [(row["category"], row["kind"]) for row in questions] == [
            *(('context', kind) for kind in owner.CONTEXT_KINDS),
            *(('handoff', kind) for kind in handoff_owner.REVIEW_OBLIGATION_KINDS),
        ]
        assert all(row["status"] == "pending_independent_review" and row["verified"] is row["closed"] is False for row in questions)
        active = [row["slot_id"] for row in questions if row["assessment_scope"] == "source_context_evidence_declaration"]
        deferred = [row["slot_id"] for row in questions if row["assessment_scope"] == "deferred_semantic_or_proof_review"]
        assert request["context_slot_ids"] == subject["context_slot_ids"] == active and len(active) == 9
        assert request["deferred_review_slot_ids"] == subject["deferred_review_slot_ids"] == deferred and len(deferred) == 7
        assert subject["graph_id"] == subject["review_request_cid"] == request["record_cid"]
        assert subject["graph_sha256"] == sha(canonical_dag_json_bytes(request))
        assert subject["ast_sha256"] == request["questions_sha256"] == sha(canonical(questions))
        assert "no semantic graph" in subject["hash_recipes"]["graph_id"]
        assert "no native AST" in subject["hash_recipes"]["ast_sha256"]
        assert subject["scope_id"] == request["review_scope_id"]
        assert "governing legal scope" in subject["hash_recipes"]["scope_id"]
    counts = prepared["manifest"]["counts"]
    assert counts["question_count"] == len(units) * 16
    assert counts["active_source_context_slots"] == len(units) * 9
    assert counts["deferred_semantic_proof_questions"] == len(units) * 7
    assert owner.validate_source_review_requests(prepared, **data["arguments"]) == prepared


def test_source_requests_join_existing_complete_corpus_records_and_both_original_report_origins(owner, tmp_path):
    data = case(tmp_path)
    prepared = prepare(owner, data)
    aligned_data = data["alignment_data"]
    by_cid = {record["record_cid"]: record for record in [*aligned_data["base"]["records"], *data["alignment_corpus"]["records"]]}
    for request in prepared["requests"]:
        assert request["parent_record_cid"] in by_cid
        for ref in request["related_source_records"]:
            assert ref["schema"] == by_cid[ref["record_cid"]]["schema"]
            assert ref["sha256"] == sha(canonical_dag_json_bytes(by_cid[ref["record_cid"]]))
        assert all(by_cid[cid]["kind"] == "comparison" for cid in request["comparison_record_cids"])
        assert len(request["comparison_record_cids"]) == len(aligned_data["arguments"]["document_inputs"])
        for field, key in (("original_unit_binding", "handoff"), ("original_context_binding", "context")):
            binding = request[field]
            if binding is None:
                assert request["unit_kind"] == "exact_declared_markup_statute_block_opportunity"
                continue
            value = data["source_reports"][key]
            for component in binding["json_pointer"].split('/')[1:]:
                value = value[int(component)] if type(value) is list else value[component]
            assert binding["value_sha256"] == sha(canonical(value))
            assert binding["report_raw_sha256"] == data["arguments"]["expected_source_report_pins"][key]["raw_sha256"]
            assert binding["report_canonical_sha256"] == data["arguments"]["expected_source_report_pins"][key]["canonical_sha256"]
        assert by_cid[request["source_occurrence_cid"]]["source_version_cid"] == request["source_version_cid"]
        assert by_cid[request["context_cid"]]["availability"] == "required_unavailable"
        assert by_cid[request["context_cid"]]["dependency_verification"] == "declaration_only"


def test_real_synthetic_source_signatures_authenticate_only_selected_declarations_with_all_groups_preserved(owner, tmp_path):
    data = signed_case(owner, tmp_path)
    result = assess(owner, data)
    assert len(result["records"]) == len(data["preparation"]["requests"])
    first = result["records"][0]["assessment"]
    assert first["schema"] == owner.ASSESSMENT_SCHEMA
    assert first["evidence_assessment_status"] == "authenticated" and first["authenticated_evidence_count"] == 2
    assert all(row["signature_status"] == "valid" for row in first["reviews"])
    assert all(row["signed_context_declaration_complete"] for row in first["reviews"])
    assert "production_trust_registry_unavailable" in first["blockers"]
    assert all(row["assessment"]["evidence_assessment_status"] == "pending" for row in result["records"][1:])
    assert result["manifest"]["counts"]["authenticated_evidence"] == 2
    assert_no_authority(owner, result)
    args = assess_arguments(data)
    assert owner.validate_source_review_assessment(result, data["preparation"], data["registry"], data["policy"], data["groups"], **args) == result


def test_external_shaped_fixture_can_satisfy_nine_source_declarations_while_seven_questions_remain_pending(owner, tmp_path):
    data = signed_case(owner, tmp_path, trust_mode="external_pinned_trust", sign_all=True)
    result = assess(owner, data)
    assert all(row["assessment"]["review_prerequisites_satisfied_under_selected_trust"] is True for row in result["records"])
    assert result["manifest"]["counts"]["source_evidence_prerequisites_under_selected_trust"] == len(result["records"])
    assert_no_authority(owner, result)


def test_empty_groups_and_unavailable_registry_remain_pending_without_automatic_keys(owner, tmp_path):
    data = signed_case(owner, tmp_path)
    data["registry"]["mode"] = data["policy"]["mode"] = "unavailable"
    data["registry"]["keys"] = []
    data["policy"]["registry_sha256"] = sha(canonical(data["registry"]))
    for group in data["groups"]:
        group["reviews"], group["evidence_artifacts"] = [], {}
    result = assess(owner, data)
    assert all(row["assessment"]["evidence_assessment_status"] == "pending" for row in result["records"])
    assert all(row["assessment"]["authenticated_evidence_count"] == 0 for row in result["records"])
    assert all("trust_registry_unavailable" in row["assessment"]["blockers"] for row in result["records"])
    assert_no_authority(owner, result)


@pytest.mark.parametrize("domain", ["graph_claim", "definition_claim", "graph_policy", "definition_policy"])
def test_old_graph_and_typed_definition_domains_cannot_supply_source_review_evidence(owner, tmp_path, domain):
    from ipfs_datasets_py.logic.autoformal import corpus_definition_review
    old = trust_owner if domain.startswith("graph") else corpus_definition_review
    data = signed_case(owner, tmp_path)
    if domain.endswith("policy"):
        data["policy"]["action"], data["policy"]["audience"] = old.ACTION, old.AUDIENCE
    else:
        for review in data["groups"][0]["reviews"]:
            review["schema"], review["action"], review["audience"] = old.CLAIM_SCHEMA, old.ACTION, old.AUDIENCE
    refresh_signatures(data)
    with pytest.raises(ValueError):
        assess(owner, data)


@pytest.mark.parametrize(
    "damage,blocker",
    [("signature", "signature_invalid"), ("key", "unknown_authorized_key"),
     ("principal", "authorized_principal_binding_differs"), ("scope", "unauthorized_legal_scope"),
     ("role", "unauthorized_review_role"), ("key_revoked", "key_revoked"),
     ("principal_revoked", "principal_revoked"), ("expired", "review_not_current"),
     ("age", "review_age_exceeded"), ("key_interval", "key_not_current_for_review_interval")],
)
def test_source_signatures_roles_scopes_revocations_and_explicit_intervals_use_the_existing_trust_contract(owner, tmp_path, damage, blocker):
    data = signed_case(owner, tmp_path)
    review = data["groups"][0]["reviews"][0]
    key = data["registry"]["keys"][0]
    if damage == "key":
        review["key_id"] = "fixture:unknown-source-key"
    elif damage == "principal":
        review["principal_id"] = "fixture:other-source-principal"
    elif damage == "scope":
        key["scope_ids"] = ["fixture:unrelated-source-scope"]
    elif damage == "role":
        key["roles"] = ["formal_review"]
    elif damage == "key_revoked":
        key["revoked_at_utc"] = NOW
    elif damage == "principal_revoked":
        data["registry"]["revoked_principals"] = [{"principal_id": key["principal_id"], "revoked_at_utc": NOW}]
    elif damage == "expired":
        review["expires_at_utc"] = NOW
    elif damage == "age":
        review["issued_at_utc"] = "2026-10-12T08:00:00Z"
    elif damage == "key_interval":
        key["valid_from_utc"] = "2026-10-14T08:30:00Z"
    refresh_signatures(data)
    if damage == "signature":
        signature = data["groups"][0]["reviews"][0]["signature"]
        data["groups"][0]["reviews"][0]["signature"] = ("A" if signature[0] != "A" else "B") + signature[1:]
    result = assess(owner, data)
    row = result["records"][0]["assessment"]["reviews"][0]
    assert row["status"] == "rejected" and blocker in row["blockers"]
    assert_no_authority(owner, result)


def test_two_different_keys_under_one_principal_do_not_create_review_independence(owner, tmp_path):
    data = signed_case(owner, tmp_path)
    principal = data["registry"]["keys"][0]["principal_id"]
    data["registry"]["keys"][1]["principal_id"] = principal
    data["groups"][0]["reviews"][1]["principal_id"] = principal
    refresh_signatures(data)
    result = assess(owner, data)
    assert "distinct_authorized_review_principals_missing" in result["records"][0]["assessment"]["blockers"]
    assert_no_authority(owner, result)


@pytest.mark.parametrize("damage", ["missing", "order", "no_evidence", "changed_evidence", "open"])
def test_nine_active_declarations_require_exact_order_and_current_evidence_without_closing_deferred_questions(owner, tmp_path, damage):
    data = signed_case(owner, tmp_path)
    closure = data["groups"][0]["reviews"][0]["context_closure"]
    if damage == "missing":
        closure["obligations"].pop()
    elif damage == "order":
        closure["obligations"].reverse()
    elif damage == "no_evidence":
        closure["obligations"][0]["evidence_refs"] = []
    elif damage == "changed_evidence":
        data["groups"][0]["evidence_artifacts"]["fixture:source-declaration"] += b"changed bytes"
    else:
        closure["status"] = "open"
    refresh_signatures(data)
    result = assess(owner, data)
    first = result["records"][0]["assessment"]
    assert first["reviews"][0]["status"] == "authenticated"
    assert first["reviews"][0]["signed_context_declaration_complete"] is False
    assert "authenticated_complete_context_declarations_missing" in first["blockers"]
    assert_no_authority(owner, result)


def test_deferred_semantic_questions_cannot_be_inserted_into_the_active_source_signature_protocol(owner, tmp_path):
    data = signed_case(owner, tmp_path)
    data["groups"][0]["reviews"][0]["context_closure"]["obligations"].append({
        "slot_id": data["preparation"]["subjects"][0]["deferred_review_slot_ids"][0],
        "disposition": "not_applicable", "evidence_refs": [],
    })
    refresh_signatures(data)
    with pytest.raises(ValueError):
        assess(owner, data)


def test_changed_request_dependency_in_one_group_does_not_stale_other_request_groups(owner, tmp_path):
    data = signed_case(owner, tmp_path, trust_mode="external_pinned_trust", sign_all=True)
    affected = data["groups"][1]
    affected["observed_artifact_sha256s"][affected["request_cid"]] = "0" * 64
    result = assess(owner, data)
    assert result["records"][0]["assessment"]["review_prerequisites_satisfied_under_selected_trust"] is True
    assert "required_dependency_closure_not_current" in result["records"][1]["assessment"]["blockers"]
    assert_no_authority(owner, result)


def test_assessment_source_replay_occurs_once_for_the_complete_group_population(owner, tmp_path, monkeypatch):
    data = signed_case(owner, tmp_path)
    original = owner.prepare_source_review_requests
    calls = []
    def counted(**arguments):
        calls.append(1)
        return original(**arguments)
    monkeypatch.setattr(owner, "prepare_source_review_requests", counted)
    result = assess(owner, data)
    assert len(result["records"]) == len(data["groups"]) > 1
    assert calls == [1]


def test_source_pin_drift_during_real_signature_verification_refuses_grouped_authentication(owner, tmp_path, monkeypatch):
    data = signed_case(owner, tmp_path)
    original_verify = trust_owner._verify_signature
    original_pins = owner._pins
    state = {"drift": False}
    def verify(review, key):
        status = original_verify(review, key)
        state["drift"] = True
        return status
    def pins(owners):
        result = original_pins(owners)
        if state["drift"]:
            result[next(iter(result))] = "0" * 64
        return result
    monkeypatch.setattr(trust_owner, "_verify_signature", verify)
    monkeypatch.setattr(owner, "_pins", pins)
    with pytest.raises(contracts.CorpusContractError):
        assess(owner, data)
    assert state["drift"]


@pytest.mark.parametrize("missing", ["parent", "official", "zero_documents"])
def test_unavailable_sources_preserve_review_requests_and_explicit_missing_core_bindings(owner, tmp_path, missing):
    helper = fixture_helper()
    if missing == "parent":
        options = {"parent_texts": [None, "aa under section 12."]}
    elif missing == "official":
        options = {"docs": [helper.missing_document()]}
    else:
        options = {"docs": []}
    data = case(tmp_path, **options)
    prepared = prepare(owner, data)
    assert_inventory(prepared)
    assert len(prepared["requests"]) == data["source_reports"]["handoff"]["queue_unit_count"]
    if missing == "parent":
        unavailable = [r for r in prepared["requests"] if r["unit_kind"] == "unavailable_parent_text_observation"]
        assert len(unavailable) == 1
        assert unavailable[0]["source_version_cid"] is unavailable[0]["source_occurrence_cid"] is unavailable[0]["context_cid"] is None
    if missing == "zero_documents":
        assert all(not r["comparison_record_cids"] for r in prepared["requests"])
    assert owner.validate_source_review_requests(prepared, **data["arguments"]) == prepared


def test_forced_inventory_pages_keep_complete_request_subject_dependency_rows(owner, tmp_path):
    data = case(tmp_path)
    limits = {"max_requests_per_page": 2}
    prepared = prepare(owner, data, limits=limits)
    assert_inventory(prepared)
    assert len(prepared["pages"]) > 2
    assert all(len(page["entries"]) <= 2 for page in prepared["pages"])
    assert owner.validate_source_review_requests(prepared, **data["arguments"], limits=limits) == prepared


@pytest.mark.parametrize("damage", ["subset", "order", "duplicate", "entry_hash", "entry_subject", "entry_dependency", "page_offset"])
def test_resealed_preparation_pages_still_require_complete_exact_request_replay(owner, tmp_path, damage):
    data = case(tmp_path)
    limits = {"max_requests_per_page": 2}
    prepared = prepare(owner, data, limits=limits)
    if damage == "subset":
        prepared["pages"].pop()
    elif damage == "order":
        prepared["pages"].reverse()
    elif damage == "duplicate":
        prepared["pages"].append(deepcopy(prepared["pages"][0]))
    else:
        page = prepared["pages"][0]
        if damage == "entry_hash":
            page["entries"][0]["request_sha256"] = "0" * 64
        elif damage == "entry_subject":
            page["entries"][0]["subject_cid"] = prepared["subjects"][1]["record_cid"]
        elif damage == "entry_dependency":
            page["entries"][0]["dependency_manifest_sha256"] = "0" * 64
        else:
            page["first_request_ordinal"] = True
        prepared["pages"][0] = reseal(page)
        prepared["manifest"]["page_refs"][0]["page_cid"] = prepared["pages"][0]["record_cid"]
        prepared["manifest"]["page_refs"][0]["sha256"] = sha(canonical(prepared["pages"][0]))
        prepared["manifest"] = reseal(prepared["manifest"])
    with pytest.raises(contracts.CorpusContractError):
        owner.validate_source_review_requests(prepared, **data["arguments"], limits=limits)


@pytest.mark.parametrize(
    "limit", ["max_source_report_bytes", "max_corpus_manifest_bytes", "max_corpus_page_bytes",
              "max_corpus_record_bytes", "max_replay_bytes", "max_total_input_bytes",
              "max_requests", "max_collection_bytes", "max_page_bytes", "max_pages"]
)
def test_complete_lowered_preparation_caps_refuse_without_selecting_a_prefix(owner, tmp_path, limit):
    data = case(tmp_path)
    limits = {limit: 1}
    if limit == "max_pages":
        limits["max_requests_per_page"] = 2
    with pytest.raises(contracts.CorpusContractError):
        prepare(owner, data, limits=limits)


@pytest.mark.parametrize("limits", [{"unknown": 1}, {"max_requests": True}, {"max_pages": 0}, {"max_requests_per_page": 65}])
def test_source_review_limits_cannot_raise_or_alias_profiles(owner, tmp_path, limits):
    with pytest.raises(contracts.CorpusContractError):
        prepare(owner, case(tmp_path), limits=limits)


def test_detached_source_preparation_exceeds_one_envelope_while_every_seal_stays_bounded(owner, tmp_path):
    data = case(tmp_path)
    prepared = prepare(owner, data)
    assert len(canonical(prepared)) > contracts.MAX_RECORD_BYTES
    assert contracts.MAX_RECORD_BYTES == 1024 * 1024
    assert_inventory(prepared)
    assert owner.validate_source_review_requests(prepared, **data["arguments"]) == prepared


@pytest.mark.parametrize("damage", ["too_many_reviews", "too_many_evidence", "group_bytes", "batch_bytes"])
def test_group_resource_caps_refuse_before_any_original_source_replay(owner, tmp_path, monkeypatch, damage):
    data = signed_case(owner, tmp_path)
    group = data["groups"][0]
    options = {}
    if damage == "too_many_reviews":
        group["reviews"] = [deepcopy(group["reviews"][0])] * 33
    elif damage == "too_many_evidence":
        group["evidence_artifacts"] = {f"fixture:source-evidence:{index}": b"x" for index in range(257)}
    elif damage == "group_bytes":
        group["evidence_artifacts"]["fixture:large-evidence"] = b"x" * (trust_owner.MAX_BYTES + 1)
    else:
        options["limits"] = {"max_batch_review_bytes": 1}
    monkeypatch.setattr(owner, "prepare_source_review_requests", lambda **kwargs: pytest.fail("over-bound group reached source replay"))
    with pytest.raises(ValueError):
        assess(owner, data, **options)


def test_grouped_assessment_output_cannot_alias_mutable_caller_keys_reviews_or_preparation(owner, tmp_path):
    data = signed_case(owner, tmp_path)
    result = assess(owner, data)
    before = canonical(result)
    data["registry"]["keys"][0]["roles"].append("formal_review")
    data["groups"][0]["reviews"][0]["context_closure"]["obligations"].clear()
    data["preparation"]["requests"][0]["review_questions"][0]["closed"] = True
    data["groups"][0]["evidence_artifacts"].clear()
    assert canonical(result) == before


@pytest.mark.parametrize("damage", ["action", "audience", "mode", "roles", "key_time", "evaluation_time"])
def test_malformed_trust_domain_and_time_refuse_before_original_source_replay(owner, tmp_path, monkeypatch, damage):
    data = signed_case(owner, tmp_path)
    if damage == "action":
        data["policy"]["action"] = trust_owner.ACTION
    elif damage == "audience":
        data["policy"]["audience"] = trust_owner.AUDIENCE
    elif damage == "mode":
        data["registry"]["mode"] = data["policy"]["mode"] = "invented_trust"
    elif damage == "roles":
        data["policy"]["required_roles"].reverse()
    elif damage == "key_time":
        data["registry"]["keys"][0]["valid_from_utc"] = "2026-10-14T08:00:00+00:00"
    else:
        data["at_time_utc"] = "2026-10-14T09:00:00+00:00"
    refresh_signatures(data)
    monkeypatch.setattr(owner, "prepare_source_review_requests", lambda **kwargs: pytest.fail("invalid trust/time reached source replay"))
    with pytest.raises(ValueError):
        assess(owner, data)


def test_remaining_evidence_budget_is_checked_before_hashing_excess_body(owner, tmp_path, monkeypatch):
    data = signed_case(owner, tmp_path)
    group = data["groups"][0]
    group["evidence_artifacts"]["fixture:first-large-body"] = b"a" * (4 * 1024 * 1024)
    excess = b"b" * (4 * 1024 * 1024)
    group["evidence_artifacts"]["fixture:second-large-body"] = excess
    original = owner._sha
    def bounded_hash(raw):
        if raw is excess:
            pytest.fail("excess evidence hashed before remaining byte-budget refusal")
        return original(raw)
    monkeypatch.setattr(owner, "_sha", bounded_hash)
    monkeypatch.setattr(owner, "prepare_source_review_requests", lambda **kwargs: pytest.fail("over-budget evidence reached source replay"))
    with pytest.raises(ValueError):
        assess(owner, data)


def test_escaped_nested_replay_budget_refuses_before_bulk_serialization_and_owner_import(owner, tmp_path, monkeypatch):
    data = case(tmp_path)
    replay = data["arguments"]["alignment_replay_inputs"]["base_replay_inputs"]
    replay["provenance_reports"][0]["rows"][0]["raw_row"]["wide_observation"] = ["雪\\\"\n" * 400] * 10
    original = json.dumps
    def bounded_dump(value, *args, **kwargs):
        if value is replay:
            pytest.fail("over-budget replay bulk serialized before refusal")
        return original(value, *args, **kwargs)
    monkeypatch.setattr(json, "dumps", bounded_dump)
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("owner imported before nested-budget refusal"))
    with pytest.raises(contracts.CorpusContractError):
        prepare(owner, data, limits={"max_replay_bytes": 512})


@pytest.mark.parametrize("damage", ["record_population", "oversized_nested_report"])
def test_malformed_assessment_output_refuses_before_regenerating_source_evidence(owner, tmp_path, monkeypatch, damage):
    data = signed_case(owner, tmp_path)
    result = assess(owner, data)
    if damage == "record_population":
        result["records"] = [result["records"][0]] * (owner.DEFAULT_LIMITS["max_requests"] + 1)
    else:
        result["records"][0]["assessment"]["untrusted_huge_note"] = "x" * (contracts.MAX_RECORD_BYTES + 1)
    monkeypatch.setattr(owner, "assess_source_review_groups", lambda *args, **kwargs: pytest.fail("malformed output reached costly source re-assessment"))
    with pytest.raises(contracts.CorpusContractError):
        owner.validate_source_review_assessment(result, data["preparation"], data["registry"], data["policy"], data["groups"], **assess_arguments(data))


@pytest.mark.parametrize("damage", ["authority", "pending", "nested_blocker", "membership"])
def test_resealed_assessments_cannot_apply_reviews_or_promote_deferred_questions(owner, tmp_path, damage):
    data = signed_case(owner, tmp_path)
    result = assess(owner, data)
    if damage == "membership":
        result["records"].pop()
    else:
        record = result["records"][0]
        if damage == "authority":
            record["source_review_completed"] = True
        elif damage == "pending":
            record["deferred_questions_remain_pending"] = False
        else:
            record["assessment"]["blockers"] = []
            body = {key: value for key, value in record["assessment"].items() if key != "assessment_sha256"}
            record["assessment"]["assessment_sha256"] = sha(canonical(body))
        result["records"][0] = reseal(record)
    with pytest.raises(ValueError):
        owner.validate_source_review_assessment(result, data["preparation"], data["registry"], data["policy"], data["groups"], **assess_arguments(data))


def test_full_ordered_source_queue_is_prepared_without_creating_any_review(owner, tmp_path):
    data = case(tmp_path)
    before = canonical(data["alignment_corpus"])
    prepared = prepare(owner, data)
    assert_inventory(prepared)
    assert len(prepared["requests"]) == len(data["source_reports"]["handoff"]["queue_units"])
    assert canonical(data["alignment_corpus"]) == before
    assert {unit["unit_kind"] for unit in data["source_reports"]["handoff"]["queue_units"]} == {
        "original_parent_partition_piece", "original_unresolved_surface_reference", "exact_declared_markup_statute_block_opportunity"
    }


@pytest.mark.parametrize("key", ["context", "handoff"])
@pytest.mark.parametrize("pin", ["raw_sha256", "canonical_sha256"])
def test_original_source_reports_require_independent_raw_and_FULL_pins(owner, tmp_path, key, pin):
    data = case(tmp_path)
    data["arguments"]["expected_source_report_pins"][key][pin] = "0" * 64
    with pytest.raises(contracts.CorpusContractError):
        prepare(owner, data)


@pytest.mark.parametrize("key", ["manifest", "pages", "records"])
def test_each_complete_alignment_transport_is_independently_pinned(owner, tmp_path, key, monkeypatch):
    data = case(tmp_path)
    data["arguments"]["expected_alignment_corpus_pins"][key] = "0" * 64
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("owner import preceded rawpin refusal"))
    with pytest.raises(contracts.CorpusContractError):
        prepare(owner, data)


@pytest.mark.parametrize("key", ["context", "handoff"])
def test_duplicate_JSON_keys_in_source_reports_are_refused_after_raw_repin(owner, tmp_path, key):
    data = case(tmp_path)
    raw = data["arguments"]["source_report_bytes"][key]
    raw = b'{"schema":"forged",' + raw.lstrip()[1:]
    data["arguments"]["source_report_bytes"][key] = raw
    data["arguments"]["expected_source_report_pins"][key]["raw_sha256"] = sha(raw)
    with pytest.raises(contracts.CorpusContractError):
        prepare(owner, data)


@pytest.mark.parametrize(
    "damage", ["missing_transport", "extra_transport", "missing_transport_pin", "missing_report",
               "extra_report", "missing_report_pin", "extra_report_pin", "callback", "buffer"]
)
def test_closed_complete_intake_refuses_partial_populations_and_callbacks(owner, tmp_path, damage):
    data = case(tmp_path)
    args = data["arguments"]
    if damage == "missing_transport":
        args["alignment_corpus_bytes"].pop("pages")
    elif damage == "extra_transport":
        args["alignment_corpus_bytes"]["selected"] = b"[]"
    elif damage == "missing_transport_pin":
        args["expected_alignment_corpus_pins"].pop("records")
    elif damage == "missing_report":
        args["source_report_bytes"].pop("context")
    elif damage == "extra_report":
        args["source_report_bytes"]["accepted"] = b"{}"
    elif damage == "missing_report_pin":
        args["expected_source_report_pins"].pop("handoff")
    elif damage == "extra_report_pin":
        args["expected_source_report_pins"]["context"]["reviewed"] = True
    elif damage == "buffer":
        args["source_report_bytes"]["context"] = bytearray(args["source_report_bytes"]["context"])
    else:
        args["alignment_replay_inputs"]["loader"] = lambda: pytest.fail("custom callback ran")
    with pytest.raises(contracts.CorpusContractError):
        prepare(owner, data)


@pytest.mark.parametrize("damage", ["drop", "order", "crop", "selector", "close_question", "admit"])
def test_repaired_handoff_hash_and_selfseal_cannot_replace_complete_source_replay(owner, tmp_path, damage):
    data = case(tmp_path)
    def mutate(report):
        unit = report["queue_units"][0]
        if damage == "drop":
            report["queue_units"].pop()
        elif damage == "order":
            report["queue_units"].reverse()
        elif damage == "crop":
            unit["original_observation"]["selector"]["text"] = "cropped"
        elif damage == "selector":
            unit["original_observation"]["selector"]["utf8byte_end"] += 1
        elif damage == "close_question":
            unit["review_obligations"][0]["closed"] = True
        else:
            unit["authority"]["admitted"] = True
    repin_source(data, "handoff", mutate)
    with pytest.raises(contracts.CorpusContractError):
        prepare(owner, data)


@pytest.mark.parametrize("damage", ["drop_piece", "drop_reference", "drop_opportunity", "source_geometry", "slots", "authority"])
def test_repaired_context_input_cannot_substitute_exact_original_sources(owner, tmp_path, damage):
    data = case(tmp_path)
    def mutate(report):
        first = report["rows"][0]
        if damage == "drop_piece":
            first["partition_piece_contexts"].pop()
        elif damage == "drop_reference":
            first["surface_reference_contexts"].pop()
        elif damage == "drop_opportunity":
            report["source_block_opportunities"].pop()
        elif damage == "source_geometry":
            report["selector_projection_table"][0]["char_start"] += 1
        elif damage == "slots":
            first["partition_piece_contexts"][0]["context_dependency_slots"].pop()
        else:
            report["authority"]["context_closure_verified"] = True
    repin_source(data, "context", mutate)
    with pytest.raises(contracts.CorpusContractError):
        prepare(owner, data)


@pytest.mark.parametrize("pin", ["preparation", "registry", "policy"])
def test_batch_requires_independent_preparation_and_selected_trust_pins(owner, tmp_path, pin):
    data = signed_case(owner, tmp_path)
    field = {
        "preparation": "expected_preparation_manifest_sha256",
        "registry": "expected_registry_sha256",
        "policy": "expected_policy_sha256",
    }[pin]
    with pytest.raises(ValueError):
        assess(owner, data, **{field: "0" * 64})


@pytest.mark.parametrize(
    "damage", ["missing", "order", "duplicate", "request_id", "unknown_field", "review_not_list", "callback"]
)
def test_batch_keeps_every_ordered_request_group_even_when_reviews_are_empty(owner, tmp_path, damage):
    data = signed_case(owner, tmp_path)
    groups = data["groups"]
    assert len(groups) > 1 and any(not group["reviews"] for group in groups)
    if damage == "missing":
        groups.pop()
    elif damage == "order":
        groups.reverse()
    elif damage == "duplicate":
        groups[1] = deepcopy(groups[0])
    elif damage == "request_id":
        groups[0]["request_cid"] = "not-a-content-identity"
    elif damage == "unknown_field":
        groups[0]["reviewed"] = True
    elif damage == "review_not_list":
        groups[0]["reviews"] = {}
    else:
        groups[0]["verifier"] = lambda: pytest.fail("custom signature verifier ran")
    with pytest.raises(ValueError):
        assess(owner, data)


@pytest.mark.parametrize("field", ["reviews_sha256", "evidence_sha256s", "observed_artifacts_sha256", "observed_pins_sha256"])
def test_complete_group_reviews_evidence_and_observations_have_independent_pins(owner, tmp_path, field):
    data = signed_case(owner, tmp_path)
    pins = group_pins(data["groups"])
    if field == "evidence_sha256s":
        pins[0][field]["fixture:source-declaration"] = "0" * 64
    else:
        pins[0][field] = "0" * 64
    with pytest.raises(ValueError):
        assess(owner, data, expected_review_group_pins=pins)


@pytest.mark.parametrize("damage", ["pin_subset", "pin_order", "pin_duplicate", "pin_unknown_field"])
def test_independent_group_population_pins_preserve_exact_membership_and_order(owner, tmp_path, damage):
    data = signed_case(owner, tmp_path)
    pins = group_pins(data["groups"])
    if damage == "pin_subset":
        pins.pop()
    elif damage == "pin_order":
        pins.reverse()
    elif damage == "pin_duplicate":
        pins[1] = deepcopy(pins[0])
    else:
        pins[0]["source_verified"] = True
    with pytest.raises(ValueError):
        assess(owner, data, expected_review_group_pins=pins)


@pytest.mark.parametrize(
    "damage", ["request_subset", "request_order", "subject_subset", "subject_order",
               "dependency_subset", "page_subset", "page_order", "request_authority", "subject_hash_recipe"]
)
def test_resealed_preparation_cannot_replace_full_request_subject_dependency_and_page_replay(owner, tmp_path, damage):
    data = signed_case(owner, tmp_path)
    prepared = data["preparation"]
    if damage == "request_subset":
        prepared["requests"].pop()
    elif damage == "request_order":
        prepared["requests"].reverse()
    elif damage == "subject_subset":
        prepared["subjects"].pop()
    elif damage == "subject_order":
        prepared["subjects"].reverse()
    elif damage == "dependency_subset":
        prepared["dependency_manifests"].pop()
    elif damage == "page_subset":
        prepared["pages"].pop()
    elif damage == "page_order":
        prepared["pages"].append(deepcopy(prepared["pages"][0]))
    elif damage == "request_authority":
        prepared["requests"][0]["admitted"] = True
        prepared["requests"][0] = reseal(prepared["requests"][0])
    else:
        prepared["subjects"][0]["hash_recipes"] = {"AST": "invented native syntax"}
        prepared["subjects"][0] = reseal(prepared["subjects"][0])
    with pytest.raises(ValueError):
        assess(owner, data)


def test_actual_public_import_is_inert():
    program = r'''
import sys
from ipfs_datasets_py.logic.autoformal import corpus_source_review
assert callable(corpus_source_review.prepare_source_review_requests)
assert callable(corpus_source_review.assess_source_review_groups)
assert not any(name == 'torch' or name.startswith('torch.') for name in sys.modules)
assert not any(name == 'transformers' or name.startswith('transformers.') for name in sys.modules)
assert not any(name == 'pyarrow' or name.startswith('pyarrow.') for name in sys.modules)
assert 'ipfs_datasets_py.logic.autoformal.legal_source_review_handoff' not in sys.modules
assert 'ipfs_datasets_py.logic.profile_g' not in sys.modules
print('inert public import verified')
'''
    repo = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [sys.executable, "-c", program], cwd=repo,
        env=dict(os.environ, IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0", PYTHONPATH=str(repo)),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "inert public import verified"

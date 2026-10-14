"""Typed candidate custody and real synthetic signatures; no human review."""

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
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_graph_review as graph_review
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as contexts
from ipfs_datasets_py.logic.profile_g import Ed25519Signer
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "authored_definition_fixture_for_typed_review",
    Path(__file__).with_name("test_corpus_definition_norm_adapter.py"),
)
assert _FIXTURE_SPEC is not None and _FIXTURE_SPEC.loader is not None
_FIXTURE_MODULE = importlib.util.module_from_spec(_FIXTURE_SPEC)
_FIXTURE_SPEC.loader.exec_module(_FIXTURE_MODULE)

NOW = "2026-10-14T03:00:00Z"
ISSUED = "2026-10-14T02:00:00Z"
EXPIRES = "2026-10-15T02:00:00Z"
START = "2026-10-01T00:00:00Z"
END = "2026-11-01T00:00:00Z"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode()


def candidate(modality="O", family="deontic_fol", **options):
    record, report_raw, report, request, arguments = _FIXTURE_MODULE.adapt_case(
        modality, family, **options
    )
    candidate_raw = canonical_dag_json_bytes(record)
    inputs = {
        "candidate_raw": candidate_raw,
        "report_raw": report_raw,
        "request_raw": arguments["request_raw"],
        "raw_html": arguments["raw_html"],
    }
    pin = {
        "candidate_sha256": sha(candidate_raw),
        "candidate_cid": record["record_cid"],
        "graph_cid": record["graph"]["record_cid"],
        "request_sha256": arguments["expected_request_sha256"],
        "report_sha256": arguments["expected_report_sha256"],
        "raw_sha256": arguments["expected_raw_sha256"],
        "extracted_sha256": arguments["expected_extracted_sha256"],
    }
    return inputs, pin, record, report, request


def reseal(record):
    return contracts.seal_record(
        {key: value for key, value in record.items() if key not in {"record_cid", "cid_scope"}}
    )


def artifact(identity, digest):
    return {
        "artifact_id": identity,
        "artifact_sha256": digest,
        "dependency_pins": {kind: [] for kind in dependencies.PIN_KINDS},
    }


def observations(manifest):
    pins = {kind: {} for kind in dependencies.PIN_KINDS}
    for row in manifest["artifacts"]:
        for kind, refs in row["dependency_pins"].items():
            pins[kind].update({ref["key"]: ref["sha256"] for ref in refs})
    return {
        "observed_artifact_sha256s": {
            row["artifact_id"]: row["artifact_sha256"] for row in manifest["artifacts"]
        },
        "observed_pins": pins,
    }


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_definition_review

    return corpus_definition_review


def context_inputs(case):
    inputs, _, record, _, request = case
    document = request["definition_request"]["document"]
    rows, expected = [], []
    for occurrence in record["source_occurrences"]:
        packet = contexts.build_context_packet(
            document,
            inputs["raw_html"],
            char_start=occurrence["start_char"],
            char_end=occurrence["end_char"],
        )
        raw = wire(packet)
        rows.append(
            {
                "source_occurrence_cid": occurrence["record_cid"],
                "packet_raw": raw,
                "dependency_requests": None,
            }
        )
        expected.append(
            {
                "source_occurrence_cid": occurrence["record_cid"],
                "packet_sha256": sha(raw),
            }
        )
    return rows, expected


def preparation_arguments(case, rows, expected):
    return {
        "candidate_inputs": case[0],
        "expected_candidate_pin": case[1],
        "context_inputs": rows,
        "expected_context_population": expected,
    }


def prepare(owner, case, rows=None, expected=None):
    if rows is None:
        rows, expected = context_inputs(case)
    return owner.prepare_definition_review_evidence(**preparation_arguments(case, rows, expected))


def materialize(owner, case):
    rows, expected = context_inputs(case)
    arguments = preparation_arguments(case, rows, expected)
    preparation = owner.prepare_definition_review_evidence(**arguments)
    manifest = dependencies.build_dependency_manifest(
        preparation["artifacts"],
        preparation["edges"],
        expected_artifact_ids=preparation["expected_artifact_ids"],
    )
    subject = owner.build_definition_review_subject(
        preparation,
        manifest,
        **arguments,
        expected_manifest_sha256=manifest["manifest_sha256"],
        required_dependency_ids=preparation["expected_artifact_ids"],
    )
    return {
        "case": case,
        "arguments": arguments,
        "preparation": preparation,
        "manifest": manifest,
        "subject": subject,
    }


def refresh(owner, case):
    case["policy"]["registry_sha256"] = graph_review.digest(case["registry"])
    for index, old in enumerate(case["reviews"]):
        body = {
            key: deepcopy(value)
            for key, value in old.items()
            if key not in {"signer_did", "signature_alg", "signature"}
        }
        body["registry_sha256"] = graph_review.digest(case["registry"])
        body["policy_sha256"] = graph_review.digest(case["policy"])
        case["reviews"][index] = case["signers"][index].sign(body)


@pytest.fixture
def signed(owner):
    case = materialize(owner, candidate())
    subject = case["subject"]
    signers = [
        Ed25519Signer.generate("did:example:typed-definition-legal-fixture"),
        Ed25519Signer.generate("did:example:typed-definition-formal-fixture"),
    ]
    roles = list(graph_review.ROLES)
    keys = [
        {
            "key_id": "fixture:typed-key:" + str(index),
            "signer_did": signer.did,
            "public_key_hex": signer.public_key.public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            ).hex(),
            "principal_id": "fixture:typed-principal:" + str(index),
            "roles": [role],
            "scope_ids": [subject["scope_id"]],
            "valid_from_utc": START,
            "valid_until_utc": END,
            "revoked_at_utc": None,
        }
        for index, (signer, role) in enumerate(zip(signers, roles, strict=True))
    ]
    registry = {
        "schema": graph_review.REGISTRY_SCHEMA,
        "mode": "synthetic_fixture",
        "process_id": "fixture:typed-review-process",
        "generation": 1,
        "revocation_generation": 1,
        "valid_from_utc": START,
        "valid_until_utc": END,
        "keys": keys,
        "revoked_principals": [],
    }
    policy = {
        "schema": graph_review.POLICY_SCHEMA,
        "mode": "synthetic_fixture",
        "policy_id": "fixture:typed-policy",
        "process_id": registry["process_id"],
        "registry_sha256": graph_review.digest(registry),
        "action": owner.ACTION,
        "audience": owner.AUDIENCE,
        "required_roles": roles,
        "valid_from_utc": START,
        "valid_until_utc": END,
        "max_review_age_seconds": 86400,
    }
    evidence = {
        "fixture:typed-context": b"Authored engineering context declarations only; no reviewed law."
    }
    closure = {
        "status": "declared_complete",
        "obligations": [
            {
                "slot_id": slot,
                "disposition": "not_applicable",
                "evidence_refs": [
                    {
                        "artifact_id": "fixture:typed-context",
                        "sha256": sha(evidence["fixture:typed-context"]),
                    }
                ],
            }
            for slot in subject["context_slot_ids"]
        ],
        "unresolved": [],
    }
    reviews = [
        signer.sign(
            {
                "schema": owner.CLAIM_SCHEMA,
                "action": owner.ACTION,
                "audience": owner.AUDIENCE,
                "review_id": "fixture:typed-review:" + str(index),
                "key_id": keys[index]["key_id"],
                "principal_id": keys[index]["principal_id"],
                "role": role,
                "registry_sha256": graph_review.digest(registry),
                "policy_sha256": graph_review.digest(policy),
                "issued_at_utc": ISSUED,
                "expires_at_utc": EXPIRES,
                "subject": deepcopy(subject),
                "interpretation": {
                    "decision": "support",
                    "reviewed_graph_sha256": subject["graph_sha256"],
                    "reviewed_ast_sha256": subject["ast_sha256"],
                    "rationale": "Synthetic typed-definition verification fixture only.",
                    "ambiguity": [],
                },
                "context_closure": deepcopy(closure),
            }
        )
        for index, (signer, role) in enumerate(zip(signers, roles, strict=True))
    ]
    case.update(
        registry=registry, policy=policy, reviews=reviews, signers=signers, evidence=evidence
    )
    case.update(observations(case["manifest"]))
    return case


def assessment_arguments(signed):
    return (
        signed["subject"],
        signed["registry"],
        signed["policy"],
        signed["reviews"],
        signed["manifest"],
    ), {
        **signed["arguments"],
        "expected_subject_sha256": graph_review.digest(signed["subject"]),
        "expected_registry_sha256": graph_review.digest(signed["registry"]),
        "expected_policy_sha256": graph_review.digest(signed["policy"]),
        "expected_reviews_sha256": graph_review.digest(signed["reviews"]),
        "expected_manifest_sha256": signed["manifest"]["manifest_sha256"],
        "at_time_utc": NOW,
        "observed_artifact_sha256s": signed["observed_artifact_sha256s"],
        "observed_pins": signed["observed_pins"],
        "evidence_artifacts": signed["evidence"],
    }


def assess(owner, signed):
    args, kwargs = assessment_arguments(signed)
    return owner.assess_definition_reviews(*args, **kwargs)


@pytest.mark.parametrize("modality", list("OPF"))
@pytest.mark.parametrize("family", ["deontic_fol", "tdfol"])
def test_six_typed_native_profiles_preserve_complete_AST_graph_and_all_physical_context_slots(
    owner, modality, family
):
    case = candidate(modality, family)
    data = materialize(owner, case)
    record, report = case[2], case[3]
    preparation, subject = data["preparation"], data["subject"]
    assert preparation["profile"] == record["profile"]
    assert preparation["family"] == family
    assert preparation["ast_sha256"] == sha(canonical_dag_json_bytes(report["native_ast"]))
    assert preparation["graph_sha256"] == sha(canonical_dag_json_bytes(record["graph"]))
    assert subject["scope_id"] == record["scope_record"]["record_cid"]
    assert subject["native_binding"] == preparation
    assert len(record["source_occurrences"]) == 13
    slot_ids = [
        slot["slot_id"]
        for row in data["arguments"]["context_inputs"]
        for slot in json.loads(row["packet_raw"])["dependency_slots"]
    ]
    assert len(slot_ids) == len(set(slot_ids)) == 78
    assert subject["context_slot_ids"] == slot_ids
    assert subject["required_dependency_ids"] == preparation["expected_artifact_ids"]
    assert subject["graph_id"] == record["graph"]["record_cid"]
    assert set(
        edge["dependency_id"]
        for edge in preparation["edges"]
        if edge["dependent_id"] == subject["graph_id"]
    ) == set(preparation["expected_artifact_ids"]) - {subject["graph_id"]}
    owner.validate_definition_review_evidence(preparation, **data["arguments"])
    for flag in (
        "admitted",
        "formalized",
        "source_semantics_verified",
        "context_closure_verified",
        "proof_authority",
    ):
        assert preparation[flag] is False


def test_real_native_domain_signatures_authenticate_all_78_fixture_obligations_without_legal_authority(
    owner, signed
):
    result = assess(owner, signed)
    assert result["schema"] == owner.SCHEMA
    assert result["evidence_assessment_status"] == "authenticated"
    assert result["authenticated_evidence_count"] == 2
    assert all(row["signature_status"] == "valid" for row in result["reviews"])
    assert all(row["signed_context_declaration_complete"] for row in result["reviews"])
    assert "production_trust_registry_unavailable" in result["blockers"]
    assert result["review_prerequisites_satisfied_under_selected_trust"] is False
    assert result["accepted_view_eligible"] is False
    assert all(result[field] is False for field in graph_review.FALSE_AUTHORITY)
    args, kwargs = assessment_arguments(signed)
    assert owner.validate_definition_review_assessment(result, *args, **kwargs) == result


def test_external_policy_wire_shape_uses_fixture_keys_and_never_authenticates_human_meaning(
    owner, signed
):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    refresh(owner, signed)
    result = assess(owner, signed)
    assert result["review_prerequisites_satisfied_under_selected_trust"] is True
    assert result["accepted_view_eligible"] is False
    assert all(result[field] is False for field in graph_review.FALSE_AUTHORITY)
    assert result["blockers"] == [
        "downstream_Lean_kernel_admission_required",
        "downstream_semantic_validation_required",
    ]


@pytest.mark.parametrize(
    "field",
    [
        "candidate_sha256",
        "candidate_cid",
        "graph_cid",
        "request_sha256",
        "report_sha256",
        "raw_sha256",
        "extracted_sha256",
    ],
)
def test_every_independent_candidate_input_pin_is_required_before_typed_preparation(owner, field):
    case = list(candidate())
    case[1] = deepcopy(case[1])
    if field.endswith("_cid"):
        case[1][field] = contracts.seal_record({"schema": "unrelated-fixture/v1"})["record_cid"]
    else:
        case[1][field] = "0" * 64
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize(
    "damage", ["omit", "reverse", "duplicate", "wrong_occurrence", "wrong_hash", "unknown_field"]
)
def test_context_population_preserves_one_exact_original_packet_per_physical_occurrence(
    owner, damage
):
    case = candidate()
    rows, expected = context_inputs(case)
    if damage == "omit":
        rows.pop()
        expected.pop()
    elif damage == "reverse":
        rows.reverse()
        expected.reverse()
    elif damage == "duplicate":
        rows[-1] = deepcopy(rows[0])
        expected[-1] = deepcopy(expected[0])
    elif damage == "wrong_occurrence":
        rows[0]["source_occurrence_cid"] = rows[1]["source_occurrence_cid"]
        expected[0]["source_occurrence_cid"] = rows[1]["source_occurrence_cid"]
    elif damage == "wrong_hash":
        expected[0]["packet_sha256"] = "0" * 64
    else:
        rows[0]["reviewed"] = True
    with pytest.raises(ValueError):
        prepare(owner, case, rows, expected)


@pytest.mark.parametrize(
    "damage", ["different_origin", "omitted_slot", "UTF8_offset", "false_closure", "source_edition"]
)
def test_rehashed_context_packet_cannot_retarget_source_geometry_or_close_obligations(
    owner, damage
):
    case = candidate()
    rows, expected = context_inputs(case)
    packet = json.loads(rows[0]["packet_raw"])
    if damage == "different_origin":
        packet = json.loads(rows[1]["packet_raw"])
    elif damage == "omitted_slot":
        packet["dependency_slots"].pop()
    elif damage == "UTF8_offset":
        packet["selection"]["utf8_byte_start"] += 1
    elif damage == "false_closure":
        packet["context_closure_verified"] = True
    elif damage == "source_edition":
        packet["source_document"]["edition"] += 1
    body = {key: value for key, value in packet.items() if key != "packet_id"}
    packet["packet_id"] = "legal-context-packet:sha256:" + sha(contexts._context_wire(body))
    rows[0]["packet_raw"] = wire(packet)
    expected[0]["packet_sha256"] = sha(rows[0]["packet_raw"])
    with pytest.raises(ValueError):
        prepare(owner, case, rows, expected)


@pytest.mark.parametrize(
    "damage",
    [
        "native_AST",
        "modal_guard",
        "variable",
        "joint_order",
        "graph_edge",
        "scope",
        "source_occurrence",
        "false_review",
        "canonical_profile",
    ],
)
def test_resealed_rehashed_candidate_must_still_match_original_native_request_report_source_and_graph(
    owner, damage
):
    case = list(candidate())
    original_record = deepcopy(case[2])
    if damage == "native_AST":
        original_record["ast_record"]["native_ast"]["left"]["formula"]["operator"]["value"] = "→"
        original_record["ast_record"] = reseal(original_record["ast_record"])
    elif damage == "modal_guard":
        native_ast = original_record["norm_record"]["native_ast"]
        native_ast["formula"]["left"], native_ast["formula"]["right"] = (
            native_ast["formula"]["right"],
            native_ast["formula"]["left"],
        )
        original_record["norm_record"] = reseal(original_record["norm_record"])
    elif damage == "variable":
        original_record["symbol_record"]["variable_binding"]["variable"] = "y"
        original_record["symbol_record"] = reseal(original_record["symbol_record"])
    elif damage == "joint_order":
        joint = original_record["ast_record"]["native_ast"]
        joint["left"], joint["right"] = joint["right"], joint["left"]
        original_record["ast_record"] = reseal(original_record["ast_record"])
    elif damage == "graph_edge":
        original_record["graph"]["edges"].pop()
        original_record["graph"] = reseal(original_record["graph"])
    elif damage == "scope":
        original_record["scope_record"]["edition"] += 1
        original_record["scope_record"] = reseal(original_record["scope_record"])
    elif damage == "source_occurrence":
        original_record["source_occurrences"][0]["start_utf8"] += 1
        original_record["source_occurrences"][0] = reseal(original_record["source_occurrences"][0])
    elif damage == "false_review":
        original_record["independently_reviewed"] = True
    elif damage == "canonical_profile":
        original_record["profile"] = "canonical_rules_v1"
    changed = reseal(original_record)
    case[0] = dict(case[0], candidate_raw=canonical_dag_json_bytes(changed))
    case[1] = dict(
        case[1],
        candidate_sha256=sha(case[0]["candidate_raw"]),
        candidate_cid=changed["record_cid"],
        graph_cid=changed["graph"]["record_cid"],
    )
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize(
    "field", ["graph_sha256", "ast_sha256", "scope_id", "context_slot_ids", "native_binding"]
)
def test_signed_subject_retargeting_is_rejected_even_after_new_outer_subject_pin_and_signature(
    owner, signed, field
):
    if field.endswith("sha256"):
        signed["subject"][field] = "0" * 64
    elif field == "scope_id":
        signed["subject"][field] = contracts.seal_record({"schema": "foreign-scope/v1"})[
            "record_cid"
        ]
    elif field == "context_slot_ids":
        signed["subject"][field].pop()
    else:
        binding = deepcopy(signed["subject"][field])
        binding["family"] = "fol"
        signed["subject"][field] = reseal(binding)
    for review in signed["reviews"]:
        review["subject"] = deepcopy(signed["subject"])
    refresh(owner, signed)
    with pytest.raises(ValueError):
        assess(owner, signed)


@pytest.mark.parametrize(
    "damage", ["omitted_required", "reordered_required", "omitted_edge", "wrong_graph_hash"]
)
def test_subject_requires_the_entire_independently_pinned_input_and_context_dependency_closure(
    owner, signed, damage
):
    preparation = signed["preparation"]
    manifest = signed["manifest"]
    required = list(preparation["expected_artifact_ids"])
    if damage == "omitted_required":
        required.pop()
    elif damage == "reordered_required":
        required[1:] = reversed(required[1:])
    elif damage == "omitted_edge":
        manifest = dependencies.build_dependency_manifest(
            preparation["artifacts"],
            preparation["edges"][:-1],
            expected_artifact_ids=preparation["expected_artifact_ids"],
        )
        required.pop()
    elif damage == "wrong_graph_hash":
        artifacts = deepcopy(preparation["artifacts"])
        artifacts[0]["artifact_sha256"] = "0" * 64
        manifest = dependencies.build_dependency_manifest(
            artifacts,
            preparation["edges"],
            expected_artifact_ids=preparation["expected_artifact_ids"],
        )
    with pytest.raises(ValueError):
        owner.build_definition_review_subject(
            preparation,
            manifest,
            **signed["arguments"],
            expected_manifest_sha256=manifest["manifest_sha256"],
            required_dependency_ids=required,
        )


@pytest.mark.parametrize("damage", ["changed_artifact", "missing_artifact", "changed_owner_pin"])
def test_current_source_companion_or_owner_dependency_changes_block_authentication_prerequisites(
    owner, signed, damage
):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    refresh(owner, signed)
    if damage in {"changed_artifact", "missing_artifact"}:
        identity = signed["preparation"]["expected_artifact_ids"][-1]
        signed["observed_artifact_sha256s"][identity] = (
            "0" * 64 if damage == "changed_artifact" else None
        )
    else:
        kind, pin = next(
            (kind, pin)
            for artifact in signed["manifest"]["artifacts"]
            for kind, pins in artifact["dependency_pins"].items()
            for pin in pins
        )
        signed["observed_pins"][kind][pin["key"]] = "0" * 64
    result = assess(owner, signed)
    assert result["authenticated_evidence_count"] == 2
    assert result["review_prerequisites_satisfied_under_selected_trust"] is False
    assert "required_dependency_closure_not_current" in result["blockers"]


@pytest.mark.parametrize(
    "domain", ["claim", "action", "audience", "policy_action", "policy_audience"]
)
def test_old_canonical_graph_review_domain_cannot_be_reused_for_native_typed_definitions(
    owner, signed, domain
):
    if domain == "claim":
        signed["reviews"][0]["schema"] = graph_review.CLAIM_SCHEMA
    elif domain == "action":
        signed["reviews"][0]["action"] = graph_review.ACTION
    elif domain == "audience":
        signed["reviews"][0]["audience"] = graph_review.AUDIENCE
    elif domain == "policy_action":
        signed["policy"]["action"] = graph_review.ACTION
    else:
        signed["policy"]["audience"] = graph_review.AUDIENCE
    refresh(owner, signed)
    with pytest.raises(ValueError):
        assess(owner, signed)


@pytest.mark.parametrize(
    "damage,blocker",
    [
        ("signature", "signature_invalid"),
        ("role", "unauthorized_review_role"),
        ("scope", "unauthorized_legal_scope"),
        ("key_revoked", "key_revoked"),
        ("principal_revoked", "principal_revoked"),
        ("key_expired", "key_not_current_for_review_interval"),
        ("review_expired", "review_not_current"),
        ("future_review", "review_not_current"),
        ("stale_review", "review_age_exceeded"),
        ("registry_expired", "registry_not_current"),
        ("policy_expired", "policy_not_current"),
    ],
)
def test_signature_roles_scope_revocations_and_explicit_time_windows_are_enforced(
    owner, signed, damage, blocker
):
    key = signed["registry"]["keys"][0]
    if damage == "signature":
        signed["reviews"][0]["interpretation"]["rationale"] += " unsigned alteration"
    else:
        if damage == "role":
            key["roles"] = ["formal_review"]
        elif damage == "scope":
            key["scope_ids"] = ["foreign-scope"]
        elif damage == "key_revoked":
            key["revoked_at_utc"] = NOW
        elif damage == "principal_revoked":
            signed["registry"]["revoked_principals"] = [
                {"principal_id": key["principal_id"], "revoked_at_utc": NOW}
            ]
        elif damage == "key_expired":
            key["valid_until_utc"] = NOW
        elif damage == "review_expired":
            signed["reviews"][0]["expires_at_utc"] = NOW
        elif damage == "future_review":
            signed["reviews"][0]["issued_at_utc"] = "2026-10-14T04:00:00Z"
        elif damage == "stale_review":
            signed["policy"]["max_review_age_seconds"] = 10
        elif damage == "registry_expired":
            signed["registry"]["valid_until_utc"] = NOW
        elif damage == "policy_expired":
            signed["policy"]["valid_until_utc"] = NOW
        refresh(owner, signed)
    result = assess(owner, signed)
    assert blocker in result["reviews"][0]["blockers"]
    assert result["reviews"][0]["status"] == "rejected"
    assert result["accepted_view_eligible"] is False


@pytest.mark.parametrize(
    "authority,boundary",
    [
        ("registry", "issuance"),
        ("registry", "expiry"),
        ("policy", "issuance"),
        ("policy", "expiry"),
    ],
)
def test_the_complete_signed_interval_must_fit_selected_registry_and_policy_authority(
    owner, signed, authority, boundary
):
    if boundary == "issuance":
        signed[authority]["valid_from_utc"] = "2026-10-14T02:30:00Z"
    else:
        signed[authority]["valid_until_utc"] = "2026-10-15T01:00:00Z"
    refresh(owner, signed)
    result = assess(owner, signed)
    assert result["reviews"][0]["signature_status"] == "valid"
    assert result["reviews"][0]["status"] == "rejected"
    assert authority + "_not_current_for_review_interval" in result["reviews"][0]["blockers"]


def test_same_principal_under_two_keys_cannot_supply_distinct_review_roles(owner, signed):
    signed["registry"]["keys"][1]["principal_id"] = signed["registry"]["keys"][0]["principal_id"]
    signed["reviews"][1]["principal_id"] = signed["registry"]["keys"][0]["principal_id"]
    refresh(owner, signed)
    result = assess(owner, signed)
    assert result["authenticated_evidence_count"] == 2
    assert "distinct_authorized_review_principals_missing" in result["blockers"]


def test_duplicate_key_material_is_refused_and_unknown_key_has_no_authentication(owner, signed):
    signed["reviews"][0]["key_id"] = "fixture:unknown-key"
    refresh(owner, signed)
    result = assess(owner, signed)
    assert "unknown_authorized_key" in result["reviews"][0]["blockers"]
    assert result["reviews"][0]["status"] == "rejected"
    signed["registry"]["keys"][1]["public_key_hex"] = signed["registry"]["keys"][0][
        "public_key_hex"
    ]
    refresh(owner, signed)
    with pytest.raises(ValueError):
        assess(owner, signed)


@pytest.mark.parametrize(
    "damage",
    ["omit_slot", "open_slot", "no_evidence", "changed_evidence", "unresolved", "disagreement"],
)
def test_all_78_signed_context_slots_require_current_exact_evidence_and_agreement(
    owner, signed, damage
):
    closure = signed["reviews"][0]["context_closure"]
    if damage == "omit_slot":
        closure["obligations"].pop()
    elif damage == "open_slot":
        closure["obligations"][-1]["disposition"] = "open"
    elif damage == "no_evidence":
        closure["obligations"][-1]["evidence_refs"] = []
    elif damage == "changed_evidence":
        signed["evidence"]["fixture:typed-context"] += b" changed bytes"
    elif damage == "unresolved":
        closure["unresolved"] = ["An unreviewed external definition remains open."]
    else:
        closure["obligations"][-1]["disposition"] = "resolved_by_evidence"
    refresh(owner, signed)
    result = assess(owner, signed)
    assert result["authenticated_evidence_count"] == 2
    assert result["review_prerequisites_satisfied_under_selected_trust"] is False
    assert result["context_closure_verified"] is False
    if damage == "disagreement":
        assert "authenticated_context_declarations_disagree" in result["blockers"]
    else:
        assert "authenticated_complete_context_declarations_missing" in result["blockers"]


@pytest.mark.parametrize(
    "damage", ["review_removed", "review_reordered", "registry_substituted", "policy_substituted"]
)
def test_complete_external_review_population_registry_and_policy_pins_prevent_substitution(
    owner, signed, damage
):
    args, kwargs = assessment_arguments(signed)
    if damage == "review_removed":
        signed["reviews"].pop()
    elif damage == "review_reordered":
        signed["reviews"].reverse()
    elif damage == "registry_substituted":
        signed["registry"]["generation"] += 1
    else:
        signed["policy"]["policy_id"] = "fixture:substituted-policy"
    with pytest.raises(ValueError):
        owner.assess_definition_reviews(*args, **kwargs)


@pytest.mark.parametrize("damage", ["reject", "ambiguity"])
def test_authenticated_review_conflict_or_ambiguity_never_qualifies_meaning(owner, signed, damage):
    if damage == "reject":
        signed["reviews"][1]["interpretation"]["decision"] = "reject"
    else:
        signed["reviews"][1]["interpretation"]["ambiguity"] = ["Competing declared interpretation."]
    refresh(owner, signed)
    result = assess(owner, signed)
    assert result["authenticated_evidence_count"] == 2
    assert "authenticated_review_conflict_or_ambiguity" in result["blockers"]
    assert result["accepted_view_eligible"] is False


def test_unavailable_trust_and_no_reviews_remain_pending_without_invented_signers(owner, signed):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "unavailable"
    signed["registry"]["keys"] = []
    signed["reviews"] = []
    refresh(owner, signed)
    result = assess(owner, signed)
    assert result["evidence_assessment_status"] == "pending"
    assert result["authenticated_evidence_count"] == 0
    assert "trust_registry_unavailable" in result["blockers"]
    assert result["review_prerequisites_satisfied_under_selected_trust"] is False
    assert all(result[field] is False for field in graph_review.FALSE_AUTHORITY)


@pytest.mark.parametrize(
    "damage",
    [
        "companion",
        "AST",
        "source_binding",
        "context_digest",
        "artifacts",
        "producer",
        "authority",
    ],
)
def test_repaired_preparation_seal_cannot_substitute_original_complete_evidence(
    owner, signed, damage
):
    changed = deepcopy(signed["preparation"])
    if damage == "companion":
        changed["companion_cids"]["definition_record"] = changed["companion_cids"]["norm_record"]
    elif damage == "AST":
        changed["native_ast"]["left"]["formula"]["operator"]["value"] = "→"
    elif damage == "source_binding":
        changed["source_bindings"][0]["source_occurrence_cid"] = changed["source_occurrences"][-1][
            "record_cid"
        ]
    elif damage == "context_digest":
        changed["contexts"][0]["packet_canonical_sha256"] = "0" * 64
    elif damage == "artifacts":
        changed["artifacts"].pop()
    elif damage == "producer":
        changed["producer_pins"][next(iter(changed["producer_pins"]))] = "0" * 64
    else:
        changed["admitted"] = True
    with pytest.raises(contracts.CorpusContractError):
        owner.validate_definition_review_evidence(reseal(changed), **signed["arguments"])


@pytest.mark.parametrize("damage", ["accepted", "blockers", "semantic", "authenticated_count"])
def test_rehashed_assessment_cannot_promote_authority_or_drop_observed_blockers(
    owner, signed, damage
):
    report = assess(owner, signed)
    if damage == "accepted":
        report["accepted_view_eligible"] = True
    elif damage == "blockers":
        report["blockers"] = []
    elif damage == "semantic":
        report["source_semantics_verified"] = True
    else:
        report["authenticated_evidence_count"] = 3
    report["assessment_sha256"] = graph_review.digest(
        {key: value for key, value in report.items() if key != "assessment_sha256"}
    )
    args, kwargs = assessment_arguments(signed)
    with pytest.raises(contracts.CorpusContractError):
        owner.validate_definition_review_assessment(report, *args, **kwargs)


@pytest.mark.parametrize(
    "damage", ["signature_shape", "signed_unknown_field", "unknown_role", "duplicate_review"]
)
def test_closed_signed_claim_schema_and_review_identity_population_are_enforced(
    owner, signed, damage
):
    if damage == "signature_shape":
        signed["reviews"][0]["signature"] = "not-an-ed25519-signature"
    elif damage == "signed_unknown_field":
        signed["reviews"][0]["legal_truth_verified"] = True
        refresh(owner, signed)
    elif damage == "unknown_role":
        signed["reviews"][0]["role"] = "human_semantic_oracle"
        refresh(owner, signed)
    else:
        signed["reviews"][1]["review_id"] = signed["reviews"][0]["review_id"]
        refresh(owner, signed)
    with pytest.raises(ValueError):
        assess(owner, signed)


def test_native_78_slot_protocol_does_not_widen_old_graph_domain_or_32_obligation_cap(
    owner, signed
):
    args, kwargs = assessment_arguments(signed)
    for field in signed["arguments"]:
        kwargs.pop(field)
    with pytest.raises(ValueError):
        graph_review.assess_graph_reviews(*args, **kwargs)
    old_claim = deepcopy(signed["reviews"][0])
    old_claim.update(
        schema=graph_review.CLAIM_SCHEMA, action=graph_review.ACTION, audience=graph_review.AUDIENCE
    )
    with pytest.raises(ValueError, match="bounded signed context declaration"):
        graph_review._review(old_claim, signed["subject"])
    assert graph_review._GRAPH_DOMAIN.context_obligation_cap == 32
    assert len(signed["subject"]["context_slot_ids"]) == 78


@pytest.mark.parametrize("bound", ["occurrences", "slots", "aggregate_bytes"])
def test_population_and_byte_limits_refuse_whole_evidence_instead_of_dropping_origins(
    owner, monkeypatch, bound
):
    case = candidate()
    rows, expected = context_inputs(case)
    if bound == "occurrences":
        monkeypatch.setattr(owner, "MAX_CONTEXT_OCCURRENCES", len(rows) - 1)
    elif bound == "slots":
        monkeypatch.setattr(owner, "MAX_CONTEXT_OBLIGATIONS", len(rows) * 6 - 1)
    else:
        monkeypatch.setattr(
            owner,
            "MAX_INPUT_BYTES",
            sum(map(len, case[0].values())) + sum(len(row["packet_raw"]) for row in rows) - 1,
        )
    with pytest.raises(contracts.CorpusContractError):
        prepare(owner, case, rows, expected)


def test_signature_backend_unavailable_is_pending_without_invented_authentication(
    owner, signed, monkeypatch
):
    monkeypatch.setattr(graph_review, "_verify_signature", lambda *_: "backend_unavailable")
    result = assess(owner, signed)
    assert result["evidence_assessment_status"] == "pending"
    assert result["authenticated_evidence_count"] == 0
    assert all(row["status"] == "pending" for row in result["reviews"])
    assert result["accepted_view_eligible"] is False


def test_assessment_output_is_detached_from_mutable_caller_inputs(owner, signed):
    result = assess(owner, signed)
    original = deepcopy(result)
    signed["reviews"][0]["interpretation"]["ambiguity"].append("later caller mutation")
    signed["registry"]["keys"][0]["roles"].clear()
    signed["evidence"].clear()
    signed["subject"]["native_binding"]["source_bindings"].clear()
    assert result == original


def test_actual_public_module_import_is_inert_and_uses_repository_package():
    program = """
import json, sys
from ipfs_datasets_py.logic.autoformal import corpus_definition_review
blocked = [name for name in sys.modules if name in {"torch", "transformers", "pyarrow"}
    or name.endswith("legal_graph_review") or name.endswith("legal_statutory_context")
    or name.endswith("legal_source_definition_norm_bridge") or name.endswith("canonical_compiler")
    or name.endswith("backends.process") or name.endswith("profile_g")]
assert not blocked, blocked
print(json.dumps(corpus_definition_review.__file__))
"""
    env = dict(os.environ, IPFS_DATASETS_PY_MINIMAL_IMPORTS="1")
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=True, env=env
    )
    expected = (
        Path(__file__).resolve().parents[4]
        / "ipfs_datasets_py/logic/autoformal/corpus_definition_review.py"
    )
    assert Path(json.loads(result.stdout)).resolve() == expected


def test_actual_signature_owner_is_source_pinned_and_native_metadata_does_not_promote_authority(
    owner, signed
):
    from ipfs_datasets_py.logic import profile_g

    path = Path(profile_g.__file__).resolve()
    prep = signed["preparation"]
    assert prep["producer_pins"][str(path)] == sha(path.read_bytes())
    root_pins = signed["manifest"]["artifacts"][0]["dependency_pins"]["policy"]
    assert {"key": "review-producer:" + str(path), "sha256": sha(path.read_bytes())} in root_pins
    result = assess(owner, signed)
    assert result["signature_owner_source_pinned"] is True
    assert result["cryptographic_distribution_authenticated"] is False
    assert result["candidate_cid"] == signed["case"][1]["candidate_cid"]
    assert result["preparation_cid"] == prep["record_cid"]
    assert result["native_profile"] == prep["profile"]
    assert result["native_family"] == prep["family"]
    assert result["candidate_sha256"] == signed["case"][1]["candidate_sha256"]
    assert result["graph_cid"] == signed["case"][1]["graph_cid"]
    for field in ("source_version", "definition_record", "norm_record", "ast_record"):
        assert result[field + "_cid"] == prep["companion_cids"][field]
    assert result["original_input_sha256s"] == {
        field: signed["case"][1][field]
        for field in (
            "candidate_sha256",
            "request_sha256",
            "report_sha256",
            "raw_sha256",
            "extracted_sha256",
        )
    }
    assert result["context_population_sha256"] == sha(
        canonical_dag_json_bytes(prep["expected_context_population"])
    )
    assert all(result[field] is False for field in owner.FALSE_FLAGS)


def test_source_pin_drift_during_actual_signature_verification_refuses_the_operation(
    owner, signed, monkeypatch
):
    original_verify, original_pins = graph_review._verify_signature, owner._pins
    verified = False

    def verify(review, key):
        nonlocal verified
        result = original_verify(review, key)
        assert result == "valid"
        verified = True
        return result

    def pins(owners):
        result = original_pins(owners)
        if verified:
            profile_path = next(path for path in result if path.endswith("/logic/profile_g.py"))
            result[profile_path] = "0" * 64
        return result

    monkeypatch.setattr(graph_review, "_verify_signature", verify)
    monkeypatch.setattr(owner, "_pins", pins)
    with pytest.raises(contracts.CorpusContractError):
        assess(owner, signed)
    assert verified


def test_fully_valid_new_edition_population_cannot_reuse_prior_edition_signed_reviews(
    owner, signed
):
    old_scope = signed["subject"]["scope_id"]
    old_source_version = signed["preparation"]["source_version"]["record_cid"]
    old_raw_sha = signed["case"][1]["raw_sha256"]
    replacement = materialize(owner, candidate(edition=2025))
    signed.update(replacement)
    signed.update(observations(signed["manifest"]))
    assert signed["subject"]["scope_id"] != old_scope
    assert signed["preparation"]["source_version"]["record_cid"] != old_source_version
    assert signed["case"][1]["raw_sha256"] == old_raw_sha
    result = assess(owner, signed)
    assert all(row["signature_status"] == "valid" for row in result["reviews"])
    assert result["authenticated_evidence_count"] == 0
    assert all("signed_subject_differs" in row["blockers"] for row in result["reviews"])
    assert result["accepted_view_eligible"] is False

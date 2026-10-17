"""Synthetic V2 review signatures verify custody, never statutory meaning."""

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
from ipfs_datasets_py.logic.autoformal import corpus_definition_adapter_v2 as adapter
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_graph_review as signatures
from ipfs_datasets_py.logic.profile_g import Ed25519Signer
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

_SPEC = importlib.util.spec_from_file_location(
    "authored_v2_definition_source_for_review",
    Path(__file__).with_name("test_corpus_definition_adapter_v2.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)

NOW = "2026-10-15T12:00:00Z"
ISSUED = "2026-10-15T11:00:00Z"
EXPIRES = "2026-10-16T11:00:00Z"
START = "2026-10-01T00:00:00Z"
END = "2026-11-01T00:00:00Z"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    # Intentionally distinct from the canonical FULL hash namespaces.
    return json.dumps(
        value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
    ).encode()


def reseal(record):
    return contracts.seal_record(
        {k: v for k, v in record.items() if k not in {"record_cid", "cid_scope"}}
    )


def candidate(family="fol"):
    report_raw, replay = _FIXTURE.inputs(family)
    record = adapter.adapt_definition_only_bytes_v2(report_raw, **replay)
    raw = canonical_dag_json_bytes(record)
    sampling_raw = wire(replay["sampling_report"])
    descriptor_raw = wire(replay["descriptor"])
    inputs = {
        "candidate_raw": raw,
        "report_raw": report_raw,
        "request_raw": replay["request_raw"],
        "raw_html": replay["raw_html"],
        "sampling_report_raw": sampling_raw,
        "descriptor_raw": descriptor_raw,
    }
    pins = {
        "candidate_sha256": sha(raw),
        "candidate_cid": record["record_cid"],
        "graph_cid": record["graph"]["record_cid"],
        "request_sha256": sha(inputs["request_raw"]),
        "report_sha256": sha(report_raw),
        "raw_sha256": replay["expected_raw_sha256"],
        "raw_bytes": replay["expected_raw_bytes"],
        "extracted_sha256": record["source_version"]["extracted_view"]["sha256"],
        "sampling_report_sha256": sha(sampling_raw),
        "sampling_report_full_canonical_sha256": replay[
            "expected_sampling_report_sha256"
        ],
        "descriptor_sha256": sha(descriptor_raw),
        "descriptor_full_canonical_sha256": replay["expected_descriptor_sha256"],
    }
    return {"inputs": inputs, "pins": pins, "record": record, "replay": replay}


def contexts(case):
    from ipfs_datasets_py.logic.autoformal import legal_statutory_context_v2 as owner

    replay = case["replay"]
    sampling = replay["sampling_report"]
    trusted = {
        k: replay[k]
        for k in (
            "descriptor",
            "expected_descriptor_sha256",
            "expected_raw_sha256",
            "expected_raw_bytes",
        )
    }
    if "view_limits" in replay:
        trusted["limits"] = replay["view_limits"]
    packets, population = [], []
    for occurrence in case["record"]["source_occurrences"]:
        packet = owner.build_context_packet_v2(
            sampling["document_view_report"],
            case["inputs"]["raw_html"],
            char_start=occurrence["start_char"],
            char_end=occurrence["end_char"],
            expected_report_sha256=sampling["document_view_report_sha256"],
            **trusted,
        )
        raw = wire(packet)
        packets.append(
            {
                "source_occurrence_cid": occurrence["record_cid"],
                "packet_raw": raw,
                "dependency_requests": None,
            }
        )
        population.append(
            {
                "source_occurrence_cid": occurrence["record_cid"],
                "packet_sha256": sha(raw),
            }
        )
    return packets, population


def arguments(case, packets=None, population=None):
    if packets is None:
        packets, population = contexts(case)
    return {
        "candidate_inputs": case["inputs"],
        "expected_candidate_pin": case["pins"],
        "context_inputs": packets,
        "expected_context_population": population,
    }


def materialize(owner, case):
    args = arguments(case)
    preparation = owner.prepare_definition_review_evidence_v2(**args)
    manifest = dependencies.build_dependency_manifest(
        preparation["artifacts"],
        preparation["edges"],
        expected_artifact_ids=preparation["expected_artifact_ids"],
    )
    subject = owner.build_definition_review_subject_v2(
        preparation,
        manifest,
        **args,
        expected_manifest_sha256=manifest["manifest_sha256"],
        required_dependency_ids=preparation["expected_artifact_ids"],
    )
    return {
        "case": case,
        "arguments": args,
        "preparation": preparation,
        "manifest": manifest,
        "subject": subject,
    }


def observations(manifest):
    observed = {kind: {} for kind in dependencies.PIN_KINDS}
    for artifact in manifest["artifacts"]:
        for kind, pins in artifact["dependency_pins"].items():
            observed[kind].update({pin["key"]: pin["sha256"] for pin in pins})
    return {
        "observed_artifact_sha256s": {
            row["artifact_id"]: row["artifact_sha256"] for row in manifest["artifacts"]
        },
        "observed_pins": observed,
    }


def refresh(case):
    case["policy"]["registry_sha256"] = signatures.digest(case["registry"])
    for index, claim in enumerate(case["reviews"]):
        body = {
            k: deepcopy(v)
            for k, v in claim.items()
            if k not in {"signer_did", "signature_alg", "signature"}
        }
        body["registry_sha256"] = signatures.digest(case["registry"])
        body["policy_sha256"] = signatures.digest(case["policy"])
        case["reviews"][index] = case["signers"][index].sign(body)


@pytest.fixture(scope="module")
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2

    return corpus_definition_review_v2


@pytest.fixture(scope="module")
def base_candidate():
    return candidate()


@pytest.fixture
def case(base_candidate):
    return deepcopy(base_candidate)


@pytest.fixture(scope="module")
def base_materialized(owner, base_candidate):
    return materialize(owner, base_candidate)


@pytest.fixture
def signed(owner, base_materialized):
    data = deepcopy(base_materialized)
    subject = data["subject"]
    roles = list(signatures.ROLES)
    signers = [
        Ed25519Signer.generate("did:example:v2-definition-legal-fixture"),
        Ed25519Signer.generate("did:example:v2-definition-formal-fixture"),
    ]
    keys = [
        {
            "key_id": "fixture:v2-key:" + str(index),
            "signer_did": signer.did,
            "public_key_hex": signer.public_key.public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            ).hex(),
            "principal_id": "fixture:v2-principal:" + str(index),
            "roles": [role],
            "scope_ids": [subject["scope_id"]],
            "valid_from_utc": START,
            "valid_until_utc": END,
            "revoked_at_utc": None,
        }
        for index, (signer, role) in enumerate(zip(signers, roles, strict=True))
    ]
    registry = {
        "schema": signatures.REGISTRY_SCHEMA,
        "mode": "synthetic_fixture",
        "process_id": "fixture:v2-review-process",
        "generation": 1,
        "revocation_generation": 1,
        "valid_from_utc": START,
        "valid_until_utc": END,
        "keys": keys,
        "revoked_principals": [],
    }
    policy = {
        "schema": signatures.POLICY_SCHEMA,
        "mode": "synthetic_fixture",
        "policy_id": "fixture:v2-review-policy",
        "process_id": registry["process_id"],
        "registry_sha256": signatures.digest(registry),
        "action": owner.ACTION,
        "audience": owner.AUDIENCE,
        "required_roles": roles,
        "valid_from_utc": START,
        "valid_until_utc": END,
        "max_review_age_seconds": 86400,
    }
    evidence = {
        "fixture:v2-context": b"Synthetic context dispositions; no actual legal or human review."
    }
    closure = {
        "status": "declared_complete",
        "obligations": [
            {
                "slot_id": slot,
                "disposition": "not_applicable",
                "evidence_refs": [
                    {
                        "artifact_id": "fixture:v2-context",
                        "sha256": sha(evidence["fixture:v2-context"]),
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
                "review_id": "fixture:v2-review:" + str(index),
                "key_id": keys[index]["key_id"],
                "principal_id": keys[index]["principal_id"],
                "role": role,
                "registry_sha256": signatures.digest(registry),
                "policy_sha256": signatures.digest(policy),
                "issued_at_utc": ISSUED,
                "expires_at_utc": EXPIRES,
                "subject": deepcopy(subject),
                "interpretation": {
                    "decision": "support",
                    "reviewed_graph_sha256": subject["graph_sha256"],
                    "reviewed_ast_sha256": subject["ast_sha256"],
                    "rationale": "Fixture-only verification of exact signed bytes.",
                    "ambiguity": [],
                },
                "context_closure": deepcopy(closure),
            }
        )
        for index, (signer, role) in enumerate(zip(signers, roles, strict=True))
    ]
    data.update(
        registry=registry,
        policy=policy,
        reviews=reviews,
        signers=signers,
        evidence=evidence,
        **observations(data["manifest"]),
    )
    return data


def assessment_arguments(data):
    return (
        data["subject"],
        data["registry"],
        data["policy"],
        data["reviews"],
        data["manifest"],
    ), {
        **data["arguments"],
        "expected_subject_sha256": signatures.digest(data["subject"]),
        "expected_registry_sha256": signatures.digest(data["registry"]),
        "expected_policy_sha256": signatures.digest(data["policy"]),
        "expected_reviews_sha256": signatures.digest(data["reviews"]),
        "expected_manifest_sha256": data["manifest"]["manifest_sha256"],
        "at_time_utc": NOW,
        "observed_artifact_sha256s": data["observed_artifact_sha256s"],
        "observed_pins": data["observed_pins"],
        "evidence_artifacts": data["evidence"],
    }


def assess(owner, data):
    args, kwargs = assessment_arguments(data)
    return owner.assess_definition_reviews_v2(*args, **kwargs)


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_complete_v2_subject_retains_all_physical_contexts_without_norm(owner, family):
    data = materialize(owner, candidate(family))
    preparation, subject = data["preparation"], data["subject"]
    record = data["case"]["record"]
    assert preparation["family"] == family
    assert preparation["native_ast"] == record["ast_record"]["native_ast"]
    assert preparation["graph_sha256"] == sha(canonical_dag_json_bytes(record["graph"]))
    assert preparation["ast_sha256"] == sha(
        canonical_dag_json_bytes(preparation["native_ast"])
    )
    assert len(record["source_occurrences"]) == 7
    slots = [
        slot["slot_id"]
        for row in data["arguments"]["context_inputs"]
        for slot in json.loads(row["packet_raw"])["dependency_slots"]
    ]
    assert len(slots) == len(set(slots)) == 42
    assert subject["context_slot_ids"] == slots
    assert subject["scope_id"] == record["scope_record"]["record_cid"]
    assert subject["required_dependency_ids"] == preparation["expected_artifact_ids"]
    assert subject["native_binding"] == preparation
    assert "norm_record" not in preparation["companion_cids"]
    assert "norm_native_ast" not in preparation
    assert all(preparation[k] is False for k in owner.FALSE_FLAGS)
    owner.validate_definition_review_evidence_v2(preparation, **data["arguments"])


def test_original_lowered_view_sampler_and_compiler_limits_replay_through_review(
    owner, case
):
    from ipfs_datasets_py.logic.autoformal import (
        legal_source_definition_bridge_v2 as compiler,
    )
    from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler

    replay = case["replay"]
    source = {
        key: replay[key]
        for key in (
            "descriptor",
            "expected_descriptor_sha256",
            "expected_raw_sha256",
            "expected_raw_bytes",
        )
    }
    view_limits = {"max_blocks": 12, "max_report_bytes": 1024 * 1024}
    sampling_limits = {"max_units": 16, "max_report_bytes": 2 * 1024 * 1024}
    compiler_limits = {
        "max_occurrences": 32,
        "max_bindings": 64,
        "max_contributors": 16,
        "max_report_bytes": 512 * 1024,
        "max_literal_bytes": 2048,
        "max_expression_depth": 8,
        "max_expression_nodes": 32,
        "max_operands": 8,
        "max_sampling_report_bytes": 2 * 1024 * 1024,
        "max_input_bytes": 4 * 1024 * 1024,
    }
    sampling = sampler.prepare_source_sampling(
        replay["raw_html"],
        **source,
        view_limits=view_limits,
        limits=sampling_limits,
    )
    replay.update(
        sampling_report=sampling,
        expected_sampling_report_sha256=sampler.source_sampling_report_sha256(sampling),
        view_limits=view_limits,
        sampling_limits=sampling_limits,
        limits=compiler_limits,
    )
    request = json.loads(replay["request_raw"])
    report = compiler.prepare_definition_v2(
        request,
        **{
            key: value
            for key, value in replay.items()
            if key
            not in {"request_raw", "expected_request_sha256", "expected_report_sha256"}
        },
    )
    report_raw = wire(report)
    replay["expected_report_sha256"] = sha(report_raw)
    record = adapter.adapt_definition_only_bytes_v2(report_raw, **replay)
    candidate_raw = canonical_dag_json_bytes(record)
    sampling_raw = wire(sampling)
    case["record"] = record
    case["inputs"].update(
        candidate_raw=candidate_raw,
        report_raw=report_raw,
        sampling_report_raw=sampling_raw,
    )
    case["pins"].update(
        candidate_sha256=sha(candidate_raw),
        candidate_cid=record["record_cid"],
        graph_cid=record["graph"]["record_cid"],
        report_sha256=sha(report_raw),
        sampling_report_sha256=sha(sampling_raw),
        sampling_report_full_canonical_sha256=sampler.source_sampling_report_sha256(
            sampling
        ),
    )
    assert all(report["limits"][key] == value for key, value in compiler_limits.items())
    assert sampling["limits"] == sampling_limits
    assert all(
        sampling["document_view_report"]["limits"][key] == value
        for key, value in view_limits.items()
    )
    data = materialize(owner, case)
    assert data["subject"]["native_binding"] == data["preparation"]
    assert len(data["subject"]["context_slot_ids"]) == 42
    owner.validate_definition_review_evidence_v2(
        data["preparation"], **data["arguments"]
    )


def test_real_synthetic_signatures_authenticate_new_domain_but_never_meaning(
    owner, signed
):
    result = assess(owner, signed)
    assert result["schema"] == owner.SCHEMA
    assert result["evidence_assessment_status"] == "authenticated"
    assert result["authenticated_evidence_count"] == 2
    assert all(row["signed_context_declaration_complete"] for row in result["reviews"])
    assert "production_trust_registry_unavailable" in result["blockers"]
    assert result["accepted_view_eligible"] is False
    assert all(result[k] is False for k in signatures.FALSE_AUTHORITY)
    args, kwargs = assessment_arguments(signed)
    assert (
        owner.validate_definition_review_assessment_v2(result, *args, **kwargs)
        == result
    )


def test_external_policy_wire_shape_still_has_no_human_or_semantic_authority(
    owner, signed
):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    refresh(signed)
    result = assess(owner, signed)
    assert result["review_prerequisites_satisfied_under_selected_trust"] is True
    assert result["accepted_view_eligible"] is False
    assert all(result[k] is False for k in signatures.FALSE_AUTHORITY)
    assert set(result["blockers"]) == {
        "downstream_Lean_kernel_admission_required",
        "downstream_semantic_validation_required",
    }


@pytest.mark.parametrize(
    "field",
    [
        "candidate_sha256",
        "candidate_cid",
        "graph_cid",
        "request_sha256",
        "report_sha256",
        "raw_sha256",
        "raw_bytes",
        "extracted_sha256",
        "sampling_report_sha256",
        "sampling_report_full_canonical_sha256",
        "descriptor_sha256",
        "descriptor_full_canonical_sha256",
    ],
)
def test_every_independent_original_input_namespace_is_required(owner, case, field):
    if field.endswith("_cid"):
        case["pins"][field] = contracts.seal_record({"schema": "unrelated/v1"})[
            "record_cid"
        ]
    else:
        case["pins"][field] = (
            case["pins"][field] + 1 if field == "raw_bytes" else "0" * 64
        )
    with pytest.raises(ValueError):
        owner.prepare_definition_review_evidence_v2(**arguments(case))


@pytest.mark.parametrize("damage", ["omit", "reverse", "duplicate", "unknown_field"])
def test_context_population_has_exact_order_membership_and_closed_inputs(
    owner, case, damage
):
    packets, population = contexts(case)
    if damage == "omit":
        packets.pop()
        population.pop()
    elif damage == "reverse":
        packets.reverse()
        population.reverse()
    elif damage == "duplicate":
        packets[-1] = deepcopy(packets[0])
        population[-1] = deepcopy(population[0])
    else:
        packets[0]["reviewed"] = True
    with pytest.raises(ValueError):
        owner.prepare_definition_review_evidence_v2(
            **arguments(case, packets, population)
        )


@pytest.mark.parametrize("damage", ["UTF8", "omit_slot", "false_closure", "wrong_view"])
def test_rehashed_context_cannot_retarget_geometry_or_close_source_obligations(
    owner, case, damage
):
    packets, population = contexts(case)
    packet = json.loads(packets[0]["packet_raw"])
    if damage == "UTF8":
        packet["selection"]["utf8_byte_start"] += 1
    elif damage == "omit_slot":
        packet["dependency_slots"].pop()
    elif damage == "false_closure":
        packet["context_closure_verified"] = True
    else:
        packet["selection"]["view_id"] = "legal-official-markup-view:sha256:" + "0" * 64
    body = {k: v for k, v in packet.items() if k != "packet_id"}
    prefix = packet["packet_id"].rsplit(":", 1)[0] + ":"
    packet["packet_id"] = prefix + sha(canonical_dag_json_bytes(body))
    packets[0]["packet_raw"] = wire(packet)
    population[0]["packet_sha256"] = sha(packets[0]["packet_raw"])
    with pytest.raises(ValueError):
        owner.prepare_definition_review_evidence_v2(
            **arguments(case, packets, population)
        )


@pytest.mark.parametrize(
    "damage", ["AST", "scope", "source_geometry", "context_population"]
)
def test_resealed_candidate_still_requires_original_v2_source_and_declared_ast(
    owner, case, damage
):
    record = case["record"]
    if damage == "AST":
        record["ast_record"]["native_ast"]["formula"]["operator"]["value"] = "→"
        record["ast_record"] = reseal(record["ast_record"])
    elif damage == "scope":
        record["scope_record"]["declared_applicability"][
            "instrument_id"
        ] = "foreign-instrument"
        record["scope_record"] = reseal(record["scope_record"])
    elif damage == "source_geometry":
        record["source_occurrences"][0]["start_utf8"] += 1
        record["source_occurrences"][0] = reseal(record["source_occurrences"][0])
    else:
        record["context_declarations"].pop()
    record = reseal(record)
    case["inputs"]["candidate_raw"] = canonical_dag_json_bytes(record)
    case["pins"]["candidate_sha256"] = sha(case["inputs"]["candidate_raw"])
    case["pins"]["candidate_cid"] = record["record_cid"]
    # Context transport uses the unchanged source fixture independently.
    packets, population = contexts(case)
    with pytest.raises(ValueError):
        owner.prepare_definition_review_evidence_v2(
            **arguments(case, packets, population)
        )


@pytest.mark.parametrize("damage", ["omit_required", "omit_edge", "wrong_graph_hash"])
def test_subject_requires_exact_complete_source_and_context_dependency_manifest(
    owner, signed, damage
):
    prep = signed["preparation"]
    required = list(prep["expected_artifact_ids"])
    artifacts, edges = deepcopy(prep["artifacts"]), deepcopy(prep["edges"])
    if damage == "omit_required":
        required.pop()
    elif damage == "omit_edge":
        edges.pop()
        required.pop()
    else:
        artifacts[0]["artifact_sha256"] = "0" * 64
    manifest = dependencies.build_dependency_manifest(
        artifacts, edges, expected_artifact_ids=prep["expected_artifact_ids"]
    )
    with pytest.raises(ValueError):
        owner.build_definition_review_subject_v2(
            prep,
            manifest,
            **signed["arguments"],
            expected_manifest_sha256=manifest["manifest_sha256"],
            required_dependency_ids=required,
        )


@pytest.mark.parametrize("field", ["schema", "action", "audience"])
def test_old_definition_plus_norm_signed_domain_cannot_be_relabelled(
    owner, signed, field
):
    from ipfs_datasets_py.logic.autoformal import corpus_definition_review as old

    old_value = {
        "schema": old.CLAIM_SCHEMA,
        "action": old.ACTION,
        "audience": old.AUDIENCE,
    }[field]
    assert old_value != signed["reviews"][0][field]
    signed["reviews"][0][field] = old_value
    refresh(signed)
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
        ("expired_review", "review_not_current"),
    ],
)
def test_existing_auth_engine_rechecks_keys_roles_scope_revocation_and_time(
    owner, signed, damage, blocker
):
    key = signed["registry"]["keys"][0]
    if damage == "signature":
        signed["reviews"][0]["interpretation"]["rationale"] += " unsigned mutation"
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
        else:
            signed["reviews"][0]["expires_at_utc"] = NOW
        refresh(signed)
    result = assess(owner, signed)
    assert blocker in result["reviews"][0]["blockers"]
    assert result["reviews"][0]["status"] == "rejected"
    assert result["accepted_view_eligible"] is False


def test_one_principal_with_two_keys_does_not_supply_independent_roles(owner, signed):
    principal = signed["registry"]["keys"][0]["principal_id"]
    signed["registry"]["keys"][1]["principal_id"] = principal
    signed["reviews"][1]["principal_id"] = principal
    refresh(signed)
    result = assess(owner, signed)
    assert result["authenticated_evidence_count"] == 2
    assert "distinct_authorized_review_principals_missing" in result["blockers"]


def test_missing_complete_signed_context_stays_blocking_even_with_valid_signatures(
    owner, signed
):
    signed["reviews"][0]["context_closure"]["obligations"].pop()
    refresh(signed)
    result = assess(owner, signed)
    assert result["authenticated_evidence_count"] == 2
    assert "authenticated_complete_context_declarations_missing" in result["blockers"]
    assert result["context_closure_verified"] is False


def test_missing_reviews_remain_pending_without_invented_authority(owner, signed):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "unavailable"
    signed["registry"]["keys"] = []
    signed["reviews"] = []
    refresh(signed)
    result = assess(owner, signed)
    assert result["evidence_assessment_status"] == "pending"
    assert result["authenticated_evidence_count"] == 0
    assert "trust_registry_unavailable" in result["blockers"]
    assert all(result[k] is False for k in signatures.FALSE_AUTHORITY)


@pytest.mark.parametrize("damage", ["artifact", "owner_pin"])
def test_current_complete_source_context_and_owner_dependencies_are_rechecked(
    owner, signed, damage
):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    refresh(signed)
    if damage == "artifact":
        signed["observed_artifact_sha256s"][
            signed["preparation"]["expected_artifact_ids"][-1]
        ] = ("0" * 64)
    else:
        kind, item = next(
            (kind, item)
            for artifact in signed["manifest"]["artifacts"]
            for kind, refs in artifact["dependency_pins"].items()
            for item in refs
        )
        signed["observed_pins"][kind][item["key"]] = "0" * 64
    result = assess(owner, signed)
    assert result["authenticated_evidence_count"] == 2
    assert "required_dependency_closure_not_current" in result["blockers"]
    assert not result["review_prerequisites_satisfied_under_selected_trust"]


def test_transport_hash_cannot_replace_full_canonical_source_pin(owner, case):
    assert (
        case["pins"]["sampling_report_sha256"]
        != case["pins"]["sampling_report_full_canonical_sha256"]
    )
    assert (
        case["pins"]["descriptor_sha256"]
        != case["pins"]["descriptor_full_canonical_sha256"]
    )
    case["pins"]["sampling_report_full_canonical_sha256"] = case["pins"][
        "sampling_report_sha256"
    ]
    with pytest.raises(ValueError):
        owner.prepare_definition_review_evidence_v2(**arguments(case))


def test_oversized_original_inputs_refuse_before_owner_import_or_replay(
    owner, case, monkeypatch
):
    def forbidden():
        raise AssertionError(
            "source/authentication owners must not load for an oversized input"
        )

    packets, population = contexts(case)
    monkeypatch.setattr(owner, "_owners", forbidden)
    case["inputs"]["candidate_raw"] = b" " * (contracts.MAX_RECORD_BYTES + 1)
    with pytest.raises(ValueError):
        owner.prepare_definition_review_evidence_v2(
            **arguments(case, packets, population)
        )


def test_resealed_subject_and_resigned_claims_cannot_retarget_exact_context_population(
    owner, signed
):
    signed["subject"]["context_slot_ids"].pop()
    for claim in signed["reviews"]:
        claim["subject"] = deepcopy(signed["subject"])
    refresh(signed)
    with pytest.raises(ValueError):
        assess(owner, signed)


def test_rehashed_assessment_cannot_promote_semantic_or_accepted_authority(
    owner, signed
):
    result = assess(owner, signed)
    result["accepted_view_eligible"] = result["source_semantics_verified"] = True
    result["assessment_sha256"] = signatures.digest(
        {k: v for k, v in result.items() if k != "assessment_sha256"}
    )
    args, kwargs = assessment_arguments(signed)
    with pytest.raises(ValueError):
        owner.validate_definition_review_assessment_v2(result, *args, **kwargs)


def test_import_does_not_load_native_source_context_or_authentication_owners():
    target = "ipfs_datasets_py.logic.autoformal.corpus_definition_review_v2"
    script = """
import importlib,sys
target=sys.argv[1]
module=importlib.import_module(target)
for suffix in ('legal_statutory_context_v2','legal_source_sampling',
               'legal_source_definition_bridge_v2','legal_graph_review',
               'legal_family_routes'):
    assert 'ipfs_datasets_py.logic.autoformal.'+suffix not in sys.modules,suffix
assert callable(module.prepare_definition_review_evidence_v2)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, target],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr

"""Independent source adjudication declarations preserve all prior uncertainty.

All identities, signing keys, source texts and answers here are authored
engineering fixtures. No fixture establishes an actual legal review or law.
"""

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
from ipfs_datasets_py.logic.autoformal import corpus_source_review as source_owner
from ipfs_datasets_py.logic.autoformal import corpus_source_review_responses as response_owner
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust_owner
from ipfs_datasets_py.logic.profile_g import Ed25519Signer
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def helper():
    spec = importlib.util.spec_from_file_location(
        "authored_source_responses_for_adjudication_tests",
        Path(__file__).with_name("test_corpus_source_review_responses.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ref(record):
    return {
        "record_cid": record["record_cid"],
        "sha256": sha(canonical_dag_json_bytes(record)),
        "schema": record["schema"],
    }


def reseal(record):
    return contracts.seal_record(
        {
            key: deepcopy(value)
            for key, value in record.items()
            if key not in {"record_cid", "cid_scope"}
        }
    )


def clone_case(data):
    # Immutable fixture key actors cannot be deep-copied.
    return {
        key: value[:] if key in {"signers", "adjudication_signers"} else deepcopy(value)
        for key, value in data.items()
    }


def refuse_replay(*_args, **_kwargs):
    pytest.fail("Untrusted input reached complete source replay or authentication")


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_source_adjudication

    return corpus_source_adjudication


@pytest.fixture(scope="module")
def fixture_data(tmp_path_factory):
    original = (
        helper()
        .helper()
        .signed_case(source_owner, tmp_path_factory.mktemp("source-adjudication-original-inputs"))
    )
    return helper().signed_typed_case(response_owner, original)


@pytest.fixture(scope="module")
def typed_report(fixture_data):
    return helper().assess(response_owner, fixture_data)


def authority(owner, data, *, mode="synthetic_fixture"):
    """A separately selected synthetic policy with two fresh test principals."""
    source_fixture = helper().helper()
    roles = list(trust_owner.ROLES)
    scopes = list(dict.fromkeys(row["scope_id"] for row in data["preparation"]["subjects"]))
    signers = [
        Ed25519Signer.generate("did:example:source-adjudication-legal"),
        Ed25519Signer.generate("did:example:source-adjudication-formal"),
    ]
    keys = [
        {
            "key_id": f"fixture:adjudication-key:{index}",
            "signer_did": signer.did,
            "public_key_hex": signer.public_key.public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            ).hex(),
            "principal_id": f"fixture:adjudication-principal:{index}",
            "roles": [role],
            "scope_ids": scopes,
            "valid_from_utc": source_fixture.START,
            "valid_until_utc": source_fixture.END,
            "revoked_at_utc": None,
        }
        for index, (signer, role) in enumerate(zip(signers, roles, strict=True))
    ]
    registry = {
        "schema": trust_owner.REGISTRY_SCHEMA,
        "mode": mode,
        "process_id": "fixture:source-adjudication-process",
        "generation": 1,
        "revocation_generation": 1,
        "valid_from_utc": source_fixture.START,
        "valid_until_utc": source_fixture.END,
        "keys": keys,
        "revoked_principals": [],
    }
    policy = {
        "schema": trust_owner.POLICY_SCHEMA,
        "mode": mode,
        "policy_id": "fixture:source-adjudication-policy",
        "process_id": registry["process_id"],
        "registry_sha256": sha(canonical(registry)),
        "action": owner.ACTION,
        "audience": owner.AUDIENCE,
        "required_roles": roles,
        "valid_from_utc": source_fixture.START,
        "valid_until_utc": source_fixture.END,
        "max_review_age_seconds": 86400,
    }
    return registry, policy, signers


DECLARED = "2026-10-14T08:15:00Z"
AUTHORITY_ISSUED = "2026-10-14T08:30:00Z"
EVIDENCE_ID = "fixture:adjudication-reason"
EVIDENCE_BYTES = b"Authored engineering evidence; no actual legal or human review."


def unit(data, ordinal=0):
    report = data["typed_report"]
    request = data["preparation"]["requests"][ordinal]
    subject = data["preparation"]["subjects"][ordinal]
    group = report["records"][ordinal]
    slots_by_cid = {row["record_cid"]: row for row in report["adjudication_requests"]}
    variants_by_cid = {row["record_cid"]: row for row in report["answer_variants"]}
    slots = [slots_by_cid[row["record_cid"]] for row in group["adjudication_refs"]]
    variants = [
        variants_by_cid[row["record_cid"]] for slot in slots for row in slot["answer_variant_refs"]
    ]
    return request, subject, group, slots, variants


def choices(data, ordinal=0, *, select=True):
    return [
        {
            "slot_id": slot["slot_id"],
            "decision": "select_existing_variant"
            if select and slot["answer_variant_refs"]
            else "unresolved",
            "selected_variant_ref": deepcopy(slot["answer_variant_refs"][0])
            if select and slot["answer_variant_refs"]
            else None,
            "rationale": "Explicit authored fixture choice retains every source alternative.",
            "evidence_refs": [{"artifact_id": EVIDENCE_ID, "sha256": sha(EVIDENCE_BYTES)}],
        }
        for slot in unit(data, ordinal)[3]
    ]


def declaration_pins(data, ordinal=0, **options):
    request, subject, group, *_ = unit(data, ordinal)
    return {
        "expected_request_sha256": sha(canonical_dag_json_bytes(request)),
        "expected_subject_sha256": sha(canonical_dag_json_bytes(subject)),
        "expected_typed_group_sha256": sha(canonical_dag_json_bytes(group)),
        "expected_preparation_manifest_sha256": sha(
            canonical_dag_json_bytes(data["preparation"]["manifest"])
        ),
        "expected_typed_response_manifest_sha256": sha(
            canonical_dag_json_bytes(data["typed_report"]["manifest"])
        ),
        "declared_at_utc": DECLARED,
        **options,
    }


def author(owner, data, decisions=None, ordinal=0, **options):
    return owner.record_source_adjudication_declaration(
        *unit(data, ordinal),
        choices(data, ordinal) if decisions is None else decisions,
        **declaration_pins(data, ordinal, **options),
    )


def sign_group(owner, data, body, ordinal=0):
    request, subject, _, _, variants = unit(data, ordinal)
    identity = f"fixture:adjudication-body:{ordinal}"
    raw = canonical_dag_json_bytes(body)
    body_ref = {"artifact_id": identity, "sha256": sha(raw)}
    variants_by_cid = {row["record_cid"]: row for row in variants}
    unresolved = [row["slot_id"] for row in body["decisions"] if row["decision"] == "unresolved"]
    obligations = [
        {
            "slot_id": row["slot_id"],
            "disposition": "open"
            if row["decision"] == "unresolved"
            else response_owner.DISPOSITIONS[
                variants_by_cid[row["selected_variant_ref"]["record_cid"]]["answer"]["disposition"]
            ],
            "evidence_refs": [deepcopy(body_ref)],
        }
        for row in body["decisions"]
    ]
    source_fixture = helper().helper()
    reviews = [
        signer.sign(
            {
                "schema": owner.CLAIM_SCHEMA,
                "action": owner.ACTION,
                "audience": owner.AUDIENCE,
                "review_id": f"fixture:adjudication-review:{ordinal}:{index}",
                "key_id": key["key_id"],
                "principal_id": key["principal_id"],
                "role": role,
                "registry_sha256": sha(canonical(data["adjudication_registry"])),
                "policy_sha256": sha(canonical(data["adjudication_policy"])),
                "issued_at_utc": AUTHORITY_ISSUED,
                "expires_at_utc": source_fixture.EXPIRES,
                "subject": deepcopy(subject),
                "interpretation": {
                    "decision": "support",
                    "reviewed_graph_sha256": subject["graph_sha256"],
                    "reviewed_ast_sha256": subject["ast_sha256"],
                    "rationale": "Support for one exact source declaration, never semantic correctness.",
                    "ambiguity": [],
                },
                "context_closure": {
                    "status": "open" if unresolved else "declared_complete",
                    "unresolved": unresolved[:],
                    "obligations": deepcopy(obligations),
                },
            }
        )
        for index, (signer, key, role) in enumerate(
            zip(
                data["adjudication_signers"],
                data["adjudication_registry"]["keys"],
                trust_owner.ROLES,
                strict=True,
            )
        )
    ]
    return {
        "request_cid": request["record_cid"],
        "reviews": reviews,
        "declaration_artifact_id": identity,
        "evidence_artifacts": {identity: raw, EVIDENCE_ID: EVIDENCE_BYTES},
        "observed_artifact_sha256s": deepcopy(data["groups"][ordinal]["observed_artifact_sha256s"]),
        "observed_pins": deepcopy(data["groups"][ordinal]["observed_pins"]),
    }


def signed_case(owner, original, report, *, mode="synthetic_fixture", select=True):
    data = clone_case(original)
    data["typed_report"] = deepcopy(report)
    data["adjudication_registry"], data["adjudication_policy"], data["adjudication_signers"] = (
        authority(owner, data, mode=mode)
    )
    data["adjudication_groups"] = []
    for ordinal, request in enumerate(data["preparation"]["requests"]):
        if ordinal == 0:
            body = author(owner, data, choices(data, ordinal, select=select), ordinal)
            data["adjudication_groups"].append(sign_group(owner, data, body, ordinal))
        else:
            data["adjudication_groups"].append(
                {
                    "request_cid": request["record_cid"],
                    "reviews": [],
                    "declaration_artifact_id": None,
                    "evidence_artifacts": {},
                    "observed_artifact_sha256s": deepcopy(
                        data["groups"][ordinal]["observed_artifact_sha256s"]
                    ),
                    "observed_pins": deepcopy(data["groups"][ordinal]["observed_pins"]),
                }
            )
    return data


def group_pins(groups):
    return [
        {**pin, "declaration_artifact_id": group["declaration_artifact_id"]}
        for pin, group in zip(helper().helper().group_pins(groups), groups, strict=True)
    ]


def assessment_arguments(data, **options):
    return {
        **helper().assessment_arguments(data),
        "expected_typed_response_manifest_sha256": sha(
            canonical_dag_json_bytes(data["typed_report"]["manifest"])
        ),
        "expected_adjudication_registry_sha256": sha(canonical(data["adjudication_registry"])),
        "expected_adjudication_policy_sha256": sha(canonical(data["adjudication_policy"])),
        "expected_adjudication_group_pins": group_pins(data["adjudication_groups"]),
        **options,
    }


def assess(owner, data, **options):
    return owner.assess_source_adjudications(
        data["preparation"],
        data["registry"],
        data["policy"],
        data["groups"],
        data["typed_report"],
        data["adjudication_registry"],
        data["adjudication_policy"],
        data["adjudication_groups"],
        **assessment_arguments(data, **options),
    )


def validate(owner, report, data, **options):
    return owner.validate_source_adjudications(
        report,
        data["preparation"],
        data["registry"],
        data["policy"],
        data["groups"],
        data["typed_report"],
        data["adjudication_registry"],
        data["adjudication_policy"],
        data["adjudication_groups"],
        **assessment_arguments(data, **options),
    )


def refresh_signatures(data):
    data["adjudication_policy"]["registry_sha256"] = sha(canonical(data["adjudication_registry"]))
    for group in data["adjudication_groups"]:
        for index, review in enumerate(group["reviews"]):
            body = {
                key: deepcopy(value)
                for key, value in review.items()
                if key not in {"signer_did", "signature_alg", "signature"}
            }
            body["registry_sha256"] = sha(canonical(data["adjudication_registry"]))
            body["policy_sha256"] = sha(canonical(data["adjudication_policy"]))
            group["reviews"][index] = data["adjudication_signers"][index].sign(body)


def replace_body(data, body, *, ordinal=0, resign=True):
    group = data["adjudication_groups"][ordinal]
    identity = group["declaration_artifact_id"]
    raw = canonical_dag_json_bytes(body)
    group["evidence_artifacts"][identity] = raw
    if resign:
        for review in group["reviews"]:
            for obligation in review["context_closure"]["obligations"]:
                obligation["evidence_refs"] = [{"artifact_id": identity, "sha256": sha(raw)}]
        refresh_signatures(data)


def assert_no_application(owner, report):
    for component, values in report.items():
        for row in [values] if component == "manifest" else values:
            assert reseal(row) == row
            assert len(canonical_dag_json_bytes(row)) <= contracts.MAX_RECORD_BYTES
            assert row["view"] == "candidate"
            assert row["selected_occurrence"] is row["governing_source_binding"] is None
            for flag in owner.FALSE_FLAGS:
                assert row[flag] is False
    assert report["manifest"]["counts"]["adjudications_applied"] == 0
    assert report["manifest"]["counts"]["source_decisions_applied"] == 0
    assert all(row["original_contexts_remain_required_unavailable"] for row in report["records"])


@pytest.fixture(scope="module")
def baseline_data(fixture_data, typed_report):
    from ipfs_datasets_py.logic.autoformal import corpus_source_adjudication

    return signed_case(corpus_source_adjudication, fixture_data, typed_report)


@pytest.fixture(scope="module")
def baseline_report(baseline_data):
    from ipfs_datasets_py.logic.autoformal import corpus_source_adjudication

    return assess(corpus_source_adjudication, baseline_data)


def test_shared_body_authenticates_two_new_roles_and_preserves_every_original_group(
    owner, baseline_data, baseline_report
):
    data, report = baseline_data, baseline_report
    assert set(report) == set(owner.COMPONENTS) == {"manifest", "pages", "records"}
    assert [row["typed_response_group_record"] for row in report["records"]] == data[
        "typed_report"
    ]["records"]
    first = report["records"][0]
    authority_result = first["authority_assessment"]
    assert authority_result["authenticated_evidence_count"] == 2
    assert all(row["status"] == "authenticated" for row in authority_result["reviews"])
    assert len({row["context_declaration_sha256"] for row in authority_result["reviews"]}) == 1
    assert "authenticated_context_declarations_disagree" not in authority_result["blockers"]
    raw = first["typed_response_group_record"]["raw_source_assessment_record"]["assessment"]
    assert "authenticated_context_declarations_disagree" in raw["blockers"]
    assert "production_trust_registry_unavailable" in raw["blockers"]
    assert (
        first["declaration_record"]["pending_slot_refs"]
        == data["typed_report"]["records"][0]["adjudication_refs"]
    )
    assert first["declaration_record"]["considered_answer_variant_refs"] == [
        ref(row) for row in unit(data)[4]
    ]
    assert first["declaration_record"]["status"] == "declared_unauthenticated_source_adjudication"
    assert first["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert all(row["declaration_record"] is None for row in report["records"][1:])
    counts = report["manifest"]["counts"]
    assert counts["groups"] == len(data["preparation"]["requests"])
    assert counts["declaration_bodies"] == 1
    assert counts["authenticated_authority_claims"] == 2
    assert counts["declared_selected_slots"] == 9
    assert counts["unresolved_or_absent_slots"] == 9 * (counts["groups"] - 1)
    assert counts["deferred_questions"] == 7 * counts["groups"]
    assert_no_application(owner, report)
    assert validate(owner, report, data) == report


def test_authoring_retains_exact_pending_population_and_authenticates_no_decisions(
    owner, baseline_data, monkeypatch
):
    monkeypatch.setattr(trust_owner, "_assess_reviews", refuse_replay)
    monkeypatch.setattr(response_owner, "validate_source_review_responses", refuse_replay)
    body = author(owner, baseline_data)
    assert body["request_ref"] == ref(unit(baseline_data)[0])
    assert body["subject_ref"] == ref(unit(baseline_data)[1])
    assert body["typed_group_ref"] == ref(unit(baseline_data)[2])
    assert body["decisions"] == choices(baseline_data)
    for flag in owner.FALSE_FLAGS:
        assert body[flag] is False
    assert (
        owner.validate_source_adjudication_declaration(
            body, *unit(baseline_data), choices(baseline_data), **declaration_pins(baseline_data)
        )
        == body
    )


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "extra",
        "reordered",
        "duplicate",
        "wrong_slot",
        "unknown_decision",
        "missing_rationale",
        "empty_rationale",
        "unknown_field",
        "unresolved_selected",
        "selected_null",
        "unknown_variant",
        "wrong_variant_hash",
        "wrong_variant_schema",
        "foreign_slot_variant",
        "missing_evidence",
        "duplicate_evidence",
        "bad_evidence_hash",
        "bool_decision",
        "nested_nonfinite",
    ],
)
def test_authoring_rejects_incomplete_or_unknown_choices_without_interpreting_them(
    owner, baseline_data, damage
):
    values = choices(baseline_data)
    if damage == "missing":
        values.pop()
    elif damage == "extra":
        values.append(deepcopy(values[-1]))
    elif damage == "reordered":
        values[0], values[1] = values[1], values[0]
    elif damage == "duplicate":
        values[1] = deepcopy(values[0])
    elif damage == "wrong_slot":
        values[0]["slot_id"] = "fixture:foreign-slot"
    elif damage == "unknown_decision":
        values[0]["decision"] = "infer_equivalence"
    elif damage == "missing_rationale":
        del values[0]["rationale"]
    elif damage == "empty_rationale":
        values[0]["rationale"] = ""
    elif damage == "unknown_field":
        values[0]["source_truth"] = True
    elif damage == "unresolved_selected":
        values[0]["decision"] = "unresolved"
    elif damage == "selected_null":
        values[0]["selected_variant_ref"] = None
    elif damage == "unknown_variant":
        values[0]["selected_variant_ref"]["record_cid"] = unit(baseline_data)[0]["record_cid"]
    elif damage == "wrong_variant_hash":
        values[0]["selected_variant_ref"]["sha256"] = "0" * 64
    elif damage == "wrong_variant_schema":
        values[0]["selected_variant_ref"]["schema"] = source_owner.REQUEST_SCHEMA
    elif damage == "foreign_slot_variant":
        values[0]["selected_variant_ref"] = deepcopy(values[1]["selected_variant_ref"])
    elif damage == "missing_evidence":
        values[0]["evidence_refs"] = []
    elif damage == "duplicate_evidence":
        values[0]["evidence_refs"] *= 2
    elif damage == "bad_evidence_hash":
        values[0]["evidence_refs"][0]["sha256"] = "invalid"
    elif damage == "bool_decision":
        values[0]["decision"] = True
    elif damage == "nested_nonfinite":
        values[0]["rationale"] = float("nan")
    with pytest.raises(contracts.CorpusContractError):
        author(owner, baseline_data, values)


@pytest.mark.parametrize(
    "field", ["expected_request_sha256", "expected_subject_sha256", "expected_typed_group_sha256"]
)
@pytest.mark.parametrize("pin", ["0" * 64, "invalid", None, True])
def test_authoring_requires_independent_exact_record_pins(owner, baseline_data, field, pin):
    with pytest.raises(contracts.CorpusContractError):
        author(owner, baseline_data, **{field: pin})


@pytest.mark.parametrize(
    "field", ["expected_preparation_manifest_sha256", "expected_typed_response_manifest_sha256"]
)
@pytest.mark.parametrize("pin", ["invalid", None, True])
def test_authoring_requires_independent_manifest_pin_format(owner, baseline_data, field, pin):
    with pytest.raises(contracts.CorpusContractError):
        author(owner, baseline_data, **{field: pin})


@pytest.mark.parametrize(
    "damage",
    [
        "missing_slot",
        "reordered_slots",
        "foreign_request_slot",
        "missing_variant",
        "reordered_variants",
        "duplicate_variant",
        "foreign_group",
        "foreign_subject",
        "changed_typed_group",
    ],
)
def test_authoring_requires_complete_original_request_subject_pending_and_variant_population(
    owner, baseline_data, damage
):
    args = deepcopy(unit(baseline_data))
    request, subject, group, slots, variants = args
    if damage == "missing_slot":
        slots.pop()
    elif damage == "reordered_slots":
        slots[0], slots[1] = slots[1], slots[0]
    elif damage == "foreign_request_slot":
        slots[0]["request_cid"] = baseline_data["preparation"]["requests"][1]["record_cid"]
        slots[0] = reseal(slots[0])
    elif damage == "missing_variant":
        variants.pop()
    elif damage == "reordered_variants":
        variants[0], variants[1] = variants[1], variants[0]
    elif damage == "duplicate_variant":
        variants[1] = deepcopy(variants[0])
    elif damage == "foreign_group":
        args = (request, subject, baseline_data["typed_report"]["records"][1], slots, variants)
    elif damage == "foreign_subject":
        args = (request, baseline_data["preparation"]["subjects"][1], group, slots, variants)
    elif damage == "changed_typed_group":
        group["deferred_questions_remain_pending"] = False
        args = (request, subject, reseal(group), slots, variants)
    with pytest.raises(contracts.CorpusContractError):
        owner.record_source_adjudication_declaration(
            *args, choices(baseline_data), **declaration_pins(baseline_data)
        )


def test_missing_original_answers_can_only_remain_explicitly_unresolved(owner, baseline_data):
    body = author(owner, baseline_data, choices(baseline_data, 1), ordinal=1)
    assert all(
        row["decision"] == "unresolved" and row["selected_variant_ref"] is None
        for row in body["decisions"]
    )
    assert body["considered_answer_variant_refs"] == []
    values = choices(baseline_data, 1)
    values[0]["decision"] = "select_existing_variant"
    values[0]["selected_variant_ref"] = deepcopy(choices(baseline_data)[0]["selected_variant_ref"])
    with pytest.raises(contracts.CorpusContractError):
        author(owner, baseline_data, values, ordinal=1)


@pytest.mark.parametrize("disposition", ["unresolved", "not_applicable"])
def test_open_and_not_applicable_typed_answers_keep_their_exact_adjudication_dispositions(
    owner, fixture_data, disposition
):
    original = helper().signed_typed_case(response_owner, fixture_data, disposition=disposition)
    original_report = helper().assess(response_owner, original)
    data = clone_case(original)
    data["typed_report"] = original_report
    if disposition == "unresolved":
        values = choices(data)
        with pytest.raises(contracts.CorpusContractError):
            author(owner, data, values)
        values = choices(data, select=False)
        body = author(owner, data, values)
        assert all(row["selected_variant_ref"] is None for row in body["decisions"])
    else:
        data = signed_case(owner, original, original_report)
        report = assess(owner, data)
        assert all(
            row["disposition"] == "not_applicable"
            for row in data["adjudication_groups"][0]["reviews"][0]["context_closure"][
                "obligations"
            ]
        )
        assert report["records"][0]["declaration_content_status"] == "valid_declared_content"
        assert_no_application(owner, report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", source_owner.CLAIM_SCHEMA),
        ("schema", trust_owner.CLAIM_SCHEMA),
        ("action", source_owner.ACTION),
        ("audience", source_owner.AUDIENCE),
        ("role", "adjudicator"),
    ],
)
def test_original_or_graph_domains_and_unrecognized_roles_cannot_supply_adjudication_authority(
    owner, baseline_data, field, value
):
    data = clone_case(baseline_data)
    data["adjudication_groups"][0]["reviews"][0][field] = value
    refresh_signatures(data)
    with pytest.raises(ValueError):
        assess(owner, data)


@pytest.mark.parametrize(
    "damage,blocker",
    [
        ("bad_signature", "signature_invalid"),
        ("unknown_key", "unknown_authorized_key"),
        ("wrong_principal", "authorized_principal_binding_differs"),
        ("wrong_subject", "signed_subject_differs"),
        ("wrong_graph", "reviewed_interpretation_binding_differs"),
        ("wrong_registry", "signed_registry_sha256_differs"),
        ("wrong_policy", "signed_policy_sha256_differs"),
        ("wrong_scope", "unauthorized_legal_scope"),
        ("wrong_role", "unauthorized_review_role"),
        ("future", "review_not_current"),
        ("expired", "review_not_current"),
        ("old", "review_age_exceeded"),
        ("revoked_key", "key_revoked"),
        ("revoked_principal", "principal_revoked"),
        ("key_interval", "key_not_current_for_review_interval"),
    ],
)
def test_signed_authority_failures_remain_rejected_even_with_valid_selected_answer_content(
    owner, baseline_data, damage, blocker
):
    data = clone_case(baseline_data)
    claim = data["adjudication_groups"][0]["reviews"][0]
    key = data["adjudication_registry"]["keys"][0]
    if damage == "unknown_key":
        claim["key_id"] = "fixture:unknown-key"
    elif damage == "wrong_principal":
        claim["principal_id"] = "fixture:wrong-principal"
    elif damage == "wrong_subject":
        claim["subject"] = deepcopy(data["preparation"]["subjects"][1])
    elif damage == "wrong_graph":
        claim["interpretation"]["reviewed_graph_sha256"] = "0" * 64
    elif damage == "wrong_scope":
        key["scope_ids"] = ["fixture:unrelated-scope"]
    elif damage == "wrong_role":
        key["roles"] = ["formal_review"]
    elif damage == "future":
        claim["issued_at_utc"] = "2026-10-14T10:00:00Z"
    elif damage == "expired":
        claim["issued_at_utc"] = "2026-10-13T08:00:00Z"
        claim["expires_at_utc"] = "2026-10-14T08:00:00Z"
    elif damage == "old":
        claim["issued_at_utc"] = "2026-10-12T08:00:00Z"
    elif damage == "revoked_key":
        key["revoked_at_utc"] = "2026-10-14T08:00:00Z"
    elif damage == "revoked_principal":
        data["adjudication_registry"]["revoked_principals"] = [
            {"principal_id": key["principal_id"], "revoked_at_utc": "2026-10-14T08:00:00Z"}
        ]
    elif damage == "key_interval":
        key["valid_from_utc"] = "2026-10-14T08:45:00Z"
    refresh_signatures(data)
    claim = data["adjudication_groups"][0]["reviews"][0]
    if damage == "bad_signature":
        claim["signature"] = "A" * 86
    elif damage in {"wrong_registry", "wrong_policy"}:
        claim["registry_sha256" if damage == "wrong_registry" else "policy_sha256"] = "0" * 64
        # Sign the deliberately false independent authority binding.
        unsigned = {
            key: value
            for key, value in claim.items()
            if key not in {"signer_did", "signature_alg", "signature"}
        }
        data["adjudication_groups"][0]["reviews"][0] = data["adjudication_signers"][0].sign(
            unsigned
        )
    report = assess(owner, data)
    first = report["records"][0]
    assert first["declaration_content_status"] == "valid_declared_content"
    assert blocker in first["authority_assessment"]["reviews"][0]["blockers"]
    assert first["authority_assessment"]["reviews"][0]["status"] == "rejected"
    assert first["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert report["manifest"]["counts"]["declared_selected_slots"] == 9
    assert first["typed_response_group_record"] == data["typed_report"]["records"][0]
    assert_no_application(owner, report)


def test_two_keys_for_one_authority_principal_do_not_create_two_role_independence(
    owner, baseline_data
):
    data = clone_case(baseline_data)
    principal = data["adjudication_registry"]["keys"][0]["principal_id"]
    data["adjudication_registry"]["keys"][1]["principal_id"] = principal
    data["adjudication_groups"][0]["reviews"][1]["principal_id"] = principal
    refresh_signatures(data)
    report = assess(owner, data)
    assessment = report["records"][0]["authority_assessment"]
    assert assessment["authenticated_evidence_count"] == 2
    assert "distinct_authorized_review_principals_missing" in assessment["blockers"]
    assert report["records"][0]["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert_no_application(owner, report)


@pytest.mark.parametrize("missing", ["legal", "formal", "both"])
def test_all_required_role_claims_are_needed_without_inventing_a_missing_authority(
    owner, baseline_data, missing
):
    data = clone_case(baseline_data)
    group = data["adjudication_groups"][0]
    if missing == "both":
        group["reviews"] = []
        group["declaration_artifact_id"] = None
        group["evidence_artifacts"] = {}
    else:
        group["reviews"] = [group["reviews"][1 if missing == "legal" else 0]]
    report = assess(owner, data)
    assert report["records"][0]["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert report["records"][0]["authority_assessment"]["authenticated_evidence_count"] == (
        0 if missing == "both" else 1
    )
    assert_no_application(owner, report)


@pytest.mark.parametrize(
    "damage,blocker",
    [
        ("predates_original", "adjudication_predates_original_review"),
        ("after_evaluation", "adjudication_declared_after_evaluation"),
        ("claim_predates_body", "authority_claim_predates_common_declaration"),
    ],
)
def test_declaration_chronology_is_checked_without_authenticating_the_clock(
    owner, baseline_data, damage, blocker
):
    data = clone_case(baseline_data)
    body = json.loads(
        data["adjudication_groups"][0]["evidence_artifacts"][
            data["adjudication_groups"][0]["declaration_artifact_id"]
        ]
    )
    if damage == "predates_original":
        body["declared_at_utc"] = "2026-10-14T07:00:00Z"
    elif damage == "after_evaluation":
        body["declared_at_utc"] = "2026-10-14T10:00:00Z"
    else:
        data["adjudication_groups"][0]["reviews"][0]["issued_at_utc"] = "2026-10-14T08:05:00Z"
    replace_body(data, reseal(body))
    report = assess(owner, data)
    first = report["records"][0]
    assert first["declaration_content_status"] == "valid_declared_content"
    assert blocker in first["separation_and_chronology_blockers"]
    assert first["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert first["authority_assessment"]["evaluation_clock_authenticated"] is False
    assert_no_application(owner, report)


@pytest.mark.parametrize("source_status", ["authenticated", "rejected"])
def test_every_supplied_original_reviewer_is_excluded_from_adjudicating_even_if_rejected(
    owner, baseline_data, source_status
):
    original = clone_case(baseline_data)
    if source_status == "rejected":
        original["groups"][0]["reviews"][0]["signature"] = "A" * 86
        original["typed_report"] = helper().assess(response_owner, original)
    data = signed_case(owner, original, original["typed_report"])
    original_principal = original["groups"][0]["reviews"][0]["principal_id"]
    data["adjudication_registry"]["keys"][0]["principal_id"] = original_principal
    data["adjudication_groups"][0]["reviews"][0]["principal_id"] = original_principal
    refresh_signatures(data)
    report = assess(owner, data)
    assert report["records"][0]["authority_assessment"]["authenticated_evidence_count"] == 2
    assert (
        "adjudicator_is_a_supplied_original_reviewer"
        in report["records"][0]["separation_and_chronology_blockers"]
    )
    assert report["records"][0]["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert_no_application(owner, report)


def test_original_reviewer_from_another_request_is_excluded_by_whole_batch_principal_scope(
    owner, baseline_data
):
    original = clone_case(baseline_data)
    foreign = deepcopy(original["groups"][0]["reviews"][0])
    foreign["review_id"] = "fixture:other-request-original-reviewer"
    foreign["principal_id"] = "fixture:other-request-original-principal"
    foreign["signature"] = "A" * 86
    original["groups"][1]["reviews"] = [foreign]
    original["groups"][1]["evidence_artifacts"] = deepcopy(
        original["groups"][0]["evidence_artifacts"]
    )
    artifact = original["response_bindings"][0]["responses"][0]
    original["response_bindings"][1]["responses"] = [
        {**deepcopy(artifact), "review_id": foreign["review_id"]}
    ]
    original["typed_report"] = helper().assess(response_owner, original)
    data = signed_case(owner, original, original["typed_report"])
    data["adjudication_registry"]["keys"][0]["principal_id"] = foreign["principal_id"]
    data["adjudication_groups"][0]["reviews"][0]["principal_id"] = foreign["principal_id"]
    refresh_signatures(data)
    report = assess(owner, data)
    assert (
        "adjudicator_is_a_supplied_original_reviewer"
        in report["records"][0]["separation_and_chronology_blockers"]
    )
    assert (
        report["records"][0]["typed_response_group_record"]
        == original["typed_report"]["records"][0]
    )
    assert_no_application(owner, report)


def test_external_shaped_fixture_can_satisfy_declared_authority_only_while_source_disagreement_and_admission_flags_remain(
    owner, fixture_data
):
    original = helper().signed_typed_case(
        response_owner, fixture_data, trust_mode="external_pinned_trust"
    )
    original_report = helper().assess(response_owner, original)
    data = signed_case(owner, original, original_report, mode="external_pinned_trust")
    report = assess(owner, data)
    first = report["records"][0]
    assert (
        first["authority_assessment"]["review_prerequisites_satisfied_under_selected_trust"] is True
    )
    assert first["authority_prerequisites_satisfied_under_selected_trust"] is True
    assert (
        report["manifest"]["counts"][
            "complete_declaration_authority_prerequisites_under_selected_trust"
        ]
        == 1
    )
    assert first["typed_response_group_record"] == original_report["records"][0]
    assert (
        "authenticated_context_declarations_disagree"
        in first["typed_response_group_record"]["raw_source_assessment_record"]["assessment"][
            "blockers"
        ]
    )
    assert first["authority_assessment"]["registry_identity_authenticated_by_this_api"] is False
    assert first["authority_assessment"]["evaluation_clock_authenticated"] is False
    assert first["adjudicator_human_independence_verified"] is False
    assert_no_application(owner, report)


def test_unavailable_empty_trust_never_creates_authority_decisions_or_reviews(owner, baseline_data):
    data = clone_case(baseline_data)
    data["adjudication_registry"]["mode"] = data["adjudication_policy"]["mode"] = "unavailable"
    data["adjudication_registry"]["keys"] = []
    data["adjudication_policy"]["registry_sha256"] = sha(canonical(data["adjudication_registry"]))
    for group in data["adjudication_groups"]:
        group["reviews"], group["declaration_artifact_id"], group["evidence_artifacts"] = (
            [],
            None,
            {},
        )
    report = assess(owner, data)
    assert all(row["declaration_record"] is None for row in report["records"])
    assert all(row["authority_assessment"]["review_count"] == 0 for row in report["records"])
    assert all(
        "trust_registry_unavailable" in row["authority_assessment"]["blockers"]
        for row in report["records"]
    )
    assert report["manifest"]["counts"]["declaration_bodies"] == 0
    assert report["manifest"]["counts"]["unresolved_or_absent_slots"] == 9 * len(report["records"])
    assert_no_application(owner, report)


@pytest.mark.parametrize(
    "damage",
    [
        "different_artifact_id",
        "changed_body_ref",
        "missing_obligation",
        "reordered_obligations",
        "duplicate_obligation",
        "wrong_disposition",
        "extra_body_ref",
        "missing_body_ref",
        "wrong_unresolved",
        "foreign_unresolved",
    ],
)
def test_each_role_must_bind_the_same_exact_common_body_and_all_nine_dispositions(
    owner, baseline_data, damage
):
    data = clone_case(baseline_data)
    group = data["adjudication_groups"][0]
    closure = group["reviews"][1]["context_closure"]
    if damage == "different_artifact_id":
        alias = "fixture:alias-adjudication-body"
        group["evidence_artifacts"][alias] = group["evidence_artifacts"][
            group["declaration_artifact_id"]
        ]
        for row in closure["obligations"]:
            row["evidence_refs"][0]["artifact_id"] = alias
    elif damage == "changed_body_ref":
        closure["obligations"][0]["evidence_refs"][0]["sha256"] = "0" * 64
    elif damage == "missing_obligation":
        closure["obligations"].pop()
    elif damage == "reordered_obligations":
        closure["obligations"][0], closure["obligations"][1] = (
            closure["obligations"][1],
            closure["obligations"][0],
        )
    elif damage == "duplicate_obligation":
        closure["obligations"][1] = deepcopy(closure["obligations"][0])
    elif damage == "wrong_disposition":
        closure["obligations"][0]["disposition"] = "not_applicable"
    elif damage == "extra_body_ref":
        closure["obligations"][0]["evidence_refs"].append(
            {"artifact_id": EVIDENCE_ID, "sha256": sha(EVIDENCE_BYTES)}
        )
    elif damage == "missing_body_ref":
        closure["obligations"][0]["evidence_refs"] = []
    elif damage == "wrong_unresolved":
        closure["unresolved"] = [closure["obligations"][0]["slot_id"]]
    elif damage == "foreign_unresolved":
        closure["unresolved"] = ["fixture:foreign-slot"]
    refresh_signatures(data)
    report = assess(owner, data)
    first = report["records"][0]
    assert first["declaration_content_status"] == "rejected"
    assert first["declaration_record"] is None
    assert any(
        "signed_choice_population_or_disposition_differs" in blocker
        for blocker in first["content_blockers"]
    )
    assert first["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert first["typed_response_group_record"] == baseline_data["typed_report"]["records"][0]
    assert_no_application(owner, report)


@pytest.mark.parametrize(
    "damage", ["complete_unknown", "missing_unresolved", "reordered_unresolved", "resolved_unknown"]
)
def test_signed_unknown_choices_cannot_be_repaired_into_complete_source_context(
    owner, baseline_data, damage
):
    data = signed_case(owner, baseline_data, baseline_data["typed_report"], select=False)
    closure = data["adjudication_groups"][0]["reviews"][0]["context_closure"]
    if damage == "complete_unknown":
        closure["status"] = "declared_complete"
    elif damage == "missing_unresolved":
        closure["unresolved"].pop()
    elif damage == "reordered_unresolved":
        closure["unresolved"][0], closure["unresolved"][1] = (
            closure["unresolved"][1],
            closure["unresolved"][0],
        )
    elif damage == "resolved_unknown":
        closure["obligations"][0]["disposition"] = "resolved_by_evidence"
    refresh_signatures(data)
    report = assess(owner, data)
    first = report["records"][0]
    assert first["declaration_content_status"] == "rejected"
    assert first["declaration_record"] is None
    assert first["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert_no_application(owner, report)


def test_conservatively_open_shared_declaration_stays_open_with_valid_typed_selected_content(
    owner, baseline_data
):
    data = clone_case(baseline_data)
    for claim in data["adjudication_groups"][0]["reviews"]:
        claim["context_closure"]["status"] = "open"
    refresh_signatures(data)
    report = assess(owner, data)
    first = report["records"][0]
    assert first["declaration_content_status"] == "valid_declared_content"
    assert all(
        "context_declared_open" in row["context_blockers"]
        for row in first["authority_assessment"]["reviews"]
    )
    assert (
        "authenticated_complete_context_declarations_missing"
        in first["authority_assessment"]["blockers"]
    )
    assert first["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert_no_application(owner, report)


@pytest.mark.parametrize("damage", ["missing", "changed", "self_ref"])
def test_decision_rationale_evidence_must_resolve_to_exact_distinct_supplied_bytes(
    owner, baseline_data, damage
):
    data = clone_case(baseline_data)
    group = data["adjudication_groups"][0]
    if damage == "missing":
        del group["evidence_artifacts"][EVIDENCE_ID]
    elif damage == "changed":
        group["evidence_artifacts"][EVIDENCE_ID] += b" altered"
    else:
        body = json.loads(group["evidence_artifacts"][group["declaration_artifact_id"]])
        body["decisions"][0]["evidence_refs"] = [
            {
                "artifact_id": group["declaration_artifact_id"],
                "sha256": sha(group["evidence_artifacts"][group["declaration_artifact_id"]]),
            }
        ]
        replace_body(data, reseal(body))
    report = assess(owner, data)
    first = report["records"][0]
    assert first["declaration_record"] is None
    assert any(
        "evidence_missing_changed_or_self_referential" in row for row in first["content_blockers"]
    )
    assert first["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert_no_application(owner, report)


@pytest.mark.parametrize(
    "field",
    [
        "request_ref",
        "subject_ref",
        "typed_group_ref",
        "preparation_manifest_sha256",
        "typed_response_manifest_sha256",
        "pending_slot_refs",
        "considered_answer_variant_refs",
        "queue_ordinal",
        "profile",
        "status",
    ],
)
def test_resealed_common_body_cannot_replace_original_pins_or_considered_populations(
    owner, baseline_data, field
):
    data = clone_case(baseline_data)
    group = data["adjudication_groups"][0]
    body = json.loads(group["evidence_artifacts"][group["declaration_artifact_id"]])
    if field.endswith("_ref"):
        body[field]["sha256"] = "0" * 64
    elif field.endswith("_sha256"):
        body[field] = "0" * 64
    elif field.endswith("_refs"):
        body[field].pop()
    elif field == "queue_ordinal":
        body[field] += 1
    else:
        body[field] = "unrecognized_profile_or_status"
    replace_body(data, reseal(body))
    report = assess(owner, data)
    assert report["records"][0]["declaration_content_status"] == "rejected"
    assert report["records"][0]["declaration_record"] is None
    assert report["records"][0]["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert_no_application(owner, report)


@pytest.mark.parametrize("overlap", ["principal", "did", "public_key", "public_key_and_did"])
def test_relabeling_an_original_signer_cannot_create_separate_adjudication_authority(
    owner, baseline_data, overlap
):
    data = clone_case(baseline_data)
    original_key = data["registry"]["keys"][0]
    key = data["adjudication_registry"]["keys"][0]
    claim = data["adjudication_groups"][0]["reviews"][0]
    if overlap == "principal":
        key["principal_id"] = claim["principal_id"] = original_key["principal_id"]
        expected = "adjudicator_is_a_supplied_original_reviewer"
    elif overlap == "did":
        key["signer_did"] = original_key["signer_did"]
        # A fresh physical key presented with an original signer's DID.
        signer = data["adjudication_signers"][0]
        data["adjudication_signers"][0] = Ed25519Signer(
            original_key["signer_did"], signer.private_key
        )
        expected = "adjudicator_reuses_an_original_reviewer_did"
    else:
        original_signer = data["signers"][0]
        new_did = (
            original_key["signer_did"] if overlap == "public_key_and_did" else key["signer_did"]
        )
        data["adjudication_signers"][0] = Ed25519Signer(new_did, original_signer.private_key)
        key["public_key_hex"] = original_key["public_key_hex"]
        key["signer_did"] = new_did
        expected = "adjudicator_reuses_an_original_reviewer_public_key"
    refresh_signatures(data)
    report = assess(owner, data)
    first = report["records"][0]
    assert first["authority_assessment"]["authenticated_evidence_count"] == 2
    assert expected in first["separation_and_chronology_blockers"]
    assert first["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert_no_application(owner, report)


@pytest.mark.parametrize(
    "pin_name",
    [
        "expected_registry_sha256",
        "expected_policy_sha256",
        "expected_typed_response_manifest_sha256",
        "expected_adjudication_registry_sha256",
        "expected_adjudication_policy_sha256",
    ],
)
def test_selected_original_and_adjudication_trust_generations_are_independently_pinned_before_replay(
    owner, baseline_data, monkeypatch, pin_name
):
    monkeypatch.setattr(response_owner, "validate_source_review_responses", refuse_replay)
    with pytest.raises(contracts.CorpusContractError):
        assess(owner, baseline_data, **{pin_name: "0" * 64})


@pytest.mark.parametrize(
    "damage",
    [
        "subset",
        "extra_group",
        "reordered",
        "duplicate",
        "foreign_request",
        "pins_subset",
        "pins_reordered",
        "wrong_review_hash",
        "wrong_evidence_hash",
        "wrong_observation_hash",
        "wrong_pin_hash",
        "missing_body",
        "wrong_body_id",
        "empty_with_body_id",
        "mutable_body",
        "unknown_group_field",
        "unknown_pin_field",
    ],
)
def test_complete_custody_populations_cannot_drop_duplicate_reorder_or_alias_before_replay(
    owner, baseline_data, monkeypatch, damage
):
    data = clone_case(baseline_data)
    groups = data["adjudication_groups"]
    pins = group_pins(groups)
    if damage == "subset":
        groups.pop()
    elif damage == "extra_group":
        groups.append(deepcopy(groups[-1]))
    elif damage == "reordered":
        groups[0], groups[1] = groups[1], groups[0]
    elif damage == "duplicate":
        groups[1] = deepcopy(groups[0])
    elif damage == "foreign_request":
        groups[0]["request_cid"] = groups[1]["request_cid"]
    elif damage == "pins_subset":
        pins.pop()
    elif damage == "pins_reordered":
        pins[0], pins[1] = pins[1], pins[0]
    elif damage == "wrong_review_hash":
        pins[0]["reviews_sha256"] = "0" * 64
    elif damage == "wrong_evidence_hash":
        pins[0]["evidence_sha256s"][groups[0]["declaration_artifact_id"]] = "0" * 64
    elif damage == "wrong_observation_hash":
        pins[0]["observed_artifacts_sha256"] = "0" * 64
    elif damage == "wrong_pin_hash":
        pins[0]["observed_pins_sha256"] = "0" * 64
    elif damage == "missing_body":
        del groups[0]["evidence_artifacts"][groups[0]["declaration_artifact_id"]]
    elif damage == "wrong_body_id":
        groups[0]["declaration_artifact_id"] = "fixture:missing-body"
        pins[0]["declaration_artifact_id"] = "fixture:missing-body"
    elif damage == "empty_with_body_id":
        groups[1]["declaration_artifact_id"] = "fixture:unsolicited-body"
        pins[1]["declaration_artifact_id"] = "fixture:unsolicited-body"
    elif damage == "mutable_body":
        groups[0]["evidence_artifacts"][groups[0]["declaration_artifact_id"]] = bytearray(
            b"mutable"
        )
    elif damage == "unknown_group_field":
        groups[0]["choose_prefix"] = True
    elif damage == "unknown_pin_field":
        pins[0]["authority"] = True
    monkeypatch.setattr(response_owner, "validate_source_review_responses", refuse_replay)
    with pytest.raises(contracts.CorpusContractError):
        assess(owner, data, expected_adjudication_group_pins=pins)


@pytest.mark.parametrize("invalid", [None, True, False, 0, -1, 1.5, "1", []])
def test_public_lower_only_limits_require_exact_positive_integers(owner, baseline_data, invalid):
    with pytest.raises(contracts.CorpusContractError):
        author(owner, baseline_data, limits={"max_declaration_bytes": invalid})


@pytest.mark.parametrize(
    "limits", [{"unknown": 1}, {"max_declaration_bytes": 1024**2 + 1}, [], True]
)
def test_public_limits_cannot_raise_or_redefine_the_fixed_profile(owner, baseline_data, limits):
    with pytest.raises(contracts.CorpusContractError):
        author(owner, baseline_data, limits=limits)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_groups": 1},
        {"max_declaration_bytes": 1},
        {"max_group_bytes": 1},
        {"max_batch_bytes": 1},
    ],
)
def test_known_complete_input_caps_refuse_before_typed_source_replay(
    owner, baseline_data, monkeypatch, limits
):
    monkeypatch.setattr(response_owner, "validate_source_review_responses", refuse_replay)
    with pytest.raises(contracts.CorpusContractError):
        assess(owner, baseline_data, limits=limits)


def test_every_adjudication_raw_body_size_passes_before_first_indexed_adjudication_body_hash(
    owner, baseline_data, monkeypatch
):
    data = clone_case(baseline_data)
    first = data["adjudication_groups"][0]
    indexed = first["evidence_artifacts"][first["declaration_artifact_id"]]
    later = data["adjudication_groups"][1]
    later["evidence_artifacts"]["fixture:later-over-budget"] = b"x" * (8 * 1024**2 + 1)
    pins = group_pins(data["adjudication_groups"])
    real_sha = source_owner._sha

    def guard(raw):
        if raw is indexed or raw == indexed:
            pytest.fail(
                "Indexed adjudication evidence was hashed before all later body sizes passed"
            )
        return real_sha(raw)

    monkeypatch.setattr(source_owner, "_sha", guard)
    monkeypatch.setattr(response_owner, "validate_source_review_responses", refuse_replay)
    with pytest.raises(contracts.CorpusContractError):
        assess(owner, data, expected_adjudication_group_pins=pins)


def test_complete_group_json_and_evidence_budget_passes_before_its_first_indexed_body_hash(
    owner, baseline_data, monkeypatch
):
    data = clone_case(baseline_data)
    group = data["adjudication_groups"][0]
    indexed = group["evidence_artifacts"][group["declaration_artifact_id"]]
    raw_size = sum(len(value) for value in group["evidence_artifacts"].values())
    real_sha = source_owner._sha

    def guard(raw):
        if raw == indexed:
            pytest.fail(
                "Indexed adjudication evidence was hashed before complete JSON plus evidence budget passed"
            )
        return real_sha(raw)

    monkeypatch.setattr(source_owner, "_sha", guard)
    monkeypatch.setattr(response_owner, "validate_source_review_responses", refuse_replay)
    with pytest.raises(contracts.CorpusContractError):
        assess(owner, data, limits={"max_group_bytes": raw_size + 1})


def test_existing_typed_response_owner_regenerates_once_for_the_complete_ordered_batch(
    owner, baseline_data, monkeypatch
):
    calls = []
    original = response_owner.validate_source_review_responses

    def count(*args, **kwargs):
        calls.append(len(args[1]["requests"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(response_owner, "validate_source_review_responses", count)
    report = assess(owner, baseline_data)
    assert calls == [len(baseline_data["preparation"]["requests"])]
    assert [row["queue_ordinal"] for row in report["records"]] == list(
        range(len(report["records"]))
    )


def test_producer_drift_during_existing_authority_signature_verification_refuses_whole_collection(
    owner, baseline_data, monkeypatch
):
    initial = owner._pins()
    changed = [False]
    original = trust_owner._verify_signature

    def verify(*args, **kwargs):
        result = original(*args, **kwargs)
        changed[0] = True
        return result

    def pins():
        return {**initial, "fixture:changed-producer": "0" * 64} if changed[0] else initial

    monkeypatch.setattr(trust_owner, "_verify_signature", verify)
    monkeypatch.setattr(owner, "_pins", pins)
    with pytest.raises(contracts.CorpusContractError):
        assess(owner, baseline_data)


def test_output_and_original_nested_declarations_never_alias_caller_owned_containers(
    owner, baseline_data
):
    data = clone_case(baseline_data)
    before = clone_case(data)
    report = assess(owner, data)
    assert data == before
    report["records"][0]["typed_response_group_record"]["deferred_review_slot_ids"].append(
        "fixture:modified-output"
    )
    report["records"][0]["declaration_record"]["decisions"][0]["rationale"] = "modified output"
    assert data == before


@pytest.mark.parametrize(
    "damage",
    [
        "wrong_choices",
        "missing_pending",
        "changed_variant_inventory",
        "changed_time",
        "changed_manifest",
        "authority_true",
    ],
)
def test_resealed_authored_declaration_still_requires_exact_independent_regeneration(
    owner, baseline_data, damage
):
    body = author(owner, baseline_data)
    if damage == "wrong_choices":
        body["decisions"][0]["rationale"] += " changed"
    elif damage == "missing_pending":
        body["pending_slot_refs"].pop()
    elif damage == "changed_variant_inventory":
        body["considered_answer_variant_refs"].pop()
    elif damage == "changed_time":
        body["declared_at_utc"] = "2026-10-14T08:20:00Z"
    elif damage == "changed_manifest":
        body["typed_response_manifest_sha256"] = "0" * 64
    elif damage == "authority_true":
        body["adjudication_accepted"] = True
    with pytest.raises(contracts.CorpusContractError):
        owner.validate_source_adjudication_declaration(
            reseal(body),
            *unit(baseline_data),
            choices(baseline_data),
            **declaration_pins(baseline_data),
        )


def rebind_report(report):
    by_ordinal = {row["queue_ordinal"]: row for row in report["records"]}
    for index, page in enumerate(report["pages"]):
        for entry in page["entries"]:
            entry["group_record_ref"] = ref(by_ordinal[entry["ordinal"]])
        report["pages"][index] = reseal(page)
    for index, page in enumerate(report["pages"]):
        report["manifest"]["page_refs"][index].update(ref(page))
    report["manifest"] = reseal(report["manifest"])


@pytest.mark.parametrize(
    "damage",
    [
        "erased_source_disagreement",
        "typed_group_changed",
        "deleted_group",
        "reordered_groups",
        "authority_true",
        "applied_true",
        "changed_body",
        "removed_variants",
        "wrong_page_ref",
        "wrong_counts",
        "wrong_producer",
    ],
)
def test_repaired_assessment_seals_and_inventories_cannot_substitute_for_exact_complete_regeneration(
    owner, baseline_data, baseline_report, damage
):
    report = deepcopy(baseline_report)
    row = report["records"][0]
    if damage == "erased_source_disagreement":
        row["typed_response_group_record"]["raw_source_assessment_record"]["assessment"][
            "blockers"
        ] = []
    elif damage == "typed_group_changed":
        row["typed_response_group_record"]["deferred_questions_remain_pending"] = False
    elif damage == "deleted_group":
        report["records"].pop()
    elif damage == "reordered_groups":
        report["records"][0], report["records"][1] = report["records"][1], report["records"][0]
    elif damage == "authority_true":
        row["authority_prerequisites_satisfied_under_selected_trust"] = True
    elif damage == "applied_true":
        row["source_selection_applied"] = True
    elif damage == "changed_body":
        row["declaration_record"]["decisions"][0]["rationale"] += " changed"
    elif damage == "removed_variants":
        row["declaration_record"]["considered_answer_variant_refs"].pop()
    elif damage == "wrong_page_ref":
        report["pages"][0]["entries"][0]["request_cid"] = report["records"][1]["request_cid"]
    elif damage == "wrong_counts":
        report["manifest"]["counts"]["adjudications_applied"] = 1
    elif damage == "wrong_producer":
        report["manifest"]["producer_pins"]["fixture:invented"] = "0" * 64
    report["records"] = [reseal(item) for item in report["records"]]
    if damage != "deleted_group":
        rebind_report(report)
    else:
        report["manifest"] = reseal(report["manifest"])
    with pytest.raises(contracts.CorpusContractError):
        validate(owner, report, baseline_data)


@pytest.mark.parametrize(
    "damage",
    [
        "extra_component",
        "missing_component",
        "mutable_component",
        "too_many_records",
        "oversized_record",
        "unsealed_record",
        "unknown_record_field",
    ],
)
def test_invalid_offered_output_is_refused_before_regeneration(
    owner, baseline_data, baseline_report, monkeypatch, damage
):
    report = deepcopy(baseline_report)
    if damage == "extra_component":
        report["unexpected"] = []
    elif damage == "missing_component":
        del report["records"]
    elif damage == "mutable_component":
        report["records"] = tuple(report["records"])
    elif damage == "too_many_records":
        report["records"] = report["records"] * (8192 // len(report["records"]) + 1)
    elif damage == "oversized_record":
        report["records"][0]["content_blockers"] = ["x" * (1024**2 + 1)]
    elif damage == "unsealed_record":
        report["records"][0]["record_cid"] = "not-a-cid"
    elif damage == "unknown_record_field":
        report["records"][0]["adjudicator_approved"] = True
        report["records"][0] = reseal(report["records"][0])
    monkeypatch.setattr(owner, "assess_source_adjudications", refuse_replay)
    with pytest.raises(contracts.CorpusContractError):
        validate(owner, report, baseline_data)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_pages": 1, "max_groups_per_page": 1},
        {"max_page_bytes": 1},
        {"max_collection_bytes": 1},
    ],
)
def test_complete_output_caps_refuse_the_entire_batch_without_returning_a_prefix(
    owner, baseline_data, limits
):
    with pytest.raises(contracts.CorpusContractError):
        assess(owner, baseline_data, limits=limits)


def test_lowered_page_inventory_keeps_all_original_ordered_groups_and_pending_refs(
    owner, baseline_data
):
    report = assess(owner, baseline_data, limits={"max_groups_per_page": 1})
    assert len(report["pages"]) == len(report["records"])
    entries = [entry for page in report["pages"] for entry in page["entries"]]
    assert [row["ordinal"] for row in entries] == list(range(len(report["records"])))
    assert [row["group_record_ref"] for row in entries] == [ref(row) for row in report["records"]]
    assert [row["typed_response_group_record"] for row in report["records"]] == baseline_data[
        "typed_report"
    ]["records"]
    assert_no_application(owner, report)


def test_all_distinct_typed_answer_variants_survive_selection_of_an_existing_alternative(
    owner, baseline_data
):
    original = clone_case(baseline_data)
    helper().mutate_response(
        original,
        lambda response: response["answers"][0].update(
            {"rationale": "A distinct exact authored rationale, never discarded by adjudication."}
        ),
        index=1,
    )
    original["typed_report"] = helper().assess(response_owner, original)
    data = signed_case(owner, original, original["typed_report"])
    slots = unit(data)[3]
    assert len(slots[0]["answer_variant_refs"]) == 2
    values = choices(data)
    values[0]["selected_variant_ref"] = deepcopy(slots[0]["answer_variant_refs"][1])
    body = author(owner, data, values)
    data["adjudication_groups"][0] = sign_group(owner, data, body)
    report = assess(owner, data)
    first = report["records"][0]
    assert first["declaration_content_status"] == "valid_declared_content"
    assert (
        first["declaration_record"]["decisions"][0]["selected_variant_ref"]
        == slots[0]["answer_variant_refs"][1]
    )
    assert first["declaration_record"]["considered_answer_variant_refs"] == [
        ref(row) for row in unit(data)[4]
    ]
    assert first["typed_response_group_record"] == original["typed_report"]["records"][0]
    assert len(first["declaration_record"]["considered_answer_variant_refs"]) == 10
    assert "distinct_exact_answer_variants" in slots[0]["issues"]
    assert_no_application(owner, report)


def test_valid_unresolved_shared_body_is_authenticated_as_open_without_becoming_complete_context(
    owner, baseline_data
):
    data = signed_case(owner, baseline_data, baseline_data["typed_report"], select=False)
    report = assess(owner, data)
    first = report["records"][0]
    assert first["declaration_content_status"] == "valid_declared_content"
    assert first["authority_assessment"]["authenticated_evidence_count"] == 2
    assert all(
        "context_declared_open" in row["context_blockers"]
        for row in first["authority_assessment"]["reviews"]
    )
    assert first["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert report["manifest"]["counts"]["declared_selected_slots"] == 0
    assert report["manifest"]["counts"]["unresolved_or_absent_slots"] == 9 * len(report["records"])
    assert_no_application(owner, report)


@pytest.mark.parametrize(
    "damage", ["missing_dependency", "changed_dependency", "changed_source_pin"]
)
def test_selected_authority_cannot_mask_stale_or_missing_original_source_dependencies(
    owner, baseline_data, damage
):
    data = clone_case(baseline_data)
    group = data["adjudication_groups"][0]
    required = data["preparation"]["subjects"][0]["required_dependency_ids"][0]
    if damage == "missing_dependency":
        # Complete observation inventories use null for unavailable bytes.
        group["observed_artifact_sha256s"][required] = None
    elif damage == "changed_dependency":
        group["observed_artifact_sha256s"][required] = "0" * 64
    else:
        kind, values = next(
            (kind, values) for kind, values in group["observed_pins"].items() if values
        )
        values[next(iter(values))] = "0" * 64
    report = assess(owner, data)
    first = report["records"][0]
    assert first["declaration_content_status"] == "valid_declared_content"
    assert "required_dependency_closure_not_current" in first["authority_assessment"]["blockers"]
    assert first["authority_prerequisites_satisfied_under_selected_trust"] is False
    assert_no_application(owner, report)


@pytest.mark.parametrize("damage", ["reject", "ambiguity", "bad_signature"])
def test_extra_supplied_authority_claims_remain_in_the_population_and_cannot_be_dropped_for_a_convenient_pair(
    owner, baseline_data, damage
):
    data = clone_case(baseline_data)
    signer = Ed25519Signer.generate("did:example:extra-source-adjudicator")
    key = deepcopy(data["adjudication_registry"]["keys"][0])
    key.update(
        {
            "key_id": "fixture:extra-adjudication-key",
            "principal_id": "fixture:extra-adjudication-principal",
            "signer_did": signer.did,
            "public_key_hex": signer.public_key.public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            ).hex(),
        }
    )
    data["adjudication_registry"]["keys"].append(key)
    data["adjudication_signers"].append(signer)
    claim = deepcopy(data["adjudication_groups"][0]["reviews"][0])
    claim.update(
        {
            "review_id": "fixture:extra-authority-claim",
            "key_id": key["key_id"],
            "principal_id": key["principal_id"],
        }
    )
    if damage == "reject":
        claim["interpretation"]["decision"] = "reject"
    elif damage == "ambiguity":
        claim["interpretation"]["ambiguity"] = ["Explicit unresolved disagreement remains visible."]
    data["adjudication_groups"][0]["reviews"].append(claim)
    refresh_signatures(data)
    if damage == "bad_signature":
        data["adjudication_groups"][0]["reviews"][-1]["signature"] = "A" * 86
    report = assess(owner, data)
    assessment = report["records"][0]["authority_assessment"]
    assert assessment["review_count"] == len(assessment["reviews"]) == 3
    assert assessment["review_prerequisites_satisfied_under_selected_trust"] is False
    assert assessment["reviews"][-1]["review_id"] == "fixture:extra-authority-claim"
    assert_no_application(owner, report)


def test_all_original_response_body_sizes_pass_before_any_original_indexed_body_hash(
    owner, baseline_data, monkeypatch
):
    data = clone_case(baseline_data)
    entry = data["response_bindings"][0]["responses"][0]
    indexed = data["groups"][0]["evidence_artifacts"][entry["artifact_id"]]
    data["groups"][1]["evidence_artifacts"]["fixture:later-original-over-budget"] = b"x" * (
        8 * 1024**2 + 1
    )
    args = assessment_arguments(data)
    real_sha = source_owner._sha

    def guard(raw):
        if raw == indexed:
            pytest.fail(
                "Original indexed response body was hashed before all later original body budgets passed"
            )
        return real_sha(raw)

    monkeypatch.setattr(source_owner, "_sha", guard)
    monkeypatch.setattr(response_owner, "validate_source_review_responses", refuse_replay)
    with pytest.raises(contracts.CorpusContractError):
        assess(owner, data, expected_review_group_pins=args["expected_review_group_pins"])


@pytest.mark.parametrize("declared", [None, "", "2026-10-14T08:15:00+00:00", "2026-10-14", True, 1])
def test_declared_time_requires_an_explicit_canonical_utc_declaration(
    owner, baseline_data, declared
):
    with pytest.raises(ValueError):
        author(owner, baseline_data, declared_at_utc=declared)


def test_oversized_cyclic_and_nonfinite_choices_refuse_at_the_untrusted_authoring_boundary(
    owner, baseline_data
):
    values = choices(baseline_data)
    values[0]["rationale"] = "x" * (1024**2 + 1)
    with pytest.raises(contracts.CorpusContractError):
        author(owner, baseline_data, values)
    values = choices(baseline_data)
    values[0]["evidence_refs"].append(values)
    with pytest.raises(contracts.CorpusContractError):
        author(owner, baseline_data, values)
    values = choices(baseline_data)
    values[0]["evidence_refs"][0]["sha256"] = float("inf")
    with pytest.raises(contracts.CorpusContractError):
        author(owner, baseline_data, values)


def test_public_import_does_not_load_models_source_decoders_crypto_or_clock():
    program = r"""
import sys
from ipfs_datasets_py.logic.autoformal import corpus_source_adjudication as owner
for prefix in ('torch', 'transformers', 'pyarrow'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules)
assert 'ipfs_datasets_py.logic.autoformal.legal_source_review_handoff' not in sys.modules
assert 'ipfs_datasets_py.logic.profile_g' not in sys.modules
print('inert source adjudication import verified')
"""
    repo = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=repo,
        env=dict(
            os.environ,
            IPFS_DATASETS_PY_MINIMAL_IMPORTS="1",
            IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0",
            PYTHONPATH=str(repo),
        ),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "inert source adjudication import verified"

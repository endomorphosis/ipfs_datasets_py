"""Genesis candidate snapshots activate exact engineering choices, never law.

Every source, identity, key and answer is an authored fixture. External-shaped
fixture registries test selected-trust behavior without establishing an actual
review, legal authority, semantic target, graph or Lean statement.
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
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_source_adjudication as adjudication_owner
from ipfs_datasets_py.logic.autoformal import corpus_source_review as source_owner
from ipfs_datasets_py.logic.autoformal import corpus_source_review_responses as response_owner
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust_owner
from ipfs_datasets_py.logic.profile_g import Ed25519Signer
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

DESCRIPTOR = {
    "snapshot_id": "fixture:candidate-source-context-snapshot",
    "use_scope": "candidate_source_context_answers",
    "generation": 1,
    "previous_snapshot_manifest_ref": None,
}
DECLARED = "2026-10-14T08:40:00Z"
ISSUED = "2026-10-14T08:45:00Z"
EVIDENCE_ID = "fixture:application-reason"
EVIDENCE_BYTES = b"Authored candidate snapshot rationale; no legal or human authority."
RATIONALE = "Activate only exact candidate answer references; preserve all original uncertainty."


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def helper():
    spec = importlib.util.spec_from_file_location(
        "authored_adjudication_for_source_application_tests",
        Path(__file__).with_name("test_corpus_source_adjudication.py"),
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
    return {
        key: value[:]
        if key in {"signers", "adjudication_signers", "application_signers"}
        else deepcopy(value)
        for key, value in data.items()
    }


def refuse_replay(*_args, **_kwargs):
    pytest.fail("Untrusted application boundary reached complete upstream replay or authentication")


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_source_application

    return corpus_source_application


@pytest.fixture(scope="module")
def fixture_data(tmp_path_factory):
    source_helper = helper().helper().helper()
    original = source_helper.signed_case(
        source_owner, tmp_path_factory.mktemp("source-application-original-inputs")
    )
    typed = (
        helper()
        .helper()
        .signed_typed_case(response_owner, original, trust_mode="external_pinned_trust")
    )
    typed_report = helper().helper().assess(response_owner, typed)
    adjudication = helper().signed_case(
        adjudication_owner, typed, typed_report, mode="external_pinned_trust"
    )
    adjudication["adjudication_report"] = helper().assess(adjudication_owner, adjudication)
    return adjudication


def unit(data, ordinal=0):
    return (
        data["preparation"]["requests"][ordinal],
        data["preparation"]["subjects"][ordinal],
        data["adjudication_report"]["records"][ordinal],
    )


def declaration_pins(data, ordinal=0, **options):
    request, subject, group = unit(data, ordinal)
    return {
        "expected_request_sha256": sha(canonical_dag_json_bytes(request)),
        "expected_subject_sha256": sha(canonical_dag_json_bytes(subject)),
        "expected_adjudication_group_sha256": sha(canonical_dag_json_bytes(group)),
        "expected_preparation_manifest_sha256": sha(
            canonical_dag_json_bytes(data["preparation"]["manifest"])
        ),
        "expected_typed_response_manifest_sha256": sha(
            canonical_dag_json_bytes(data["typed_report"]["manifest"])
        ),
        "expected_adjudication_manifest_sha256": sha(
            canonical_dag_json_bytes(data["adjudication_report"]["manifest"])
        ),
        "declared_at_utc": DECLARED,
        "rationale": RATIONALE,
        "evidence_refs": [{"artifact_id": EVIDENCE_ID, "sha256": sha(EVIDENCE_BYTES)}],
        **options,
    }


def author(owner, data, ordinal=0, *, descriptor=None, **options):
    return owner.record_source_application_declaration(
        *unit(data, ordinal),
        deepcopy(DESCRIPTOR) if descriptor is None else descriptor,
        **declaration_pins(data, ordinal, **options),
    )


def replay_inputs(data, **options):
    return {
        "preparation": data["preparation"],
        "source_registry": data["registry"],
        "source_policy": data["policy"],
        "source_review_groups": data["groups"],
        "typed_response_report": data["typed_report"],
        "adjudication_registry": data["adjudication_registry"],
        "adjudication_policy": data["adjudication_policy"],
        "adjudication_groups": data["adjudication_groups"],
        **helper().assessment_arguments(data),
        **options,
    }


def authority(owner, data, *, mode="external_pinned_trust"):
    # Application is an explicit new action; it may reuse the selected
    # adjudicators under a separately pinned policy without inventing actors.
    registry = deepcopy(data["adjudication_registry"])
    registry["mode"] = mode
    policy = deepcopy(data["adjudication_policy"])
    policy.update(
        {
            "mode": mode,
            "policy_id": "fixture:source-application-policy",
            "registry_sha256": sha(canonical(registry)),
            "action": owner.ACTION,
            "audience": owner.AUDIENCE,
        }
    )
    return registry, policy, data["adjudication_signers"][:]


def sign_group(owner, data, body, ordinal=0):
    request, subject, adjudication = unit(data, ordinal)
    identity = f"fixture:application-body:{ordinal}"
    raw = canonical_dag_json_bytes(body)
    common_ref = {"artifact_id": identity, "sha256": sha(raw)}
    declaration = adjudication["declaration_record"]
    # All nine selected answers are resolved or not applicable by construction.
    source_claim = data["adjudication_groups"][ordinal]["reviews"][0]
    obligations = [
        {
            "slot_id": row["slot_id"],
            "disposition": row["disposition"],
            "evidence_refs": [deepcopy(common_ref)],
        }
        for row in source_claim["context_closure"]["obligations"]
    ]
    assert len(declaration["decisions"]) == len(obligations) == 9
    source_helper = helper().helper().helper()
    reviews = [
        signer.sign(
            {
                "schema": owner.CLAIM_SCHEMA,
                "action": owner.ACTION,
                "audience": owner.AUDIENCE,
                "review_id": f"fixture:application-review:{ordinal}:{index}",
                "key_id": key["key_id"],
                "principal_id": key["principal_id"],
                "role": role,
                "registry_sha256": sha(canonical(data["application_registry"])),
                "policy_sha256": sha(canonical(data["application_policy"])),
                "issued_at_utc": ISSUED,
                "expires_at_utc": source_helper.EXPIRES,
                "subject": deepcopy(subject),
                "interpretation": {
                    "decision": "support",
                    "reviewed_graph_sha256": subject["graph_sha256"],
                    "reviewed_ast_sha256": subject["ast_sha256"],
                    "rationale": "Support for exact candidate snapshot activation only.",
                    "ambiguity": [],
                },
                "context_closure": {
                    "status": "declared_complete",
                    "unresolved": [],
                    "obligations": deepcopy(obligations),
                },
            }
        )
        for index, (signer, key, role) in enumerate(
            zip(
                data["application_signers"],
                data["application_registry"]["keys"],
                trust_owner.ROLES,
                strict=True,
            )
        )
    ]
    return {
        "request_cid": request["record_cid"],
        "reviews": reviews,
        "app_artifact_id": identity,
        "evidence_artifacts": {identity: raw, EVIDENCE_ID: EVIDENCE_BYTES},
        "observed_artifact_sha256s": deepcopy(data["groups"][ordinal]["observed_artifact_sha256s"]),
        "observed_pins": deepcopy(data["groups"][ordinal]["observed_pins"]),
    }


def signed_case(owner, original, *, mode="external_pinned_trust"):
    data = clone_case(original)
    data["descriptor"] = deepcopy(DESCRIPTOR)
    data["application_registry"], data["application_policy"], data["application_signers"] = (
        authority(owner, data, mode=mode)
    )
    data["application_groups"] = []
    for ordinal, request in enumerate(data["preparation"]["requests"]):
        if ordinal == 0:
            data["application_groups"].append(
                sign_group(owner, data, author(owner, data, ordinal), ordinal)
            )
        else:
            data["application_groups"].append(
                {
                    "request_cid": request["record_cid"],
                    "reviews": [],
                    "app_artifact_id": None,
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
        {**pin, "app_artifact_id": group["app_artifact_id"]}
        for pin, group in zip(helper().helper().helper().group_pins(groups), groups, strict=True)
    ]


def assessment_arguments(data, **options):
    return {
        "expected_adjudication_manifest_sha256": sha(
            canonical_dag_json_bytes(data["adjudication_report"]["manifest"])
        ),
        "expected_application_registry_sha256": sha(canonical(data["application_registry"])),
        "expected_application_policy_sha256": sha(canonical(data["application_policy"])),
        "expected_application_group_pins": group_pins(data["application_groups"]),
        "adjudication_replay_inputs": replay_inputs(data),
        **options,
    }


def assess(owner, data, **options):
    return owner.assess_source_applications(
        data["adjudication_report"],
        data["application_registry"],
        data["application_policy"],
        data["application_groups"],
        data["descriptor"],
        **assessment_arguments(data, **options),
    )


def validate(owner, report, data, **options):
    return owner.validate_source_applications(
        report,
        data["adjudication_report"],
        data["application_registry"],
        data["application_policy"],
        data["application_groups"],
        data["descriptor"],
        **assessment_arguments(data, **options),
    )


def refresh_signatures(data):
    data["application_policy"]["registry_sha256"] = sha(canonical(data["application_registry"]))
    for group in data["application_groups"]:
        for index, review in enumerate(group["reviews"]):
            unsigned = {
                key: deepcopy(value)
                for key, value in review.items()
                if key not in {"signer_did", "signature_alg", "signature"}
            }
            unsigned["registry_sha256"] = sha(canonical(data["application_registry"]))
            unsigned["policy_sha256"] = sha(canonical(data["application_policy"]))
            group["reviews"][index] = data["application_signers"][index].sign(unsigned)


def replace_body(data, body, *, ordinal=0, resign=True):
    group = data["application_groups"][ordinal]
    identity = group["app_artifact_id"]
    raw = canonical_dag_json_bytes(body)
    group["evidence_artifacts"][identity] = raw
    if resign:
        for review in group["reviews"]:
            for obligation in review["context_closure"]["obligations"]:
                obligation["evidence_refs"] = [{"artifact_id": identity, "sha256": sha(raw)}]
        refresh_signatures(data)


@pytest.fixture(scope="module")
def baseline_data(fixture_data):
    from ipfs_datasets_py.logic.autoformal import corpus_source_application

    return signed_case(corpus_source_application, fixture_data)


@pytest.fixture(scope="module")
def baseline_report(baseline_data):
    from ipfs_datasets_py.logic.autoformal import corpus_source_application

    return assess(corpus_source_application, baseline_data)


def assert_narrow_effect(owner, report):
    for component, values in report.items():
        for row in [values] if component == "manifest" else values:
            assert row["view"] == "candidate"
            assert row["selected_occurrence"] is row["governing_source_binding"] is None
            assert reseal(row) == row
            assert len(canonical_dag_json_bytes(row)) <= contracts.MAX_RECORD_BYTES
            for flag in owner.FALSE_FLAGS:
                assert row[flag] is False
    assert report["manifest"]["counts"]["source_decisions_applied"] == 0
    assert report["manifest"]["counts"]["physical_governing_bindings_applied"] == 0
    assert all(row["original_contexts_remain_required_unavailable"] for row in report["records"])


def test_genesis_activation_copies_exact_signed_variants_without_changing_original_evidence_or_legal_authority(
    owner, baseline_data, baseline_report
):
    data, report = baseline_data, baseline_report
    assert set(report) == set(owner.COMPONENTS) == {"manifest", "pages", "records"}
    assert report["manifest"]["snapshot_descriptor"] == DESCRIPTOR
    assert report["manifest"]["activation_effect"] == owner.EFFECT
    assert report["manifest"]["adjudication_manifest_ref"] == ref(
        data["adjudication_report"]["manifest"]
    )
    assert [row["original_adjudication_group_record"] for row in report["records"]] == data[
        "adjudication_report"
    ]["records"]
    first = report["records"][0]
    original = first["original_adjudication_group_record"]
    assert original["authority_prerequisites_satisfied_under_selected_trust"] is True
    assert (
        first["authority_assessment"]["review_prerequisites_satisfied_under_selected_trust"] is True
    )
    assert first["source_answer_snapshot_activated_under_selected_profile"] is True
    assert first["application_content_status"] == "valid_declared_content"
    selected = [row["selected_variant_ref"] for row in original["declaration_record"]["decisions"]]
    assert first["activated_answer_variant_refs"] == selected
    assert len(selected) == 9
    raw = original["typed_response_group_record"]["raw_source_assessment_record"]["assessment"]
    assert "authenticated_context_declarations_disagree" in raw["blockers"]
    assert (
        first["deferred_review_slot_ids"]
        == data["preparation"]["requests"][0]["deferred_review_slot_ids"]
    )
    assert all(
        not row["source_answer_snapshot_activated_under_selected_profile"]
        and row["activated_answer_variant_refs"] == []
        for row in report["records"][1:]
    )
    counts = report["manifest"]["counts"]
    assert counts["groups"] == len(data["preparation"]["requests"])
    assert counts["activated_candidate_answer_snapshots"] == 1
    assert counts["activated_answer_slots"] == 9
    assert counts["blocked_groups"] == counts["groups"] - 1
    assert counts["blocked_active_slots"] == 9 * (counts["groups"] - 1)
    assert counts["deferred_questions"] == 7 * counts["groups"]
    assert_narrow_effect(owner, report)
    assert validate(owner, report, data) == report


def test_application_body_binds_the_complete_genesis_scope_and_all_original_roots(
    owner, fixture_data
):
    body = author(owner, fixture_data)
    request, subject, group = unit(fixture_data)
    assert body["request_ref"] == ref(request)
    assert body["subject_ref"] == ref(subject)
    assert body["adjudication_group_ref"] == ref(group)
    assert body["snapshot_descriptor"] == DESCRIPTOR
    assert body["source_review_scope_id"] == request["review_scope_id"]
    assert body["selected_answer_variant_refs"] == [
        row["selected_variant_ref"] for row in group["declaration_record"]["decisions"]
    ]
    assert body["status"] == "declared_unauthenticated_candidate_source_application"
    for key, value in declaration_pins(fixture_data).items():
        if key in body:
            assert body[key] == value


def test_missing_original_adjudication_can_never_become_an_application_body(owner, fixture_data):
    with pytest.raises(ValueError):
        author(owner, fixture_data, ordinal=1)


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "extra",
        "reordered",
        "duplicate",
        "foreign_slot",
        "unresolved",
        "unknown_decision",
        "missing_selected_ref",
        "nonnull_open",
        "unknown_choice_field",
    ],
)
def test_all_nine_adjudicated_slots_are_atomic_and_open_or_partial_selections_are_refused(
    owner, fixture_data, damage
):
    data = clone_case(fixture_data)
    group = data["adjudication_report"]["records"][0]
    declaration = group["declaration_record"]
    choices = declaration["decisions"]
    if damage == "missing":
        choices.pop()
    elif damage == "extra":
        choices.append(deepcopy(choices[-1]))
    elif damage == "reordered":
        choices[0], choices[1] = choices[1], choices[0]
    elif damage == "duplicate":
        choices[1] = deepcopy(choices[0])
    elif damage == "foreign_slot":
        choices[0]["slot_id"] = "fixture:foreign-slot"
    elif damage == "unresolved":
        choices[0]["decision"], choices[0]["selected_variant_ref"] = "unresolved", None
    elif damage == "unknown_decision":
        choices[0]["decision"] = "infer_equivalence"
    elif damage == "missing_selected_ref":
        del choices[0]["selected_variant_ref"]
    elif damage == "nonnull_open":
        choices[0]["decision"] = "unresolved"
    elif damage == "unknown_choice_field":
        choices[0]["legal_truth_verified"] = True
    group["declaration_record"] = reseal(declaration)
    data["adjudication_report"]["records"][0] = reseal(group)
    with pytest.raises(ValueError):
        author(owner, data)


def test_authoring_and_validation_do_not_replay_sources_or_authenticate_authority(
    owner, fixture_data, monkeypatch
):
    monkeypatch.setattr(trust_owner, "_assess_reviews", refuse_replay)
    monkeypatch.setattr(adjudication_owner, "validate_source_adjudications", refuse_replay)
    body = author(owner, fixture_data)
    assert reseal(body) == body
    assert body["view"] == "candidate"
    assert body["selected_occurrence"] is body["governing_source_binding"] is None
    for flag in owner.FALSE_FLAGS:
        assert body[flag] is False
    assert (
        owner.validate_source_application_declaration(
            body, *unit(fixture_data), deepcopy(DESCRIPTOR), **declaration_pins(fixture_data)
        )
        == body
    )


@pytest.mark.parametrize(
    "damage",
    [
        "missing_snapshot",
        "empty_snapshot",
        "invalid_snapshot_type",
        "missing_scope",
        "other_scope",
        "missing_generation",
        "bool_generation",
        "zero_generation",
        "negative_generation",
        "second_generation",
        "large_generation",
        "float_generation",
        "missing_predecessor",
        "nonnull_predecessor",
        "wrong_predecessor_type",
        "extra_field",
        "mutable_descriptor",
        "null_descriptor",
    ],
)
def test_only_explicit_genesis_candidate_scope_is_supported_without_implied_revision_history(
    owner, fixture_data, damage
):
    descriptor = deepcopy(DESCRIPTOR)
    if damage == "missing_snapshot":
        del descriptor["snapshot_id"]
    elif damage == "empty_snapshot":
        descriptor["snapshot_id"] = ""
    elif damage == "invalid_snapshot_type":
        descriptor["snapshot_id"] = True
    elif damage == "missing_scope":
        del descriptor["use_scope"]
    elif damage == "other_scope":
        descriptor["use_scope"] = "governing_legal_source"
    elif damage == "missing_generation":
        del descriptor["generation"]
    elif damage == "bool_generation":
        descriptor["generation"] = True
    elif damage == "zero_generation":
        descriptor["generation"] = 0
    elif damage == "negative_generation":
        descriptor["generation"] = -1
    elif damage == "second_generation":
        descriptor["generation"] = 2
    elif damage == "large_generation":
        descriptor["generation"] = 2147483647
    elif damage == "float_generation":
        descriptor["generation"] = 1.0
    elif damage == "missing_predecessor":
        del descriptor["previous_snapshot_manifest_ref"]
    elif damage == "nonnull_predecessor":
        descriptor["previous_snapshot_manifest_ref"] = ref(
            fixture_data["adjudication_report"]["manifest"]
        )
    elif damage == "wrong_predecessor_type":
        descriptor["previous_snapshot_manifest_ref"] = "infer_latest_previous"
    elif damage == "extra_field":
        descriptor["source_jurisdiction"] = "inferred from freeform answer"
    elif damage == "mutable_descriptor":
        descriptor = list(descriptor.items())
    elif damage == "null_descriptor":
        descriptor = None
    with pytest.raises(ValueError):
        owner.record_source_application_declaration(
            *unit(fixture_data), descriptor, **declaration_pins(fixture_data)
        )


@pytest.mark.parametrize(
    "pin_name",
    ["expected_request_sha256", "expected_subject_sha256", "expected_adjudication_group_sha256"],
)
@pytest.mark.parametrize("pin_value", ["0" * 64, "invalid", None, True])
def test_authoring_requires_independent_exact_record_identities(
    owner, fixture_data, pin_name, pin_value
):
    with pytest.raises(ValueError):
        author(owner, fixture_data, **{pin_name: pin_value})


@pytest.mark.parametrize(
    "pin_name",
    [
        "expected_preparation_manifest_sha256",
        "expected_typed_response_manifest_sha256",
        "expected_adjudication_manifest_sha256",
    ],
)
@pytest.mark.parametrize("pin_value", ["invalid", None, True])
def test_authoring_requires_explicit_full_manifest_pin_format(
    owner, fixture_data, pin_name, pin_value
):
    with pytest.raises(ValueError):
        author(owner, fixture_data, **{pin_name: pin_value})


@pytest.mark.parametrize("declared", [None, "", "2026-10-14T08:40:00+00:00", "2026-10-14", True, 1])
def test_application_time_is_an_explicit_canonical_utc_declaration(owner, fixture_data, declared):
    with pytest.raises(ValueError):
        author(owner, fixture_data, declared_at_utc=declared)


@pytest.mark.parametrize("rationale", [None, "", " ", True, 1, [], {}, "x" * (1024**2 + 1)])
def test_activation_rationale_requires_nonblank_bounded_declared_text(
    owner, fixture_data, rationale
):
    with pytest.raises(ValueError):
        author(owner, fixture_data, rationale=rationale)


@pytest.mark.parametrize(
    "damage",
    [
        "invalid_hash",
        "duplicate",
        "too_many",
        "unknown_field",
        "missing_identity",
        "mutable",
        "nonfinite",
        "cyclic",
    ],
)
def test_application_evidence_is_a_complete_closed_bounded_declaration(owner, fixture_data, damage):
    refs = [{"artifact_id": EVIDENCE_ID, "sha256": sha(EVIDENCE_BYTES)}]
    if damage == "invalid_hash":
        refs[0]["sha256"] = "invalid"
    elif damage == "duplicate":
        refs *= 2
    elif damage == "too_many":
        refs = [
            {"artifact_id": f"fixture:application-evidence:{n}", "sha256": sha(EVIDENCE_BYTES)}
            for n in range(9)
        ]
    elif damage == "unknown_field":
        refs[0]["verified_law"] = True
    elif damage == "missing_identity":
        del refs[0]["artifact_id"]
    elif damage == "mutable":
        refs = tuple(refs)
    elif damage == "nonfinite":
        refs[0]["sha256"] = float("nan")
    elif damage == "cyclic":
        refs.append(refs)
    with pytest.raises(ValueError):
        author(owner, fixture_data, evidence_refs=refs)


@pytest.mark.parametrize("foreign", ["request", "subject", "adjudication_group"])
def test_original_request_subject_and_adjudication_group_cannot_be_transplanted(
    owner, fixture_data, foreign
):
    arguments = list(unit(fixture_data))
    other = unit(fixture_data, 1)
    position = {"request": 0, "subject": 1, "adjudication_group": 2}[foreign]
    arguments[position] = other[position]
    with pytest.raises(ValueError):
        owner.record_source_application_declaration(
            *arguments, deepcopy(DESCRIPTOR), **declaration_pins(fixture_data)
        )


def test_no_signed_application_claims_create_no_activation_even_with_a_current_adjudication(
    owner, baseline_data
):
    data = clone_case(baseline_data)
    for group in data["application_groups"]:
        group["reviews"], group["app_artifact_id"], group["evidence_artifacts"] = [], None, {}
    report = assess(owner, data)
    assert report["manifest"]["counts"]["application_bodies"] == 0
    assert report["manifest"]["counts"]["authenticated_application_claims"] == 0
    assert report["manifest"]["counts"]["activated_candidate_answer_snapshots"] == 0
    assert report["manifest"]["counts"]["blocked_active_slots"] == 9 * len(report["records"])
    assert all(
        row["application_declaration_record"] is None and row["activated_answer_variant_refs"] == []
        for row in report["records"]
    )
    assert_narrow_effect(owner, report)


@pytest.mark.parametrize("mode", ["synthetic_fixture", "unavailable"])
def test_application_trust_must_be_current_production_shaped_and_never_verifies_human_identity(
    owner, baseline_data, mode
):
    data = clone_case(baseline_data)
    data["application_registry"]["mode"] = data["application_policy"]["mode"] = mode
    if mode == "unavailable":
        data["application_registry"]["keys"] = []
        for group in data["application_groups"]:
            group["reviews"], group["app_artifact_id"], group["evidence_artifacts"] = [], None, {}
        data["application_policy"]["registry_sha256"] = sha(canonical(data["application_registry"]))
    else:
        refresh_signatures(data)
    report = assess(owner, data)
    first = report["records"][0]
    assert first["source_answer_snapshot_activated_under_selected_profile"] is False
    assert first["activated_answer_variant_refs"] == []
    assert first["authority_assessment"]["registry_identity_authenticated_by_this_api"] is False
    assert first["authority_assessment"]["evaluation_clock_authenticated"] is False
    assert "production_trust_registry_unavailable" in first["authority_assessment"]["blockers"]
    assert_narrow_effect(owner, report)


@pytest.mark.parametrize(
    "failure",
    [
        "source_synthetic",
        "source_legal_missing",
        "source_bad_signature",
        "adjudication_synthetic",
        "adjudication_legal_missing",
        "adjudication_bad_signature",
        "adjudication_open",
    ],
)
def test_current_original_and_adjudication_prerequisites_cannot_be_repaired_by_a_new_valid_application_signature(
    owner, fixture_data, failure
):
    upstream = clone_case(fixture_data)
    if failure.startswith("source_"):
        if failure == "source_synthetic":
            upstream["registry"]["mode"] = upstream["policy"]["mode"] = "synthetic_fixture"
            helper().helper().helper().refresh_signatures(upstream)
        elif failure == "source_legal_missing":
            upstream["groups"][0]["reviews"] = upstream["groups"][0]["reviews"][1:]
            upstream["response_bindings"][0]["responses"] = upstream["response_bindings"][0][
                "responses"
            ][1:]
        elif failure == "source_bad_signature":
            upstream["groups"][0]["reviews"][0]["signature"] = "A" * 86
        upstream["typed_report"] = helper().helper().assess(response_owner, upstream)
        upstream = helper().signed_case(
            adjudication_owner, upstream, upstream["typed_report"], mode="external_pinned_trust"
        )
    else:
        if failure == "adjudication_synthetic":
            upstream["adjudication_registry"]["mode"] = upstream["adjudication_policy"]["mode"] = (
                "synthetic_fixture"
            )
            helper().refresh_signatures(upstream)
        elif failure == "adjudication_legal_missing":
            upstream["adjudication_groups"][0]["reviews"] = upstream["adjudication_groups"][0][
                "reviews"
            ][1:]
        elif failure == "adjudication_bad_signature":
            upstream["adjudication_groups"][0]["reviews"][0]["signature"] = "A" * 86
        elif failure == "adjudication_open":
            for claim in upstream["adjudication_groups"][0]["reviews"]:
                claim["context_closure"]["status"] = "open"
            helper().refresh_signatures(upstream)
    upstream["adjudication_report"] = helper().assess(adjudication_owner, upstream)
    assert (
        upstream["adjudication_report"]["records"][0]["declaration_content_status"]
        == "valid_declared_content"
    )
    assert (
        upstream["adjudication_report"]["records"][0][
            "authority_prerequisites_satisfied_under_selected_trust"
        ]
        is False
    )
    data = signed_case(owner, upstream)
    # Select application trust separately; synthetic adjudication does not
    # force the fresh application signatures to be synthetic too.
    data["application_registry"]["mode"] = data["application_policy"]["mode"] = (
        "external_pinned_trust"
    )
    refresh_signatures(data)
    report = assess(owner, data)
    first = report["records"][0]
    assert first["application_content_status"] == "valid_declared_content"
    assert (
        first["authority_assessment"]["review_prerequisites_satisfied_under_selected_trust"] is True
    )
    assert (
        "current_original_and_adjudication_authority_prerequisites_unavailable"
        in first["application_blockers"]
    )
    assert first["source_answer_snapshot_activated_under_selected_profile"] is False
    assert first["activated_answer_variant_refs"] == []
    assert_narrow_effect(owner, report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", source_owner.CLAIM_SCHEMA),
        ("schema", adjudication_owner.CLAIM_SCHEMA),
        ("schema", trust_owner.CLAIM_SCHEMA),
        ("action", adjudication_owner.ACTION),
        ("audience", adjudication_owner.AUDIENCE),
        ("role", "snapshot_administrator"),
    ],
)
def test_no_prior_review_domain_or_unrecognized_role_can_authorize_candidate_activation(
    owner, baseline_data, field, value
):
    data = clone_case(baseline_data)
    data["application_groups"][0]["reviews"][0][field] = value
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
        ("wrong_scope", "unauthorized_legal_scope"),
        ("wrong_role", "unauthorized_review_role"),
        ("future", "review_not_current"),
        ("expired", "review_not_current"),
        ("old", "review_age_exceeded"),
        ("revoked_key", "key_revoked"),
        ("revoked_principal", "principal_revoked"),
    ],
)
def test_valid_content_and_selected_variants_never_activate_through_failed_application_authority(
    owner, baseline_data, damage, blocker
):
    data = clone_case(baseline_data)
    claim = data["application_groups"][0]["reviews"][0]
    key = data["application_registry"]["keys"][0]
    if damage == "unknown_key":
        claim["key_id"] = "fixture:unknown-application-key"
    elif damage == "wrong_principal":
        claim["principal_id"] = "fixture:wrong-application-principal"
    elif damage == "wrong_subject":
        claim["subject"] = deepcopy(data["preparation"]["subjects"][1])
    elif damage == "wrong_graph":
        claim["interpretation"]["reviewed_graph_sha256"] = "0" * 64
    elif damage == "wrong_scope":
        key["scope_ids"] = ["fixture:unrelated-source-scope"]
    elif damage == "wrong_role":
        key["roles"] = ["formal_review"]
    elif damage == "future":
        claim["issued_at_utc"] = "2026-10-14T10:00:00Z"
    elif damage == "expired":
        claim["issued_at_utc"], claim["expires_at_utc"] = (
            "2026-10-13T08:00:00Z",
            "2026-10-14T08:00:00Z",
        )
    elif damage == "old":
        claim["issued_at_utc"] = "2026-10-12T08:00:00Z"
    elif damage == "revoked_key":
        key["revoked_at_utc"] = "2026-10-14T08:00:00Z"
    elif damage == "revoked_principal":
        data["application_registry"]["revoked_principals"] = [
            {"principal_id": key["principal_id"], "revoked_at_utc": "2026-10-14T08:00:00Z"}
        ]
    refresh_signatures(data)
    if damage == "bad_signature":
        data["application_groups"][0]["reviews"][0]["signature"] = "A" * 86
    report = assess(owner, data)
    first = report["records"][0]
    assert first["application_content_status"] == "valid_declared_content"
    assert blocker in first["authority_assessment"]["reviews"][0]["blockers"]
    assert first["source_answer_snapshot_activated_under_selected_profile"] is False
    assert first["activated_answer_variant_refs"] == []
    assert (
        first["original_adjudication_group_record"]
        == baseline_data["adjudication_report"]["records"][0]
    )
    assert_narrow_effect(owner, report)


@pytest.mark.parametrize("missing", ["legal", "formal", "both"])
def test_two_distinct_application_roles_are_required_without_fabricating_missing_actors(
    owner, baseline_data, missing
):
    data = clone_case(baseline_data)
    group = data["application_groups"][0]
    if missing == "both":
        group["reviews"], group["app_artifact_id"], group["evidence_artifacts"] = [], None, {}
    else:
        group["reviews"] = [group["reviews"][1 if missing == "legal" else 0]]
    report = assess(owner, data)
    assert report["records"][0]["source_answer_snapshot_activated_under_selected_profile"] is False
    assert report["records"][0]["activated_answer_variant_refs"] == []
    assert_narrow_effect(owner, report)


def test_two_application_keys_for_one_principal_cannot_supply_independent_role_authority(
    owner, baseline_data
):
    data = clone_case(baseline_data)
    principal = data["application_registry"]["keys"][0]["principal_id"]
    data["application_registry"]["keys"][1]["principal_id"] = principal
    data["application_groups"][0]["reviews"][1]["principal_id"] = principal
    refresh_signatures(data)
    report = assess(owner, data)
    first = report["records"][0]
    assert first["authority_assessment"]["authenticated_evidence_count"] == 2
    assert (
        "distinct_authorized_review_principals_missing" in first["authority_assessment"]["blockers"]
    )
    assert first["source_answer_snapshot_activated_under_selected_profile"] is False
    assert first["activated_answer_variant_refs"] == []
    assert_narrow_effect(owner, report)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_cid",
        "invalid_cid",
        "missing_hash",
        "invalid_hash",
        "missing_schema",
        "wrong_schema",
        "unknown_field",
        "duplicate_ref",
        "unknown_ref",
    ],
)
def test_authoring_requires_full_distinct_variant_references_from_the_considered_population(
    owner, fixture_data, damage
):
    data = clone_case(fixture_data)
    group = data["adjudication_report"]["records"][0]
    body = group["declaration_record"]
    selected = body["decisions"][0]["selected_variant_ref"]
    if damage == "missing_cid":
        del selected["record_cid"]
    elif damage == "invalid_cid":
        selected["record_cid"] = "not-a-cid"
    elif damage == "missing_hash":
        del selected["sha256"]
    elif damage == "invalid_hash":
        selected["sha256"] = "not-a-sha"
    elif damage == "missing_schema":
        del selected["schema"]
    elif damage == "wrong_schema":
        selected["schema"] = source_owner.REQUEST_SCHEMA
    elif damage == "unknown_field":
        selected["governing_source_verified"] = True
    elif damage == "duplicate_ref":
        body["decisions"][1]["selected_variant_ref"] = deepcopy(selected)
    elif damage == "unknown_ref":
        selected["record_cid"] = data["preparation"]["requests"][0]["record_cid"]
    group["declaration_record"] = reseal(body)
    data["adjudication_report"]["records"][0] = reseal(group)
    with pytest.raises(ValueError):
        author(owner, data)


@pytest.mark.parametrize(
    "field",
    [
        "snapshot_descriptor",
        "request_ref",
        "subject_ref",
        "adjudication_group_ref",
        "preparation_manifest_sha256",
        "typed_response_manifest_sha256",
        "adjudication_manifest_sha256",
        "queue_ordinal",
        "source_review_scope_id",
        "selected_answer_variant_refs",
        "profile",
        "activation_effect",
        "status",
    ],
)
def test_resealed_and_resigned_application_body_cannot_rebind_scope_roots_or_signed_choices(
    owner, baseline_data, field
):
    data = clone_case(baseline_data)
    group = data["application_groups"][0]
    body = json.loads(group["evidence_artifacts"][group["app_artifact_id"]])
    if field == "snapshot_descriptor":
        body[field]["snapshot_id"] = "fixture:foreign-snapshot"
    elif field.endswith("_ref"):
        body[field]["sha256"] = "0" * 64
    elif field.endswith("_sha256"):
        body[field] = "0" * 64
    elif field == "queue_ordinal":
        body[field] += 1
    elif field == "selected_answer_variant_refs":
        body[field].pop()
    else:
        body[field] = "unrecognized-or-foreign-scope"
    replace_body(data, reseal(body))
    report = assess(owner, data)
    first = report["records"][0]
    assert first["application_content_status"] == "rejected"
    assert first["application_declaration_record"] is None
    assert first["source_answer_snapshot_activated_under_selected_profile"] is False
    assert first["activated_answer_variant_refs"] == []
    assert_narrow_effect(owner, report)


@pytest.mark.parametrize(
    "damage",
    [
        "different_body_id",
        "wrong_body_hash",
        "missing_obligation",
        "reordered_obligations",
        "duplicate_obligation",
        "wrong_disposition",
        "extra_ref",
        "missing_ref",
        "open",
        "unresolved",
    ],
)
def test_each_role_must_attest_the_exact_complete_common_application_body(
    owner, baseline_data, damage
):
    data = clone_case(baseline_data)
    group = data["application_groups"][0]
    closure = group["reviews"][1]["context_closure"]
    if damage == "different_body_id":
        alias = "fixture:application-body-alias"
        group["evidence_artifacts"][alias] = group["evidence_artifacts"][group["app_artifact_id"]]
        for row in closure["obligations"]:
            row["evidence_refs"][0]["artifact_id"] = alias
    elif damage == "wrong_body_hash":
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
    elif damage == "extra_ref":
        closure["obligations"][0]["evidence_refs"].append(
            {"artifact_id": EVIDENCE_ID, "sha256": sha(EVIDENCE_BYTES)}
        )
    elif damage == "missing_ref":
        closure["obligations"][0]["evidence_refs"] = []
    elif damage == "open":
        closure["status"] = "open"
    elif damage == "unresolved":
        closure["unresolved"] = [closure["obligations"][0]["slot_id"]]
    refresh_signatures(data)
    report = assess(owner, data)
    first = report["records"][0]
    assert first["application_content_status"] == "rejected"
    assert any(
        "exact_complete_signed_nine_slot_activation" in value for value in first["content_blockers"]
    )
    assert first["source_answer_snapshot_activated_under_selected_profile"] is False
    assert first["activated_answer_variant_refs"] == []
    assert_narrow_effect(owner, report)


@pytest.mark.parametrize("damage", ["missing", "changed", "self_ref"])
def test_application_supporting_evidence_requires_exact_nonself_supplied_bytes(
    owner, baseline_data, damage
):
    data = clone_case(baseline_data)
    group = data["application_groups"][0]
    if damage == "missing":
        del group["evidence_artifacts"][EVIDENCE_ID]
    elif damage == "changed":
        group["evidence_artifacts"][EVIDENCE_ID] += b" changed"
    elif damage == "self_ref":
        body = json.loads(group["evidence_artifacts"][group["app_artifact_id"]])
        body["evidence_refs"] = [
            {
                "artifact_id": group["app_artifact_id"],
                "sha256": sha(group["evidence_artifacts"][group["app_artifact_id"]]),
            }
        ]
        replace_body(data, reseal(body))
    report = assess(owner, data)
    first = report["records"][0]
    assert first["application_content_status"] == "rejected"
    assert any(
        "missing_changed_or_self_referential" in value for value in first["content_blockers"]
    )
    assert first["source_answer_snapshot_activated_under_selected_profile"] is False
    assert first["activated_answer_variant_refs"] == []
    assert_narrow_effect(owner, report)


@pytest.mark.parametrize(
    "damage,blocker",
    [
        ("predates_body", "application_predates_adjudication"),
        ("predates_authority", "application_predates_adjudication"),
        ("after_evaluation", "application_declared_after_evaluation"),
        ("claim_predates_body", "application_authority_claim_predates_common_declaration"),
    ],
)
def test_application_chronology_preserves_all_prior_declaration_and_authority_intervals(
    owner, baseline_data, damage, blocker
):
    data = clone_case(baseline_data)
    group = data["application_groups"][0]
    body = json.loads(group["evidence_artifacts"][group["app_artifact_id"]])
    if damage == "predates_body":
        body["declared_at_utc"] = "2026-10-14T08:05:00Z"
    elif damage == "predates_authority":
        body["declared_at_utc"] = "2026-10-14T08:20:00Z"
    elif damage == "after_evaluation":
        body["declared_at_utc"] = "2026-10-14T10:00:00Z"
    elif damage == "claim_predates_body":
        group["reviews"][0]["issued_at_utc"] = "2026-10-14T08:35:00Z"
    replace_body(data, reseal(body))
    report = assess(owner, data)
    first = report["records"][0]
    assert first["application_content_status"] == "valid_declared_content"
    assert blocker in first["application_blockers"]
    assert first["source_answer_snapshot_activated_under_selected_profile"] is False
    assert first["activated_answer_variant_refs"] == []
    assert first["authority_assessment"]["evaluation_clock_authenticated"] is False
    assert_narrow_effect(owner, report)


@pytest.mark.parametrize("overlap", ["principal", "did", "public_key"])
def test_relabeling_any_original_reviewer_as_application_authority_never_creates_independence(
    owner, baseline_data, overlap
):
    data = clone_case(baseline_data)
    original = data["registry"]["keys"][0]
    key = data["application_registry"]["keys"][0]
    claim = data["application_groups"][0]["reviews"][0]
    if overlap == "principal":
        key["principal_id"] = claim["principal_id"] = original["principal_id"]
        expected = "application_authority_is_a_supplied_original_reviewer"
    elif overlap == "did":
        signer = data["application_signers"][0]
        data["application_signers"][0] = Ed25519Signer(original["signer_did"], signer.private_key)
        key["signer_did"] = original["signer_did"]
        expected = "application_authority_reuses_an_original_reviewer_did"
    elif overlap == "public_key":
        data["application_signers"][0] = Ed25519Signer(
            key["signer_did"], data["signers"][0].private_key
        )
        key["public_key_hex"] = original["public_key_hex"]
        expected = "application_authority_reuses_an_original_reviewer_public_key"
    refresh_signatures(data)
    report = assess(owner, data)
    first = report["records"][0]
    assert first["authority_assessment"]["authenticated_evidence_count"] == 2
    assert expected in first["application_blockers"]
    assert first["source_answer_snapshot_activated_under_selected_profile"] is False
    assert first["activated_answer_variant_refs"] == []
    assert_narrow_effect(owner, report)


@pytest.mark.parametrize(
    "damage", ["unavailable_dependency", "changed_dependency", "changed_source_pin"]
)
def test_stale_or_unavailable_source_observations_block_activation_without_dropping_population(
    owner, baseline_data, damage
):
    data = clone_case(baseline_data)
    group = data["application_groups"][0]
    required = data["preparation"]["subjects"][0]["required_dependency_ids"][0]
    if damage == "unavailable_dependency":
        group["observed_artifact_sha256s"][required] = None
    elif damage == "changed_dependency":
        group["observed_artifact_sha256s"][required] = "0" * 64
    elif damage == "changed_source_pin":
        values = next(values for values in group["observed_pins"].values() if values)
        values[next(iter(values))] = "0" * 64
    report = assess(owner, data)
    first = report["records"][0]
    assert "required_dependency_closure_not_current" in first["authority_assessment"]["blockers"]
    assert first["source_answer_snapshot_activated_under_selected_profile"] is False
    assert first["activated_answer_variant_refs"] == []
    assert len(report["records"]) == len(data["preparation"]["requests"])
    assert_narrow_effect(owner, report)


def test_a_body_signed_for_another_named_genesis_snapshot_cannot_be_transplanted(
    owner, baseline_data
):
    data = clone_case(baseline_data)
    data["descriptor"]["snapshot_id"] = "fixture:second-named-candidate-snapshot"
    report = assess(owner, data)
    assert report["records"][0]["application_content_status"] == "rejected"
    assert report["records"][0]["source_answer_snapshot_activated_under_selected_profile"] is False
    assert report["records"][0]["activated_answer_variant_refs"] == []
    assert_narrow_effect(owner, report)


@pytest.mark.parametrize(
    "pin_name",
    [
        "expected_adjudication_manifest_sha256",
        "expected_application_registry_sha256",
        "expected_application_policy_sha256",
    ],
)
def test_independent_adjudication_and_application_trust_roots_are_required_before_upstream_replay(
    owner, baseline_data, monkeypatch, pin_name
):
    monkeypatch.setattr(adjudication_owner, "validate_source_adjudications", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, baseline_data, **{pin_name: "0" * 64})


@pytest.mark.parametrize(
    "damage",
    [
        "missing_required",
        "unknown_callback",
        "not_object",
        "wrong_original_registry",
        "wrong_adjudication_registry",
        "wrong_preparation",
        "wrong_typed_root",
    ],
)
def test_replay_contract_cannot_omit_override_or_repair_upstream_generations(
    owner, baseline_data, monkeypatch, damage
):
    replay = replay_inputs(baseline_data)
    if damage == "missing_required":
        del replay["preparation"]
    elif damage == "unknown_callback":
        replay["source_loader"] = "trust this callback"
    elif damage == "not_object":
        replay = list(replay.items())
    elif damage == "wrong_original_registry":
        replay["expected_registry_sha256"] = "0" * 64
    elif damage == "wrong_adjudication_registry":
        replay["expected_adjudication_registry_sha256"] = "0" * 64
    elif damage == "wrong_preparation":
        replay["expected_preparation_manifest_sha256"] = "0" * 64
    elif damage == "wrong_typed_root":
        replay["expected_typed_response_manifest_sha256"] = "0" * 64
    if damage != "wrong_typed_root":
        monkeypatch.setattr(adjudication_owner, "validate_source_adjudications", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, baseline_data, adjudication_replay_inputs=replay)


@pytest.mark.parametrize(
    "damage",
    [
        "subset",
        "extra",
        "reordered",
        "duplicate",
        "foreign_request",
        "pins_subset",
        "pins_reordered",
        "wrong_reviews_hash",
        "wrong_evidence_hash",
        "wrong_observation_hash",
        "wrong_pin_hash",
        "missing_body",
        "wrong_body_id",
        "empty_with_body",
        "mutable_body",
        "unknown_group_field",
        "unknown_pin_field",
    ],
)
def test_complete_application_custody_cannot_filter_alias_reorder_or_reseal_populations_before_replay(
    owner, baseline_data, monkeypatch, damage
):
    data = clone_case(baseline_data)
    groups = data["application_groups"]
    pins = group_pins(groups)
    if damage == "subset":
        groups.pop()
    elif damage == "extra":
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
    elif damage == "wrong_reviews_hash":
        pins[0]["reviews_sha256"] = "0" * 64
    elif damage == "wrong_evidence_hash":
        pins[0]["evidence_sha256s"][groups[0]["app_artifact_id"]] = "0" * 64
    elif damage == "wrong_observation_hash":
        pins[0]["observed_artifacts_sha256"] = "0" * 64
    elif damage == "wrong_pin_hash":
        pins[0]["observed_pins_sha256"] = "0" * 64
    elif damage == "missing_body":
        del groups[0]["evidence_artifacts"][groups[0]["app_artifact_id"]]
    elif damage == "wrong_body_id":
        groups[0]["app_artifact_id"] = pins[0]["app_artifact_id"] = (
            "fixture:missing-application-body"
        )
    elif damage == "empty_with_body":
        groups[1]["app_artifact_id"] = pins[1]["app_artifact_id"] = (
            "fixture:unsolicited-application-body"
        )
    elif damage == "mutable_body":
        groups[0]["evidence_artifacts"][groups[0]["app_artifact_id"]] = bytearray(b"mutable")
    elif damage == "unknown_group_field":
        groups[0]["authorize_any_context"] = True
    elif damage == "unknown_pin_field":
        pins[0]["choose_prefix"] = True
    monkeypatch.setattr(adjudication_owner, "validate_source_adjudications", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, data, expected_application_group_pins=pins)


@pytest.mark.parametrize("invalid", [None, True, False, 0, -1, 1.5, "1", []])
def test_application_limits_are_exact_positive_lower_only_integers(owner, fixture_data, invalid):
    with pytest.raises(ValueError):
        author(owner, fixture_data, limits={"max_declaration_bytes": invalid})


@pytest.mark.parametrize(
    "limits", [{"unknown": 1}, {"max_declaration_bytes": 1024**2 + 1}, [], True]
)
def test_fixed_application_budget_profile_cannot_be_raised_or_redefined(
    owner, fixture_data, limits
):
    with pytest.raises(ValueError):
        author(owner, fixture_data, limits=limits)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_groups": 1},
        {"max_declaration_bytes": 1},
        {"max_group_bytes": 1},
        {"max_batch_bytes": 1},
    ],
)
def test_known_complete_application_input_caps_refuse_before_upstream_replay(
    owner, baseline_data, monkeypatch, limits
):
    monkeypatch.setattr(adjudication_owner, "validate_source_adjudications", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, baseline_data, limits=limits)


@pytest.mark.parametrize("population", ["source", "adjudication", "application"])
def test_every_later_evidence_population_budget_passes_before_the_first_indexed_application_body_hash(
    owner, baseline_data, monkeypatch, population
):
    data = clone_case(baseline_data)
    group = data["application_groups"][0]
    indexed = group["evidence_artifacts"][group["app_artifact_id"]]
    key = {
        "source": "groups",
        "adjudication": "adjudication_groups",
        "application": "application_groups",
    }[population]
    data[key][1]["evidence_artifacts"]["fixture:later-over-budget"] = b"x" * (8 * 1024**2 + 1)
    kwargs = assessment_arguments(data)
    real_sha = source_owner._sha

    def guard(raw):
        if raw == indexed:
            pytest.fail(
                "Indexed application body was hashed before every later evidence budget passed"
            )
        return real_sha(raw)

    monkeypatch.setattr(source_owner, "_sha", guard)
    monkeypatch.setattr(adjudication_owner, "validate_source_adjudications", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, data, **kwargs)


def test_complete_application_group_json_and_raw_evidence_budget_passes_before_its_first_body_hash(
    owner, baseline_data, monkeypatch
):
    data = clone_case(baseline_data)
    group = data["application_groups"][0]
    indexed = group["evidence_artifacts"][group["app_artifact_id"]]
    raw_bytes = sum(len(body) for body in group["evidence_artifacts"].values())
    real_sha = source_owner._sha

    def guard(raw):
        if raw == indexed:
            pytest.fail(
                "Indexed application body was hashed before JSON plus raw evidence budget passed"
            )
        return real_sha(raw)

    monkeypatch.setattr(source_owner, "_sha", guard)
    monkeypatch.setattr(adjudication_owner, "validate_source_adjudications", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, data, limits={"max_group_bytes": raw_bytes + 1})


def test_complete_original_evidence_budgets_pass_before_an_early_original_response_body_hash(
    owner, baseline_data, monkeypatch
):
    data = clone_case(baseline_data)
    entry = data["response_bindings"][0]["responses"][0]
    indexed = data["groups"][0]["evidence_artifacts"][entry["artifact_id"]]
    data["application_groups"][1]["evidence_artifacts"]["fixture:later-application-over-budget"] = (
        b"x" * (8 * 1024**2 + 1)
    )
    kwargs = assessment_arguments(data)
    real_sha = source_owner._sha

    def guard(raw):
        if raw == indexed:
            pytest.fail(
                "Original response body was hashed before later application evidence passed"
            )
        return real_sha(raw)

    monkeypatch.setattr(source_owner, "_sha", guard)
    monkeypatch.setattr(adjudication_owner, "validate_source_adjudications", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, data, **kwargs)


def test_complete_adjudication_owner_regenerates_once_for_all_original_requests(
    owner, baseline_data, monkeypatch
):
    calls = []
    original = adjudication_owner.validate_source_adjudications

    def count(*args, **kwargs):
        calls.append(len(kwargs["preparation"]["requests"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(adjudication_owner, "validate_source_adjudications", count)
    report = assess(owner, baseline_data)
    assert calls == [len(baseline_data["preparation"]["requests"])]
    assert [row["queue_ordinal"] for row in report["records"]] == list(
        range(len(report["records"]))
    )


def test_application_producer_drift_during_shared_signature_verification_refuses_the_whole_result(
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
        return (
            {**initial, "fixture:changed-application-producer": "0" * 64} if changed[0] else initial
        )

    monkeypatch.setattr(trust_owner, "_verify_signature", verify)
    monkeypatch.setattr(owner, "_pins", pins)
    with pytest.raises(ValueError):
        assess(owner, baseline_data)


def test_returned_snapshot_and_all_original_evidence_do_not_alias_caller_containers(
    owner, baseline_data
):
    data = clone_case(baseline_data)
    before = clone_case(data)
    report = assess(owner, data)
    assert data == before
    report["records"][0]["original_adjudication_group_record"]["deferred_review_slot_ids"].append(
        "fixture:changed-output"
    )
    report["records"][0]["activated_answer_variant_refs"][0]["sha256"] = "0" * 64
    report["manifest"]["snapshot_descriptor"]["snapshot_id"] = "fixture:changed-output-snapshot"
    assert data == before


def rebind_report(report):
    rows = {row["queue_ordinal"]: row for row in report["records"]}
    for index, page in enumerate(report["pages"]):
        for entry in page["entries"]:
            entry["group_record_ref"] = ref(rows[entry["ordinal"]])
        report["pages"][index] = reseal(page)
    for index, page in enumerate(report["pages"]):
        report["manifest"]["page_refs"][index].update(ref(page))
    report["manifest"] = reseal(report["manifest"])


@pytest.mark.parametrize(
    "damage",
    [
        "changed_upstream",
        "erased_raw_disagreement",
        "changed_activated_ref",
        "activate_blocked",
        "drop_group",
        "reorder_groups",
        "physical_binding_true",
        "semantic_true",
        "changed_descriptor",
        "changed_counts",
        "changed_producer",
    ],
)
def test_repaired_snapshot_seals_and_inventories_cannot_replace_complete_independent_regeneration(
    owner, baseline_data, baseline_report, damage
):
    report = deepcopy(baseline_report)
    row = report["records"][0]
    if damage == "changed_upstream":
        row["original_adjudication_group_record"][
            "authority_prerequisites_satisfied_under_selected_trust"
        ] = False
    elif damage == "erased_raw_disagreement":
        row["original_adjudication_group_record"]["typed_response_group_record"][
            "raw_source_assessment_record"
        ]["assessment"]["blockers"] = []
    elif damage == "changed_activated_ref":
        row["activated_answer_variant_refs"][0]["sha256"] = "0" * 64
    elif damage == "activate_blocked":
        report["records"][1]["source_answer_snapshot_activated_under_selected_profile"] = True
        report["records"][1]["activated_answer_variant_refs"] = deepcopy(
            row["activated_answer_variant_refs"]
        )
    elif damage == "drop_group":
        report["records"].pop()
    elif damage == "reorder_groups":
        report["records"][0], report["records"][1] = report["records"][1], report["records"][0]
    elif damage == "physical_binding_true":
        row["physical_governing_bindings_applied"] = True
    elif damage == "semantic_true":
        row["adjudicated_source_meaning_verified"] = True
    elif damage == "changed_descriptor":
        report["manifest"]["snapshot_descriptor"]["generation"] = 2
    elif damage == "changed_counts":
        report["manifest"]["counts"]["activated_candidate_answer_snapshots"] += 1
    elif damage == "changed_producer":
        report["manifest"]["producer_pins"]["fixture:invented-owner"] = "0" * 64
    report["records"] = [reseal(value) for value in report["records"]]
    if damage != "drop_group":
        rebind_report(report)
    else:
        report["manifest"] = reseal(report["manifest"])
    with pytest.raises(ValueError):
        validate(owner, report, baseline_data)


@pytest.mark.parametrize(
    "damage",
    [
        "extra_component",
        "missing_component",
        "mutable_records",
        "too_many_records",
        "oversized_record",
        "unknown_field",
    ],
)
def test_offered_snapshot_shape_and_size_are_checked_before_upstream_regeneration(
    owner, baseline_data, baseline_report, monkeypatch, damage
):
    report = deepcopy(baseline_report)
    if damage == "extra_component":
        report["unexpected"] = []
    elif damage == "missing_component":
        del report["records"]
    elif damage == "mutable_records":
        report["records"] = tuple(report["records"])
    elif damage == "too_many_records":
        report["records"] *= 8192 // len(report["records"]) + 1
    elif damage == "oversized_record":
        report["records"][0]["content_blockers"] = ["x" * (1024**2 + 1)]
    elif damage == "unknown_field":
        report["records"][0]["caller_approved"] = True
        report["records"][0] = reseal(report["records"][0])
    monkeypatch.setattr(owner, "assess_source_applications", refuse_replay)
    with pytest.raises(ValueError):
        validate(owner, report, baseline_data)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_page_bytes": 1},
        {"max_pages": 1, "max_groups_per_page": 1},
        {"max_collection_bytes": 1},
    ],
)
def test_complete_snapshot_output_caps_refuse_a_whole_population_without_activating_a_prefix(
    owner, baseline_data, limits
):
    with pytest.raises(ValueError):
        assess(owner, baseline_data, limits=limits)


def test_exact_lowered_paging_preserves_every_activated_and_blocked_original_request(
    owner, baseline_data
):
    report = assess(owner, baseline_data, limits={"max_groups_per_page": 1})
    assert len(report["pages"]) == len(report["records"])
    entries = [entry for page in report["pages"] for entry in page["entries"]]
    assert [entry["ordinal"] for entry in entries] == list(range(len(report["records"])))
    assert [entry["group_record_ref"] for entry in entries] == [
        ref(row) for row in report["records"]
    ]
    assert report["manifest"]["counts"]["activated_candidate_answer_snapshots"] == 1
    assert_narrow_effect(owner, report)


def test_a_rejected_original_reviewer_in_another_request_cannot_be_reused_as_application_principal(
    owner, fixture_data
):
    upstream = clone_case(fixture_data)
    foreign = deepcopy(upstream["groups"][0]["reviews"][0])
    foreign["review_id"] = "fixture:cross-request-source-review"
    foreign["principal_id"] = "fixture:cross-request-source-principal"
    foreign["signature"] = "A" * 86
    upstream["groups"][1]["reviews"] = [foreign]
    upstream["groups"][1]["evidence_artifacts"] = deepcopy(
        upstream["groups"][0]["evidence_artifacts"]
    )
    binding = upstream["response_bindings"][0]["responses"][0]
    upstream["response_bindings"][1]["responses"] = [
        {**deepcopy(binding), "review_id": foreign["review_id"]}
    ]
    upstream["typed_report"] = helper().helper().assess(response_owner, upstream)
    upstream = helper().signed_case(
        adjudication_owner, upstream, upstream["typed_report"], mode="external_pinned_trust"
    )
    upstream["adjudication_report"] = helper().assess(adjudication_owner, upstream)
    assert (
        upstream["adjudication_report"]["records"][0][
            "authority_prerequisites_satisfied_under_selected_trust"
        ]
        is True
    )
    data = signed_case(owner, upstream)
    data["application_registry"]["keys"][0]["principal_id"] = foreign["principal_id"]
    data["application_groups"][0]["reviews"][0]["principal_id"] = foreign["principal_id"]
    refresh_signatures(data)
    report = assess(owner, data)
    first = report["records"][0]
    assert first["authority_assessment"]["authenticated_evidence_count"] == 2
    assert "application_authority_is_a_supplied_original_reviewer" in first["application_blockers"]
    assert first["source_answer_snapshot_activated_under_selected_profile"] is False
    assert first["activated_answer_variant_refs"] == []
    assert_narrow_effect(owner, report)


def test_a_new_explicit_adjudicated_alternative_changes_snapshot_roots_and_keeps_every_competing_variant(
    owner, fixture_data, baseline_report
):
    upstream = clone_case(fixture_data)
    helper().helper().mutate_response(
        upstream,
        lambda response: response["answers"][0].update(
            {"rationale": "A distinct authored alternative retained for explicit adjudication."}
        ),
        index=1,
    )
    upstream["typed_report"] = helper().helper().assess(response_owner, upstream)
    upstream = helper().signed_case(
        adjudication_owner, upstream, upstream["typed_report"], mode="external_pinned_trust"
    )
    decisions = helper().choices(upstream)
    variants = helper().unit(upstream)[3][0]["answer_variant_refs"]
    assert len(variants) == 2
    decisions[0]["selected_variant_ref"] = deepcopy(variants[1])
    new_body = helper().author(adjudication_owner, upstream, decisions)
    upstream["adjudication_groups"][0] = helper().sign_group(adjudication_owner, upstream, new_body)
    upstream["adjudication_report"] = helper().assess(adjudication_owner, upstream)
    data = signed_case(owner, upstream)
    before = deepcopy(baseline_report)
    report = assess(owner, data)
    first = report["records"][0]
    assert first["source_answer_snapshot_activated_under_selected_profile"] is True
    assert first["activated_answer_variant_refs"][0] == variants[1]
    original = first["original_adjudication_group_record"]["declaration_record"]
    assert len(original["considered_answer_variant_refs"]) == 10
    assert all(value in original["considered_answer_variant_refs"] for value in variants)
    assert (
        report["manifest"]["adjudication_manifest_ref"]
        != baseline_report["manifest"]["adjudication_manifest_ref"]
    )
    assert ref(report["manifest"]) != ref(baseline_report["manifest"])
    assert baseline_report == before
    assert first["snapshot_name_uniqueness_verified"] is False
    assert first["historical_predecessor_qualified"] is False
    assert_narrow_effect(owner, report)


@pytest.mark.parametrize(
    "damage", ["changed_rationale", "changed_time", "changed_selected", "historical_true"]
)
def test_repaired_authored_application_declarations_require_exact_independent_input_regeneration(
    owner, fixture_data, damage
):
    body = author(owner, fixture_data)
    if damage == "changed_rationale":
        body["rationale"] += " altered"
    elif damage == "changed_time":
        body["declared_at_utc"] = "2026-10-14T08:41:00Z"
    elif damage == "changed_selected":
        body["selected_answer_variant_refs"][0]["sha256"] = "0" * 64
    elif damage == "historical_true":
        body["historical_predecessor_qualified"] = True
    with pytest.raises(ValueError):
        owner.validate_source_application_declaration(
            reseal(body),
            *unit(fixture_data),
            deepcopy(DESCRIPTOR),
            **declaration_pins(fixture_data),
        )


def test_public_import_keeps_models_source_decoders_crypto_and_default_authorities_unloaded():
    program = r"""
import sys
from ipfs_datasets_py.logic.autoformal import corpus_source_application as owner
for prefix in ('torch', 'transformers', 'pyarrow'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules)
assert 'ipfs_datasets_py.logic.autoformal.legal_source_review_handoff' not in sys.modules
assert 'ipfs_datasets_py.logic.profile_g' not in sys.modules
print('inert source application import verified')
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
    assert result.stdout.strip() == "inert source application import verified"

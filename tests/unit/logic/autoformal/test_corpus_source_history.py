"""Complete candidate history replay never turns old eligible flags into law.

All source texts, identities, keys, answers and clocks are engineering fixtures.
External-shaped trust exercises a selected technical premise, never an actual
legal review, authoritative head, physical source binding, graph or Lean target.
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
from ipfs_datasets_py.logic.autoformal import corpus_source_application as genesis_owner
from ipfs_datasets_py.logic.autoformal import corpus_source_review as source_owner
from ipfs_datasets_py.logic.autoformal import corpus_source_review_responses as response_owner
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust_owner
from ipfs_datasets_py.logic.profile_g import Ed25519Signer
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

GENESIS_ID = "fixture:history-genesis"
REVISION_ID = "fixture:history-revision:2"
DECLARED = "2026-10-14T09:00:00Z"
ISSUED = "2026-10-14T09:00:00Z"
EVIDENCE_ID = "fixture:history-revision-reason"
EVIDENCE_BYTES = b"Engineering revision evidence; no actual law or human authority."
RATIONALE = (
    "Fresh explicit candidate choice references, with every prior source declaration retained."
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def helper():
    spec = importlib.util.spec_from_file_location(
        "authored_genesis_for_source_history_tests",
        Path(__file__).with_name("test_corpus_source_application.py"),
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
        if key in {"signers", "adjudication_signers", "application_signers", "revision_signers"}
        else deepcopy(value)
        for key, value in data.items()
    }


def refuse_replay(*_args, **_kwargs):
    pytest.fail("Untrusted history input reached epoch regeneration or indexed body hashing")


def guard_indexed_body_hashes(monkeypatch, owner, inputs, steps):
    bodies = set()
    for epoch in [inputs, *steps]:
        replay = epoch["adjudication_replay_inputs"]
        populations = [
            replay["source_review_groups"],
            replay["adjudication_groups"],
            epoch.get("application_groups", epoch.get("revision_groups")),
        ]
        for groups in populations:
            for group in groups:
                bodies.update(group["evidence_artifacts"].values())
    for target in (owner, genesis_owner, adjudication_owner, response_owner, source_owner):
        original = target._sha

        def guarded(raw, original=original):
            if raw in bodies:
                refuse_replay()
            return original(raw)

        monkeypatch.setattr(target, "_sha", guarded)
    monkeypatch.setattr(genesis_owner, "_replay_inputs", refuse_replay)


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_source_history

    return corpus_source_history


@pytest.fixture(scope="module")
def fixture_data(tmp_path_factory):
    original = helper().fixture_data.__wrapped__(tmp_path_factory)
    data = helper().signed_case(genesis_owner, original)
    data["genesis_report"] = helper().assess(genesis_owner, data)
    return data


def genesis_inputs(data, **options):
    return {
        "adjudication_report": data["adjudication_report"],
        "application_registry": data["application_registry"],
        "application_policy": data["application_policy"],
        "application_groups": data["application_groups"],
        "descriptor": data["descriptor"],
        **helper().assessment_arguments(data),
        **options,
    }


def revision_descriptor(data, previous_manifest=None, *, generation=2):
    previous = (
        data["genesis_report"]["manifest"] if previous_manifest is None else previous_manifest
    )
    return {
        "snapshot_id": data["descriptor"]["snapshot_id"],
        "use_scope": data["descriptor"]["use_scope"],
        "generation": generation,
        "previous_snapshot_manifest_ref": ref(previous),
    }


def declaration_pins(data, ordinal=0, *, previous_report=None, epoch_id=REVISION_ID, **options):
    previous = data["genesis_report"] if previous_report is None else previous_report
    return {
        "epoch_id": epoch_id,
        "expected_request_sha256": sha(
            canonical_dag_json_bytes(data["preparation"]["requests"][ordinal])
        ),
        "expected_subject_sha256": sha(
            canonical_dag_json_bytes(data["preparation"]["subjects"][ordinal])
        ),
        "expected_adjudication_group_sha256": sha(
            canonical_dag_json_bytes(data["adjudication_report"]["records"][ordinal])
        ),
        "expected_previous_snapshot_group_sha256": sha(
            canonical_dag_json_bytes(previous["records"][ordinal])
        ),
        "expected_previous_snapshot_manifest_sha256": sha(
            canonical_dag_json_bytes(previous["manifest"])
        ),
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


def author(
    owner,
    data,
    ordinal=0,
    *,
    previous_report=None,
    descriptor=None,
    epoch_id=REVISION_ID,
    **options,
):
    previous = data["genesis_report"] if previous_report is None else previous_report
    return owner.record_source_revision_declaration(
        data["preparation"]["requests"][ordinal],
        data["preparation"]["subjects"][ordinal],
        data["adjudication_report"]["records"][ordinal],
        previous["records"][ordinal],
        previous["manifest"],
        revision_descriptor(data, previous["manifest"]) if descriptor is None else descriptor,
        **declaration_pins(data, ordinal, previous_report=previous, epoch_id=epoch_id, **options),
    )


def authority(owner, data, *, mode="external_pinned_trust"):
    registry = deepcopy(data["application_registry"])
    registry["mode"] = mode
    policy = deepcopy(data["application_policy"])
    policy.update(
        {
            "mode": mode,
            "policy_id": "fixture:source-history-revision-policy",
            "registry_sha256": sha(canonical(registry)),
            "action": owner.ACTION,
            "audience": owner.AUDIENCE,
        }
    )
    return registry, policy, data["application_signers"][:]


def sign_group(owner, data, body, ordinal=0, *, epoch_id=REVISION_ID, issued=ISSUED):
    request = data["preparation"]["requests"][ordinal]
    subject = data["preparation"]["subjects"][ordinal]
    identity = f"{epoch_id}:body:{ordinal}"
    raw = canonical_dag_json_bytes(body)
    common_ref = {"artifact_id": identity, "sha256": sha(raw)}
    prior_claim = data["adjudication_groups"][ordinal]["reviews"][0]
    obligations = [
        {
            "slot_id": row["slot_id"],
            "disposition": row["disposition"],
            "evidence_refs": [deepcopy(common_ref)],
        }
        for row in prior_claim["context_closure"]["obligations"]
    ]
    source_helper = helper().helper().helper().helper()
    reviews = [
        signer.sign(
            {
                "schema": owner.CLAIM_SCHEMA,
                "action": owner.ACTION,
                "audience": owner.AUDIENCE,
                "review_id": f"{epoch_id}:review:{ordinal}:{index}",
                "key_id": key["key_id"],
                "principal_id": key["principal_id"],
                "role": role,
                "registry_sha256": sha(canonical(data["revision_registry"])),
                "policy_sha256": sha(canonical(data["revision_policy"])),
                "issued_at_utc": issued,
                "expires_at_utc": source_helper.EXPIRES,
                "subject": deepcopy(subject),
                "interpretation": {
                    "decision": "support",
                    "reviewed_graph_sha256": subject["graph_sha256"],
                    "reviewed_ast_sha256": subject["ast_sha256"],
                    "rationale": "Support for exact candidate revision only, never legal meaning.",
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
                data["revision_signers"],
                data["revision_registry"]["keys"],
                trust_owner.ROLES,
                strict=True,
            )
        )
    ]
    return {
        "request_cid": request["record_cid"],
        "reviews": reviews,
        "revision_artifact_id": identity,
        "evidence_artifacts": {identity: raw, EVIDENCE_ID: EVIDENCE_BYTES},
        "observed_artifact_sha256s": deepcopy(data["groups"][ordinal]["observed_artifact_sha256s"]),
        "observed_pins": deepcopy(data["groups"][ordinal]["observed_pins"]),
    }


def group_pins(groups):
    return [
        {**pin, "revision_artifact_id": group["revision_artifact_id"]}
        for pin, group in zip(
            helper().helper().helper().helper().group_pins(groups), groups, strict=True
        )
    ]


def revision_step(
    owner,
    original,
    *,
    epoch_id=REVISION_ID,
    previous_report=None,
    generation=2,
    mode="external_pinned_trust",
    declared=DECLARED,
    issued=ISSUED,
):
    data = clone_case(original)
    previous = data["genesis_report"] if previous_report is None else previous_report
    data["revision_registry"], data["revision_policy"], data["revision_signers"] = authority(
        owner, data, mode=mode
    )
    groups = []
    descriptor = revision_descriptor(data, previous["manifest"], generation=generation)
    for ordinal, request in enumerate(data["preparation"]["requests"]):
        if ordinal == 0:
            body = author(
                owner,
                data,
                ordinal,
                previous_report=previous,
                descriptor=descriptor,
                epoch_id=epoch_id,
                declared_at_utc=declared,
            )
            groups.append(sign_group(owner, data, body, ordinal, epoch_id=epoch_id, issued=issued))
        else:
            groups.append(
                {
                    "request_cid": request["record_cid"],
                    "reviews": [],
                    "revision_artifact_id": None,
                    "evidence_artifacts": {},
                    "observed_artifact_sha256s": deepcopy(
                        data["groups"][ordinal]["observed_artifact_sha256s"]
                    ),
                    "observed_pins": deepcopy(data["groups"][ordinal]["observed_pins"]),
                }
            )
    return {
        "epoch_id": epoch_id,
        "adjudication_report": data["adjudication_report"],
        "revision_registry": data["revision_registry"],
        "revision_policy": data["revision_policy"],
        "revision_groups": groups,
        "descriptor": descriptor,
        "expected_adjudication_manifest_sha256": sha(
            canonical_dag_json_bytes(data["adjudication_report"]["manifest"])
        ),
        "expected_revision_registry_sha256": sha(canonical(data["revision_registry"])),
        "expected_revision_policy_sha256": sha(canonical(data["revision_policy"])),
        "expected_revision_group_pins": group_pins(groups),
        "adjudication_replay_inputs": helper().replay_inputs(data),
    }


def step_pins(steps):
    return [
        {
            "epoch_id": step["epoch_id"],
            "descriptor_sha256": sha(canonical(step["descriptor"])),
            "adjudication_manifest_sha256": step["expected_adjudication_manifest_sha256"],
            "registry_sha256": step["expected_revision_registry_sha256"],
            "policy_sha256": step["expected_revision_policy_sha256"],
            "group_pins_sha256": sha(canonical(step["expected_revision_group_pins"])),
            "evaluation_time_utc": step["adjudication_replay_inputs"]["at_time_utc"],
        }
        for step in steps
    ]


def assessment_arguments(data, steps, **options):
    return {
        "genesis_epoch_id": GENESIS_ID,
        "current_epoch_id": steps[-1]["epoch_id"] if steps else GENESIS_ID,
        "at_time_utc": data["at_time_utc"],
        "expected_genesis_manifest_sha256": sha(
            canonical_dag_json_bytes(data["genesis_report"]["manifest"])
        ),
        "expected_revision_step_pins": step_pins(steps),
        **options,
    }


def assess(owner, data, steps, **options):
    return owner.assess_source_history(
        data["genesis_report"],
        genesis_inputs(data),
        steps,
        **assessment_arguments(data, steps, **options),
    )


def validate(owner, report, data, steps, **options):
    return owner.validate_source_history(
        report,
        data["genesis_report"],
        genesis_inputs(data),
        steps,
        **assessment_arguments(data, steps, **options),
    )


@pytest.fixture(scope="module")
def baseline_step(fixture_data):
    from ipfs_datasets_py.logic.autoformal import corpus_source_history

    return revision_step(corpus_source_history, fixture_data)


@pytest.fixture(scope="module")
def baseline_report(fixture_data, baseline_step):
    from ipfs_datasets_py.logic.autoformal import corpus_source_history

    return assess(corpus_source_history, fixture_data, [baseline_step])


def epoch_report(history, epoch_id):
    manifest = next(
        row["snapshot_manifest_record"]
        for row in history["epoch_manifests"]
        if row["epoch_id"] == epoch_id
    )
    return {
        "manifest": manifest,
        "pages": [
            row["snapshot_page_record"]
            for row in history["epoch_pages"]
            if row["epoch_id"] == epoch_id
        ],
        "records": [
            row["snapshot_group_record"]
            for row in history["records"]
            if row["epoch_id"] == epoch_id
        ],
    }


def refresh_step(step, signers):
    step["revision_policy"]["registry_sha256"] = sha(canonical(step["revision_registry"]))
    for group in step["revision_groups"]:
        for index, review in enumerate(group["reviews"]):
            body = {
                key: deepcopy(value)
                for key, value in review.items()
                if key not in {"signer_did", "signature_alg", "signature"}
            }
            body["registry_sha256"] = sha(canonical(step["revision_registry"]))
            body["policy_sha256"] = sha(canonical(step["revision_policy"]))
            group["reviews"][index] = signers[index].sign(body)
    step["expected_revision_registry_sha256"] = sha(canonical(step["revision_registry"]))
    step["expected_revision_policy_sha256"] = sha(canonical(step["revision_policy"]))
    step["expected_revision_group_pins"] = group_pins(step["revision_groups"])


def replace_revision_body(step, record, signers, *, resign=True):
    group = step["revision_groups"][0]
    identity = group["revision_artifact_id"]
    raw = canonical_dag_json_bytes(record)
    group["evidence_artifacts"][identity] = raw
    if resign:
        for review in group["reviews"]:
            for obligation in review["context_closure"]["obligations"]:
                obligation["evidence_refs"] = [{"artifact_id": identity, "sha256": sha(raw)}]
        refresh_step(step, signers)
    else:
        step["expected_revision_group_pins"] = group_pins(step["revision_groups"])


def add_rejected_original_actor(data, *, identity="all"):
    """A supplied other-request original claim counts even without a typed response."""
    result = clone_case(data)
    ordinal = 1
    old = result["groups"][0]["reviews"][0]
    key = deepcopy(result["application_registry"]["keys"][0])
    key["key_id"] = "fixture:later-original-key"
    if identity == "principal":
        key["signer_did"] = "did:example:later-independent-original"
        signer = Ed25519Signer.generate(key["signer_did"])
        from cryptography.hazmat.primitives import serialization

        key["public_key_hex"] = signer.public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ).hex()
    elif identity == "did":
        key["principal_id"] = "fixture:later-independent-original-principal"
        signer = Ed25519Signer.generate(key["signer_did"])
        from cryptography.hazmat.primitives import serialization

        key["public_key_hex"] = signer.public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ).hex()
    elif identity == "public_key":
        key["principal_id"] = "fixture:later-independent-original-principal"
        key["signer_did"] = "did:example:later-independent-original"
        # The claimed DID is intentionally rejected by the sole shared verifier.
        signer = result["application_signers"][0]
    else:
        signer = result["application_signers"][0]
    result["registry"]["keys"].append(key)
    result["policy"]["registry_sha256"] = sha(canonical(result["registry"]))
    claim = {
        field: deepcopy(value)
        for field, value in old.items()
        if field not in {"signer_did", "signature_alg", "signature"}
    }
    subject = result["preparation"]["subjects"][ordinal]
    claim.update(
        review_id="fixture:later-original-other-request",
        key_id=key["key_id"],
        principal_id=key["principal_id"],
        subject=deepcopy(subject),
        registry_sha256=sha(canonical(result["registry"])),
        policy_sha256=sha(canonical(result["policy"])),
    )
    claim["interpretation"].update(
        reviewed_graph_sha256=subject["graph_sha256"], reviewed_ast_sha256=subject["ast_sha256"]
    )
    claim["context_closure"] = {
        "status": "open",
        "unresolved": subject["context_slot_ids"][:],
        "obligations": [
            {"slot_id": slot, "disposition": "open", "evidence_refs": []}
            for slot in subject["context_slot_ids"]
        ],
    }
    # Invalid signature deliberately keeps this submitted claim nonauthoritative.
    rejected = signer.sign(claim)
    if identity == "public_key":
        rejected["signer_did"] = key["signer_did"]
    rejected["signature"] = "A" * 86
    result["groups"][ordinal]["reviews"] = [rejected]
    rejected_response = b"Rejected engineering response; no typed declaration or law."
    response_id = "fixture:later-original-rejected-response"
    result["groups"][ordinal]["evidence_artifacts"] = {response_id: rejected_response}
    result["response_bindings"][ordinal]["responses"] = [
        {
            "review_id": rejected["review_id"],
            "artifact_id": response_id,
            "raw_sha256": sha(rejected_response),
        }
    ]
    # Re-sign only the unchanged original first-request actors with current trust pins.
    helper().helper().helper().helper().refresh_signatures(
        {**result, "groups": [result["groups"][0]]}
    )
    result["typed_report"] = helper().helper().helper().assess(response_owner, result)
    helper().helper().replace_body(result, helper().helper().author(adjudication_owner, result))
    result["adjudication_report"] = helper().helper().assess(adjudication_owner, result)
    assert (
        result["typed_report"]["records"][ordinal]["raw_source_assessment_record"]["assessment"][
            "authenticated_evidence_count"
        ]
        == 0
    )
    return result


def assert_narrow_history(owner, report):
    for component, values in report.items():
        for row in [values] if component == "manifest" else values:
            assert row["view"] == "candidate"
            assert row["selected_occurrence"] is row["governing_source_binding"] is None
            assert reseal(row) == row
            assert len(canonical_dag_json_bytes(row)) <= contracts.MAX_RECORD_BYTES
            for flag in owner.FALSE_FLAGS:
                assert row[flag] is False


def test_complete_genesis_and_fresh_revision_replay_preserves_epochs_without_carrying_old_eligibility(
    owner, fixture_data, baseline_step, baseline_report
):
    report = baseline_report
    assert set(report) == set(owner.COMPONENTS)
    assert epoch_report(report, GENESIS_ID) == fixture_data["genesis_report"]
    current = epoch_report(report, REVISION_ID)
    assert current["manifest"]["snapshot_descriptor"] == baseline_step["descriptor"]
    assert current["records"][0]["source_answer_snapshot_activated_under_selected_profile"] is True
    original = [row for row in report["records"] if row["epoch_id"] == GENESIS_ID]
    revised = [row for row in report["records"] if row["epoch_id"] == REVISION_ID]
    assert len(original) == len(revised) == len(fixture_data["preparation"]["requests"])
    assert all(
        row["regenerated_at_explicit_epoch_trust_and_time"] is True for row in report["records"]
    )
    assert all(
        row["current_candidate_refs_eligible_under_selected_history_profile"] is False
        and row["current_active_answer_variant_refs"] == []
        for row in original
    )
    assert revised[0]["current_candidate_refs_eligible_under_selected_history_profile"] is True
    assert len(revised[0]["current_active_answer_variant_refs"]) == 9
    assert all(row["current_active_answer_variant_refs"] == [] for row in revised[1:])
    counts = report["manifest"]["counts"]
    assert counts["epochs"] == 2 and counts["revision_epochs"] == 1
    assert counts["total_groups"] == 2 * len(revised)
    assert counts["historical_activated_groups_at_selected_epoch_times"] == 2
    assert counts["current_eligible_groups"] == 1 and counts["current_eligible_answer_slots"] == 9
    assert counts["visible_fork_parents"] == 0
    assert report["manifest"]["leaf_epoch_ids"] == [REVISION_ID]
    assert_narrow_history(owner, report)
    assert validate(owner, report, fixture_data, [baseline_step]) == report


def test_revision_authoring_binds_exact_predecessor_and_new_scope_without_authentication(
    owner, fixture_data, monkeypatch
):
    monkeypatch.setattr(trust_owner, "_assess_reviews", refuse_replay)
    monkeypatch.setattr(genesis_owner, "validate_source_applications", refuse_replay)
    monkeypatch.setattr(adjudication_owner, "validate_source_adjudications", refuse_replay)
    body = author(owner, fixture_data)
    assert body["epoch_id"] == REVISION_ID
    assert body["previous_snapshot_group_ref"] == ref(fixture_data["genesis_report"]["records"][0])
    assert body["previous_snapshot_manifest_ref"] == ref(fixture_data["genesis_report"]["manifest"])
    assert body["snapshot_descriptor"] == revision_descriptor(fixture_data)
    assert body["status"] == "declared_unauthenticated_candidate_source_revision"
    for flag in owner.FALSE_FLAGS:
        assert body[flag] is False
    assert (
        owner.validate_source_revision_declaration(
            body,
            fixture_data["preparation"]["requests"][0],
            fixture_data["preparation"]["subjects"][0],
            fixture_data["adjudication_report"]["records"][0],
            fixture_data["genesis_report"]["records"][0],
            fixture_data["genesis_report"]["manifest"],
            revision_descriptor(fixture_data),
            **declaration_pins(fixture_data),
        )
        == body
    )


def test_regenerated_genesis_alone_cannot_supply_fresh_current_revision_authority(
    owner, fixture_data
):
    report = assess(owner, fixture_data, [])
    assert epoch_report(report, GENESIS_ID) == fixture_data["genesis_report"]
    assert report["manifest"]["counts"]["historical_activated_groups_at_selected_epoch_times"] == 1
    assert report["manifest"]["counts"]["current_eligible_groups"] == 0
    assert all(row["current_active_answer_variant_refs"] == [] for row in report["records"])
    assert all(
        "fresh_revision_authorization_required_for_current_history_use"
        in row["current_eligibility_blockers"]
        for row in report["records"]
    )
    assert_narrow_history(owner, report)


def test_three_epoch_chain_preserves_exact_genesis_and_parent_roots_and_requires_fresh_all_nine(
    owner, fixture_data, baseline_step, baseline_report
):
    parent = epoch_report(baseline_report, REVISION_ID)
    step = revision_step(
        owner,
        fixture_data,
        epoch_id="fixture:history-revision:3",
        previous_report=parent,
        generation=3,
    )
    report = assess(owner, fixture_data, [baseline_step, step])
    assert epoch_report(report, GENESIS_ID) == fixture_data["genesis_report"]
    assert epoch_report(report, REVISION_ID) == parent
    current = epoch_report(report, step["epoch_id"])
    assert current["records"][0]["previous_snapshot_group_ref"] == ref(parent["records"][0])
    assert current["manifest"]["snapshot_descriptor"]["previous_snapshot_manifest_ref"] == ref(
        parent["manifest"]
    )
    assert current["records"][0]["source_answer_snapshot_activated_under_selected_profile"] is True
    assert len(current["records"][0]["activated_answer_variant_refs"]) == 9
    assert report["manifest"]["counts"]["historical_activated_groups_at_selected_epoch_times"] == 3
    assert report["manifest"]["counts"]["current_eligible_groups"] == 1
    assert report["manifest"]["leaf_epoch_ids"] == [step["epoch_id"]]
    assert_narrow_history(owner, report)


def test_visible_sibling_forks_retain_both_authenticated_epochs_without_authoritative_head(
    owner, fixture_data, baseline_step, baseline_report
):
    sibling = revision_step(owner, fixture_data, epoch_id="fixture:history-sibling:2")
    report = assess(owner, fixture_data, [baseline_step, sibling])
    assert epoch_report(report, REVISION_ID) == epoch_report(baseline_report, REVISION_ID)
    assert report["manifest"]["leaf_epoch_ids"] == [REVISION_ID, sibling["epoch_id"]]
    assert report["manifest"]["fork_parent_manifest_refs"] == [
        ref(fixture_data["genesis_report"]["manifest"])
    ]
    assert report["manifest"]["counts"]["historical_activated_groups_at_selected_epoch_times"] == 3
    assert report["manifest"]["counts"]["current_eligible_groups"] == 0
    assert all(row["current_active_answer_variant_refs"] == [] for row in report["records"])
    assert all(
        "visible_forks_require_separate_resolution_profile" in row["current_eligibility_blockers"]
        for row in report["records"]
    )
    assert_narrow_history(owner, report)


@pytest.mark.parametrize("relationship", ["descendant", "sibling"])
@pytest.mark.parametrize(
    "identity,blocker",
    [
        ("principal", "current_revision_actor_is_a_supplied_history_original_reviewer"),
        ("did", "current_revision_actor_reuses_a_supplied_history_original_reviewer_did"),
        (
            "public_key",
            "current_revision_actor_reuses_a_supplied_history_original_reviewer_public_key",
        ),
    ],
)
def test_append_or_sibling_original_actor_does_not_rewrite_sealed_parent_but_blocks_current_projection(
    owner, fixture_data, baseline_step, baseline_report, relationship, identity, blocker
):
    original_inputs = deepcopy(baseline_step)
    parent = epoch_report(baseline_report, REVISION_ID)
    later = add_rejected_original_actor(fixture_data, identity=identity)
    if relationship == "descendant":
        later_step = revision_step(
            owner, later, epoch_id="fixture:history-later:3", previous_report=parent, generation=3
        )
        current_id = later_step["epoch_id"]
    else:
        later_step = revision_step(owner, later, epoch_id="fixture:history-other-branch:2")
        current_id = REVISION_ID
    report = assess(owner, fixture_data, [baseline_step, later_step], current_epoch_id=current_id)
    assert epoch_report(report, REVISION_ID) == parent
    assert ref(epoch_report(report, REVISION_ID)["manifest"]) == ref(parent["manifest"])
    assert baseline_step == original_inputs
    selected = next(
        row
        for row in report["records"]
        if row["epoch_id"] == current_id and row["queue_ordinal"] == 0
    )
    assert selected["current_candidate_refs_eligible_under_selected_history_profile"] is False
    assert selected["current_active_answer_variant_refs"] == []
    assert blocker in selected["current_eligibility_blockers"]
    if relationship == "sibling":
        assert (
            selected["snapshot_group_record"][
                "source_answer_snapshot_activated_under_selected_profile"
            ]
            is True
        )
    assert_narrow_history(owner, report)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_name",
        "wrong_name",
        "missing_scope",
        "wrong_scope",
        "missing_generation",
        "bool_generation",
        "genesis_generation",
        "gap",
        "missing_parent",
        "null_parent",
        "wrong_parent_hash",
        "wrong_parent_cid",
        "wrong_parent_schema",
        "extra_parent_field",
        "extra_descriptor_field",
    ],
)
def test_revision_descriptor_requires_exact_stable_scope_generation_and_immediate_parent(
    owner, fixture_data, damage
):
    descriptor = revision_descriptor(fixture_data)
    if damage == "missing_name":
        del descriptor["snapshot_id"]
    elif damage == "wrong_name":
        descriptor["snapshot_id"] = "fixture:other-history"
    elif damage == "missing_scope":
        del descriptor["use_scope"]
    elif damage == "wrong_scope":
        descriptor["use_scope"] = "governing_physical_source"
    elif damage == "missing_generation":
        del descriptor["generation"]
    elif damage == "bool_generation":
        descriptor["generation"] = True
    elif damage == "genesis_generation":
        descriptor["generation"] = 1
    elif damage == "gap":
        descriptor["generation"] = 3
    elif damage == "missing_parent":
        del descriptor["previous_snapshot_manifest_ref"]
    elif damage == "null_parent":
        descriptor["previous_snapshot_manifest_ref"] = None
    elif damage == "wrong_parent_hash":
        descriptor["previous_snapshot_manifest_ref"]["sha256"] = "0" * 64
    elif damage == "wrong_parent_cid":
        descriptor["previous_snapshot_manifest_ref"]["record_cid"] = fixture_data["preparation"][
            "manifest"
        ]["record_cid"]
    elif damage == "wrong_parent_schema":
        descriptor["previous_snapshot_manifest_ref"]["schema"] = adjudication_owner.MANIFEST_SCHEMA
    elif damage == "extra_parent_field":
        descriptor["previous_snapshot_manifest_ref"]["cached_eligible"] = True
    elif damage == "extra_descriptor_field":
        descriptor["latest_head_authoritative"] = True
    with pytest.raises(ValueError):
        author(owner, fixture_data, descriptor=descriptor)


@pytest.mark.parametrize(
    "pin_name",
    [
        "expected_request_sha256",
        "expected_subject_sha256",
        "expected_adjudication_group_sha256",
        "expected_previous_snapshot_group_sha256",
        "expected_previous_snapshot_manifest_sha256",
    ],
)
@pytest.mark.parametrize("pin_value", ["0" * 64, "invalid", None, True])
def test_authoring_requires_exact_full_current_and_predecessor_record_pins(
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
def test_revision_roots_require_explicit_full_sha256_format(
    owner, fixture_data, pin_name, pin_value
):
    with pytest.raises(ValueError):
        author(owner, fixture_data, **{pin_name: pin_value})


@pytest.mark.parametrize("epoch_id", [None, "", True, 1, [], "relative epoch"])
def test_epoch_identity_is_explicit_and_cannot_be_inferred_from_list_position(
    owner, fixture_data, epoch_id
):
    with pytest.raises(ValueError):
        author(owner, fixture_data, epoch_id=epoch_id)


@pytest.mark.parametrize("declared", [None, "", True, "2026-10-14", "2026-10-14T09:00:00+00:00"])
def test_revision_time_requires_explicit_canonical_utc(owner, fixture_data, declared):
    with pytest.raises(ValueError):
        author(owner, fixture_data, declared_at_utc=declared)


@pytest.mark.parametrize(
    "rationale",
    [None, "", " ", True, [], "x" * (1024**2 + 1)],
    ids=["null", "empty", "blank", "boolean", "list", "oversized"],
)
def test_revision_rationale_cannot_infer_or_omit_change_authority(owner, fixture_data, rationale):
    with pytest.raises(ValueError):
        author(owner, fixture_data, rationale=rationale)


@pytest.mark.parametrize(
    "damage",
    [
        "empty",
        "duplicate",
        "too_many",
        "invalid_hash",
        "missing_id",
        "unknown_field",
        "tuple",
        "nonfinite",
        "cyclic",
    ],
)
def test_revision_evidence_declarations_are_closed_bounded_and_explicit(
    owner, fixture_data, damage
):
    values = [{"artifact_id": EVIDENCE_ID, "sha256": sha(EVIDENCE_BYTES)}]
    if damage == "empty":
        values = []
    elif damage == "duplicate":
        values *= 2
    elif damage == "too_many":
        values = [
            {"artifact_id": f"fixture:revision-evidence:{n}", "sha256": sha(EVIDENCE_BYTES)}
            for n in range(9)
        ]
    elif damage == "invalid_hash":
        values[0]["sha256"] = "invalid"
    elif damage == "missing_id":
        del values[0]["artifact_id"]
    elif damage == "unknown_field":
        values[0]["past_eligibility_establishes_authority"] = True
    elif damage == "tuple":
        values = tuple(values)
    elif damage == "nonfinite":
        values[0]["sha256"] = float("inf")
    elif damage == "cyclic":
        values.append(values)
    with pytest.raises(ValueError):
        author(owner, fixture_data, evidence_refs=values)


def test_unresolved_current_adjudication_cannot_inherit_a_past_selected_snapshot(
    owner, fixture_data
):
    data = clone_case(fixture_data)
    group = data["adjudication_report"]["records"][0]
    declaration = group["declaration_record"]
    declaration["decisions"][0]["decision"] = "unresolved"
    declaration["decisions"][0]["selected_variant_ref"] = None
    group["declaration_record"] = reseal(declaration)
    data["adjudication_report"]["records"][0] = reseal(group)
    with pytest.raises(ValueError):
        author(owner, data)


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "extra",
        "duplicate",
        "reordered",
        "unknown_cid",
        "wrong_hash",
        "wrong_schema",
        "short_hash",
        "extra_ref_field",
    ],
)
def test_revision_body_validator_never_repairs_missing_reordered_or_unknown_selected_answers(
    owner, fixture_data, damage
):
    body = author(owner, fixture_data)
    refs = body["selected_answer_variant_refs"]
    if damage == "missing":
        refs.pop()
    elif damage == "extra":
        refs.append(deepcopy(refs[0]))
    elif damage == "duplicate":
        refs[1] = deepcopy(refs[0])
    elif damage == "reordered":
        refs.reverse()
    elif damage == "unknown_cid":
        refs[0]["record_cid"] = fixture_data["preparation"]["requests"][0]["record_cid"]
    elif damage == "wrong_hash":
        refs[0]["sha256"] = "0" * 64
    elif damage == "wrong_schema":
        refs[0]["schema"] = source_owner.REQUEST_SCHEMA
    elif damage == "short_hash":
        refs[0]["sha256"] = "abc"
    else:
        refs[0]["proven_exists"] = True
    with pytest.raises(ValueError):
        owner.validate_source_revision_declaration(
            reseal(body),
            fixture_data["preparation"]["requests"][0],
            fixture_data["preparation"]["subjects"][0],
            fixture_data["adjudication_report"]["records"][0],
            fixture_data["genesis_report"]["records"][0],
            fixture_data["genesis_report"]["manifest"],
            revision_descriptor(fixture_data),
            **declaration_pins(fixture_data),
        )


@pytest.mark.parametrize(
    "field",
    [
        "epoch_id",
        "request_ref",
        "subject_ref",
        "adjudication_group_ref",
        "previous_snapshot_group_ref",
        "previous_snapshot_manifest_ref",
        "preparation_manifest_sha256",
        "typed_response_manifest_sha256",
        "adjudication_manifest_sha256",
        "source_review_scope_id",
        "profile",
        "activation_effect",
        "status",
    ],
)
def test_revision_declaration_validation_binds_epoch_scope_complete_roots_and_activation_effect(
    owner, fixture_data, field
):
    body = author(owner, fixture_data)
    if type(body[field]) is dict:
        body[field]["sha256"] = "0" * 64
    elif field.endswith("sha256"):
        body[field] = "0" * 64
    else:
        body[field] = "fixture:changed-value"
    with pytest.raises(ValueError):
        owner.validate_source_revision_declaration(
            reseal(body),
            fixture_data["preparation"]["requests"][0],
            fixture_data["preparation"]["subjects"][0],
            fixture_data["adjudication_report"]["records"][0],
            fixture_data["genesis_report"]["records"][0],
            fixture_data["genesis_report"]["manifest"],
            revision_descriptor(fixture_data),
            **declaration_pins(fixture_data),
        )


@pytest.mark.parametrize(
    "stage",
    [
        "genesis_source",
        "genesis_adjudication",
        "genesis_application",
        "revision_source",
        "revision_adjudication",
        "revision_application",
    ],
)
@pytest.mark.parametrize("damage", ["raw_overflow", "mixed_json_overflow"])
def test_complete_later_epoch_mixed_evidence_budget_finishes_before_first_owner_hash(
    owner, fixture_data, baseline_step, monkeypatch, stage, damage
):
    data = clone_case(fixture_data)
    steps = [deepcopy(baseline_step)]
    inputs = genesis_inputs(data)
    if stage.startswith("genesis"):
        epoch = inputs
    else:
        epoch = steps[0]
    if stage.endswith("source"):
        groups = epoch["adjudication_replay_inputs"]["source_review_groups"]
    elif stage.endswith("adjudication"):
        groups = epoch["adjudication_replay_inputs"]["adjudication_groups"]
    else:
        groups = (
            epoch["application_groups"] if stage.startswith("genesis") else epoch["revision_groups"]
        )
    group = groups[-1]
    group["evidence_artifacts"]["fixture:late-oversized-input"] = b"x" * (
        8 * 1024**2 + 1 if damage == "raw_overflow" else 8 * 1024**2 - 256
    )
    if damage == "mixed_json_overflow":
        group["observed_pins"]["fixture:late-large-pin"] = "y" * 512
    arguments = assessment_arguments(data, steps)
    guard_indexed_body_hashes(monkeypatch, owner, inputs, steps)
    with pytest.raises(ValueError):
        owner.assess_source_history(data["genesis_report"], inputs, steps, **arguments)


@pytest.mark.parametrize(
    "limit",
    [
        "max_all_input_bytes",
        "max_all_input_nodes",
        "max_input_depth",
        "max_all_signed_evidence_bytes",
        "max_total_groups",
        "max_epochs",
    ],
)
def test_complete_all_epoch_population_caps_refuse_before_hash_or_regeneration(
    owner, fixture_data, baseline_step, monkeypatch, limit
):
    arguments = assessment_arguments(fixture_data, [baseline_step], limits={limit: 1})
    guard_indexed_body_hashes(monkeypatch, owner, genesis_inputs(fixture_data), [baseline_step])
    monkeypatch.setattr(genesis_owner, "validate_source_applications", refuse_replay)
    with pytest.raises(ValueError):
        owner.assess_source_history(
            fixture_data["genesis_report"],
            genesis_inputs(fixture_data),
            [baseline_step],
            **arguments,
        )


@pytest.mark.parametrize(
    "damage",
    ["callback", "custom_loader", "cycle", "tuple", "nonstring_key", "nonfinite", "deep_tree"],
)
def test_native_history_detachment_rejects_callbacks_cycles_and_unsafe_shapes_before_body_hash(
    owner, fixture_data, baseline_step, monkeypatch, damage
):
    step = deepcopy(baseline_step)
    if damage == "callback":
        step["adjudication_replay_inputs"]["callback"] = refuse_replay
    elif damage == "custom_loader":

        class ExternalLoader:
            def read(self):
                pytest.fail("External loader was evaluated")

        step["adjudication_replay_inputs"]["loader"] = ExternalLoader()
    elif damage == "cycle":
        step["descriptor"]["cycle"] = step
    elif damage == "tuple":
        step["revision_groups"] = tuple(step["revision_groups"])
    elif damage == "nonstring_key":
        step["descriptor"][1] = "not-native-json"
    elif damage == "nonfinite":
        step["descriptor"]["generation"] = float("inf")
    else:
        nested = {}
        current = nested
        for _ in range(66):
            child = {}
            current["child"] = child
            current = child
        step["adjudication_replay_inputs"]["deep"] = nested
    arguments = assessment_arguments(fixture_data, [baseline_step])
    for target in (owner, genesis_owner, adjudication_owner, response_owner, source_owner):
        monkeypatch.setattr(target, "_sha", refuse_replay)
    with pytest.raises(ValueError):
        owner.assess_source_history(
            fixture_data["genesis_report"], genesis_inputs(fixture_data), [step], **arguments
        )


def test_shared_native_aliases_are_charged_for_every_logical_occurrence_without_being_cycles(owner):
    shared = {"body": b"12345678"}
    bounds = owner._limits(None)
    first, single = owner._clone(shared, bounds)
    copied, double = owner._clone([shared, shared], bounds)
    assert copied == [first, first]
    assert copied[0] is not copied[1]
    assert double["logical_input_bytes"] > 2 * single["logical_input_bytes"]
    assert double["native_input_nodes"] == 2 * single["native_input_nodes"] + 1
    with pytest.raises(ValueError, match="byte"):
        owner._clone(
            [shared, shared], {**bounds, "max_all_input_bytes": double["logical_input_bytes"] - 1}
        )


@pytest.mark.parametrize(
    "limit",
    [
        "max_epochs",
        "max_total_groups",
        "max_pages",
        "max_groups_per_page",
        "max_page_bytes",
        "max_collection_bytes",
        "max_all_input_bytes",
        "max_all_input_nodes",
        "max_input_depth",
        "max_all_signed_evidence_bytes",
    ],
)
@pytest.mark.parametrize("bad", [0, -1, True, "1"])
def test_history_limits_are_closed_positive_lower_only_integers_before_replay(
    owner, fixture_data, monkeypatch, limit, bad
):
    monkeypatch.setattr(genesis_owner, "validate_source_applications", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, fixture_data, [], limits={limit: bad})


@pytest.mark.parametrize(
    "limit",
    [
        "max_epochs",
        "max_total_groups",
        "max_pages",
        "max_groups_per_page",
        "max_page_bytes",
        "max_collection_bytes",
        "max_all_input_bytes",
        "max_all_input_nodes",
        "max_input_depth",
        "max_all_signed_evidence_bytes",
    ],
)
def test_history_caps_cannot_be_raised_to_admit_a_larger_snapshot(
    owner, fixture_data, monkeypatch, limit
):
    monkeypatch.setattr(genesis_owner, "validate_source_applications", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, fixture_data, [], limits={limit: owner.DEFAULT_LIMITS[limit] + 1})


@pytest.mark.parametrize("damage", ["unknown", "list", "callback"])
def test_history_limit_profile_does_not_accept_custom_behavior_or_unknown_fields(
    owner, fixture_data, monkeypatch, damage
):
    limits = {"unknown": 1} if damage == "unknown" else [] if damage == "list" else refuse_replay
    monkeypatch.setattr(genesis_owner, "validate_source_applications", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, fixture_data, [], limits=limits)


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("schema", genesis_owner.CLAIM_SCHEMA),
        ("schema", adjudication_owner.CLAIM_SCHEMA),
        ("schema", source_owner.CLAIM_SCHEMA),
        ("action", genesis_owner.ACTION),
        ("action", adjudication_owner.ACTION),
        ("audience", genesis_owner.AUDIENCE),
    ],
)
def test_old_source_adjudication_or_genesis_claims_cannot_authorize_the_new_revision_action(
    owner, fixture_data, baseline_step, field, wrong
):
    step = deepcopy(baseline_step)
    for review in step["revision_groups"][0]["reviews"]:
        review[field] = wrong
    refresh_step(step, fixture_data["application_signers"])
    with pytest.raises(ValueError, match="signing domain"):
        assess(owner, fixture_data, [step])


@pytest.mark.parametrize(
    "damage",
    [
        "one_role",
        "same_role",
        "same_principal",
        "bad_signature",
        "revoked_actor",
        "scope_mismatch",
        "open_closure",
        "one_foreign_body",
        "wrong_disposition",
    ],
)
def test_revision_requires_two_independent_current_roles_attesting_one_complete_common_body(
    owner, fixture_data, baseline_step, damage
):
    step = deepcopy(baseline_step)
    group = step["revision_groups"][0]
    if damage == "one_role":
        group["reviews"].pop()
    elif damage == "same_role":
        group["reviews"][1]["role"] = group["reviews"][0]["role"]
    elif damage == "same_principal":
        step["revision_registry"]["keys"][1]["principal_id"] = step["revision_registry"]["keys"][0][
            "principal_id"
        ]
        group["reviews"][1]["principal_id"] = group["reviews"][0]["principal_id"]
    elif damage == "revoked_actor":
        step["revision_registry"]["keys"][0]["revoked_at_utc"] = "2026-10-14T08:59:00Z"
    elif damage == "scope_mismatch":
        step["revision_registry"]["keys"][0]["scope_ids"] = ["fixture:other-source-scope"]
    elif damage == "open_closure":
        group["reviews"][0]["context_closure"]["status"] = "open"
    elif damage == "one_foreign_body":
        group["reviews"][1]["context_closure"]["obligations"][0]["evidence_refs"] = [
            {"artifact_id": EVIDENCE_ID, "sha256": sha(EVIDENCE_BYTES)}
        ]
    elif damage == "wrong_disposition":
        group["reviews"][1]["context_closure"]["obligations"][0]["disposition"] = "not_applicable"
    refresh_step(step, fixture_data["application_signers"])
    if damage == "bad_signature":
        group["reviews"][0]["signature"] = "A" * 86
        step["expected_revision_group_pins"] = group_pins(step["revision_groups"])
    report = assess(owner, fixture_data, [step])
    revised = epoch_report(report, REVISION_ID)["records"][0]
    assert revised["source_answer_snapshot_activated_under_selected_profile"] is False
    assert revised["activated_answer_variant_refs"] == []
    assert report["manifest"]["counts"]["current_eligible_groups"] == 0
    assert epoch_report(report, GENESIS_ID) == fixture_data["genesis_report"]
    assert_narrow_history(owner, report)


@pytest.mark.parametrize(
    "damage",
    [
        "old_genesis_body",
        "missing_slot",
        "unknown_variant",
        "wrong_root",
        "wrong_predecessor",
        "wrong_epoch",
        "evidence_changed",
        "evidence_missing",
        "unresolved_selected",
    ],
)
def test_even_valid_revision_signatures_cannot_admit_stale_transplanted_or_unbound_body_choices(
    owner, fixture_data, baseline_step, damage
):
    step = deepcopy(baseline_step)
    group = step["revision_groups"][0]
    body = json.loads(group["evidence_artifacts"][group["revision_artifact_id"]])
    if damage == "old_genesis_body":
        old = fixture_data["application_groups"][0]
        body = json.loads(old["evidence_artifacts"][old["app_artifact_id"]])
    elif damage == "missing_slot":
        body["selected_answer_variant_refs"].pop()
    elif damage == "unknown_variant":
        body["selected_answer_variant_refs"][0]["record_cid"] = fixture_data["preparation"][
            "requests"
        ][0]["record_cid"]
    elif damage == "wrong_root":
        body["typed_response_manifest_sha256"] = "0" * 64
    elif damage == "wrong_predecessor":
        body["previous_snapshot_group_ref"]["sha256"] = "0" * 64
    elif damage == "wrong_epoch":
        body["epoch_id"] = "fixture:transplanted-epoch"
    elif damage == "evidence_changed":
        group["evidence_artifacts"][EVIDENCE_ID] = b"Changed evidence is not silently repaired"
    elif damage == "evidence_missing":
        del group["evidence_artifacts"][EVIDENCE_ID]
    else:
        group["reviews"][0]["context_closure"]["obligations"][0]["disposition"] = "open"
        group["reviews"][0]["context_closure"]["unresolved"] = [
            group["reviews"][0]["context_closure"]["obligations"][0]["slot_id"]
        ]
    replace_revision_body(step, reseal(body), fixture_data["application_signers"])
    report = assess(owner, fixture_data, [step])
    revised = epoch_report(report, REVISION_ID)["records"][0]
    assert revised["application_content_status"] == "rejected"
    assert revised["content_blockers"]
    assert revised["activated_answer_variant_refs"] == []
    assert revised["source_answer_snapshot_activated_under_selected_profile"] is False
    assert_narrow_history(owner, report)


@pytest.mark.parametrize(
    "damage", ["after_evaluation", "before_parent", "before_adjudication", "claim_before_body"]
)
def test_explicit_parent_adjudication_declaration_and_claim_chronology_never_carries_old_activation(
    owner, fixture_data, baseline_step, damage
):
    step = deepcopy(baseline_step)
    group = step["revision_groups"][0]
    body = json.loads(group["evidence_artifacts"][group["revision_artifact_id"]])
    if damage == "after_evaluation":
        body["declared_at_utc"] = "2026-10-14T09:00:01Z"
    elif damage == "before_parent":
        body["declared_at_utc"] = "2026-10-14T08:59:59Z"
    elif damage == "before_adjudication":
        body["declared_at_utc"] = "2026-10-14T08:29:59Z"
    else:
        group["reviews"][0]["issued_at_utc"] = "2026-10-14T08:59:59Z"
    replace_revision_body(step, reseal(body), fixture_data["application_signers"])
    report = assess(owner, fixture_data, [step])
    revised = epoch_report(report, REVISION_ID)["records"][0]
    assert revised["application_content_status"] == "valid_declared_content"
    expected = {
        "after_evaluation": "revision_declared_after_evaluation",
        "before_parent": "revision_predates_predecessor_selected_evaluation",
        "before_adjudication": "revision_predates_current_adjudication",
        "claim_before_body": "revision_claim_predates_common_declaration",
    }[damage]
    assert expected in revised["application_blockers"]
    assert revised["source_answer_snapshot_activated_under_selected_profile"] is False
    assert revised["activated_answer_variant_refs"] == []
    assert_narrow_history(owner, report)


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate_epoch",
        "alias_genesis",
        "unknown_current",
        "parent_selected",
        "changed_name",
        "changed_scope",
        "changed_preparation",
        "generation_gap",
        "selected_wrong_time",
        "historical_future",
    ],
)
def test_known_history_population_scope_and_clock_errors_refuse_before_genesis_regeneration(
    owner, fixture_data, baseline_step, monkeypatch, damage
):
    step = deepcopy(baseline_step)
    steps = [step]
    options = {}
    if damage == "duplicate_epoch":
        steps.append(deepcopy(step))
    elif damage == "alias_genesis":
        step["epoch_id"] = GENESIS_ID
    elif damage == "unknown_current":
        options["current_epoch_id"] = "fixture:absent-history-epoch"
    elif damage == "parent_selected":
        options["current_epoch_id"] = GENESIS_ID
    elif damage == "changed_name":
        step["descriptor"]["snapshot_id"] = "fixture:other-snapshot"
    elif damage == "changed_scope":
        step["descriptor"]["use_scope"] = "governing_source"
    elif damage == "changed_preparation":
        step["adjudication_replay_inputs"]["expected_preparation_manifest_sha256"] = "0" * 64
    elif damage == "generation_gap":
        step["descriptor"]["generation"] = 3
    elif damage == "selected_wrong_time":
        options["at_time_utc"] = "2026-10-14T09:00:01Z"
    else:
        step["adjudication_replay_inputs"]["at_time_utc"] = "2026-10-14T08:59:59Z"
        options.update(at_time_utc="2026-10-14T08:59:59Z")
    monkeypatch.setattr(genesis_owner, "validate_source_applications", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, fixture_data, steps, **options)


@pytest.mark.parametrize(
    "field",
    [
        "epoch_id",
        "descriptor_sha256",
        "adjudication_manifest_sha256",
        "registry_sha256",
        "policy_sha256",
        "group_pins_sha256",
        "evaluation_time_utc",
    ],
)
def test_independent_complete_epoch_pins_cannot_be_derived_or_repaired_after_input_changes(
    owner, fixture_data, baseline_step, monkeypatch, field
):
    pins = step_pins([baseline_step])
    pins[0][field] = (
        "fixture:changed"
        if field == "epoch_id"
        else "2026-10-14T09:00:01Z"
        if field == "evaluation_time_utc"
        else "0" * 64
    )
    monkeypatch.setattr(genesis_owner, "validate_source_applications", refuse_replay)
    with pytest.raises(ValueError):
        assess(owner, fixture_data, [baseline_step], expected_revision_step_pins=pins)


def rebind_history_report(report):
    report["records"] = [reseal(row) for row in report["records"]]
    for index, page in enumerate(report["pages"]):
        for entry in page["entries"]:
            entry["group_record_ref"] = ref(report["records"][entry["ordinal"]])
        report["pages"][index] = reseal(page)
        report["manifest"]["page_refs"][index].update(ref(report["pages"][index]))
    report["manifest"] = reseal(report["manifest"])


@pytest.mark.parametrize(
    "damage",
    [
        "activate_past",
        "activate_blocked",
        "changed_active_ref",
        "erase_blocker",
        "reorder_rows",
        "omit_epoch",
        "changed_count",
        "invented_producer",
        "physical_true",
        "semantic_true",
        "head_true",
    ],
)
def test_resealed_history_seals_and_page_inventories_never_replace_complete_epoch_regeneration(
    owner, fixture_data, baseline_step, baseline_report, damage
):
    report = deepcopy(baseline_report)
    selected = next(
        row
        for row in report["records"]
        if row["epoch_id"] == REVISION_ID and row["queue_ordinal"] == 0
    )
    if damage == "activate_past":
        report["records"][0]["current_candidate_refs_eligible_under_selected_history_profile"] = (
            True
        )
        report["records"][0]["current_active_answer_variant_refs"] = deepcopy(
            selected["current_active_answer_variant_refs"]
        )
    elif damage == "activate_blocked":
        blocked = next(
            row
            for row in report["records"]
            if row["epoch_id"] == REVISION_ID and row["queue_ordinal"] == 1
        )
        blocked["current_candidate_refs_eligible_under_selected_history_profile"] = True
        blocked["current_active_answer_variant_refs"] = deepcopy(
            selected["current_active_answer_variant_refs"]
        )
    elif damage == "changed_active_ref":
        selected["current_active_answer_variant_refs"][0]["sha256"] = "0" * 64
    elif damage == "erase_blocker":
        report["records"][0]["current_eligibility_blockers"] = []
    elif damage == "reorder_rows":
        report["records"][0], report["records"][1] = report["records"][1], report["records"][0]
    elif damage == "omit_epoch":
        report["epoch_manifests"].pop()
    elif damage == "changed_count":
        report["manifest"]["counts"]["current_eligible_groups"] += 1
    elif damage == "invented_producer":
        report["manifest"]["producer_pins"]["fixture:unqualified-producer"] = "0" * 64
    elif damage == "physical_true":
        selected["physical_governing_bindings_applied"] = True
    elif damage == "semantic_true":
        selected["adjudicated_source_meaning_verified"] = True
    else:
        selected["authoritative_history_head_qualified"] = True
    rebind_history_report(report)
    with pytest.raises(ValueError):
        validate(owner, report, fixture_data, [baseline_step])


@pytest.mark.parametrize("damage", ["cached_activation", "raw_disagreement_erased"])
def test_repaired_genesis_roots_and_signed_predecessors_cannot_establish_unregenerated_historical_eligibility(
    owner, fixture_data, damage
):
    data = clone_case(fixture_data)
    report = data["genesis_report"]
    if damage == "cached_activation":
        report["records"][1]["source_answer_snapshot_activated_under_selected_profile"] = True
        report["records"][1]["activated_answer_variant_refs"] = deepcopy(
            report["records"][0]["activated_answer_variant_refs"]
        )
        report["manifest"]["counts"]["activated_candidate_answer_snapshots"] += 1
    else:
        report["records"][0]["original_adjudication_group_record"]["typed_response_group_record"][
            "raw_source_assessment_record"
        ]["assessment"]["blockers"] = []
    report["records"] = [reseal(row) for row in report["records"]]
    helper().rebind_report(report)
    step = revision_step(owner, data)
    with pytest.raises(ValueError):
        assess(owner, data, [step])


@pytest.mark.parametrize(
    "damage",
    [
        "extra_component",
        "missing_component",
        "tuple_records",
        "too_many_epochs",
        "oversized_row",
        "unknown_field",
    ],
)
def test_offered_history_shape_and_size_refuse_before_any_epoch_regeneration(
    owner, fixture_data, baseline_step, baseline_report, monkeypatch, damage
):
    report = deepcopy(baseline_report)
    if damage == "extra_component":
        report["unqualified_head"] = []
    elif damage == "missing_component":
        del report["epoch_pages"]
    elif damage == "tuple_records":
        report["records"] = tuple(report["records"])
    elif damage == "too_many_epochs":
        report["epoch_manifests"] *= 3
    elif damage == "oversized_row":
        report["records"][0]["current_eligibility_blockers"] = ["x" * (1024**2 + 1)]
    else:
        report["records"][0]["approved_by_caller"] = True
        report["records"][0] = reseal(report["records"][0])
    monkeypatch.setattr(owner, "assess_source_history", refuse_replay)
    with pytest.raises(ValueError):
        validate(owner, report, fixture_data, [baseline_step])


def test_history_regenerates_genesis_once_and_each_revision_once_without_recursive_callbacks(
    owner, fixture_data, baseline_step, baseline_report, monkeypatch
):
    parent = epoch_report(baseline_report, REVISION_ID)
    third = revision_step(
        owner,
        fixture_data,
        epoch_id="fixture:history-counted:3",
        previous_report=parent,
        generation=3,
    )
    calls = {"genesis": 0, "adjudication": 0}
    original_genesis = genesis_owner.validate_source_applications
    original_adjudication = adjudication_owner.validate_source_adjudications

    def counted_genesis(*args, **kwargs):
        calls["genesis"] += 1
        return original_genesis(*args, **kwargs)

    def counted_adjudication(*args, **kwargs):
        calls["adjudication"] += 1
        return original_adjudication(*args, **kwargs)

    monkeypatch.setattr(genesis_owner, "validate_source_applications", counted_genesis)
    monkeypatch.setattr(adjudication_owner, "validate_source_adjudications", counted_adjudication)
    report = assess(owner, fixture_data, [baseline_step, third])
    assert calls == {"genesis": 1, "adjudication": 3}
    assert report["manifest"]["counts"]["epochs"] == 3


def test_lowered_outer_paging_preserves_every_request_in_every_epoch_and_has_no_prefix_activation(
    owner, fixture_data, baseline_step
):
    report = assess(owner, fixture_data, [baseline_step], limits={"max_groups_per_page": 1})
    assert len(report["pages"]) == len(report["records"])
    entries = [entry for page in report["pages"] for entry in page["entries"]]
    assert [entry["ordinal"] for entry in entries] == list(range(len(report["records"])))
    assert [entry["group_record_ref"] for entry in entries] == [
        ref(row) for row in report["records"]
    ]
    assert report["manifest"]["counts"]["current_eligible_groups"] == 1
    assert_narrow_history(owner, report)


@pytest.mark.parametrize(
    "failure",
    [
        "source_bad_signature",
        "source_revoked_at_current_time",
        "adjudication_bad_signature",
        "adjudication_revoked_at_current_time",
    ],
)
def test_old_epoch_remains_regenerated_while_fresh_current_source_or_adjudication_trust_blocks_use(
    owner, fixture_data, failure
):
    data = clone_case(fixture_data)
    current_time = "2026-10-14T10:00:00Z"
    data["at_time_utc"] = current_time
    if failure == "source_bad_signature":
        data["groups"][0]["reviews"][0]["signature"] = "A" * 86
    elif failure == "source_revoked_at_current_time":
        data["registry"]["keys"][0]["revoked_at_utc"] = "2026-10-14T09:30:00Z"
        data["registry"]["revocation_generation"] += 1
        helper().helper().helper().helper().refresh_signatures(data)
    data["typed_report"] = helper().helper().helper().assess(response_owner, data)
    helper().helper().replace_body(data, helper().helper().author(adjudication_owner, data))
    if failure == "adjudication_bad_signature":
        data["adjudication_groups"][0]["reviews"][0]["signature"] = "A" * 86
    elif failure == "adjudication_revoked_at_current_time":
        data["adjudication_registry"]["keys"][0]["revoked_at_utc"] = "2026-10-14T09:30:00Z"
        data["adjudication_registry"]["revocation_generation"] += 1
        helper().helper().refresh_signatures(data)
    data["adjudication_report"] = helper().helper().assess(adjudication_owner, data)
    step = revision_step(owner, data, declared=current_time, issued=current_time)
    report = assess(owner, fixture_data, [step], at_time_utc=current_time)
    assert epoch_report(report, GENESIS_ID) == fixture_data["genesis_report"]
    assert report["manifest"]["counts"]["historical_activated_groups_at_selected_epoch_times"] == 1
    revised = epoch_report(report, REVISION_ID)["records"][0]
    assert revised["application_content_status"] == "valid_declared_content"
    assert (
        revised["authority_assessment"]["review_prerequisites_satisfied_under_selected_trust"]
        is True
    )
    assert (
        "current_original_and_adjudication_authority_prerequisites_unavailable"
        in revised["application_blockers"]
    )
    assert revised["source_answer_snapshot_activated_under_selected_profile"] is False
    assert revised["activated_answer_variant_refs"] == []
    assert_narrow_history(owner, report)


def test_later_fresh_complete_revision_can_resolve_a_blocked_parent_without_inheriting_its_flags(
    owner, fixture_data
):
    blocked = revision_step(owner, fixture_data, mode="synthetic_fixture")
    blocked_history = assess(owner, fixture_data, [blocked])
    parent = epoch_report(blocked_history, REVISION_ID)
    assert parent["records"][0]["source_answer_snapshot_activated_under_selected_profile"] is False
    step = revision_step(
        owner,
        fixture_data,
        epoch_id="fixture:resolved-current:3",
        previous_report=parent,
        generation=3,
    )
    report = assess(owner, fixture_data, [blocked, step])
    assert epoch_report(report, REVISION_ID) == parent
    current = epoch_report(report, step["epoch_id"])["records"][0]
    assert current["source_answer_snapshot_activated_under_selected_profile"] is True
    assert len(current["activated_answer_variant_refs"]) == 9
    assert report["manifest"]["counts"]["historical_activated_groups_at_selected_epoch_times"] == 2
    assert report["manifest"]["counts"]["current_eligible_groups"] == 1
    assert_narrow_history(owner, report)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_page_bytes": 1},
        {"max_pages": 1, "max_groups_per_page": 1},
        {"max_collection_bytes": 1},
    ],
)
def test_complete_history_output_budget_refuses_whole_population_without_exposing_an_eligible_prefix(
    owner, fixture_data, baseline_step, limits
):
    with pytest.raises(ValueError):
        assess(owner, fixture_data, [baseline_step], limits=limits)


def test_detached_history_cannot_mutate_caller_input_roots_raw_groups_or_later_output(
    owner, fixture_data, baseline_step
):
    data = clone_case(fixture_data)
    step = deepcopy(baseline_step)
    before_data = clone_case(data)
    before_step = deepcopy(step)
    report = assess(owner, data, [step])
    assert data == before_data and step == before_step
    report["records"][0]["snapshot_group_record"]["application_blockers"].append(
        "fixture:output-only-change"
    )
    report["epoch_manifests"][0]["snapshot_manifest_record"]["producer_pins"][
        "fixture:output-only-producer"
    ] = "0" * 64
    report["manifest"]["revision_step_pins"][0]["policy_sha256"] = "0" * 64
    assert data == before_data and step == before_step


def test_changed_history_producer_bytes_during_generation_refuse_a_complete_result(
    owner, fixture_data, baseline_step, monkeypatch
):
    original = owner._pins
    count = 0

    def changing_pins():
        nonlocal count
        count += 1
        values = original()
        if count > 1:
            values["fixture:changed-producer"] = "0" * 64
        return values

    monkeypatch.setattr(owner, "_pins", changing_pins)
    with pytest.raises(ValueError, match="producers changed"):
        assess(owner, fixture_data, [baseline_step])


def test_public_import_does_not_restore_models_crypto_source_decoders_or_implicit_clocks():
    program = r"""
import sys
from ipfs_datasets_py.logic.autoformal import corpus_source_history as owner
for prefix in ('torch', 'transformers', 'pyarrow'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules)
assert 'ipfs_datasets_py.logic.autoformal.legal_source_review_handoff' not in sys.modules
assert 'ipfs_datasets_py.logic.profile_g' not in sys.modules
print('inert source history import verified')
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
    assert result.stdout.strip() == "inert source history import verified"

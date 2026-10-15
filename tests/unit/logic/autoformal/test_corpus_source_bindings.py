"""Synthetic binding declarations retain source geometry without becoming law.

Every principal, clock, document and signature is an authored engineering fixture.
External-shaped trust exercises a selected technical premise only.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import (
    corpus_source_adjudication as adjudication_owner,
)
from ipfs_datasets_py.logic.autoformal import corpus_source_application as genesis_owner
from ipfs_datasets_py.logic.autoformal import corpus_source_history as history_owner
from ipfs_datasets_py.logic.autoformal import corpus_source_review as source_owner
from ipfs_datasets_py.logic.autoformal import (
    corpus_source_review_responses as response_owner,
)
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust_owner
from ipfs_datasets_py.logic.profile_g import Ed25519Signer
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

DECLARED = "2026-10-14T09:00:00Z"
EVIDENCE_ID = "fixture:governing-source-binding-reason"
EVIDENCE_BYTES = b"Synthetic source selection rationale; no actual governing law."


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


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


@lru_cache(maxsize=1)
def helper():
    spec = importlib.util.spec_from_file_location(
        "authored_history_for_source_binding_tests",
        Path(__file__).with_name("test_corpus_source_history.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clone_case(data):
    return {
        key: value[:] if key.endswith("signers") else deepcopy(value)
        for key, value in data.items()
    }


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_source_bindings

    return corpus_source_bindings


@pytest.fixture(scope="module")
def fixture_data(tmp_path_factory):
    return helper().fixture_data.__wrapped__(tmp_path_factory)


@pytest.fixture(scope="module")
def baseline_step(fixture_data):
    return helper().baseline_step.__wrapped__(fixture_data)


@pytest.fixture(scope="module")
def baseline_report(fixture_data, baseline_step):
    return helper().baseline_report.__wrapped__(fixture_data, baseline_step)


def replay_inputs(data, steps, **options):
    return {
        "genesis_report": data["genesis_report"],
        "genesis_inputs": helper().genesis_inputs(data),
        "revision_steps": steps,
        **helper().assessment_arguments(data, steps),
        **options,
    }


def catalog(data):
    """Read original fixture JSONL components; do not call the product catalog."""
    original = data["data"]["arguments"]
    raw_components = (
        original["alignment_replay_inputs"]["base_corpus_bytes"]["records"],
        original["alignment_corpus_bytes"]["records"],
    )
    result = {}
    for raw in raw_components:
        for line in raw.splitlines():
            record = json.loads(line)
            cid = record["record_cid"]
            if cid in result:
                assert result[cid] == record
            result[cid] = record
    return result


def choice(data, ordinal=0, *, view="normalized", occurrence_cid=None):
    records = catalog(data)
    request = data["preparation"]["requests"][ordinal]
    parent = records[request["parent_record_cid"]]
    comparison = records[request["comparison_record_cids"][0]]
    document = records[comparison["related_records"]["document_record_cid"]]
    version = records[document["related_records"][view + "_source_version_cid"]]
    occurrence = (
        records[occurrence_cid]
        if occurrence_cid is not None
        else next(
            row
            for row in records.values()
            if row.get("source_version_cid") == version["record_cid"]
            and "start_char" in row
        )
    )
    context = next(
        row
        for row in records.values()
        if row.get("source_occurrence_cid") == occurrence["record_cid"]
        and "availability" in row
    )
    return {
        "parent_ref": ref(parent),
        "comparison_ref": ref(comparison),
        "document_observation_ref": ref(document),
        "source_version_ref": ref(version),
        "source_occurrence_ref": ref(occurrence),
        "context_ref": ref(context),
        "declared_region_role": "operative_body",
        "applicability": {
            "scope_id": data["preparation"]["subjects"][ordinal]["scope_id"],
            "jurisdiction_id": "fixture:jurisdiction",
            "instrument_id": "fixture:instrument",
            "legal_as_of_civil_date": "2026-10-14",
            "evidence_occurrence_refs": [ref(occurrence)],
        },
    }


def current_group(report, ordinal=0):
    return next(
        row
        for row in report["records"]
        if row["epoch_id"] == report["manifest"]["current_epoch_id"]
        and row["queue_ordinal"] == ordinal
    )


def declaration_pins(data, history, ordinal=0, **options):
    return {
        "expected_request_sha256": sha(
            canonical_dag_json_bytes(data["preparation"]["requests"][ordinal])
        ),
        "expected_subject_sha256": sha(
            canonical_dag_json_bytes(data["preparation"]["subjects"][ordinal])
        ),
        "expected_current_history_group_sha256": sha(
            canonical_dag_json_bytes(current_group(history, ordinal))
        ),
        "expected_preparation_manifest_sha256": sha(
            canonical_dag_json_bytes(data["preparation"]["manifest"])
        ),
        "expected_history_manifest_sha256": sha(
            canonical_dag_json_bytes(history["manifest"])
        ),
        "current_epoch_id": history["manifest"]["current_epoch_id"],
        "declared_at_utc": DECLARED,
        "rationale": "An explicit candidate source tuple; no legal truth or physical-source application.",
        "evidence_refs": [{"artifact_id": EVIDENCE_ID, "sha256": sha(EVIDENCE_BYTES)}],
        **options,
    }


def author(owner, data, history, ordinal=0, *, selected=None, **options):
    return owner.record_source_binding_declaration(
        data["preparation"]["requests"][ordinal],
        data["preparation"]["subjects"][ordinal],
        current_group(history, ordinal),
        choice(data, ordinal) if selected is None else selected,
        **declaration_pins(data, history, ordinal, **options),
    )


def authority(owner, data, *, mode="external_pinned_trust"):
    registry = deepcopy(data["application_registry"])
    registry["mode"] = mode
    policy = deepcopy(data["application_policy"])
    policy.update(
        mode=mode,
        policy_id="fixture:source-binding-policy",
        registry_sha256=sha(canonical(registry)),
        action=owner.ACTION,
        audience=owner.AUDIENCE,
    )
    return registry, policy, data["application_signers"][:]


def sign_group(owner, data, body, ordinal=0, *, issued=DECLARED):
    request, subject = (
        data["preparation"]["requests"][ordinal],
        data["preparation"]["subjects"][ordinal],
    )
    identity = f"fixture:binding-body:{ordinal}"
    raw = canonical_dag_json_bytes(body)
    obligations = [
        {
            "slot_id": row["slot_id"],
            "disposition": row["disposition"],
            "evidence_refs": [{"artifact_id": identity, "sha256": sha(raw)}],
        }
        for row in data["adjudication_groups"][ordinal]["reviews"][0][
            "context_closure"
        ]["obligations"]
    ]
    source_helper = helper().helper().helper().helper().helper()
    reviews = [
        signer.sign(
            {
                "schema": owner.CLAIM_SCHEMA,
                "action": owner.ACTION,
                "audience": owner.AUDIENCE,
                "review_id": f"fixture:binding-review:{ordinal}:{index}",
                "key_id": key["key_id"],
                "principal_id": key["principal_id"],
                "role": role,
                "registry_sha256": sha(canonical(data["binding_registry"])),
                "policy_sha256": sha(canonical(data["binding_policy"])),
                "issued_at_utc": issued,
                "expires_at_utc": source_helper.EXPIRES,
                "subject": deepcopy(subject),
                "interpretation": {
                    "decision": "support",
                    "reviewed_graph_sha256": subject["graph_sha256"],
                    "reviewed_ast_sha256": subject["ast_sha256"],
                    "rationale": "Support for fixture tuple only.",
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
                data["binding_signers"],
                data["binding_registry"]["keys"],
                trust_owner.ROLES,
                strict=True,
            )
        )
    ]
    return {
        "request_cid": request["record_cid"],
        "reviews": reviews,
        "binding_artifact_id": identity,
        "evidence_artifacts": {identity: raw, EVIDENCE_ID: EVIDENCE_BYTES},
        "observed_artifact_sha256s": deepcopy(
            data["groups"][ordinal]["observed_artifact_sha256s"]
        ),
        "observed_pins": deepcopy(data["groups"][ordinal]["observed_pins"]),
    }


def group_pins(groups):
    source = helper().helper().helper().helper().helper()
    return [
        {**pin, "binding_artifact_id": group["binding_artifact_id"]}
        for pin, group in zip(source.group_pins(groups), groups, strict=True)
    ]


def signed_case(
    owner, original, history, *, selected=None, mode="external_pinned_trust"
):
    data = clone_case(original)
    data["binding_registry"], data["binding_policy"], data["binding_signers"] = (
        authority(owner, data, mode=mode)
    )
    data["binding_groups"] = []
    for ordinal, request in enumerate(data["preparation"]["requests"]):
        if ordinal == 0:
            data["binding_groups"].append(
                sign_group(owner, data, author(owner, data, history, selected=selected))
            )
        else:
            data["binding_groups"].append(
                {
                    "request_cid": request["record_cid"],
                    "reviews": [],
                    "binding_artifact_id": None,
                    "evidence_artifacts": {},
                    "observed_artifact_sha256s": deepcopy(
                        data["groups"][ordinal]["observed_artifact_sha256s"]
                    ),
                    "observed_pins": deepcopy(data["groups"][ordinal]["observed_pins"]),
                }
            )
    return data


def assess_arguments(data, history, **options):
    return {
        "expected_history_manifest_sha256": sha(
            canonical_dag_json_bytes(history["manifest"])
        ),
        "expected_binding_registry_sha256": sha(canonical(data["binding_registry"])),
        "expected_binding_policy_sha256": sha(canonical(data["binding_policy"])),
        "expected_binding_group_pins": group_pins(data["binding_groups"]),
        **options,
    }


def assess(owner, data, history, steps, *, replay=None, **options):
    return owner.assess_source_bindings(
        history,
        replay_inputs(data, steps) if replay is None else replay,
        data["binding_registry"],
        data["binding_policy"],
        data["binding_groups"],
        **assess_arguments(data, history, **options),
    )


def validate(owner, report, data, history, steps, **options):
    return owner.validate_source_bindings(
        report,
        history,
        replay_inputs(data, steps),
        data["binding_registry"],
        data["binding_policy"],
        data["binding_groups"],
        **assess_arguments(data, history, **options),
    )


def refresh_signatures(data):
    data["binding_policy"]["registry_sha256"] = sha(canonical(data["binding_registry"]))
    for group in data["binding_groups"]:
        for index, old in enumerate(group["reviews"]):
            body = {
                key: deepcopy(value)
                for key, value in old.items()
                if key not in {"signer_did", "signature_alg", "signature"}
            }
            body["registry_sha256"] = sha(canonical(data["binding_registry"]))
            body["policy_sha256"] = sha(canonical(data["binding_policy"]))
            group["reviews"][index] = data["binding_signers"][index].sign(body)


def replace_body(data, body, *, resign=True):
    group = data["binding_groups"][0]
    identity = group["binding_artifact_id"]
    raw = canonical_dag_json_bytes(body)
    group["evidence_artifacts"][identity] = raw
    if resign:
        for review in group["reviews"]:
            for obligation in review["context_closure"]["obligations"]:
                obligation["evidence_refs"] = [
                    {"artifact_id": identity, "sha256": sha(raw)}
                ]
        refresh_signatures(data)


def assert_narrow(owner, report):
    for component, values in report.items():
        if component.startswith("history_"):
            continue
        for row in [values] if component == "manifest" else values:
            assert row["view"] == "candidate" and reseal(row) == row
            assert len(canonical_dag_json_bytes(row)) <= contracts.MAX_RECORD_BYTES
            for flag in owner.FALSE_FLAGS:
                assert row[flag] is False


def refuse_replay(*_args, **_kwargs):
    pytest.fail(
        "Untrusted binding boundary reached indexed body hashing or complete history replay"
    )


def guard_replay(monkeypatch, owner, data, steps, *, block_history_call=True):
    helper().guard_indexed_body_hashes(
        monkeypatch, owner, helper().genesis_inputs(data), steps
    )
    bodies = {
        raw
        for group in data["binding_groups"]
        for raw in group["evidence_artifacts"].values()
    }
    original = owner._sha

    def guarded(raw):
        if raw in bodies:
            refuse_replay()
        return original(raw)

    monkeypatch.setattr(owner, "_sha", guarded)
    if block_history_call:
        monkeypatch.setattr(history_owner, "validate_source_history", refuse_replay)


@pytest.fixture(scope="module")
def baseline_binding_data(fixture_data, baseline_report):
    from ipfs_datasets_py.logic.autoformal import corpus_source_bindings

    return signed_case(corpus_source_bindings, fixture_data, baseline_report)


@pytest.fixture(scope="module")
def baseline_binding_report(baseline_binding_data, baseline_report, baseline_step):
    from ipfs_datasets_py.logic.autoformal import corpus_source_bindings

    return assess(
        corpus_source_bindings, baseline_binding_data, baseline_report, [baseline_step]
    )


def test_signed_current_binding_preserves_all_history_components_without_applying_physical_law(
    owner,
    baseline_binding_data,
    baseline_report,
    baseline_step,
    baseline_binding_report,
):
    report = baseline_binding_report
    assert set(report) == {
        "manifest",
        "pages",
        "records",
        "history_manifest",
        "history_pages",
        "history_records",
        "history_epoch_manifests",
        "history_epoch_pages",
    }
    for component, value in baseline_report.items():
        assert report["history_" + component] == value
    group = report["records"][0]
    assert group["structured_source_binding_declared_under_selected_profile"] is True
    assert group["binding_content_status"] == "valid_declared_content"
    assert group["original_current_history_group_record"] == current_group(
        baseline_report
    )
    assert group["original_contexts_remain_required_unavailable"] is True
    assert len(group["declared_binding_refs"]) == 1
    counts = report["manifest"]["counts"]
    assert (
        counts["declared_structured_bindings"] == 1
        and counts["declared_active_answer_slots"] == 9
    )
    assert counts["groups"] == len(baseline_binding_data["preparation"]["requests"])
    assert (
        counts["source_decisions_applied"]
        == counts["physical_governing_bindings_applied"]
        == 0
    )
    assert_narrow(owner, report)
    assert (
        validate(owner, report, baseline_binding_data, baseline_report, [baseline_step])
        == report
    )


def test_authoring_is_structural_without_catalog_replay_or_authentication(
    owner, fixture_data, baseline_report, monkeypatch
):
    monkeypatch.setattr(owner, "_catalog", refuse_replay)
    monkeypatch.setattr(history_owner, "validate_source_history", refuse_replay)
    monkeypatch.setattr(trust_owner, "_assess_reviews", refuse_replay)
    selected = choice(fixture_data)
    body = author(owner, fixture_data, baseline_report, selected=selected)
    assert reseal(body) == body
    for flag in owner.FALSE_FLAGS:
        assert body[flag] is False
    assert (
        owner.validate_source_binding_declaration(
            body,
            fixture_data["preparation"]["requests"][0],
            fixture_data["preparation"]["subjects"][0],
            current_group(baseline_report),
            selected,
            **declaration_pins(fixture_data, baseline_report),
        )
        == body
    )


@pytest.mark.parametrize(
    "field",
    [
        "parent_ref",
        "comparison_ref",
        "document_observation_ref",
        "source_version_ref",
        "source_occurrence_ref",
        "context_ref",
    ],
)
def test_full_source_references_are_closed_and_not_cid_only(
    owner, fixture_data, baseline_report, field
):
    selected = choice(fixture_data)
    del selected[field]["sha256"]
    with pytest.raises(ValueError):
        author(owner, fixture_data, baseline_report, selected=selected)


@pytest.mark.parametrize(
    "field",
    [
        "expected_request_sha256",
        "expected_subject_sha256",
        "expected_current_history_group_sha256",
    ],
)
def test_authoring_rejects_wrong_exact_record_pins(
    owner, fixture_data, baseline_report, field
):
    with pytest.raises(ValueError):
        author(owner, fixture_data, baseline_report, **{field: "0" * 64})


@pytest.mark.parametrize(
    "field",
    ["expected_preparation_manifest_sha256", "expected_history_manifest_sha256"],
)
def test_authoring_root_pins_must_be_explicit_sha256(
    owner, fixture_data, baseline_report, field
):
    with pytest.raises(ValueError):
        author(owner, fixture_data, baseline_report, **{field: None})


@pytest.mark.parametrize(
    "damage",
    [
        "extra_choice",
        "extra_applicability",
        "selector",
        "extra_ref",
        "wrong_schema",
        "wrong_parent",
        "wrong_comparison",
        "bool_date",
        "timestamp_date",
        "impossible_date",
        "noncanonical_date",
        "duplicate_evidence_occurrence",
        "empty_evidence_occurrences",
    ],
)
def test_choice_has_exact_existing_identity_shapes_and_civil_date_syntax(
    owner, fixture_data, baseline_report, damage
):
    selected = choice(fixture_data)
    if damage == "extra_choice":
        selected["legal_truth"] = True
    elif damage == "extra_applicability":
        selected["applicability"]["authenticated_wall_clock"] = True
    elif damage == "selector":
        selected["source_occurrence_ref"]["start_char"] = 0
    elif damage == "extra_ref":
        selected["context_ref"]["governing"] = True
    elif damage == "wrong_schema":
        selected["source_occurrence_ref"]["schema"] = (
            contracts.SOURCE_VERSION_SCHEMA
            if hasattr(contracts, "SOURCE_VERSION_SCHEMA")
            else "fixture:wrong-schema"
        )
    elif damage == "wrong_parent":
        selected["parent_ref"] = ref(
            next(
                row
                for row in catalog(fixture_data).values()
                if row["schema"] == selected["parent_ref"]["schema"]
                and row["record_cid"] != selected["parent_ref"]["record_cid"]
            )
        )
    elif damage == "wrong_comparison":
        considered = fixture_data["preparation"]["requests"][0][
            "comparison_record_cids"
        ]
        selected["comparison_ref"] = ref(
            next(
                row
                for row in catalog(fixture_data).values()
                if row.get("kind") == "comparison"
                and row["record_cid"] not in considered
            )
        )
    elif damage == "duplicate_evidence_occurrence":
        selected["applicability"]["evidence_occurrence_refs"] *= 2
    elif damage == "empty_evidence_occurrences":
        selected["applicability"]["evidence_occurrence_refs"] = []
    else:
        selected["applicability"]["legal_as_of_civil_date"] = {
            "bool_date": True,
            "timestamp_date": DECLARED,
            "impossible_date": "2026-02-30",
            "noncanonical_date": "2026-1-2",
        }[damage]
    with pytest.raises(ValueError):
        author(owner, fixture_data, baseline_report, selected=selected)


@pytest.mark.parametrize(
    "field,value,blocker",
    [
        ("date", None, "declared_legal_as_of_civil_date_unavailable"),
        ("role", "unknown", "declared_source_region_role_unavailable"),
    ],
)
def test_unknown_legal_date_or_role_is_retained_without_using_utc_to_complete_it(
    owner, fixture_data, baseline_report, baseline_step, field, value, blocker
):
    selected = choice(fixture_data)
    if field == "date":
        selected["applicability"]["legal_as_of_civil_date"] = value
    else:
        selected["declared_region_role"] = value
    data = signed_case(owner, fixture_data, baseline_report, selected=selected)
    report = assess(owner, data, baseline_report, [baseline_step])
    group = report["records"][0]
    assert group["binding_content_status"] == "valid_declared_content"
    assert blocker in group["binding_blockers"]
    assert group["structured_source_binding_declared_under_selected_profile"] is False
    assert group["declared_binding_refs"] == []
    assert_narrow(owner, report)


@pytest.mark.parametrize(
    "field",
    [
        "document_observation_ref",
        "source_version_ref",
        "source_occurrence_ref",
        "context_ref",
    ],
)
def test_other_document_view_or_occurrence_is_rejected_with_authenticated_raw_body_retained(
    owner, fixture_data, baseline_report, baseline_step, field
):
    selected = choice(fixture_data)
    records = catalog(fixture_data)
    other_comparison = records[
        fixture_data["preparation"]["requests"][0]["comparison_record_cids"][1]
    ]
    other_document = records[other_comparison["related_records"]["document_record_cid"]]
    other_version = records[
        other_document["related_records"]["normalized_source_version_cid"]
    ]
    other_occurrence = next(
        row
        for row in records.values()
        if row.get("source_version_cid") == other_version["record_cid"]
        and "start_char" in row
    )
    other_context = next(
        row
        for row in records.values()
        if row.get("source_occurrence_cid") == other_occurrence["record_cid"]
        and "availability" in row
    )
    selected[field] = ref(
        {
            "document_observation_ref": other_document,
            "source_version_ref": other_version,
            "source_occurrence_ref": other_occurrence,
            "context_ref": other_context,
        }[field]
    )
    data = signed_case(owner, fixture_data, baseline_report, selected=selected)
    report = assess(owner, data, baseline_report, [baseline_step])
    group = report["records"][0]
    assert group["binding_content_status"] == "rejected" and group["content_blockers"]
    assert group["binding_declaration_artifact_ref"] is not None
    assert (
        group["authority_assessment"][
            "review_prerequisites_satisfied_under_selected_trust"
        ]
        is True
    )
    assert group["structured_source_binding_declared_under_selected_profile"] is False
    assert_narrow(owner, report)


@pytest.mark.parametrize("view", ["normalized", "rendered"])
def test_existing_comparison_source_views_retain_distinct_version_geometry(
    owner, fixture_data, baseline_report, baseline_step, view
):
    selected = choice(fixture_data, view=view)
    data = signed_case(owner, fixture_data, baseline_report, selected=selected)
    report = assess(owner, data, baseline_report, [baseline_step])
    assert (
        report["records"][0][
            "structured_source_binding_declared_under_selected_profile"
        ]
        is True
    )
    assert (
        choice(fixture_data, view="normalized")["source_version_ref"]
        != choice(fixture_data, view="rendered")["source_version_ref"]
    )
    assert_narrow(owner, report)


def test_existing_unicode_coordinates_are_not_recomputed_from_literal_matches(
    fixture_data,
):
    selected = choice(fixture_data)
    records = catalog(fixture_data)
    version_cid = selected["source_version_ref"]["record_cid"]
    occurrences = [
        row
        for row in records.values()
        if row.get("source_version_cid") == version_cid and "start_char" in row
    ]
    assert any(
        row["start_char"] != row["start_utf8"] or row["end_char"] != row["end_utf8"]
        for row in occurrences
    )
    assert all(
        sha(row["span_text"].encode()) == row["span_sha256"] for row in occurrences
    )


@pytest.mark.parametrize(
    "pin",
    [
        "expected_history_manifest_sha256",
        "expected_binding_registry_sha256",
        "expected_binding_policy_sha256",
    ],
)
def test_independent_input_pins_refuse_before_history_or_indexed_body_hashes(
    owner, baseline_binding_data, baseline_report, baseline_step, monkeypatch, pin
):
    guard_replay(monkeypatch, owner, baseline_binding_data, [baseline_step])
    with pytest.raises(ValueError):
        assess(
            owner,
            baseline_binding_data,
            baseline_report,
            [baseline_step],
            **{pin: "0" * 64},
        )


@pytest.mark.parametrize(
    "damage",
    [
        "missing_history",
        "callback",
        "unknown_argument",
        "wrong_current_epoch",
        "bad_independent_epoch_pin",
    ],
)
def test_complete_history_replay_arguments_are_closed_and_pinned(
    owner, baseline_binding_data, baseline_report, baseline_step, monkeypatch, damage
):
    replay = replay_inputs(baseline_binding_data, [baseline_step])
    if damage == "missing_history":
        del replay["genesis_inputs"]
    elif damage == "callback":
        replay["validator"] = refuse_replay
    elif damage == "unknown_argument":
        replay["cached_eligible"] = True
    elif damage == "wrong_current_epoch":
        replay["current_epoch_id"] = "fixture:absent-current"
    else:
        replay["expected_revision_step_pins"][0]["registry_sha256"] = "0" * 64
    guard_replay(
        monkeypatch,
        owner,
        baseline_binding_data,
        [baseline_step],
        block_history_call=damage != "bad_independent_epoch_pin",
    )
    with pytest.raises(ValueError):
        assess(
            owner,
            baseline_binding_data,
            baseline_report,
            [baseline_step],
            replay=replay,
        )


@pytest.mark.parametrize(
    "damage",
    [
        "bad_signature",
        "old_domain",
        "old_audience",
        "missing_role",
        "expired",
        "revoked",
        "wrong_scope",
        "dependency_drift",
    ],
)
def test_fresh_binding_authority_requires_current_domain_roles_scope_clock_and_dependencies(
    owner, baseline_binding_data, baseline_report, baseline_step, damage
):
    data = clone_case(baseline_binding_data)
    review = data["binding_groups"][0]["reviews"][0]
    if damage == "bad_signature":
        review["signature"] = "A" * 86
    elif damage == "old_domain":
        review["action"] = history_owner.ACTION
        refresh_signatures(data)
    elif damage == "old_audience":
        review["audience"] = history_owner.AUDIENCE
        refresh_signatures(data)
    elif damage == "missing_role":
        data["binding_groups"][0]["reviews"].pop()
    elif damage == "expired":
        review["issued_at_utc"] = "2026-10-14T08:00:00Z"
        review["expires_at_utc"] = "2026-10-14T08:59:59Z"
        refresh_signatures(data)
    elif damage == "revoked":
        data["binding_registry"]["keys"][0]["revoked_at_utc"] = DECLARED
        data["binding_registry"]["revocation_generation"] += 1
        refresh_signatures(data)
    elif damage == "wrong_scope":
        data["binding_registry"]["keys"][0]["scope_ids"] = ["fixture:other-scope"]
        refresh_signatures(data)
    else:
        group = data["binding_groups"][0]
        artifact = next(iter(group["observed_artifact_sha256s"]))
        group["observed_artifact_sha256s"][artifact] = "0" * 64
    if damage in {"old_domain", "old_audience"}:
        with pytest.raises(ValueError, match="signing domain differs"):
            assess(owner, data, baseline_report, [baseline_step])
        return
    report = assess(owner, data, baseline_report, [baseline_step])
    assert (
        report["records"][0][
            "structured_source_binding_declared_under_selected_profile"
        ]
        is False
    )
    if damage == "expired":
        assert any(
            "review_not_current" in row["blockers"]
            for row in report["records"][0]["authority_assessment"]["reviews"]
        )
        assert (
            "binding_claim_predates_common_declaration"
            in report["records"][0]["binding_blockers"]
        )
    assert (
        report["records"][0]["authority_assessment"][
            "review_prerequisites_satisfied_under_selected_trust"
        ]
        is False
    )
    assert_narrow(owner, report)


@pytest.mark.parametrize(
    "damage", ["future_declaration", "before_history", "claim_before_body"]
)
def test_binding_chronology_requires_fresh_declaration_and_claim_at_selected_history_time(
    owner, baseline_binding_data, baseline_report, baseline_step, damage
):
    data = clone_case(baseline_binding_data)
    group = data["binding_groups"][0]
    body = json.loads(group["evidence_artifacts"][group["binding_artifact_id"]])
    if damage == "future_declaration":
        body["declared_at_utc"] = "2026-10-14T09:00:01Z"
    elif damage == "before_history":
        body["declared_at_utc"] = "2026-10-14T08:59:59Z"
    else:
        group["reviews"][0]["issued_at_utc"] = "2026-10-14T08:59:59Z"
    replace_body(data, reseal(body))
    report = assess(owner, data, baseline_report, [baseline_step])
    assert report["records"][0]["binding_content_status"] == "valid_declared_content"
    assert (
        report["records"][0][
            "structured_source_binding_declared_under_selected_profile"
        ]
        is False
    )
    assert report["records"][0]["binding_blockers"]
    assert_narrow(owner, report)


def test_later_binding_signed_population_is_capped_before_indexed_hashing(
    owner, baseline_binding_data, baseline_report, baseline_step, monkeypatch
):
    data = clone_case(baseline_binding_data)
    later = data["binding_groups"][-1]
    later["reviews"] = [deepcopy(data["binding_groups"][0]["reviews"][0])]
    later["reviews"][0]["interpretation"]["rationale"] = "x" * (
        contracts.MAX_RECORD_BYTES + 1
    )
    guard_replay(monkeypatch, owner, data, [baseline_step])
    with pytest.raises(ValueError):
        assess(owner, data, baseline_report, [baseline_step])


@pytest.mark.parametrize(
    "limits",
    [
        {"max_all_input_bytes": 1},
        {"max_all_input_nodes": 1},
        {"max_input_depth": 1},
        {"max_all_signed_evidence_bytes": 1},
    ],
)
def test_global_input_and_signed_evidence_caps_refuse_before_replay_and_indexed_hashing(
    owner, baseline_binding_data, baseline_report, baseline_step, monkeypatch, limits
):
    guard_replay(monkeypatch, owner, baseline_binding_data, [baseline_step])
    with pytest.raises(ValueError):
        assess(
            owner,
            baseline_binding_data,
            baseline_report,
            [baseline_step],
            limits=limits,
        )


@pytest.mark.parametrize(
    "component",
    [
        "manifest",
        "pages",
        "records",
        "history_manifest",
        "history_pages",
        "history_records",
        "history_epoch_manifests",
        "history_epoch_pages",
    ],
)
def test_all_eight_output_components_are_revalidated_not_merely_resealed(
    owner,
    baseline_binding_data,
    baseline_report,
    baseline_step,
    baseline_binding_report,
    component,
):
    report = deepcopy(baseline_binding_report)
    if component in {"manifest", "history_manifest"}:
        report[component]["view"] = "authoritative"
        report[component] = reseal(report[component])
    else:
        report[component] = report[component][:-1]
    with pytest.raises(ValueError):
        validate(owner, report, baseline_binding_data, baseline_report, [baseline_step])


def test_history_replays_once_and_source_catalog_does_not_add_a_third_raw_replay(
    owner, baseline_binding_data, baseline_report, baseline_step, monkeypatch
):
    calls = []
    original = history_owner.validate_source_history

    def counted(*args, **kwargs):
        calls.append("history")
        return original(*args, **kwargs)

    monkeypatch.setattr(history_owner, "validate_source_history", counted)
    report = assess(owner, baseline_binding_data, baseline_report, [baseline_step])
    assert calls == ["history"]
    assert report["history_records"] == baseline_report["records"]


@pytest.mark.parametrize(
    "limits",
    [
        {"max_page_bytes": 1},
        {"max_collection_bytes": 1},
        {"max_pages": 1, "max_groups_per_page": 1},
    ],
)
def test_full_output_limits_refuse_without_exposing_a_bound_prefix(
    owner, baseline_binding_data, baseline_report, baseline_step, limits
):
    with pytest.raises(ValueError):
        assess(
            owner,
            baseline_binding_data,
            baseline_report,
            [baseline_step],
            limits=limits,
        )


def test_lowered_page_population_preserves_every_group_and_detaches_caller_data(
    owner, baseline_binding_data, baseline_report, baseline_step
):
    data = clone_case(baseline_binding_data)
    before = clone_case(data)
    history = deepcopy(baseline_report)
    history_before = deepcopy(history)
    step = deepcopy(baseline_step)
    report = assess(owner, data, history, [step], limits={"max_groups_per_page": 1})
    assert len(report["pages"]) == len(report["records"])
    assert data == before and history == history_before and step == baseline_step
    report["history_records"][0]["current_eligibility_blockers"].append(
        "fixture:output-only-change"
    )
    report["records"][0]["binding_blockers"].append("fixture:output-only-change")
    assert data == before and history == history_before


def test_changed_binding_producers_during_generation_refuse_the_complete_result(
    owner, baseline_binding_data, baseline_report, baseline_step, monkeypatch
):
    original = owner._pins
    count = 0

    def changing():
        nonlocal count
        count += 1
        values = original()
        if count > 1:
            values["fixture:changed-producer"] = "0" * 64
        return values

    monkeypatch.setattr(owner, "_pins", changing)
    with pytest.raises(ValueError, match="producer.*changed"):
        assess(owner, baseline_binding_data, baseline_report, [baseline_step])


def test_cold_public_import_remains_inert_without_models_crypto_or_source_replay():
    program = r"""
import sys
from ipfs_datasets_py.logic.autoformal import corpus_source_bindings
for prefix in ('torch', 'transformers', 'pyarrow'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules)
assert 'ipfs_datasets_py.logic.profile_g' not in sys.modules
assert 'ipfs_datasets_py.logic.autoformal.legal_source_review_handoff' not in sys.modules
print('inert source bindings import verified')
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
    assert result.stdout.strip() == "inert source bindings import verified"


@pytest.mark.parametrize("identity", ["principal", "did", "public_key"])
def test_authenticated_binding_actors_cannot_reuse_original_source_identities(
    owner, baseline_binding_data, baseline_report, baseline_step, identity
):
    data = clone_case(baseline_binding_data)
    original_key = data["registry"]["keys"][0]
    key = data["binding_registry"]["keys"][0]
    if identity == "principal":
        key["principal_id"] = original_key["principal_id"]
    elif identity == "did":
        key["signer_did"] = original_key["signer_did"]
        data["binding_signers"][0] = Ed25519Signer(
            key["signer_did"], data["application_signers"][0].private_key
        )
    else:
        key["public_key_hex"] = original_key["public_key_hex"]
        data["binding_signers"][0] = Ed25519Signer(
            key["signer_did"], data["signers"][0].private_key
        )
    review = data["binding_groups"][0]["reviews"][0]
    review["key_id"], review["principal_id"] = key["key_id"], key["principal_id"]
    refresh_signatures(data)
    report = assess(owner, data, baseline_report, [baseline_step])
    group = report["records"][0]
    assert (
        group["authority_assessment"][
            "review_prerequisites_satisfied_under_selected_trust"
        ]
        is True
    )
    assert group["structured_source_binding_declared_under_selected_profile"] is False
    expected = {
        "principal": "binding_actor_is_a_supplied_history_original_reviewer",
        "did": "binding_actor_reuses_a_supplied_history_original_reviewer_did",
        "public_key": "binding_actor_reuses_a_supplied_history_original_reviewer_public_key",
    }[identity]
    assert expected in group["binding_blockers"]
    assert group["declared_binding_refs"] == []
    assert_narrow(owner, report)


@pytest.mark.parametrize("mode", ["synthetic_fixture", "unavailable"])
def test_nonexternal_binding_registry_is_not_authority(
    owner, fixture_data, baseline_report, baseline_step, mode
):
    data = signed_case(owner, fixture_data, baseline_report)
    data["binding_registry"]["mode"] = mode
    data["binding_policy"]["mode"] = mode
    if mode == "unavailable":
        data["binding_registry"]["keys"] = []
        for group in data["binding_groups"]:
            group["reviews"] = []
            group["binding_artifact_id"] = None
            group["evidence_artifacts"] = {}
    refresh_signatures(data)
    report = assess(owner, data, baseline_report, [baseline_step])
    assert (
        report["records"][0][
            "structured_source_binding_declared_under_selected_profile"
        ]
        is False
    )
    assert (
        report["records"][0]["authority_assessment"][
            "review_prerequisites_satisfied_under_selected_trust"
        ]
        is False
    )
    assert_narrow(owner, report)


@pytest.mark.parametrize("history_kind", ["genesis_only", "sibling_fork"])
def test_cached_binding_from_old_current_history_does_not_survive_genesis_or_visible_forks(
    owner, fixture_data, baseline_binding_data, baseline_step, history_kind
):
    steps = (
        []
        if history_kind == "genesis_only"
        else [
            baseline_step,
            helper().revision_step(
                history_owner, fixture_data, epoch_id="fixture:binding-other-branch"
            ),
        ]
    )
    offered = helper().assess(history_owner, fixture_data, steps)
    assert offered["manifest"]["counts"]["current_eligible_groups"] == 0
    data = clone_case(baseline_binding_data)
    report = assess(owner, data, offered, steps)
    assert report["history_records"] == offered["records"]
    assert report["manifest"]["counts"]["declared_structured_bindings"] == 0
    assert report["manifest"]["counts"]["declared_active_answer_slots"] == 0
    assert all(
        row["structured_source_binding_declared_under_selected_profile"] is False
        for row in report["records"]
    )
    assert (
        "current_history_candidate_prerequisites_unavailable"
        in report["records"][0]["binding_blockers"]
    )
    assert_narrow(owner, report)


@pytest.mark.parametrize(
    "damage", ["root", "epoch", "answer_ref", "semantic_flag", "changed_evidence"]
)
def test_resealed_or_resigned_content_cannot_repair_different_roots_answers_or_evidence(
    owner, baseline_binding_data, baseline_report, baseline_step, damage
):
    data = clone_case(baseline_binding_data)
    group = data["binding_groups"][0]
    body = json.loads(group["evidence_artifacts"][group["binding_artifact_id"]])
    if damage == "root":
        body["history_manifest_sha256"] = "0" * 64
    elif damage == "epoch":
        body["current_epoch_id"] = "fixture:other-binding-epoch"
    elif damage == "answer_ref":
        body["selected_answer_variant_refs"][0]["sha256"] = "0" * 64
    elif damage == "semantic_flag":
        body["structured_binding_establishes_legal_truth"] = True
    else:
        group["evidence_artifacts"][
            EVIDENCE_ID
        ] = b"Evidence changed despite retained declaration."
    replace_body(data, reseal(body))
    report = assess(owner, data, baseline_report, [baseline_step])
    row = report["records"][0]
    assert row["binding_content_status"] == "rejected" and row["content_blockers"]
    assert row["binding_declaration_artifact_ref"] is not None
    assert row["structured_source_binding_declared_under_selected_profile"] is False
    assert_narrow(owner, report)


@pytest.mark.parametrize(
    "population", ["genesis_original", "revision_original", "revision_claims"]
)
def test_all_historical_signed_populations_are_capped_before_first_indexed_hash(
    owner,
    baseline_binding_data,
    baseline_report,
    baseline_step,
    monkeypatch,
    population,
):
    data = clone_case(baseline_binding_data)
    steps = [deepcopy(baseline_step)]
    replay = replay_inputs(data, steps)
    groups = {
        "genesis_original": replay["genesis_inputs"]["adjudication_replay_inputs"][
            "source_review_groups"
        ],
        "revision_original": steps[0]["adjudication_replay_inputs"][
            "source_review_groups"
        ],
        "revision_claims": steps[0]["revision_groups"],
    }[population]
    groups[-1]["reviews"] = [deepcopy(groups[0]["reviews"][0])]
    groups[-1]["reviews"][0]["interpretation"]["rationale"] = "x" * (
        contracts.MAX_RECORD_BYTES + 1
    )
    guard_replay(monkeypatch, owner, data, steps)
    with pytest.raises(ValueError):
        assess(owner, data, baseline_report, steps, replay=replay)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_all_input_bytes": True},
        {"max_input_depth": 0},
        {"max_all_signed_evidence_bytes": float("inf")},
        {"max_all_input_nodes": 8_000_001},
        {"max_unknown_binding_records": 1},
    ],
)
def test_input_limit_configuration_is_lower_only_closed_finite_and_not_boolean(
    owner, baseline_binding_data, baseline_report, baseline_step, monkeypatch, limits
):
    guard_replay(monkeypatch, owner, baseline_binding_data, [baseline_step])
    with pytest.raises(ValueError):
        assess(
            owner,
            baseline_binding_data,
            baseline_report,
            [baseline_step],
            limits=limits,
        )


def geometry_case(tmp_path):
    """Use the frozen seven-helper chain with a second synthetic literal geometry."""
    application_fixture = helper().helper()
    adjudication_fixture = application_fixture.helper()
    typed_fixture = adjudication_fixture.helper()
    source_fixture = typed_fixture.helper()
    alignment_fixture = source_fixture.fixture_helper()
    repeated_document = alignment_fixture.redocument(
        alignment_fixture.document(1),
        (
            '<html><head><meta charset="utf-8"><title>Fixture</title></head><body>'
            '<h3 class="section-head">§1. Heading</h3><!-- field-start:statute -->'
            "<p>雪</p><p>aa</p><p>aa</p><!-- field-end:statute -->"
            '<h4 class="notes-head">Historical and Revision Notes</h4><p>Shared Café.</p>'
            "</body></html>"
        ).encode(),
    )
    original = source_fixture.signed_case(
        source_owner,
        tmp_path,
        parent_texts=[" 雪 aa aa under section 12. ", "aa."],
        docs=[
            repeated_document,
            alignment_fixture.document(2, "aa"),
        ],
    )
    typed = typed_fixture.signed_typed_case(
        response_owner, original, trust_mode="external_pinned_trust"
    )
    typed_report = typed_fixture.assess(response_owner, typed)
    data = adjudication_fixture.signed_case(
        adjudication_owner, typed, typed_report, mode="external_pinned_trust"
    )
    data["adjudication_report"] = adjudication_fixture.assess(adjudication_owner, data)
    data = application_fixture.signed_case(genesis_owner, data)
    data["genesis_report"] = application_fixture.assess(genesis_owner, data)
    step = helper().revision_step(history_owner, data)
    report = helper().assess(history_owner, data, [step])
    return data, step, report


def test_repeated_unicode_literals_keep_existing_distinct_occurrence_coordinates(
    owner, tmp_path
):
    data, step, history = geometry_case(tmp_path)
    records = catalog(data)
    selected = choice(data)
    version = selected["source_version_ref"]["record_cid"]
    occurrences = [
        row
        for row in records.values()
        if row.get("source_version_cid") == version and row.get("span_text") == "aa"
    ]
    assert len(occurrences) >= 2
    first, second = occurrences[:2]
    assert first["span_sha256"] == second["span_sha256"]
    assert first["record_cid"] != second["record_cid"]
    assert (first["start_char"], first["start_utf8"]) != (
        second["start_char"],
        second["start_utf8"],
    )
    assert first["start_char"] != first["start_utf8"]
    bindings = []
    for occurrence in (first, second):
        chosen = choice(data, occurrence_cid=occurrence["record_cid"])
        signed = signed_case(owner, data, history, selected=chosen)
        report = assess(owner, signed, history, [step])
        row = report["records"][0]
        assert row["structured_source_binding_declared_under_selected_profile"] is True
        assert row["binding_declaration_record"]["choice"] == chosen
        bindings.append(
            row["binding_declaration_record"]["choice"]["source_occurrence_ref"]
        )
    assert bindings[0] != bindings[1]


def test_fabricated_selector_with_same_literal_hash_is_not_an_existing_occurrence(
    owner, fixture_data, baseline_report, baseline_step
):
    selected = choice(fixture_data)
    original = catalog(fixture_data)[selected["source_occurrence_ref"]["record_cid"]]
    forged = deepcopy(original)
    for field in ("start_char", "end_char", "start_utf8", "end_utf8"):
        forged[field] += 1
    forged = reseal(forged)
    assert forged["span_sha256"] == original["span_sha256"]
    selected["source_occurrence_ref"] = ref(forged)
    selected["applicability"]["evidence_occurrence_refs"] = [ref(forged)]
    data = signed_case(owner, fixture_data, baseline_report, selected=selected)
    report = assess(owner, data, baseline_report, [baseline_step])
    assert report["records"][0]["binding_content_status"] == "rejected"
    assert (
        report["records"][0][
            "structured_source_binding_declared_under_selected_profile"
        ]
        is False
    )


def test_declared_applicability_scope_is_preserved_separately_from_review_authority_scope(
    owner, fixture_data, baseline_report, baseline_step
):
    selected = choice(fixture_data)
    review_scope = fixture_data["preparation"]["subjects"][0]["scope_id"]
    declared_scope = "fixture:separately-declared-applicability-scope"
    assert declared_scope != review_scope
    selected["applicability"]["scope_id"] = declared_scope
    data = signed_case(owner, fixture_data, baseline_report, selected=selected)
    report = assess(owner, data, baseline_report, [baseline_step])
    group = report["records"][0]
    assert group["structured_source_binding_declared_under_selected_profile"] is True
    body = group["binding_declaration_record"]
    assert body["choice"]["applicability"]["scope_id"] == declared_scope
    assert body["source_review_scope_id"] == review_scope
    assert all(
        claim["subject"]["scope_id"] == review_scope
        for claim in data["binding_groups"][0]["reviews"]
    )
    assert body["applicability_semantics_verified"] is False
    assert_narrow(owner, report)


def test_rejected_other_request_original_actor_in_a_later_epoch_still_blocks_key_reuse(
    owner, fixture_data, baseline_binding_data, baseline_step, baseline_report
):
    later = helper().add_rejected_original_actor(fixture_data, identity="public_key")
    assert (
        later["typed_report"]["records"][1]["raw_source_assessment_record"][
            "assessment"
        ]["authenticated_evidence_count"]
        == 0
    )
    previous = helper().epoch_report(baseline_report, helper().REVISION_ID)
    later_step = helper().revision_step(
        history_owner,
        later,
        epoch_id="fixture:binding-later-original-reviewer:3",
        previous_report=previous,
        generation=3,
    )
    steps = [baseline_step, later_step]
    history = helper().assess(history_owner, fixture_data, steps)
    assert helper().epoch_report(history, helper().REVISION_ID) == previous
    report = assess(owner, clone_case(baseline_binding_data), history, steps)
    assert report["history_records"] == history["records"]
    group = report["records"][0]
    assert (
        "binding_actor_reuses_a_supplied_history_original_reviewer_public_key"
        in group["binding_blockers"]
    )
    assert group["structured_source_binding_declared_under_selected_profile"] is False
    assert group["declared_binding_refs"] == []
    assert_narrow(owner, report)

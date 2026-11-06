"""Legacy source reviews authenticate declarations without selecting source law.

All source text, keys, principals and declarations below are engineering
fixtures.  Even the externally shaped trust case is not a human review.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_join as joins
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust_owner
from ipfs_datasets_py.logic.profile_g import Ed25519Signer


NOW = "2026-10-14T09:00:00Z"
ISSUED = "2026-10-14T08:00:00Z"
EXPIRES = "2026-10-15T08:00:00Z"
START = "2026-10-01T00:00:00Z"
END = "2026-11-01T00:00:00Z"


def wire(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fixture_helper():
    spec = importlib.util.spec_from_file_location(
        "authored_legacy_source_join_for_review_authentication",
        Path(__file__).with_name("test_corpus_legacy_source_join.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_review

    return corpus_legacy_source_review


def dependency_observations(manifest):
    pins = {kind: {} for kind in dependencies.PIN_KINDS}
    for row in manifest["artifacts"]:
        for kind, references in row["dependency_pins"].items():
            pins[kind].update({ref["key"]: ref["sha256"] for ref in references})
    return {
        "observed_artifact_sha256s": {
            row["artifact_id"]: row["artifact_sha256"] for row in manifest["artifacts"]
        },
        "observed_pins": pins,
    }


def signed_case(owner, *, trust_mode="synthetic_fixture"):
    paired_rows, join_inputs = fixture_helper().fixture()
    joined = joins.build_legacy_source_join(paired_rows, **join_inputs)
    assert joined["rows"][0]["disposition"] == "ambiguous_exact_candidates"
    join_bytes = wire(joined)
    arguments = {
        "join_bytes": join_bytes,
        "paired_row_bytes": paired_rows,
        "expected_join_sha256": sha(join_bytes),
        **join_inputs,
    }
    prepared = owner.prepare_legacy_source_review_requests(**arguments)
    subject = prepared["subjects"][0]
    signers = [
        Ed25519Signer.generate("did:example:legacy-source-review-legal"),
        Ed25519Signer.generate("did:example:legacy-source-review-formal"),
    ]
    keys = [
        {
            "key_id": f"fixture:legacy-source-key:{index}",
            "signer_did": signer.did,
            "public_key_hex": signer.public_key.public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            ).hex(),
            "principal_id": f"fixture:legacy-source-principal:{index}",
            "roles": [role],
            "scope_ids": [subject["scope_id"]],
            "valid_from_utc": START,
            "valid_until_utc": END,
            "revoked_at_utc": None,
        }
        for index, (signer, role) in enumerate(zip(signers, trust_owner.ROLES, strict=True))
    ]
    registry = {
        "schema": trust_owner.REGISTRY_SCHEMA,
        "mode": trust_mode,
        "process_id": "fixture:legacy-source-review-process",
        "generation": 1,
        "revocation_generation": 1,
        "valid_from_utc": START,
        "valid_until_utc": END,
        "keys": keys,
        "revoked_principals": [],
    }
    policy = {
        "schema": trust_owner.POLICY_SCHEMA,
        "mode": trust_mode,
        "policy_id": "fixture:legacy-source-review-policy",
        "process_id": registry["process_id"],
        "registry_sha256": sha(wire(registry)),
        "action": owner.ACTION,
        "audience": owner.AUDIENCE,
        "required_roles": list(trust_owner.ROLES),
        "valid_from_utc": START,
        "valid_until_utc": END,
        "max_review_age_seconds": 86400,
    }
    evidence = {
        "fixture:legacy-source-declaration": (
            b"Synthetic engineering declaration; no human source or legal review."
        )
    }
    closure = {
        "status": "declared_complete",
        "unresolved": [],
        "obligations": [
            {
                "slot_id": slot,
                "disposition": "not_applicable",
                "evidence_refs": [
                    {"artifact_id": name, "sha256": sha(raw)}
                    for name, raw in evidence.items()
                ],
            }
            for slot in subject["context_slot_ids"]
        ],
    }
    reviews = [
        signer.sign(
            {
                "schema": owner.CLAIM_SCHEMA,
                "action": owner.ACTION,
                "audience": owner.AUDIENCE,
                "review_id": f"fixture:legacy-source-review:{index}",
                "key_id": keys[index]["key_id"],
                "principal_id": keys[index]["principal_id"],
                "role": role,
                "registry_sha256": sha(wire(registry)),
                "policy_sha256": sha(wire(policy)),
                "issued_at_utc": ISSUED,
                "expires_at_utc": EXPIRES,
                "subject": deepcopy(subject),
                "interpretation": {
                    "decision": "support",
                    "reviewed_graph_sha256": subject["graph_sha256"],
                    "reviewed_ast_sha256": subject["ast_sha256"],
                    "rationale": "Synthetic source declarations only.",
                    "ambiguity": [],
                },
                "context_closure": deepcopy(closure),
            }
        )
        for index, (signer, role) in enumerate(zip(signers, trust_owner.ROLES, strict=True))
    ]
    return {
        "arguments": arguments,
        "joined": joined,
        "preparation": prepared,
        "registry": registry,
        "policy": policy,
        "reviews": reviews,
        "signers": signers,
        "evidence_artifacts": evidence,
        **dependency_observations(prepared["dependency_manifests"][0]),
    }


def refresh_signatures(data):
    data["policy"]["registry_sha256"] = sha(wire(data["registry"]))
    for index, review in enumerate(data["reviews"]):
        body = {
            key: deepcopy(value)
            for key, value in review.items()
            if key not in {"signer_did", "signature_alg", "signature"}
        }
        body["registry_sha256"] = sha(wire(data["registry"]))
        body["policy_sha256"] = sha(wire(data["policy"]))
        data["reviews"][index] = data["signers"][index].sign(body)


def assess(owner, data, **overrides):
    arguments = {
        **data["arguments"],
        "request_ordinal": 0,
        "expected_preparation_manifest_sha256": sha(wire(data["preparation"]["manifest"])),
        "expected_registry_sha256": sha(wire(data["registry"])),
        "expected_policy_sha256": sha(wire(data["policy"])),
        "expected_reviews_sha256": sha(wire(data["reviews"])),
        "at_time_utc": NOW,
        "observed_artifact_sha256s": data["observed_artifact_sha256s"],
        "observed_pins": data["observed_pins"],
        "evidence_artifacts": data["evidence_artifacts"],
        **overrides,
    }
    return owner.assess_legacy_source_review(
        data["preparation"], data["registry"], data["policy"], data["reviews"], **arguments
    )


def assert_no_authority(result):
    assert result["accepted_view_eligible"] is False
    for flag in trust_owner.FALSE_AUTHORITY:
        assert result[flag] is False
    assert result["legal_dependency_inventory_exhaustive"] is False
    assert len(result["deferred_review_slot_ids"]) == 7
    assert "downstream_semantic_validation_required" in result["blockers"]
    assert "downstream_Lean_kernel_admission_required" in result["blockers"]


def test_unavailable_trust_and_empty_reviews_remain_pending(owner):
    data = signed_case(owner)
    data["registry"]["mode"] = data["policy"]["mode"] = "unavailable"
    data["registry"]["keys"] = []
    data["policy"]["registry_sha256"] = sha(wire(data["registry"]))
    data["reviews"] = []
    data["evidence_artifacts"] = {}
    result = assess(owner, data)
    assert result["evidence_assessment_status"] == "pending"
    assert result["authenticated_evidence_count"] == result["review_count"] == 0
    assert "trust_registry_unavailable" in result["blockers"]
    assert result["review_prerequisites_satisfied_under_selected_trust"] is False
    assert_no_authority(result)


@pytest.mark.parametrize("trust_mode", ["synthetic_fixture", "external_pinned_trust"])
def test_signed_fixture_declarations_do_not_select_occurrences_or_establish_semantics(owner, trust_mode):
    data = signed_case(owner, trust_mode=trust_mode)
    before = deepcopy(data["preparation"])
    result = assess(owner, data)
    assert result["schema"] == owner.ASSESSMENT_SCHEMA
    assert result["evidence_assessment_status"] == "authenticated"
    assert result["authenticated_evidence_count"] == 2
    assert all(row["signature_status"] == "valid" for row in result["reviews"])
    assert all(row["signed_context_declaration_complete"] for row in result["reviews"])
    assert result["preparation_manifest_sha256"] == sha(wire(before["manifest"]))
    assert result["request_ordinal"] == 0
    assert result["coverage_scope"] != "exact_selected_graph_reviews_context_slots_and_declared_dependencies_only"
    if trust_mode == "synthetic_fixture":
        assert "production_trust_registry_unavailable" in result["blockers"]
    assert data["preparation"] == before
    assert data["joined"]["rows"][0]["selected_occurrence"] is None
    assert data["joined"]["rows"][0]["original_producer_occurrence_attested"] is False
    assert len(data["joined"]["rows"][0]["candidates"]) == 2
    assert_no_authority(result)


@pytest.mark.parametrize("field", ["action", "audience"])
def test_parent_alignment_review_policy_cannot_authorize_legacy_domain(owner, field):
    from ipfs_datasets_py.logic.autoformal import corpus_source_review as old_owner

    assert owner.ACTION != old_owner.ACTION
    assert owner.AUDIENCE != old_owner.AUDIENCE
    data = signed_case(owner)
    data["policy"][field] = getattr(old_owner, field.upper())
    refresh_signatures(data)
    with pytest.raises(ValueError):
        assess(owner, data)


@pytest.mark.parametrize("old_domain", ["source_review", "graph_review"])
def test_validly_signed_old_domain_claim_is_refused(owner, old_domain):
    from ipfs_datasets_py.logic.autoformal import corpus_source_review

    old_owner = corpus_source_review if old_domain == "source_review" else trust_owner
    data = signed_case(owner)
    for review in data["reviews"]:
        review.update(schema=old_owner.CLAIM_SCHEMA, action=old_owner.ACTION, audience=old_owner.AUDIENCE)
    refresh_signatures(data)
    with pytest.raises(ValueError):
        assess(owner, data)


@pytest.mark.parametrize("damage", ["request", "subject", "source_section", "join_bytes", "paired_bytes"])
def test_tampered_preparation_or_original_inputs_fail_before_authentication(owner, monkeypatch, damage):
    data = signed_case(owner)
    if damage == "request":
        data["preparation"]["requests"][0]["review_scope_id"] = "fixture:changed-source-scope"
    elif damage == "subject":
        data["preparation"]["subjects"][0]["graph_sha256"] = "0" * 64
    elif damage == "source_section":
        data["arguments"]["source_sections"][0]["text"] += " Extra context."
    elif damage == "join_bytes":
        data["arguments"]["join_bytes"] += b" "
    else:
        data["arguments"]["paired_row_bytes"][0] += b" "

    def forbidden_assessment(*args, **kwargs):
        raise AssertionError("The trust engine must not receive unreplayed source preparation.")

    monkeypatch.setattr(trust_owner, "_assess_reviews", forbidden_assessment)
    with pytest.raises(ValueError):
        assess(owner, data)


def test_changed_required_dependency_invalidates_otherwise_authenticated_declarations(owner):
    data = signed_case(owner, trust_mode="external_pinned_trust")
    subject = data["preparation"]["subjects"][0]
    data["observed_artifact_sha256s"][subject["graph_id"]] = "0" * 64
    result = assess(owner, data)
    assert result["authenticated_evidence_count"] == 2
    assert "required_dependency_closure_not_current" in result["blockers"]
    assert result["review_prerequisites_satisfied_under_selected_trust"] is False
    assert_no_authority(result)


def test_changed_evidence_bytes_do_not_invalidate_signatures_but_leave_declarations_incomplete(owner):
    data = signed_case(owner)
    data["evidence_artifacts"]["fixture:legacy-source-declaration"] += b" changed"
    result = assess(owner, data)
    assert result["authenticated_evidence_count"] == 2
    assert all(row["signed_context_declaration_complete"] is False for row in result["reviews"])
    assert all("context_evidence_missing_or_changed" in row["context_blockers"] for row in result["reviews"])
    assert "authenticated_complete_context_declarations_missing" in result["blockers"]
    assert_no_authority(result)


def test_deferred_semantic_obligations_cannot_be_smuggled_into_source_closure(owner):
    data = signed_case(owner)
    deferred = data["preparation"]["subjects"][0]["deferred_review_slot_ids"][0]
    obligation = deepcopy(data["reviews"][0]["context_closure"]["obligations"][0])
    obligation["slot_id"] = deferred
    data["reviews"][0]["context_closure"]["obligations"].append(obligation)
    refresh_signatures(data)
    with pytest.raises(ValueError):
        assess(owner, data)

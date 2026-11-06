"""Bounded candidate-answer history cannot turn branches into current authority.

Every identity, source, declaration, and signature here is an engineering
fixture. History qualification does not establish governing law or semantics.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_application as application
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_adjudication as adjudication
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_responses as responses
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust
from ipfs_datasets_py.logic.profile_g import Ed25519Signer


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def helper():
    spec = importlib.util.spec_from_file_location(
        "authored_legacy_source_application_for_history",
        Path(__file__).with_name("test_corpus_legacy_source_application.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_history

    return corpus_legacy_source_history


GENESIS = "fixture:genesis-epoch"
TIMES = (("2026-10-14T09:08:00Z", "2026-10-14T09:09:00Z", "2026-10-14T09:10:00Z"),
         ("2026-10-14T09:12:00Z", "2026-10-14T09:13:00Z", "2026-10-14T09:14:00Z"),
         ("2026-10-14T09:16:00Z", "2026-10-14T09:17:00Z", "2026-10-14T09:18:00Z"))


def report_ref(report):
    return {"schema": report["schema"], "sha256": sha(wire(report))}


def application_inputs(data):
    return dict(zip(("cohort", "banks", "adjudications", "applications", "descriptor"),
                    helper().assessment_inputs(data), strict=True)) | helper().assessment_arguments(application, data)


def genesis_case(*, failed=False, data=None):
    data = helper().application_case(application) if data is None else data
    if failed:
        row = data["applications"][0]
        row["application_reviews"] = []
        row["assessment_inputs"].update(declaration_artifact_id=None,
                                        expected_declaration_sha256=None, evidence_artifacts={})
        helper().resign(data, 0)
    report = helper().assess(application, data)
    return {"data": data, "genesis_report": report, "genesis_inputs": application_inputs(data),
            "steps": [], "reports": {GENESIS: report}, "signers": {}}


def history_arguments(owner, data, *, current=None, at=None):
    current = current or (data["steps"][-1]["epoch_id"] if data["steps"] else GENESIS)
    at = at or (data["steps"][-1]["inputs"]["at_time_utc"] if data["steps"]
                else data["genesis_inputs"]["at_time_utc"])
    return {"genesis_epoch_id": GENESIS, "current_epoch_id": current, "at_time_utc": at,
            "expected_genesis_assessment_sha256": sha(wire(data["genesis_report"])),
            "expected_revision_step_sha256s": [owner.legacy_source_history_step_sha256(step)
                                               for step in data["steps"]]}


def assess(owner, data, **overrides):
    return owner.assess_legacy_source_history(data["genesis_report"], data["genesis_inputs"], data["steps"],
        **{**history_arguments(owner, data), **overrides})


def resign_revision(owner, data, step):
    for index, row in enumerate(step["inputs"]["revisions"]):
        registry, policy = row["revision_registry"], row["revision_policy"]
        policy["registry_sha256"] = sha(wire(registry))
        for ordinal, claim in enumerate(row["revision_reviews"]):
            body = {key: deepcopy(value) for key, value in claim.items()
                    if key not in {"signer_did", "signature_alg", "signature"}}
            body.update(registry_sha256=sha(wire(registry)), policy_sha256=sha(wire(policy)))
            row["revision_reviews"][ordinal] = data["signers"][step["epoch_id"]][index][ordinal].sign(body)
        row["assessment_inputs"].update(expected_revision_registry_sha256=sha(wire(registry)),
            expected_revision_policy_sha256=sha(wire(policy)),
            expected_revision_reviews_sha256=sha(wire(row["revision_reviews"])))
    step["inputs"]["expected_revision_input_sha256s"] = [owner.legacy_source_revision_input_sha256(row)
                                                       for row in step["inputs"]["revisions"]]


def append_revision(owner, data, *, epoch="fixture:revision-one", parent=GENESIS,
                    time_index=0, source_data=None, declared_override=None):
    source_data = data["data"] if source_data is None else source_data
    prior_report = data["reports"][parent]
    prior_generation = prior_report["descriptor"]["generation"]
    declared, signed, evaluated = TIMES[time_index]
    declared = declared if declared_override is None else declared_override
    original_inputs = application_inputs(source_data)
    inputs = {key: deepcopy(value) for key, value in original_inputs.items()
              if key not in {"applications", "expected_application_input_sha256s", "descriptor", "at_time_utc"}}
    inputs.update(revisions=[], expected_revision_input_sha256s=[], at_time_utc=evaluated,
                  descriptor={"snapshot_id": data["genesis_report"]["descriptor"]["snapshot_id"],
                      "use_scope": "candidate_source_context_answers", "generation": prior_generation + 1,
                      "previous_snapshot_report_ref": report_ref(prior_report)})
    step = {"epoch_id": epoch, "previous_epoch_id": parent, "inputs": inputs}
    entries, signers, bodies = [], [], []
    for bank_id, group in source_data["groups"]:
        for ordinal, member in enumerate(group):
            author_args = {"genesis_epoch_id": GENESIS, "epoch_id": epoch, "previous_epoch_id": parent,
                "bank_id": bank_id, "request_ordinal": ordinal,
                "expected_genesis_assessment_sha256": sha(wire(data["genesis_report"])),
                "expected_revision_step_sha256s": [owner.legacy_source_history_step_sha256(old) for old in data["steps"]],
                "declared_at_utc": declared, "rationale": "Fictional successor answer-reference snapshot.",
                "evidence_refs": helper().source_support(member)}
            body = owner.record_legacy_source_revision_declaration(
                data["genesis_report"], data["genesis_inputs"], data["steps"], inputs, **author_args)
            identity = f"fixture:revision-body:{epoch}:{bank_id}:{ordinal}"
            raw = wire(body)
            seed = source_data["applications"][len(entries)]
            registry, policy = deepcopy(seed["application_registry"]), deepcopy(seed["application_policy"])
            policy.update(policy_id=f"fixture:revision-policy:{epoch}:{ordinal}",
                          action=owner.ACTION, audience=owner.AUDIENCE)
            claims = []
            for index, old in enumerate(member["adjudication"]["reviews"]):
                claim = {key: deepcopy(value) for key, value in old.items()
                         if key not in {"signer_did", "signature_alg", "signature"}}
                claim.update(schema=owner.CLAIM_SCHEMA, action=owner.ACTION, audience=owner.AUDIENCE,
                             review_id=f"fixture:revision-claim:{epoch}:{ordinal}:{index}",
                             issued_at_utc=signed, expires_at_utc=helper().EXPIRES)
                for obligation in claim["context_closure"]["obligations"]:
                    obligation["evidence_refs"] = [{"artifact_id": identity, "sha256": sha(raw)}]
                claims.append(claim)
            seed_inputs = seed["assessment_inputs"]
            entry = {"bank_id": bank_id, "request_ordinal": ordinal, "revision_registry": registry,
                "revision_policy": policy, "revision_reviews": claims,
                "assessment_inputs": {"declaration_artifact_id": identity, "expected_declaration_sha256": sha(raw),
                    "expected_revision_registry_sha256": sha(wire(registry)),
                    "expected_revision_policy_sha256": sha(wire(policy)),
                    "expected_revision_reviews_sha256": sha(wire(claims)),
                    "observed_artifact_sha256s": deepcopy(seed_inputs["observed_artifact_sha256s"]),
                    "observed_pins": deepcopy(seed_inputs["observed_pins"]),
                    "evidence_artifacts": {**member["adjudication"]["evidence_artifacts"], identity: raw}}}
            entries.append(entry)
            signers.append(list(member["adjudication"]["signers"]))
            bodies.append((body, author_args))
    inputs["revisions"] = entries
    data["signers"][epoch] = signers
    resign_revision(owner, data, step)
    data["steps"].append(step)
    report = assess(owner, data)
    data["reports"].update({row["epoch_id"]: row["report"] for row in report["epochs"]})
    return step, bodies


def no_authority(report):
    for flag in trust.FALSE_AUTHORITY:
        assert report[flag] is False
    assert report["selected_occurrence"] is None
    assert report["counts"]["source_decisions_applied"] == 0
    assert report["counts"]["physical_governing_bindings_applied"] == 0


def renamed_source_application(tag):
    """Keep source bytes fixed while replacing all current source reviewers."""
    app_helper = helper()
    cohort_helper = app_helper.helper()
    response_helper = cohort_helper.helper().helper()
    groups = cohort_helper.cohort_case((1,))
    data = groups[0][1][0]
    for index, key in enumerate(data["registry"]["keys"]):
        signer = Ed25519Signer.generate(f"did:example:{tag}:source:{index}")
        data["signers"][index] = signer
        key.update(key_id=f"fixture:{tag}:source-key:{index}",
                   principal_id=f"fixture:{tag}:source-principal:{index}", signer_did=signer.did,
                   public_key_hex=signer.public_key.public_bytes(
                       serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex())
        data["reviews"][index].update(review_id=f"fixture:{tag}:source-review:{index}",
                                      key_id=key["key_id"], principal_id=key["principal_id"])
    declarations = []
    for index, original in enumerate(data["responses"]):
        declaration = deepcopy(original)
        declaration.update({key: data["reviews"][index][key]
                            for key in ("review_id", "principal_id", "role", "issued_at_utc")})
        declarations.append(declaration)
    for index, declaration in enumerate(declarations):
        response_helper.install_record(data, index, response_helper.record(responses, data, declaration))
    data["responses"] = declarations
    data["response_inputs"].update(response_bindings=deepcopy(data["response_bindings"]),
        expected_response_bindings_sha256=sha(wire(data["response_bindings"])))
    cohort_helper.refresh_source_and_declaration(data)
    return app_helper.application_case(application, groups=groups)


def test_linear_successor_preserves_genesis_and_activates_exact_answer_references(owner):
    data = genesis_case()
    original = wire(data["genesis_report"])
    step, bodies = append_revision(owner, data)
    report = assess(owner, data)
    assert report["counts"]["epochs"] == 2 and report["counts"]["revision_epochs"] == 1
    assert report["counts"]["current_eligible_requests"] == 1
    assert report["counts"]["current_answer_references"] == 9
    assert report["forks"] == []
    assert report["current_request_results"][0]["current_use_eligible"] is True
    assert len(report["current_request_results"][0]["active_answer_variant_refs"]) == 9
    assert wire(report["epochs"][0]["report"]) == original
    assert owner.validate_legacy_source_history(report, data["genesis_report"], data["genesis_inputs"],
        data["steps"], **history_arguments(owner, data)) == report
    body, args = bodies[0]
    unsigned = {**step["inputs"], "revisions": [], "expected_revision_input_sha256s": []}
    assert owner.validate_legacy_source_revision_declaration(body, data["genesis_report"],
        data["genesis_inputs"], [], unsigned, **args) == body
    no_authority(report)


def test_failed_predecessor_can_have_a_fresh_qualified_successor(owner):
    data = genesis_case(failed=True)
    assert data["genesis_report"]["counts"]["activated_requests"] == 0
    append_revision(owner, data)
    report = assess(owner, data)
    assert report["epochs"][0]["report"]["counts"]["activated_requests"] == 0
    assert report["counts"]["current_eligible_requests"] == 1
    no_authority(report)


def test_failed_revision_is_retained_when_its_fresh_successor_qualifies(owner):
    data = genesis_case()
    step, _ = append_revision(owner, data)
    entry = step["inputs"]["revisions"][0]
    entry["revision_reviews"] = []
    entry["assessment_inputs"].update(declaration_artifact_id=None, expected_declaration_sha256=None,
                                      evidence_artifacts={})
    resign_revision(owner, data, step)
    failed = assess(owner, data)
    data["reports"].update({row["epoch_id"]: row["report"] for row in failed["epochs"]})
    failed_bytes = wire(data["reports"]["fixture:revision-one"])
    assert failed["counts"]["current_eligible_requests"] == 0
    append_revision(owner, data, epoch="fixture:revision-two", parent="fixture:revision-one", time_index=1)
    report = assess(owner, data)
    assert report["counts"]["current_eligible_requests"] == 1
    assert failed_bytes == wire(next(row["report"] for row in report["epochs"]
                                    if row["epoch_id"] == "fixture:revision-one"))
    no_authority(report)


def test_genesis_alone_is_not_a_current_history_qualification(owner):
    data = genesis_case()
    assert data["genesis_report"]["counts"]["activated_requests"] == 1
    report = assess(owner, data)
    assert report["counts"]["current_eligible_requests"] == report["counts"]["current_answer_references"] == 0
    assert all(row["current_use_eligible"] is False and row["active_answer_variant_refs"] == []
               for row in report["current_request_results"])
    no_authority(report)


@pytest.mark.parametrize("current", ["fixture:revision-one", "fixture:revision-branch"])
def test_equal_answer_forks_block_both_current_branches(owner, current):
    data = genesis_case()
    append_revision(owner, data)
    saved = wire(data["reports"]["fixture:revision-one"])
    append_revision(owner, data, epoch="fixture:revision-branch", time_index=0)
    # Authored siblings share an evaluation instant, permitting either leaf
    # to be selected without relabeling an earlier report's evaluation time.
    at = next(step["inputs"]["at_time_utc"] for step in data["steps"] if step["epoch_id"] == current)
    report = assess(owner, data, current_epoch_id=current, at_time_utc=at)
    assert report["counts"]["visible_fork_points"] == 1
    assert report["counts"]["current_eligible_requests"] == 0
    assert report["current_request_results"][0]["active_answer_variant_refs"] == []
    assert saved == wire(next(row["report"] for row in report["epochs"]
                             if row["epoch_id"] == "fixture:revision-one"))
    no_authority(report)


def test_later_branch_source_inventory_blocks_current_actor_without_rewriting_old_epoch(owner):
    data = genesis_case()
    branch_source = renamed_source_application("branchreviewers")
    future_source_principal = branch_source["groups"][0][1][0]["registry"]["keys"][0]["principal_id"]
    step, _ = append_revision(owner, data)
    entry = step["inputs"]["revisions"][0]
    entry["revision_registry"]["keys"][0]["principal_id"] = future_source_principal
    entry["revision_reviews"][0]["principal_id"] = future_source_principal
    resign_revision(owner, data, step)
    earlier = assess(owner, data)
    assert earlier["counts"]["current_eligible_requests"] == 1
    data["reports"].update({row["epoch_id"]: row["report"] for row in earlier["epochs"]})
    frozen = wire(data["reports"]["fixture:revision-one"])
    append_revision(owner, data, epoch="fixture:source-branch", time_index=0, source_data=branch_source)
    report = assess(owner, data, current_epoch_id="fixture:revision-one", at_time_utc=TIMES[0][2])
    current = report["current_request_results"][0]
    assert current["current_use_eligible"] is False
    assert current["exclusion_matches"]
    assert "current_actor_matches_all_epoch_source_reviewers" in current["blockers"]
    assert frozen == wire(next(row["report"] for row in report["epochs"]
                              if row["epoch_id"] == "fixture:revision-one"))
    no_authority(report)


@pytest.mark.parametrize("damage", ["omitted_step", "duplicated_epoch", "wrong_step_hash", "bool_report_flag"])
def test_complete_graph_and_original_assessment_pins_are_required(owner, damage):
    data = genesis_case()
    append_revision(owner, data)
    kwargs = history_arguments(owner, data)
    if damage == "omitted_step":
        data["steps"].clear()
    elif damage == "duplicated_epoch":
        data["steps"].append(deepcopy(data["steps"][0]))
        kwargs["expected_revision_step_sha256s"].append(kwargs["expected_revision_step_sha256s"][0])
    elif damage == "wrong_step_hash":
        kwargs["expected_revision_step_sha256s"][0] = "0" * 64
    else:
        data["genesis_report"]["admitted"] = 0
        kwargs["expected_genesis_assessment_sha256"] = sha(wire(data["genesis_report"]))
    with pytest.raises(ValueError):
        owner.assess_legacy_source_history(data["genesis_report"], data["genesis_inputs"], data["steps"], **kwargs)


@pytest.mark.parametrize("damage", ["generation_skip", "wrong_parent_ref", "non_leaf_current", "step_order"])
def test_successor_generation_parent_and_order_are_bound(owner, damage):
    data = genesis_case()
    append_revision(owner, data)
    if damage in {"step_order", "non_leaf_current"}:
        append_revision(owner, data, epoch="fixture:revision-two", parent="fixture:revision-one", time_index=1)
    if damage == "generation_skip":
        data["steps"][0]["inputs"]["descriptor"]["generation"] = 3
    elif damage == "wrong_parent_ref":
        data["steps"][0]["inputs"]["descriptor"]["previous_snapshot_report_ref"]["sha256"] = "0" * 64
    elif damage == "step_order":
        data["steps"].reverse()
    overrides = ({"current_epoch_id": "fixture:revision-one"} if damage == "non_leaf_current" else
                 {"current_epoch_id": "fixture:revision-two", "at_time_utc": TIMES[1][2]}
                 if damage == "step_order" else {})
    with pytest.raises(ValueError):
        assess(owner, data, **overrides)


@pytest.mark.parametrize("field", ["schema", "action"])
def test_genesis_application_signing_domain_cannot_authorize_revision(owner, field):
    data = genesis_case()
    step, _ = append_revision(owner, data)
    step["inputs"]["revisions"][0]["revision_reviews"][0][field] = {
        "schema": application.CLAIM_SCHEMA, "action": application.ACTION}[field]
    resign_revision(owner, data, step)
    with pytest.raises(ValueError):
        assess(owner, data)


@pytest.mark.parametrize("damage", ["expired_claim", "absent_current_claims"])
def test_stale_or_absent_current_revision_authority_retains_no_current_answers(owner, damage):
    data = genesis_case()
    step, _ = append_revision(owner, data)
    row = step["inputs"]["revisions"][0]
    if damage == "expired_claim":
        for claim in row["revision_reviews"]:
            claim["expires_at_utc"] = "2026-10-14T09:09:30Z"
    else:
        row["revision_reviews"] = []
        row["assessment_inputs"].update(declaration_artifact_id=None, expected_declaration_sha256=None,
                                        evidence_artifacts={})
    resign_revision(owner, data, step)
    report = assess(owner, data)
    assert report["counts"]["current_eligible_requests"] == report["counts"]["current_answer_references"] == 0
    assert report["current_request_results"][0]["active_answer_variant_refs"] == []
    no_authority(report)


def test_source_migration_cannot_be_hidden_in_a_successor_descriptor(owner):
    data = genesis_case()
    cohort_helper = helper().helper()
    changed_groups = [(data["data"]["groups"][0][0], [cohort_helper.request_case("changed-source")])]
    changed_source = helper().application_case(application, groups=changed_groups)
    assert wire(changed_source["banks"][0]["preparation"]) != wire(data["genesis_inputs"]["banks"][0]["preparation"])
    with pytest.raises(ValueError):
        append_revision(owner, data, source_data=changed_source)


@pytest.mark.parametrize("actor", ["revision", "adjudicator"])
def test_ancestor_source_reviewer_is_excluded_after_current_reviewers_change(owner, actor):
    data = genesis_case()
    changed_source = renamed_source_application("successor")
    old_principal = data["data"]["groups"][0][1][0]["registry"]["keys"][0]["principal_id"]
    assert old_principal not in changed_source["cohort"]["excluded_principal_ids"]
    assert wire(changed_source["banks"][0]["preparation"]) == wire(data["genesis_inputs"]["banks"][0]["preparation"])
    if actor == "adjudicator":
        member = changed_source["groups"][0][1][0]
        member["adjudication"]["registry"]["keys"][0]["principal_id"] = old_principal
        member["adjudication"]["reviews"][0]["principal_id"] = old_principal
        helper().helper().helper().resign(member)
        changed_source = helper().application_case(application, groups=changed_source["groups"])
    step, _ = append_revision(owner, data, source_data=changed_source)
    if actor == "revision":
        row = step["inputs"]["revisions"][0]
        row["revision_registry"]["keys"][0]["principal_id"] = old_principal
        row["revision_reviews"][0]["principal_id"] = old_principal
        resign_revision(owner, data, step)
    report = assess(owner, data)
    assert report["counts"]["current_eligible_requests"] == 0
    assert report["current_request_results"][0]["current_use_eligible"] is False
    assert report["current_request_results"][0]["active_answer_variant_refs"] == []
    assert report["current_request_results"][0]["blockers"]
    no_authority(report)


@pytest.mark.parametrize("bound", ["MAX_HISTORY_REQUESTS", "MAX_EPOCHS", "MAX_HISTORY_INPUT_BYTES"])
def test_unsigned_candidate_is_included_in_whole_history_budget_before_replay(owner, monkeypatch, bound):
    data = genesis_case()
    monkeypatch.setattr(owner, bound, 1)

    def forbidden_replay(*args, **kwargs):
        raise AssertionError("Whole proposed graph must be bounded before predecessor replay.")

    monkeypatch.setattr(owner, "_replay", forbidden_replay)
    with pytest.raises(ValueError):
        append_revision(owner, data)


def test_revision_authoring_rejects_declaration_after_its_evaluation(owner):
    data = genesis_case()
    with pytest.raises(ValueError, match="declaration follows its evaluation"):
        append_revision(owner, data, declared_override="2026-10-14T09:11:00Z")


def test_revision_cannot_evaluate_before_its_new_original_adjudication_cohort(owner):
    data = genesis_case()
    changed = helper().application_case(application)
    member = changed["groups"][0][1][0]
    original = helper().helper().helper().assess(adjudication, member, at_time_utc="2026-10-14T09:20:00Z")
    changed["adjudications"][0]["assessment"] = original
    changed["adjudications"][0]["assessment_inputs"]["at_time_utc"] = "2026-10-14T09:20:00Z"
    changed["cohort_arguments"]["expected_adjudication_assessment_sha256s"][0] = sha(wire(original))
    with pytest.raises(ValueError, match="cohort"):
        append_revision(owner, data, source_data=changed)


def test_history_validator_rejects_false_integer_alias(owner):
    data = genesis_case()
    append_revision(owner, data)
    report = assess(owner, data)
    report["admitted"] = 0
    with pytest.raises(ValueError):
        owner.validate_legacy_source_history(report, data["genesis_report"], data["genesis_inputs"],
                                             data["steps"], **history_arguments(owner, data))

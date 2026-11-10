"""Compile unavailable or invented TRAIN relation masks, never semantic admission.

External pins bind plain declared values, not authentic human review. The only
positive path is explicitly synthetic mask engineering. No vectors, loss,
gradient, verifier, file, model or prover are executed or verified here.
"""
from __future__ import annotations

import json
from collections import Counter

from . import alignment_relation_declarations as relations
from .alignment_lane_bundle import MASKS, _closed, _digest, _raw, _require, _sha, _text

POLICY_SCHEMA = "alignment-relation-mask-policy/v1"
SNAPSHOT_SCHEMA = "alignment-train-relation-verification-snapshot/v1"
SCHEMA = "alignment-train-relation-mask-handoff/v1"
VALIDATION_SCHEMA = "alignment-train-relation-mask-handoff-validation/v1"
UNAVAILABLE = "unavailable_verification/v1"
SYNTHETIC = "synthetic_engineering_only/v1"
SCOPE_RECIPE = "whole_source_and_bound_formal_view/v1"
MAX_BYTES = 16 * 1024 * 1024
MAX_EXPECTED_BYTES = 1024 * 1024
POLICY_FIELDS = {"mode", "pair_order", "scope_recipe", "source_family_id", "target_family_id",
                 "source_semantic_profile_sha256", "target_semantic_profile_sha256", "assumptions_sha256",
                 "separation_required"}
ENDPOINT_FIELDS = {"id", "input_sha256", "formal_view_sha256", "source_fidelity", "formal_fidelity",
                   "source_review_sha256", "formal_review_sha256"}
JOIN_FIELDS = {"left_id", "right_id", "left_input_sha256", "right_input_sha256",
               "left_formal_view_sha256", "right_formal_view_sha256"}
PAIR_FIELDS = JOIN_FIELDS | {"relation", "review_sha256", "adjudication_sha256", "reason"}
FIDELITIES = ("unavailable", "synthetic_complete", "synthetic_incomplete")
RELATIONS = ("unknown", "synthetic_positive", "synthetic_negative")
FALSE = dict.fromkeys(("accepted", "qualified", "source_fidelity_established", "proof_authority",
    "actual_fit_authorized", "semantic_label_admission", "reviewer_identity_authenticated",
    "reviewer_independence_authenticated", "independent_semantic_review_completed", "semantic_gold_created",
    "evidence_contents_verified", "relation_semantics_verified", "family_profile_scope_verified",
    "representation_values_verified", "formal_vectors_verified", "runtime_computation_proven",
    "file_bindings_verified", "split_provenance_authenticated", "training_executed", "model_executed",
    "numerical_worker_executed", "query_reference_accessed", "family_coercion_executed"), False)
COUNTERS = ("human_reviews_authenticated", "independent_reviews_authenticated", "admitted_evidence_count",
            "model_calls", "encoder_calls", "prover_calls", "optimizer_updates")


def _bounded(value, maximum, label):
    _require(len(_raw(value)) <= maximum, label + " byte bound exceeded")


def _seal(value):
    value["content_sha256"] = _digest({key: item for key, item in value.items() if key != "content_sha256"})
    return value


def _detached(value):
    return json.loads(_raw(value))


def _policy(policy):
    _bounded(policy, MAX_BYTES, "mask policy")
    relations.stages._role(policy, POLICY_FIELDS, POLICY_SCHEMA, "relation mask policy")
    _require(type(policy["mode"]) is str and policy["mode"] in (UNAVAILABLE, SYNTHETIC),
             "only unavailable or synthetic mask policy supported")
    _require(policy["pair_order"] == relations.PAIR_ORDER and policy["scope_recipe"] == SCOPE_RECIPE,
             "mask pair order or scope recipe differs")
    _require(policy["separation_required"] is True, "exact true separation requirement required")
    for key in ("source_family_id", "target_family_id"):
        if policy[key] is not None:
            _text(policy[key], key, maximum=512)
    for key in ("source_semantic_profile_sha256", "target_semantic_profile_sha256", "assumptions_sha256"):
        _sha(policy[key], key, nullable=True)
    if policy["mode"] == UNAVAILABLE:
        _require(all(policy[key] is None for key in POLICY_FIELDS if key.endswith("_id") or key.endswith("_sha256")),
                 "unavailable policy cannot declare semantic scope or assumptions")


def _pins(declaration, snapshot, policy, expected):
    _bounded(expected, MAX_EXPECTED_BYTES, "external handoff pins")
    _closed(expected, {"declaration_sha256", "declaration_roles", "snapshot_sha256", "policy_sha256"},
            "external handoff pins")
    for key, value in (("declaration_sha256", declaration), ("snapshot_sha256", snapshot),
                       ("policy_sha256", policy)):
        _sha(expected[key], "selected " + key)
        _require(expected[key] == _digest(value), "selected " + key + " differs")
    return relations.validate_relation_declaration(declaration, expected_bindings=expected["declaration_roles"])


def _scope_reasons(declaration, policy):
    reasons = []
    old = declaration["relation_policy"]
    families = (policy["source_family_id"], policy["target_family_id"])
    profiles = (policy["source_semantic_profile_sha256"], policy["target_semantic_profile_sha256"])
    if None in families:
        reasons.append("family_unknown")
    elif families[0] != families[1]:
        reasons.append("family_mismatch")
    if any(old[key] is None or old[key] != policy[key] for key in ("source_family_id", "target_family_id")):
        reasons.append("declared_family_binding_incomplete_or_different")
    if None in profiles:
        reasons.append("semantic_profile_unknown")
    elif profiles[0] != profiles[1]:
        reasons.append("semantic_profile_mismatch")
    return reasons


def _snapshot(snapshot, declaration, policy):
    _bounded(snapshot, MAX_BYTES, "verification snapshot")
    relations.stages._role(snapshot, {"provenance", "declaration_sha256", "policy_sha256", "endpoint_rows", "pair_rows"},
                           SNAPSHOT_SCHEMA, "verification snapshot")
    provenance = "unavailable" if policy["mode"] == UNAVAILABLE else "synthetic_fixture_not_human_review"
    _require(snapshot["provenance"] == provenance, "snapshot provenance differs from selected policy mode")
    for key, value in (("declaration_sha256", declaration), ("policy_sha256", policy)):
        _sha(snapshot[key], "snapshot " + key)
        _require(snapshot[key] == _digest(value), "snapshot " + key + " differs")
    rows = declaration["train_manifest"]["rows"]
    endpoints, pairs = snapshot["endpoint_rows"], snapshot["pair_rows"]
    n = len(rows)
    _require(type(endpoints) is list and len(endpoints) == n, "all ordered TRAIN endpoints required")
    _require(type(pairs) is list and len(pairs) == n * n, "complete TRAIN row-major snapshot pairs required")
    for row, endpoint in zip(rows, endpoints, strict=True):
        _closed(endpoint, ENDPOINT_FIELDS, "TRAIN snapshot endpoint")
        _require(all(endpoint[key] == row[key] for key in ("id", "input_sha256", "formal_view_sha256")),
                 "snapshot endpoint identity/input/formal binding differs")
        for key in ("source_fidelity", "formal_fidelity"):
            _require(type(endpoint[key]) is str and endpoint[key] in FIDELITIES, "known synthetic fidelity status required")
        for key in ("source_review_sha256", "formal_review_sha256"):
            _sha(endpoint[key], key, nullable=True)
        if policy["mode"] == UNAVAILABLE:
            _require(endpoint["source_fidelity"] == endpoint["formal_fidelity"] == "unavailable"
                     and endpoint["source_review_sha256"] is endpoint["formal_review_sha256"] is None,
                     "unavailable endpoint cannot claim fidelity or review")
    for index, pair in enumerate(pairs):
        _closed(pair, PAIR_FIELDS, "snapshot relation pair")
        for prefix, row in (("left", rows[index // n]), ("right", rows[index % n])):
            _require(all(pair[prefix + "_" + key] == row[key] for key in ("id", "input_sha256", "formal_view_sha256")),
                     "snapshot pair order or endpoint binding differs")
        _require(type(pair["relation"]) is str and pair["relation"] in RELATIONS, "known synthetic relation required")
        for key in ("review_sha256", "adjudication_sha256"):
            _sha(pair[key], key, nullable=True)
        _text(pair["reason"], "snapshot relation reason", maximum=4096)
        if policy["mode"] == UNAVAILABLE:
            _require(pair["relation"] == "unknown" and pair["review_sha256"] is pair["adjudication_sha256"] is None,
                     "unavailable pair cannot claim a relation or review")


def compile_train_relation_masks(declaration, snapshot, policy, *, expected_bindings):
    """Return detached mask preflight; even synthetic readiness authorizes no fit.

    External digests hash complete sealed values. Semantic profiles are separate
    from the representation lane profile. Only source(left) and formal(right)
    declared fixture coverage supports that directed pair; no closure is inferred.
    Source-lane availability is metadata, not formal-vector computation evidence.
    """
    _bounded(declaration, MAX_BYTES, "relation declaration")
    _policy(policy)
    declared = _pins(declaration, snapshot, policy, expected_bindings)
    _snapshot(snapshot, declaration, policy)
    rows, endpoints = declaration["train_manifest"]["rows"], snapshot["endpoint_rows"]
    n = len(rows)
    positive, negative = [[False] * n for _ in rows], [[False] * n for _ in rows]
    scope_reasons = _scope_reasons(declaration, policy)
    diagnostics, excluded = [], Counter()
    for index, pair in enumerate(snapshot["pair_rows"]):
        i, j = divmod(index, n)
        reasons = []
        if policy["mode"] == UNAVAILABLE:
            reasons.append("verification_unavailable")
        if pair["relation"] == "unknown":
            reasons.append("relation_unknown")
        else:
            reasons.extend(scope_reasons)
            for row, reason in ((rows[i], "source_representation_unavailable"),
                                (rows[j], "formal_endpoint_representation_unavailable")):
                if row["status"] != "available":
                    reasons.append(reason)
            for endpoint, side in ((endpoints[i], "source"), (endpoints[j], "formal")):
                if endpoint[side + "_fidelity"] != "synthetic_complete":
                    reasons.append(side + "_fidelity_not_complete")
                if endpoint[side + "_review_sha256"] is None:
                    reasons.append(side + "_review_unbound")
            if pair["review_sha256"] is None:
                reasons.append("relation_review_unbound")
            if pair["adjudication_sha256"] is None:
                reasons.append("adjudication_unbound")
        eligible = not reasons
        positive[i][j] = eligible and pair["relation"] == "synthetic_positive"
        negative[i][j] = eligible and pair["relation"] == "synthetic_negative"
        excluded.update(reasons)
        diagnostics.append({**pair, "objective_positive": positive[i][j], "objective_permitted_negative": negative[i][j],
                            "exclusion_reasons": reasons, "admitted_positive": False, "admitted_permitted_negative": False})
    row_positive = [sum(row) for row in positive]
    col_positive = [sum(row[j] for row in positive) for j in range(n)]
    row_negative = [sum(row) for row in negative]
    col_negative = [sum(row[j] for row in negative) for j in range(n)]
    missing_rows = [rows[i]["id"] for i, count in enumerate(row_positive) if not count]
    missing_cols = [rows[j]["id"] for j, count in enumerate(col_positive) if not count]
    ready = policy["mode"] == SYNTHETIC and not scope_reasons and not missing_rows and not missing_cols and any(row_negative)
    blockers = []
    if policy["mode"] == UNAVAILABLE:
        blockers.append("verification_unavailable")
    if scope_reasons:
        blockers.append("semantic_scope_incomplete_or_incompatible")
    if missing_rows:
        blockers.append("missing_positive_rows")
    if missing_cols:
        blockers.append("missing_positive_columns")
    if not any(row_negative):
        blockers.append("no_negative_separation")
    false_mask = [[False] * n for _ in rows]
    matrices = {"objective_positive_mask": positive, "objective_permitted_negative_mask": negative,
                "admitted_positive_mask": false_mask, "admitted_permitted_negative_mask": false_mask}
    result = {"schema": SCHEMA, "status": "synthetic_mask_preflight_ready" if ready else "mask_preflight_blocked",
        "validation_scope": "externally_pinned_declared_train_associations_and_synthetic_mask_preflight_only",
        "mode": policy["mode"], "snapshot_provenance": snapshot["provenance"],
        "expected_bindings": expected_bindings, "declaration_validation_sha256": _digest(declared),
        "declaration_sha256": expected_bindings["declaration_sha256"],
        "snapshot_sha256": expected_bindings["snapshot_sha256"], "policy_sha256": expected_bindings["policy_sha256"],
        "declaration_role_bindings": expected_bindings["declaration_roles"],
        "representation_profile_sha256": declaration["lane_validation"]["profile_sha256"],
        "declared_semantic_scope": {key: policy[key] for key in ("source_family_id", "target_family_id",
            "source_semantic_profile_sha256", "target_semantic_profile_sha256", "assumptions_sha256")},
        "train_row_count": n, "pair_count": n * n, "pair_order": relations.PAIR_ORDER,
        "endpoint_rows": endpoints, "ordered_endpoint_rows_sha256": _digest(endpoints), "pair_rows": diagnostics,
        "ordered_pair_join_sha256": _digest([{key: pair[key] for key in sorted(JOIN_FIELDS)} for pair in snapshot["pair_rows"]]),
        "declared_relation_counts": dict(Counter(pair["relation"] for pair in snapshot["pair_rows"])),
        "exclusion_reason_counts": dict(sorted(excluded.items())), "scope_exclusion_reasons": scope_reasons,
        "objective_positive_pair_count": sum(row_positive), "objective_permitted_negative_pair_count": sum(row_negative),
        "admitted_positive_pair_count": 0, "admitted_permitted_negative_pair_count": 0,
        **matrices, "matrix_sha256": {name: _digest(matrix) for name, matrix in matrices.items()},
        "row_positive_counts": row_positive, "column_positive_counts": col_positive,
        "row_negative_counts": row_negative, "column_negative_counts": col_negative,
        "missing_positive_row_ids": missing_rows, "missing_positive_column_ids": missing_cols,
        "no_negative_row_ids": [rows[i]["id"] for i, count in enumerate(row_negative) if not count],
        "no_negative_column_ids": [rows[j]["id"] for j, count in enumerate(col_negative) if not count],
        "synthetic_objective_mask_ready": ready, "objective_blockers": blockers,
        "representation_scope": "source_lane_availability_declarations_only_no_formal_vector_or_gradient_validation",
        "verification_status": "unavailable" if policy["mode"] == UNAVAILABLE else "synthetic_only_not_human_verified",
        "admission_status": "pending_external_authoritative_review_process",
        "masks": dict.fromkeys(MASKS, 0), **dict.fromkeys(COUNTERS, 0), **FALSE}
    _seal(result)
    _bounded(result, MAX_BYTES, "relation mask handoff receipt")
    return _detached(result)


def validate_train_relation_mask_handoff(receipt, declaration, snapshot, policy, *, expected_bindings):
    """Replay every field; receipt resealing cannot establish admission."""
    _bounded(receipt, MAX_BYTES, "saved handoff receipt")
    expected = compile_train_relation_masks(declaration, snapshot, policy, expected_bindings=expected_bindings)
    _require(_raw(receipt) == _raw(expected), "saved handoff differs from exact replay")
    return _detached(_seal({"schema": VALIDATION_SCHEMA, "status": "validated_exact_mask_preflight_replay",
        "handoff_sha256": _digest(receipt), "expected_bindings": expected_bindings,
        "train_row_count": expected["train_row_count"], "pair_count": expected["pair_count"],
        "synthetic_objective_mask_ready": expected["synthetic_objective_mask_ready"],
        "masks": dict.fromkeys(MASKS, 0), **dict.fromkeys(COUNTERS, 0), **FALSE}))


def prepare_unavailable_relation_handoff(declaration, *, expected_declaration_bindings):
    """Prepare all TRAIN anchors without inventing scope, reviews or relations."""
    relations.validate_relation_declaration(declaration, expected_bindings=expected_declaration_bindings)
    policy = _seal({"schema": POLICY_SCHEMA, "mode": UNAVAILABLE, "pair_order": relations.PAIR_ORDER,
        "scope_recipe": SCOPE_RECIPE, "source_family_id": None, "target_family_id": None,
        "source_semantic_profile_sha256": None, "target_semantic_profile_sha256": None,
        "assumptions_sha256": None, "separation_required": True})
    rows = declaration["train_manifest"]["rows"]
    snapshot = _seal({"schema": SNAPSHOT_SCHEMA, "provenance": "unavailable", "declaration_sha256": _digest(declaration),
        "policy_sha256": _digest(policy), "endpoint_rows": [{key: row[key] for key in ("id", "input_sha256", "formal_view_sha256")}
            | {"source_fidelity": "unavailable", "formal_fidelity": "unavailable",
               "source_review_sha256": None, "formal_review_sha256": None} for row in rows],
        "pair_rows": [{key: pair[key] for key in JOIN_FIELDS} | {"relation": "unknown", "review_sha256": None,
            "adjudication_sha256": None, "reason": "verification unavailable; no relation inferred"}
            for pair in declaration["pair_ledger"]["rows"]]})
    bindings = {"declaration_sha256": _digest(declaration), "declaration_roles": expected_declaration_bindings,
                "snapshot_sha256": _digest(snapshot), "policy_sha256": _digest(policy)}
    validation = compile_train_relation_masks(declaration, snapshot, policy, expected_bindings=bindings)
    return _detached({"snapshot": snapshot, "policy": policy, "expected_bindings": bindings, "validation": validation})


__all__ = ["compile_train_relation_masks", "validate_train_relation_mask_handoff", "prepare_unavailable_relation_handoff"]


REVIEWED_SCHEMA = "alignment-reviewed-train-relation-mask-handoff/v2"
REVIEWED_MODE = "authenticated_reviewed_pair_purpose/v2"

from pathlib import Path as _ReviewedPath
import hashlib as _reviewed_hashlib
_REVIEWED_IMPORTED_RAW_PINS = {
    str(_ReviewedPath(path).resolve()): _reviewed_hashlib.sha256(_ReviewedPath(path).read_bytes()).hexdigest()
    for path in (__file__, relations.__file__)
}


def _reviewed_imported_pins():
    observed = {path: _reviewed_hashlib.sha256(_ReviewedPath(path).read_bytes()).hexdigest()
                for path in _REVIEWED_IMPORTED_RAW_PINS}
    _require(observed == _REVIEWED_IMPORTED_RAW_PINS,
             "reviewed pair mask self or direct relation source changed since import")
    return dict(_REVIEWED_IMPORTED_RAW_PINS)


def _reviewed_pins():
    from pathlib import Path
    import hashlib
    imported = _reviewed_imported_pins()
    pins = relations._reviewed_pins()
    for path, digest in imported.items():
        _require(path not in pins or pins[path] == digest, "reviewed pair mask imported producer identity differs")
        pins[path] = digest
    _require(_reviewed_imported_pins() == imported, "reviewed pair mask sources changed during pin capture")
    return pins


def _reviewed_process_exclusions(prepared, original_inputs, registry, policy, reviews, current_endpoint_reports):
    """Inventory bounded known custody bytes before accepting independent evidence.

    Hash complete ordinary JSON records and exact bytes/text, plus declared
    producer/content pins. Pair process references themselves are nominations,
    so their hashes/IDs are not treated as known evidence bodies. Original
    endpoint closures and both vector lanes remain entirely ineligible witnesses.
    """
    admission = relations._reviewed_owners()[0]
    ids, hashes = set(), set()
    remaining_nodes, remaining_bytes = 1500000, admission.norm.MAX_INPUT_BYTES

    def known(raw):
        nonlocal remaining_bytes
        remaining_bytes -= len(raw)
        _require(remaining_bytes >= 0, "pair process exclusion byte bound exceeded")
        hashes.add(_reviewed_hashlib.sha256(raw).hexdigest())

    def visit(value, harvest_pins, depth=0):
        nonlocal remaining_nodes
        remaining_nodes -= 1
        _require(remaining_nodes >= 0 and depth <= 96, "pair process exclusion structure bound exceeded")
        if type(value) is bytes:
            known(value)
            return
        try:
            raw = admission.norm._wire(value)
        except (ValueError, TypeError):
            # A compound replay may contain raw bytes; those are visited below.
            if type(value) not in (dict, list):
                raise
            raw = None
        if raw is not None:
            known(raw)
        if type(value) is dict:
            for key, child in value.items():
                if harvest_pins and type(child) is str:
                    if (key.endswith("_id") or key.endswith("_cid") or key == "id"):
                        ids.add(child)
                    if len(child) == 64 and all(letter in "0123456789abcdef" for letter in child):
                        hashes.add(child)
                visit(child, harvest_pins, depth + 1)
        elif type(value) is list:
            for child in value:
                visit(child, harvest_pins, depth + 1)
        elif type(value) is str:
            known(value.encode("utf-8"))
            if harvest_pins and len(value) == 64 and all(letter in "0123456789abcdef" for letter in value):
                hashes.add(value)

    for value in (original_inputs["endpoint_admissions"], original_inputs["source_lane"], original_inputs["formal_lane"],
                  original_inputs["expected_source_lane_bindings"], original_inputs["expected_formal_lane_bindings"],
                  original_inputs["split_manifest"], original_inputs["dependency_manifest"], current_endpoint_reports):
        visit(value, True)
    # These hashes catch aliases of the whole preparation/registry/policy or a
    # signed pair claim without excluding the nominated process-reference pins.
    for value in (prepared, registry, policy, reviews):
        visit(value, False)
    return ids, hashes


def compile_reviewed_train_relation_masks_v2(preparation, registry, policy, reviews, *,
        expected_preparation_sha256, preparation_inputs, expected_registry_sha256,
        expected_policy_sha256, expected_reviews_sha256, at_time_utc,
        observed_artifact_sha256s, observed_pins, evidence_artifacts, current_endpoint_observations):
    """Authenticate a separately reviewed directed ledger and explicit purpose.

    Endpoint training permission never supplies pair labels. Unknown relations
    and analogies are absent from this objective. Vector checks establish
    custody under supplied producer declarations, not runtime computation.
    No fit, model allocation, producer qualification or resource grant occurs.
    """
    _reviewed_imported_pins()
    relations._reviewed_imported_pins()
    import hashlib
    admission, auth, _, _, lanes = relations._reviewed_owners()
    original = dict(preparation=preparation, registry=registry, policy=policy, reviews=reviews,
        expected_preparation_sha256=expected_preparation_sha256, preparation_inputs=preparation_inputs,
        expected_registry_sha256=expected_registry_sha256, expected_policy_sha256=expected_policy_sha256,
        expected_reviews_sha256=expected_reviews_sha256, at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s, observed_pins=observed_pins,
        evidence_artifacts=evidence_artifacts, current_endpoint_observations=current_endpoint_observations)
    copied, commitment = admission.norm._snapshot(original)
    pins = _reviewed_pins()
    checked = relations.validate_reviewed_relation_declaration_v2(copied["preparation"],
        expected_preparation_sha256=expected_preparation_sha256, **copied["preparation_inputs"])
    body, subject = checked["body"], checked["subject"]
    domain = auth._ReviewDomain(relations.REVIEWED_SUBJECT_SCHEMA, relations.REVIEWED_CLAIM_SCHEMA,
        relations.REVIEWED_ACTION, relations.REVIEWED_AUDIENCE,
        "alignment-reviewed-pair-authority-assessment/v2", relations._reviewed_subject, len(relations.REVIEWED_SLOTS))
    authority = auth._assess_reviews(subject, copied["registry"], copied["policy"], copied["reviews"],
        copied["preparation_inputs"]["dependency_manifest"], domain=domain,
        expected_subject_sha256=auth.digest(subject), expected_manifest_sha256=subject["dependency_manifest_sha256"],
        **{key: copied[key] for key in ("expected_registry_sha256", "expected_policy_sha256", "expected_reviews_sha256",
            "at_time_utc", "observed_artifact_sha256s", "observed_pins", "evidence_artifacts")})
    blockers = [] if authority["review_prerequisites_satisfied_under_selected_trust"] else [reason for reason in
        authority["blockers"] if reason not in ("downstream_semantic_validation_required", "downstream_Lean_kernel_admission_required")]
    if auth._time(at_time_utc) < auth._time(checked["endpoint_assessment_time_utc"]):
        blockers.append("pair_evaluation_predates_original_endpoint_snapshot")
    # The original signed snapshots remain exact commitments. Their selected
    # trust roots/reviews are separately replayed at the current pair clock;
    # endpoint manifests never borrow the unrelated pair-manifest observations.
    original_endpoints = copied["preparation_inputs"]["endpoint_admissions"]
    current_observations = copied["current_endpoint_observations"]
    _require(type(current_observations) is dict and set(current_observations) == set(original_endpoints),
             "complete explicit current observations for every original endpoint admission required")
    current_endpoint_digests, current_endpoint_blockers, current_endpoint_reports = {}, {}, {}
    for identity, entry in original_endpoints.items():
        observations = current_observations[identity]
        _closed(observations, {"observed_artifact_sha256s", "observed_pins"}, "current endpoint dependency observations")
        current_inputs = dict(entry["kwargs"], at_time_utc=at_time_utc,
            observed_artifact_sha256s=observations["observed_artifact_sha256s"], observed_pins=observations["observed_pins"])
        current = admission.assess_reviewed_norm_admission_v2(*entry["args"], **current_inputs)
        current_endpoint_reports[identity] = current
        current_endpoint_digests[identity] = admission.norm_content_adjudication_sha256(current)
        current_endpoint_blockers[identity] = list(current["blockers"])
        if current["semantic_use_eligible"] is not True or "training" not in current["permitted_uses"]:
            blockers.append("endpoint_current_training_admission_unavailable:" + identity)
    declared = auth._time(body["declared_at_utc"])
    if declared > auth._time(at_time_utc) or any(auth._time(row["issued_at_utc"]) < declared for row in copied["reviews"]):
        blockers.append("pair_review_or_evaluation_predates_ledger_declaration")
    keys = {row["key_id"]: row for row in copied["registry"]["keys"]}
    authenticated_ids = {row["review_id"] for row in authority["reviews"] if row["status"] == "authenticated"}
    authenticated = [row for row in copied["reviews"] if row["review_id"] in authenticated_ids]
    if not admission._distinct_pair(authenticated, keys):
        blockers.append("distinct_independent_legal_and_formal_pair_review_roles_missing")
    for claim in copied["reviews"]:
        key = keys.get(claim["key_id"])
        if any(claim["principal_id"] == actor["principal_id"] or claim["signer_did"] == actor["signer_did"]
            or key is not None and (key["principal_id"] == actor["principal_id"]
                or key["signer_did"] == actor["signer_did"] or key["public_key_hex"] == actor["public_key_hex"])
            for actor in checked["author_exclusions"]):
            blockers.append("pair_reviewer_reuses_declared_source_IR_or_ledger_author")
    evidence = copied["evidence_artifacts"]
    body_ref = {"artifact_id": body["ledger_id"], "sha256": checked["body_sha256"]}
    if evidence.get(body["ledger_id"]) != admission.norm._wire(body):
        blockers.append("exact_whole_pair_ledger_evidence_missing_or_changed")
    forbidden_ids, forbidden_sha = _reviewed_process_exclusions(checked, copied["preparation_inputs"],
        copied["registry"], copied["policy"], copied["reviews"], current_endpoint_reports)

    def independent(ref):
        raw = evidence.get(ref["artifact_id"])
        return (ref["artifact_id"] not in forbidden_ids and ref["sha256"] not in forbidden_sha
            and type(raw) is bytes and hashlib.sha256(raw).hexdigest() == ref["sha256"])

    for claim in copied["reviews"]:
        for obligation in claim["context_closure"]["obligations"]:
            if obligation["disposition"] != "resolved_by_evidence":
                blockers.append("every_fixed_pair_review_obligation_requires_resolved_by_evidence")
            if body_ref not in obligation["evidence_refs"] or not any(independent(ref) for ref in obligation["evidence_refs"]):
                blockers.append("every_pair_review_obligation_needs_whole_ledger_and_independent_process_evidence")
    for pair in checked["pairs"]:
        if pair["relation"] in ("corresponding", "equivalent", "incompatible"):
            if not pair["evidence_refs"] or not all(independent(ref) for ref in pair["evidence_refs"]):
                blockers.append("reviewed_relationship_independent_process_evidence_missing_or_changed")
    if checked["unavailable_vector_ids"]:
        blockers.append("endpoint_vector_declarations_unavailable")
    verified = not blockers
    source, formal = checked["source_endpoints"], checked["formal_endpoints"]
    n, m = len(source), len(formal)
    positive, negative, diagnostics = [[False] * m for _ in range(n)], [[False] * m for _ in range(n)], []
    for index, pair in enumerate(checked["pairs"]):
        i, j = divmod(index, m)
        positive[i][j] = verified and pair["relation"] in ("corresponding", "equivalent")
        negative[i][j] = verified and pair["relation"] == "incompatible"
        diagnostics.append({**pair, "objective_positive": positive[i][j], "objective_permitted_negative": negative[i][j],
            "disposition": "unknown_excluded" if pair["relation"] == "unknown" else "analogy_retrieval_only"
                if pair["relation"] == "analogy" else "reviewed_objective_label" if verified else "verification_unavailable"})
    row_counts = [sum(row) for row in positive]
    col_counts = [sum(row[j] for row in positive) for j in range(m)]
    missing_rows = [row["id"] for row, count in zip(source, row_counts) if not count]
    missing_columns = [row["id"] for row, count in zip(formal, col_counts) if not count]
    objective_blockers = list(blockers)
    if missing_rows: objective_blockers.append("missing_positive_rows")
    if missing_columns: objective_blockers.append("missing_positive_columns")
    ready = verified and not missing_rows and not missing_columns
    fixture = body["provenance_kind"] == "fictional_fixture"
    report = {"schema": REVIEWED_SCHEMA, "profile": relations.REVIEWED_PROFILE,
        "mode": REVIEWED_MODE if verified else UNAVAILABLE, "status": "reviewed_objective_mask_ready" if ready else "mask_preflight_blocked",
        "preparation_sha256": expected_preparation_sha256, "body_sha256": checked["body_sha256"],
        "ordered_endpoint_sha256": checked["ordered_endpoint_sha256"],
        "source_endpoints": source, "formal_endpoints": formal,
        "representation_dimension": 384, "pair_order": "source_row_major_formal_column/v2",
        "source_representation_profile": checked["source_representation_profile"],
        "formal_representation_profile": checked["formal_representation_profile"],
        "source_profile_sha256": checked["source_profile_sha256"], "formal_profile_sha256": checked["formal_profile_sha256"],
        "source_producer_receipt_sha256": checked["source_producer_receipt_sha256"],
        "formal_producer_receipt_sha256": checked["formal_producer_receipt_sha256"],
        "vector_custody_scope": "exact externally pinned native384 producer declarations; runtime computation unproved",
        "source_vectors": checked["source_vectors"], "formal_vectors": checked["formal_vectors"],
        "source_vector_sha256": checked["source_vector_sha256"], "formal_vector_sha256": checked["formal_vector_sha256"],
        "objective_positive_mask": positive, "objective_permitted_negative_mask": negative,
        "objective_positive_mask_sha256": lanes._digest(positive), "objective_permitted_negative_mask_sha256": lanes._digest(negative),
        "source_row_count": n, "formal_row_count": m, "pair_count": n * m, "pair_rows": diagnostics,
        "unknown_pair_count": sum(pair["relation"] == "unknown" for pair in checked["pairs"]),
        "analogy_retrieval_only_pair_count": sum(pair["relation"] == "analogy" for pair in checked["pairs"]),
        "objective_positive_pair_count": sum(row_counts), "objective_permitted_negative_pair_count": sum(sum(row) for row in negative),
        "row_positive_counts": row_counts, "column_positive_counts": col_counts,
        "missing_positive_row_ids": missing_rows, "missing_positive_column_ids": missing_columns,
        "reviewed_pair_labels_authenticated": verified, "reviewed_objective_mask_ready": ready,
        "objective_blockers": sorted(set(objective_blockers)), "review_authority": authority,
        "original_endpoint_snapshot_time_utc": checked["endpoint_assessment_time_utc"],
        "current_endpoint_assessment_sha256s": current_endpoint_digests,
        "current_endpoint_blockers": current_endpoint_blockers,
        "provenance_kind": body["provenance_kind"], "fixture_only": fixture,
        "production_contrastive_mask": int(ready and not fixture), "training_gold_mask": 0, "evaluation_gold_mask": 0,
        "producer_pins": pins, "runtime_computation_proven": False, "actual_fit_authorized": False,
        "human_identity_and_competence_verified": False, "evaluation_clock_authenticated": False,
        "registry_freshness_authenticated": False, "graph_admitted": False, "Lean_admitted": False,
        "proof_authority": False, "training_executed": False, "model_executed": False}
    report["content_sha256"] = admission.norm_content_adjudication_sha256(report)
    _require(admission.norm._snapshot(original)[1] == commitment and admission.norm._snapshot(copied)[1] == commitment,
             "reviewed pair mask inputs changed during operation")
    _require(_reviewed_pins() == pins, "reviewed pair mask source owners changed during operation")
    return json.loads(admission.norm._wire(report))


def validate_reviewed_train_relation_masks_v2(receipt, *args, expected_receipt_sha256, **kwargs):
    """Recompute whole-ledger authority and all masks; saved flags confer none."""
    _reviewed_imported_pins()
    relations._reviewed_imported_pins()
    admission = relations._reviewed_owners()[0]
    original = {"receipt": receipt, "args": list(args), "kwargs": kwargs}
    copied, commitment = admission.norm._snapshot(original)
    pins = _reviewed_pins()
    _sha(expected_receipt_sha256, "reviewed pair mask receipt")
    _require(admission.norm_content_adjudication_sha256(copied["receipt"]) == expected_receipt_sha256,
             "independent complete reviewed pair mask receipt differs")
    expected = compile_reviewed_train_relation_masks_v2(*copied["args"], **copied["kwargs"])
    _require(admission.norm._same(copied["receipt"], expected), "reviewed pair mask receipt differs from complete replay")
    _require(admission.norm._snapshot(original)[1] == commitment and admission.norm._snapshot(copied)[1] == commitment,
             "reviewed pair mask validation inputs changed during operation")
    _require(_reviewed_pins() == pins, "reviewed pair mask source owners changed during validation")
    return expected


__all__ += ["compile_reviewed_train_relation_masks_v2", "validate_reviewed_train_relation_masks_v2", "REVIEWED_SCHEMA"]

"""Check selected fixture signatures without authenticating human reviews.

Ed25519 binds a selected raw key to exact bytes. Registry roles, offline
revocation snapshots and evaluation time remain declarations. Neither supported
mode establishes identity, independence, semantic fidelity, labels or fit rights.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from . import alignment_relation_mask_handoff as handoffs
from .alignment_lane_bundle import MASKS, _closed, _digest, _raw, _require, _sha, _text

REGISTRY_SCHEMA = "alignment-review-key-registry/v1"
POLICY_SCHEMA = "alignment-review-provenance-policy/v1"
BUNDLE_SCHEMA = "alignment-review-attestation-bundle/v1"
ATTESTATION_SCHEMA = "alignment-review-provenance-attestation/v1"
PAYLOAD_SCHEMA = "alignment-review-provenance-claim/v1"
SCHEMA = "alignment-review-provenance-verification/v1"
VALIDATION_SCHEMA = "alignment-review-provenance-replay/v1"
UNAVAILABLE = "unavailable_verification/v1"
SYNTHETIC = "synthetic_signature_engineering_only/v1"
UNAVAILABLE_REGISTRY = "unavailable_registry/v1"
SYNTHETIC_REGISTRY = "synthetic_fixture_registry/v1"
ACTION = "record_review_provenance/v1"
AUDIENCE = "alignment-train-relation-handoff/v1"
DOMAIN = b"alignment-review-provenance-attestation/v1\x00"
MAX_BYTES = 16 * 1024 * 1024
MAX_SIGNATURES = 1024
MAX_KEYS = 128
SCOPE_FIELDS = {"source_family_id", "target_family_id", "source_semantic_profile_sha256",
                "target_semantic_profile_sha256", "assumptions_sha256"}
ENDPOINT_FIELDS = {"id", "input_sha256", "source_sha256", "context_sha256", "formal_view_sha256"}
KINDS = {"source_review": "reviewer", "formal_review": "reviewer", "relation_review": "reviewer",
         "pair_adjudication": "adjudicator"}
PAYLOAD_FIELDS = {"schema", "attestation_id", "kind", "key_id", "principal_id", "role", "action", "audience",
    "process_id", "registry_sha256", "policy_sha256", "registry_generation", "revocation_generation",
    "declaration_sha256", "handoff_sha256", "issued_at_utc", "expires_at_utc", "subject", "scope", "reference_sha256"}
FALSE = {**handoffs.FALSE, **dict.fromkeys(("human_review_authenticated", "signature_establishes_human_identity",
    "signature_establishes_semantic_fidelity", "registry_selection_authenticated", "process_identity_authenticated",
    "review_contents_verified", "current_revocation_status_verified", "evaluation_clock_authenticated",
    "actual_training_or_evaluation_admission"), False)}
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


def _bounded(value, label):
    _require(len(_raw(value)) <= MAX_BYTES, label + " byte bound exceeded")


def _seal(value):
    value["content_sha256"] = _digest({key: item for key, item in value.items() if key != "content_sha256"})
    return value


def _detach(value):
    return json.loads(_raw(value))


def _time(value, label):
    _require(type(value) is str and _UTC.fullmatch(value), "exact UTC seconds required for " + label)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("valid UTC calendar required for " + label) from error


def _hex(value, size, label):
    _require(type(value) is str and len(value) == size * 2 and all(c in "0123456789abcdef" for c in value),
             "raw lowercase hexadecimal " + label + " required")


def _generation(value, label, nullable=False):
    if nullable and value is None:
        return
    handoffs.relations.stages._int(value, 0, 2147483647, label)


def _scope(value):
    _closed(value, SCOPE_FIELDS, "declared semantic scope")
    for key in SCOPE_FIELDS:
        if key.endswith("_id"):
            if value[key] is not None:
                _text(value[key], key, maximum=512)
        else:
            _sha(value[key], key, nullable=True)


def _registry(registry):
    _bounded(registry, "selected registry")
    handoffs.relations.stages._role(registry, {"mode", "process_id", "generation", "revocation_generation", "keys"},
                                  REGISTRY_SCHEMA, "review key registry")
    _require(registry["mode"] in (UNAVAILABLE_REGISTRY, SYNTHETIC_REGISTRY), "supported fixture registry mode required")
    unavailable = registry["mode"] == UNAVAILABLE_REGISTRY
    for key in ("generation", "revocation_generation"):
        _generation(registry[key], key, nullable=unavailable)
    keys = registry["keys"]
    _require(type(keys) is list and len(keys) <= MAX_KEYS, "bounded registry keys required")
    if unavailable:
        _require(registry["process_id"] is registry["generation"] is registry["revocation_generation"] is None
                 and keys == [], "unavailable registry cannot declare a process, generation or keys")
    else:
        _text(registry["process_id"], "declared fixture process", maximum=512)
    identities, public_keys = set(), set()
    for key in keys:
        _closed(key, {"key_id", "public_key_hex", "principal_id", "role", "action", "audience", "scope",
                      "valid_from_utc", "valid_until_utc", "revoked_at_utc"}, "registry key")
        for field in ("key_id", "principal_id", "action", "audience"):
            _text(key[field], "registry " + field, maximum=512)
        _require(key["key_id"] not in identities, "duplicate registry key ID")
        _hex(key["public_key_hex"], 32, "Ed25519 public key")
        _require(key["public_key_hex"] not in public_keys, "duplicate registry public key")
        identities.add(key["key_id"])
        public_keys.add(key["public_key_hex"])
        _require(key["role"] in ("reviewer", "adjudicator"), "declared reviewer or adjudicator role required")
        _scope(key["scope"])
        start, end = _time(key["valid_from_utc"], "key validity start"), _time(key["valid_until_utc"], "key validity end")
        _require(start < end, "nonempty key validity interval required")
        if key["revoked_at_utc"] is not None:
            _time(key["revoked_at_utc"], "offline declared revocation")


def _policy(policy):
    _bounded(policy, "selected provenance policy")
    handoffs.relations.stages._role(policy, {"mode", "registry_sha256", "registry_generation", "revocation_generation",
        "process_id", "action", "audience", "evaluation_time_utc"}, POLICY_SCHEMA, "provenance policy")
    _require(policy["mode"] in (UNAVAILABLE, SYNTHETIC), "only unavailable or synthetic provenance mode supported")
    _sha(policy["registry_sha256"], "policy registry SHA")
    for key in ("action", "audience"):
        _text(policy[key], "policy " + key, maximum=512)
    if policy["mode"] == UNAVAILABLE:
        _require(policy["process_id"] is policy["registry_generation"] is policy["revocation_generation"]
                 is policy["evaluation_time_utc"] is None, "unavailable policy cannot claim process, time or generations")
    else:
        _text(policy["process_id"], "declared policy process", maximum=512)
        _generation(policy["registry_generation"], "policy registry generation")
        _generation(policy["revocation_generation"], "policy revocation generation")
        _time(policy["evaluation_time_utc"], "selected evaluation time")


def _endpoint(value):
    _closed(value, ENDPOINT_FIELDS, "signed endpoint")
    _text(value["id"], "signed endpoint ID", maximum=512)
    for key in ENDPOINT_FIELDS - {"id"}:
        _sha(value[key], "signed " + key)


def _attestations(bundle):
    _bounded(bundle, "selected attestations")
    handoffs.relations.stages._role(bundle, {"declaration_sha256", "handoff_sha256", "registry_sha256", "policy_sha256", "rows"},
                                  BUNDLE_SCHEMA, "attestation bundle")
    for key in ("declaration_sha256", "handoff_sha256", "registry_sha256", "policy_sha256"):
        _sha(bundle[key], "bundle " + key)
    _require(type(bundle["rows"]) is list and len(bundle["rows"]) <= MAX_SIGNATURES, "bounded detached signatures required")
    identities, associations = set(), set()
    for entry in bundle["rows"]:
        handoffs.relations.stages._role(entry, {"payload", "signature_hex"}, ATTESTATION_SCHEMA, "detached attestation")
        _hex(entry["signature_hex"], 64, "Ed25519 signature")
        body = entry["payload"]
        _closed(body, PAYLOAD_FIELDS, "signed provenance payload")
        _require(body["schema"] == PAYLOAD_SCHEMA and type(body["kind"]) is str and body["kind"] in KINDS,
                 "known signed provenance kind required")
        for key in ("attestation_id", "key_id", "principal_id", "role", "action", "audience", "process_id"):
            _text(body[key], "signed " + key, maximum=512)
        for key in ("registry_sha256", "policy_sha256", "declaration_sha256", "handoff_sha256", "reference_sha256"):
            _sha(body[key], "signed " + key)
        for key in ("registry_generation", "revocation_generation"):
            _generation(body[key], "signed " + key)
        issued, expires = _time(body["issued_at_utc"], "signature issue"), _time(body["expires_at_utc"], "signature expiry")
        _require(issued < expires, "nonempty signed validity interval required")
        _scope(body["scope"])
        _closed(body["subject"], {"left_endpoint", "right_endpoint"}, "signed subject geometry")
        _endpoint(body["subject"]["left_endpoint"])
        if body["kind"] in ("source_review", "formal_review"):
            _require(body["subject"]["right_endpoint"] is None, "singleton review requires null right endpoint")
        else:
            _endpoint(body["subject"]["right_endpoint"])
        identity, association = body["attestation_id"], _association(body)
        _require(identity not in identities and association not in associations, "duplicate attestation ID or association")
        identities.add(identity)
        associations.add(association)


def _association(body):
    subject = body["subject"]
    right = subject["right_endpoint"]
    return body["kind"], subject["left_endpoint"]["id"], None if right is None else right["id"]


def provenance_signing_bytes(payload):
    """Fixed v1 domain plus sorted compact strict UTF8 payload, without a file hash."""
    _bounded(payload, "signing payload")
    return DOMAIN + _raw(payload)


def _verify_signature(key_hex, signature_hex, body):
    try:
        from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except (ImportError, OSError, RuntimeError):
        return "backend_unavailable", False
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_hex)).verify(bytes.fromhex(signature_hex), provenance_signing_bytes(body))
    except InvalidSignature:
        return "invalid", True
    except UnsupportedAlgorithm:
        return "backend_unavailable", False
    except (ValueError, OSError, RuntimeError):
        return "backend_error", False
    return "valid", True


def _parents(declaration, envelope, expected):
    _bounded(declaration, "relation declaration")
    _bounded(envelope, "handoff envelope")
    _closed(envelope, {"snapshot", "policy", "receipt"}, "handoff envelope")
    handoffs.relations.validate_relation_declaration(declaration, expected_bindings=expected["declaration_roles"])
    handoffs.validate_train_relation_mask_handoff(envelope["receipt"], declaration, envelope["snapshot"], envelope["policy"],
                                                expected_bindings=expected["handoff_bindings"])
    _require(expected["declaration_sha256"] == expected["handoff_bindings"]["declaration_sha256"]
             and _raw(expected["declaration_roles"]) == _raw(expected["handoff_bindings"]["declaration_roles"]),
             "selected declaration and handoff pins differ")


def _slots(declaration, envelope):
    rows = declaration["train_manifest"]["rows"]
    endpoints = [{"id": row["id"], "input_sha256": row["input_sha256"], "formal_view_sha256": row["formal_view_sha256"],
        "source_sha256": lane["source_sha256"], "context_sha256": lane["context_sha256"]}
        for row, lane in zip(rows, declaration["lane_validation"]["rows"], strict=True)]
    slots = {}
    for endpoint, original in zip(endpoints, envelope["snapshot"]["endpoint_rows"], strict=True):
        for kind, field in (("source_review", "source_review_sha256"), ("formal_review", "formal_review_sha256")):
            slots[(kind, endpoint["id"], None)] = {"subject": {"left_endpoint": endpoint, "right_endpoint": None},
                                                   "reference_sha256": original[field]}
    n = len(rows)
    for index, original in enumerate(envelope["snapshot"]["pair_rows"]):
        left, right = endpoints[index // n], endpoints[index % n]
        for kind, field in (("relation_review", "review_sha256"), ("pair_adjudication", "adjudication_sha256")):
            slots[(kind, left["id"], right["id"])] = {"subject": {"left_endpoint": left, "right_endpoint": right},
                                                       "reference_sha256": original[field]}
    return endpoints, slots


def verify_train_review_provenance(declaration, handoff_envelope, registry, policy, attestations, *, expected_bindings):
    """Verify fixture-key math and selected declared scope; authorize no human label."""
    _bounded(expected_bindings, "external provenance pins")
    _closed(expected_bindings, {"declaration_sha256", "declaration_roles", "handoff_sha256", "handoff_bindings",
                               "registry_sha256", "policy_sha256", "attestations_sha256"}, "external provenance pins")
    values = {"declaration": declaration, "handoff": handoff_envelope, "registry": registry,
              "policy": policy, "attestations": attestations}
    _require(sum(len(_raw(value)) for value in values.values()) + len(_raw(expected_bindings)) <= MAX_BYTES,
             "aggregate provenance input byte bound exceeded")
    for name, value in values.items():
        _sha(expected_bindings[name + "_sha256"], "selected " + name + " SHA")
        _require(_digest(value) == expected_bindings[name + "_sha256"], "selected " + name + " generation differs")
    _parents(declaration, handoff_envelope, expected_bindings)
    _registry(registry)
    _policy(policy)
    _attestations(attestations)
    unavailable = policy["mode"] == UNAVAILABLE
    _require((registry["mode"] == UNAVAILABLE_REGISTRY) == unavailable, "registry and policy modes differ")
    _require(not unavailable or attestations["rows"] == [], "unavailable process cannot contain attestations")
    common = []
    for name in ("declaration", "handoff", "registry", "policy"):
        if attestations[name + "_sha256"] != _digest(values[name]):
            common.append("bundle_" + name + "_binding_differs")
    for field, selected in (("registry_sha256", _digest(registry)), ("registry_generation", registry["generation"]),
                            ("revocation_generation", registry["revocation_generation"]), ("process_id", registry["process_id"]),
                            ("action", ACTION), ("audience", AUDIENCE)):
        if policy[field] != selected:
            common.append("policy_" + field + "_differs")
    if unavailable:
        common.append("process_registry_unavailable")
    elif handoff_envelope["policy"]["mode"] != handoffs.SYNTHETIC:
        common.append("handoff_not_synthetic")
    scope = handoff_envelope["receipt"]["declared_semantic_scope"]
    endpoints, slots = _slots(declaration, handoff_envelope)
    keys = {key["key_id"]: key for key in registry["keys"]}
    results, by_slot = [], {}
    for entry in attestations["rows"]:
        body = entry["payload"]
        association, reasons = _association(body), list(common)
        slot = slots.get(association)
        if slot is None:
            reasons.append("unknown_train_subject")
        else:
            if _raw(body["subject"]) != _raw(slot["subject"]):
                reasons.append("exact_endpoint_binding_differs")
            if slot["reference_sha256"] is None or body["reference_sha256"] != slot["reference_sha256"]:
                reasons.append("review_reference_binding_differs")
        for field in ("declaration_sha256", "handoff_sha256", "registry_sha256", "policy_sha256"):
            if body[field] != expected_bindings[field]:
                reasons.append("signed_" + field + "_differs")
        for field in ("registry_generation", "revocation_generation", "process_id", "action", "audience"):
            if body[field] != policy[field]:
                reasons.append("signed_" + field + "_differs")
        if _raw(body["scope"]) != _raw(scope):
            reasons.append("signed_semantic_scope_differs")
        evaluation = _time(policy["evaluation_time_utc"], "selected evaluation time")
        issued, expires = _time(body["issued_at_utc"], "issue"), _time(body["expires_at_utc"], "expiry")
        if not issued <= evaluation < expires:
            reasons.append("signed_interval_not_current_at_selected_time")
        key = keys.get(body["key_id"])
        signature_status, executed = "not_attempted_unknown_key", False
        if key is None:
            reasons.append("unknown_selected_registry_key")
        else:
            for field in ("principal_id", "role", "action", "audience"):
                if body[field] != key[field]:
                    reasons.append("registry_declared_" + field + "_differs")
            if key["role"] != KINDS[body["kind"]] or body["role"] != KINDS[body["kind"]]:
                reasons.append("kind_role_mapping_differs")
            if _raw(key["scope"]) != _raw(scope):
                reasons.append("registry_declared_semantic_scope_differs")
            start, end = _time(key["valid_from_utc"], "key start"), _time(key["valid_until_utc"], "key end")
            if not start <= issued <= evaluation < end:
                reasons.append("key_interval_not_current_at_selected_time")
            if key["revoked_at_utc"] is not None and _time(key["revoked_at_utc"], "revocation") <= evaluation:
                reasons.append("key_revoked_in_selected_offline_snapshot")
            signature_status, executed = _verify_signature(key["public_key_hex"], entry["signature_hex"], body)
        if signature_status != "valid":
            reasons.append("signature_" + signature_status)
        result = {"attestation_id": body["attestation_id"], "attestation_sha256": _digest(entry), "kind": body["kind"],
            "subject": body["subject"], "reference_sha256": body["reference_sha256"], "key_id": body["key_id"],
            "declared_principal_id": body["principal_id"], "declared_role": body["role"],
            "signature_status": signature_status, "signature_valid": signature_status == "valid",
            "signature_check_executed": executed, "declared_fixture_scope_permitted": not reasons,
            "status": "valid_fixture_signature_and_declared_scope_only" if not reasons else "denied_fixture_attestation",
            "denial_reasons": reasons, "human_review_authenticated": False, "actual_fit_authorized": False}
        results.append(result)
        by_slot[association] = result
    ledger = [{"kind": kind, **slot, "attestation_id": None if identity not in by_slot else by_slot[identity]["attestation_id"],
               "status": "missing_attestation" if identity not in by_slot else by_slot[identity]["status"],
               "signature_valid": False if identity not in by_slot else by_slot[identity]["signature_valid"],
               "declared_fixture_scope_permitted": False if identity not in by_slot else by_slot[identity]["declared_fixture_scope_permitted"]}
              for identity, slot in slots.items() for kind in (identity[0],)]
    n = len(endpoints)
    masks = {name: [[False] * n for _ in endpoints] for name in ("objective_positive_mask", "objective_permitted_negative_mask",
                                                             "admitted_positive_mask", "admitted_permitted_negative_mask")}
    result = _seal({"schema": SCHEMA, "status": "unavailable_review_process" if unavailable else "synthetic_signature_diagnostics_only",
        "mode": policy["mode"], "expected_bindings": expected_bindings, "train_row_count": n, "pair_count": n * n,
        "endpoint_rows": endpoints, "ordered_endpoint_rows_sha256": _digest(endpoints),
        "endpoint_signature_ledger": ledger[:2 * n], "pair_signature_ledger": ledger[2 * n:],
        "attestation_rows": results, "attestation_count": len(results), "expected_signature_slot_count": len(slots),
        "missing_attestation_slot_count": len(slots) - sum(identity in slots for identity in by_slot),
        "unassociated_attestation_count": sum(identity not in slots for identity in by_slot),
        "signature_checks_executed": sum(row["signature_check_executed"] for row in results),
        "valid_signature_count": sum(row["signature_valid"] for row in results),
        "declared_attesting_principal_ids": sorted({row["declared_principal_id"] for row in results}),
        "declared_attesting_principal_count": len({row["declared_principal_id"] for row in results}),
        "declared_scope_permitted_principal_count": len({row["declared_principal_id"] for row in results
                                                       if row["declared_fixture_scope_permitted"]}),
        "declared_fixture_scope_permitted_count": sum(row["declared_fixture_scope_permitted"] for row in results),
        "denied_attestation_count": sum(not row["declared_fixture_scope_permitted"] for row in results),
        "common_denial_reasons": common, "registry_generation": registry["generation"],
        "revocation_generation": registry["revocation_generation"], "evaluation_time_utc": policy["evaluation_time_utc"],
        "verification_scope": "selected_fixture_key_math_and_offline_declared_scope_only_not_human_or_semantic_verification",
        "review_reference_scope": "separate_evidence_hash_association_only_no_evidence_content_read",
        "replay_scope": "selected_bundle_unique_ids_and_slot_associations_only_no_persistent_replay_ledger",
        "principal_count_scope": "deduplicated_declared_strings_only_not_authenticated_people_or_independent_reviews",
        "verification_status": "unavailable" if unavailable else "synthetic_only_not_human_verified",
        "admission_status": "pending_external_authoritative_review_process", **masks,
        "matrix_sha256": {key: _digest(value) for key, value in masks.items()}, "masks": dict.fromkeys(MASKS, 0),
        **dict.fromkeys(handoffs.COUNTERS, 0), **FALSE})
    _bounded(result, "provenance verification receipt")
    return _detach(result)


def validate_train_review_provenance(receipt, declaration, handoff_envelope, registry, policy, attestations, *, expected_bindings):
    """Replay bindings and signature math; local resealing cannot grant authority."""
    _bounded(receipt, "saved provenance verification")
    expected = verify_train_review_provenance(declaration, handoff_envelope, registry, policy, attestations,
                                            expected_bindings=expected_bindings)
    _require(_raw(receipt) == _raw(expected), "saved provenance receipt differs from exact replay")
    return _detach(_seal({"schema": VALIDATION_SCHEMA, "status": "validated_exact_provenance_replay",
        "verification_sha256": _digest(receipt), "expected_bindings": expected_bindings, "masks": dict.fromkeys(MASKS, 0),
        **dict.fromkeys(handoffs.COUNTERS, 0), **FALSE}))


def prepare_unavailable_review_provenance(declaration, handoff_envelope, *, expected_declaration_bindings, expected_handoff_bindings):
    """Prepare a blocked offline ledger without keys, process, time or reviews."""
    registry = _seal({"schema": REGISTRY_SCHEMA, "mode": UNAVAILABLE_REGISTRY, "process_id": None,
                      "generation": None, "revocation_generation": None, "keys": []})
    policy = _seal({"schema": POLICY_SCHEMA, "mode": UNAVAILABLE, "registry_sha256": _digest(registry),
        "registry_generation": None, "revocation_generation": None, "process_id": None, "action": ACTION,
        "audience": AUDIENCE, "evaluation_time_utc": None})
    attestations = _seal({"schema": BUNDLE_SCHEMA, "declaration_sha256": _digest(declaration),
        "handoff_sha256": _digest(handoff_envelope), "registry_sha256": _digest(registry), "policy_sha256": _digest(policy), "rows": []})
    expected = {"declaration_sha256": _digest(declaration), "declaration_roles": expected_declaration_bindings,
        "handoff_sha256": _digest(handoff_envelope), "handoff_bindings": expected_handoff_bindings,
        "registry_sha256": _digest(registry), "policy_sha256": _digest(policy), "attestations_sha256": _digest(attestations)}
    verification = verify_train_review_provenance(declaration, handoff_envelope, registry, policy, attestations, expected_bindings=expected)
    return _detach({"registry": registry, "policy": policy, "attestations": attestations, "expected_bindings": expected,
                    "verification": verification})


__all__ = ["verify_train_review_provenance", "validate_train_review_provenance", "prepare_unavailable_review_provenance",
           "provenance_signing_bytes"]

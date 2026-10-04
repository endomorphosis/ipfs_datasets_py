"""Strict live validation gates for source-bound native projection training.

Coverage is reviewed across the complete canonical catalog. A family may be
inapplicable to one source only by an explicit, source-bound review; that review
cannot waive a modality's minimum capability floor across the training batch.
Every emitted projection requires a supported native lowering, parser evidence,
and matching live Lake execution. Generic JSON schema builds and saved receipts
are deliberately insufficient. Even a passed gate does not prove source meaning.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path
import weakref

from . import family_training as native
from ...families.canonical_catalog import DEFAULT_CANONICAL_CATALOG_SNAPSHOT

SCHEMA = "native-projection-validation-contract/v8"
POLICY_VERSION = "8.0.0"
MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_BATCH_BYTES = 128 * 1024 * 1024
MAX_BATCH_ROWS = 384
_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_ISSUED = weakref.WeakKeyDictionary()
_BASE_FLOORS = {
    "intent_ir": ("first_order", "deontic", "intention_agency", "program", "temporal", "transition_system"),
    "security_ir": ("program", "temporal", "transition_system"),
    "ui_ux_ir": ("frame_logic", "event_calculus", "tdfol", "dcec", "temporal", "transition_system"),
}
_FALSE = {"admitted": False, "qualified": False, "formalized": False, "roundtrip_ok": False,
          "source_semantics_verified": False, "proof_of_source_meaning": False,
          "training_executed": False, "checkpoint_promoted": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _source_guard():
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_SHA,
             "projection validation policy source changed after import")


def _formula_floor():
    module = importlib.import_module(__package__ + ".native_formula_evidence")
    rows = module.named_logic_routes()
    _require(type(rows) in (list, tuple) and len(rows) == 8,
             "eight explicit native named-logic routes required")
    return rows


def domain_projection_policy(domain_id):
    """Return a fresh closed catalog policy, never a caller-narrowed floor."""
    _source_guard()
    _require(domain_id in native.DOMAINS, "supported explicit domain required")
    families = tuple(DEFAULT_CANONICAL_CATALOG_SNAPSHOT.family_ids)
    if domain_id == "legal_ir":
        floors = _formula_floor()
    else:
        floors = [{"requirement_id": family, "family_id": family, "profile": None}
                  for family in _BASE_FLOORS[domain_id]]
        floors.append({"requirement_id": "TLA+", "family_id": "transition_system", "profile": "tla_plus"})
    seen = set()
    for row in floors:
        _require(type(row) is dict and set(row) == {"requirement_id", "family_id", "profile"}
                 and type(row["requirement_id"]) is str and 0 < len(row["requirement_id"]) <= 128
                 and row["requirement_id"] not in seen and row["family_id"] in families
                 and (row["profile"] is None or type(row["profile"]) is str and 0 < len(row["profile"]) <= 256),
                 "closed canonical family/profile minimum requirement required")
        seen.add(row["requirement_id"])
    result = {"schema": SCHEMA, "policy_version": POLICY_VERSION,
        "policy_id": domain_id + "/native-projections/" + POLICY_VERSION,
        "domain_id": domain_id, "family_inventory": list(families),
        "minimum_batch_floor": floors,
        "catalog_scope": "all_canonical_families_reviewed_not_all_applicable_to_each_source",
        "narrow_request_can_complete": False,
        "inapplicability_can_waive_minimum_batch_floor": False,
        "all_emitted_projections_require_validation": True,
        "required_projection_evidence": ["native_parser", "supported_semantic_lowering", "live_Lake_build"],
        "policy_source_sha256": _SOURCE_SHA, **_FALSE}
    result["policy_sha256"] = _sha(result)
    return json.loads(_raw(result))


def _validate_report(report):
    schema = report.get("schema")
    if schema == native.SCHEMA:
        native.validate_family_training_report(report)
    elif schema == "domain-family-training-targets/v2":
        module = importlib.import_module(__package__ + ".family_training_v2")
        module.validate_family_training_report_v2(report)
    elif schema == "domain-family-training-targets/v3":
        module = importlib.import_module(__package__ + ".family_training_v3")
        module.validate_family_training_report_v3(report)
    elif schema == "domain-family-training-targets/v4":
        module = importlib.import_module(__package__ + ".family_training_v4")
        module.validate_family_training_report_v4(report)
    elif schema == "domain-family-training-targets/v5":
        module = importlib.import_module(__package__ + ".family_training_v5")
        module.validate_family_training_report_v5(report)
    elif schema == "domain-family-training-targets/v6":
        module = importlib.import_module(__package__ + ".family_training_v6")
        module.validate_family_training_report_v6(report)
    elif schema == "domain-family-training-targets/v7":
        module = importlib.import_module(__package__ + ".family_training_v7")
        module.validate_family_training_report_v7(report)
    elif schema == "ui-guarded-family-training-targets/v1":
        module = importlib.import_module(__package__ + ".ui_source_contract_384_v4")
        module.validate_family_training_report(report)
    elif schema == "ui-bounded-event-family-training-targets/v1":
        module = importlib.import_module(__package__ + ".ui_source_contract_384_v5")
        module.validate_family_training_report(report)
    elif schema == "ui-declared-logic-family-targets/v1":
        module = importlib.import_module(__package__ + ".ui_declared_logic_source")
        module.validate_family_training_report(report)
    else:
        raise ValueError("recognized native target report required")


def _verify_execution(execution, report):
    module = importlib.import_module(__package__ + ".native_family_lake_v8")
    return module.verify_native_family_lake(execution, report)


def _reviews(rows, report, known):
    _require(type(rows) in (list, tuple) and len(rows) <= len(known), "bounded explicit family applicability review required")
    result = {}
    for row in rows:
        _require(type(row) is dict and set(row) == {"family_id", "source_digest", "disposition", "reason", "evidence_refs"},
                 "closed source-bound applicability review required")
        family = row["family_id"]
        _require(type(family) is str and family in known and family not in result
                 and row["source_digest"] == report["source_digest"],
                 "unique canonical family review bound to exact source required")
        _require(row["disposition"] in {"applicable", "inapplicable", "needs_evidence", "unsupported"}
                 and type(row["reason"]) is str and 0 < len(row["reason"].strip()) <= 2048,
                 "explicit applicability disposition and substantive reason required")
        references = row["evidence_refs"]
        _require(type(references) is list and 1 <= len(references) <= 16
                 and all(type(item) is str and 0 < len(item.strip()) <= 1024 for item in references),
                 "applicability review evidence references required")
        result[family] = row
    return result


@dataclass(frozen=True, eq=False)
class ProjectionValidationObservation:
    """Immutable local observation; serialized copies cannot reopen the gate."""
    _bytes: bytes

    def to_dict(self):
        return json.loads(self._bytes)

    def native_report(self):
        """Fresh exact input copy; downstream fitting must retain this binding."""
        _require(self in _ISSUED, "issued live projection observation required")
        return json.loads(_ISSUED[self][0])


def validate_projection_report(report, *, lake_execution=None, applicability_review=()):
    """Check one native report and its actual live execution without training.

    Applicability reviews have fields ``family_id``, ``source_digest``,
    ``disposition``, ``reason``, ``evidence_refs``. Absent reviews mean evidence
    is still needed, not that a related family applies to the source. A review
    cannot remove an emitted projection from validation. The full 40-family
    request scope is required for completeness; narrower diagnostic reports
    are retained as incomplete observations. Source review remains a declared
    scope assessment and does not authenticate the source's semantics.
    """
    _source_guard()
    _require(type(report) is dict, "native report mapping required")
    report_bytes = _raw(report)
    _require(len(report_bytes) <= MAX_REPORT_BYTES, "native projection report exceeds byte bound")
    report = json.loads(report_bytes)
    _validate_report(report)
    policy = domain_projection_policy(report["domain_id"])
    known = set(policy["family_inventory"])
    reviews = _reviews(applicability_review, report, known)
    review_bytes = _raw(reviews)
    _require(len(report_bytes) + len(review_bytes) <= MAX_REPORT_BYTES, "projection reviews exceed byte bound")
    requested = set(report["requested_families"])
    full_request = requested == known
    evidence, evidence_error = None, None
    try:
        evidence = _verify_execution(lake_execution, report)
    except (ValueError, TypeError, RuntimeError) as exc:
        evidence_error = {"type": type(exc).__name__, "reason": str(exc)[:2048]}
    live = evidence is not None
    native_rows = report["projections"]
    receipt_rows = evidence.get("per_projection", []) if live else []
    _require(type(receipt_rows) is list and len(receipt_rows) <= 256, "bounded live projection evidence required")
    by_id = {}
    for row in receipt_rows:
        _require(type(row) is dict and type(row.get("projection_id")) is str
                 and row["projection_id"] not in by_id, "unique live projection evidence required")
        by_id[row["projection_id"]] = row
    _require(not set(by_id) - {row["projection_id"] for row in native_rows},
             "live evidence contains an unrelated projection")
    observations = []
    for target in native_rows:
        identity = target["projection_id"]
        row = by_id.get(identity)
        reasons = []
        if target["ready_for_training"] is not True:
            reasons.append("native_target_not_ready")
        if row is None:
            reasons.append("matching_live_Lake_projection_evidence_missing")
        else:
            expected = {"projection_id": identity, "logic_family": target["logic_family"],
                "profile": target.get("profile"), "source_digest": report["source_digest"],
                "payload_sha256": _sha(target["payload"])}
            if any(row.get(key) != value for key, value in expected.items()):
                reasons.append("live_projection_binding_differs")
            if row.get("parser_status") != "passed":
                reasons.append("native_parser_not_passed")
            if row.get("semantic_lowering_supported") is not True:
                reasons.append("semantic_lowering_unsupported_or_partial")
            if row.get("lake_status") != "passed":
                reasons.append("actual_Lake_build_not_passed")
        observations.append({"projection_id": identity, "logic_family": target["logic_family"],
            "profile": target.get("profile"), "source_digest": report["source_digest"],
            "target_sha256": target["target_sha256"], "payload_sha256": _sha(target["payload"]),
            "validated": not reasons, "blocking_reasons": reasons,
            "capability_floor_eligible": bool(row and row.get("lowering") and
                row["lowering"].get("capability_floor_eligible", True) is True)})
    inventory, blockers = [], []
    for family in policy["family_inventory"]:
        emitted = [row for row in observations if row["logic_family"] == family]
        review = reviews.get(family)
        if emitted:
            disposition, reason = "applicable", "native_projections_emitted_for_exact_source"
            if review is not None and review["disposition"] == "inapplicable":
                blockers.append({"family_id": family, "reason": "inapplicability_cannot_waive_existing_projection"})
            elif review is not None and review["disposition"] in {"unsupported", "needs_evidence"}:
                blockers.append({"family_id": family, "reason": "explicit_review_has_unresolved_evidence"})
        elif review is not None:
            disposition, reason = review["disposition"], review["reason"]
        else:
            disposition, reason = "needs_evidence", "no_native_projection_or_source_specific_applicability_review"
        if not emitted and disposition != "inapplicable":
            blockers.append({"family_id": family, "reason": reason})
        inventory.append({"family_id": family, "requested": family in requested,
            "disposition": disposition, "reason": reason,
            "review_evidence_refs": review["evidence_refs"] if review else [],
            "projection_count": len(emitted), "validated_projection_count": sum(row["validated"] for row in emitted)})
    if not full_request:
        blockers.append({"family_id": None, "reason": "narrowed_request_cannot_satisfy_complete_catalog_policy",
                         "missing_requested_families": sorted(known - requested)})
    all_projections = bool(observations) and all(row["validated"] for row in observations)
    result = {"schema": SCHEMA, "policy_id": policy["policy_id"], "policy_sha256": policy["policy_sha256"],
        "domain_id": report["domain_id"], "source_digest": report["source_digest"],
        "native_report_sha256": _sha(report), "full_request_scope": full_request,
        "live_execution_verified": live, "execution_error": evidence_error,
        "projection_observations": observations, "family_inventory": inventory,
        "family_blockers": blockers, "all_emitted_projections_validated": all_projections,
        "source_projection_gate_passed": full_request and live and all_projections and not blockers,
        "modality_batch_floor_checked": False,
        "review_scope": "explicit_source_bound_applicability_declaration_not_semantic_authentication",
        "lake_scope": "supported_formula_interpretation_not_its_truth_or_source_text_equivalence", **_FALSE}
    observation = ProjectionValidationObservation(_raw(result))
    _ISSUED[observation] = (report_bytes, review_bytes, lake_execution, policy["policy_sha256"])
    return observation


def evaluate_projection_training_batch(observations, *, domain_id, target_reports=None):
    """Reverify live evidence and require the fixed modality floor across rows."""
    _source_guard()
    _require(type(observations) in (list, tuple) and 1 <= len(observations) <= MAX_BATCH_ROWS,
             "bounded nonempty live projection observation batch required")
    policy = domain_projection_policy(domain_id)
    if target_reports is not None:
        _require(type(target_reports) in (list, tuple) and len(target_reports) == len(observations),
                 "ordered exact optimization target reports required")
    current, source_ids, consumed = [], set(), 0
    for index, observation in enumerate(observations):
        _require(type(observation) is ProjectionValidationObservation and observation in _ISSUED,
                 "issued live projection observations required; saved JSON is insufficient")
        report_bytes, review_bytes, execution, policy_sha = _ISSUED[observation]
        if target_reports is not None:
            _require(_raw(target_reports[index]) == report_bytes,
                     "optimization targets differ from live validated reports")
        consumed += len(report_bytes) + len(review_bytes)
        _require(consumed <= MAX_BATCH_BYTES, "projection validation batch exceeds byte bound")
        _require(policy_sha == policy["policy_sha256"], "domain or policy drift across validation batch")
        report = json.loads(report_bytes)
        _require(report["domain_id"] == domain_id and report["source_digest"] not in source_ids,
                 "one domain and unique source identities required for batch coverage")
        source_ids.add(report["source_digest"])
        # This calls the native issuer again, so edited artifacts, expired or
        # forged executions cannot rely on an old positive policy observation.
        fresh = validate_projection_report(report, lake_execution=execution,
            applicability_review=list(json.loads(review_bytes).values())).to_dict()
        current.append(fresh)
    valid = [projection for row in current for projection in row["projection_observations"] if projection["validated"] and projection["capability_floor_eligible"]]
    requirements = []
    for requirement in policy["minimum_batch_floor"]:
        matching = [row for row in valid if row["logic_family"] == requirement["family_id"]
                    and (requirement["profile"] is None or row["profile"] == requirement["profile"])
                    and (domain_id != "legal_ir" or row["projection_id"] ==
                         domain_id + "/native_formula/" + requirement["requirement_id"] + "/v3")]
        requirements.append({**requirement, "satisfied": bool(matching),
            "source_digests": sorted({row["source_digest"] for row in matching}),
            "projection_ids": sorted({row["projection_id"] for row in matching})})
    source_gate = all(row["source_projection_gate_passed"] for row in current)
    floor_gate = all(row["satisfied"] for row in requirements)
    result = {"schema": SCHEMA, "domain_id": domain_id, "policy": policy,
        "source_count": len(current), "source_observations": current,
        "required_floor": requirements, "all_source_projection_gates_passed": source_gate,
        "modality_floor_satisfied": floor_gate, "strict_training_allowed": source_gate and floor_gate,
        "optimization_input_binding_checked": target_reports is not None,
        "scope": "live_native_projection_validation_only_not_source_semantics_or_model_fidelity", **_FALSE}
    result["report_sha256"] = _sha(result)
    return result


class ProjectionValidationError(ValueError):
    def __init__(self, report):
        self._report_bytes = _raw(report)
        super().__init__("strict native projection training gate failed; missing/unsupported projections or modality floor")

    def to_dict(self):
        return json.loads(self._report_bytes)


def require_projection_training_batch(observations, *, domain_id, target_reports=None):
    """Fail before optimization; the exception retains the full failed audit."""
    report = evaluate_projection_training_batch(observations, domain_id=domain_id, target_reports=target_reports)
    if not report["strict_training_allowed"]:
        raise ProjectionValidationError(report)
    return report


__all__ = ["SCHEMA", "domain_projection_policy", "ProjectionValidationObservation",
    "validate_projection_report", "evaluate_projection_training_batch",
    "require_projection_training_batch", "ProjectionValidationError"]

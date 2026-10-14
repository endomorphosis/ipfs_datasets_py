"""Artifact-bound qualification declarations and conservative corpus views.

This module validates declared statuses and evidence references. It neither
resolves those references nor authenticates a reviewer, an execution, source
meaning or a proof. Every derived view is explicitly *declared-evidence-only*;
it is not admission. A consumer requiring authority must independently resolve
and verify the exact evidence under its own policy.
"""
from __future__ import annotations

from .corpus_contracts import (
    CorpusContractError,
    clone_json,
    require_cid,
    require_keys,
    require_text,
    seal_record,
    validate_record,
)

SCHEMA = "legal-corpus-qualification/v1"
ELIGIBILITY_SCHEMA = "legal-corpus-declared-eligibility/v1"
LEGACY_SCHEMA = "legal-corpus-legacy-qualification-adapter/v1"
DECLARATION_SCOPE = "declared_evidence_only_not_admission"

STATUS_VALUES = {
    "processing": ("pending", "complete", "gap", "failed"),
    "source_integrity": ("unassessed", "verified", "failed"),
    "interpretation": ("candidate", "reviewed", "disputed", "partial", "unsupported"),
    "representation": ("unassessed", "supported_complete", "supported_partial", "unsupported"),
    "dependency": ("unassessed", "resolved", "unresolved", "ambiguous"),
    "native_translation": ("not_run", "passed", "failed", "unsupported"),
    "lean_compilation": ("not_run", "passed", "failed"),
    "proof": ("not_requested", "pending", "discharged", "failed", "unsupported"),
}
DEFAULT_STATUSES = {
    "processing": "pending", "source_integrity": "unassessed",
    "interpretation": "candidate", "representation": "unassessed",
    "dependency": "unassessed", "native_translation": "not_run",
    "lean_compilation": "not_run", "proof": "not_requested",
}
EVIDENCE_REQUIRED = {
    "processing": ("complete",),
    "source_integrity": ("verified",),
    "interpretation": ("reviewed",),
    "representation": ("supported_complete", "supported_partial"),
    "dependency": ("resolved",),
    "native_translation": ("passed",),
    "lean_compilation": ("passed",),
    "proof": ("discharged",),
}
MAX_EVIDENCE_PER_DIMENSION = 256
AUTHORITY_FIELDS = (
    "admitted", "formalized", "proof_authority", "source_semantics_verified",
    "evidence_authenticated", "reviewer_authenticated",
)
_FIELDS = {
    "artifact_cid", "profile", "dimensions", "theorem_requested",
    "declaration_scope", *AUTHORITY_FIELDS,
}


def _require(condition, message):
    if not condition:
        raise CorpusContractError(message)


def _authority_flags():
    return dict.fromkeys(AUTHORITY_FIELDS, False)


def _binding(artifact_cid, profile):
    require_cid(artifact_cid, "artifact_cid")
    require_text(profile, "profile", max_bytes=512)


def _dimensions(value, theorem_requested):
    require_keys(value, set(STATUS_VALUES), "qualification dimensions")
    for name, choices in STATUS_VALUES.items():
        item = value[name]
        require_keys(item, {"status", "evidence_cids"}, name + " dimension")
        _require(type(item["status"]) is str and item["status"] in choices,
                 "unknown " + name + " status")
        refs = item["evidence_cids"]
        _require(type(refs) is list and len(refs) <= MAX_EVIDENCE_PER_DIMENSION,
                 "bounded " + name + " evidence_cids list required")
        for ref in refs:
            require_cid(ref, name + " evidence CID")
        _require(len(set(refs)) == len(refs), "duplicate " + name + " evidence reference")
        _require(item["status"] not in EVIDENCE_REQUIRED[name] or bool(refs),
                 name + " affirmative status requires an evidence CID")
    proof = value["proof"]["status"]
    _require((not theorem_requested and proof == "not_requested")
             or (theorem_requested and proof != "not_requested"),
             "proof status contradicts theorem_requested")
    _require(proof != "not_requested" or not value["proof"]["evidence_cids"],
             "not_requested proof cannot carry proof evidence")
    _require(proof != "discharged" or value["lean_compilation"]["status"] == "passed",
             "discharged Lean theorem requires passed compilation for this artifact/profile")


def _validate_body(value):
    _binding(value["artifact_cid"], value["profile"])
    _require(type(value["theorem_requested"]) is bool, "theorem_requested must be boolean")
    _require(value["declaration_scope"] == DECLARATION_SCOPE,
             "qualification declaration scope changed")
    for key in AUTHORITY_FIELDS:
        _require(type(value[key]) is bool and value[key] is False,
                 "qualification declaration cannot grant " + key)
    _dimensions(value["dimensions"], value["theorem_requested"])


def prepare_qualification(*, artifact_cid, profile, dimensions=None, theorem_requested=False):
    """Seal complete orthogonal status declarations for exactly one artifact.

    ``dimensions`` may specify a subset; unspecified dimensions remain unknown
    or pending. Positive statuses require evidence CIDs, not invented receipts.
    The references are declarations and are not authenticated here.
    """
    _binding(artifact_cid, profile)
    _require(type(theorem_requested) is bool, "theorem_requested must be boolean")
    supplied = {} if dimensions is None else clone_json(dimensions)
    _require(type(supplied) is dict and not set(supplied) - set(STATUS_VALUES),
             "unknown qualification dimension")
    result = {name: {"status": status, "evidence_cids": []}
              for name, status in DEFAULT_STATUSES.items()}
    if theorem_requested:
        result["proof"]["status"] = "pending"
    result.update(supplied)
    body = {"schema": SCHEMA, "artifact_cid": artifact_cid, "profile": profile,
            "dimensions": result, "theorem_requested": theorem_requested,
            "declaration_scope": DECLARATION_SCOPE, **_authority_flags()}
    _validate_body(body)
    return seal_record(body)


def validate_qualification(record, *, artifact_cid, profile):
    """Validate the seal, schema and exact externally supplied artifact/profile.

    Validation returns a detached record. It verifies content integrity only;
    evidence references and their asserted meaning remain unauthenticated.
    """
    _binding(artifact_cid, profile)
    value = validate_record(record, schema=SCHEMA, fields=_FIELDS)
    _validate_body(value)
    _require(value["artifact_cid"] == artifact_cid and value["profile"] == profile,
             "qualification belongs to another artifact or profile")
    return value


def derive_eligibility(record, *, artifact_cid, profile):
    """Derive declared candidate/reviewed/checked views; never grant admission.

    Candidate graphs may retain partial/disputed interpretations and unresolved
    dependencies. Reviewed graphs require complete reviewed interpretations and
    closure. Checked Lean additionally requires passed translation/compilation
    and discharge of a requested theorem. A successful build of an unreviewed
    candidate remains recorded, without becoming a reviewed checked artifact.
    """
    value = validate_qualification(record, artifact_cid=artifact_cid, profile=profile)
    statuses = {name: item["status"] for name, item in value["dimensions"].items()}
    base = {
        "processing": ("complete",), "source_integrity": ("verified",),
        "representation": ("supported_complete", "supported_partial"),
        "interpretation": ("candidate", "reviewed", "partial", "disputed"),
    }
    reviewed = {**base, "interpretation": ("reviewed",),
                "representation": ("supported_complete",), "dependency": ("resolved",)}
    checked = {**reviewed, "native_translation": ("passed",), "lean_compilation": ("passed",)}
    if value["theorem_requested"]:
        checked["proof"] = ("discharged",)
    views = {}
    for name, requirements in (("candidate_graph", base), ("reviewed_graph", reviewed),
                               ("checked_lean", checked)):
        blockers = [{"dimension": dimension, "observed_status": statuses[dimension],
                     "required_statuses": list(allowed)}
                    for dimension, allowed in requirements.items() if statuses[dimension] not in allowed]
        views[name] = {"declared_eligible": not blockers, "blockers": blockers}
    return seal_record({"schema": ELIGIBILITY_SCHEMA, "artifact_cid": artifact_cid, "profile": profile,
                        "qualification_cid": value["record_cid"], "views": views,
                        "declaration_scope": DECLARATION_SCOPE,
                        "authority_policy_required": True, **_authority_flags()})


def validate_eligibility(report, record, *, artifact_cid, profile):
    """Recompute a declared view; a self-consistent seal cannot invent eligibility."""
    value = validate_record(report, schema=ELIGIBILITY_SCHEMA, fields={
        "artifact_cid", "profile", "qualification_cid", "views", "declaration_scope",
        "authority_policy_required", *AUTHORITY_FIELDS,
    })
    expected = derive_eligibility(record, artifact_cid=artifact_cid, profile=profile)
    _require(value == expected, "declared eligibility differs from exact qualification derivation")
    return value


def adapt_legacy_qualification(legacy, *, artifact_cid, profile):
    """Preserve legacy flags descriptively; derive no review/build/proof credit.

    Only processing state is translated. A sealed/complete legacy observation
    cites the sealed adapter observation as its processing evidence. Legacy
    admitted/formalized booleans cannot establish any other positive dimension.
    """
    _binding(artifact_cid, profile)
    supplied = clone_json(legacy)
    _require(type(supplied) is dict, "legacy qualification must be an object")
    for key, expected in (("artifact_cid", artifact_cid), ("profile", profile)):
        if key in supplied:
            _require(supplied[key] == expected, "legacy qualification belongs to another " + key)
    observed = {key: supplied[key] for key in ("sealed", "gap", "admitted", "formalized", "status")
                if key in supplied}
    for key in ("sealed", "gap", "admitted", "formalized"):
        if key in observed:
            _require(type(observed[key]) is bool, "legacy " + key + " must be boolean")
    status = observed.get("status")
    _require("status" not in observed or type(status) is str and status in {
        "pending", "claimed", "unsealed", "sealed", "complete", "gap", "failed", "prepared"},
        "unknown legacy processing status")
    _require(not (observed.get("sealed") is True and observed.get("gap") is True),
             "legacy sealed and gap statuses conflict")
    if status in {"sealed", "complete"}:
        _require(observed.get("sealed") is not False and observed.get("gap") is not True,
                 "legacy processing flags contradict complete status")
    elif status is not None:
        _require(observed.get("sealed") is not True, "legacy sealed flag contradicts processing status")
    if observed.get("gap") is True:
        _require(status in (None, "gap"), "legacy gap flag contradicts processing status")
    if status == "gap":
        _require(observed.get("gap") is not False, "legacy gap flag contradicts processing status")
    processing = ("complete" if observed.get("sealed") is True or status in {"sealed", "complete"}
                  else "gap" if observed.get("gap") is True or status == "gap"
                  else "failed" if status == "failed" else "pending")
    observation = seal_record({"schema": "legal-corpus-legacy-processing-observation/v1",
                               "artifact_cid": artifact_cid, "profile": profile,
                               "legacy_fields": observed, "declaration_scope": DECLARATION_SCOPE,
                               **_authority_flags()})
    qualification = prepare_qualification(artifact_cid=artifact_cid, profile=profile,
        dimensions={"processing": {"status": processing,
                    "evidence_cids": [observation["record_cid"]] if processing == "complete" else []}})
    return seal_record({"schema": LEGACY_SCHEMA, "artifact_cid": artifact_cid, "profile": profile,
                        "legacy_observation": observation, "qualification": qualification,
                        "legacy_flags_grant_authority": False,
                        "declaration_scope": DECLARATION_SCOPE, **_authority_flags()})

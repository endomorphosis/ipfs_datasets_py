"""Authenticate scoped graph review evidence without admitting legal meaning.

The caller independently pins the selected trust registry, policy, complete
review population and subject inputs. Profile G's existing detached Ed25519
signature mechanism authenticates bytes under those selected keys. It does not
establish a human's identity, competence, independence or the truth of a review.
No trusted production keys, signer, clock, filesystem or network fallback is
provided here. Synthetic fixtures can exercise verification but cannot qualify
an accepted view. All semantic, corpus and Lean admission remains downstream.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from . import legal_graph_dependencies as dependencies
from . import legal_semantic_graph as graphs
from . import legal_statutory_context as contexts

SCHEMA = "legal-graph-review-assessment/v1"
SUBJECT_SCHEMA = "legal-graph-review-subject/v1"
REGISTRY_SCHEMA = "legal-graph-review-key-registry/v1"
POLICY_SCHEMA = "legal-graph-review-trust-policy/v1"
CLAIM_SCHEMA = "legal-graph-review-signed-claim/v1"
ACTION = "record_graph_review_evidence/v1"
AUDIENCE = "legal-autoformalization-graph-review/v1"
MODES = ("external_pinned_trust", "synthetic_fixture", "unavailable")
ROLES = ("legal_review", "formal_review")
MAX_BYTES = 8 * 1024 * 1024
MAX_REVIEWS = 32
MAX_KEYS = 64
MAX_EVIDENCE = 256
MAX_TEXT = 8192
FALSE_AUTHORITY = dict.fromkeys(("admitted", "formalized", "source_semantics_verified",
    "context_closure_verified", "global_consistency_verified", "proof_authority", "training_qualified",
    "signature_establishes_legal_truth", "human_identity_verified", "human_independence_verified"), False)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_ID = re.compile(r"[a-z0-9][a-z0-9_.:@/-]{0,255}\Z")
_DID = re.compile(r"did:[a-z0-9]+:[A-Za-z0-9._:%-]{1,256}\Z")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def wire(value):
    """Bound plain JSON before encoding; reject aliases such as bool-for-int."""
    count = 0
    def visit(item, depth):
        nonlocal count
        count += 1
        require(depth <= 40 and count <= 262144, "review JSON depth/node bound exceeded")
        if type(item) is dict:
            require(all(type(k) is str for k in item), "review JSON string keys required")
            for child in item.values(): visit(child, depth + 1)
        elif type(item) is list:
            for child in item: visit(child, depth + 1)
        else:
            require(item is None or type(item) in (str, int, bool), "plain integer review JSON required")
            if type(item) is int: require(abs(item) <= 9007199254740991, "review safe integer required")
    visit(value, 0)
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (UnicodeError, TypeError, ValueError, RecursionError) as error:
        raise ValueError("bounded UTF8 review JSON required") from error
    require(len(raw) <= MAX_BYTES, "review byte bound exceeded")
    return raw


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def _closed(value, fields, label):
    require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _text(value, label):
    require(type(value) is str and 0 < len(value) <= MAX_TEXT and value.strip() and "\x00" not in value,
            "bounded " + label + " required")


def _id(value, label):
    require(type(value) is str and _ID.fullmatch(value), "canonical " + label + " required")


def _sha(value):
    require(type(value) is str and _SHA.fullmatch(value), "exact review SHA256 required")


def _time(value):
    require(type(value) is str and _UTC.fullmatch(value), "explicit UTC seconds required")
    try: return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error: raise ValueError("valid UTC calendar required") from error


def _interval(value, start="valid_from_utc", end="valid_until_utc"):
    left, right = _time(value[start]), _time(value[end])
    require(left < right, "nonempty validity interval required")
    return left, right


def _closure(manifest, graph_id, graph_sha256):
    by_id = {row["artifact_id"]: row for row in manifest["artifacts"]}
    require(graph_id in by_id and by_id[graph_id]["artifact_sha256"] == graph_sha256,
            "dependency manifest graph binding differs")
    adjacency = {key: [] for key in by_id}
    for edge in manifest["edges"]: adjacency[edge["dependent_id"]].append(edge["dependency_id"])
    reachable, seen = [graph_id], {graph_id}
    for parent in reachable:
        for child in adjacency.get(parent, []):
            if child not in seen: seen.add(child); reachable.append(child)
    return reachable, [{"artifact_id": key, "artifact_sha256": by_id[key]["artifact_sha256"] if key in by_id else None}
                       for key in reachable]


def _check_declared_dependencies(refs, reachable, artifacts):
    require(type(refs) is list and len(refs) <= 4096, "bounded graph-declared dependencies required")
    bindings = {row["artifact_id"]: row["artifact_sha256"] for row in artifacts}
    seen = set()
    for row in refs:
        _closed(row, {"origin", "reference"}, "graph-declared dependency")
        _text(row["origin"], "graph dependency origin")
        require(row["origin"] not in seen, "duplicate graph dependency origin")
        seen.add(row["origin"])
        ref = graphs._refs([row["reference"]])[0]
        require(ref["artifact_id"] in reachable and bindings.get(ref["artifact_id"]) == ref["artifact_sha256"],
                "graph-declared dependency omitted, unreachable or differently pinned in manifest")


def build_review_subject(graph, context_packet, dependency_manifest, *, expected_graph_sha256,
        expected_context_sha256, expected_manifest_sha256, document, raw_html,
        required_dependency_ids, context_dependency_requests=None):
    """Replay exact source/context custody and the entire declared dependency closure.

    Required IDs are an independently retained, ordered forward-reachable
    inventory starting with this graph. Missing targets are retained. This is
    completeness of the supplied graph, never exhaustive legal dependencies.
    """
    for value in (expected_graph_sha256, expected_context_sha256, expected_manifest_sha256): _sha(value)
    require(digest(graph) == expected_graph_sha256 and digest(context_packet) == expected_context_sha256,
            "independently pinned graph or context differs")
    ast = graphs.graph_to_ast(graph)
    require(type(raw_html) is bytes and len(raw_html) <= MAX_BYTES, "bounded exact rawHTML bytes required")
    source = graphs.bind_source_occurrence(document, raw_html, selector=graph["source"]["selector"],
                                          document_revision=graph["source"]["document_revision"])
    require(wire(source) == wire(graph["source"]), "graph source differs from original document")
    contexts.validate_context_packet(context_packet, document, raw_html,
        expected_selector=source["selector"], dependency_requests=context_dependency_requests)
    manifest = dependencies.validate_dependency_manifest(dependency_manifest,
        expected_manifest_sha256=expected_manifest_sha256)
    reachable, artifacts = _closure(manifest, graph["graph_id"], expected_graph_sha256)
    declared_refs = [{"origin": "/dependency_refs/" + str(i), "reference": deepcopy(ref)}
                     for i, ref in enumerate(graph["dependency_refs"])]
    for index, assertion in enumerate(graph["assertions"]):
        declared_refs.extend({"origin": "/assertions/" + str(index) + "/declaration/dependency_refs/" + str(i),
                              "reference": deepcopy(ref)}
                             for i, ref in enumerate(assertion["declaration"]["dependency_refs"]))
    _check_declared_dependencies(declared_refs, reachable, artifacts)
    require(type(required_dependency_ids) is list and wire(required_dependency_ids) == wire(reachable),
            "independent required dependency population differs")
    body = {"schema": SUBJECT_SCHEMA, "graph_id": graph["graph_id"], "graph_sha256": expected_graph_sha256,
        "ast_sha256": digest(ast), "source_binding_sha256": source["source_binding_sha256"],
        "source_occurrence_id": source["selector"]["occurrence_id"], "source_text_sha256": source["selector"]["text_sha256"],
        "document_id": source["document_id"], "document_revision": source["document_revision"],
        "scope_id": graph["scope"]["scope_id"], "context_packet_sha256": expected_context_sha256,
        "context_packet_id": context_packet["packet_id"],
        "context_slot_ids": [row["slot_id"] for row in context_packet["dependency_slots"]],
        "dependency_manifest_sha256": expected_manifest_sha256, "required_dependency_ids": reachable,
        "dependency_artifacts": artifacts, "graph_declared_dependency_refs": declared_refs}
    return json.loads(wire(body))


def _trust(registry, policy, expected_registry_sha256, expected_policy_sha256, *, action=ACTION, audience=AUDIENCE):
    for selected, expected in ((registry, expected_registry_sha256), (policy, expected_policy_sha256)):
        _sha(expected); require(digest(selected) == expected, "independently pinned trust input differs")
    _closed(registry, {"schema", "mode", "process_id", "generation", "revocation_generation",
        "valid_from_utc", "valid_until_utc", "keys", "revoked_principals"}, "review registry")
    _closed(policy, {"schema", "mode", "policy_id", "process_id", "registry_sha256", "action", "audience",
        "required_roles", "valid_from_utc", "valid_until_utc", "max_review_age_seconds"}, "review policy")
    require(registry["schema"] == REGISTRY_SCHEMA and policy["schema"] == POLICY_SCHEMA,
            "versioned review registry and policy required")
    require(registry["mode"] in MODES and policy["mode"] == registry["mode"], "review trust modes differ")
    for name in ("process_id",): _id(registry[name], name)
    _id(policy["policy_id"], "policy ID")
    require(policy["process_id"] == registry["process_id"] and policy["registry_sha256"] == expected_registry_sha256
            and policy["action"] == action and policy["audience"] == audience
            and wire(policy["required_roles"]) == wire(list(ROLES)), "review authority scope differs")
    for name in ("generation", "revocation_generation"):
        require(type(registry[name]) is int and 0 <= registry[name] <= 2147483647, "exact registry generation required")
    require(type(policy["max_review_age_seconds"]) is int and 0 < policy["max_review_age_seconds"] <= 2592000,
            "bounded review age required")
    _interval(registry); _interval(policy)
    require(type(registry["keys"]) is list and len(registry["keys"]) <= MAX_KEYS
            and type(registry["revoked_principals"]) is list and len(registry["revoked_principals"]) <= MAX_KEYS,
            "bounded trust key and revocation inventory required")
    keys, public = {}, set()
    for key in registry["keys"]:
        _closed(key, {"key_id", "signer_did", "public_key_hex", "principal_id", "roles", "scope_ids",
            "valid_from_utc", "valid_until_utc", "revoked_at_utc"}, "review key")
        _id(key["key_id"], "key ID"); _id(key["principal_id"], "principal ID")
        require(type(key["signer_did"]) is str and _DID.fullmatch(key["signer_did"]), "absolute signer DID required")
        raw = key["public_key_hex"]
        require(type(raw) is str and re.fullmatch(r"[0-9a-f]{64}", raw), "raw Ed25519 public key required")
        require(key["key_id"] not in keys and raw not in public
                and all(other["signer_did"] != key["signer_did"] for other in keys.values()), "duplicate review key identity")
        require(type(key["roles"]) is list and key["roles"] and len(set(key["roles"])) == len(key["roles"])
                and all(role in ROLES for role in key["roles"]), "authorized review roles required")
        require(type(key["scope_ids"]) is list and 0 < len(key["scope_ids"]) <= 128
                and len(set(key["scope_ids"])) == len(key["scope_ids"]), "explicit distinct legal scopes required")
        for scope in key["scope_ids"]: _text(scope, "authorized legal scope")
        _interval(key)
        if key["revoked_at_utc"] is not None: _time(key["revoked_at_utc"])
        keys[key["key_id"]] = key; public.add(raw)
    revoked = {}
    for row in registry["revoked_principals"]:
        _closed(row, {"principal_id", "revoked_at_utc"}, "principal revocation")
        _id(row["principal_id"], "revoked principal"); _time(row["revoked_at_utc"])
        require(row["principal_id"] not in revoked, "duplicate principal revocation")
        revoked[row["principal_id"]] = row["revoked_at_utc"]
    require(registry["mode"] != "unavailable" or not keys, "unavailable trust cannot contain keys")
    return keys, revoked


def _verify_signature(review, key):
    """Use the existing Profile G signing CID and detached EdDSA verifier."""
    try:
        from ..profile_g import Ed25519PublicKey, verify_ed25519_artifact
        if Ed25519PublicKey is None: return "backend_unavailable"
    except (ImportError, OSError, RuntimeError): return "backend_unavailable"
    return "valid" if verify_ed25519_artifact(review,
        lambda did: bytes.fromhex(key["public_key_hex"]) if did == key["signer_did"] else None) else "invalid"


def _review(review, subject, *, claim_schema=CLAIM_SCHEMA, action=ACTION, audience=AUDIENCE,
            context_obligation_cap=32):
    _closed(review, {"schema", "action", "audience", "review_id", "key_id", "principal_id", "role",
        "registry_sha256", "policy_sha256", "issued_at_utc", "expires_at_utc", "subject", "interpretation",
        "context_closure", "signer_did", "signature_alg", "signature"}, "signed graph review")
    require(review["schema"] == claim_schema and review["action"] == action and review["audience"] == audience,
            "graph review signing domain differs")
    for name in ("review_id", "key_id", "principal_id"): _id(review[name], name)
    require(review["role"] in ROLES, "legal or formal review role required")
    for name in ("registry_sha256", "policy_sha256"): _sha(review[name])
    _interval(review, "issued_at_utc", "expires_at_utc")
    require(review["signature_alg"] == "EdDSA" and type(review["signature"]) is str
            and re.fullmatch(r"[A-Za-z0-9_-]{86}", review["signature"]), "canonical detached Ed25519 signature required")
    require(base64.urlsafe_b64encode(base64.urlsafe_b64decode(review["signature"] + "==")).decode().rstrip("=")
            == review["signature"], "noncanonical signature encoding")
    require(type(review["signer_did"]) is str and _DID.fullmatch(review["signer_did"]), "absolute signed DID required")
    _closed(review["interpretation"], {"decision", "reviewed_graph_sha256", "reviewed_ast_sha256", "rationale", "ambiguity"},
            "reviewed interpretation")
    interpretation = review["interpretation"]
    require(interpretation["decision"] in ("support", "reject", "unresolved"), "explicit interpretation decision required")
    _text(interpretation["rationale"], "review rationale")
    require(type(interpretation["ambiguity"]) is list and len(interpretation["ambiguity"]) <= 32, "bounded ambiguity declarations required")
    for entry in interpretation["ambiguity"]: _text(entry, "declared ambiguity")
    for name in ("reviewed_graph_sha256", "reviewed_ast_sha256"): _sha(interpretation[name])
    closure = review["context_closure"]
    _closed(closure, {"status", "obligations", "unresolved"}, "signed context declaration")
    require(closure["status"] in ("declared_complete", "open") and type(closure["obligations"]) is list
            and len(closure["obligations"]) <= context_obligation_cap and type(closure["unresolved"]) is list
            and len(closure["unresolved"]) <= 32, "bounded signed context declaration required")
    for entry in closure["unresolved"]: _text(entry, "unresolved context")
    for obligation in closure["obligations"]:
        _closed(obligation, {"slot_id", "disposition", "evidence_refs"}, "reviewed context obligation")
        _text(obligation["slot_id"], "context slot")
        require(obligation["disposition"] in ("resolved_by_evidence", "not_applicable", "open"), "context disposition required")
        require(type(obligation["evidence_refs"]) is list and len(obligation["evidence_refs"]) <= 8, "bounded context evidence required")
        seen = set()
        for ref in obligation["evidence_refs"]:
            _closed(ref, {"artifact_id", "sha256"}, "review evidence reference")
            _id(ref["artifact_id"], "review evidence artifact"); _sha(ref["sha256"])
            require(ref["artifact_id"] not in seen, "duplicate obligation evidence")
            seen.add(ref["artifact_id"])
    wire(review)


def _subject(subject, manifest):
    _closed(subject, {"schema", "graph_id", "graph_sha256", "ast_sha256", "source_binding_sha256",
        "source_occurrence_id", "source_text_sha256", "document_id", "document_revision", "scope_id",
        "context_packet_sha256", "context_packet_id", "context_slot_ids", "dependency_manifest_sha256",
        "required_dependency_ids", "dependency_artifacts", "graph_declared_dependency_refs"}, "review subject")
    require(subject["schema"] == SUBJECT_SCHEMA, "versioned review subject required")
    for key, value in subject.items():
        if key.endswith("_sha256"): _sha(value)
        elif key.endswith("_id") or key == "document_revision": _text(value, key)
    slots = subject["context_slot_ids"]
    require(type(slots) is list and len(slots) == len(contexts.DEPENDENCY_KINDS)
            and all(type(slot) is str for slot in slots) and len(set(slots)) == len(slots),
            "exact distinct context obligation population required")
    for slot in slots: _text(slot, "context slot")
    reachable, artifacts = _closure(manifest, subject["graph_id"], subject["graph_sha256"])
    require(wire(subject["required_dependency_ids"]) == wire(reachable)
            and wire(subject["dependency_artifacts"]) == wire(artifacts),
            "review subject dropped or changed required dependency closure")
    _check_declared_dependencies(subject["graph_declared_dependency_refs"], reachable, artifacts)


@dataclass(frozen=True)
class _ReviewDomain:
    """Internal fixed protocol configuration; never populated from review JSON."""

    subject_schema: str
    claim_schema: str
    action: str
    audience: str
    assessment_schema: str
    subject_validator: object
    context_obligation_cap: int


_GRAPH_DOMAIN = _ReviewDomain(SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE, SCHEMA, _subject, 32)


def _assess_reviews(subject, registry, policy, reviews, dependency_manifest, *, domain,
        expected_subject_sha256,
        expected_registry_sha256, expected_policy_sha256, expected_reviews_sha256,
        expected_manifest_sha256, at_time_utc, observed_artifact_sha256s, observed_pins, evidence_artifacts):
    """Shared verifier called only by fixed-domain, source-replaying wrappers."""
    _sha(expected_subject_sha256); _sha(expected_reviews_sha256)
    require(digest(subject) == expected_subject_sha256 and subject.get("schema") == domain.subject_schema,
            "independently pinned subject differs")
    require(type(reviews) is list and len(reviews) <= MAX_REVIEWS and digest(reviews) == expected_reviews_sha256,
            "independently pinned complete review population differs")
    require(subject["dependency_manifest_sha256"] == expected_manifest_sha256, "selected dependency generation differs")
    manifest = dependencies.validate_dependency_manifest(dependency_manifest, expected_manifest_sha256=expected_manifest_sha256)
    domain.subject_validator(subject, manifest)
    keys, revoked = _trust(registry, policy, expected_registry_sha256, expected_policy_sha256,
                          action=domain.action, audience=domain.audience)
    evaluation = _time(at_time_utc)
    current = dependencies.invalidate_dependencies(dependency_manifest, expected_manifest_sha256=expected_manifest_sha256,
        observed_artifact_sha256s=observed_artifact_sha256s, observed_pins=observed_pins)
    require(type(evidence_artifacts) is dict and len(evidence_artifacts) <= MAX_EVIDENCE,
            "bounded independent evidence bodies required")
    total = sum(len(wire(v)) for v in (subject, registry, policy, reviews, dependency_manifest))
    for name, raw in evidence_artifacts.items():
        _id(name, "evidence identity"); require(type(raw) is bytes, "exact review evidence bytes required")
        total += len(raw)
    require(total <= MAX_BYTES, "aggregate review evidence bound exceeded")
    common = []
    for label, value in (("registry", registry), ("policy", policy)):
        start, end = _interval(value)
        if not start <= evaluation < end: common.append(label + "_not_current")
    if registry["mode"] == "unavailable": common.append("trust_registry_unavailable")
    rows, seen, associations = [], set(), set()
    for review in reviews:
        _review(review, subject, claim_schema=domain.claim_schema, action=domain.action,
                audience=domain.audience, context_obligation_cap=domain.context_obligation_cap)
        require(review["review_id"] not in seen, "duplicate review identity")
        seen.add(review["review_id"])
        association = (review["principal_id"], review["role"])
        require(association not in associations, "duplicate principal/role review")
        associations.add(association)
        reasons = list(common)
        if wire(review["subject"]) != wire(subject): reasons.append("signed_subject_differs")
        for name, expected in (("registry_sha256", expected_registry_sha256), ("policy_sha256", expected_policy_sha256)):
            if review[name] != expected: reasons.append("signed_" + name + "_differs")
        if review["interpretation"]["reviewed_graph_sha256"] != subject["graph_sha256"] or review["interpretation"]["reviewed_ast_sha256"] != subject["ast_sha256"]:
            reasons.append("reviewed_interpretation_binding_differs")
        issued, expires = _interval(review, "issued_at_utc", "expires_at_utc")
        if not issued <= evaluation < expires: reasons.append("review_not_current")
        if (evaluation - issued).total_seconds() > policy["max_review_age_seconds"]: reasons.append("review_age_exceeded")
        for label, authority in (("registry", registry), ("policy", policy)):
            start, end = _interval(authority)
            if not start <= issued <= evaluation < end or expires > end:
                reasons.append(label + "_not_current_for_review_interval")
        key = keys.get(review["key_id"]); signature = "not_attempted_unknown_key"
        if key is None: reasons.append("unknown_authorized_key")
        else:
            if review["principal_id"] != key["principal_id"] or review["signer_did"] != key["signer_did"]:
                reasons.append("authorized_principal_binding_differs")
            if review["role"] not in key["roles"]: reasons.append("unauthorized_review_role")
            if subject["scope_id"] not in key["scope_ids"]: reasons.append("unauthorized_legal_scope")
            start, end = _interval(key)
            if not start <= issued <= evaluation < end or expires > end: reasons.append("key_not_current_for_review_interval")
            if key["revoked_at_utc"] is not None and _time(key["revoked_at_utc"]) <= evaluation: reasons.append("key_revoked")
            if key["principal_id"] in revoked and _time(revoked[key["principal_id"]]) <= evaluation: reasons.append("principal_revoked")
            signature = _verify_signature(review, key)
        if signature != "valid": reasons.append("signature_" + signature)
        obligations = review["context_closure"]["obligations"]
        closure_reasons = []
        if [row["slot_id"] for row in obligations] != subject["context_slot_ids"]: closure_reasons.append("context_obligation_population_differs")
        if review["context_closure"]["status"] != "declared_complete" or review["context_closure"]["unresolved"]:
            closure_reasons.append("context_declared_open")
        for obligation in obligations:
            if obligation["disposition"] == "open" or not obligation["evidence_refs"]: closure_reasons.append("context_obligation_unresolved")
            for ref in obligation["evidence_refs"]:
                raw = evidence_artifacts.get(ref["artifact_id"])
                if raw is None or hashlib.sha256(raw).hexdigest() != ref["sha256"]: closure_reasons.append("context_evidence_missing_or_changed")
        status = "authenticated" if not reasons else "pending" if reasons == ["signature_backend_unavailable"] else "rejected"
        rows.append({"review_id": review["review_id"], "review_sha256": digest(review), "principal_id": review["principal_id"],
            "key_id": review["key_id"], "role": review["role"], "status": status, "signature_status": signature,
            "blockers": sorted(set(reasons)), "declared_decision": review["interpretation"]["decision"],
            "declared_ambiguity": deepcopy(review["interpretation"]["ambiguity"]),
            "context_declaration_sha256": digest(review["context_closure"]),
            "signed_context_declaration_complete": not closure_reasons, "context_blockers": sorted(set(closure_reasons))})
    blockers = list(common)
    if registry["mode"] != "external_pinned_trust": blockers.append("production_trust_registry_unavailable")
    selected = [row for row in rows if row["status"] == "authenticated"]
    if len(selected) != len(rows): blockers.append("review_evidence_not_fully_authenticated")
    supporting = [row for row in selected if row["declared_decision"] == "support" and not row["declared_ambiguity"]]
    for role in ROLES:
        if not any(row["role"] == role for row in supporting): blockers.append("authenticated_" + role + "_missing")
    if any(row["declared_decision"] != "support" or row["declared_ambiguity"] for row in selected): blockers.append("authenticated_review_conflict_or_ambiguity")
    if len({row["context_declaration_sha256"] for row in selected}) > 1: blockers.append("authenticated_context_declarations_disagree")
    pairs = [(left, right) for left in supporting for right in supporting if left["role"] == ROLES[0] and right["role"] == ROLES[1]
             and left["principal_id"] != right["principal_id"] and left["key_id"] != right["key_id"]]
    if not pairs: blockers.append("distinct_authorized_review_principals_missing")
    if not any(left["signed_context_declaration_complete"] and right["signed_context_declaration_complete"] for left, right in pairs):
        blockers.append("authenticated_complete_context_declarations_missing")
    if any(key in current["stale_artifact_ids"] or key not in observed_artifact_sha256s for key in subject["required_dependency_ids"]):
        blockers.append("required_dependency_closure_not_current")
    prerequisites = not blockers
    blockers.extend(("downstream_semantic_validation_required", "downstream_Lean_kernel_admission_required"))
    report = {"schema": domain.assessment_schema, "subject_sha256": expected_subject_sha256, "registry_sha256": expected_registry_sha256,
        "policy_sha256": expected_policy_sha256, "reviews_sha256": expected_reviews_sha256,
        "dependency_manifest_sha256": expected_manifest_sha256, "dependency_invalidation_sha256": current["invalidation_sha256"],
        "evaluation_time_utc": at_time_utc, "evidence_artifact_sha256s": {key: hashlib.sha256(raw).hexdigest() for key, raw in sorted(evidence_artifacts.items())},
        "structural_intake_valid": True, "reviews": rows, "review_count": len(rows),
        "evidence_assessment_status": "authenticated" if rows and len(selected) == len(rows)
            else "rejected" if any(row["status"] == "rejected" for row in rows) else "pending",
        "authenticated_evidence_count": len(selected), "trust_mode": registry["mode"],
        "review_prerequisites_satisfied_under_selected_trust": prerequisites,
        "accepted_view_eligible": False, "eligibility_status": "blocked", "blockers": sorted(set(blockers)),
        "coverage_scope": "exact_selected_graph_reviews_context_slots_and_declared_dependencies_only",
        "legal_dependency_inventory_exhaustive": False, "evaluation_clock_authenticated": False,
        "registry_identity_authenticated_by_this_api": False, **FALSE_AUTHORITY}
    return {**json.loads(wire(report)), "assessment_sha256": digest(report)}


def assess_graph_reviews(subject, registry, policy, reviews, dependency_manifest, *, expected_subject_sha256,
        expected_registry_sha256, expected_policy_sha256, expected_reviews_sha256,
        expected_manifest_sha256, at_time_utc, observed_artifact_sha256s, observed_pins, evidence_artifacts):
    """Authenticate evidence and report named admission blockers; admit nothing.

    A subject must be retained from ``build_review_subject`` under the caller's
    independent pin. The evaluation clock and revocation snapshot are explicit
    caller inputs, not authenticated by this dictionary API. Evidence bodies
    are checked as exact bytes; their legal content is not inferred.
    """
    return _assess_reviews(subject, registry, policy, reviews, dependency_manifest,
        domain=_GRAPH_DOMAIN, expected_subject_sha256=expected_subject_sha256,
        expected_registry_sha256=expected_registry_sha256, expected_policy_sha256=expected_policy_sha256,
        expected_reviews_sha256=expected_reviews_sha256, expected_manifest_sha256=expected_manifest_sha256,
        at_time_utc=at_time_utc, observed_artifact_sha256s=observed_artifact_sha256s,
        observed_pins=observed_pins, evidence_artifacts=evidence_artifacts)


def validate_review_assessment(report, *args, **kwargs):
    """Regenerate using independently pinned original inputs; no ledger flag passes."""
    expected = assess_graph_reviews(*args, **kwargs)
    require(wire(report) == wire(expected), "graph review assessment differs from exact regeneration")
    return expected


__all__ = ["build_review_subject", "assess_graph_reviews", "validate_review_assessment"]

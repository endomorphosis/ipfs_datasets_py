"""Authenticate unapplied exact-use definition applicability declarations.

Complete original norm/definition evidence is replayed before a separate fixed
Profile G action can authenticate an association declaration. Every original
norm question stays open. No predicate substitution, governing use, accepted
meaning, graph admission, learning target, signer or clock default is supplied.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import re

from . import legal_norm_definition_evidence_v1 as companion_owner
from . import legal_norm_interpretation_review_v1 as norm
from . import legal_paired_manifest_inventory_v1 as reader

PROFILE = "unapplied-exact-norm-use-definition-applicability-declarations/v1"
SUBJECT_SCHEMA = norm.SUBJECT_SCHEMA
TEMPLATE_SCHEMA = "legal-norm-definition-applicability-template/v1"
DECLARATION_SCHEMA = "legal-norm-definition-applicability-declaration/v1"
CLAIM_SCHEMA = "legal-norm-definition-applicability-signed-claim/v1"
ACTION = "record_exact_norm_use_definition_applicability_declaration/v1"
AUDIENCE = "legal-autoformalization-norm-definition-applicability/v1"
AUTHORITY_SCHEMA = "legal-norm-definition-applicability-authority-assessment/v1"
ASSESSMENT_SCHEMA = "legal-norm-definition-applicability-assessment/v1"
MAX_REPORT_BYTES = norm.MAX_BYTES
MAX_UNRESOLVED = 32
COMPANION_FIELDS = {"norm_preparation", "request_raw", "expected_norm_preparation_sha256",
                    "expected_request_sha256", "norm_inputs", "definitions"}
OBSERVATION_FIELDS = {"observed_artifact_sha256s", "observed_pins", "evidence_artifacts"}
AUTHORITY = dict(companion_owner.FALSE_FLAGS, decisions_applied=False,
    governing_definition_applicability_verified=False, combined_norm_meaning_verified=False,
    adjudicator_human_independence_verified=False, norm_reviewer_cohort_verified=False,
    cross_candidate_cohort_verified=False, global_reviewer_cohort_verified=False,
    evaluation_clock_authenticated=False, current_registry_freshness_authenticated=False,
    accepted_view_eligible=False, graph_admission_verified=False)
_DIRECT_PINS = {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                for module in (companion_owner, norm, reader)}
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_need, _keys, _sha = norm._need, norm._keys, norm._sha


def norm_definition_applicability_sha256(value):
    """Hash complete bounded norm canonical UTF8 JSON, including embedded pins."""
    return norm.norm_review_sha256(value)


def _auth():
    return norm._owners()[1]


def _domain():
    return _auth()._ReviewDomain(SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE,
                               AUTHORITY_SCHEMA, norm._subject, norm.MAX_OBLIGATIONS)


def _pins():
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "norm definition applicability producer changed since import")
    _need({path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _DIRECT_PINS} == _DIRECT_PINS,
          "direct norm definition applicability producer changed since import")
    result = dict(companion_owner._pins(companion_owner._owners()))
    result[str(Path(__file__).resolve())] = _SELF_PIN
    result.update(_DIRECT_PINS)
    return result


def _finish(original, detached, commitment, pins, report):
    raw = norm._wire(report)
    _need(len(raw) <= MAX_REPORT_BYTES, "complete applicability report byte bound exceeded")
    _need(companion_owner._snapshot(original)[1] == commitment
          and companion_owner._snapshot(detached)[1] == commitment,
          "norm definition applicability inputs changed during operation")
    _need(_pins() == pins, "norm definition applicability producers changed during operation")
    return json.loads(raw)


def _seal(schema, **values):
    return {"schema": schema, "profile": PROFILE, **values, **AUTHORITY,
        "authority": dict(AUTHORITY), "norm_interpretation_ready": False,
        "selected_interpretation": None, "accepted_interpretation": None,
        "governing_definition_use": None, "native_ast_rewritten": False,
        "semantic_mask": 0, "consumer_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0}


def _text(value, label, maximum=8192):
    _need(type(value) is str and bool(value.strip()) and "\x00" not in value
          and len(value.encode("utf-8")) <= maximum, "bounded explicit " + label + " required")


def _refs(values):
    _need(type(values) is list and len(values) <= 8, "bounded ordered applicability evidence references required")
    seen = set()
    for ref in values:
        _keys(ref, {"artifact_id", "sha256"}, "applicability evidence reference")
        _auth()._id(ref["artifact_id"], "applicability evidence identity")
        _sha(ref["sha256"], "applicability evidence bytes")
        _need(ref["artifact_id"] not in seen, "duplicate applicability evidence identity")
        seen.add(ref["artifact_id"])


def _source_args(companion, norm_subject, norm_manifest, expected_companion_sha256,
                 companion_inputs, expected_norm_subject_sha256, expected_norm_manifest_sha256):
    return dict(companion=companion, norm_subject=norm_subject, norm_manifest=norm_manifest,
        expected_companion_sha256=expected_companion_sha256, companion_inputs=companion_inputs,
        expected_norm_subject_sha256=expected_norm_subject_sha256,
        expected_norm_manifest_sha256=expected_norm_manifest_sha256)


def _preflight(original):
    detached, commitment = companion_owner._snapshot(original)
    _keys(detached["companion_inputs"], COMPANION_FIELDS, "complete original norm definition companion inputs")
    for key in ("expected_companion_sha256", "expected_norm_subject_sha256", "expected_norm_manifest_sha256"):
        _sha(detached[key], key)
    _need(norm_definition_applicability_sha256(detached["companion"]) == detached["expected_companion_sha256"],
          "independent complete norm definition companion pin differs")
    inputs = detached["companion_inputs"]
    companion_owner._preflight({key: inputs[key] for key in ("norm_preparation", "request_raw", "norm_inputs", "definitions")},
        inputs["expected_norm_preparation_sha256"], inputs["expected_request_sha256"])
    auth = _auth()
    _keys(detached["norm_subject"], norm._SUBJECT_FIELDS, "complete original norm review subject")
    _need(detached["norm_subject"]["schema"] == SUBJECT_SCHEMA, "unchanged original norm subject schema required")
    _need(auth.digest(detached["norm_subject"]) == detached["expected_norm_subject_sha256"],
          "independent original norm subject pin differs")
    norm._owners()[0].validate_dependency_manifest(detached["norm_manifest"],
        expected_manifest_sha256=detached["expected_norm_manifest_sha256"])
    slots = detached["norm_subject"]["context_slot_ids"]
    _need(type(slots) is list and 0 < len(slots) <= MAX_UNRESOLVED
          and all(type(slot) is str for slot in slots) and len(set(slots)) == len(slots),
          "all original norm questions must fit unchanged shared unresolved bound")
    return detached, commitment


def _context(value):
    companion = companion_owner.validate_norm_definition_evidence_v1(value["companion"],
        expected_report_sha256=value["expected_companion_sha256"], **value["companion_inputs"])
    inputs = value["companion_inputs"]
    subject = norm.build_norm_review_subject_v1(inputs["norm_preparation"], value["norm_manifest"],
        expected_preparation_sha256=inputs["expected_norm_preparation_sha256"],
        expected_manifest_sha256=value["expected_norm_manifest_sha256"],
        required_dependency_ids=value["norm_subject"]["required_dependency_ids"], **inputs["norm_inputs"])
    _need(norm._same(subject, value["norm_subject"]), "original norm subject differs from complete regeneration")
    _need(companion["norm_preparation_sha256"] == inputs["expected_norm_preparation_sha256"],
          "companion names another exact norm preparation")
    _need([row["slot_id"] for row in companion["norm_obligations"]] == subject["context_slot_ids"],
          "companion and norm subject original obligation populations differ")
    return companion


def _group_uses(companion):
    """Preserve whole exact typed identities and complete first-appearance order."""
    links = companion["links"]
    _need(type(links) is list and 0 < len(links) <= companion_owner.MAX_LINKS,
          "bounded complete nominated definition links required")
    groups, by_target = [], {}
    for index, link in enumerate(links):
        target = link["request_link"]["target"]
        target_sha = norm_definition_applicability_sha256(target)
        context = {key: link[key] for key in ("typed_row", "typed_node", "typed_context", "source_rows", "norm_source_target")}
        context.update(target=target, source_paths=link["request_link"]["source_paths"])
        if target_sha not in by_target:
            group = dict(use_id="norm-definition-use:" + target_sha, **context, nominated_link_refs=[])
            by_target[target_sha] = group
            groups.append(group)
        else:
            group = by_target[target_sha]
            _need(all(norm._same(group[key], value) for key, value in context.items()),
                  "one exact typed use has inconsistent original binding evidence")
        group["nominated_link_refs"].append({"link_index": index, "sha256": norm_definition_applicability_sha256(link)})
    return groups


def _selected_link(companion, use, ref):
    _keys(ref, {"link_index", "sha256"}, "existing exact-use definition link reference")
    index = ref["link_index"]
    _need(type(index) is int and 0 <= index < len(companion["links"]), "exact existing definition link index required")
    _sha(ref["sha256"], "complete existing definition link")
    _need(any(norm._same(ref, offered) for offered in use["nominated_link_refs"]),
          "selected link belongs to another exact typed use or generation")
    link = companion["links"][index]
    _need(norm_definition_applicability_sha256(link) == ref["sha256"]
          and norm._same(link["request_link"]["target"], use["target"]),
          "selected complete definition link commitment differs")
    return link


def _source_times(companion_inputs):
    times = []
    for endpoint in companion_inputs["definitions"]:
        evidence = endpoint["review_evidence"]
        if evidence is not None:
            times.append(evidence["assessment"]["evaluation_time_utc"])
            times.extend(row["issued_at_utc"] for row in evidence["assessment_inputs"]["reviews"])
        responses = endpoint["correspondence_inputs"]["contextual_replay_inputs"]["responses"]
        times.extend(row["declaration"]["reviewer_declaration"]["issued_at_utc"] for row in responses)
    return times


def _civil(value):
    if value is not None:
        _need(type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None,
              "canonical legal-as-of civil date or null required")
        try:
            _need(date.fromisoformat(value).isoformat() == value, "canonical real legal-as-of civil date required")
        except ValueError as error:
            raise ValueError("canonical real legal-as-of civil date required") from error


def _declaration(companion, subject, companion_inputs, decisions, declared_at_utc):
    declared = _auth()._time(declared_at_utc)
    _need(all(declared >= _auth()._time(value) for value in _source_times(companion_inputs)),
          "applicability declaration predates considered assessment or source declaration")
    uses = _group_uses(companion)
    _need(type(decisions) is list and len(decisions) == len(uses), "complete ordered exact-use applicability decisions required")
    for use, choice in zip(uses, decisions, strict=True):
        _keys(choice, {"use_id", "use_sha256", "decision", "selected_link_ref", "legal_as_of_date",
                       "scope_statement", "rationale", "evidence_refs"}, "exact-use applicability decision")
        _need(choice["use_id"] == use["use_id"]
              and choice["use_sha256"] == norm_definition_applicability_sha256(use),
              "choice differs from exact ordered complete typed use")
        _need(type(choice["decision"]) is str and choice["decision"] in {
            "declare_one_supplied_alternative_applicable", "unresolved"}, "explicit unapplied applicability decision required")
        _civil(choice["legal_as_of_date"])
        _text(choice["rationale"], "applicability rationale")
        _refs(choice["evidence_refs"])
        if choice["scope_statement"] is not None:
            _text(choice["scope_statement"], "authored applicability scope statement")
        if choice["decision"] == "unresolved":
            _need(choice["selected_link_ref"] is None, "unresolved applicability cannot select a definition link")
        else:
            _need(choice["legal_as_of_date"] is not None and choice["scope_statement"] is not None
                  and bool(choice["evidence_refs"]), "positive declaration needs explicit legal date, scope and independent evidence")
            _selected_link(companion, use, choice["selected_link_ref"])
    _need(len(subject["context_slot_ids"]) <= MAX_UNRESOLVED, "shared unresolved original norm obligation bound exceeded")
    record = _seal(DECLARATION_SCHEMA,
        companion_sha256=norm_definition_applicability_sha256(companion),
        subject_sha256=_auth().digest(subject), norm_preparation_sha256=companion["norm_preparation_sha256"],
        norm_dependency_manifest_sha256=subject["dependency_manifest_sha256"],
        considered_uses_sha256=norm_definition_applicability_sha256(uses),
        considered_links_sha256=norm_definition_applicability_sha256(companion["links"]),
        considered_alternatives_sha256=norm_definition_applicability_sha256(companion["definitions"]),
        original_norm_obligations_sha256=norm_definition_applicability_sha256(companion["norm_obligations"]),
        declared_at_utc=declared_at_utc, decisions=decisions,
        status="declared_unauthenticated_unapplied_exact_use_applicability",
        effect="record_one_supplied_alternative_declaration_without_priority_substitution_or_application")
    _auth().wire(record)
    reader._wire(record, MAX_REPORT_BYTES)
    return record


def _closure(subject, body_ref=None):
    _need(len(subject["context_slot_ids"]) <= MAX_UNRESOLVED, "shared unresolved original norm obligation bound exceeded")
    return {"status": "open", "obligations": [{"slot_id": slot, "disposition": "open",
        **({} if body_ref is None else {"evidence_refs": [body_ref]})} for slot in subject["context_slot_ids"]],
        "unresolved": list(subject["context_slot_ids"])}


def _source_exclusions(companion_inputs):
    principals, dids, public_keys, unknown, actors, unsigned = set(), set(), set(), [], [], []
    for endpoint in companion_inputs["definitions"]:
        alternative = endpoint["alternative_id"]
        evidence = endpoint["review_evidence"]
        if evidence is not None:
            arguments = evidence["assessment_inputs"]
            keys = {row["key_id"]: row for row in arguments["registry"]["keys"]}
            for claim in arguments["reviews"]:
                key = keys.get(claim["key_id"])
                principals.add(claim["principal_id"])
                dids.add(claim["signer_did"])
                if key is None:
                    unknown.append({"alternative_id": alternative, "review_id": claim["review_id"]})
                else:
                    principals.add(key["principal_id"])
                    dids.add(key["signer_did"])
                    public_keys.add(key["public_key_hex"])
                actors.append({"alternative_id": alternative, "review_id": claim["review_id"], "key_id": claim["key_id"],
                    "claimed_principal_id": claim["principal_id"], "claimed_signer_did": claim["signer_did"],
                    "registered_principal_id": None if key is None else key["principal_id"],
                    "registered_signer_did": None if key is None else key["signer_did"],
                    "registered_public_key_hex": None if key is None else key["public_key_hex"]})
        for index, row in enumerate(endpoint["correspondence_inputs"]["contextual_replay_inputs"]["responses"]):
            reviewer = row["declaration"]["reviewer_declaration"]
            principals.add(reviewer["principal_id"])
            unsigned.append({"alternative_id": alternative, "response_index": index,
                "response_sha256": norm_definition_applicability_sha256(row),
                "claimed_principal_id": reviewer["principal_id"], "cryptographic_actor_inventory_available": False})
    return {"excluded_principal_ids": sorted(principals), "excluded_signer_dids": sorted(dids),
        "excluded_public_keys": sorted(public_keys), "unknown_key_reviews": unknown, "actors": actors,
        "unsigned_contextual_actors": unsigned, "cryptographic_actor_inventory_complete": not unknown and not unsigned,
        "norm_review_actor_inventory_supplied": False,
        "scope": "complete supplied definition endpoints and contextual declarations only; norm reviewers, cross-candidate and global cohorts unavailable"}


def _distinct_pair(claims, keys):
    return any(left["role"] == "legal_review" and right["role"] == "formal_review"
        and left["key_id"] in keys and right["key_id"] in keys
        and left["principal_id"] != right["principal_id"] and left["key_id"] != right["key_id"]
        and left["signer_did"] != right["signer_did"]
        and keys[left["key_id"]]["public_key_hex"] != keys[right["key_id"]]["public_key_hex"]
        for left in claims for right in claims)


def _definition_observations(companion_inputs, observations):
    endpoints = companion_inputs["definitions"]
    _need(type(observations) is list and len(observations) == len(endpoints),
          "complete ordered per-alternative current definition observations required")
    for endpoint, row in zip(endpoints, observations, strict=True):
        _keys(row, {"alternative_id", "observations"}, "current definition observation row")
        _need(row["alternative_id"] == endpoint["alternative_id"], "current definition observations reordered or foreign")
        if endpoint["review_evidence"] is None:
            _need(row["observations"] is None, "absent definition assessment requires explicit absent current observations")
        else:
            _keys(row["observations"], OBSERVATION_FIELDS, "current definition observations")


def _definition_context_intake(subject, reviews, evidence_artifacts):
    """Check exact old signed populations and referenced bytes, allowing open slots.

    Existing unresolved strings remain the original free-form declarations. This
    gate neither treats them as slot IDs nor requires support or legal closure.
    """
    blockers = []
    for claim in reviews:
        closure = claim["context_closure"]
        obligations = closure["obligations"]
        if [row["slot_id"] for row in obligations] != subject["context_slot_ids"]:
            blockers.append("definition_source_signed_context_population_differs")
        for row in obligations:
            if row["disposition"] != "open" and not row["evidence_refs"]:
                blockers.append("definition_source_nonopen_context_slot_missing_evidence")
            for ref in row["evidence_refs"]:
                raw = evidence_artifacts.get(ref["artifact_id"])
                if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                    blockers.append("definition_source_signed_context_evidence_missing_or_changed")
        if closure["status"] == "declared_complete" and (closure["unresolved"]
                or any(row["disposition"] == "open" for row in obligations)):
            blockers.append("definition_source_declared_complete_context_inconsistent")
    return sorted(set(blockers))


def _current_definitions(companion_inputs, observations, at_time_utc, fence):
    _definition_observations(companion_inputs, observations)
    owner = companion_owner._owners()[1]
    results = []
    for endpoint, observed in zip(companion_inputs["definitions"], observations, strict=True):
        evidence = endpoint["review_evidence"]
        current, blockers = None, []
        if evidence is None:
            blockers.append("original_definition_assessment_not_supplied")
        else:
            arguments = dict(evidence["assessment_inputs"], **observed["observations"])
            arguments["at_time_utc"] = at_time_utc
            current = owner.assess_definition_reviews_v2(**arguments)
            claims = arguments["reviews"]
            keys = {row["key_id"]: row for row in arguments["registry"]["keys"]}
            ids = {row["review_id"] for row in current["reviews"] if row["status"] == "authenticated"}
            authenticated = [row for row in claims if row["review_id"] in ids]
            if not claims or len(ids) != len(claims) or current["authenticated_evidence_count"] != len(claims):
                blockers.append("complete_original_definition_claims_not_currently_authenticated")
            if not _distinct_pair(authenticated, keys):
                blockers.append("distinct_current_authenticated_definition_principal_key_did_public_key_roles_missing")
            if current["trust_mode"] != "external_pinned_trust":
                blockers.append("original_definition_production_trust_unavailable")
            if "required_dependency_closure_not_current" in current["blockers"]:
                blockers.append("original_definition_dependency_closure_not_current")
            blockers.extend(_definition_context_intake(arguments["subject"], claims, arguments["evidence_artifacts"]))
            raw_context_blockers = {blocker for row in current["reviews"] for blocker in row["context_blockers"]}
            if "context_obligation_population_differs" in raw_context_blockers:
                blockers.append("definition_source_signed_context_population_differs")
            if "context_evidence_missing_or_changed" in raw_context_blockers:
                blockers.append("definition_source_signed_context_evidence_missing_or_changed")
            if _auth()._time(at_time_utc) < _auth()._time(evidence["assessment"]["evaluation_time_utc"]):
                blockers.append("applicability_evaluation_predates_original_definition_assessment")
        results.append({"alternative_id": endpoint["alternative_id"],
            "original_assessment_sha256": None if evidence is None else evidence["expected_assessment_sha256"],
            "current_assessment": current, "current_blockers": sorted(set(blockers)),
            "current_authentication_prerequisites_satisfied": not blockers,
            "contextual_companion_reviewed": False, "definition_meaning_accepted": False})
        fence()
    return results


def _source_bodies(companion_inputs):
    """Inventory known canonical structured bodies, never arbitrary source bytes.

    Original response/review transports are not separately supplied here. These
    hashes therefore identify only their existing canonical encodings, not every
    possible raw serialization or the source/context attachments they reference.
    """
    identities, hashes = set(), set()
    for endpoint in companion_inputs["definitions"]:
        evidence = endpoint["review_evidence"]
        if evidence is not None:
            hashes.add(norm_definition_applicability_sha256(evidence["assessment"]))
            hashes.update(norm_definition_applicability_sha256(claim)
                          for claim in evidence["assessment_inputs"]["reviews"])
        for response in endpoint["correspondence_inputs"]["contextual_replay_inputs"]["responses"]:
            hashes.add(norm_definition_applicability_sha256(response))
    return identities, hashes


def _content(identity, raw_pin, canonical_pin, evidence, claims, companion, subject, companion_inputs):
    if identity is None:
        return None, []
    try:
        raw = evidence.get(identity)
        _need(type(raw) is bytes and hashlib.sha256(raw).hexdigest() == raw_pin,
              "independent common applicability declaration raw pin differs")
        record = reader._read_json(raw, MAX_REPORT_BYTES, "common applicability declaration")
        _auth().wire(record)
        _need(norm_definition_applicability_sha256(record) == canonical_pin,
              "independent complete common applicability declaration canonical pin differs")
        expected = _declaration(companion, subject, companion_inputs, record["decisions"], record["declared_at_utc"])
        _need(norm._same(record, expected), "common applicability declaration differs from complete population regeneration")
        closure = _closure(subject, {"artifact_id": identity, "sha256": raw_pin})
        _need(all(norm._same(claim["context_closure"], closure) for claim in claims),
              "signed original norm open slots, order or exact whole common body reference differs")
        forbidden_ids, forbidden_sha = _source_bodies(companion_inputs)
        forbidden_ids.add(identity)
        forbidden_sha.add(raw_pin)
        forbidden_sha.add(norm_definition_applicability_sha256(companion))
        for choice in record["decisions"]:
            for ref in choice["evidence_refs"]:
                support = evidence.get(ref["artifact_id"])
                _need(ref["artifact_id"] not in forbidden_ids and ref["sha256"] not in forbidden_sha
                      and type(support) is bytes and hashlib.sha256(support).hexdigest() == ref["sha256"],
                      "independent applicability support missing, changed or aliases source/common bytes")
        return record, []
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
        return None, [str(error) or "invalid common applicability declaration content"]


def _authority_inputs(registry, policy, reviews, identity, raw_pin, canonical_pin,
                      registry_pin, policy_pin, reviews_pin, evidence):
    auth = _auth()
    for pin in (registry_pin, policy_pin, reviews_pin):
        _sha(pin, "independent applicability trust/review population")
    auth._trust(registry, policy, registry_pin, policy_pin, action=ACTION, audience=AUDIENCE)
    _need(type(reviews) is list and len(reviews) <= auth.MAX_REVIEWS and auth.digest(reviews) == reviews_pin,
          "independently pinned complete applicability review population differs")
    _need(type(evidence) is dict and len(evidence) <= auth.MAX_EVIDENCE
          and all(type(key) is str and type(raw) is bytes for key, raw in evidence.items())
          and sum(map(len, evidence.values())) <= auth.MAX_BYTES, "bounded immutable applicability evidence required")
    for identity_key in evidence:
        auth._id(identity_key, "applicability evidence identity")
    _need(sum(len(auth.wire(value)) for value in (registry, policy, reviews))
          + sum(map(len, evidence.values())) <= auth.MAX_BYTES, "aggregate applicability authority evidence byte bound exceeded")
    if identity is None:
        _need(raw_pin is None and canonical_pin is None and reviews == [],
              "absent applicability declaration requires absent pins and no authority claims")
    else:
        auth._id(identity, "common applicability declaration identity")
        _sha(raw_pin, "common applicability declaration raw bytes")
        _sha(canonical_pin, "complete common applicability declaration")


def _assess_prepared(companion, subject, manifest, companion_inputs, current_definitions,
        registry, policy, reviews, *, declaration_artifact_id, expected_declaration_raw_sha256,
        expected_declaration_sha256, expected_applicability_registry_sha256,
        expected_applicability_policy_sha256, expected_applicability_reviews_sha256,
        at_time_utc, observed_artifact_sha256s, observed_pins, evidence_artifacts):
    """Downstream unit seam; public intake fully replays original endpoints first."""
    auth = _auth()
    _authority_inputs(registry, policy, reviews, declaration_artifact_id, expected_declaration_raw_sha256,
        expected_declaration_sha256, expected_applicability_registry_sha256,
        expected_applicability_policy_sha256, expected_applicability_reviews_sha256, evidence_artifacts)
    _need(type(current_definitions) is list and [row["alternative_id"] for row in current_definitions]
          == [row["alternative_id"] for row in companion_inputs["definitions"]],
          "complete ordered current definition assessment population required")
    for row in current_definitions:
        if row["current_assessment"] is not None:
            _need(row["current_assessment"]["evaluation_time_utc"] == at_time_utc,
                  "current definition assessment uses another explicit clock")
    authority = auth._assess_reviews(subject, registry, policy, reviews, manifest, domain=_domain(),
        expected_subject_sha256=auth.digest(subject), expected_registry_sha256=expected_applicability_registry_sha256,
        expected_policy_sha256=expected_applicability_policy_sha256,
        expected_reviews_sha256=expected_applicability_reviews_sha256,
        expected_manifest_sha256=subject["dependency_manifest_sha256"], at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s, observed_pins=observed_pins, evidence_artifacts=evidence_artifacts)
    record, content_blockers = _content(declaration_artifact_id, expected_declaration_raw_sha256,
        expected_declaration_sha256, evidence_artifacts, reviews, companion, subject, companion_inputs)
    inventory = _source_exclusions(companion_inputs)
    keys = {row["key_id"]: row for row in registry["keys"]}
    blockers = []
    if inventory["unknown_key_reviews"]:
        blockers.append("definition_source_public_key_inventory_incomplete")
    if inventory["unsigned_contextual_actors"]:
        blockers.append("unsigned_contextual_actor_cryptographic_inventory_unavailable")
    for claim in reviews:
        key = keys.get(claim["key_id"])
        if claim["principal_id"] in inventory["excluded_principal_ids"] or key is not None and key["principal_id"] in inventory["excluded_principal_ids"]:
            blockers.append("applicability_reviewer_reuses_claimed_or_registered_source_principal")
        if claim["signer_did"] in inventory["excluded_signer_dids"] or key is not None and key["signer_did"] in inventory["excluded_signer_dids"]:
            blockers.append("applicability_reviewer_reuses_claimed_or_registered_source_did")
        if key is not None and key["public_key_hex"] in inventory["excluded_public_keys"]:
            blockers.append("applicability_reviewer_reuses_registered_source_public_key")
    ids = {row["review_id"] for row in authority["reviews"] if row["status"] == "authenticated"}
    authenticated = [row for row in reviews if row["review_id"] in ids]
    if not _distinct_pair(authenticated, keys):
        blockers.append("distinct_authenticated_applicability_principal_key_did_public_key_roles_missing")
    if any(row["interpretation"]["decision"] != "support" or row["interpretation"]["ambiguity"] for row in authenticated):
        blockers.append("applicability_claims_reject_or_dispute_common_declaration")
    evaluation = auth._time(at_time_utc)
    if any(evaluation < auth._time(value) for value in _source_times(companion_inputs)):
        blockers.append("applicability_evaluation_predates_considered_source_evidence")
    if record is not None:
        declared = auth._time(record["declared_at_utc"])
        if declared > evaluation:
            blockers.append("common_applicability_declaration_postdates_evaluation")
        if any(auth._time(row["issued_at_utc"]) < declared for row in reviews):
            blockers.append("applicability_claim_predates_common_declaration")
    if authority["trust_mode"] != "external_pinned_trust":
        blockers.append("applicability_production_trust_unavailable")
    if "required_dependency_closure_not_current" in authority["blockers"]:
        blockers.append("original_norm_dependency_closure_not_current")
    endpoint_ready = all(row["current_authentication_prerequisites_satisfied"] is True for row in current_definitions)
    body_authenticated = bool(record is not None and not content_blockers and reviews and len(authenticated) == len(reviews))
    custody_ready = body_authenticated and endpoint_ready and not blockers
    selected = 0 if record is None else sum(row["decision"] == "declare_one_supplied_alternative_applicable" for row in record["decisions"])
    return _seal(ASSESSMENT_SCHEMA, subject=subject,
        expected_companion_sha256=norm_definition_applicability_sha256(companion), original_companion=companion,
        uses=_group_uses(companion), current_definition_assessments=current_definitions,
        raw_applicability_authority_assessment=authority,
        declaration_artifact_ref=None if declaration_artifact_id is None else {"artifact_id": declaration_artifact_id, "sha256": expected_declaration_raw_sha256},
        expected_declaration_sha256=expected_declaration_sha256, declaration_record=record,
        common_body_content_status="absent" if declaration_artifact_id is None else "rejected" if content_blockers else "valid_declared_content",
        content_blockers=content_blockers, source_reviewer_exclusions=inventory,
        separation_and_chronology_blockers=sorted(set(blockers)),
        common_body_authenticated_under_selected_trust=body_authenticated,
        current_definition_endpoint_prerequisites_satisfied=endpoint_ready,
        current_definition_endpoint_prerequisite_scope="authentication, exact signed-context intake and dependency snapshots only; deliberately open slots and dissent remain; not accepted definition meaning",
        original_norm_dependency_closure_current="required_dependency_closure_not_current" not in authority["blockers"],
        partial_declaration_custody_prerequisites_satisfied_under_selected_trust=bool(custody_ready),
        prerequisite_scope="definition endpoint authentication and new common declaration custody only; norm reviewers unavailable",
        original_norm_manifest_covers_definition_endpoints=False,
        original_norm_questions_answered=False, closed_context_prerequisites_satisfied=False,
        combined_norm_meaning_prerequisites_satisfied=False,
        closed_context_blockers=["all_original_norm_obligations_required_open", "norm_source_and_meaning_review_inputs_not_supplied",
            "governing_definition_application_and_semantic_admission_not_performed"],
        pending_uses=[{"use_id": use["use_id"], "declared_decision": None if record is None else record["decisions"][index]["decision"],
            "decision_applied": False, "governing_definition_use": None} for index, use in enumerate(_group_uses(companion))],
        counts={"uses": len(_group_uses(companion)), "alternatives": len(companion["definitions"]),
            "links": len(companion["links"]), "declaration_bodies": int(declaration_artifact_id is not None),
            "authenticated_authority_claims": authority["authenticated_evidence_count"], "declared_selected_uses": selected,
            "decisions_applied": 0, "definition_applications": 0},
        evidence_scope="Independent raw bytes are hashed without truth, adequate support, nested attachment or typed-substitution verification.",
        self_support_exclusion_scope="Exact common-body identity/raw-byte aliases and known canonical whole companion/response/review encodings; other original source/context attachments remain usable and alternate structured-body transports are not identified.")


def build_norm_definition_applicability_template_v1(companion, norm_subject, norm_manifest, *,
        expected_companion_sha256, companion_inputs, expected_norm_subject_sha256, expected_norm_manifest_sha256):
    original = _source_args(companion, norm_subject, norm_manifest, expected_companion_sha256,
        companion_inputs, expected_norm_subject_sha256, expected_norm_manifest_sha256)
    detached, commitment = _preflight(original)
    pins = _pins()
    checked = _context(detached)
    uses = _group_uses(checked)
    report = _seal(TEMPLATE_SCHEMA, subject_sha256=expected_norm_subject_sha256,
        companion_sha256=expected_companion_sha256, original_norm_obligations=checked["norm_obligations"],
        uses=uses, alternatives=checked["definitions"], links=checked["links"],
        declaration={"declared_at_utc": None, "decisions": [{"use_id": use["use_id"],
            "use_sha256": norm_definition_applicability_sha256(use), "decision": None,
            "selected_link_ref": None, "legal_as_of_date": None, "scope_statement": None,
            "rationale": None, "evidence_refs": []} for use in uses]},
        status="blank_unsubmitted_exact_use_applicability_template", producer_pins=pins)
    return _finish(original, detached, commitment, pins, report)


def build_norm_definition_applicability_declaration_v1(companion, norm_subject, norm_manifest, decisions, *,
        declared_at_utc, expected_companion_sha256, companion_inputs, expected_norm_subject_sha256, expected_norm_manifest_sha256):
    original = dict(_source_args(companion, norm_subject, norm_manifest, expected_companion_sha256,
        companion_inputs, expected_norm_subject_sha256, expected_norm_manifest_sha256), decisions=decisions, declared_at_utc=declared_at_utc)
    detached, commitment = _preflight(original)
    pins = _pins()
    checked = _context(detached)
    report = _declaration(checked, detached["norm_subject"], detached["companion_inputs"], detached["decisions"], detached["declared_at_utc"])
    return _finish(original, detached, commitment, pins, report)


def assess_norm_definition_applicability_v1(companion, norm_subject, norm_manifest,
        applicability_registry, applicability_policy, applicability_reviews, *, expected_companion_sha256,
        companion_inputs, expected_norm_subject_sha256, expected_norm_manifest_sha256,
        declaration_artifact_id, expected_declaration_raw_sha256, expected_declaration_sha256,
        expected_applicability_registry_sha256, expected_applicability_policy_sha256,
        expected_applicability_reviews_sha256, at_time_utc, observed_artifact_sha256s,
        observed_pins, evidence_artifacts, definition_observations):
    original = dict(_source_args(companion, norm_subject, norm_manifest, expected_companion_sha256,
        companion_inputs, expected_norm_subject_sha256, expected_norm_manifest_sha256),
        applicability_registry=applicability_registry, applicability_policy=applicability_policy,
        applicability_reviews=applicability_reviews, declaration_artifact_id=declaration_artifact_id,
        expected_declaration_raw_sha256=expected_declaration_raw_sha256, expected_declaration_sha256=expected_declaration_sha256,
        expected_applicability_registry_sha256=expected_applicability_registry_sha256,
        expected_applicability_policy_sha256=expected_applicability_policy_sha256,
        expected_applicability_reviews_sha256=expected_applicability_reviews_sha256, at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s, observed_pins=observed_pins,
        evidence_artifacts=evidence_artifacts, definition_observations=definition_observations)
    detached, commitment = _preflight(original)
    _definition_observations(detached["companion_inputs"], detached["definition_observations"])
    _authority_inputs(detached["applicability_registry"], detached["applicability_policy"], detached["applicability_reviews"],
        detached["declaration_artifact_id"], detached["expected_declaration_raw_sha256"], detached["expected_declaration_sha256"],
        detached["expected_applicability_registry_sha256"], detached["expected_applicability_policy_sha256"],
        detached["expected_applicability_reviews_sha256"], detached["evidence_artifacts"])
    pins = _pins()
    def fence():
        _need(companion_owner._snapshot(original)[1] == commitment
              and companion_owner._snapshot(detached)[1] == commitment,
              "norm definition applicability inputs changed during replay")
        _need(_pins() == pins, "norm definition applicability producers changed during replay")
    checked = _context(detached)
    fence()
    current = _current_definitions(detached["companion_inputs"], detached["definition_observations"], detached["at_time_utc"], fence)
    authority_fields = {key: detached[key] for key in ("declaration_artifact_id", "expected_declaration_raw_sha256",
        "expected_declaration_sha256", "expected_applicability_registry_sha256", "expected_applicability_policy_sha256",
        "expected_applicability_reviews_sha256", "at_time_utc", "observed_artifact_sha256s", "observed_pins", "evidence_artifacts")}
    report = _assess_prepared(checked, detached["norm_subject"], detached["norm_manifest"], detached["companion_inputs"],
        current, detached["applicability_registry"], detached["applicability_policy"], detached["applicability_reviews"], **authority_fields)
    report["producer_pins"] = pins
    report["assessment_sha256"] = norm_definition_applicability_sha256(report)
    return _finish(original, detached, commitment, pins, report)


def validate_norm_definition_applicability_v1(report, *args, expected_report_sha256, **kwargs):
    original = dict(report=report, args=list(args), kwargs=kwargs)
    detached, commitment = companion_owner._snapshot(original)
    _sha(expected_report_sha256, "complete norm definition applicability report")
    _need(norm_definition_applicability_sha256(detached["report"]) == expected_report_sha256,
          "independently pinned complete applicability report differs")
    pins = _pins()
    expected = assess_norm_definition_applicability_v1(*detached["args"], **detached["kwargs"])
    _need(norm._same(detached["report"], expected), "norm definition applicability differs from complete exact regeneration")
    return _finish(original, detached, commitment, pins, expected)


__all__ = ["build_norm_definition_applicability_template_v1", "build_norm_definition_applicability_declaration_v1",
           "assess_norm_definition_applicability_v1", "validate_norm_definition_applicability_v1",
           "norm_definition_applicability_sha256"]

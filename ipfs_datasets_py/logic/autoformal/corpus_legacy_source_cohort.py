"""Complete declared legacy review cohorts and cross-request exclusions.

Replays the existing typed and adjudication owners. The expected population is
an independently supplied scope, not discovery of all external submissions.
No signatures, policy, current registry, source choice or legal meaning are
created here. Per-request signed bodies remain unchanged; cohort checks are a
separate bound assessment and do not claim that reviewers signed the cohort.
"""
from __future__ import annotations

import json

from . import corpus_contracts as contracts
from . import corpus_legacy_source_adjudication as adjudication
from . import corpus_legacy_source_responses as responses
from . import corpus_legacy_source_review as source
from . import legal_graph_review as auth

PROFILE = "complete-declared-legacy-source-review-cohort/v1"
COHORT_SCHEMA = "legal-corpus-legacy-source-review-cohort/v1"
ASSESSMENT_SCHEMA = "legal-corpus-legacy-source-cohort-adjudications/v1"
MAX_BANKS = 8
MAX_REQUESTS = 64
MAX_REVIEWS = 256
# Count repeated byte references as replay work, not as unique memory usage.
MAX_REPLAY_BYTES = 512 * 1024**2
FALSE_FLAGS = {**adjudication.FALSE_FLAGS,
    "cohort_human_independence_verified": False,
    "external_submission_inventory_exhaustive": False,
    "registry_snapshot_currentness_authenticated": False,
    "evaluation_clock_authenticated": False}
_BANK_FIELDS = {"bank_id", "preparation", "source_registry", "source_policy", "requests"}
_MEMBER_FIELDS = {"typed_assessment", "source_reviews", "response_inputs"}
_ADJ_FIELDS = {"bank_id", "request_ordinal", "assessment", "adjudication_registry",
               "adjudication_policy", "adjudication_reviews", "assessment_inputs"}
_ADJ_INPUT_FIELDS = {"declaration_artifact_id", "expected_declaration_sha256",
    "expected_adjudication_registry_sha256", "expected_adjudication_policy_sha256",
    "expected_adjudication_reviews_sha256", "at_time_utc", "observed_artifact_sha256s",
    "observed_pins", "evidence_artifacts"}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _freeze(value):
    return json.loads(auth.wire(value))


def _same(left, right):
    return auth.wire(left) == auth.wire(right)


def _ref(record):
    return responses._ref(record)


def _input_cost(inputs):
    byte_fields = {"join_bytes", "producer_receipt_bytes", "paired_row_bytes", "evidence_artifacts"}
    return (len(inputs["join_bytes"]) + len(inputs["producer_receipt_bytes"] or b"")
        + sum(map(len, inputs["paired_row_bytes"]))
        + sum(map(len, inputs["evidence_artifacts"].values()))
        + len(auth.wire({key: value for key, value in inputs.items() if key not in byte_fields})))


def _inputs(banks, expected_population, expected_population_sha256):
    """Bound, detach and bind the whole population before expensive replay."""
    contracts.require_sha256(expected_population_sha256, "expected cohort population SHA256")
    expected = _freeze(expected_population)
    if auth.digest(expected) != expected_population_sha256:
        _fail("independently pinned cohort population differs")
    if type(banks) is not list or not 0 < len(banks) <= MAX_BANKS:
        _fail("bounded nonempty cohort banks required")
    detached, observed, bank_ids, request_ids = [], [], set(), set()
    size, total_reviews, total_requests = 0, 0, 0
    for bank in banks:
        contracts.require_keys(bank, _BANK_FIELDS, "legacy source cohort bank")
        auth._id(bank["bank_id"], "bank identity")
        identity = bank["bank_id"]
        if identity in bank_ids:
            _fail("duplicate cohort bank identity")
        bank_ids.add(identity)
        preparation = source._detach(bank["preparation"])
        contracts.require_keys(preparation, source._BUNDLE_KEYS, "complete source preparation")
        registry, policy = _freeze(bank["source_registry"]), _freeze(bank["source_policy"])
        members = bank["requests"]
        if (type(members) is not list or not members
                or len(members) != len(preparation["requests"])):
            _fail("every prepared request must be supplied in the cohort")
        total_requests += len(members)
        if total_requests > MAX_REQUESTS:
            _fail("cohort request bound exceeded")
        size += sum(len(auth.wire(item)) for item in (preparation, registry, policy))
        copied, pins = [], []
        for ordinal, member in enumerate(members):
            contracts.require_keys(member, _MEMBER_FIELDS, "cohort request evidence")
            typed, reviews = _freeze(member["typed_assessment"]), _freeze(member["source_reviews"])
            if type(reviews) is not list or len(reviews) > auth.MAX_REVIEWS:
                _fail("bounded complete source reviews required")
            total_reviews += len(reviews)
            if total_reviews > MAX_REVIEWS:
                _fail("cohort review bound exceeded")
            inputs = adjudication._replay_inputs(member["response_inputs"])
            contracts.require_int(inputs["request_ordinal"], "cohort request ordinal", maximum=len(members) - 1)
            if inputs["request_ordinal"] != ordinal:
                _fail("cohort requests must retain complete preparation order")
            request = preparation["requests"][ordinal]
            ref = _ref(request)
            if ref["record_cid"] in request_ids:
                _fail("duplicate request identity across declared cohort")
            request_ids.add(ref["record_cid"])
            size += len(auth.wire(typed)) + len(auth.wire(reviews)) + _input_cost(inputs)
            if size > MAX_REPLAY_BYTES:
                _fail("aggregate cohort replay byte budget exceeded")
            copied.append({"typed_assessment": typed, "source_reviews": reviews, "response_inputs": inputs})
            pins.append({"request_ref": ref, "typed_assessment_sha256": auth.digest(typed),
                         "source_reviews_sha256": auth.digest(reviews)})
        detached.append({"bank_id": identity, "preparation": preparation,
            "source_registry": registry, "source_policy": policy, "requests": copied})
        observed.append({"bank_id": identity, "preparation_sha256": auth.digest(preparation),
            "registry_sha256": auth.digest(registry), "policy_sha256": auth.digest(policy), "requests": pins})
    if not _same(expected, observed):
        _fail("complete ordered cohort differs from independently expected population")
    return detached, expected


def _prepare(banks, population, population_sha256):
    result, principals, dids, public_keys = [], set(), set(), set()
    request_count, review_count, unknown_keys = 0, 0, 0
    for bank, expected in zip(banks, population, strict=True):
        members = []
        for ordinal, (member, pin) in enumerate(zip(bank["requests"], expected["requests"], strict=True)):
            # Reuse exact current source/typed validation, including rejected
            # content retained in the submitted denominator.
            context = adjudication._context(bank["preparation"], member["typed_assessment"],
                bank["source_registry"], bank["source_policy"], member["source_reviews"],
                pin["typed_assessment_sha256"], member["response_inputs"])
            _, typed, registry, _, reviews, _, request, _, _ = context
            keys = {key["key_id"]: key for key in registry["keys"]}
            raw_status = {row["review_id"]: row for row in typed["raw_source_assessment"]["reviews"]}
            typed_status = {row["review_id"]: row for row in typed["response_results"]}
            inventory = []
            for claim in reviews:
                key = keys.get(claim["key_id"])
                principals.add(claim["principal_id"])
                dids.add(claim["signer_did"])
                if key is None:
                    unknown_keys += 1
                else:
                    # A rejected mismatched identity still retains both the
                    # claimed identity and the registered identity of its key.
                    principals.add(key["principal_id"])
                    dids.add(key["signer_did"])
                    public_keys.add(key["public_key_hex"])
                inventory.append({"review_id": claim["review_id"], "review_sha256": auth.digest(claim),
                    "principal_id": claim["principal_id"], "signer_did": claim["signer_did"],
                    "key_id": claim["key_id"], "role": claim["role"],
                    "registered_principal_id": None if key is None else key["principal_id"],
                    "registered_signer_did": None if key is None else key["signer_did"],
                    "public_key_hex": None if key is None else key["public_key_hex"],
                    "authentication_status": raw_status[claim["review_id"]]["status"],
                    "signature_status": raw_status[claim["review_id"]]["signature_status"],
                    "authenticated_typed_content": typed_status[claim["review_id"]]["authenticated_typed_content"]})
            review_count += len(reviews)
            request_count += 1
            members.append({**pin, "request_ordinal": ordinal, "reviewer_inventory": inventory,
                "active_slot_ids": list(request["context_slot_ids"]),
                "deferred_review_slot_ids": list(request["deferred_review_slot_ids"])})
        result.append({key: value for key, value in expected.items() if key != "requests"} | {"requests": members})
    return contracts.seal_record({"schema": COHORT_SCHEMA, "profile": PROFILE,
        "expected_population_sha256": population_sha256, "banks": result,
        "excluded_principal_ids": sorted(principals), "excluded_signer_dids": sorted(dids),
        "excluded_public_keys": sorted(public_keys), "complete_under_expected_population": True,
        "counts": {"banks": len(result), "requests": request_count, "reviews": review_count,
                   "unknown_key_reviews": unknown_keys},
        "coverage_scope": "all_requests_and_supplied_reviews_in_independently_pinned_bank_population",
        "view": "candidate", **FALSE_FLAGS, **source._UNSELECTED})


def prepare_legacy_source_review_cohort(banks, *, expected_population, expected_population_sha256):
    """Replay all declared banks and retain every claimed/known reviewer identity."""
    detached, expected = _inputs(banks, expected_population, expected_population_sha256)
    return _prepare(detached, expected, expected_population_sha256)


def validate_legacy_source_review_cohort(cohort, *args, **kwargs):
    checked = contracts.clone_json(cohort)
    expected = prepare_legacy_source_review_cohort(*args, **kwargs)
    if not _same(checked, expected):
        _fail("legacy source cohort differs from exact regeneration")
    return checked


def _adjudications(values, expected_hashes, banks):
    expected_hashes = _freeze(expected_hashes)
    count = sum(len(bank["requests"]) for bank in banks)
    if (type(values) is not list or type(expected_hashes) is not list
            or len(values) != count or len(expected_hashes) != count):
        _fail("complete ordered cohort adjudication population required")
    result, total = [], 0
    for value, expected in zip(values, expected_hashes, strict=True):
        contracts.require_keys(value, _ADJ_FIELDS, "cohort adjudication input")
        contracts.require_sha256(expected, "expected adjudication assessment SHA256")
        contracts.require_keys(value["assessment_inputs"], _ADJ_INPUT_FIELDS, "adjudication assessment inputs")
        evidence = adjudication._evidence(value["assessment_inputs"]["evidence_artifacts"])
        copied = _freeze({key: item for key, item in value.items() if key != "assessment_inputs"})
        copied["assessment_inputs"] = _freeze({key: item for key, item in value["assessment_inputs"].items()
                                                if key != "evidence_artifacts"}) | {"evidence_artifacts": evidence}
        if auth.digest(copied["assessment"]) != expected:
            _fail("independently pinned adjudication assessment differs")
        total += len(auth.wire({key: item for key, item in copied.items() if key != "assessment_inputs"}))
        total += len(auth.wire({key: item for key, item in copied["assessment_inputs"].items()
                                if key != "evidence_artifacts"})) + sum(map(len, evidence.values()))
        if total > auth.MAX_BYTES:
            _fail("aggregate cohort adjudication input budget exceeded")
        result.append(copied)
    return result


def assess_legacy_source_cohort_adjudications(cohort, banks, adjudications, *, expected_population,
        expected_population_sha256, expected_cohort_sha256, expected_adjudication_assessment_sha256s):
    """Recheck each declaration and reject identity reuse anywhere in the cohort.

    Assessment times and trust snapshots retain each original request's explicit
    values. This batch is not a simultaneous live freshness check or an action.
    A future application must obtain a same-time upstream requalification.
    """
    contracts.require_sha256(expected_cohort_sha256, "expected cohort SHA256")
    offered = contracts.clone_json(cohort)
    if auth.digest(offered) != expected_cohort_sha256:
        _fail("independently pinned source cohort differs")
    detached, expected = _inputs(banks, expected_population, expected_population_sha256)
    adjudications = _adjudications(adjudications, expected_adjudication_assessment_sha256s, detached)
    replayed = _prepare(detached, expected, expected_population_sha256)
    if not _same(offered, replayed):
        _fail("cohort identities or population differ from full replay")
    results, index = [], 0
    for bank, cohort_bank in zip(detached, replayed["banks"], strict=True):
        for ordinal, (member, cohort_member) in enumerate(zip(bank["requests"], cohort_bank["requests"], strict=True)):
            item = adjudications[index]
            contracts.require_int(item["request_ordinal"], "adjudication request ordinal", maximum=MAX_REQUESTS - 1)
            if item["bank_id"] != bank["bank_id"] or item["request_ordinal"] != ordinal:
                _fail("adjudication population moved across cohort requests")
            report = adjudication.validate_legacy_source_adjudication(item["assessment"],
                bank["preparation"], member["typed_assessment"], bank["source_registry"],
                bank["source_policy"], member["source_reviews"], item["adjudication_registry"],
                item["adjudication_policy"], item["adjudication_reviews"],
                expected_typed_assessment_sha256=cohort_member["typed_assessment_sha256"],
                response_inputs=member["response_inputs"], **item["assessment_inputs"])
            keys = {key["key_id"]: key for key in item["adjudication_registry"]["keys"]}
            matches = []
            for claim in item["adjudication_reviews"]:
                key = keys.get(claim["key_id"])
                reasons = []
                if (claim["principal_id"] in replayed["excluded_principal_ids"]
                        or key is not None and key["principal_id"] in replayed["excluded_principal_ids"]):
                    reasons.append("principal_id")
                if (claim["signer_did"] in replayed["excluded_signer_dids"]
                        or key is not None and key["signer_did"] in replayed["excluded_signer_dids"]):
                    reasons.append("signer_did")
                if key is not None and key["public_key_hex"] in replayed["excluded_public_keys"]:
                    reasons.append("public_key")
                if reasons:
                    matches.append({"review_id": claim["review_id"], "identity_kinds": reasons})
            blockers = []
            upstream = report["authority_prerequisites_satisfied_under_selected_trust"]
            if not upstream:
                blockers.append("original_adjudication_prerequisites_unsatisfied")
            if matches:
                blockers.append("adjudicator_matches_declared_source_review_cohort")
            if replayed["counts"]["unknown_key_reviews"]:
                blockers.append("source_cohort_public_key_inventory_incomplete")
            results.append({"bank_id": bank["bank_id"], "request_ordinal": ordinal,
                "request_ref": cohort_member["request_ref"], "adjudication_assessment_sha256": auth.digest(report),
                "evaluation_time_utc": item["assessment_inputs"]["at_time_utc"],
                "original_authority_prerequisites_satisfied": upstream,
                "exclusion_matches": matches, "blockers": blockers,
                "cohort_authority_prerequisites_satisfied": not blockers,
                "decision_applied": False})
            index += 1
    report = {"schema": ASSESSMENT_SCHEMA, "profile": PROFILE, "cohort_ref": _ref(replayed),
        "expected_population_sha256": expected_population_sha256,
        "expected_adjudication_assessment_sha256s": [auth.digest(item["assessment"]) for item in adjudications],
        "request_results": results,
        "counts": {"banks": len(detached), "requests": len(results),
            "eligible_requests": sum(row["cohort_authority_prerequisites_satisfied"] for row in results),
            "excluded_requests": sum(bool(row["exclusion_matches"]) for row in results),
            "source_decisions_applied": 0},
        "cohort_binding_signed_by_adjudicators": False,
        "coverage_scope": "declaration_prerequisites_and_supplied_cohort_identity_exclusion_only",
        "view": "candidate", **FALSE_FLAGS, **source._UNSELECTED}
    report["assessment_sha256"] = auth.digest(report)
    return _freeze(report)


def validate_legacy_source_cohort_adjudications(report, *args, **kwargs):
    checked = _freeze(report)
    expected = assess_legacy_source_cohort_adjudications(*args, **kwargs)
    if not _same(checked, expected):
        _fail("cohort adjudication assessment differs from exact regeneration")
    return checked


__all__ = ["prepare_legacy_source_review_cohort", "validate_legacy_source_review_cohort",
           "assess_legacy_source_cohort_adjudications", "validate_legacy_source_cohort_adjudications"]

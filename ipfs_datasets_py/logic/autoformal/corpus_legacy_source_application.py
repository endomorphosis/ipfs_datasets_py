"""Separately authorized genesis snapshots of declared legacy answer references.

Replays the complete declared cohort, then rechecks every source/adjudication
at application time under the original pinned trust snapshots. The only effect
is an atomic nine-reference candidate projection. No physical source choice,
legal meaning, current registry discovery, training or proof authority follows.
"""
from __future__ import annotations

from . import corpus_contracts as contracts
from . import corpus_legacy_source_adjudication as adjudication
from . import corpus_legacy_source_cohort as cohorts
from . import corpus_legacy_source_responses as responses
from . import corpus_legacy_source_review as source
from . import legal_graph_review as auth

PROFILE = "signed-genesis-legacy-source-answer-snapshot/v1"
DECLARATION_SCHEMA = "legal-corpus-legacy-source-application-declaration/v1"
CLAIM_SCHEMA = "legal-corpus-legacy-source-application-signed-claim/v1"
ACTION = "activate_legacy_candidate_source_answer_snapshot/v1"
AUDIENCE = "legal-autoformalization-legacy-source-application/v1"
ASSESSMENT_SCHEMA = "legal-corpus-legacy-source-application-authority-assessment/v1"
REPORT_SCHEMA = "legal-corpus-legacy-source-application-assessment/v1"
EFFECT = "copy_exact_declared_answer_variant_references_only"
FALSE_FLAGS = {**cohorts.FALSE_FLAGS, "application_human_independence_verified": False}
MAX_APPLICATION_BYTES = auth.MAX_BYTES
_DOMAIN = auth._ReviewDomain(source.SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE,
                             ASSESSMENT_SCHEMA, source._subject, 9)
_ENTRY_FIELDS = {"bank_id", "request_ordinal", "application_registry", "application_policy",
                 "application_reviews", "assessment_inputs"}
_INPUT_FIELDS = {"declaration_artifact_id", "expected_declaration_sha256",
    "expected_application_registry_sha256", "expected_application_policy_sha256",
    "expected_application_reviews_sha256", "observed_artifact_sha256s", "observed_pins",
    "evidence_artifacts"}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _descriptor(value):
    value = cohorts._freeze(value)
    contracts.require_keys(value, {"snapshot_id", "use_scope", "generation",
                                  "previous_snapshot_manifest_ref"}, "genesis descriptor")
    auth._id(value["snapshot_id"], "snapshot identity")
    contracts.require_int(value["generation"], "genesis generation", minimum=1, maximum=1)
    if (value["use_scope"] != "candidate_source_context_answers"
            or value["previous_snapshot_manifest_ref"] is not None):
        _fail("only candidate-answer genesis without a predecessor is supported")
    return value


def _entry(value):
    contracts.require_keys(value, _ENTRY_FIELDS, "legacy application input")
    contracts.require_keys(value["assessment_inputs"], _INPUT_FIELDS, "application assessment inputs")
    evidence = adjudication._evidence(value["assessment_inputs"]["evidence_artifacts"])
    result = cohorts._freeze({key: item for key, item in value.items() if key != "assessment_inputs"})
    inputs = cohorts._freeze({key: item for key, item in value["assessment_inputs"].items()
                             if key != "evidence_artifacts"})
    auth._id(result["bank_id"], "application bank identity")
    contracts.require_int(result["request_ordinal"], "application request ordinal", maximum=cohorts.MAX_REQUESTS - 1)
    auth._trust(result["application_registry"], result["application_policy"],
        inputs["expected_application_registry_sha256"], inputs["expected_application_policy_sha256"],
        action=ACTION, audience=AUDIENCE)
    claims = result["application_reviews"]
    contracts.require_sha256(inputs["expected_application_reviews_sha256"], "application reviews SHA256")
    if (type(claims) is not list or len(claims) > auth.MAX_REVIEWS
            or auth.digest(claims) != inputs["expected_application_reviews_sha256"]):
        _fail("independently pinned application claims differ")
    identity = inputs["declaration_artifact_id"]
    if identity is None:
        if inputs["expected_declaration_sha256"] is not None or claims:
            _fail("absent application requires absent declaration pin and no claims")
    else:
        auth._id(identity, "application declaration identity")
        contracts.require_sha256(inputs["expected_declaration_sha256"], "application declaration SHA256")
        if identity in evidence and len(evidence[identity]) > contracts.MAX_RECORD_BYTES:
            _fail("application declaration exceeds record bound")
    result["assessment_inputs"] = {**inputs, "evidence_artifacts": evidence}
    size = len(auth.wire({**result, "assessment_inputs": inputs})) + sum(map(len, evidence.values()))
    if size > MAX_APPLICATION_BYTES:
        _fail("application input byte bound exceeded")
    return result, size


def _commitment(entry):
    inputs = entry["assessment_inputs"]
    return {**entry, "assessment_inputs": {**inputs, "evidence_artifacts": {
        name: {"sha256": adjudication._sha(raw), "bytes": len(raw)}
        for name, raw in inputs["evidence_artifacts"].items()}}}


def legacy_source_application_input_sha256(entry):
    """Commit complete metadata and exact raw evidence without running replay."""
    checked, _ = _entry(entry)
    return auth.digest(_commitment(checked))


def _entries(values, expected_hashes):
    hashes = cohorts._freeze(expected_hashes)
    if (type(values) is not list or not 0 < len(values) <= cohorts.MAX_REQUESTS
            or type(hashes) is not list or len(values) != len(hashes)):
        _fail("bounded complete ordered application population required")
    result, total = [], 0
    for value, expected in zip(values, hashes, strict=True):
        contracts.require_sha256(expected, "application input SHA256")
        item, size = _entry(value)
        total += size
        if total > MAX_APPLICATION_BYTES:
            _fail("aggregate application input byte bound exceeded")
        if auth.digest(_commitment(item)) != expected:
            _fail("independently pinned complete application input differs")
        result.append(item)
    return result, hashes


def _context(cohort, banks, adjudications, expected_population,
             expected_population_sha256, expected_cohort_sha256, expected_adjudication_assessment_sha256s):
    # Detach before replay so the following same-time checks consume exactly
    # the identities and bytes that were independently bound and regenerated.
    checked_cohort = contracts.clone_json(cohort)
    detached, population = cohorts._inputs(banks, expected_population, expected_population_sha256)
    items = cohorts._adjudications(adjudications, expected_adjudication_assessment_sha256s, detached)
    batch = cohorts.assess_legacy_source_cohort_adjudications(checked_cohort, detached, items,
        expected_population=population, expected_population_sha256=expected_population_sha256,
        expected_cohort_sha256=expected_cohort_sha256,
        expected_adjudication_assessment_sha256s=expected_adjudication_assessment_sha256s)
    contexts, index = [], 0
    for bank in detached:
        for ordinal, member in enumerate(bank["requests"]):
            contexts.append({"bank": bank, "member": member, "adjudication": items[index],
                "prior_result": batch["request_results"][index], "request_ordinal": ordinal,
                "request": bank["preparation"]["requests"][ordinal],
                "subject": bank["preparation"]["subjects"][ordinal],
                "manifest": bank["preparation"]["dependency_manifests"][ordinal]})
            index += 1
    return checked_cohort, batch, contexts


def _declaration(cohort, batch, context, descriptor, declared_at_utc, rationale, evidence_refs):
    declared = auth._time(declared_at_utc)
    contracts.require_text(rationale, "application rationale", max_bytes=8192)
    refs = contracts.clone_json(evidence_refs)
    responses._refs(refs)
    if not refs:
        _fail("application requires explicit supporting evidence")
    item = context["adjudication"]
    report = item["assessment"]
    earlier = report["declaration_record"]
    if earlier is None or any(choice["decision"] != "select_existing_variant" for choice in earlier["decisions"]):
        _fail("genesis application requires all nine existing resolved adjudication choices")
    times = [row["evaluation_time_utc"] for row in batch["request_results"]]
    times += [earlier["declared_at_utc"]] + [row["issued_at_utc"] for row in item["adjudication_reviews"]]
    if any(declared < auth._time(time) for time in times):
        _fail("application declaration predates its considered adjudication cohort")
    return contracts.seal_record({"schema": DECLARATION_SCHEMA, "profile": PROFILE,
        "cohort_ref": responses._ref(cohort), "expected_population_sha256": cohort["expected_population_sha256"],
        "cohort_adjudication_assessment_sha256": auth.digest(batch),
        "bank_id": context["bank"]["bank_id"], "request_ordinal": context["request_ordinal"],
        "request_ref": responses._ref(context["request"]), "subject_ref": responses._ref(context["subject"]),
        "original_adjudication_assessment_sha256": auth.digest(report),
        "adjudication_declaration_ref": responses._ref(earlier),
        "typed_assessment_sha256": auth.digest(context["member"]["typed_assessment"]),
        "active_slot_ids": list(context["request"]["context_slot_ids"]),
        "selected_answer_variant_refs": [choice["selected_variant_ref"] for choice in earlier["decisions"]],
        "descriptor": descriptor, "effect": EFFECT, "declared_at_utc": declared_at_utc,
        "rationale": rationale, "evidence_refs": refs,
        "deferred_review_slot_ids": context["request"]["deferred_review_slot_ids"],
        "view": "candidate", **FALSE_FLAGS, **source._UNSELECTED})


def record_legacy_source_application_declaration(cohort, banks, adjudications, descriptor, *,
        bank_id, request_ordinal, declared_at_utc, rationale, evidence_refs,
        expected_population, expected_population_sha256, expected_cohort_sha256,
        expected_adjudication_assessment_sha256s):
    """Author supplied copying intent after replay; create no keys or authority."""
    descriptor = _descriptor(descriptor)
    auth._id(bank_id, "selected application bank")
    contracts.require_int(request_ordinal, "selected application ordinal", maximum=cohorts.MAX_REQUESTS - 1)
    cohort, batch, contexts = _context(cohort, banks, adjudications, expected_population,
        expected_population_sha256, expected_cohort_sha256, expected_adjudication_assessment_sha256s)
    context = next((row for row in contexts if row["bank"]["bank_id"] == bank_id
                    and row["request_ordinal"] == request_ordinal), None)
    if context is None:
        _fail("application member absent from complete declared cohort")
    return _declaration(cohort, batch, context, descriptor, declared_at_utc, rationale, evidence_refs)


def validate_legacy_source_application_declaration(record, *args, **kwargs):
    checked = contracts.clone_json(record)
    if not cohorts._same(checked, record_legacy_source_application_declaration(*args, **kwargs)):
        _fail("legacy application declaration differs from exact regeneration")
    return checked


def _content(entry, cohort, batch, context, descriptor):
    inputs = entry["assessment_inputs"]
    identity = inputs["declaration_artifact_id"]
    if identity is None:
        return None, []
    evidence = inputs["evidence_artifacts"]
    try:
        record = contracts.load_record_bytes(evidence.get(identity),
            expected_sha256=inputs["expected_declaration_sha256"])
        expected = _declaration(cohort, batch, context, descriptor, record["declared_at_utc"],
                                record["rationale"], record["evidence_refs"])
        if not cohorts._same(record, expected):
            _fail("application cohort, source, choices or copying effect differs")
        for ref in record["evidence_refs"]:
            body = evidence.get(ref["artifact_id"])
            if ref["artifact_id"] == identity or body is None or adjudication._sha(body) != ref["sha256"]:
                _fail("application supporting evidence missing, changed or self-referential")
        variants = {row["record_cid"]: row for row in context["member"]["typed_assessment"]["answer_variants"]}
        common = {"artifact_id": identity, "sha256": inputs["expected_declaration_sha256"]}
        closure = {"status": "declared_complete", "unresolved": [], "obligations": [
            {"slot_id": slot, "disposition": responses.DISPOSITIONS[variants[ref["record_cid"]]["answer"]["disposition"]],
             "evidence_refs": [common]} for slot, ref in zip(record["active_slot_ids"],
                                                            record["selected_answer_variant_refs"], strict=True)]}
        if any(not cohorts._same(claim["context_closure"], closure) for claim in entry["application_reviews"]):
            _fail("application claims must bind the same complete nine-choice body")
        return record, []
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
        return None, [str(error)[:512] or "invalid_application_content"]


def _matches(entry, cohort):
    keys = {row["key_id"]: row for row in entry["application_registry"]["keys"]}
    matches = []
    for claim in entry["application_reviews"]:
        key = keys.get(claim["key_id"])
        reasons = []
        for field, excluded in (("principal_id", "excluded_principal_ids"), ("signer_did", "excluded_signer_dids")):
            if claim[field] in cohort[excluded] or key is not None and key[field] in cohort[excluded]:
                reasons.append(field)
        if key is not None and key["public_key_hex"] in cohort["excluded_public_keys"]:
            reasons.append("public_key")
        if reasons:
            matches.append({"review_id": claim["review_id"], "identity_kinds": reasons})
    return matches


def assess_legacy_source_applications(cohort, banks, adjudications, applications, descriptor, *,
        expected_population, expected_population_sha256, expected_cohort_sha256,
        expected_adjudication_assessment_sha256s, expected_application_input_sha256s, at_time_utc):
    """Copy nine references or none, with complete same-time upstream checks.

    Signatures authorize the exact immutable original cohort and answer choices.
    Fresh authority evaluations are separately retained and hashed here; earlier
    signed bodies and assessments are never relabeled with the new time.
    """
    descriptor = _descriptor(descriptor)
    evaluation = auth._time(at_time_utc)
    applications, hashes = _entries(applications, expected_application_input_sha256s)
    cohort, batch, contexts = _context(cohort, banks, adjudications, expected_population,
        expected_population_sha256, expected_cohort_sha256, expected_adjudication_assessment_sha256s)
    if len(applications) != len(contexts):
        _fail("every declared cohort member requires an application disposition")
    if any(evaluation < auth._time(row["evaluation_time_utc"]) for row in batch["request_results"]):
        _fail("application evaluation predates its original adjudication cohort")
    results = []
    for entry, context in zip(applications, contexts, strict=True):
        bank, member, item = context["bank"], context["member"], context["adjudication"]
        ordinal = context["request_ordinal"]
        if entry["bank_id"] != bank["bank_id"] or entry["request_ordinal"] != ordinal:
            _fail("application population moved across declared cohort members")
        inputs = entry["assessment_inputs"]
        current = adjudication.assess_legacy_source_adjudication(bank["preparation"], member["typed_assessment"],
            bank["source_registry"], bank["source_policy"], member["source_reviews"],
            item["adjudication_registry"], item["adjudication_policy"], item["adjudication_reviews"],
            expected_typed_assessment_sha256=auth.digest(member["typed_assessment"]),
            response_inputs=member["response_inputs"], **{**item["assessment_inputs"],
                "at_time_utc": at_time_utc, "observed_artifact_sha256s": inputs["observed_artifact_sha256s"],
                "observed_pins": inputs["observed_pins"]})
        authority = auth._assess_reviews(context["subject"], entry["application_registry"],
            entry["application_policy"], entry["application_reviews"], context["manifest"], domain=_DOMAIN,
            expected_subject_sha256=auth.digest(context["subject"]),
            expected_manifest_sha256=context["manifest"]["manifest_sha256"],
            expected_registry_sha256=inputs["expected_application_registry_sha256"],
            expected_policy_sha256=inputs["expected_application_policy_sha256"],
            expected_reviews_sha256=inputs["expected_application_reviews_sha256"], at_time_utc=at_time_utc,
            observed_artifact_sha256s=inputs["observed_artifact_sha256s"], observed_pins=inputs["observed_pins"],
            evidence_artifacts=inputs["evidence_artifacts"])
        authority.pop("assessment_sha256")
        authority["coverage_scope"] = "legacy_genesis_answer_reference_copy_authority_only"
        authority["assessment_sha256"] = auth.digest(authority)
        record, content_blockers = _content(entry, cohort, batch, context, descriptor)
        matches = _matches(entry, cohort)
        extra = []
        if not context["prior_result"]["cohort_authority_prerequisites_satisfied"]:
            extra.append("original_cohort_adjudication_prerequisites_unsatisfied")
        if not current["authority_prerequisites_satisfied_under_selected_trust"]:
            extra.append("application_time_adjudication_or_source_prerequisites_unsatisfied")
        if matches:
            extra.append("application_signer_matches_declared_source_review_cohort")
        if cohort["counts"]["unknown_key_reviews"]:
            extra.append("source_cohort_public_key_inventory_incomplete")
        if record is not None:
            declared = auth._time(record["declared_at_utc"])
            if declared > evaluation:
                extra.append("application_declared_after_evaluation")
            if any(auth._time(row["issued_at_utc"]) < declared for row in entry["application_reviews"]):
                extra.append("application_claim_predates_common_declaration")
        activated = (record is not None and not content_blockers and not extra
                     and authority["review_prerequisites_satisfied_under_selected_trust"])
        identity = inputs["declaration_artifact_id"]
        results.append({"bank_id": bank["bank_id"], "request_ordinal": ordinal,
            "request_ref": responses._ref(context["request"]),
            "original_adjudication_assessment_sha256": auth.digest(item["assessment"]),
            "original_cohort_authority_prerequisites_satisfied": context["prior_result"]["cohort_authority_prerequisites_satisfied"],
            "current_adjudication_assessment": current, "current_adjudication_assessment_sha256": auth.digest(current),
            "authority_assessment": authority,
            "declaration_artifact_ref": None if identity is None else
                {"artifact_id": identity, "sha256": inputs["expected_declaration_sha256"]},
            "observed_declaration_sha256": None if identity not in inputs["evidence_artifacts"] else
                adjudication._sha(inputs["evidence_artifacts"][identity]),
            "declaration_record": record, "declaration_content_status": "absent" if identity is None else
                "valid_declared_content" if record is not None else "rejected",
            "content_blockers": content_blockers, "exclusion_matches": matches,
            "separation_and_chronology_blockers": sorted(set(extra)),
            "source_answer_snapshot_activated_under_selected_profile": activated,
            "active_slot_ids": list(context["request"]["context_slot_ids"]),
            "activated_answer_variant_refs": record["selected_answer_variant_refs"] if activated else [],
            "deferred_review_slot_ids": context["request"]["deferred_review_slot_ids"],
            "decision_applied": False})
    report = {"schema": REPORT_SCHEMA, "profile": PROFILE, "descriptor": descriptor, "effect": EFFECT,
        "original_cohort_ref": responses._ref(cohort), "expected_population_sha256": expected_population_sha256,
        "original_cohort_adjudication_assessment_sha256": auth.digest(batch),
        "expected_application_input_sha256s": hashes, "evaluation_time_utc": at_time_utc,
        "request_results": results,
        "counts": {"banks": len(cohort["banks"]), "requests": len(results),
            "activated_requests": sum(row["source_answer_snapshot_activated_under_selected_profile"] for row in results),
            "activated_answer_references": sum(len(row["activated_answer_variant_refs"]) for row in results),
            "source_decisions_applied": 0, "physical_governing_bindings_applied": 0},
        "coverage_scope": "separately_authorized_candidate_answer_references_under_pinned_trust_only",
        "view": "candidate", **FALSE_FLAGS, **source._UNSELECTED}
    report["assessment_sha256"] = auth.digest(report)
    return cohorts._freeze(report)


def validate_legacy_source_applications(report, *args, **kwargs):
    checked = cohorts._freeze(report)
    if not cohorts._same(checked, assess_legacy_source_applications(*args, **kwargs)):
        _fail("legacy application assessment differs from exact regeneration")
    return checked


__all__ = ["legacy_source_application_input_sha256", "record_legacy_source_application_declaration",
           "validate_legacy_source_application_declaration", "assess_legacy_source_applications",
           "validate_legacy_source_applications"]

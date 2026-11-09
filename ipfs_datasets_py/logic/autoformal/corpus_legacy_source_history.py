"""Bounded, fully replayed legacy answer-snapshot history and fork refusal.

History is an explicitly supplied graph, not a discovered authoritative head.
Revision signatures authorize new logical answer references. Source geometry,
governing meaning, physical publication, training and proof remain separate.
"""
from __future__ import annotations

import hashlib
import json
import math

from . import corpus_contracts as contracts
from . import corpus_legacy_source_adjudication as adjudication
from . import corpus_legacy_source_application as application
from . import corpus_legacy_source_cohort as cohorts
from . import corpus_legacy_source_responses as responses
from . import corpus_legacy_source_review as source
from . import legal_graph_review as auth

PROFILE = "signed-legacy-source-answer-history/v1"
DECLARATION_SCHEMA = "legal-corpus-legacy-source-revision-declaration/v1"
CLAIM_SCHEMA = "legal-corpus-legacy-source-revision-signed-claim/v1"
ACTION = "revise_legacy_candidate_source_answer_snapshot/v1"
AUDIENCE = "legal-autoformalization-legacy-source-history/v1"
ASSESSMENT_SCHEMA = "legal-corpus-legacy-source-revision-authority-assessment/v1"
REVISION_REPORT_SCHEMA = "legal-corpus-legacy-source-revision-assessment/v1"
REPORT_SCHEMA = "legal-corpus-legacy-source-history-assessment/v1"
FALSE_FLAGS = {**application.FALSE_FLAGS, "history_head_authenticated": False,
               "external_history_inventory_exhaustive": False}
MAX_EPOCHS = 8
MAX_HISTORY_REQUESTS = 128
MAX_HISTORY_INPUT_BYTES = 512 * 1024**2
MAX_COMMITMENT_BYTES = 64 * 1024**2
MAX_INPUT_NODES = 2_000_000
_BYTES_TAG = "_legacy_history_raw_bytes_v1"
_DOMAIN = auth._ReviewDomain(source.SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE,
                             ASSESSMENT_SCHEMA, source._subject, 9)
_COMMON = {"cohort", "banks", "adjudications", "descriptor", "expected_population",
    "expected_population_sha256", "expected_cohort_sha256",
    "expected_adjudication_assessment_sha256s", "at_time_utc"}
_GENESIS = _COMMON | {"applications", "expected_application_input_sha256s"}
_REVISION = _COMMON | {"revisions", "expected_revision_input_sha256s"}
_ENTRY = {"bank_id", "request_ordinal", "revision_registry", "revision_policy",
          "revision_reviews", "assessment_inputs"}
_ENTRY_INPUTS = {"declaration_artifact_id", "expected_declaration_sha256",
    "expected_revision_registry_sha256", "expected_revision_policy_sha256",
    "expected_revision_reviews_sha256", "observed_artifact_sha256s", "observed_pins", "evidence_artifacts"}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _freeze(value):
    """Detach mixed JSON/raw bytes with bounded, unambiguous commitments."""
    count, raw_bytes, text_bytes = 0, 0, 0

    def visit(item, depth):
        nonlocal count, raw_bytes, text_bytes
        count += 1
        if depth > 64 or count > MAX_INPUT_NODES:
            _fail("history input structure bound exceeded")
        if type(item) is bytes:
            raw_bytes += len(item)
            if raw_bytes > MAX_HISTORY_INPUT_BYTES:
                _fail("history raw input byte bound exceeded")
            return item, {_BYTES_TAG: {"sha256": hashlib.sha256(item).hexdigest(), "bytes": len(item)}}
        if type(item) is dict:
            if any(type(key) is not str or key == _BYTES_TAG for key in item):
                _fail("history dictionary keys must be text outside the reserved byte-tag namespace")
            text_bytes += sum(len(key.encode("utf-8")) for key in item)
            if text_bytes > MAX_COMMITMENT_BYTES:
                _fail("history metadata byte bound exceeded")
            copied, committed = {}, {}
            for key, child in item.items():
                copied[key], committed[key] = visit(child, depth + 1)
            return copied, committed
        if type(item) is list:
            pairs = [visit(child, depth + 1) for child in item]
            return [pair[0] for pair in pairs], [pair[1] for pair in pairs]
        if type(item) is str:
            text_bytes += len(item.encode("utf-8"))
            if text_bytes > MAX_COMMITMENT_BYTES:
                _fail("history metadata byte bound exceeded")
        elif item is not None and type(item) not in (bool, int, float):
            _fail("history accepts only exact JSON values and immutable bytes")
        if type(item) is float and not math.isfinite(item):
            _fail("history nonfinite numbers are unsupported")
        return item, item

    detached, committed = visit(value, 0)
    raw = json.dumps(committed, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode("utf-8")
    if len(raw) > MAX_COMMITMENT_BYTES or len(raw) + raw_bytes > MAX_HISTORY_INPUT_BYTES:
        _fail("complete history input budget exceeded")
    return detached, hashlib.sha256(raw).hexdigest()


def legacy_source_history_step_sha256(step):
    """Commit the complete external step, including exact evidence byte hashes."""
    contracts.require_keys(step, {"epoch_id", "previous_epoch_id", "inputs"}, "revision step")
    return _freeze(step)[1]


def legacy_source_revision_input_sha256(entry):
    contracts.require_keys(entry, _ENTRY, "revision entry")
    contracts.require_keys(entry["assessment_inputs"], _ENTRY_INPUTS, "revision assessment inputs")
    return _freeze(entry)[1]


def _report_ref(report):
    return {"schema": report["schema"], "sha256": auth.digest(report)}


def _population(inputs):
    return [{"bank_id": bank["bank_id"], "preparation_sha256": auth.digest(bank["preparation"]),
        "request_refs": [responses._ref(row) for row in bank["preparation"]["requests"]],
        "subject_refs": [responses._ref(row) for row in bank["preparation"]["subjects"]]}
        for bank in inputs["banks"]]


def _request_count(inputs):
    banks = inputs.get("banks")
    if type(banks) is not list:
        _fail("history banks must be a complete list")
    count = 0
    for bank in banks:
        if type(bank) is not dict or type(bank.get("requests")) is not list:
            _fail("history bank requests must be a complete list")
        count += len(bank["requests"])
    return count


def _cohort_time(inputs, batch):
    if any(auth._time(inputs["at_time_utc"]) < auth._time(row["evaluation_time_utc"])
           for row in batch["request_results"]):
        _fail("revision evaluation predates its original adjudication cohort")


def _union(cohorts):
    result = {field: sorted({value for cohort in cohorts for value in cohort[field]})
              for field in ("excluded_principal_ids", "excluded_signer_dids", "excluded_public_keys")}
    result["counts"] = {"unknown_key_reviews": sum(c["counts"]["unknown_key_reviews"] for c in cohorts)}
    return result


def _context(inputs):
    return application._context(inputs["cohort"], inputs["banks"], inputs["adjudications"],
        inputs["expected_population"], inputs["expected_population_sha256"], inputs["expected_cohort_sha256"],
        inputs["expected_adjudication_assessment_sha256s"])


def _descriptor(value, parent):
    value = cohorts._freeze(value)
    contracts.require_keys(value, {"snapshot_id", "use_scope", "generation", "previous_snapshot_report_ref"},
                           "revision descriptor")
    prior = parent["report"]["descriptor"]
    contracts.require_int(value["generation"], "revision generation", minimum=2)
    if (value["snapshot_id"] != prior["snapshot_id"] or value["use_scope"] != prior["use_scope"]
            or value["generation"] != prior["generation"] + 1
            or not cohorts._same(value["previous_snapshot_report_ref"], parent["report_ref"])):
        _fail("revision must preserve the snapshot scope and name the exact next-generation predecessor")
    return value


def _revision_entries(inputs, contexts):
    values, pins = inputs["revisions"], inputs["expected_revision_input_sha256s"]
    if type(values) is not list or type(pins) is not list or len(values) != len(contexts) or len(pins) != len(values):
        _fail("complete ordered revision entry population required")
    results, total = [], 0
    for value, expected, context in zip(values, pins, contexts, strict=True):
        contracts.require_sha256(expected, "revision entry SHA256")
        if legacy_source_revision_input_sha256(value) != expected:
            _fail("independently pinned revision entry differs")
        contracts.require_int(value["request_ordinal"], "revision request ordinal", maximum=cohorts.MAX_REQUESTS - 1)
        if value["bank_id"] != context["bank"]["bank_id"] or value["request_ordinal"] != context["request_ordinal"]:
            _fail("revision entries moved across source requests")
        raw = value["assessment_inputs"]
        evidence = adjudication._evidence(raw["evidence_artifacts"])
        # Explicit internal vocabulary adapter; signed claims and evidence
        # bytes are never rewritten into the application signing domain.
        entry = {"bank_id": value["bank_id"], "request_ordinal": value["request_ordinal"],
            "application_registry": value["revision_registry"], "application_policy": value["revision_policy"],
            "application_reviews": value["revision_reviews"], "assessment_inputs": {
                key.replace("expected_revision_", "expected_application_"): item
                for key, item in raw.items() if key != "evidence_artifacts"}}
        entry["assessment_inputs"]["evidence_artifacts"] = evidence
        auth._trust(value["revision_registry"], value["revision_policy"],
            raw["expected_revision_registry_sha256"], raw["expected_revision_policy_sha256"],
            action=ACTION, audience=AUDIENCE)
        claims = value["revision_reviews"]
        if type(claims) is not list or len(claims) > auth.MAX_REVIEWS or auth.digest(claims) != raw["expected_revision_reviews_sha256"]:
            _fail("complete pinned revision claims required")
        identity = raw["declaration_artifact_id"]
        if identity is None:
            if raw["expected_declaration_sha256"] is not None or claims:
                _fail("absent revision requires absent hash and claims")
        else:
            auth._id(identity, "revision declaration identity")
            contracts.require_sha256(raw["expected_declaration_sha256"], "revision declaration hash")
            if identity in evidence and len(evidence[identity]) > contracts.MAX_RECORD_BYTES:
                _fail("revision declaration exceeds record bound")
        total += len(auth.wire(application._commitment(entry))) + sum(map(len, evidence.values()))
        if total > auth.MAX_BYTES:
            _fail("revision authority input byte bound exceeded")
        results.append(entry)
    return results


def _declaration(cohort, batch, context, descriptor, parent, epoch_id,
                 declared_at_utc, rationale, evidence_refs):
    if auth._time(declared_at_utc) < auth._time(parent["report"]["evaluation_time_utc"]):
        _fail("revision declaration predates predecessor evaluation")
    # Reuse the exact source/choice/chronology checks to author a NEW record.
    # No previously signed application record is retyped or modified.
    base = application._declaration(cohort, batch, context, descriptor,
                                     declared_at_utc, rationale, evidence_refs)
    previous = next(row for row in parent["report"]["request_results"]
        if row["bank_id"] == context["bank"]["bank_id"] and row["request_ordinal"] == context["request_ordinal"])
    values = {key: value for key, value in base.items() if key not in {"schema", "profile", "record_cid", "cid_scope"}}
    return contracts.seal_record({**values, "schema": DECLARATION_SCHEMA, "profile": PROFILE,
        "epoch_id": epoch_id, "previous_epoch_id": parent["epoch_id"],
        "previous_snapshot_report_ref": parent["report_ref"],
        "previous_request_result_sha256": auth.digest(previous), **FALSE_FLAGS})


def _content(entry, cohort, batch, context, descriptor, parent, epoch_id):
    inputs = entry["assessment_inputs"]
    identity, evidence = inputs["declaration_artifact_id"], inputs["evidence_artifacts"]
    if identity is None:
        return None, []
    try:
        record = contracts.load_record_bytes(evidence.get(identity), expected_sha256=inputs["expected_declaration_sha256"])
        expected = _declaration(cohort, batch, context, descriptor, parent, epoch_id,
            record["declared_at_utc"], record["rationale"], record["evidence_refs"])
        if not cohorts._same(record, expected):
            _fail("revision body differs from exact predecessor, source or selected answers")
        for ref in record["evidence_refs"]:
            body = evidence.get(ref["artifact_id"])
            if ref["artifact_id"] == identity or body is None or adjudication._sha(body) != ref["sha256"]:
                _fail("revision supporting evidence missing, changed or self-referential")
        variants = {row["record_cid"]: row for row in context["member"]["typed_assessment"]["answer_variants"]}
        common = {"artifact_id": identity, "sha256": inputs["expected_declaration_sha256"]}
        closure = {"status": "declared_complete", "unresolved": [], "obligations": [
            {"slot_id": slot, "disposition": responses.DISPOSITIONS[variants[ref["record_cid"]]["answer"]["disposition"]],
             "evidence_refs": [common]} for slot, ref in zip(record["active_slot_ids"], record["selected_answer_variant_refs"], strict=True)]}
        if any(not cohorts._same(claim["context_closure"], closure) for claim in entry["application_reviews"]):
            _fail("every revision claim must sign the same complete copying declaration")
        return record, []
    except (ValueError, TypeError, KeyError, IndexError, StopIteration, RecursionError) as error:
        return None, [str(error)[:512] or "invalid_revision_content"]


def _revision(step, parent, ancestors, population):
    inputs = step["inputs"]
    descriptor = _descriptor(inputs["descriptor"], parent)
    evaluation = auth._time(inputs["at_time_utc"])
    if evaluation < auth._time(parent["report"]["evaluation_time_utc"]):
        _fail("revision evaluation predates predecessor")
    if not cohorts._same(_population(inputs), population):
        _fail("source/preparation/request migration requires a different history profile")
    cohort, batch, contexts = _context(inputs)
    _cohort_time(inputs, batch)
    entries = _revision_entries(inputs, contexts)
    actors = _union([node["inputs"]["cohort"] for node in ancestors] + [cohort])
    results = []
    for entry, context in zip(entries, contexts, strict=True):
        bank, member, item = context["bank"], context["member"], context["adjudication"]
        params = entry["assessment_inputs"]
        current = adjudication.assess_legacy_source_adjudication(bank["preparation"], member["typed_assessment"],
            bank["source_registry"], bank["source_policy"], member["source_reviews"], item["adjudication_registry"],
            item["adjudication_policy"], item["adjudication_reviews"],
            expected_typed_assessment_sha256=auth.digest(member["typed_assessment"]), response_inputs=member["response_inputs"],
            **{**item["assessment_inputs"], "at_time_utc": inputs["at_time_utc"],
               "observed_artifact_sha256s": params["observed_artifact_sha256s"], "observed_pins": params["observed_pins"]})
        authority = auth._assess_reviews(context["subject"], entry["application_registry"], entry["application_policy"],
            entry["application_reviews"], context["manifest"], domain=_DOMAIN,
            expected_subject_sha256=auth.digest(context["subject"]), expected_manifest_sha256=context["manifest"]["manifest_sha256"],
            expected_registry_sha256=params["expected_application_registry_sha256"],
            expected_policy_sha256=params["expected_application_policy_sha256"], expected_reviews_sha256=params["expected_application_reviews_sha256"],
            at_time_utc=inputs["at_time_utc"], observed_artifact_sha256s=params["observed_artifact_sha256s"],
            observed_pins=params["observed_pins"], evidence_artifacts=params["evidence_artifacts"])
        authority.pop("assessment_sha256")
        authority["coverage_scope"] = "legacy_revision_answer_reference_copy_authority_only"
        authority["assessment_sha256"] = auth.digest(authority)
        record, content_blockers = _content(entry, cohort, batch, context, descriptor, parent, step["epoch_id"])
        matches = application._matches(entry, actors)
        adjudicator_matches = application._matches({"application_registry": item["adjudication_registry"],
            "application_reviews": item["adjudication_reviews"]}, actors)
        extra = []
        if not context["prior_result"]["cohort_authority_prerequisites_satisfied"]:
            extra.append("original_epoch_adjudication_prerequisites_unsatisfied")
        if not current["authority_prerequisites_satisfied_under_selected_trust"]:
            extra.append("revision_time_source_or_adjudication_prerequisites_unsatisfied")
        if matches or adjudicator_matches:
            extra.append("revision_or_adjudicator_matches_lineage_source_reviewers")
        if actors["counts"]["unknown_key_reviews"]:
            extra.append("lineage_source_key_inventory_incomplete")
        if record is not None:
            declared = auth._time(record["declared_at_utc"])
            if declared > evaluation:
                extra.append("revision_declared_after_evaluation")
            if any(auth._time(claim["issued_at_utc"]) < declared for claim in entry["application_reviews"]):
                extra.append("revision_claim_predates_declaration")
        activated = (record is not None and not content_blockers and not extra
                     and authority["review_prerequisites_satisfied_under_selected_trust"])
        results.append({"bank_id": bank["bank_id"], "request_ordinal": context["request_ordinal"],
            "request_ref": responses._ref(context["request"]),
            "original_adjudication_assessment_sha256": auth.digest(item["assessment"]),
            "current_adjudication_assessment": current, "current_adjudication_assessment_sha256": auth.digest(current),
            "authority_assessment": authority, "declaration_record": record,
            "declaration_artifact_ref": None if params["declaration_artifact_id"] is None else
                {"artifact_id": params["declaration_artifact_id"], "sha256": params["expected_declaration_sha256"]},
            "declaration_content_status": "absent" if params["declaration_artifact_id"] is None else
                "valid_declared_content" if record is not None else "rejected",
            "content_blockers": content_blockers, "exclusion_matches": matches,
            "adjudicator_exclusion_matches": adjudicator_matches, "separation_and_chronology_blockers": sorted(set(extra)),
            "source_answer_snapshot_activated_under_selected_profile": activated,
            "activated_answer_variant_refs": record["selected_answer_variant_refs"] if activated else [],
            "active_slot_ids": list(context["request"]["context_slot_ids"]),
            "deferred_review_slot_ids": context["request"]["deferred_review_slot_ids"], "decision_applied": False})
    report = {"schema": REVISION_REPORT_SCHEMA, "profile": PROFILE, "epoch_id": step["epoch_id"],
        "previous_epoch_id": parent["epoch_id"], "previous_snapshot_report_ref": parent["report_ref"],
        "descriptor": descriptor, "effect": application.EFFECT, "evaluation_time_utc": inputs["at_time_utc"],
        "cohort_ref": responses._ref(cohort), "expected_population_sha256": inputs["expected_population_sha256"],
        "cohort_adjudication_assessment_sha256": auth.digest(batch),
        "expected_revision_input_sha256s": inputs["expected_revision_input_sha256s"],
        "lineage_epoch_ids": [node["epoch_id"] for node in ancestors],
        "lineage_source_exclusion_sha256": auth.digest(actors), "request_results": results,
        "counts": {"requests": len(results), "activated_requests": sum(row["source_answer_snapshot_activated_under_selected_profile"] for row in results),
            "activated_answer_references": sum(len(row["activated_answer_variant_refs"]) for row in results),
            "source_decisions_applied": 0, "physical_governing_bindings_applied": 0},
        "view": "candidate", **FALSE_FLAGS, **source._UNSELECTED}
    report["assessment_sha256"] = auth.digest(report)
    return cohorts._freeze(report)


def _replay(genesis_report, genesis_inputs, revision_steps, genesis_epoch_id,
            expected_genesis_assessment_sha256, expected_revision_step_sha256s):
    auth._id(genesis_epoch_id, "genesis epoch identity")
    contracts.require_sha256(expected_genesis_assessment_sha256, "genesis assessment SHA256")
    if (type(revision_steps) is not list or len(revision_steps) >= MAX_EPOCHS
            or type(expected_revision_step_sha256s) is not list or len(revision_steps) != len(expected_revision_step_sha256s)):
        _fail("complete bounded independently pinned revision graph required")
    copied, _ = _freeze({"genesis_report": genesis_report, "genesis_inputs": genesis_inputs,
                         "steps": revision_steps, "pins": expected_revision_step_sha256s})
    genesis_report, genesis_inputs, steps, pins = (copied[key] for key in ("genesis_report", "genesis_inputs", "steps", "pins"))
    contracts.require_keys(genesis_inputs, _GENESIS, "genesis replay inputs")
    count = _request_count(genesis_inputs)
    seen_ids = {genesis_epoch_id}
    seen_inputs = set()
    for step, pin in zip(steps, pins, strict=True):
        contracts.require_sha256(pin, "revision step SHA256")
        if legacy_source_history_step_sha256(step) != pin:
            _fail("complete independently pinned revision graph differs")
        auth._id(step["epoch_id"], "revision epoch identity")
        auth._id(step["previous_epoch_id"], "previous epoch identity")
        if step["epoch_id"] in seen_ids or step["previous_epoch_id"] not in seen_ids:
            _fail("duplicate epoch or unknown/later predecessor")
        seen_ids.add(step["epoch_id"])
        contracts.require_keys(step["inputs"], _REVISION, "revision replay inputs")
        digest = _freeze(step["inputs"])[1]
        if digest in seen_inputs:
            _fail("one revision input root cannot be relabeled as multiple epochs")
        seen_inputs.add(digest)
        count += _request_count(step["inputs"])
    if count > MAX_HISTORY_REQUESTS:
        _fail("aggregate history request bound exceeded")
    if auth.digest(genesis_report) != expected_genesis_assessment_sha256:
        _fail("independently pinned genesis assessment differs")
    application.validate_legacy_source_applications(genesis_report, **genesis_inputs)
    population = _population(genesis_inputs)
    nodes = [{"epoch_id": genesis_epoch_id, "previous_epoch_id": None,
              "report": genesis_report, "report_ref": _report_ref(genesis_report), "inputs": genesis_inputs,
              "ancestor_ids": []}]
    by_id, roots = {genesis_epoch_id: nodes[0]}, {auth.digest(genesis_report)}
    for step in steps:
        parent = by_id[step["previous_epoch_id"]]
        ancestors = [by_id[name] for name in parent["ancestor_ids"]] + [parent]
        report = _revision(step, parent, ancestors, population)
        ref = _report_ref(report)
        if ref["sha256"] in roots:
            _fail("duplicate epoch report root")
        roots.add(ref["sha256"])
        node = {"epoch_id": step["epoch_id"], "previous_epoch_id": step["previous_epoch_id"],
                "report": report, "report_ref": ref, "inputs": step["inputs"],
                "ancestor_ids": parent["ancestor_ids"] + [parent["epoch_id"]]}
        nodes.append(node)
        by_id[node["epoch_id"]] = node
    return nodes, pins


def record_legacy_source_revision_declaration(genesis_report, genesis_inputs, revision_steps, revision_inputs, *,
        genesis_epoch_id, epoch_id, previous_epoch_id, bank_id, request_ordinal,
        expected_genesis_assessment_sha256, expected_revision_step_sha256s, declared_at_utc, rationale, evidence_refs):
    """Author new revision intent after complete predecessor replay, without signing."""
    auth._id(epoch_id, "new revision epoch identity")
    auth._id(previous_epoch_id, "selected predecessor identity")
    auth._id(bank_id, "revision bank identity")
    contracts.require_int(request_ordinal, "revision request ordinal", maximum=cohorts.MAX_REQUESTS - 1)
    # Bound the entire proposed graph before replay, including this unsigned
    # candidate. Separate per-node budgets would otherwise permit oversized
    # authoring inputs even though assessment would later refuse them.
    copied, _ = _freeze({"genesis_report": genesis_report, "genesis_inputs": genesis_inputs,
        "steps": revision_steps, "pins": expected_revision_step_sha256s, "candidate": revision_inputs})
    genesis_report, genesis_inputs, revision_steps, expected_revision_step_sha256s, inputs = (
        copied[key] for key in ("genesis_report", "genesis_inputs", "steps", "pins", "candidate"))
    contracts.require_keys(inputs, _REVISION, "unsigned revision replay inputs")
    if inputs["revisions"] != [] or inputs["expected_revision_input_sha256s"] != []:
        _fail("revision authoring requires empty unsubmitted authority inputs")
    if type(revision_steps) is not list or len(revision_steps) >= MAX_EPOCHS - 1:
        _fail("unsigned revision would exceed the complete history epoch bound")
    if _request_count(genesis_inputs) + _request_count(inputs) + sum(
            _request_count(step["inputs"]) for step in revision_steps) > MAX_HISTORY_REQUESTS:
        _fail("unsigned revision would exceed aggregate history request bound")
    nodes, _ = _replay(genesis_report, genesis_inputs, revision_steps, genesis_epoch_id,
                       expected_genesis_assessment_sha256, expected_revision_step_sha256s)
    if len(nodes) >= MAX_EPOCHS or epoch_id in {node["epoch_id"] for node in nodes}:
        _fail("new revision epoch duplicates or exceeds graph bound")
    parent = next((node for node in nodes if node["epoch_id"] == previous_epoch_id), None)
    if parent is None:
        _fail("revision predecessor absent from replayed graph")
    descriptor = _descriptor(inputs["descriptor"], parent)
    if auth._time(inputs["at_time_utc"]) < auth._time(parent["report"]["evaluation_time_utc"]):
        _fail("revision evaluation predates predecessor")
    if not cohorts._same(_population(inputs), _population(nodes[0]["inputs"])):
        _fail("revision source/preparation migration is unsupported")
    cohort, batch, contexts = _context(inputs)
    _cohort_time(inputs, batch)
    if auth._time(declared_at_utc) > auth._time(inputs["at_time_utc"]):
        _fail("revision declaration follows its evaluation")
    context = next((row for row in contexts if row["bank"]["bank_id"] == bank_id and row["request_ordinal"] == request_ordinal), None)
    if context is None:
        _fail("revision request absent from fixed source population")
    return _declaration(cohort, batch, context, descriptor, parent, epoch_id, declared_at_utc, rationale, evidence_refs)


def validate_legacy_source_revision_declaration(record, *args, **kwargs):
    checked = contracts.clone_json(record)
    if not cohorts._same(checked, record_legacy_source_revision_declaration(*args, **kwargs)):
        _fail("revision declaration differs from exact regeneration")
    return checked


def assess_legacy_source_history(genesis_report, genesis_inputs, revision_steps, *, genesis_epoch_id,
        current_epoch_id, at_time_utc, expected_genesis_assessment_sha256, expected_revision_step_sha256s):
    """Replay all supplied branches; expose current references only without forks."""
    auth._id(current_epoch_id, "current epoch identity")
    evaluation = auth._time(at_time_utc)
    nodes, pins = _replay(genesis_report, genesis_inputs, revision_steps, genesis_epoch_id,
                         expected_genesis_assessment_sha256, expected_revision_step_sha256s)
    current = next((node for node in nodes if node["epoch_id"] == current_epoch_id), None)
    parents = {node["previous_epoch_id"] for node in nodes if node["previous_epoch_id"] is not None}
    if current is None or current_epoch_id in parents:
        _fail("current epoch must explicitly select a supplied leaf")
    if auth._time(current["report"]["evaluation_time_utc"]) != evaluation:
        _fail("current leaf requires an exact current-time evaluation")
    if any(auth._time(node["report"]["evaluation_time_utc"]) > evaluation for node in nodes):
        _fail("history contains an epoch later than current evaluation")
    forks = [{"previous_epoch_id": node["epoch_id"],
              "child_epoch_ids": [child["epoch_id"] for child in nodes if child["previous_epoch_id"] == node["epoch_id"]]}
             for node in nodes]
    forks = [row for row in forks if len(row["child_epoch_ids"]) > 1]
    actors = _union([node["inputs"]["cohort"] for node in nodes])
    is_genesis = current["previous_epoch_id"] is None
    supplied = current["inputs"]["applications" if is_genesis else "revisions"]
    adjudications = current["inputs"]["adjudications"]
    current_rows = []
    for row, entry, item in zip(current["report"]["request_results"], supplied, adjudications, strict=True):
        prefix = "application" if is_genesis else "revision"
        matches = application._matches({"application_registry": entry[prefix + "_registry"],
                                        "application_reviews": entry[prefix + "_reviews"]}, actors)
        adjudicator_matches = application._matches({"application_registry": item["adjudication_registry"],
            "application_reviews": item["adjudication_reviews"]}, actors)
        blockers = []
        if is_genesis:
            blockers.append("fresh_revision_authorization_required")
        if forks:
            blockers.append("visible_history_fork_requires_separate_resolution")
        if not row["source_answer_snapshot_activated_under_selected_profile"]:
            blockers.append("selected_epoch_revision_prerequisites_unsatisfied")
        if matches or adjudicator_matches:
            blockers.append("current_actor_matches_all_epoch_source_reviewers")
        if actors["counts"]["unknown_key_reviews"]:
            blockers.append("all_epoch_source_key_inventory_incomplete")
        eligible = not blockers
        current_rows.append({"bank_id": row["bank_id"], "request_ordinal": row["request_ordinal"],
            "request_ref": row["request_ref"], "historical_result_sha256": auth.digest(row),
            "current_use_eligible": eligible, "active_answer_variant_refs": row["activated_answer_variant_refs"] if eligible else [],
            "blockers": blockers, "exclusion_matches": matches, "adjudicator_exclusion_matches": adjudicator_matches,
            "deferred_review_slot_ids": row["deferred_review_slot_ids"], "decision_applied": False})
    report = {"schema": REPORT_SCHEMA, "profile": PROFILE, "genesis_epoch_id": genesis_epoch_id,
        "current_epoch_id": current_epoch_id, "evaluation_time_utc": at_time_utc,
        "expected_genesis_assessment_sha256": expected_genesis_assessment_sha256,
        "expected_revision_step_sha256s": pins,
        "epochs": [{key: node[key] for key in ("epoch_id", "previous_epoch_id", "report_ref", "report")} for node in nodes],
        "forks": forks, "current_source_exclusion_sha256": auth.digest(actors), "current_request_results": current_rows,
        "counts": {"epochs": len(nodes), "revision_epochs": len(nodes) - 1, "requests": len(current_rows),
            "current_eligible_requests": sum(row["current_use_eligible"] for row in current_rows),
            "current_answer_references": sum(len(row["active_answer_variant_refs"]) for row in current_rows),
            "visible_fork_points": len(forks), "source_decisions_applied": 0, "physical_governing_bindings_applied": 0},
        "coverage_scope": "complete_supplied_history_with_independent_revision_authority_and_fork_refusal_only",
        "view": "candidate", **FALSE_FLAGS, **source._UNSELECTED}
    report["assessment_sha256"] = auth.digest(report)
    return cohorts._freeze(report)


def validate_legacy_source_history(report, *args, **kwargs):
    checked = cohorts._freeze(report)
    if not cohorts._same(checked, assess_legacy_source_history(*args, **kwargs)):
        _fail("legacy history differs from exact regeneration")
    return checked


__all__ = ["legacy_source_history_step_sha256", "legacy_source_revision_input_sha256",
           "record_legacy_source_revision_declaration", "validate_legacy_source_revision_declaration",
           "assess_legacy_source_history", "validate_legacy_source_history"]

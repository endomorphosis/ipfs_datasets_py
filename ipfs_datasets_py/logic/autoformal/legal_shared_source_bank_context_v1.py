"""Owner-minted immutable parsed-bank contexts for planned pure projections.

The genuine public shared-source validator replays original banks once before
minting. Contexts are private process-local immutable objects, never caller
inputs or portable authority. Projection does no legacy source-body parsing,
review/history execution, signing, source adoption or authority caching.
"""
from __future__ import annotations

import hashlib

from . import legal_shared_source_replay_v1 as shared
from . import legal_source_correspondence_requests_v1 as correspondence

SCHEMA = "legal-shared-source-bank-context/v1"
PROFILE = "owner-minted-immutable-bank-projections/v1"
GENERATION_SCHEMA = "legal-shared-source-bank-context-generation/v1"
DEFAULT_LIMITS = {**shared.DEFAULT_LIMITS, "max_context_bytes": 16 * 1024**2, "max_projection_count": 128}
AUTHORITY = {**shared.AUTHORITY, "parsed_bank_context_is_review_authority": False,
             "source_adoption_applied": False}
OWNER_RECIPE = {"schema": "legal-shared-source-bank-context-owner-recipe/v1",
    "mint_boundary": "genuine_public_shared_source_report_original_bound_validation/v1",
    "storage": "private_immutable_tagged_plain_JSON_tuple_tree/v1",
    "type_gate": "exact_private_type_operation_local_identity_registry_and_generation/v1",
    "projection": "complete_request_subject_dependencies_sections_physical_refs_detached/v1",
    "authority": "none_no_signed_review_history_or_source_adoption_cache/v1"}
LIMITATIONS = [
    "Opaque bank contexts are minted only within this operation after genuine public shared-source original-bound validation. No caller-supplied parsed dictionary, serialized context or saved report substitutes for that mint boundary.",
    "Immutable context payloads reuse already validated bank structures for planned pure projections only. No signature, trust, revocation, chronology, legal context or authority result is cached.",
    "Every planned request retains its complete original request, subject, dependency manifest, all bank source sections and all matching physical references/candidates. Equal logical data never collapses physical fanout or planned branches.",
    "Projection thaws immutable plain JSON into detached output; it does not parse original joins, paired rows or receipts. The original public validator still parses/replays each bank once per preparation; public report validation independently remints from originals.",
    "Planned epochs and context accesses are not executed review/history epochs. Existing raw/original, per-bank preparation and history limits are unchanged. No source, meaning, training, Lean or convergence authority follows.",
    "Type and registry gates describe cooperative Python custody, not attestation against arbitrary reflection, monkeypatching, native code or replacement of every independent original and pin. Source implementation custody belongs to the separately frozen execution environment.",
    "No runtime speedup, memory bound or token saving is established by projection counts. Raw source custody, immutable freezing, output thawing/serialization and closing checks remain work.",
]


class SharedSourceBankContextError(ValueError):
    """An original, generation, private context or full projection differs."""


def _need(condition, message):
    if not condition:
        raise SharedSourceBankContextError(message)


def _bounded(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except (shared.SharedSourceReplayError, correspondence.SourceCorrespondenceRequestsError) as error:
        raise SharedSourceBankContextError(str(error)) from error


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    return correspondence._wire(value)


def _limits(value):
    _need(value is None or type(value) is dict, "plain lower-only context limits required")
    _need(value is None or (len(value) <= len(DEFAULT_LIMITS) and all(type(key) is str for key in value)),
          "bounded plain context limit keys required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        _need(key in result and type(bound) is int and 0 < bound <= result[key],
              "unknown, raised or noninteger context limit")
        result[key] = bound
    return result


def _shared_limits(bounds):
    return {key: bounds[key] for key in shared.DEFAULT_LIMITS}


def _plain(value, bounds, maximum):
    return _bounded(shared._plain, value, bounds, maximum)


def _digest(value, label):
    return _bounded(correspondence._digest, value, label)


def _capture(shared_report, packet, source_request_raw, replay_request_raw, original_banks, bounds, offered=None):
    """Preflight the entire original/parsed/report graph before any hashing."""
    _need(type(shared_report) is dict and len(shared_report) <= 32 and
          all(type(key) is str for key in shared_report), "bounded plain shared report required")
    schedule = shared_report.get("schedule")
    _need(type(schedule) is dict and len(schedule) <= 8 and all(type(key) is str for key in schedule),
          "bounded complete planned schedule required")
    epochs = schedule.get("epochs")
    extra = {"shared_report": shared_report, "offered_report": offered}
    copied, frozen, _ = _bounded(shared._capture, original_banks, epochs, bounds,
        packet=packet, source_request_raw=source_request_raw, replay_request_raw=replay_request_raw, extra=extra)
    return copied, frozen


def _freeze(value):
    """Convert already bounded, validated plain JSON into immutable tuples."""
    if type(value) is dict:
        return ("d", tuple((key, _freeze(child)) for key, child in value.items()))
    if type(value) is list:
        return ("l", tuple(_freeze(child) for child in value))
    _need(value is None or type(value) in (str, int, bool), "validated immutable JSON scalar required")
    return ("v", value)


def _thaw(value):
    tag, content = value
    if tag == "d":
        return {key: _thaw(child) for key, child in content}
    if tag == "l":
        return [_thaw(child) for child in content]
    _need(tag == "v", "immutable JSON tag differs")
    return content


class _BankContext:
    """Private immutable payload; constructor is never a public mint API."""
    __slots__ = ("_context_id", "_generation", "_bank_id", "_bundle_raw", "_payloads", "_mint_token")

    def __new__(cls, *args, **kwargs):
        raise SharedSourceBankContextError("bank contexts require the private validated mint boundary")

    def __setattr__(self, name, value):
        raise SharedSourceBankContextError("bank context is immutable")

    def __delattr__(self, name):
        raise SharedSourceBankContextError("bank context is immutable")

    def __reduce__(self):
        raise SharedSourceBankContextError("bank contexts are process-local and nonserializable")

    def __reduce_ex__(self, protocol):
        raise SharedSourceBankContextError("bank contexts are process-local and nonserializable")


def _mint(bank, physical_references, generation_sha256, registry, mint_token):
    """Called only on banks returned by the genuine complete public validator."""
    raw = _wire(bank)
    digest = _sha(raw)
    identity = {"generation_sha256": generation_sha256, "bank_id": bank["bank_id"],
        "bank_ordinal": bank["bank_ordinal"], "bank_bundle_sha256": digest}
    context_id = "sha256:" + _sha(_wire(identity))
    preparation = bank["preparation"]
    sections = _freeze(preparation["source_sections"])
    payloads = []
    for ordinal, request in enumerate(preparation["requests"]):
        refs = [row for row in physical_references
            if row["bank_id"] == bank["bank_id"] and row["request_ordinal"] == ordinal]
        _need(refs, "every parsed logical request requires its complete physical references")
        payloads.append((_freeze(request), _freeze(preparation["subjects"][ordinal]),
            _freeze(preparation["dependency_manifests"][ordinal]), sections, _freeze(refs)))
    context = object.__new__(_BankContext)
    for key, value in (("_context_id", context_id), ("_generation", generation_sha256),
            ("_bank_id", bank["bank_id"]), ("_bundle_raw", raw), ("_payloads", tuple(payloads))):
        object.__setattr__(context, key, value)
    object.__setattr__(context, "_mint_token", mint_token)
    _need(id(context) not in registry, "context mint identity collision")
    # Local strong ownership prevents ID reuse during the operation. Registry
    # records immutable identity and payload objects, not external authority.
    registry[id(context)] = (context, context_id, generation_sha256, raw, context._payloads, mint_token, bank["bank_id"])
    refs = [row for row in physical_references if row["bank_id"] == bank["bank_id"]]
    descriptor = {"context_id": context_id, "bank_id": bank["bank_id"], "bank_ordinal": bank["bank_ordinal"],
        "generation_sha256": generation_sha256, "bank_bundle_sha256": digest, "bank_bundle_bytes": len(raw),
        "logical_requests": len(payloads), "physical_references": len(refs),
        "source_sections": len(preparation["source_sections"]),
        "candidate_occurrence_references": sum(row["candidate_count"] for row in refs)}
    return context, descriptor


def _project(context, scheduled, parent_epoch_id, generation_sha256, registry, mint_token):
    _need(type(context) is _BankContext, "exact private bank context type required")
    witness = registry.get(id(context))
    _need(witness is not None and witness[0] is context and witness[1] == context._context_id and
          witness[2] == context._generation == generation_sha256 and witness[3] is context._bundle_raw and
          witness[4] is context._payloads and witness[5] is context._mint_token is mint_token,
          "owner-minted context generation or payload differs")
    _need(witness[6] == context._bank_id, "minted context bank identity differs")
    _need(scheduled["bank_id"] == context._bank_id, "planned request selects another bank context")
    ordinal = scheduled["request_ordinal"]
    _need(type(ordinal) is int and 0 <= ordinal < len(context._payloads), "plain planned logical ordinal required")
    request, subject, manifest, sections, physical = (_thaw(value) for value in context._payloads[ordinal])
    _need([row["physical_row_ordinal"] for row in physical] == scheduled["physical_row_ordinals"],
          "complete planned physical fanout differs from minted bank")
    return {"epoch_id": scheduled["epoch_id"], "parent_epoch_id": parent_epoch_id,
        "bank_id": context._bank_id, "request_ordinal": ordinal, "context_id": context._context_id,
        "context_generation_sha256": generation_sha256, "request": request, "subject": subject,
        "dependency_manifest": manifest, "source_sections": sections, "physical_references": physical}


def prepare_shared_source_bank_context_v1(shared_report, packet, source_request_raw, replay_request_raw, *,
        expected_shared_report_sha256, expected_packet_sha256, expected_source_request_sha256,
        expected_replay_request_sha256, original_banks, limits=None):
    """Validate originals once, mint private contexts and project every plan row."""
    bounds = _limits(limits)
    copied, frozen = _capture(shared_report, packet, source_request_raw, replay_request_raw, original_banks, bounds)
    def fence():
        _need(_limits(limits) == bounds, "caller limits changed during bank context preparation")
        _need(_capture(shared_report, packet, source_request_raw, replay_request_raw, original_banks, bounds)[1] == frozen,
              "caller bank context originals changed")
        _need(_capture(copied["extra"]["shared_report"], copied["packet"], copied["source_request_raw"],
            copied["replay_request_raw"], copied["original_banks"], bounds)[1] == frozen,
            "detached bank context originals changed")
    failure = None
    try:
        _digest(expected_shared_report_sha256, "shared source report")
        offered_shared = copied["extra"]["shared_report"]
        offered_source = offered_shared.get("source_packet")
        _need(type(offered_source) is dict and type(offered_source.get("banks")) is list,
              "complete offered source bank payloads required")
        _plain(offered_source["banks"], bounds, bounds["max_context_bytes"])
        offered_requests = offered_shared["schedule"].get("requests")
        _need(type(offered_requests) is list and len(offered_requests) <= bounds["max_projection_count"],
              "complete offered projection count exceeds context bound")
        checked = shared.validate_shared_source_replay_v1(copied["extra"]["shared_report"], copied["packet"],
            copied["source_request_raw"], copied["replay_request_raw"],
            expected_report_sha256=expected_shared_report_sha256, expected_packet_sha256=expected_packet_sha256,
            expected_source_request_sha256=expected_source_request_sha256,
            expected_replay_request_sha256=expected_replay_request_sha256,
            original_banks=copied["original_banks"], limits=_shared_limits(bounds))
        generation = {"schema": GENERATION_SCHEMA, "owner_profile": PROFILE,
            "owner_recipe_sha256": _sha(_wire(OWNER_RECIPE)), "shared_report_sha256": expected_shared_report_sha256,
            "source_packet_sha256": expected_packet_sha256, "source_request_sha256": expected_source_request_sha256,
            "replay_request_sha256": expected_replay_request_sha256, "catalog_sha256": checked["catalog_sha256"],
            "schedule_sha256": checked["schedule_sha256"],
            "bank_commitments": checked["replay_request"]["bank_commitments"],
            "parser_profiles": dict(shared.PARSER_PROFILES),
            "owner_profiles": {"legal_shared_source_bank_context_v1": PROFILE,
                "legal_shared_source_replay_v1": shared.PROFILE,
                "legal_source_correspondence_requests_v1": correspondence.PROFILE,
                "corpus_legacy_source_review": "complete-legacy-stored-source-candidate-review/v1",
                "corpus_legacy_source_join": "pinned-parquet-text-column-as-stored/v1"},
            "source_view_profiles": [{"bank_id": bank["bank_id"], "source_versions": [
                {"record_cid": section["source_version"]["record_cid"],
                    "schema": section["source_version"]["schema"],
                    "media_type": section["source_version"]["raw_artifact"]["media_type"],
                    "extraction_profile": section["source_version"]["extracted_view"]["extraction_profile"],
                    "normalization_profile": section["source_version"]["extracted_view"]["normalization_profile"]}
                for section in bank["preparation"]["source_sections"]]}
                for bank in checked["source_packet"]["banks"]], "limits": bounds}
        generation_sha = _sha(_plain(generation, bounds, bounds["max_report_bytes"])[1])
        registry, contexts, descriptors, mint_token = {}, {}, [], object()
        source = checked["source_packet"]
        _plain(source["banks"], bounds, bounds["max_context_bytes"])
        _need(len(checked["schedule"]["requests"]) <= bounds["max_projection_count"],
              "complete planned projection count exceeds context bound")
        for bank in source["banks"]:
            context, descriptor = _mint(bank, source["physical_rows"], generation_sha, registry, mint_token)
            _need(bank["bank_id"] not in contexts, "duplicate validated bank context identity")
            contexts[bank["bank_id"]] = context
            descriptors.append(descriptor)
        parents = {row["epoch_id"]: row["parent_epoch_id"] for row in checked["schedule"]["epochs"]}
        projections = []
        for scheduled in checked["schedule"]["requests"]:
            _need(scheduled["bank_id"] in contexts, "planned bank has no validated minted context")
            projection = _project(contexts[scheduled["bank_id"]], scheduled, parents[scheduled["epoch_id"]], generation_sha, registry, mint_token)
            projections.append(projection)
            # Preserve the complete planned projection or refuse the byte/node
            # budget before growing to the next scheduled request.
            _plain(projections, bounds, bounds["max_report_bytes"])
        physical_total = sum(len(row["physical_references"]) for row in projections)
        candidate_total = sum(item["candidate_count"] for row in projections for item in row["physical_references"])
        report = {"schema": SCHEMA, "profile": PROFILE, "status": "complete_planned_bank_context_projections",
            "shared_report_sha256": expected_shared_report_sha256, "shared_report": checked,
            "context_generation": generation, "context_generation_sha256": generation_sha,
            "contexts": descriptors, "projections": projections,
            "coverage": {"contexts_minted": len(descriptors), "planned_epochs": len(parents),
                "projected_logical_requests": len(projections), "projected_physical_references": physical_total,
                "projected_candidate_occurrence_references": candidate_total,
                "original_physical_references": len(source["physical_rows"]),
                "original_candidate_occurrence_references": source["coverage"]["candidate_occurrence_references"],
                "full_declared_population_retained": True},
            "work": {"shared_report_validation_calls": 1, "source_bank_preparations": len(source["banks"]),
                "shared_bank_projection_reuse_implemented": True,
                "immutable_bank_context_mints": len(descriptors), "planned_context_accesses": len(projections),
                "legacy_bank_parses_during_projection": 0, "original_raw_body_parses_by_context_owner": 0,
                "history_epoch_replays": 0, "authority_cache_hits": 0},
            "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
            "inference_view": None, "limitations": list(LIMITATIONS)}
        return _plain(report, bounds, bounds["max_report_bytes"])[0]
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing bank context original/limit comparison also failed.")


def shared_source_bank_context_sha256(report, *, limits=None):
    """Bounded JSON report identity only; no contexts are minted or trusted."""
    bounds = _limits(limits)
    return _sha(_plain(report, bounds, bounds["max_report_bytes"])[1])


def validate_shared_source_bank_context_v1(report, shared_report, packet, source_request_raw, replay_request_raw, *,
        expected_report_sha256, expected_shared_report_sha256, expected_packet_sha256,
        expected_source_request_sha256, expected_replay_request_sha256, original_banks, limits=None):
    """Independently remint from originals and compare every detached projection."""
    bounds = _limits(limits)
    copied, frozen = _capture(shared_report, packet, source_request_raw, replay_request_raw, original_banks, bounds, report)
    def fence():
        _need(_limits(limits) == bounds, "caller limits changed during bank context validation")
        _need(_capture(shared_report, packet, source_request_raw, replay_request_raw, original_banks, bounds, report)[1] == frozen,
              "caller originals or offered bank context report changed")
        _need(_capture(copied["extra"]["shared_report"], copied["packet"], copied["source_request_raw"],
            copied["replay_request_raw"], copied["original_banks"], bounds, copied["extra"]["offered_report"])[1] == frozen,
            "detached bank context validation inputs changed")
    failure = None
    try:
        _digest(expected_report_sha256, "bank context report")
        checked, raw = _plain(copied["extra"]["offered_report"], bounds, bounds["max_report_bytes"])
        _need(_sha(raw) == expected_report_sha256, "independent bank context report SHA differs")
        expected = prepare_shared_source_bank_context_v1(copied["extra"]["shared_report"], copied["packet"],
            copied["source_request_raw"], copied["replay_request_raw"],
            expected_shared_report_sha256=expected_shared_report_sha256, expected_packet_sha256=expected_packet_sha256,
            expected_source_request_sha256=expected_source_request_sha256,
            expected_replay_request_sha256=expected_replay_request_sha256,
            original_banks=copied["original_banks"], limits=bounds)
        _need(_wire(expected) == raw, "bank context report differs from complete original-bound remint")
        return checked
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing bank context validation original/limit comparison also failed.")


__all__ = ["SharedSourceBankContextError", "prepare_shared_source_bank_context_v1",
    "shared_source_bank_context_sha256", "validate_shared_source_bank_context_v1"]

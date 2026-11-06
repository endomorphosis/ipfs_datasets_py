"""Bounded cross-source review nominations behind the existing review owner.

Complete replayed bundles are retained once. Attached evidence is namespaced by
both subjects and their exact bundles; a nomination grants no source or semantic
authority. These context responses are deliberately distinct from v1 responses.
No persistence, source acquisition, reviewer, signer or loader callback lives here.
"""

from __future__ import annotations

from collections import Counter

from . import legal_source_sampling_review as owner

SCHEMA = "legal-source-sampling-review-context/v1"
EVIDENCE_SCHEMA = "legal-source-sampling-attached-evidence/v1"
RESPONSE_SCHEMA = "legal-source-sampling-context-declaration/v1"
POPULATION_SCHEMA = "legal-source-sampling-context-population/v1"
DEFAULT_LIMITS = {
    "max_sources": 4,
    "max_attachments": 128,
    "max_subjects": 8192,
    "max_bundle_bytes": 64 * 1024 * 1024,
    # Source bundles + raw bytes + replay inputs + attachment nominations.
    # These and the separately bounded response collection are not a claim
    # about total process memory or all simultaneous JSON snapshots.
    "max_input_bytes": 96 * 1024 * 1024,
    "max_packet_bytes": 96 * 1024 * 1024,
    "max_responses": 256,
    "max_response_bytes": 1024 * 1024,
    "max_response_input_bytes": 96 * 1024 * 1024,
    # Existing sealed records use a 1 MiB contract. Do not silently truncate.
    "max_population_bytes": 1024 * 1024,
}
ATTACHMENT_FIELDS = {
    "target_bundle_sha256", "target_subject_ref",
    "supporting_bundle_sha256", "supporting_subject_ref", "role",
}
PACKET_FIELDS = {
    "schema", "limits", "sources", "attachments", "attachments_sha256",
    "counts", "status", "authority", "training_mask", "evaluation_gold_mask",
}
RESPONSE_FIELDS = {
    "schema", "context_sha256", "declaration_sha256", "declaration", "status",
    "authority", "training_mask", "evaluation_gold_mask", "record_cid", "cid_scope",
}


def _limits(value):
    owner._need(
        value is None or type(value) is dict and not (set(value) - set(DEFAULT_LIMITS)),
        "closed lowered context limits required",
    )
    result = dict(DEFAULT_LIMITS, **(value or {}))
    owner._need(
        all(type(v) is int and 0 < v <= DEFAULT_LIMITS[k] for k, v in result.items()),
        "positive lowered context limits required",
    )
    return result


def _subject(value):
    owner._keys(value, {"kind", "index", "sha256"}, "attached sampler subject")
    owner._need(
        type(value["kind"]) is str and value["kind"] in ("unit", "withheld_context")
        and type(value["index"]) is int and value["index"] >= 0,
        "exact typed attached subject required",
    )
    owner._sha(value["sha256"], "attached sampler subject")


def _guide(bundle, subject):
    owner._need(
        all(type(g) is dict and "subject_ref" in g for g in bundle["guides"]),
        "complete original guide records required",
    )
    matches = [g for g in bundle["guides"] if g["subject_ref"] == subject]
    owner._need(len(matches) == 1, "one exact attached subject in the pinned bundle required")
    return matches[0]


def _source_snapshot(sources, bounds):
    owner._need(
        type(sources) is list and 2 <= len(sources) <= bounds["max_sources"],
        "bounded complete target and supporting source list required",
    )
    result, remaining, subjects = [], bounds["max_input_bytes"], 0
    for entry in sources:
        owner._keys(entry, {"bundle", "raw", "expected_bundle_sha256", "replay_inputs"}, "context source")
        pin = entry["expected_bundle_sha256"]
        owner._sha(pin, "complete context source bundle")
        bundle = owner._copy(entry["bundle"], min(remaining, bounds["max_bundle_bytes"]))
        owner._keys(bundle, {"schema", "limits", "manifest", "sampling_report", "question_catalog", "guides"}, "complete context source bundle")
        owner._need(bundle["schema"] == owner.SCHEMA, "original review bundle schema required")
        owner._need(type(bundle["guides"]) is list, "complete source guides required")
        subjects += len(bundle["guides"])
        owner._need(subjects <= bounds["max_subjects"], "complete context subject bound exceeded")
        owner._need(owner._digest(bundle, bounds["max_bundle_bytes"]) == pin, "independent context bundle pin differs")
        replay = owner._copy(entry["replay_inputs"], 1024 * 1024)
        owner._need(type(replay) is dict and "expected_sampling_report_sha256" in replay, "complete source replay inputs required")
        sampling_pin = replay.pop("expected_sampling_report_sha256")
        detached = owner._input_snapshot(entry["raw"], sampling_pin, replay)
        replay = dict(detached, expected_sampling_report_sha256=sampling_pin)
        remaining -= len(owner._wire(bundle, bounds["max_bundle_bytes"]))
        remaining -= len(owner._wire(replay, 1024 * 1024)) + (len(entry["raw"]) if entry["raw"] is not None else 0)
        owner._need(remaining >= 0, "whole context source input byte bound exceeded before replay")
        result.append(dict(bundle=bundle, raw=entry["raw"], expected_bundle_sha256=pin, replay_inputs=replay))
    pins = [e["expected_bundle_sha256"] for e in result]
    owner._need(len(set(pins)) == len(pins), "duplicate complete context source bundles forbidden")
    return result, remaining


def _attachment_snapshot(attachments, pin, sources, bounds, remaining):
    owner._sha(pin, "ordered context attachments")
    owner._need(type(attachments) is list and 0 < len(attachments) <= bounds["max_attachments"], "bounded nonempty attachment nominations required")
    result = owner._copy(attachments, min(remaining, bounds["max_input_bytes"]))
    owner._need(owner._digest(result, bounds["max_input_bytes"]) == pin, "independent ordered attachment pin differs")
    by_pin = {s["expected_bundle_sha256"]: s["bundle"] for s in sources}
    hashes, used = set(), set()
    for item in result:
        owner._keys(item, ATTACHMENT_FIELDS, "context attachment nomination")
        for side in ("target", "supporting"):
            source_pin, subject = item[side + "_bundle_sha256"], item[side + "_subject_ref"]
            owner._sha(source_pin, "attached " + side + " bundle")
            _subject(subject)
            owner._need(source_pin in by_pin, "attachment names a foreign or missing source bundle")
            _guide(by_pin[source_pin], subject)
            used.add(source_pin)
        owner._need(item["target_bundle_sha256"] != item["supporting_bundle_sha256"], "context attachment requires distinct source bundles")
        owner._text(item["role"], "unreviewed attachment nomination role", maximum=128)
        digest = owner._digest(item)
        owner._need(digest not in hashes, "duplicate exact attachment nomination forbidden")
        hashes.add(digest)
    owner._need(used == set(by_pin), "every complete context bundle must be an explicit attachment endpoint")
    return result


def _assemble(sources, attachments, pin, bounds):
    retained = []
    for entry in sources:
        bundle = owner.validate_sampling_review_bundle(
            entry["bundle"], entry["raw"], expected_bundle_sha256=entry["expected_bundle_sha256"], **entry["replay_inputs"]
        )
        # v1 retains Python equality for compatibility. This profile requires
        # byte equality too, so false/0 and true/1 cannot be normalized away.
        owner._need(
            owner._wire(bundle, bounds["max_bundle_bytes"]) == owner._wire(entry["bundle"], bounds["max_bundle_bytes"]),
            "context source differs from canonical complete replay",
        )
        replay = entry["replay_inputs"]
        retained.append(dict(
            bundle_sha256=entry["expected_bundle_sha256"], bundle=bundle, replay_inputs=replay,
            raw_source=dict(sha256=replay["expected_raw_sha256"], bytes=replay["expected_raw_bytes"], available=entry["raw"] is not None),
        ))
    by_pin = {s["bundle_sha256"]: s["bundle"] for s in retained}
    attached, targets, supports = [], set(), set()
    remaining = bounds["max_packet_bytes"] - len(owner._wire(retained, bounds["max_packet_bytes"]))
    for item in attachments:
        target = _guide(by_pin[item["target_bundle_sha256"]], item["target_subject_ref"])
        support = _guide(by_pin[item["supporting_bundle_sha256"]], item["supporting_subject_ref"])
        nomination_sha = owner._digest(item)
        refs = [dict(schema=EVIDENCE_SCHEMA, nomination_sha256=nomination_sha, **item, evidence_ref=ref) for ref in support["evidence_refs"]]
        row = dict(nomination=item, nomination_sha256=nomination_sha, target_guide_ref=owner._ref(target), supporting_guide_ref=owner._ref(support), evidence_refs=refs)
        remaining -= len(owner._wire(row, max(0, remaining)))
        owner._need(remaining >= 0, "attached context output byte bound exceeded")
        attached.append(row)
        targets.add((item["target_bundle_sha256"], owner._digest(item["target_subject_ref"])))
        supports.add((item["supporting_bundle_sha256"], owner._digest(item["supporting_subject_ref"])))
    guides = [g for s in retained for g in s["bundle"]["guides"]]
    packet = dict(
        schema=SCHEMA, limits=bounds, sources=retained, attachments=attached, attachments_sha256=pin,
        counts=dict(sources=len(retained), attachments=len(attached), subjects=len(guides),
                    units=sum(g["subject_ref"]["kind"] == "unit" for g in guides),
                    withheld_contexts=sum(g["subject_ref"]["kind"] == "withheld_context" for g in guides),
                    target_subjects=len(targets), supporting_subjects=len(supports)),
        status="unreviewed_context_nominations_not_applicability_or_meaning",
        authority=dict(owner.FALSE_FLAGS), training_mask=0, evaluation_gold_mask=0,
    )
    owner._wire(packet, bounds["max_packet_bytes"])
    return packet


def prepare(sources, attachments, *, expected_attachments_sha256, limits=None):
    bounds = _limits(limits)
    checked, remaining = _source_snapshot(sources, bounds)
    nominations = _attachment_snapshot(attachments, expected_attachments_sha256, checked, bounds, remaining)
    # Full retained bundle bodies alone must fit before any owner is invoked.
    owner._wire([s["bundle"] for s in checked], bounds["max_packet_bytes"])
    return _assemble(checked, nominations, expected_attachments_sha256, bounds)


def packet_sha256(packet):
    owner._keys(packet, PACKET_FIELDS, "review context packet")
    bounds = _limits(packet["limits"])
    owner._need(packet["schema"] == SCHEMA, "distinct review context schema required")
    return owner._digest(packet, bounds["max_packet_bytes"])


def validate(packet, sources, attachments, *, expected_context_sha256, expected_attachments_sha256, limits=None):
    owner._sha(expected_context_sha256, "complete review context packet")
    owner._keys(packet, PACKET_FIELDS, "review context packet")
    bounds = _limits(packet["limits"] if limits is None else limits)
    offered = owner._copy(packet, bounds["max_packet_bytes"])
    owner._need(packet_sha256(offered) == expected_context_sha256, "independent review context pin differs")
    expected = prepare(sources, attachments, expected_attachments_sha256=expected_attachments_sha256, limits=bounds)
    owner._need(owner._wire(offered, bounds["max_packet_bytes"]) == owner._wire(expected, bounds["max_packet_bytes"]), "context packet differs from complete sources and exact nominations")
    return expected


def _declaration(value, pin, bounds):
    owner._sha(pin, "original contextual declaration")
    result = owner._declaration_snapshot(value, bounds)
    owner._need(owner._digest(result, bounds["max_response_bytes"]) == pin, "independent original declaration pin differs")
    return result


def _response(value, declaration_pin, packet, context_pin, bounds):
    source_pin, subject = value["bundle_sha256"], value["subject_ref"]
    _subject(subject)
    source = [s for s in packet["sources"] if s["bundle_sha256"] == source_pin]
    owner._need(len(source) == 1, "context declaration target bundle required")
    nominations = [a for a in packet["attachments"] if a["nomination"]["target_bundle_sha256"] == source_pin and a["nomination"]["target_subject_ref"] == subject]
    owner._need(bool(nominations), "declaration subject must be a nominated context target")
    extras = [ref for a in nominations for ref in a["evidence_refs"]]
    owner._checked_declaration(value, source[0]["bundle"], source_pin, _extra_evidence_refs=extras)
    result = dict(schema=RESPONSE_SCHEMA, context_sha256=context_pin, declaration_sha256=declaration_pin,
                  declaration=value, status="recorded_unverified_context_declaration", authority=dict(owner.FALSE_FLAGS), training_mask=0, evaluation_gold_mask=0)
    owner._wire(result, bounds["max_response_bytes"])
    _, seal = owner._owners()
    result = seal(result)
    owner._wire(result, bounds["max_response_bytes"])
    return result


def _response_snapshot(response, pin, bounds):
    owner._sha(pin, "complete context response")
    owner._keys(response, RESPONSE_FIELDS, "separate context response")
    value = owner._copy(response, bounds["max_response_bytes"])
    owner._need(value["schema"] == RESPONSE_SCHEMA, "distinct context response schema required, no v1 downgrade")
    owner._need(owner._digest(value, bounds["max_response_bytes"]) == pin, "independent context response pin differs")
    return value


def _checked_response(offered, value, declaration_pin, packet, context_pin, bounds):
    expected = _response(value, declaration_pin, packet, context_pin, bounds)
    owner._need(owner._wire(offered, bounds["max_response_bytes"]) == owner._wire(expected, bounds["max_response_bytes"]), "context response differs from original declaration and packet")
    return expected


def record_response(packet, declaration, sources, attachments, *, expected_context_sha256, expected_declaration_sha256, expected_attachments_sha256, limits=None):
    bounds = _limits(packet.get("limits") if limits is None and type(packet) is dict else limits)
    value = _declaration(declaration, expected_declaration_sha256, bounds)
    checked = validate(packet, sources, attachments, expected_context_sha256=expected_context_sha256, expected_attachments_sha256=expected_attachments_sha256, limits=bounds)
    return _response(value, expected_declaration_sha256, checked, expected_context_sha256, bounds)


def validate_response(response, packet, declaration, sources, attachments, *, expected_response_sha256, expected_context_sha256, expected_declaration_sha256, expected_attachments_sha256, limits=None):
    bounds = _limits(packet.get("limits") if limits is None and type(packet) is dict else limits)
    offered = _response_snapshot(response, expected_response_sha256, bounds)
    value = _declaration(declaration, expected_declaration_sha256, bounds)
    checked = validate(packet, sources, attachments, expected_context_sha256=expected_context_sha256, expected_attachments_sha256=expected_attachments_sha256, limits=bounds)
    return _checked_response(offered, value, expected_declaration_sha256, checked, expected_context_sha256, bounds)


def summarize(packet, responses, sources, attachments, *, expected_context_sha256, expected_response_sha256s, expected_attachments_sha256, limits=None):
    bounds = _limits(packet.get("limits") if limits is None and type(packet) is dict else limits)
    owner._need(type(responses) is list and len(responses) <= bounds["max_responses"], "bounded complete context response list required")
    owner._need(type(expected_response_sha256s) is list and len(expected_response_sha256s) == len(responses), "one ordered independent context response pin required")
    offered, remaining = [], bounds["max_response_input_bytes"]
    for response, pin in zip(responses, expected_response_sha256s, strict=True):
        value = _response_snapshot(response, pin, bounds)
        remaining -= len(owner._wire(value, bounds["max_response_bytes"]))
        owner._need(remaining >= 0, "complete context response input byte bound exceeded")
        # A complete independently pinned response commits its exact declaration.
        _declaration(value["declaration"], value["declaration_sha256"], bounds)
        offered.append(value)
    owner._need(len(set(expected_response_sha256s)) == len(responses), "duplicate exact context responses forbidden")
    checked = validate(packet, sources, attachments, expected_context_sha256=expected_context_sha256, expected_attachments_sha256=expected_attachments_sha256, limits=bounds)
    accepted = [_checked_response(r, r["declaration"], r["declaration_sha256"], checked, expected_context_sha256, bounds) for r in offered]
    subjects = []
    for source in checked["sources"]:
        for guide in source["bundle"]["guides"]:
            selected = [r for r in accepted if r["declaration"]["bundle_sha256"] == source["bundle_sha256"] and r["declaration"]["subject_ref"] == guide["subject_ref"]]
            state, reasons = owner._population_state([r["declaration"] for r in selected])
            subjects.append(dict(bundle_sha256=source["bundle_sha256"], subject_ref=guide["subject_ref"], guide_ref=owner._ref(guide), state=state, reasons=reasons, response_refs=[owner._ref(r) for r in selected]))
    counts = dict.fromkeys(("pending", "disputed", "unsupported", "declarations_recorded"), 0)
    counts.update(Counter(s["state"] for s in subjects))
    result = dict(schema=POPULATION_SCHEMA, context_sha256=expected_context_sha256,
                  sources=[dict(bundle_sha256=s["bundle_sha256"], counts=s["bundle"]["manifest"]["counts"], source_status=s["bundle"]["manifest"]["source_status"]) for s in checked["sources"]],
                  subjects=subjects, counts=counts, subject_count=len(subjects), response_count=len(accepted), attachment_count=len(checked["attachments"]),
                  population_accounted=True, all_subjects_have_declarations=bool(subjects) and all(s["response_refs"] for s in subjects),
                  review_completed=False, adjudication_performed=False, latest_response_selected=False,
                  authority=dict(owner.FALSE_FLAGS), training_mask=0, evaluation_gold_mask=0)
    owner._wire(result, bounds["max_population_bytes"])
    _, seal = owner._owners()
    result = seal(result)
    owner._wire(result, bounds["max_population_bytes"])
    return result

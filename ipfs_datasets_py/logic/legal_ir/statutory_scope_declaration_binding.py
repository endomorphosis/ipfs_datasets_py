"""Join caller scope sidecars to archived statutory declarations, without admission.

The existing recorder and preflight retain physical custody and review status.
The existing scope and bridge validators own occurrence/connective/binder
transport. This boundary checks explicit maps between those distinct profiles;
it never guesses cues, aliases, clocks, references or legal meanings. Complete
raw context is retained or refused by the scope profile, never shortened.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from . import canonical_statement_scope as scope
from . import canonical_statement_scope_bridge as bridge
from . import statutory_declaration_preflight as preflight_owner
from . import statutory_review_recording as recorder
from . import statutory_source_review as sources

SCHEMA = "statutory-submission-scope-binding/v1"
SIDECAR_SCHEMA = "statutory-submission-scope-sidecar/v1"
GUIDE_SCHEMA = "statutory-submission-scope-binding-guide/v1"
VALIDATION_SCHEMA = "statutory-submission-scope-binding-validation/v1"
MAX_SIDECARS = sources.MAX_ROWS * recorder.MAX_SUBMISSIONS
MAX_QUALIFIER_MAPS = recorder.MAX_RULES * 16 * len(recorder.QUALIFIERS)
MAP_FIELDS = ("rule_bindings", "modality_bindings", "qualifier_bindings", "anchor_bindings", "attachment_bindings")
SIDECAR_FIELDS = {"schema", "binding_id", "packet_sha256", "submission_id", "submission_sha256",
                  "declaration_sha256", *recorder.ENVELOPE_FIELDS, "scope_input_sha256",
                  "scope_declaration", *MAP_FIELDS}
BINDING_STATUSES = ("pending_scope_declaration", "partial_binding", "profile_limit", "joined_declared_scope_only")
MAX_JSON_BYTES = sources.MAX_JSON_BYTES
DIGEST_RECIPE = sources.DIGEST_RECIPE


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    """Hash complete bounded ordinary JSON content, distinct from file bytes."""
    return recorder.digest(value)


def parse_json_bytes(raw):
    """Reject duplicate keys, non-UTF8 and floating/nonordinary JSON input."""
    return recorder.parse_json_bytes(raw)


def _detach(value):
    return parse_json_bytes(sources._wire(value))


def _seal(value):
    return {**value, "content_sha256": digest(value)}


def _false():
    return {**recorder._false(), **scope._FALSE,
            "target_eligibility": False, "declared_consistency_is_legal_correctness": False,
            "symbolic_aliases_inferred": False, "cross_references_resolved": False,
            "Boolean_scope_inferred": False, "modality_cues_inferred": False,
            "statement_scope_synthesized": False, "formal_output_lowered": False,
            "scope_declaration_truth_verified": False, "review_status_promoted": False,
            "formalized": False, "native_lowering_performed": False,
            "temporal_origin_resolved": False, "binder_roles_inferred": False,
            "trigger_to_rule_linkage_assessed": False, "scope_binding_authorizes_lowering": False}


def _masks():
    return sources._masks()


def _setup(packet, submissions, expected, resolver, recording, preflight):
    packet, submissions = _detach(packet), _detach(submissions)
    options = {"expected_packet_sha256": expected, "artifact_resolver": resolver}
    if recording is None:
        recording = recorder.record_reviews(packet, submissions, **options)
    else:
        recording = _detach(recording)
    recorder.validate_recording(recording, packet, submissions, **options)
    if preflight is None:
        preflight = preflight_owner.preflight_declarations(packet, submissions, recording=recording, **options)
    else:
        preflight = _detach(preflight)
    preflight_owner.validate_preflight(preflight, packet, submissions, recording=recording, **options)
    contexts = {row["artifact"]["sha256"]: row for row in packet["context_views"]}
    return packet, submissions, recording, preflight, contexts


def _request(item, contexts):
    ref = item["context"]["artifact"]
    context = contexts[ref["sha256"]]
    _require(context["artifact"] == ref and context["normalization"] == "identity"
             and context["complete_raw_section"] is True, "complete physical context differs")
    return {"source_text": item["input"]["source_text"],
            "context": {"role": "declared_context", "text": context["text"],
                        "bindings": {}, "sha256": ref["sha256"]}}


def _limits(request, declaration=None, rules=None):
    limits = []
    if len(request["source_text"]) > 16384:
        limits.append("selected_source_character_limit")
    if len(request["context"]["text"]) > 16384:
        limits.append("complete_raw_context_character_limit")
    if rules is not None and len(rules) > scope.MAX_RULES:
        limits.append("recorded_rule_count_exceeds_scope_profile")
    for value, label in ((request, "request"), (declaration, "declaration")):
        if value is None:
            continue
        try:
            scope._raw(value)
        except ValueError as error:
            if str(error) == "scope payload exceeds bridge byte bound; no truncation":
                limits.append(label + "_byte_limit")
            elif str(error) == "scope JSON node/depth bound exceeded":
                limits.append(label + "_scope_JSON_node_or_depth_limit")
            else:
                raise
    return limits


def _slot(item, request, expected, entry=None):
    return {"schema": SIDECAR_SCHEMA, "binding_id": None, "packet_sha256": expected,
            **recorder._envelope(item), "scope_input_sha256": digest(request),
            "submission_id": None if entry is None else entry["submission_id"],
            "submission_sha256": None if entry is None else entry["submission_sha256"],
            "declaration_sha256": None if entry is None else entry["declaration_sha256"],
            "scope_declaration": None, **dict.fromkeys(MAP_FIELDS)}


def _closing(initial, packet, submissions, expected, resolver, recording, preflight):
    closing = _setup(packet, submissions, expected, resolver, recording, preflight)
    _require(all(sources._wire(a) == sources._wire(b) for a, b in zip(initial[:4], closing[:4], strict=True)),
             "packet/review/source closure changed across scope binding")


def prepare_binding_slots(packet, reviewed_submissions, *, expected_packet_sha256, artifact_resolver,
                          recording=None, preflight=None):
    """Prepare null caller slots; neither source scopes nor reviews are invented.

    Full-context request limits are diagnostic. An oversized request is not
    exported as a truncated scope view; its complete content digest and exact
    physical artifact remain bound. Supplied record/preflight values are replayed.
    """
    setup = _setup(packet, reviewed_submissions, expected_packet_sha256, artifact_resolver, recording, preflight)
    packet, submissions, recording, preflight, contexts = setup
    rows = []
    by_item = {item["item_id"]: item for item in preflight["items"]}
    for item in packet["items"]:
        request = _request(item, contexts)
        limits = _limits(request)
        reviewed = by_item[item["item_id"]]
        rows.append({**recorder._envelope(item), "source_input": deepcopy(item["input"]),
                     "review_recording_status": reviewed["recording_status"],
                     "declared_dispute_present": reviewed["declared_dispute_present"],
                     "scope_request": None if limits else request, "scope_input_sha256": digest(request),
                     "complete_context_characters": len(request["context"]["text"]),
                     "request_profile_limits": limits, "unsubmitted_binding_slot": _slot(item, request, expected_packet_sha256),
                     "submission_slots": [{"review_status": entry["status"], "review_complete": entry["complete"],
                                            "binding_profile_limits": _limits(request, rules=entry["declaration"]["review"]["normative_rules"]),
                                            "slot": _slot(item, request, expected_packet_sha256, entry)}
                                           for entry in reviewed["received_declarations"]],
                     "admission_masks": _masks(), **_false()})
    _closing(setup, packet, submissions, expected_packet_sha256, artifact_resolver, recording, preflight)
    return _seal({"schema": GUIDE_SCHEMA, "packet_sha256": expected_packet_sha256,
                  "recording_sha256": digest(recording), "preflight_sha256": digest(preflight),
                  "items": rows, "item_count": len(rows), "submission_count": len(submissions),
                  "completed_scope_declarations_generated": 0, "scope_profile": scope.PROFILE,
                  "instructions": {
                      "context": "Use the exact complete raw context; profile limits cannot be repaired by truncation or none_required.",
                      "maps": "Supply ordered rule/modality maps, qualifier-index to exact leaf paths, and every original anchor/attachment map.",
                      "leaf_order": "Qualifiers retain leaf order: local qualifier trees first, then shared attachments in inner-to-outer statement traversal. This is a transport convention, not a legal equivalence claim.",
                      "scope": "Supply your own cue, connective, shared qualifier and binder declarations. No legal interpretation is inferred.",
                      "partial": "Null is unanswered. Explicit empty maps are assessed when a complete sidecar is supplied.",
                      "trigger": "The archival trigger list has no rule association; it is preserved with linkage unassessed.",
                      "authority": "Structural transport, agreement and caller hashes do not authenticate human review or admit targets."},
                  "admission_masks": _masks(), **_false()})


def _maps(sidecar):
    specifications = {
        "rule_bindings": ({"rule_index", "scope_rule_id"}, recorder.MAX_RULES),
        "modality_bindings": ({"rule_index", "scope_occurrence_id"}, recorder.MAX_RULES),
        "qualifier_bindings": ({"rule_index", "facet", "qualifier_index", "scope_leaf_path"}, MAX_QUALIFIER_MAPS),
        "anchor_bindings": ({"anchor_id", "scope_occurrence_id"}, recorder.MAX_ANCHORS),
        "attachment_bindings": ({"attachment_id", "scope_path"}, recorder.MAX_ANCHORS),
    }
    for field, (fields, cap) in specifications.items():
        rows = sidecar[field]
        if rows is None:
            continue
        _require(type(rows) is list and len(rows) <= cap, "bounded " + field + " required")
        for row in rows:
            sources._closed(row, fields, field + " row")
            for key, value in row.items():
                if key in ("rule_index", "qualifier_index"):
                    sources._integer(value, key)
                elif key == "facet":
                    _require(type(value) is str and value in recorder.QUALIFIERS, "known qualifier map facet required")
                else:
                    sources._text(value, key, 256)


def _header(sidecar, item, entry, request, expected):
    sources._closed(sidecar, SIDECAR_FIELDS, "statutory scope sidecar")
    _require(sidecar["schema"] == SIDECAR_SCHEMA, "scope sidecar schema differs")
    sources._text(sidecar["binding_id"], "binding_id", 256)
    _require(sidecar["packet_sha256"] == expected, "scope sidecar packet binding differs")
    _require(all(sidecar[k] == entry[k] for k in ("submission_id", "submission_sha256", "declaration_sha256")),
             "scope sidecar submission/declaration binding differs")
    _require(sources._wire({k: sidecar[k] for k in recorder.ENVELOPE_FIELDS}) == sources._wire(recorder._envelope(item)),
             "scope sidecar physical/source/context envelope differs")
    _require(sidecar["scope_input_sha256"] == digest(request), "scope sidecar complete input binding differs")
    _maps(sidecar)
    declaration = sidecar["scope_declaration"]
    if declaration is not None:
        sources._closed(declaration, scope._FIELDS, "scope declaration")
        _require(declaration["schema"] == scope.SCHEMA and declaration["family"] == "deontic"
                 and declaration["profile"] == scope.PROFILE, "scope declaration schema/family/profile differs")
        _require(sources._wire(declaration["input"]) == sources._wire(request)
                 and declaration["input_sha256"] == digest(request), "scope declaration complete source/context differs")
        _require(declaration["content_sha256"] == digest({k: v for k, v in declaration.items() if k != "content_sha256"}),
                 "scope declaration body seal differs")


def _geometry(anchor, occurrence, shift):
    selected = [anchor["char_start"], anchor["char_end"]]
    span = occurrence["anchor"]
    translated = selected if span["origin"] == "source" else [shift + selected[0], shift + selected[1]]
    _require([span["start"], span["end"]] == translated and span["text"] == anchor["text"],
             "mapped anchor exact source/context occurrence differs")


def _graph(declaration):
    """Enumerate caller-declared leaf sites and their explicit affected rules."""
    groups, leaves = {}, {}

    def expression(node, path, facet, affected, group):
        if node is None:
            return
        if node["op"] == "leaf":
            leaves[path] = {"occurrence_id": node["occurrence_id"], "facet": facet,
                            "affected_rule_ids": affected, "group_path": group}
        elif node["op"] == "not":
            expression(node["child"], path + "/child", facet, affected, group)
        else:
            for index, child in enumerate(node["children"]):
                expression(child, f"{path}/children/{index}", facet, affected, group)

    def qualifiers(value, path, affected):
        for facet in recorder.QUALIFIERS:
            group = path + "/" + facet
            if value[facet] is not None:
                groups[group] = {"facet": facet, "affected_rule_ids": affected}
                expression(value[facet], group, facet, affected, group)

    for index, rule in enumerate(declaration["rules"]):
        qualifiers(rule["qualifiers"], f"/rules/{index}/qualifiers", [rule["rule_id"]])

    def statement(node, path):
        if node["op"] == "rule":
            return [node["rule_id"]]
        if node["op"] == "attach":
            affected = statement(node["body"], path + "/body")
            qualifiers(node["qualifiers"], path + "/qualifiers", affected)
            return affected
        return [identity for index, child in enumerate(node["children"])
                for identity in statement(child, f"{path}/children/{index}")]

    statement(declaration["statement_structure"], "/statement_structure")
    return groups, leaves


def _join(sidecar, entry, item):
    review = entry["declaration"]["review"]
    rules, anchors, attachments = review["normative_rules"], review["source_role_anchors"], review["qualifier_attachments"]
    _require(rules is not None and anchors is not None and attachments is not None,
             "complete binding requires explicitly declared rules, anchors and attachments")
    declaration = sidecar["scope_declaration"]
    scoped_rules = declaration["rules"]
    _require(sidecar["rule_bindings"] == [{"rule_index": index, "scope_rule_id": rule["rule_id"]}
                                         for index, rule in enumerate(scoped_rules)]
             and len(rules) == len(scoped_rules), "ordered exhaustive rule bindings differ")
    table = {row["occurrence_id"]: row for row in declaration["occurrences"]}
    rule_ids = {row["rule_id"]: index for index, row in enumerate(scoped_rules)}
    expected_modalities = []
    for index, (rule, declared) in enumerate(zip(rules, scoped_rules, strict=True)):
        for facet in scope.CORE:
            ref = declared["body"][facet]
            _require((ref is None and facet == "object" and rule[facet] == "")
                     or (ref is not None and table[ref]["canonical_symbol"] == rule[facet]),
                     "scope core symbol differs from recorded rule value")
        expected_modalities.append({"rule_index": index, "scope_occurrence_id": declared["body"]["modality"]})
    _require(sidecar["modality_bindings"] == expected_modalities, "ordered exhaustive caller modality bindings differ")
    groups, leaves = _graph(declaration)
    expected_slots = [(index, facet, position) for index, rule in enumerate(rules)
                      for facet in recorder.QUALIFIERS for position in range(len(rule[facet]))]
    _require([(r["rule_index"], r["facet"], r["qualifier_index"]) for r in sidecar["qualifier_bindings"]] == expected_slots,
             "ordered exhaustive qualifier-index bindings differ")
    used, qualifier_occurrences = set(), {}
    for row in sidecar["qualifier_bindings"]:
        index, facet, position, path = (row[k] for k in ("rule_index", "facet", "qualifier_index", "scope_leaf_path"))
        _require(path in leaves and leaves[path]["facet"] == facet
                 and scoped_rules[index]["rule_id"] in leaves[path]["affected_rule_ids"],
                 "qualifier leaf escapes its declared rule/facet attachment")
        key = (index, path)
        _require(key not in used, "duplicate mapped qualifier leaf site")
        used.add(key)
        identity = leaves[path]["occurrence_id"]
        _require(table[identity]["canonical_symbol"] == rules[index][facet][position],
                 "qualifier symbol or repeated occurrence order differs")
        qualifier_occurrences.setdefault((index, facet), set()).add(identity)
    expected_sites = {(rule_ids[identity], path) for path, row in leaves.items() for identity in row["affected_rule_ids"]}
    _require(used == expected_sites, "scope qualifier leaf site lost or invented by flat declaration mapping")
    for index, rule in enumerate(scoped_rules):
        for facet in recorder.QUALIFIERS:
            expected_order = [path for path, leaf in leaves.items() if leaf["facet"] == facet
                              and rule["rule_id"] in leaf["affected_rule_ids"]]
            supplied_order = [row["scope_leaf_path"] for row in sidecar["qualifier_bindings"]
                              if row["rule_index"] == index and row["facet"] == facet]
            _require(supplied_order == expected_order, "qualifier leaf occurrence order differs")
    _require([r["anchor_id"] for r in sidecar["anchor_bindings"]] == [r["anchor_id"] for r in anchors],
             "ordered exhaustive original anchor bindings differ")
    for anchor, row in zip(anchors, sidecar["anchor_bindings"], strict=True):
        identity = row["scope_occurrence_id"]
        _require(identity in table and table[identity]["facet"] == anchor["facet"], "mapped anchor occurrence/facet differs")
        allowed = (qualifier_occurrences.get((anchor["rule_index"], anchor["facet"]), set())
                   if anchor["facet"] in recorder.QUALIFIERS else {scoped_rules[anchor["rule_index"]]["body"][anchor["facet"]]})
        _require(identity in allowed, "mapped source anchor is not attached to its original rule/facet")
        _geometry(anchor, table[identity], item["context"]["selected_char_start"])
    _require([r["attachment_id"] for r in sidecar["attachment_bindings"]] == [r["attachment_id"] for r in attachments],
             "ordered exhaustive original attachment bindings differ")
    for attachment, row in zip(attachments, sidecar["attachment_bindings"], strict=True):
        path = row["scope_path"]
        _require(path in groups and groups[path]["facet"] == attachment["facet"], "mapped qualifier attachment path/facet differs")
        affected = [rule_ids[identity] for identity in groups[path]["affected_rule_ids"]]
        _require(set(affected) == set(attachment["affected_rule_indices"]), "mapped attachment affected rules differ")
        mapped_anchors = {r["anchor_id"]: r["scope_occurrence_id"] for r in sidecar["anchor_bindings"]}
        members = {leaf["occurrence_id"] for leaf in leaves.values() if leaf["group_path"] == path}
        _require(all(mapped_anchors[identity] in members for identity in attachment["anchor_ids"]),
                 "attachment source anchor escapes its mapped qualifier expression")
    return {"ordered_rule_count": len(rules), "qualifier_index_count": len(expected_slots),
            "scope_leaf_site_count": len(leaves), "source_role_anchor_count": len(anchors),
            "attachment_count": len(attachments), "binder_count": len(declaration["binders"]),
            "review_trigger_anchors_preserved": deepcopy(review["trigger"]),
            "review_trigger_rule_linkage": "not_assessed_archival_trigger_list_has_no_rule_association"}


def bind_scope_declarations(packet, reviewed_submissions, scope_sidecars, *, expected_packet_sha256,
                            artifact_resolver, recording=None, preflight=None):
    """Record explicit lossless joins; retain every physical item and declaration.

    A partial sidecar remains unassessed. A complete malformed graph/map fails
    closed. Scope-profile limits preserve the supplied sidecar as unvalidated
    evidence, never as a truncated or accepted scope view. Review status and
    transport status are separate; disputed/inconsistent reviews are not promoted.
    """
    setup = _setup(packet, reviewed_submissions, expected_packet_sha256, artifact_resolver, recording, preflight)
    packet, submissions, recording, preflight, contexts = setup
    sidecars = _detach(scope_sidecars)
    _require(type(sidecars) is list and len(sidecars) <= MAX_SIDECARS, "bounded scope sidecar list required")
    items = {item["item_id"]: item for item in packet["items"]}
    entries = {(entry["submission_id"], item["item_id"]): entry for item in preflight["items"]
               for entry in item["received_declarations"]}
    by_pair, binding_ids = {}, set()
    for index, sidecar in enumerate(sidecars):
        sources._closed(sidecar, SIDECAR_FIELDS, "statutory scope sidecar")
        pair = (sidecar["submission_id"], sidecar["item_id"])
        _require(all(type(identity) is str for identity in pair) and pair in entries,
                 "scope sidecar requires an existing submission/physical item pair")
        _require(pair not in by_pair, "duplicate scope sidecar for submission/physical item")
        entry, item = entries[pair], items[pair[1]]
        _header(sidecar, item, entry, _request(item, contexts), expected_packet_sha256)
        _require(sidecar["binding_id"] not in binding_ids, "duplicate scope binding_id")
        binding_ids.add(sidecar["binding_id"])
        by_pair[pair] = (index, sidecar)
    results, counts = [], Counter()
    for item in packet["items"]:
        reviewed = next(row for row in preflight["items"] if row["item_id"] == item["item_id"])
        request = _request(item, contexts)
        request_limits = _limits(request)
        declarations = []
        for entry in reviewed["received_declarations"]:
            supplied = by_pair.get((entry["submission_id"], item["item_id"]))
            sidecar_index, sidecar = (None, None) if supplied is None else supplied
            limits = _limits(request, None if sidecar is None else sidecar["scope_declaration"],
                             entry["declaration"]["review"]["normative_rules"])
            validation, view, bridge_validation, geometry = None, None, None, None
            if limits:
                status = "profile_limit"
            elif sidecar is None:
                status = "pending_scope_declaration"
            elif sidecar["scope_declaration"] is None or any(sidecar[k] is None for k in MAP_FIELDS):
                status = "partial_binding"
            else:
                declaration = sidecar["scope_declaration"]
                validation = scope.validate_scope_declaration(request, declaration, expected_input_sha256=digest(request))
                geometry = _join(sidecar, entry, item)
                try:
                    native_view = bridge.prepare_scope_bridge_view(request, declaration, expected_input_sha256=digest(request))
                    view = native_view.to_dict()
                    bridge_validation = bridge.validate_scope_bridge_view(view, request, expected_input_sha256=digest(request))
                    status = "joined_declared_scope_only"
                except ValueError as error:
                    if str(error) == "scope payload exceeds bridge byte bound; no truncation":
                        limits = ["complete_scope_bridge_view_byte_limit"]
                        status = "profile_limit"
                    elif str(error) == "scope JSON node/depth bound exceeded":
                        limits = ["complete_scope_bridge_view_JSON_node_or_depth_limit"]
                        status = "profile_limit"
                    else:
                        raise
            counts[status] += 1
            declarations.append({"review_declaration": deepcopy(entry), "binding_status": status,
                                 "binding_index": sidecar_index, "sidecar": deepcopy(sidecar),
                                 "sidecar_sha256": None if sidecar is None else digest(sidecar),
                                 "profile_limits": limits, "scope_validation": validation,
                                 "scope_bridge_view": view, "scope_bridge_validation": bridge_validation,
                                 "declaration_join": geometry, "review_status_promoted": False,
                                 "scope_graph_validation_performed": validation is not None,
                                 "scope_bridge_transport_validated": bridge_validation is not None,
                                 "admission_masks": _masks(), **_false()})
        results.append({**recorder._envelope(item), "source_input": deepcopy(item["input"]),
                        "scope_input_sha256": digest(request), "scope_request": None if request_limits else request,
                        "complete_context_characters": len(request["context"]["text"]),
                        "request_profile_limits": request_limits, "recording_status": reviewed["recording_status"],
                        "declared_dispute_present": reviewed["declared_dispute_present"],
                        "reviewed_declarations": declarations, "admission_masks": _masks(), **_false()})
    _closing(setup, packet, submissions, expected_packet_sha256, artifact_resolver, recording, preflight)
    return _seal({"schema": SCHEMA, "status": "pending" if not submissions else "caller_scope_bindings_recorded_only",
                  "scope": "exact_physical_submission_to_declared_scope_transport_only", "digest_recipe": DIGEST_RECIPE,
                  "packet_sha256": expected_packet_sha256, "recording_sha256": digest(recording),
                  "preflight_sha256": digest(preflight), "submissions_sha256": digest(submissions),
                  "scope_sidecars_sha256": digest(sidecars), "scope_sidecars": sidecars,
                  "item_count": len(results), "submission_count": len(submissions), "sidecar_count": len(sidecars),
                  "declaration_count": sum(counts.values()), "binding_status_counts": {k: counts[k] for k in BINDING_STATUSES},
                  "declared_disputed_item_count": sum(r["declared_dispute_present"] for r in results), "items": results,
                  "gold_labels_created": 0, "human_reviews_authenticated": 0, "qualified_training_pairs": 0,
                  "formal_targets_created": 0, "model_calls": 0, "encoder_calls": 0, "prover_calls": 0,
                  "context_resolved": False, "actual_training_or_evaluation_admission": False,
                  "scope_profile": scope.PROFILE, "native_lowering_performed": False,
                  "admission_masks": _masks(), **_false()})


def validate_binding(receipt, packet, reviewed_submissions, scope_sidecars, *, expected_packet_sha256,
                     artifact_resolver, recording=None, preflight=None):
    """Rebuild every closed status/map/view/authority field from pinned inputs."""
    supplied = _detach(receipt)
    expected = bind_scope_declarations(packet, reviewed_submissions, scope_sidecars,
        expected_packet_sha256=expected_packet_sha256, artifact_resolver=artifact_resolver,
        recording=recording, preflight=preflight)
    _require(sources._wire(supplied) == sources._wire(expected), "scope binding differs from exact authoritative replay")
    return _seal({"schema": VALIDATION_SCHEMA, "status": "validated_declared_scope_binding_only",
                  "packet_sha256": expected_packet_sha256, "binding_sha256": digest(expected),
                  "scope_sidecars_sha256": expected["scope_sidecars_sha256"],
                  "declaration_count": expected["declaration_count"], "admission_masks": _masks(), **_false()})


__all__ = ["digest", "parse_json_bytes", "prepare_binding_slots", "bind_scope_declarations", "validate_binding"]

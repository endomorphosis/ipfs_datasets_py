"""Complete source-review requests and scoped signature evidence, no admission.

All requests retain original context and handoff questions. Nine source/context
evidence declarations may be authenticated under explicitly selected keys; seven
semantic/proof questions stay deferred. Original corpus contexts are never
changed. The existing review verifier supplies signatures, trust and dependency
checks in a distinct fixed source domain. Public import performs no source
decoding, crypto, signing, model, network or clock operation.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_bytes

from . import corpus_contracts as contracts
from . import corpus_parent_alignment_adapter as alignment
from . import corpus_parent_occurrence_adapter as base

PROFILE = "complete-parent-official-source-context-evidence-review/v1"
MANIFEST_SCHEMA = "legal-corpus-source-review-manifest/v1"
PAGE_SCHEMA = "legal-corpus-source-review-page/v1"
REQUEST_SCHEMA = "legal-corpus-source-review-request/v1"
SUBJECT_SCHEMA = "legal-corpus-source-review-subject/v1"
CLAIM_SCHEMA = "legal-corpus-source-context-review-signed-claim/v1"
ACTION = "record_source_context_review_evidence/v1"
AUDIENCE = "legal-autoformalization-source-context-review/v1"
ASSESSMENT_SCHEMA = "legal-corpus-source-context-review-assessment/v1"
GROUP_SCHEMA = "legal-corpus-source-review-group-assessment/v1"
GROUP_MANIFEST_SCHEMA = "legal-corpus-source-review-group-manifest/v1"
GROUP_PAGE_SCHEMA = "legal-corpus-source-review-group-page/v1"
CONTEXT_KINDS = base.MISSING_CONTEXT
HANDOFF_KINDS = (
    "producer_historical_source_correspondence", "official_edition_authentication", "region_legal_classification",
    "definition_closure", "reference_closure", "exception_scope_closure", "temporal_closure",
    "IR_semantic_fidelity", "global_consistency", "Lean4_kernel_check",
)
ACTIVE_SLOT_COUNT = 9
CORPUS_KEYS = ("manifest", "pages", "records")
REPORT_KEYS = ("context", "handoff")
REPLAY_FIELDS = {
    "base_corpus_bytes", "expected_base_corpus_pins", "base_report_bytes", "expected_base_report_pins",
    "base_replay_inputs", "alignment_report_bytes", "expected_alignment_report_pins", "document_inputs",
    "expected_document_population_sha256",
}
PREPARATION_KEYS = {"manifest", "pages", "requests", "subjects", "dependency_manifests"}
DEFAULT_LIMITS = {
    "max_source_report_bytes": 16 * 1024**2, "max_corpus_manifest_bytes": contracts.MAX_RECORD_BYTES,
    "max_corpus_page_bytes": 8 * 1024**2, "max_corpus_record_bytes": 64 * 1024**2,
    "max_replay_bytes": 16 * 1024**2, "max_total_input_bytes": 128 * 1024**2,
    "max_requests": 8192, "max_collection_bytes": 64 * 1024**2,
    "max_requests_per_page": 64, "max_page_bytes": contracts.MAX_RECORD_BYTES, "max_pages": 256,
    "max_batch_review_bytes": 64 * 1024**2,
}
FALSE_FLAGS = {
    **alignment.FALSE_FLAGS,
    **dict.fromkeys(("source_review_completed", "source_review_decisions_applied", "signature_establishes_legal_truth",
                     "human_identity_verified", "human_independence_verified", "semantic_graph_verified"), False),
}
REQUEST_FIELDS = {
    "profile", "queue_ordinal", "review_unit_id", "unit_kind", "parent_index", "source_observation_id",
    "source_version_cid", "source_occurrence_cid", "context_cid", "parent_record_cid", "source_role_cid",
    "related_source_records", "comparison_record_cids", "review_scope_id", "original_unit_binding",
    "original_context_binding", "review_questions", "context_slot_ids", "deferred_review_slot_ids",
    "source_binding_sha256", "questions_sha256", "input_bindings", "status", "view", *FALSE_FLAGS, *base.UNSELECTED,
}
SUBJECT_FIELDS = {
    "profile", "review_request_cid", "graph_id", "graph_sha256", "ast_sha256", "scope_id",
    "context_slot_ids", "deferred_review_slot_ids", "source_binding_sha256", "hash_recipes",
    "dependency_manifest_sha256", "required_dependency_ids", "dependency_artifacts", "view", *FALSE_FLAGS, *base.UNSELECTED,
}
MANIFEST_FIELDS = {
    "profile", "limits", "input_bindings", "producer_pins", "page_refs", "counts", "population_complete",
    "coverage_scope", "view", *FALSE_FLAGS, *base.UNSELECTED,
}
PAGE_FIELDS = {"page_ordinal", "first_request_ordinal", "entries", "view", *FALSE_FLAGS, *base.UNSELECTED}
GROUP_FIELDS = {
    "queue_ordinal", "review_request_cid", "subject_sha256", "assessment", "deferred_review_slot_ids",
    "deferred_questions_remain_pending", "view", *FALSE_FLAGS, *base.UNSELECTED,
}
GROUP_MANIFEST_FIELDS = {
    "profile", "preparation_manifest_cid", "preparation_manifest_sha256", "registry_sha256", "policy_sha256",
    "review_group_pins", "evaluation_time_utc", "producer_pins", "page_refs", "counts", "view", *FALSE_FLAGS, *base.UNSELECTED,
}
GROUP_PAGE_FIELDS = {"page_ordinal", "first_group_ordinal", "entries", "view", *FALSE_FLAGS, *base.UNSELECTED}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(base._plain(value, DEFAULT_LIMITS["max_replay_bytes"]))


def _limits(value):
    if value is not None and type(value) is not dict:
        _fail("closed lower-only source review limits required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        if key not in result or type(bound) is not int or not 0 < bound <= result[key]:
            _fail("unknown or raised source review limit")
        result[key] = bound
    return result


def _owners():
    from . import (
        legal_candidate_context_inventory,
        legal_graph_dependencies,
        legal_graph_review,
        legal_source_review_handoff,
    )
    return legal_candidate_context_inventory, legal_source_review_handoff, legal_graph_dependencies, legal_graph_review


def _pins(owners):
    result = alignment._pins(alignment._owners())
    paths = [Path(__file__).resolve(), *(Path(module.__file__).resolve() for module in owners)]
    paths.append(Path(owners[3].__file__).resolve().parent.parent / "profile_g.py")
    for path in paths:
        result[str(path)] = _sha(path.read_bytes())
    return result


def _raw(raw, expected, maximum, *, empty=False):
    contracts.require_sha256(expected, "independent raw input SHA256")
    if type(raw) is not bytes or not (0 if empty else 1) <= len(raw) <= maximum or _sha(raw) != expected:
        _fail("complete immutable source-review input hash or byte bound differs")
    return raw


def _jsonl(raw, maximum_records):
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        _fail("complete source corpus JSONL requires declared final newline")
    result = []
    for line in raw.split(b"\n")[:-1]:
        if not line or len(line) > contracts.MAX_RECORD_BYTES or len(result) >= maximum_records:
            _fail("complete bounded source corpus JSONL population required")
        result.append(base._load(line, contracts.MAX_RECORD_BYTES))
    return result


def _snapshot(alignment_corpus_bytes, expected_alignment_corpus_pins, alignment_replay_inputs,
              source_report_bytes, expected_source_report_pins, bounds):
    """Check all raw namespaces and exact nested budgets before operation imports."""
    contracts.require_keys(alignment_corpus_bytes, CORPUS_KEYS, "complete alignment corpus transport")
    contracts.require_keys(expected_alignment_corpus_pins, CORPUS_KEYS, "independent alignment corpus pins")
    contracts.require_keys(source_report_bytes, REPORT_KEYS, "complete context and handoff reports")
    contracts.require_keys(expected_source_report_pins, REPORT_KEYS, "independent context and handoff pins")
    contracts.require_keys(alignment_replay_inputs, REPLAY_FIELDS, "complete alignment replay")
    transport = dict(alignment_corpus_bytes)
    corpus_pins = contracts.clone_json(expected_alignment_corpus_pins)
    report_raw = dict(source_report_bytes)
    report_pins = contracts.clone_json(expected_source_report_pins)
    total = 0
    for key, maximum in zip(CORPUS_KEYS, (bounds["max_corpus_manifest_bytes"], bounds["max_corpus_page_bytes"], bounds["max_corpus_record_bytes"]), strict=True):
        total += len(_raw(transport[key], corpus_pins[key], maximum, empty=key != "manifest"))
    for key in REPORT_KEYS:
        contracts.require_keys(report_pins[key], {"raw_sha256", "canonical_sha256"}, "source report raw/FULL hashes")
        contracts.require_sha256(report_pins[key]["canonical_sha256"], "source FULL hash")
        total += len(_raw(report_raw[key], report_pins[key]["raw_sha256"], bounds["max_source_report_bytes"]))
    replay = dict(alignment_replay_inputs)
    for field, pin_field, keys, maxima in (
            ("base_corpus_bytes", "expected_base_corpus_pins", ("manifest", "records"), (contracts.MAX_RECORD_BYTES, 16 * 1024**2)),
            ("base_report_bytes", "expected_base_report_pins", base.REPORT_KEYS, (8 * 1024**2,) * 3)):
        contracts.require_keys(replay[field], keys, "complete original alignment replay bytes")
        contracts.require_keys(replay[pin_field], keys, "complete original alignment replay pins")
        replay[field] = dict(replay[field])
        replay[pin_field] = contracts.clone_json(replay[pin_field])
        for key, maximum in zip(keys, maxima, strict=True):
            pin = replay[pin_field][key]
            if field == "base_report_bytes":
                contracts.require_keys(pin, {"raw_sha256", "canonical_sha256"}, "base report raw/FULL pins")
                contracts.require_sha256(pin["canonical_sha256"], "base FULL pin")
                pin = pin["raw_sha256"]
            total += len(_raw(replay[field][key], pin, maximum))
    replay["expected_alignment_report_pins"] = contracts.clone_json(replay["expected_alignment_report_pins"])
    contracts.require_keys(replay["expected_alignment_report_pins"], {"raw_sha256", "canonical_sha256"}, "alignment raw/FULL pins")
    contracts.require_sha256(replay["expected_alignment_report_pins"]["canonical_sha256"], "alignment FULL pin")
    total += len(_raw(replay["alignment_report_bytes"], replay["expected_alignment_report_pins"]["raw_sha256"], 16 * 1024**2))
    contracts.require_sha256(replay["expected_document_population_sha256"], "official document population hash")
    if type(replay["document_inputs"]) is not list or len(replay["document_inputs"]) > 10:
        _fail("complete bounded official replay population required")
    documents = []
    declared_raw_total = 0
    for item in replay["document_inputs"]:
        contracts.require_keys(item, alignment.DOCUMENT_FIELDS, "complete official document input")
        item = dict(item)
        for field in ("expected_descriptor_sha256", "expected_raw_sha256", "expected_view_report_sha256"):
            contracts.require_sha256(item[field], field)
        size = item["expected_raw_bytes"]
        contracts.require_int(size, "declared raw HTML bytes", minimum=1, maximum=8 * 1024**2)
        declared_raw_total += size
        if declared_raw_total > 8 * 1024**2:
            _fail("complete declared raw HTML population exceeds bound")
        if item["raw_bytes"] is not None:
            total += len(_raw(item["raw_bytes"], item["expected_raw_sha256"], size))
            if len(item["raw_bytes"]) != size:
                _fail("declared raw HTML length differs")
        documents.append(item)
    residual = bounds["max_total_input_bytes"] - total
    if residual <= 0:
        _fail("whole source-review input budget exhausted before nested replay")
    contracts.require_keys(replay["base_replay_inputs"], base.REPLAY_FIELDS, "complete base original replay")
    raw = base._plain(replay["base_replay_inputs"], min(bounds["max_replay_bytes"], residual))
    residual -= len(raw)
    replay["base_replay_inputs"] = json.loads(raw)
    for item in documents:
        if residual <= 0:
            _fail("whole source-review input budget exhausted before document replay")
        raw = base._plain({key: value for key, value in item.items() if key != "raw_bytes"}, min(bounds["max_replay_bytes"], residual))
        residual -= len(raw)
        snapshot = json.loads(raw)
        snapshot["raw_bytes"] = item["raw_bytes"]
        item.clear()
        item.update(snapshot)
    replay["document_inputs"] = documents
    return transport, corpus_pins, replay, report_raw, report_pins


def _binding(raw, canonical_sha=None):
    result = {"raw_cid": cid_for_bytes(raw), "raw_sha256": _sha(raw), "raw_bytes": len(raw)}
    if canonical_sha is not None:
        result["canonical_sha256"] = canonical_sha
    return result


def _external(report, binding, pointer):
    return {"report_raw_cid": binding["raw_cid"], "report_raw_sha256": binding["raw_sha256"],
            "report_canonical_sha256": binding["canonical_sha256"], "json_pointer": pointer,
            "value_sha256": _digest(base._pointer(report, pointer))}


def _questions(review_unit_id):
    result = []
    for category, kinds in (("context", CONTEXT_KINDS), ("handoff", HANDOFF_KINDS)):
        for index, kind in enumerate(kinds):
            active = category == "context" or index < 3
            result.append({"slot_id": "source-review-slot:" + review_unit_id + ":" + category + ":" + kind,
                "category": category, "kind": kind,
                "assessment_scope": "source_context_evidence_declaration" if active else "deferred_semantic_or_proof_review",
                "status": "pending_independent_review", "verified": False, "closed": False})
    return result


def _aggregate_size(bundle):
    # Exactly account the complete compact representation without a bulk copy.
    total = len(b'{"manifest":}') + len(canonical_dag_json_bytes(bundle["manifest"]))
    for key, values in bundle.items():
        if key == "manifest":
            continue
        total += len(json.dumps(key).encode()) + 4 + sum(len(canonical_dag_json_bytes(item)) for item in values) + max(0, len(values) - 1)
    return total


def _pages(entries, bounds, *, assessment=False):
    pages, refs, pending = [], [], []
    start = 0
    schema = GROUP_PAGE_SCHEMA if assessment else PAGE_SCHEMA
    first_key = "first_group_ordinal" if assessment else "first_request_ordinal"
    def sealed(items):
        return contracts.seal_record({"schema": schema, "page_ordinal": len(pages), first_key: start,
            "entries": items, "view": "candidate", **FALSE_FLAGS, **base.UNSELECTED})
    def finish():
        if len(pages) >= bounds["max_pages"]:
            _fail("complete source-review page population exceeds bound")
        page = sealed(pending)
        raw = base._plain(page, bounds["max_page_bytes"])
        pages.append(page)
        refs.append({"page_cid": page["record_cid"], "sha256": _sha(raw), "page_ordinal": len(pages) - 1,
                     first_key: start, "entry_count": len(pending)})
    empty_size, retained_entries = len(canonical_dag_json_bytes(sealed([]))), 0
    for entry in entries:
        size = len(canonical_dag_json_bytes(entry))
        if pending and (len(pending) >= bounds["max_requests_per_page"]
                        or empty_size + retained_entries + size + len(pending) > bounds["max_page_bytes"]):
            finish()
            start = entry["ordinal"]
            pending, retained_entries = [], 0
            empty_size = len(canonical_dag_json_bytes(sealed([])))
        pending.append(entry)
        retained_entries += size
    if pending:
        finish()
    return pages, refs


def prepare_source_review_requests(*, alignment_corpus_bytes, expected_alignment_corpus_pins,
        alignment_replay_inputs, source_report_bytes, expected_source_report_pins, limits=None):
    """Replay complete source populations once and prepare every pending unit."""
    bounds = _limits(limits)
    transport, corpus_pins, replay, report_raw, report_pins = _snapshot(alignment_corpus_bytes,
        expected_alignment_corpus_pins, alignment_replay_inputs, source_report_bytes, expected_source_report_pins, bounds)
    owners = _owners()
    producer_pins = _pins(owners)
    context_owner, handoff_owner, dependencies, review_owner = owners
    supplement = {"manifest": base._load(transport["manifest"], contracts.MAX_RECORD_BYTES),
                  "pages": _jsonl(transport["pages"], alignment.DEFAULT_LIMITS["max_pages"]),
                  "records": _jsonl(transport["records"], alignment.DEFAULT_LIMITS["max_records"])}
    try:
        supplement = alignment.validate_parent_alignment_corpus(supplement, **replay, limits=supplement["manifest"]["limits"])
        reports = {key: base._load(report_raw[key], bounds["max_source_report_bytes"]) for key in REPORT_KEYS}
        for key, hasher in (("context", context_owner.candidate_context_inventory_report_sha256),
                            ("handoff", handoff_owner.source_review_handoff_report_sha256)):
            if hasher(reports[key]) != report_pins[key]["canonical_sha256"]:
                _fail("independent FULL context/handoff hash differs")
        aligned = base._load(replay["alignment_report_bytes"], 16 * 1024**2)
        sentence = base._load(replay["base_report_bytes"]["parent_sentence_candidates"], 8 * 1024**2)
        sentence_inputs = {"expected_parent_text_views_report_sha256": replay["expected_base_report_pins"]["parent_text_views"]["canonical_sha256"],
                           "parent_text_views_inputs": replay["base_replay_inputs"]["parent_text_views_inputs"]}
        context_inputs = {"sentence_candidates_report": sentence, "alignment_report": aligned,
            "expected_sentence_candidates_report_sha256": replay["expected_base_report_pins"]["parent_sentence_candidates"]["canonical_sha256"],
            "sentence_inputs": sentence_inputs,
            "expected_alignment_report_sha256": replay["expected_alignment_report_pins"]["canonical_sha256"],
            "alignment_inputs": {**sentence_inputs, "document_inputs": replay["document_inputs"],
                "expected_document_population_sha256": replay["expected_document_population_sha256"]},
            "limits": reports["context"]["limits"]}
        handoff_owner.validate_source_review_handoff(reports["handoff"], reports["context"],
            expected_report_sha256=report_pins["handoff"]["canonical_sha256"],
            expected_candidate_context_inventory_report_sha256=report_pins["context"]["canonical_sha256"],
            context_inputs=context_inputs, limits=reports["handoff"]["limits"])
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError) as error:
        raise contracts.CorpusContractError("source review refused complete original corpus/context/handoff replay") from error
    if tuple(handoff_owner.REVIEW_OBLIGATION_KINDS) != HANDOFF_KINDS:
        _fail("declared handoff question profile changed")
    baseline = {"manifest": base._load(replay["base_corpus_bytes"]["manifest"], contracts.MAX_RECORD_BYTES),
                "records": _jsonl(replay["base_corpus_bytes"]["records"], base.DEFAULT_LIMITS["max_records"])}
    by_cid = {item["record_cid"]: item for item in (*baseline["records"], *supplement["records"])}
    if len(by_cid) != len(baseline["records"]) + len(supplement["records"]):
        _fail("base and supplement record populations collide")
    parents = [by_cid[cid] for cid in baseline["manifest"]["populations"]["parents"]]
    parent_indices = {item["record_cid"]: index for index, item in enumerate(parents)}
    roles = {(parent_indices[item["parent_record_cid"]], item["role"], item["owner_id"]): item for item in baseline["records"]
             if item["schema"] == base.ROLE_SCHEMA and item["role"] in {"segment", "dependency"}}
    anchors = {item["owner_identity"]["alignment_id"]: item for item in supplement["records"]
               if item["schema"] == alignment.OBSERVATION_SCHEMA and item["kind"] == "alignment"}
    comparisons = {(item["parent_index"], item["document_index"]): item for item in supplement["records"]
                   if item["schema"] == alignment.OBSERVATION_SCHEMA and item["kind"] == "comparison"}
    context_units = {}
    for row_index, row in enumerate(reports["context"]["rows"]):
        for key in ("partition_piece_contexts", "surface_reference_contexts"):
            for index, unit in enumerate(row[key]):
                context_units[(row_index, unit["source_observation_id"])] = (unit, f"/rows/{row_index}/{key}/{index}")
    input_bindings = {"corpus": {key: _binding(transport[key]) for key in CORPUS_KEYS},
        "base_corpus": {key: _binding(replay["base_corpus_bytes"][key]) for key in ("manifest", "records")},
        "source_reports": {key: _binding(report_raw[key], report_pins[key]["canonical_sha256"]) for key in REPORT_KEYS},
        "alignment_report": _binding(replay["alignment_report_bytes"], replay["expected_alignment_report_pins"]["canonical_sha256"])}
    requests, subjects, manifests, inventory = [], [], [], []
    retained = 0
    for ordinal, unit in enumerate(reports["handoff"]["queue_units"]):
        if ordinal >= bounds["max_requests"] or unit["queue_ordinal"] != ordinal:
            _fail("complete ordered source review request population exceeds bound")
        parent = parents[unit["parent_index"]]
        primary = related_role = None
        related_ids = []
        original_context_binding = None
        if unit["unit_kind"] in {"original_parent_partition_piece", "original_unresolved_surface_reference"}:
            kind = "segment" if unit["unit_kind"] == "original_parent_partition_piece" else "dependency"
            related_role = roles[(unit["parent_index"], kind, unit["source_observation_id"])]
            if related_role["external_binding"]["value_sha256"] != unit["original_observation_sha256"]:
                _fail("original review unit differs from exact corpus source role")
            primary = related_role
            original_context, pointer = context_units[(unit["parent_index"], unit["source_observation_id"])]
            if original_context["context_unit_id"] != unit["context_unit_id"]:
                _fail("complete original review context identity differs")
            original_context_binding = _external(reports["context"], input_bindings["source_reports"]["context"], pointer)
            for compared in original_context["comparison_contexts"]:
                for intersection in compared["exact_block_intersections"]:
                    anchor = anchors[intersection["alignment_id"]]
                    related_ids.extend([anchor["record_cid"], anchor["source_occurrence_cid"], anchor["context_cid"],
                        anchor["related_records"]["official_source_occurrence_cid"], anchor["related_records"]["official_context_cid"],
                        anchor["related_records"]["official_block_record_cid"]])
        elif unit["unit_kind"] == "exact_declared_markup_statute_block_opportunity":
            primary = anchors[unit["original_observation"]["alignment_id"]]
            if primary["observations"]["parent_selector"] != unit["original_observation"]["parent_selector"]:
                _fail("markup opportunity parent origin differs")
            if primary["observations"]["official_selector"] != unit["original_observation"]["official_selector"]:
                _fail("markup opportunity official origin differs")
            related_ids.extend([primary["record_cid"], *primary["related_records"].values()])
        elif unit["unit_kind"] != "unavailable_parent_text_observation":
            _fail("unsupported original source review unit kind")
        comparison_cids = [comparisons[(unit["parent_index"], index)]["record_cid"]
                           for index in range(reports["handoff"]["official_document_count"])]
        related_ids.extend([parent["record_cid"], *comparison_cids])
        occurrence_cid = None if primary is None else primary["source_occurrence_cid"]
        context_cid = None if primary is None else primary["context_cid"]
        version_cid = parent["source_version_cid"]
        related_ids.extend(value for value in (version_cid, occurrence_cid, context_cid,
                                               None if related_role is None else related_role["record_cid"]) if value is not None)
        # Retain the complete declared source-record closure, including both
        # normalized/rendered document origins, without copying their bodies.
        reachable, seen = list(dict.fromkeys(related_ids)), set(related_ids)
        for cid in reachable:
            record = by_cid[cid]
            children = [record.get(key) for key in ("parent_record_cid", "source_version_cid", "source_occurrence_cid", "context_cid")]
            for value in record.get("related_records", {}).values():
                children.extend(value if type(value) is list else [value])
            children.extend(item["record_cid"] for item in record.get("context_references", []))
            for child in children:
                if child is not None and child not in seen:
                    if child not in by_cid:
                        _fail("declared source evidence reference is absent from complete corpus")
                    seen.add(child)
                    reachable.append(child)
        related_ids = reachable
        refs = []
        for cid in dict.fromkeys(related_ids):
            record = by_cid[cid]
            refs.append({"record_cid": cid, "sha256": _sha(canonical_dag_json_bytes(record)), "schema": record["schema"]})
        questions = _questions(unit["review_unit_id"])
        active = [item["slot_id"] for item in questions if item["assessment_scope"] == "source_context_evidence_declaration"]
        deferred = [item["slot_id"] for item in questions if item["assessment_scope"] != "source_context_evidence_declaration"]
        scope = "source-review-scope:sha256:" + _digest({"profile": PROFILE, "parent_record_cid": parent["record_cid"], "source_version_cid": version_cid})
        source_binding_sha = _digest({"parent_record_cid": parent["record_cid"], "related_source_records": refs,
            "source_occurrence_cid": occurrence_cid, "context_cid": context_cid})
        request = contracts.seal_record({
            "schema": REQUEST_SCHEMA, "profile": PROFILE, "queue_ordinal": ordinal,
            **{key: unit[key] for key in ("review_unit_id", "unit_kind", "parent_index", "source_observation_id")},
            "source_version_cid": version_cid, "source_occurrence_cid": occurrence_cid, "context_cid": context_cid,
            "parent_record_cid": parent["record_cid"], "source_role_cid": None if related_role is None else related_role["record_cid"],
            "related_source_records": refs, "comparison_record_cids": comparison_cids, "review_scope_id": scope,
            "original_unit_binding": _external(reports["handoff"], input_bindings["source_reports"]["handoff"], f"/queue_units/{ordinal}"),
            "original_context_binding": original_context_binding, "review_questions": questions,
            "context_slot_ids": active, "deferred_review_slot_ids": deferred, "source_binding_sha256": source_binding_sha,
            "questions_sha256": _digest(questions), "input_bindings": input_bindings,
            "status": "pending_independent_source_and_context_evidence_review", "view": "candidate", **FALSE_FLAGS, **base.UNSELECTED,
        })
        manifest = _dependency_manifest(request, producer_pins, dependencies)
        subject = _build_subject(request, manifest, review_owner)
        for item in (request, subject, manifest):
            retained += len(base._plain(item, min(contracts.MAX_RECORD_BYTES, bounds["max_collection_bytes"] - retained))) + 1
        requests.append(request)
        subjects.append(subject)
        manifests.append(manifest)
        inventory.append({"ordinal": ordinal, "request_cid": request["record_cid"], "request_sha256": _digest(request),
            "subject_cid": subject["record_cid"], "subject_sha256": _digest(subject),
            "dependency_manifest_sha256": manifest["manifest_sha256"]})
    pages, page_refs = _pages(inventory, bounds)
    root = contracts.seal_record({"schema": MANIFEST_SCHEMA, "profile": PROFILE, "limits": bounds,
        "input_bindings": input_bindings, "producer_pins": producer_pins, "page_refs": page_refs,
        "counts": {"requests": len(requests), "subjects": len(subjects), "dependency_manifests": len(manifests),
            "pages": len(pages), "question_count": len(requests) * 16, "active_source_context_slots": len(requests) * ACTIVE_SLOT_COUNT,
            "deferred_semantic_proof_questions": len(requests) * 7,
            "unit_kinds": dict(Counter(item["unit_kind"] for item in requests))},
        "population_complete": True, "coverage_scope": "all_supplied_pending_source_review_requests_and_exact_corpus_evidence_only",
        "view": "candidate", **FALSE_FLAGS, **base.UNSELECTED})
    result = {"manifest": root, "pages": pages, "requests": requests, "subjects": subjects, "dependency_manifests": manifests}
    if _aggregate_size(result) > bounds["max_collection_bytes"]:
        _fail("complete source-review preparation exceeds collection byte bound")
    if _pins(owners) != producer_pins:
        _fail("source-review producers changed during preparation")
    return result


def _dependency_manifest(request, producer_pins, owner):
    artifacts, seen = [], set()
    def add(identity, sha256, *, policy_pins=()):
        if identity in seen:
            return
        seen.add(identity)
        pins = {kind: [] for kind in owner.PIN_KINDS}
        pins["policy"] = list(policy_pins)
        artifacts.append({"artifact_id": identity, "artifact_sha256": sha256, "dependency_pins": pins})
    policies = [{"key": "source-review-producer:" + path, "sha256": sha256} for path, sha256 in sorted(producer_pins.items())]
    add(request["record_cid"], _digest(request), policy_pins=policies)
    add("source-review-questions:sha256:" + request["questions_sha256"], request["questions_sha256"])
    for group, values in request["input_bindings"].items():
        items = values.items() if group != "alignment_report" else [("complete", values)]
        for key, value in items:
            add("source-review-input:" + group + ":" + key + ":sha256:" + value["raw_sha256"], value["raw_sha256"])
    for item in request["related_source_records"]:
        add(item["record_cid"], item["sha256"])
    identities = [item["artifact_id"] for item in artifacts]
    return owner.build_dependency_manifest(artifacts,
        [{"dependent_id": identities[0], "dependency_id": child} for child in identities[1:]], expected_artifact_ids=identities)


def _build_subject(request, manifest, review_owner):
    reachable, artifacts = review_owner._closure(manifest, request["record_cid"], _digest(request))
    return contracts.seal_record({"schema": SUBJECT_SCHEMA, "profile": PROFILE,
        "review_request_cid": request["record_cid"], "graph_id": request["record_cid"],
        "graph_sha256": _digest(request), "ast_sha256": request["questions_sha256"],
        "scope_id": request["review_scope_id"], "context_slot_ids": request["context_slot_ids"],
        "deferred_review_slot_ids": request["deferred_review_slot_ids"], "source_binding_sha256": request["source_binding_sha256"],
        "hash_recipes": {
            "graph_id": "compatibility alias for sealed source-review request CID; no semantic graph",
            "graph_sha256": "FULL canonical sealed source-review request SHA256; no graph interpretation",
            "ast_sha256": "canonical complete sixteen source/context/deferred questions SHA256; no native AST",
            "scope_id": "explicit parent-field review authorization scope; no governing legal scope inferred",
        }, "dependency_manifest_sha256": manifest["manifest_sha256"], "required_dependency_ids": reachable,
        "dependency_artifacts": artifacts, "view": "candidate", **FALSE_FLAGS, **base.UNSELECTED})


def _subject(subject, manifest):
    """Fixed private validator, invoked only after complete batch regeneration."""
    checked = contracts.validate_record(subject, schema=SUBJECT_SCHEMA, fields=SUBJECT_FIELDS)
    if checked["profile"] != PROFILE or checked["graph_id"] != checked["review_request_cid"]:
        _fail("source-only compatibility binding differs")
    slots, deferred = checked["context_slot_ids"], checked["deferred_review_slot_ids"]
    if (type(slots) is not list or len(slots) != ACTIVE_SLOT_COUNT or type(deferred) is not list or len(deferred) != 7
            or any(type(item) is not str for item in (*slots, *deferred)) or len(set((*slots, *deferred))) != 16):
        _fail("complete distinct active/deferred source-review questions required")
    for flag in FALSE_FLAGS:
        if checked[flag] is not False:
            _fail("source-review subjects cannot claim semantic or source authority")
    _, _, _, review_owner = _owners()
    reachable, artifacts = review_owner._closure(manifest, checked["graph_id"], checked["graph_sha256"])
    if (checked["dependency_manifest_sha256"] != manifest["manifest_sha256"]
            or checked["required_dependency_ids"] != reachable or checked["dependency_artifacts"] != artifacts):
        _fail("source-review declared dependency closure differs")


def _detach_preparation(preparation, bounds):
    contracts.require_keys(preparation, PREPARATION_KEYS, "complete source-review preparation")
    result = {"manifest": None}
    total = 0
    for group in ("manifest", "pages", "requests", "subjects", "dependency_manifests"):
        values = [preparation[group]] if group == "manifest" else preparation[group]
        if type(values) is not list or len(values) > (bounds["max_pages"] if group == "pages" else bounds["max_requests"]):
            _fail("complete bounded preparation component list required")
        detached = []
        for item in values:
            maximum = bounds["max_page_bytes"] if group == "pages" else contracts.MAX_RECORD_BYTES
            raw = base._plain(item, min(maximum, bounds["max_collection_bytes"] - total))
            total += len(raw) + 1
            value = json.loads(raw)
            if group != "dependency_manifests":
                schema, fields = {"manifest": (MANIFEST_SCHEMA, MANIFEST_FIELDS), "pages": (PAGE_SCHEMA, PAGE_FIELDS),
                    "requests": (REQUEST_SCHEMA, REQUEST_FIELDS), "subjects": (SUBJECT_SCHEMA, SUBJECT_FIELDS)}[group]
                value = contracts.validate_record(value, schema=schema, fields=fields)
            detached.append(value)
        result[group] = detached[0] if group == "manifest" else detached
    if _aggregate_size(result) > bounds["max_collection_bytes"]:
        _fail("complete source-review preparation byte bound exceeded")
    return result


def _equal_components(actual, expected):
    if set(actual) != set(expected):
        _fail("complete source-review component population differs")
    for key in actual:
        left = [actual[key]] if key == "manifest" else actual[key]
        right = [expected[key]] if key == "manifest" else expected[key]
        if len(left) != len(right) or any(canonical_dag_json_bytes(a) != canonical_dag_json_bytes(b)
                                        for a, b in zip(left, right, strict=True)):
            _fail("source-review evidence differs from complete independent regeneration")


def validate_source_review_requests(preparation, *, alignment_corpus_bytes, expected_alignment_corpus_pins,
        alignment_replay_inputs, source_report_bytes, expected_source_report_pins, limits=None):
    """Repeat complete source replay, ordering and every request/subject binding."""
    bounds = _limits(limits)
    detached = _detach_preparation(preparation, bounds)
    expected = prepare_source_review_requests(alignment_corpus_bytes=alignment_corpus_bytes,
        expected_alignment_corpus_pins=expected_alignment_corpus_pins, alignment_replay_inputs=alignment_replay_inputs,
        source_report_bytes=source_report_bytes, expected_source_report_pins=expected_source_report_pins, limits=limits)
    _equal_components(detached, expected)
    if _pins(_owners()) != expected["manifest"]["producer_pins"]:
        _fail("source-review producers changed during final preparation validation")
    return detached


def _review_groups(groups, pins, subjects, owner, bounds):
    if type(groups) is not list or type(pins) is not list or len(groups) != len(subjects) or len(pins) != len(subjects):
        _fail("complete ordered source-review groups and independent pins required")
    result, total = [], 0
    for group, pin, subject in zip(groups, pins, subjects, strict=True):
        contracts.require_keys(group, {"request_cid", "reviews", "evidence_artifacts", "observed_artifact_sha256s", "observed_pins"}, "complete review group")
        contracts.require_keys(pin, {"request_cid", "reviews_sha256", "evidence_sha256s", "observed_artifacts_sha256", "observed_pins_sha256"}, "independent review group pins")
        if group["request_cid"] != subject["review_request_cid"] or pin["request_cid"] != group["request_cid"]:
            _fail("review group order or exact source request differs")
        for field in ("reviews_sha256", "observed_artifacts_sha256", "observed_pins_sha256"):
            contracts.require_sha256(pin[field], field)
        if type(group["reviews"]) is not list or len(group["reviews"]) > owner.MAX_REVIEWS:
            _fail("bounded complete per-request signed reviews required")
        if type(group["evidence_artifacts"]) is not dict or len(group["evidence_artifacts"]) > owner.MAX_EVIDENCE:
            _fail("bounded complete per-request review evidence bodies required")
        contracts.require_keys(pin["evidence_sha256s"], set(group["evidence_artifacts"]), "independent evidence body population")
        per_group = 0
        bodies = {}
        for name, raw in group["evidence_artifacts"].items():
            owner._id(name, "source-review evidence ID")
            residual = min(owner.MAX_BYTES - per_group, bounds["max_batch_review_bytes"] - total - per_group)
            if type(raw) is not bytes or len(raw) > residual:
                _fail("complete review evidence group or batch budget exhausted before hashing")
            bodies[name] = _raw(raw, pin["evidence_sha256s"][name], residual, empty=True)
            per_group += len(raw)
        detached = {"request_cid": group["request_cid"], "evidence_artifacts": bodies}
        for field, pin_field in (("reviews", "reviews_sha256"), ("observed_artifact_sha256s", "observed_artifacts_sha256"),
                                 ("observed_pins", "observed_pins_sha256")):
            residual = min(owner.MAX_BYTES - per_group, bounds["max_batch_review_bytes"] - total - per_group)
            if residual <= 0:
                _fail("complete review group or batch budget exhausted before serialization")
            raw = base._plain(group[field], residual)
            if _sha(raw) != pin[pin_field]:
                _fail("review group differs from independent complete hash")
            per_group += len(raw)
            detached[field] = json.loads(raw)
        total += per_group
        if total > bounds["max_batch_review_bytes"]:
            _fail("complete batch review evidence byte bound exceeded")
        result.append(detached)
    return result


def assess_source_review_groups(preparation, registry, policy, review_groups, *,
        expected_preparation_manifest_sha256, expected_registry_sha256, expected_policy_sha256,
        expected_review_group_pins, at_time_utc, alignment_corpus_bytes, expected_alignment_corpus_pins,
        alignment_replay_inputs, source_report_bytes, expected_source_report_pins, limits=None):
    """Replay once, then authenticate every compact group with the fixed owner."""
    bounds = _limits(limits)
    detached = _detach_preparation(preparation, bounds)
    contracts.require_sha256(expected_preparation_manifest_sha256, "complete preparation root SHA256")
    if _digest(detached["manifest"]) != expected_preparation_manifest_sha256:
        _fail("independent complete preparation root differs")
    selected_trust = []
    for value, expected in ((registry, expected_registry_sha256), (policy, expected_policy_sha256)):
        contracts.require_sha256(expected, "selected trust SHA256")
        raw = base._plain(value, 8 * 1024**2)
        if _sha(raw) != expected:
            _fail("independent selected source-review trust input differs")
        selected_trust.append(json.loads(raw))
    registry, policy = selected_trust
    pins_raw = base._plain(expected_review_group_pins, contracts.MAX_RECORD_BYTES)
    expected_review_group_pins = json.loads(pins_raw)
    owners = _owners()
    review_owner = owners[3]
    review_owner._trust(registry, policy, expected_registry_sha256, expected_policy_sha256, action=ACTION, audience=AUDIENCE)
    review_owner._time(at_time_utc)
    groups = _review_groups(review_groups, expected_review_group_pins, detached["subjects"], review_owner, bounds)
    checked = validate_source_review_requests(detached, alignment_corpus_bytes=alignment_corpus_bytes,
        expected_alignment_corpus_pins=expected_alignment_corpus_pins, alignment_replay_inputs=alignment_replay_inputs,
        source_report_bytes=source_report_bytes, expected_source_report_pins=expected_source_report_pins, limits=limits)
    producer_pins = checked["manifest"]["producer_pins"]
    domain = review_owner._ReviewDomain(SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE, ASSESSMENT_SCHEMA, _subject, ACTIVE_SLOT_COUNT)
    records, inventory, retained = [], [], 0
    for ordinal, (request, subject, manifest, group, pin) in enumerate(zip(checked["requests"], checked["subjects"],
            checked["dependency_manifests"], groups, expected_review_group_pins, strict=True)):
        assessment = review_owner._assess_reviews(subject, registry, policy, group["reviews"], manifest, domain=domain,
            expected_subject_sha256=_digest(subject), expected_registry_sha256=expected_registry_sha256,
            expected_policy_sha256=expected_policy_sha256, expected_reviews_sha256=pin["reviews_sha256"],
            expected_manifest_sha256=manifest["manifest_sha256"], at_time_utc=at_time_utc,
            observed_artifact_sha256s=group["observed_artifact_sha256s"], observed_pins=group["observed_pins"],
            evidence_artifacts=group["evidence_artifacts"])
        # The shared engine's graph-shaped compatibility fields describe only
        # this source request. No native AST, semantic graph or closure is made.
        assessment["coverage_scope"] = "exact_selected_source_request_nine_evidence_declarations_and_declared_custody_only"
        assessment.pop("assessment_sha256")
        assessment["assessment_sha256"] = review_owner.digest(assessment)
        record = contracts.seal_record({"schema": GROUP_SCHEMA, "queue_ordinal": ordinal,
            "review_request_cid": request["record_cid"], "subject_sha256": _digest(subject),
            "assessment": assessment, "deferred_review_slot_ids": request["deferred_review_slot_ids"],
            "deferred_questions_remain_pending": True, "view": "candidate", **FALSE_FLAGS, **base.UNSELECTED})
        raw = base._plain(record, min(contracts.MAX_RECORD_BYTES, bounds["max_collection_bytes"] - retained))
        retained += len(raw) + 1
        records.append(record)
        inventory.append({"ordinal": ordinal, "record_cid": record["record_cid"], "sha256": _sha(raw),
                          "request_cid": request["record_cid"]})
    pages, page_refs = _pages(inventory, bounds, assessment=True)
    root = contracts.seal_record({"schema": GROUP_MANIFEST_SCHEMA, "profile": PROFILE,
        "preparation_manifest_cid": checked["manifest"]["record_cid"], "preparation_manifest_sha256": expected_preparation_manifest_sha256,
        "registry_sha256": expected_registry_sha256, "policy_sha256": expected_policy_sha256,
        "review_group_pins": contracts.clone_json(expected_review_group_pins), "evaluation_time_utc": at_time_utc,
        "producer_pins": producer_pins, "page_refs": page_refs,
        "counts": {"groups": len(records), "authenticated_evidence": sum(row["assessment"]["authenticated_evidence_count"] for row in records),
            "pending_groups": sum(row["assessment"]["evidence_assessment_status"] == "pending" for row in records),
            "source_evidence_prerequisites_under_selected_trust": sum(row["assessment"]["review_prerequisites_satisfied_under_selected_trust"] for row in records),
            "deferred_questions": len(records) * 7}, "view": "candidate", **FALSE_FLAGS, **base.UNSELECTED})
    result = {"manifest": root, "pages": pages, "records": records}
    if _aggregate_size(result) > bounds["max_collection_bytes"]:
        _fail("complete source-review assessment collection exceeds byte bound")
    if _pins(owners) != producer_pins:
        _fail("source-review/signature producers changed during grouped authentication")
    return result


def _detach_assessment(report, bounds):
    contracts.require_keys(report, {"manifest", "pages", "records"}, "complete source-review assessment")
    result, total = {}, 0
    specs = {"manifest": (GROUP_MANIFEST_SCHEMA, GROUP_MANIFEST_FIELDS),
             "pages": (GROUP_PAGE_SCHEMA, GROUP_PAGE_FIELDS), "records": (GROUP_SCHEMA, GROUP_FIELDS)}
    for group, (schema, fields) in specs.items():
        values = [report[group]] if group == "manifest" else report[group]
        cap = bounds["max_pages"] if group == "pages" else bounds["max_requests"]
        if type(values) is not list or len(values) > cap:
            _fail("complete bounded assessment component list required")
        detached = []
        for item in values:
            maximum = bounds["max_page_bytes"] if group == "pages" else contracts.MAX_RECORD_BYTES
            raw = base._plain(item, min(maximum, bounds["max_collection_bytes"] - total))
            total += len(raw) + 1
            detached.append(contracts.validate_record(json.loads(raw), schema=schema, fields=fields))
        result[group] = detached[0] if group == "manifest" else detached
    if _aggregate_size(result) > bounds["max_collection_bytes"]:
        _fail("complete source-review assessment byte bound exceeded")
    return result


def validate_source_review_assessment(report, *args, **kwargs):
    """Regenerate every complete batch assessment under its independent inputs."""
    detached = _detach_assessment(report, _limits(kwargs.get("limits")))
    expected = assess_source_review_groups(*args, **kwargs)
    _equal_components(detached, expected)
    if _pins(_owners()) != expected["manifest"]["producer_pins"]:
        _fail("source-review producers changed during final assessment comparison")
    return expected


__all__ = ["prepare_source_review_requests", "validate_source_review_requests",
           "assess_source_review_groups", "validate_source_review_assessment"]

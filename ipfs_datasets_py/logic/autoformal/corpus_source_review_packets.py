"""Complete source-first review packets and blank guides, never decisions.

The existing source-review owner regenerates the entire original population.
Full parent/normalized/rendered views stay distinct; physical overlap does not
merge requests. These packets create no reviewer, signed claim, interpretation,
context decision, qualified training target or semantic/Lean admission.
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
from . import corpus_source_review as reviews

PROFILE = "complete-source-first-parent-grouped-review-packets/v1"
MANIFEST_SCHEMA = "legal-corpus-source-review-packets-manifest/v1"
PAGE_SCHEMA = "legal-corpus-source-review-packets-page/v1"
VIEW_SCHEMA = "legal-corpus-source-review-packet-view/v1"
DOCUMENT_SCHEMA = "legal-corpus-source-review-packet-document/v1"
DOCUMENT_PART_SCHEMA = "legal-corpus-source-review-document-structure-part/v1"
PARENT_SCHEMA = "legal-corpus-source-review-parent-packet/v1"
UNIT_SCHEMA = "legal-corpus-source-review-unit-packet/v1"
GUIDE_SCHEMA = "legal-corpus-source-review-blank-response-guide/v1"
CATALOG_SCHEMA = "legal-corpus-source-review-question-catalog/v1"
PROJECTION_SCHEMA = "legal-corpus-source-review-selector-projection-evidence/v1"
COMPARISON_SCHEMA = "legal-corpus-source-review-comparison-evidence/v1"
COMPONENTS = ("manifest", "pages", "source_views", "official_documents", "document_parts", "parent_packets", "unit_packets", "response_guides", "question_catalog", "selector_projections", "comparison_evidence")
DEFAULT_LIMITS = {"max_parents": 6, "max_source_views": 32, "max_units": 8192,
    "max_units_per_page": 64, "max_pages": 256, "max_page_bytes": contracts.MAX_RECORD_BYTES,
    "max_selector_projections": 4096, "max_document_parts": 1024, "max_document_part_items": 128,
    "max_collection_bytes": 64 * 1024**2}
FALSE_FLAGS = {**reviews.FALSE_FLAGS, **dict.fromkeys(("review_packet_reviewed", "response_recorded",
    "typed_responses_authenticated", "source_decisions_applied"), False)}
COMMON_FIELDS = {"view", *FALSE_FLAGS, *base.UNSELECTED}
FIELDS = {
    "manifest": {"profile", "limits", "source_review_limits", "source_preparation_ref", "source_input_bindings",
        "producer_pins", "page_refs", "source_view_refs", "official_document_refs", "parent_packet_refs",
        "question_catalog_ref", "selector_projection_refs", "comparison_evidence_refs", "document_part_refs", "original_context_authority",
        "counts", "population_complete", "presentation_scope", *COMMON_FIELDS},
    "pages": {"page_ordinal", "first_unit_ordinal", "entries", *COMMON_FIELDS},
    "source_views": {"origin_kind", "source_version_cid", "source_version_record", "text", "text_sha256",
        "text_cid", "char_count", "utf8_bytes", "coordinate_system", "original_field_bindings",
        "source_observation_memberships", *COMMON_FIELDS},
    "official_documents": {"document_index", "document_observation_record", "original_input_identity",
        "normalized_view_ref", "rendered_view_ref", "view_report_transport", "rendered_field_transport",
        "original_alignment_binding", *COMMON_FIELDS},
    "document_parts": {"document_index", "report_kind", "field_pointer", "first_item_index", "item_count",
        "values", "values_sha256", "original_list_sha256", *COMMON_FIELDS},
    "parent_packets": {"parent_index", "parent_record", "parent_view_ref", "unit_refs", "official_document_refs",
        "comparison_record_refs", "original_parent_row_binding", "candidate_interpretations_included", *COMMON_FIELDS},
    "unit_packets": {"queue_ordinal", "parent_index", "source_review_request", "source_review_subject_ref",
        "dependency_manifest_sha256", "parent_view_ref", "quoted_source_occurrence", "original_queue_unit",
        "original_context_unit", "comparison_record_refs", "question_catalog_ref", "candidate_interpretations_included", *COMMON_FIELDS},
    "response_guides": {"queue_ordinal", "request_cid", "request_sha256", "subject_ref", "dependency_manifest_sha256",
        "unit_packet_ref", "question_catalog_ref", "reviewer_declaration", "exposure_declaration",
        "answers", "deferred_questions", "required_existing_auth_domain", "completion_instructions", "status", *COMMON_FIELDS},
    "question_catalog": {"profile", "questions", "answer_disposition_choices", "instructions", *COMMON_FIELDS},
    "selector_projections": {"projection_index", "original_projection", "original_context_binding", "full_source_view_ref",
        "quoted_text", "coordinate_system", *COMMON_FIELDS},
    "comparison_evidence": {"parent_index", "document_index", "comparison_record", "original_alignment_comparison",
        "original_context_comparison", "original_alignment_binding", "original_context_binding", *COMMON_FIELDS},
}
SCHEMAS = dict(zip(COMPONENTS, (MANIFEST_SCHEMA, PAGE_SCHEMA, VIEW_SCHEMA, DOCUMENT_SCHEMA, DOCUMENT_PART_SCHEMA, PARENT_SCHEMA,
                              UNIT_SCHEMA, GUIDE_SCHEMA, CATALOG_SCHEMA, PROJECTION_SCHEMA, COMPARISON_SCHEMA), strict=True))
PROMPTS = {
    "definition": "Identify evidence for necessary definitions and their source/applicability, or record what is unavailable; do not assert definition closure.",
    "authority": "Record the supplied authority/publication evidence and its limits; content hashes or a URL alone do not authenticate publisher or governing law.",
    "antecedent": "Identify source evidence for antecedents or inherited references, and preserve missing or ambiguous antecedents.",
    "shared_qualifier": "Identify surrounding source evidence for shared qualifiers and list introductions; unresolved attachment stays unresolved.",
    "temporal_origin": "Record evidence for the relevant source edition, legal time and event/clock origin separately; do not infer a legal clock from acquisition time.",
    "referenced_provision": "Identify exact referenced source evidence and unavailable or competing targets; citation alone does not prove applicable meaning.",
    "producer_historical_source_correspondence": "Assess whether the supplied producer/source evidence supports a historical correspondence; preserve competing occurrences and unverified invocation or mapping.",
    "official_edition_authentication": "Record evidence for source publication and edition identity; keep declared metadata, byte custody and authenticated governing edition distinct.",
    "region_legal_classification": "Propose a region classification with exact source evidence and rationale, including whitespace/editorial/metadata or unresolved input; extractor labels are observations.",
    "definition_closure": "Deferred: complete semantic definition binding and applicability require a separate reviewed interpretation/profile.",
    "reference_closure": "Deferred: semantic reference closure is not established by source locator or citation evidence.",
    "exception_scope_closure": "Deferred: exception meaning and attachment require a separate reviewed semantic interpretation.",
    "temporal_closure": "Deferred: temporal scope and evaluation semantics require a separate supported reviewed profile.",
    "IR_semantic_fidelity": "Deferred: source-only packets contain no candidate or accepted semantic IR target.",
    "global_consistency": "Deferred: corpus consistency requires declared shared applicability, scope, time and semantics.",
    "Lean4_kernel_check": "Deferred: native kernel/build evidence requires exact generated statements, assumptions and a pinned toolchain.",
}
COMPLETION_INSTRUCTIONS = [
    "This is a blank source/context evidence guide, not a submitted or authenticated review.",
    "Preserve exact request, subject, slot, source and evidence identities in a separately versioned completed response.",
    "Unknown or unavailable evidence is a valid unresolved answer. Never convert it to a resolved or not-applicable disposition by default.",
    "Record evidence bodies and hashes, rationale, reviewer/process declarations and actual exposure. A declared principal is not verified human identity.",
    "Only the existing fixed source-review verifier may authenticate supplied source-domain signed claims under independently selected trust and explicit time.",
    "That verifier authenticates bytes; a later typed response/adjudication owner must check answer contents, disagreements and unknown-versus-complete contradictions.",
    "This owner accepts no completed responses, applies no decisions and leaves the seven semantic/proof questions deferred.",
]


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(base._plain(value, contracts.MAX_RECORD_BYTES))


def _limits(value):
    if value is not None and type(value) is not dict:
        _fail("closed lower-only packet limits required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        if key not in result or type(bound) is not int or not 0 < bound <= result[key]:
            _fail("unknown or raised source-review packet limit")
        result[key] = bound
    return result


def _candidate(schema, **value):
    payload = {"schema": schema, **value, "view": "candidate", **FALSE_FLAGS, **base.UNSELECTED}
    base._plain(payload, contracts.MAX_RECORD_BYTES)
    return contracts.seal_record(payload)


def _ref(record):
    return {"record_cid": record["record_cid"], "sha256": _digest(record), "schema": record["schema"]}


def _pins():
    result = reviews._pins(reviews._owners())
    result[str(Path(__file__).resolve())] = _sha(Path(__file__).read_bytes())
    return result


def _field_binding(report, input_binding, pointer):
    return {"report_raw_cid": input_binding["raw_cid"], "report_raw_sha256": input_binding["raw_sha256"],
        "report_canonical_sha256": input_binding["canonical_sha256"], "json_pointer": pointer,
        "value_sha256": _sha(canonical_dag_json_bytes(base._pointer(report, pointer)))}


def _document_transport(value, document_index, kind, original_binding, retain, bounds):
    """Move complete nonempty arrays into ordered parts; keep all other fields.

    Part indices address JSON array entries, never HTML or extracted text bytes.
    The transport head is explicitly not an original extraction-report schema.
    """
    if value is None:
        return None
    fields, parts_by_cid = [], {}

    def export(items, pointer):
        list_sha = _sha(canonical_dag_json_bytes(items))
        refs, pending, start, retained_bytes = [], [], 0, 0

        def seal(values):
            return _candidate(DOCUMENT_PART_SCHEMA, document_index=document_index, report_kind=kind,
                field_pointer=pointer, first_item_index=start, item_count=len(values), values=values,
                values_sha256=_sha(canonical_dag_json_bytes(values)), original_list_sha256=list_sha)

        def finish():
            if len(parts_by_cid) >= bounds['max_document_parts']:
                _fail("complete document structure part population exceeds bound")
            part = seal(pending)
            retain('document_parts', part)
            parts_by_cid[part['record_cid']] = part
            refs.append(_ref(part))

        empty_size = len(base._plain(seal([]), contracts.MAX_RECORD_BYTES))
        for index, item in enumerate(items):
            size = len(base._plain(item, contracts.MAX_RECORD_BYTES))
            # Reserve decimal-count growth and array commas in the sealed record.
            if pending and (len(pending) >= bounds['max_document_part_items']
                    or empty_size + retained_bytes + size + len(pending) + 32 > contracts.MAX_RECORD_BYTES):
                finish()
                pending, start, retained_bytes = [], index, 0
                empty_size = len(base._plain(seal([]), contracts.MAX_RECORD_BYTES))
            pending.append(item)
            retained_bytes += size
        finish()
        fields.append({'json_pointer': pointer, 'item_count': len(items),
            'original_list_sha256': list_sha, 'part_refs': refs})

    def head(item, pointer):
        if type(item) is dict:
            result = {}
            for key, child in item.items():
                path = pointer + '/' + key.replace('~', '~0').replace('/', '~1')
                if type(child) is list and child:
                    export(child, path)
                else:
                    result[key] = head(child, path)
            return result
        return item

    transport = {'document_index': document_index, 'report_kind': kind, 'head': head(value, ''), 'list_fields': fields,
        'original_value_sha256': _sha(canonical_dag_json_bytes(value)), 'original_field_binding': original_binding}
    if _reconstruct_document_transport(transport, parts_by_cid) != value:
        _fail("partitioned document structure did not reconstruct the original value")
    return transport


def _reconstruct_document_transport(transport, parts_by_cid):
    """Reconstruct exact original JSON; caller still needs fixed source replay."""
    if transport is None:
        return None
    value = json.loads(canonical_dag_json_bytes(transport['head']))
    for field in transport['list_fields']:
        items = []
        for ref in field['part_refs']:
            part = parts_by_cid[ref['record_cid']]
            if (_ref(part) != ref or part['field_pointer'] != field['json_pointer']
                    or part['document_index'] != transport['document_index'] or part['report_kind'] != transport['report_kind']
                    or part['first_item_index'] != len(items) or part['item_count'] != len(part['values'])
                    or part['values_sha256'] != _sha(canonical_dag_json_bytes(part['values']))
                    or part['original_list_sha256'] != field['original_list_sha256']):
                _fail("document part order, geometry or content differs")
            items.extend(part['values'])
        if len(items) != field['item_count'] or _sha(canonical_dag_json_bytes(items)) != field['original_list_sha256']:
            _fail("complete ordered original document array differs")
        keys = [key.replace('~1', '/').replace('~0', '~') for key in field['json_pointer'][1:].split('/')]
        parent = value
        for key in keys[:-1]:
            parent = parent[key]
        if keys[-1] in parent:
            _fail("document transport pointer overlaps retained head")
        parent[keys[-1]] = items
    if _sha(canonical_dag_json_bytes(value)) != transport['original_value_sha256']:
        _fail("reconstructed original document hash differs")
    return value


def _catalog():
    topics = [*(('context', kind) for kind in reviews.CONTEXT_KINDS), *(('handoff', kind) for kind in reviews.HANDOFF_KINDS)]
    questions = [{"category": category, "kind": kind, "prompt": PROMPTS[kind],
        "assessment_scope": "source_context_evidence_declaration" if index < 9 else "deferred_semantic_or_proof_review",
        "status": "pending_independent_review", "verified": False, "closed": False}
        for index, (category, kind) in enumerate(topics)]
    return _candidate(CATALOG_SCHEMA, profile=PROFILE, questions=questions,
        answer_disposition_choices=["unresolved", "evidence_declared", "not_applicable"],
        instructions=list(COMPLETION_INSTRUCTIONS))


def _pages(entries, bounds):
    pages, refs, pending = [], [], []
    start = 0
    def seal(items):
        return _candidate(PAGE_SCHEMA, page_ordinal=len(pages), first_unit_ordinal=start, entries=items)
    def finish():
        if len(pages) >= bounds["max_pages"]:
            _fail("complete packet page population exceeds bound")
        page = seal(pending)
        raw = base._plain(page, bounds["max_page_bytes"])
        pages.append(page)
        refs.append({**_ref(page), "page_ordinal": len(pages) - 1, "first_unit_ordinal": start,
                     "entry_count": len(pending), "sha256": _sha(raw)})
    empty_size, retained = len(canonical_dag_json_bytes(seal([]))), 0
    for entry in entries:
        size = len(canonical_dag_json_bytes(entry))
        if pending and (len(pending) >= bounds["max_units_per_page"]
                or empty_size + retained + size + len(pending) > bounds["max_page_bytes"]):
            finish()
            start, pending, retained = entry["ordinal"], [], 0
            empty_size = len(canonical_dag_json_bytes(seal([])))
        pending.append(entry)
        retained += size
    if pending:
        finish()
    return pages, refs


def _source_views(parent_records, documents, by_cid, aligned, binding, bounds):
    pending, order = {}, []
    def add(kind, version_cid, text, pointer, membership):
        if version_cid is None:
            _fail("available full source text lacks an exact source version")
        version = by_cid[version_cid]
        raw = text.encode('utf-8') if type(text) is str else None
        if (raw is None or _sha(raw) != version['extracted_view']['sha256']
                or cid_for_bytes(raw) != version['extracted_view']['cid']
                or len(text) != version['extracted_view']['character_length']
                or len(raw) != version['extracted_view']['byte_length']):
            _fail("full packet source view differs from the exact corpus version")
        original = _field_binding(aligned, binding, pointer)
        if version_cid not in pending:
            if len(order) >= bounds['max_source_views']:
                _fail("complete source view population exceeds packet bound")
            pending[version_cid] = {"origin_kind": kind, "source_version_cid": version_cid,
                "source_version_record": version, "text": text, "text_sha256": _sha(raw), "text_cid": cid_for_bytes(raw),
                "char_count": len(text), "utf8_bytes": len(raw),
                "coordinate_system": version['extracted_view']['coordinate_system'],
                "original_field_bindings": [], "source_observation_memberships": []}
            order.append(version_cid)
        row = pending[version_cid]
        if row['text'] != text or row['origin_kind'] != kind or row['source_version_record'] != version:
            _fail("reused source version has differing whole-view content or origin")
        row['original_field_bindings'].append(original)
        row['source_observation_memberships'].append(membership)
    for index, parent in enumerate(parent_records):
        view = aligned['parent_text_views_report']['views'][index]['text_view']
        if view is not None:
            add('parent_literal_field', parent['source_version_cid'], view['text'],
                f'/parent_text_views_report/views/{index}/text_view/text',
                {"parent_index": index, "parent_record_ref": _ref(parent)})
    for index, doc in enumerate(aligned['official_documents']):
        observation = documents[index]
        refs = observation['related_records']
        view = doc['view_report']
        if view['document'] is not None:
            add('official_normalized', refs['normalized_source_version_cid'], view['document']['document_text'],
                f'/official_documents/{index}/view_report/document/document_text',
                {"document_index": index, "document_observation_ref": _ref(observation)})
        rendered = doc['rendered_field_view']
        if rendered is not None:
            add('official_rendered_field', refs['rendered_source_version_cid'], rendered['text'],
                f'/official_documents/{index}/rendered_field_view/text',
                {"document_index": index, "document_observation_ref": _ref(observation)})
    records = [_candidate(VIEW_SCHEMA, **pending[cid]) for cid in order]
    return records, {item['source_version_cid']: item for item in records}


def _quote(request, by_cid, views):
    cid = request['source_occurrence_cid']
    if cid is None:
        return None
    occurrence = by_cid[cid]
    view = views[occurrence['source_version_cid']]
    text, start, end = view['text'], occurrence['start_char'], occurrence['end_char']
    if (text[start:end] != occurrence['span_text'] or len(text[:start].encode()) != occurrence['start_utf8']
            or len(text[:end].encode()) != occurrence['end_utf8']
            or _sha(occurrence['span_text'].encode()) != occurrence['span_sha256']):
        _fail("packet quotation differs from the original full-view source occurrence")
    return {"source_occurrence_record": occurrence, "source_context_record": by_cid[request['context_cid']], "full_source_view_ref": _ref(view),
        "coordinate_system": occurrence['coordinate_system'], "raw_HTML_coordinate_mapping_verified": False}


def _response_guide(unit, request, subject, manifest, catalog):
    return _candidate(GUIDE_SCHEMA, queue_ordinal=request['queue_ordinal'], request_cid=request['record_cid'],
        request_sha256=_digest(request), subject_ref=_ref(subject), dependency_manifest_sha256=manifest['manifest_sha256'],
        unit_packet_ref=_ref(unit), question_catalog_ref=_ref(catalog),
        reviewer_declaration={"principal_id": None, "role": None, "issued_at_utc": None,
            "identity_evidence_refs": [], "independence_evidence_refs": [], "process_evidence_refs": []},
        exposure_declaration={"candidate_interpretations_exposed": None, "organizer_source_metadata_exposed": None, "other_exposure": None},
        answers=[{"slot_id": item['slot_id'], "category": item['category'], "kind": item['kind'],
            "disposition": None, "finding": None, "rationale": None, "evidence_refs": []}
            for item in request['review_questions'] if item['slot_id'] in request['context_slot_ids']],
        deferred_questions=[{"slot_id": item['slot_id'], "category": item['category'], "kind": item['kind'],
            "status": "deferred_semantic_or_proof_review", "answer": None}
            for item in request['review_questions'] if item['slot_id'] in request['deferred_review_slot_ids']],
        required_existing_auth_domain={"claim_schema": reviews.CLAIM_SCHEMA, "action": reviews.ACTION, "audience": reviews.AUDIENCE},
        completion_instructions=list(COMPLETION_INSTRUCTIONS), status='blank_not_a_review')


def prepare_source_review_packets(*, expected_preparation_manifest_sha256, alignment_corpus_bytes,
        expected_alignment_corpus_pins, alignment_replay_inputs, source_report_bytes,
        expected_source_report_pins, source_review_limits=None, limits=None):
    """Replay original sources once and retain every exact review request."""
    bounds = _limits(limits)
    source_bounds = reviews._limits(source_review_limits)
    contracts.require_sha256(expected_preparation_manifest_sha256, "independent complete source preparation hash")
    transport, corpus_pins, replay, report_raw, report_pins = reviews._snapshot(alignment_corpus_bytes,
        expected_alignment_corpus_pins, alignment_replay_inputs, source_report_bytes, expected_source_report_pins, source_bounds)
    arguments = {"alignment_corpus_bytes": transport, "expected_alignment_corpus_pins": corpus_pins,
        "alignment_replay_inputs": replay, "source_report_bytes": report_raw, "expected_source_report_pins": report_pins,
        "limits": source_review_limits}
    producer_pins = _pins()
    preparation = reviews.prepare_source_review_requests(**arguments)
    if _digest(preparation['manifest']) != expected_preparation_manifest_sha256:
        _fail("independent complete source preparation root differs")
    if len(preparation['requests']) > bounds['max_units']:
        _fail("complete original review request population exceeds packet bound")
    aligned = base._load(replay['alignment_report_bytes'], 16 * 1024**2)
    handoff = base._load(report_raw['handoff'], source_bounds['max_source_report_bytes'])
    context = base._load(report_raw['context'], source_bounds['max_source_report_bytes'])
    original_records = reviews._jsonl(replay['base_corpus_bytes']['records'], base.DEFAULT_LIMITS['max_records'])
    supplement = reviews._jsonl(transport['records'], alignment.DEFAULT_LIMITS['max_records'])
    by_cid = {row['record_cid']: row for row in [*original_records, *supplement]}
    base_manifest = base._load(replay['base_corpus_bytes']['manifest'], contracts.MAX_RECORD_BYTES)
    parents = [by_cid[cid] for cid in base_manifest['populations']['parents']]
    if len(parents) > bounds['max_parents']:
        _fail("complete original parent population exceeds packet bound")
    documents = {row['document_index']: row for row in supplement
                 if row['schema'] == alignment.OBSERVATION_SCHEMA and row['kind'] == 'document'}
    source_views, views = _source_views(parents, documents, by_cid, aligned, preparation['manifest']['input_bindings']['alignment_report'], bounds)
    catalog = _catalog()
    result = {"manifest": None, "pages": [], "source_views": source_views, "official_documents": [], "document_parts": [],
        "parent_packets": [], "unit_packets": [], "response_guides": [], "question_catalog": [catalog],
        "selector_projections": [], "comparison_evidence": []}
    retained = sum(len(base._plain(row, contracts.MAX_RECORD_BYTES)) + 1 for row in [*source_views, catalog])
    def retain(group, row):
        nonlocal retained
        if group == 'document_parts' and len(result[group]) >= bounds['max_document_parts']:
            _fail("complete document structure part population exceeds bound")
        raw = base._plain(row, min(contracts.MAX_RECORD_BYTES, bounds['max_collection_bytes'] - retained))
        retained += len(raw) + 1
        result[group].append(row)
    def view_ref(cid):
        return None if cid is None else _ref(views[cid])
    for index, doc in enumerate(aligned['official_documents']):
        original = documents[index]
        retain('official_documents', _candidate(DOCUMENT_SCHEMA, document_index=index,
            document_observation_record=original, original_input_identity=doc['input_identity'],
            normalized_view_ref=view_ref(original['related_records']['normalized_source_version_cid']),
            rendered_view_ref=view_ref(original['related_records']['rendered_source_version_cid']),
            view_report_transport=_document_transport(doc['view_report'], index, 'view_report',
                _field_binding(aligned, preparation['manifest']['input_bindings']['alignment_report'], f'/official_documents/{index}/view_report'), retain, bounds),
            rendered_field_transport=_document_transport(doc['rendered_field_view'], index, 'rendered_field_view',
                _field_binding(aligned, preparation['manifest']['input_bindings']['alignment_report'], f'/official_documents/{index}/rendered_field_view'), retain, bounds),
            original_alignment_binding=_field_binding(aligned, preparation['manifest']['input_bindings']['alignment_report'], f'/official_documents/{index}')))
    projection_values = context['selector_projection_table']
    if len(projection_values) > bounds['max_selector_projections']:
        _fail("complete original selector projection population exceeds packet bound")
    for index, projection in enumerate(projection_values):
        origin = projection['coordinate_space']
        if origin == 'parent_literal_field':
            version_cid = parents[projection['source_ref']['parent_index']]['source_version_cid']
            left, right = projection['utf8byte_start'], projection['utf8byte_end']
        elif origin == 'official_normalized_view':
            version_cid = documents[projection['source_ref']['document_index']]['related_records']['normalized_source_version_cid']
            left, right = projection['utf8_byte_start'], projection['utf8_byte_end']
        else:
            _fail("unsupported original projection coordinate origin")
        view = views[version_cid]
        text = view['text']
        lo, hi = projection['char_start'], projection['char_end']
        quoted = text[lo:hi]
        if (_sha(quoted.encode()) != projection['text_sha256'] or len(text[:lo].encode()) != left
                or len(text[:hi].encode()) != right):
            _fail("shared projection differs from its complete original coordinate owner")
        retain('selector_projections', _candidate(PROJECTION_SCHEMA, projection_index=index,
            original_projection=projection, original_context_binding=_field_binding(context,
                preparation['manifest']['input_bindings']['source_reports']['context'], f'/selector_projection_table/{index}'),
            full_source_view_ref=_ref(view), quoted_text=quoted, coordinate_system=view['coordinate_system']))
    context_comparisons = {(item['parent_index'], item['document_index']): (index, item)
                          for index, item in enumerate(context['comparison_table'])}
    compared_records = {(item['parent_index'], item['document_index']): item for item in supplement
        if item['schema'] == alignment.OBSERVATION_SCHEMA and item['kind'] == 'comparison'}
    for parent_index, row in enumerate(aligned['rows']):
        for document_index, comparison in enumerate(row['comparisons']):
            context_index, context_comparison = context_comparisons[(parent_index, document_index)]
            retain('comparison_evidence', _candidate(COMPARISON_SCHEMA, parent_index=parent_index,
                document_index=document_index, comparison_record=compared_records[(parent_index, document_index)],
                original_alignment_comparison=comparison, original_context_comparison=context_comparison,
                original_alignment_binding=_field_binding(aligned, preparation['manifest']['input_bindings']['alignment_report'],
                    f'/rows/{parent_index}/comparisons/{document_index}'),
                original_context_binding=_field_binding(context, preparation['manifest']['input_bindings']['source_reports']['context'],
                    f'/comparison_table/{context_index}')))
    entries, grouped = [], {index: [] for index in range(len(parents))}
    for request, subject, manifest in zip(preparation['requests'], preparation['subjects'], preparation['dependency_manifests'], strict=True):
        ordinal = request['queue_ordinal']
        binding = request['original_context_binding']
        original_context = None if binding is None else base._pointer(context, binding['json_pointer'])
        unit = _candidate(UNIT_SCHEMA, queue_ordinal=ordinal, parent_index=request['parent_index'],
            source_review_request=request, source_review_subject_ref=_ref(subject),
            dependency_manifest_sha256=manifest['manifest_sha256'], parent_view_ref=view_ref(request['source_version_cid']),
            quoted_source_occurrence=_quote(request, by_cid, views), original_queue_unit=handoff['queue_units'][ordinal],
            original_context_unit=original_context, comparison_record_refs=[_ref(by_cid[cid]) for cid in request['comparison_record_cids']],
            question_catalog_ref=_ref(catalog), candidate_interpretations_included=False)
        guide = _response_guide(unit, request, subject, manifest, catalog)
        retain('unit_packets', unit)
        retain('response_guides', guide)
        entry = {"ordinal": ordinal, "request_cid": request['record_cid'], "unit_packet_ref": _ref(unit), "response_guide_ref": _ref(guide)}
        entries.append(entry)
        grouped[request['parent_index']].append(entry)
    for index, parent in enumerate(parents):
        comparisons = [row for row in supplement if row['schema'] == alignment.OBSERVATION_SCHEMA
                       and row['kind'] == 'comparison' and row['parent_index'] == index]
        retain('parent_packets', _candidate(PARENT_SCHEMA, parent_index=index, parent_record=parent,
            parent_view_ref=view_ref(parent['source_version_cid']), unit_refs=grouped[index],
            official_document_refs=[_ref(doc) for doc in result['official_documents']],
            comparison_record_refs=[_ref(row) for row in comparisons], original_parent_row_binding=parent['original_row_binding'],
            candidate_interpretations_included=False))
    result['pages'], page_refs = _pages(entries, bounds)
    result['manifest'] = _candidate(MANIFEST_SCHEMA, profile=PROFILE, limits=bounds, source_review_limits=source_bounds,
        source_preparation_ref=_ref(preparation['manifest']), source_input_bindings=preparation['manifest']['input_bindings'],
        producer_pins=producer_pins, page_refs=page_refs, source_view_refs=[_ref(row) for row in source_views],
        official_document_refs=[_ref(row) for row in result['official_documents']], parent_packet_refs=[_ref(row) for row in result['parent_packets']],
        question_catalog_ref=_ref(catalog), selector_projection_refs=[_ref(row) for row in result['selector_projections']],
        document_part_refs=[_ref(row) for row in result['document_parts']],
        comparison_evidence_refs=[_ref(row) for row in result['comparison_evidence']], original_context_authority=context['authority'],
        counts={"parents": len(parents), "source_views": len(source_views),
            "source_view_kinds": dict(Counter(row['origin_kind'] for row in source_views)), "official_documents": len(documents),
            "units": len(entries), "response_guides": len(entries), "pages": len(result['pages']),
            "selector_projections": len(result['selector_projections']), "comparison_evidence": len(result['comparison_evidence']),
            "document_parts": len(result['document_parts']),
            "parent_unit_counts": [len(grouped[index]) for index in range(len(parents))], "retained_questions": len(entries) * 16,
            "blank_active_answers": len(entries) * 9, "deferred_questions": len(entries) * 7, "recorded_reviews": 0},
        population_complete=True, presentation_scope='all_original_requests_full_source_views_and_blank_evidence_guides_only')
    if reviews._aggregate_size(result) > bounds['max_collection_bytes']:
        _fail("complete source review packet collection exceeds byte bound")
    if _pins() != producer_pins:
        _fail("source packet or inherited producers changed during preparation")
    return result


def _detach(bundle, bounds):
    contracts.require_keys(bundle, COMPONENTS, "complete source review packet collection")
    result, retained = {}, 0
    caps = {"manifest": 1, "pages": bounds['max_pages'], "source_views": bounds['max_source_views'],
        "official_documents": 10, "parent_packets": bounds['max_parents'], "unit_packets": bounds['max_units'],
        "document_parts": bounds['max_document_parts'],
        "response_guides": bounds['max_units'], "question_catalog": 1,
        "selector_projections": bounds['max_selector_projections'], "comparison_evidence": bounds['max_parents'] * 10}
    for group in COMPONENTS:
        values = [bundle[group]] if group == 'manifest' else bundle[group]
        if type(values) is not list or len(values) > caps[group]:
            _fail("complete bounded packet component list required")
        detached = []
        for row in values:
            if group == 'document_parts' and (type(row) is not dict or type(row.get('values')) is not list
                    or len(row['values']) > bounds['max_document_part_items']):
                _fail("bounded complete document part items required")
            maximum = bounds['max_page_bytes'] if group == 'pages' else contracts.MAX_RECORD_BYTES
            raw = base._plain(row, min(maximum, bounds['max_collection_bytes'] - retained))
            retained += len(raw) + 1
            detached.append(contracts.validate_record(json.loads(raw), schema=SCHEMAS[group], fields=FIELDS[group]))
        result[group] = detached[0] if group == 'manifest' else detached
    if reviews._aggregate_size(result) > bounds['max_collection_bytes']:
        _fail("complete packet collection byte bound exceeded")
    return result


def validate_source_review_packets(bundle, **inputs):
    """Bound offered output first, then repeat complete original-source replay."""
    detached = _detach(bundle, _limits(inputs.get('limits')))
    expected = prepare_source_review_packets(**inputs)
    reviews._equal_components(detached, expected)
    if _pins() != expected['manifest']['producer_pins']:
        _fail("packet or inherited producers changed during final comparison")
    return detached


__all__ = ['prepare_source_review_packets', 'validate_source_review_packets']

"""Paged candidate custody across exact parent, markup and rendered origins.

Original raw/FULL report pins and complete fixed-owner replay are mandatory.
The unchanged parent corpus stays external. New physical geometries share core
IDs while every comparison, anchor, partition, block, event and fragment keeps
its own evidence record. No raw HTML offset, governing role, reviewed context,
semantic graph, training target or Lean authority is inferred.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from ipfs_datasets_py.utils import cid_utils
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_bytes

from . import corpus_contracts as contracts
from . import corpus_parent_occurrence_adapter as base
from . import corpus_source as source

SCHEMA = "legal-corpus-parent-alignment-manifest/v1"
PAGE_SCHEMA = "legal-corpus-parent-alignment-page/v1"
OBSERVATION_SCHEMA = "legal-corpus-parent-alignment-observation/v1"
PROFILE = "complete-parent-official-rendered-candidate-supplement/v1"
DEFAULT_LIMITS = {
    "max_alignment_report_bytes": 16 * 1024**2,
    "max_base_manifest_bytes": contracts.MAX_RECORD_BYTES,
    "max_base_records_bytes": 16 * 1024**2,
    "max_replay_bytes": 16 * 1024**2,
    "max_total_input_bytes": 64 * 1024**2,
    "max_records": 32768,
    "max_collection_bytes": 64 * 1024**2,
    "max_records_per_page": 256,
    "max_page_bytes": contracts.MAX_RECORD_BYTES,
    "max_pages": 256,
}
DOCUMENT_FIELDS = {
    "descriptor", "raw_bytes", "expected_descriptor_sha256", "expected_raw_sha256",
    "expected_raw_bytes", "view_report", "expected_view_report_sha256",
}
KINDS = (
    "source_version", "source_occurrence", "context", "document", "comparison", "alignment",
    "block", "parent_partition", "official_partition", "render_event", "render_fragment", "render_gap",
)
FALSE_FLAGS = {
    **base.FALSE_FLAGS,
    **dict.fromkeys(("original_parent_HTML_correspondence_verified", "raw_HTML_coordinate_mapping_verified",
                     "markup_region_legal_role_verified", "official_normalized_rendered_equivalence_verified",
                     "historical_producer_operation_verified", "native_statutory_selector_compatibility_verified"), False),
}
MANIFEST_FIELDS = {
    "profile", "limits", "base_binding", "alignment_binding", "replay_bindings", "producer_pins",
    "page_refs", "counts", "population_complete", "coverage_scope", "view", *FALSE_FLAGS, *base.UNSELECTED,
}
PAGE_FIELDS = {"page_ordinal", "first_record_ordinal", "entries", "view", *FALSE_FLAGS, *base.UNSELECTED}
OBSERVATION_FIELDS = {
    "kind", "ordinal", "parent_index", "document_index", "comparison_record_cid", "source_version_cid",
    "source_occurrence_cid", "context_cid", "related_records", "owner_identity", "observations",
    "external_binding", "view", *FALSE_FLAGS, *base.UNSELECTED,
}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _limits(value):
    if value is not None and type(value) is not dict:
        _fail("closed lower-only alignment supplement limits required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        if key not in result or type(bound) is not int or not 0 < bound <= result[key]:
            _fail("unknown or raised alignment supplement limit")
        result[key] = bound
    return result


def _owners():
    from . import (
        legal_official_document_views,
        legal_parent_source_alignment,
        legal_source_view_inventory,
    )
    return legal_parent_source_alignment, legal_official_document_views, legal_source_view_inventory


def _pins(owners):
    from . import legal_official_source_custody, legal_statutory_context
    result = base._pins(base._owners())
    modules = (base, contracts, source, cid_utils, *owners, legal_official_source_custody, legal_statutory_context)
    for path in (Path(__file__).resolve(), *(Path(module.__file__).resolve() for module in modules)):
        result[str(path)] = _sha(path.read_bytes())
    return result


def _inputs(arguments, bounds):
    """All raw pins and finite nested budgets precede operation-owner imports."""
    corpus_bytes = arguments["base_corpus_bytes"]
    corpus_pins = arguments["expected_base_corpus_pins"]
    contracts.require_keys(corpus_bytes, {"manifest", "records"}, "complete base corpus bytes")
    contracts.require_keys(corpus_pins, {"manifest", "records"}, "independent base transport hashes")
    report_bytes = arguments["base_report_bytes"]
    report_pins = arguments["expected_base_report_pins"]
    contracts.require_keys(report_bytes, base.REPORT_KEYS, "complete base original reports")
    contracts.require_keys(report_pins, base.REPORT_KEYS, "independent base original report hashes")
    alignment_pins = arguments["expected_alignment_report_pins"]
    contracts.require_keys(alignment_pins, {"raw_sha256", "canonical_sha256"}, "independent alignment hash namespaces")
    raw_items = [(corpus_bytes[key], corpus_pins[key], bounds["max_base_manifest_bytes"] if key == "manifest"
                  else bounds["max_base_records_bytes"]) for key in ("manifest", "records")]
    for key in base.REPORT_KEYS:
        contracts.require_keys(report_pins[key], {"raw_sha256", "canonical_sha256"}, "base raw/FULL hash namespaces")
        contracts.require_sha256(report_pins[key]["canonical_sha256"], "base FULL report hash")
        raw_items.append((report_bytes[key], report_pins[key]["raw_sha256"], base.DEFAULT_LIMITS["max_report_bytes"]))
    contracts.require_sha256(alignment_pins["canonical_sha256"], "alignment FULL report hash")
    raw_items.append((arguments["alignment_report_bytes"], alignment_pins["raw_sha256"], bounds["max_alignment_report_bytes"]))
    total = 0
    for raw, expected, maximum in raw_items:
        contracts.require_sha256(expected, "independent raw input hash")
        if type(raw) is not bytes or not 0 < len(raw) <= maximum or _sha(raw) != expected:
            _fail("complete immutable input differs from independent raw hash or byte bound")
        total += len(raw)
    contracts.require_sha256(arguments["expected_document_population_sha256"], "complete document population hash")
    documents = arguments["document_inputs"]
    if type(documents) is not list or len(documents) > 10:
        _fail("complete bounded document population required")
    total_raw = 0
    for item in documents:
        contracts.require_keys(item, DOCUMENT_FIELDS, "complete official source replay")
        for key in ("expected_descriptor_sha256", "expected_raw_sha256", "expected_view_report_sha256"):
            contracts.require_sha256(item[key], key)
        size, raw = item["expected_raw_bytes"], item["raw_bytes"]
        if type(size) is not int or not 0 < size <= 8 * 1024**2:
            _fail("bounded independent raw HTML size required")
        total_raw += size
        if total_raw > 8 * 1024**2:
            _fail("complete raw HTML population bound exceeded")
        if raw is not None and (type(raw) is not bytes or len(raw) != size or _sha(raw) != item["expected_raw_sha256"]):
            _fail("official source bytes differ from independent raw hash or length")
        total += 0 if raw is None else len(raw)
    residual = bounds["max_total_input_bytes"] - total
    if residual <= 0:
        _fail("complete input byte budget exhausted before nested serialization")
    contracts.require_keys(arguments["base_replay_inputs"], base.REPLAY_FIELDS, "complete base fixed replay")
    replay_raw = base._plain(arguments["base_replay_inputs"], min(bounds["max_replay_bytes"], residual))
    residual -= len(replay_raw)
    detached_documents = []
    document_bindings = []
    for item in documents:
        if residual <= 0:
            _fail("complete input byte budget exhausted before document serialization")
        metadata = {key: value for key, value in item.items() if key != "raw_bytes"}
        raw = base._plain(metadata, min(bounds["max_replay_bytes"], residual))
        residual -= len(raw)
        detached = json.loads(raw)
        document_bindings.append({"metadata_sha256": _sha(raw), "raw_body_supplied": item["raw_bytes"] is not None,
                                  "raw_sha256": item["expected_raw_sha256"], "raw_bytes": item["expected_raw_bytes"]})
        detached["raw_bytes"] = item["raw_bytes"]
        detached_documents.append(detached)
    replay = json.loads(replay_raw)
    # No original JSON or operation module is loaded until every raw/body pin and
    # exact nested UTF8/escaped-JSON/residual aggregate budget has passed.
    owners = _owners()
    producer_pins = _pins(owners)
    manifest = base._load(corpus_bytes["manifest"], bounds["max_base_manifest_bytes"])
    records = []
    if not corpus_bytes["records"].endswith(b"\n"):
        _fail("complete original JSONL transport must end with its declared newline")
    for line in corpus_bytes["records"].split(b"\n")[:-1]:
        if not line or len(line) > contracts.MAX_RECORD_BYTES or len(records) >= base.DEFAULT_LIMITS["max_records"]:
            _fail("complete bounded base JSONL records required")
        records.append(base._load(line, contracts.MAX_RECORD_BYTES))
    # Existing limits are externally bound producer declarations, never raised.
    try:
        checked_base = base.validate_parent_occurrence_corpus({"manifest": manifest, "records": records},
            report_bytes=report_bytes, expected_report_pins=report_pins, replay_inputs=replay,
            limits=manifest["limits"])
        alignment_report = base._load(arguments["alignment_report_bytes"], bounds["max_alignment_report_bytes"])
        if owners[0].parent_source_alignment_report_sha256(alignment_report) != alignment_pins["canonical_sha256"]:
            _fail("independent FULL alignment report hash differs")
        parent_report = base._load(report_bytes["parent_text_views"], base.DEFAULT_LIMITS["max_report_bytes"])
        owners[0].validate_parent_source_alignment(alignment_report, parent_report,
            expected_report_sha256=alignment_pins["canonical_sha256"],
            expected_parent_text_views_report_sha256=report_pins["parent_text_views"]["canonical_sha256"],
            parent_text_views_inputs=replay["parent_text_views_inputs"], document_inputs=detached_documents,
            expected_document_population_sha256=arguments["expected_document_population_sha256"],
            limits=alignment_report["limits"])
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError) as error:
        raise contracts.CorpusContractError("base/alignment refused complete independent original-source regeneration") from error
    if _pins(owners) != producer_pins:
        _fail("source producers changed during complete original-input replay")
    base_binding = {key: {"raw_cid": cid_for_bytes(corpus_bytes[key]), "raw_sha256": corpus_pins[key],
                         "raw_bytes": len(corpus_bytes[key])} for key in ("manifest", "records")}
    base_binding["manifest_record_cid"] = checked_base["manifest"]["record_cid"]
    alignment_binding = {"raw_cid": cid_for_bytes(arguments["alignment_report_bytes"]),
        "raw_sha256": alignment_pins["raw_sha256"], "raw_bytes": len(arguments["alignment_report_bytes"]),
        "canonical_sha256": alignment_pins["canonical_sha256"], "owner_schema": alignment_report["schema"]}
    return checked_base, alignment_report, detached_documents, base_binding, alignment_binding, {
        "base_replay_sha256": _sha(replay_raw), "document_inputs": document_bindings,
        "document_population_sha256": arguments["expected_document_population_sha256"],
        "base_original_report_pins": contracts.clone_json(report_pins),
    }, owners, producer_pins


def _external(report, binding, pointer):
    value = base._pointer(report, pointer)
    return {"report_raw_cid": binding["raw_cid"], "report_raw_sha256": binding["raw_sha256"],
            "report_canonical_sha256": binding["canonical_sha256"], "json_pointer": pointer,
            "value_sha256": _sha(base._plain(value, DEFAULT_LIMITS["max_alignment_report_bytes"]))}


def _wire_size(bundle):
    # Exact compact JSON size without bulk serialization or allocating a second
    # copy of the entire detached multi-page collection.
    return (len(b'{"manifest":,"pages":[],"records":[]}')
            + len(canonical_dag_json_bytes(bundle["manifest"]))
            + sum(len(canonical_dag_json_bytes(item)) for item in bundle["pages"])
            + sum(len(canonical_dag_json_bytes(item)) for item in bundle["records"])
            + max(0, len(bundle["pages"]) - 1) + max(0, len(bundle["records"]) - 1))


def build_parent_alignment_corpus(*, base_corpus_bytes, expected_base_corpus_pins,
        base_report_bytes, expected_base_report_pins, base_replay_inputs,
        alignment_report_bytes, expected_alignment_report_pins, document_inputs,
        expected_document_population_sha256, limits=None):
    """Build a complete new-only supplement; every envelope remains <=1 MiB."""
    bounds = _limits(limits)
    arguments = {key: value for key, value in locals().items() if key not in {"limits", "bounds"}}
    (baseline, report, documents, base_binding, alignment_binding,
     replay_bindings, owners, producer_pins) = _inputs(arguments, bounds)
    records, inventory, seen, counts = [], [], set(), Counter()
    retained = 0
    external_bindings = {}

    def external(pointer):
        if pointer not in external_bindings:
            if len(external_bindings) >= bounds["max_records"]:
                _fail("complete external binding population exceeds bound")
            external_bindings[pointer] = _external(report, alignment_binding, pointer)
        return external_bindings[pointer]

    def put(kind, record):
        nonlocal retained
        cid = record["record_cid"]
        if cid in seen or len(records) >= bounds["max_records"]:
            _fail("duplicate or over-bound complete supplement record population")
        raw = base._plain(record, min(contracts.MAX_RECORD_BYTES, bounds["max_collection_bytes"] - retained))
        retained += len(raw) + 1
        if retained > bounds["max_collection_bytes"]:
            _fail("complete supplement collection byte bound exceeded")
        seen.add(cid)
        inventory.append({"ordinal": len(records), "record_cid": cid, "sha256": _sha(raw), "kind": kind})
        records.append(record)
        counts[kind] += 1
        return record

    def observation(kind, pointer, *, parent_index=None, document_index=None, comparison=None,
                    version=None, occurrence=None, context=None, related=None, identity=None, observed=None):
        return put(kind, contracts.seal_record({
            "schema": OBSERVATION_SCHEMA, "kind": kind, "ordinal": len(records),
            "parent_index": parent_index, "document_index": document_index,
            "comparison_record_cid": None if comparison is None else comparison["record_cid"],
            "source_version_cid": None if version is None else version["record_cid"],
            "source_occurrence_cid": None if occurrence is None else occurrence["record_cid"],
            "context_cid": None if context is None else context["record_cid"],
            "related_records": related or {}, "owner_identity": identity or {}, "observations": observed or {},
            "external_binding": external(pointer),
            "view": "candidate", **FALSE_FLAGS, **base.UNSELECTED,
        }))

    by_cid = {item["record_cid"]: item for item in baseline["records"]}
    parents = [by_cid[cid] for cid in baseline["manifest"]["populations"]["parents"]]
    if len(parents) != len(report["rows"]):
        _fail("complete physical parent populations differ")
    versions, texts, raw_hashes = {}, {}, {}
    for index, (parent, row) in enumerate(zip(parents, report["rows"], strict=True)):
        identity = parent["source_identity"]
        if (any(row[key] != identity[key] for key in ("row_ordinal", "row_group", "row_group_ordinal", "raw_row_sha256"))
                or row["view_sha256"] != parent["view_sha256"]):
            _fail("alignment parent differs from complete physical corpus identity")
        view = report["parent_text_views_report"]["views"][index]["text_view"]
        if view is not None:
            version = by_cid[parent["source_version_cid"]]
            versions[("parent", index)] = version
            texts[version["record_cid"]] = view["text"]
            raw_hashes[version["record_cid"]] = view["text_sha256"]
    geometry = {}
    contexts = {}
    for item in baseline["records"]:
        if item["schema"] == source.SOURCE_OCCURRENCE_SCHEMA:
            key = (item["source_version_cid"], item["start_char"], item["end_char"], item["start_utf8"], item["end_utf8"])
            if key in geometry:
                _fail("duplicate baseline physical occurrence geometry")
            geometry[key] = item
        elif item["schema"] == source.CONTEXT_DECLARATION_SCHEMA:
            if item["source_occurrence_cid"] in contexts:
                _fail("duplicate baseline occurrence context")
            contexts[item["source_occurrence_cid"]] = item
    baseline_geometry = frozenset(geometry)
    new_parent_anchor_geometry, reused_parent_anchor_geometry = set(), set()
    anchor_baseline_counts = Counter()
    new_geometry_by_origin = Counter()

    def occurrence(origin, index, selector):
        version = versions[(origin, index)]
        text = texts[version["record_cid"]]
        lo, hi = selector["char_start"], selector["char_end"]
        left = selector["utf8byte_start"] if origin == "parent" else selector["utf8_byte_start"]
        right = selector["utf8byte_end"] if origin == "parent" else selector["utf8_byte_end"]
        if _sha(text[lo:hi].encode("utf-8")) != selector["text_sha256"]:
            _fail("original selector differs from exact declared origin text")
        key = (version["record_cid"], lo, hi, left, right)
        if key not in geometry:
            item = put("source_occurrence", source.build_source_occurrence(version,
                expected_raw_sha256=raw_hashes[version["record_cid"]], extracted_text=text,
                expected_extracted_sha256=version["extracted_view"]["sha256"],
                start_char=lo, end_char=hi, start_utf8=left, end_utf8=right, historical_aliases=[]))
            geometry[key] = item
            new_geometry_by_origin[origin] += 1
            parent_origin = origin == "parent"
            contexts[item["record_cid"]] = put("context", source.build_context_declaration(item,
                expected_occurrence_cid=item["record_cid"], availability="required_unavailable",
                reason=("Exact physical literal-field geometry supplies no qualified governing context." if parent_origin
                        else "Exact comparison-view geometry supplies no qualified governing context."),
                context_references=[{"record_cid": version["record_cid"], "record_kind": "source_version",
                    "purpose": ("complete exact parent field; governing roles and context remain unresolved" if parent_origin
                                else "complete declared comparison view; governing roles and context remain unresolved")}],
                missing_requirements=list(base.MISSING_CONTEXT)))
        item = geometry[key]
        return item, contexts[item["record_cid"]], key

    document_records, block_records, block_occurrences, comparison_versions = {}, {}, {}, {}
    for index, item in enumerate(report["official_documents"]):
        if item["document_index"] != index:
            _fail("complete ordered official document population differs")
        view_report, rendered = item["view_report"], item["rendered_field_view"]
        descriptor = item["input_identity"]["descriptor"]
        available = view_report["document"] is not None
        for origin in ("official", "rendered"):
            if not available or origin == "rendered" and rendered is None:
                continue
            text = (view_report["document"]["document_text"] if origin == "official" else rendered["text"])
            profile = (view_report["document"]["parser_profile"] if origin == "official" else owners[0].RENDER_PROFILE)
            normalization = owners[1].NORMALIZATION_PROFILE if origin == "official" else owners[0].RENDER_PROFILE
            identity = {key: descriptor[key] for key in ("url", "legal_id", "edition", "package_id", "granule_id", "raw_sha256", "raw_bytes")}
            identity.update(origin=origin, extraction_profile=profile, normalization_profile=normalization,
                            extracted_text_sha256=_sha(text.encode("utf-8")))
            if origin == "official":
                identity["normalized_view_identity"] = view_report["normalized_view"]
            else:
                identity["decoder_profile"] = view_report["document"]["decoder_profile"]
                identity["coordinate_origin"] = rendered["coordinate_origin"]
            identity_sha = _sha(base._plain(identity, contracts.MAX_RECORD_BYTES))
            candidate_version = source.build_source_version(
                source_id="official-comparison-" + origin + ":sha256:" + identity_sha,
                release_id="govinfo:" + descriptor["package_id"] + ";granule=" + descriptor["granule_id"]
                    + ";raw-sha256=" + descriptor["raw_sha256"],
                edition=str(descriptor["edition"]), provision_id=descriptor["legal_id"],
                raw_bytes=documents[index]["raw_bytes"], expected_raw_sha256=descriptor["raw_sha256"],
                extracted_text=text, expected_extracted_sha256=identity["extracted_text_sha256"],
                extraction_profile=profile, normalization_profile=normalization, media_type="text/html", historical_aliases=[])
            version_cid = candidate_version["record_cid"]
            if version_cid in comparison_versions:
                version = comparison_versions[version_cid]
                if canonical_dag_json_bytes(version) != canonical_dag_json_bytes(candidate_version):
                    _fail("comparison source version identity collision")
            else:
                version = put("source_version", candidate_version)
                comparison_versions[version_cid] = version
            versions[(origin, index)] = version
            texts[version["record_cid"]], raw_hashes[version["record_cid"]] = text, descriptor["raw_sha256"]
        document_records[index] = observation("document", f"/official_documents/{index}", document_index=index,
            related={"normalized_source_version_cid": None if ("official", index) not in versions else versions[("official", index)]["record_cid"],
                     "rendered_source_version_cid": None if ("rendered", index) not in versions else versions[("rendered", index)]["record_cid"]},
            identity={"document_index": index}, observed={"input_identity": item["input_identity"],
                "status": view_report["status"], "issues": view_report["issues"],
                "normalized_view_observation": view_report["normalized_view"],
                "rendered_profile": None if rendered is None else rendered["profile"]})
        for block_index, block in enumerate((view_report["document"] or {}).get("blocks", [])):
            selector = {key: block[key] for key in ("char_start", "char_end", "utf8_byte_start", "utf8_byte_end")}
            selector["text_sha256"] = _sha(block["text"].encode("utf-8"))
            core, context, _ = occurrence("official", index, selector)
            block_records[(index, block_index)] = observation("block", f"/official_documents/{index}/view_report/document/blocks/{block_index}",
                document_index=index, version=versions[("official", index)], occurrence=core, context=context,
                related={"document_record_cid": document_records[index]["record_cid"]},
                identity={"block_id": block["block_id"], "block_index": block_index},
                observed={key: value for key, value in block.items() if key not in {"text", "verbatim_text"}})
            block_occurrences[(index, block_index)] = (core, context)

    comparisons, anchor_records = {}, {}
    # Snapshot classifications refer exclusively to the original baseline, even
    # when an earlier anchor in this supplement has already created the range.
    for parent_index, row in enumerate(report["rows"]):
        for comparison_index, comparison in enumerate(row["comparisons"]):
            index = comparison["document_index"]
            if index != comparison_index:
                _fail("complete ordered parent/document comparisons required")
            pointer = f"/rows/{parent_index}/comparisons/{comparison_index}"
            compared = observation("comparison", pointer, parent_index=parent_index, document_index=index,
                related={"parent_record_cid": parents[parent_index]["record_cid"], "document_record_cid": document_records[index]["record_cid"]},
                identity={"parent_index": parent_index, "document_index": index}, observed={
                    **{key: value for key, value in comparison.items() if key not in {"exact_block_alignments", "parent_partition", "official_partition"}},
                    "alignment_count": len(comparison["exact_block_alignments"]),
                    "parent_partition_count": len(comparison["parent_partition"]), "official_partition_count": len(comparison["official_partition"])})
            comparisons[(parent_index, index)] = compared
            for anchor_index, anchor in enumerate(comparison["exact_block_alignments"]):
                core, context, geometry_key = occurrence("parent", parent_index, anchor["parent_selector"])
                in_base = geometry_key in baseline_geometry
                anchor_baseline_counts["reused" if in_base else "missing"] += 1
                (reused_parent_anchor_geometry if in_base else new_parent_anchor_geometry).add(geometry_key)
                ref = anchor["official_block_ref"]
                official_core, official_context = block_occurrences[(index, ref["block_index"])]
                record = observation("alignment", pointer + f"/exact_block_alignments/{anchor_index}",
                    parent_index=parent_index, document_index=index, comparison=compared, version=versions[("parent", parent_index)],
                    occurrence=core, context=context,
                    related={"parent_record_cid": parents[parent_index]["record_cid"],
                             "official_block_record_cid": block_records[(index, ref["block_index"])]["record_cid"],
                             "official_source_occurrence_cid": official_core["record_cid"], "official_context_cid": official_context["record_cid"]},
                    identity={"alignment_id": anchor["alignment_id"], "anchor_index": anchor_index},
                    observed={**anchor, "parent_geometry_present_in_original_base": in_base})
                if anchor["alignment_id"] in anchor_records:
                    _fail("duplicate complete original alignment identity")
                anchor_records[anchor["alignment_id"]] = record

    for parent_index, row in enumerate(report["rows"]):
        for index, comparison in enumerate(row["comparisons"]):
            pointer = f"/rows/{parent_index}/comparisons/{index}"
            for origin, key, kind in (("parent", "parent_partition", "parent_partition"), ("official", "official_partition", "official_partition")):
                for piece_index, piece in enumerate(comparison[key]):
                    selector = dict(piece)
                    if origin == "parent":
                        selector["utf8byte_start"], selector["utf8byte_end"] = piece["utf8_byte_start"], piece["utf8_byte_end"]
                    core, context, _ = occurrence(origin, parent_index if origin == "parent" else index, selector)
                    observation(kind, pointer + f"/{key}/{piece_index}", parent_index=parent_index, document_index=index,
                        comparison=comparisons[(parent_index, index)], version=versions[(origin, parent_index if origin == "parent" else index)],
                        occurrence=core, context=context,
                        related={"covering_alignment_record_cids": [anchor_records[value]["record_cid"] for value in piece["alignment_ids"]]},
                        identity={"partition_piece_id": piece["partition_piece_id"], "piece_index": piece_index}, observed=piece)

    for index, item in enumerate(report["official_documents"]):
        rendered = item["rendered_field_view"]
        if rendered is None:
            continue
        fragments = {}
        for fragment_index, fragment in enumerate(rendered["fragments"]):
            core, context, _ = occurrence("rendered", index, fragment)
            fragments[fragment_index] = observation("render_fragment", f"/official_documents/{index}/rendered_field_view/fragments/{fragment_index}",
                document_index=index, version=versions[("rendered", index)], occurrence=core, context=context,
                related={"document_record_cid": document_records[index]["record_cid"]},
                identity={"fragment_index": fragment_index, "event_index": fragment["event_index"]}, observed=fragment)
        for event_index, event in enumerate(rendered["events"]):
            fragment_index = event["fragment_index"]
            observation("render_event", f"/official_documents/{index}/rendered_field_view/events/{event_index}", document_index=index,
                version=versions[("rendered", index)], related={"render_fragment_record_cid": None if fragment_index is None else fragments[fragment_index]["record_cid"]},
                identity={"event_index": event_index, "coordinate_scope": "parser_data_event_before_strip_no_HTML_byte_offsets"}, observed=event)
        for gap_index, (left, right) in enumerate(zip(rendered["fragments"], rendered["fragments"][1:], strict=False)):
            selector = {"char_start": left["char_end"], "char_end": right["char_start"],
                "utf8_byte_start": left["utf8_byte_end"], "utf8_byte_end": right["utf8_byte_start"], "text_sha256": _sha(b" ")}
            if selector["char_end"] - selector["char_start"] != 1 or selector["utf8_byte_end"] - selector["utf8_byte_start"] != 1:
                _fail("declared one-ASCII-space rendering gap differs")
            core, context, _ = occurrence("rendered", index, selector)
            # Derived gap provenance binds the real whole field and adjacent
            # original fragments. The owner report contains no fabricated gaps[].
            observation("render_gap", f"/official_documents/{index}/rendered_field_view", document_index=index,
                version=versions[("rendered", index)], occurrence=core, context=context,
                related={"left_fragment_record_cid": fragments[gap_index]["record_cid"], "right_fragment_record_cid": fragments[gap_index + 1]["record_cid"]},
                identity={"gap_index": gap_index, "derived_origin": "one_ASCII_space_between_nonempty_render_fragments/v1"}, observed=selector)

    pages, page_refs, pending = [], [], []
    first_ordinal = 0

    def page_value(entries, start):
        return contracts.seal_record({"schema": PAGE_SCHEMA, "page_ordinal": len(pages),
            "first_record_ordinal": start, "entries": entries, "view": "candidate", **FALSE_FLAGS, **base.UNSELECTED})

    def finish(entries, start):
        nonlocal retained
        if len(pages) >= bounds["max_pages"]:
            _fail("complete page population exceeds bound")
        page = page_value(entries, start)
        raw = base._plain(page, min(bounds["max_page_bytes"], bounds["max_collection_bytes"] - retained))
        retained += len(raw) + 1
        if retained > bounds["max_collection_bytes"]:
            _fail("complete records plus pages exceed collection byte bound")
        pages.append(page)
        page_refs.append({"page_cid": page["record_cid"], "sha256": _sha(raw), "page_ordinal": len(pages) - 1,
            "first_record_ordinal": start, "record_count": len(entries),
            "first_record_cid": entries[0]["record_cid"], "last_record_cid": entries[-1]["record_cid"]})

    empty_page_bytes = len(canonical_dag_json_bytes(page_value([], first_ordinal)))
    pending_entry_bytes = 0
    for entry in inventory:
        entry_bytes = len(canonical_dag_json_bytes(entry))
        trial_bytes = empty_page_bytes + pending_entry_bytes + entry_bytes + len(pending)
        if pending and (len(pending) >= bounds["max_records_per_page"] or trial_bytes > bounds["max_page_bytes"]):
            finish(pending, first_ordinal)
            first_ordinal = entry["ordinal"]
            pending = [entry]
            pending_entry_bytes = entry_bytes
            empty_page_bytes = len(canonical_dag_json_bytes(page_value([], first_ordinal)))
        else:
            pending.append(entry)
            pending_entry_bytes += entry_bytes
    if pending:
        finish(pending, first_ordinal)
    if _pins(owners) != producer_pins:
        _fail("source producers changed during complete supplement projection")
    manifest = contracts.seal_record({
        "schema": SCHEMA, "profile": PROFILE, "limits": bounds, "base_binding": base_binding,
        "alignment_binding": alignment_binding, "replay_bindings": replay_bindings, "producer_pins": producer_pins,
        "page_refs": page_refs, "counts": {
            "records": len(records), "pages": len(pages), "kinds": {key: counts[key] for key in KINDS},
            "base_records": len(baseline["records"]), "parents": len(parents), "documents": len(documents),
            "parent_anchor_observations_reusing_base": anchor_baseline_counts["reused"],
            "parent_anchor_observations_missing_in_base": anchor_baseline_counts["missing"],
            "distinct_parent_anchor_geometries_reusing_base": len(reused_parent_anchor_geometry),
            "distinct_parent_anchor_geometries_missing_in_base": len(new_parent_anchor_geometry),
            "new_physical_geometries_by_origin": {key: new_geometry_by_origin[key] for key in ("parent", "official", "rendered")},
        }, "population_complete": True,
        "coverage_scope": "complete_supplied_parent_and_official_alignment_populations_and_derived_render_join_spaces_only",
        "view": "candidate", **FALSE_FLAGS, **base.UNSELECTED,
    })
    bundle = {"manifest": manifest, "pages": pages, "records": records}
    if _wire_size(bundle) > bounds["max_collection_bytes"]:
        _fail("whole supplement including manifest/pages exceeds collection byte bound")
    if _pins(owners) != producer_pins:
        _fail("source producers changed during final manifest sealing")
    return bundle


def validate_parent_alignment_corpus(bundle, *, base_corpus_bytes, expected_base_corpus_pins,
        base_report_bytes, expected_base_report_pins, base_replay_inputs,
        alignment_report_bytes, expected_alignment_report_pins, document_inputs,
        expected_document_population_sha256, limits=None):
    """Verify every page/record then repeat complete fixed source regeneration."""
    bounds = _limits(limits)
    contracts.require_keys(bundle, {"manifest", "pages", "records"}, "complete paged alignment supplement")
    if type(bundle["pages"]) is not list or type(bundle["records"]) is not list:
        _fail("ordinary complete page and record lists required")
    if len(bundle["pages"]) > bounds["max_pages"] or len(bundle["records"]) > bounds["max_records"]:
        _fail("complete supplement population exceeds bounds")
    detached = {"manifest": None, "pages": [], "records": []}
    retained = 0
    schemas = {source.SOURCE_VERSION_SCHEMA: source._VERSION_FIELDS,
               source.SOURCE_OCCURRENCE_SCHEMA: source._OCCURRENCE_FIELDS,
               source.CONTEXT_DECLARATION_SCHEMA: source._CONTEXT_FIELDS,
               OBSERVATION_SCHEMA: OBSERVATION_FIELDS}
    for group in ("manifest", "pages", "records"):
        items = [bundle[group]] if group == "manifest" else bundle[group]
        for item in items:
            maximum = bounds["max_page_bytes"] if group == "pages" else contracts.MAX_RECORD_BYTES
            raw = base._plain(item, min(maximum, bounds["max_collection_bytes"] - retained))
            retained += len(raw) + 1
            record = json.loads(raw)
            schema = record.get("schema") if type(record) is dict else None
            if type(schema) is not str:
                _fail("ordinary supported supplement record schema required")
            fields = MANIFEST_FIELDS if group == "manifest" else PAGE_FIELDS if group == "pages" else schemas.get(schema)
            expected_schema = SCHEMA if group == "manifest" else PAGE_SCHEMA if group == "pages" else schema
            if fields is None:
                _fail("unsupported supplement record schema")
            checked = contracts.validate_record(record, schema=expected_schema, fields=fields)
            if group == "manifest":
                detached[group] = checked
            else:
                detached[group].append(checked)
    if _wire_size(detached) > bounds["max_collection_bytes"]:
        _fail("complete supplement collection byte bound exceeded")
    inventory, seen = [], set()
    for page_index, page in enumerate(detached["pages"]):
        contracts.require_int(page["page_ordinal"], "page ordinal", maximum=bounds["max_pages"])
        contracts.require_int(page["first_record_ordinal"], "first record ordinal", maximum=bounds["max_records"])
        if page["page_ordinal"] != page_index or page["first_record_ordinal"] != len(inventory):
            _fail("ordered complete page offsets differ")
        if type(page["entries"]) is not list or not 0 < len(page["entries"]) <= bounds["max_records_per_page"]:
            _fail("nonempty bounded page entries required")
        for entry in page["entries"]:
            contracts.require_keys(entry, {"ordinal", "record_cid", "sha256", "kind"}, "complete ordered inventory entry")
            contracts.require_int(entry["ordinal"], "record ordinal", maximum=bounds["max_records"])
            contracts.require_cid(entry["record_cid"], "inventory record CID", codecs=("dag-json",))
            if entry["ordinal"] != len(inventory) or entry["kind"] not in KINDS or entry["record_cid"] in seen:
                _fail("duplicate, missing or reordered complete inventory entry")
            contracts.require_sha256(entry["sha256"], "whole sealed record hash")
            seen.add(entry["record_cid"])
            inventory.append(entry)
    if len(inventory) != len(detached["records"]):
        _fail("complete inventory and record populations differ")
    for entry, item in zip(inventory, detached["records"], strict=True):
        if entry["record_cid"] != item["record_cid"] or entry["sha256"] != _sha(canonical_dag_json_bytes(item)):
            _fail("complete ordered inventory record CID or hash differs")
    expected = build_parent_alignment_corpus(base_corpus_bytes=base_corpus_bytes,
        expected_base_corpus_pins=expected_base_corpus_pins, base_report_bytes=base_report_bytes,
        expected_base_report_pins=expected_base_report_pins, base_replay_inputs=base_replay_inputs,
        alignment_report_bytes=alignment_report_bytes, expected_alignment_report_pins=expected_alignment_report_pins,
        document_inputs=document_inputs, expected_document_population_sha256=expected_document_population_sha256, limits=limits)
    for group in ("manifest", "pages", "records"):
        actual_items = [detached[group]] if group == "manifest" else detached[group]
        expected_items = [expected[group]] if group == "manifest" else expected[group]
        if len(actual_items) != len(expected_items) or any(canonical_dag_json_bytes(a) != canonical_dag_json_bytes(b)
                for a, b in zip(actual_items, expected_items, strict=True)):
            _fail("alignment supplement differs from complete independent original regeneration")
    if _pins(_owners()) != expected["manifest"]["producer_pins"]:
        _fail("source producers changed during final supplement validation")
    return detached


__all__ = ["build_parent_alignment_corpus", "validate_parent_alignment_corpus"]

"""Census retained source/span targets without selecting or qualifying them.

This owner replays candidate custody and audits the current source-copy decoder.
Its independently pinned join report is retained evidence, not a fresh replay of
upstream source, Parquet or entity files. The execution owner must replay those
inputs separately. Neither structural support nor producer syntax is legal gold.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import importlib
from pathlib import Path
import re

from .legal_paired_manifest_inventory_v1 import _keys, _read_json, _wire

REQUEST_SCHEMA = "legal-source-span-target-eligibility-request/v1"
SCHEMA = "legal-source-span-target-eligibility/v1"
DECODER_PROFILE = "source_span_formula_v1"
MAX_REQUEST_BYTES = 128 * 1024
MAX_JOIN_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_ROWS = 256
MAX_BUNDLES = 16
MAX_OUTPUTS_PER_ROUTE = 128
MAX_OUTPUTS = MAX_ROWS * 3 * MAX_OUTPUTS_PER_ROUTE
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
AUTHORITY = dict.fromkeys(("source_semantics_verified", "complete_meaning_units_verified",
    "historical_occurrence_selected", "context_closure_verified", "semantic_review_verified",
    "training_qualified", "evaluation_gold_qualified", "consumer_dispatched", "model_executed",
    "checkpoint_assessed", "training_executed", "admitted", "formalized", "proof_authority",
    "Lean_admitted", "published"), False)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OWNER_PINS = None
_UNRESOLVED = ("complete_meaning_unit_unestablished", "source_occurrence_unselected", "context_unresolved",
               "source_review_unresolved", "semantic_review_unresolved", "source_role_unresolved",
               "applicability_unresolved", "dependency_unresolved", "definition_binding_unresolved",
               "exposure_unresolved", "split_unresolved")


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    _need(type(value) is str and _SHA.fullmatch(value), "exact lowercase SHA256 required")


def _same(left, right):
    return _wire(left, MAX_JOIN_BYTES) == _wire(right, MAX_JOIN_BYTES)


def _freshness():
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "eligibility producer changed since import")


def _owners():
    from . import tree_pin, legal_source_span_entity_join_v1 as join, corpus_span_adapter as adapter
    from . import corpus_contracts as contracts, corpus_graph, corpus_source, legal_paired_manifest_inventory_v1
    guard_paths = tree_pin.require_workspace_logic_tree()
    from ...optimizers.logic_theorem_optimizer import legal_span_formula as span
    from ...optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtime
    from ...optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    modules = [join, adapter, contracts, corpus_graph, corpus_source, tree_pin,
               legal_paired_manifest_inventory_v1, span, span.codec_module, runtime, consumer]
    modules.extend(importlib.import_module(value.__module__) for value in
                   (span.codec_module.CanonicalRoundTripIR, span.codec_module.LegalIRGrammarDecoder))
    root = Path(__file__).resolve().parents[3]
    paths = {Path(module.__file__).resolve() for module in modules}
    paths.update(Path(path).resolve() for path in guard_paths.values())
    paths.add(Path(__file__).resolve())
    _need(all(root in path.parents for path in paths), "eligibility owner escaped selected source tree")
    pins = {str(path): _sha(path.read_bytes()) for path in sorted(paths)}
    pins["span_implementation"] = span._implementation()
    pins["logic_tree_guard_paths"] = guard_paths
    global _OWNER_PINS
    if _OWNER_PINS is None:
        _OWNER_PINS = _read_json(_wire(pins, MAX_REQUEST_BYTES), MAX_REQUEST_BYTES, "owner pins")
    _need(pins == _OWNER_PINS, "eligibility operation owner changed since first use")
    return join, adapter, contracts, span, runtime, pins


def _preflight(request_raw, join_raw, expected_request_sha256):
    _digest(expected_request_sha256)
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_REQUEST_BYTES
          and _sha(request_raw) == expected_request_sha256,
          "request bytes differ from independent pin")
    request = _read_json(request_raw, MAX_REQUEST_BYTES, "eligibility request")
    _keys(request, {"schema", "join_manifest_raw_sha256", "join_manifest_sha256",
                    "expected_physical_ids", "decoder_profile", "latent_dimension"}, "eligibility request")
    _need(request["schema"] == REQUEST_SCHEMA and request["decoder_profile"] == DECODER_PROFILE,
          "unsupported eligibility profile")
    _need(type(request["latent_dimension"]) is int and request["latent_dimension"] in (0, 384),
          "explicit supported latent dimension required")
    for field in ("join_manifest_raw_sha256", "join_manifest_sha256"):
        _digest(request[field])
    _need(type(join_raw) is bytes and 0 < len(join_raw) <= MAX_JOIN_BYTES
          and _sha(join_raw) == request["join_manifest_raw_sha256"],
          "retained join bytes differ from independent pin")
    join = _read_json(join_raw, MAX_JOIN_BYTES, "retained join manifest")
    _need(_sha(_wire(join, MAX_JOIN_BYTES)) == request["join_manifest_sha256"],
          "retained join canonical identity differs")
    ids = request["expected_physical_ids"]
    _need(type(ids) is list and len(ids) <= MAX_ROWS, "bounded ordered physical population required")
    for identity in ids:
        _digest(identity)
    _need(len(ids) == len(set(ids)), "duplicate expected physical identity")
    return request, join


def _population(join, request):
    _need(type(join) is dict and join.get("schema") == "legal-source-span-entity-join-manifest/v1"
          and join.get("selection_complete") is True, "complete selected join report required")
    _need(join.get("training_mask") == 0 and type(join.get("training_mask")) is int
          and join.get("evaluation_gold_mask") == 0 and type(join.get("evaluation_gold_mask")) is int,
          "unqualified join masks required")
    _need(type(join.get("authority")) is dict and bool(join["authority"])
          and all(value is False for value in join["authority"].values()), "unqualified join authority required")
    bundles, refs, physical = join.get("paired_bundles"), join.get("row_references"), join.get("physical_rows")
    _need(type(bundles) is list and len(bundles) <= MAX_BUNDLES and type(refs) is list
          and len(refs) <= MAX_ROWS and type(physical) is list and len(physical) <= MAX_ROWS,
          "bounded complete join populations required")
    inventory = join.get("span_inventory")
    _need(type(inventory) is dict and type(inventory.get("manifests")) is list,
          "retained selected manifest inventory required")
    selections = inventory["manifests"]
    _need(len(selections) == len(bundles), "selected manifest population differs")
    _need([entry["manifest_path_in_repo"] for entry in bundles] ==
          [entry["path_in_repo"] for entry in selections], "bundle selection population/order differs")
    flattened = []
    for bundle, selected in zip(bundles, selections):
        intake = bundle["payload_intake"]
        table = selected["manifest"]["tables"]["paired_spans"]
        rows = intake["rows"]
        _need(type(rows) is list, "ordered payload rows required")
        for row in rows:
            _keys(row, {"row_ordinal", "observation_id", "row_sha256", "derived_row_json",
                        "disposition", "candidate", "error"}, "retained payload row")
            _need(type(row["derived_row_json"]) is str and type(row["observation_id"]) is str,
                  "retained row text identities required")
            _digest(row["row_sha256"])
        _need(type(rows) is list and len(rows) <= MAX_ROWS and len(rows) == table["row_count"]
              and type(table["row_count"]) is int
              and all(type(row.get("row_ordinal")) is int for row in rows)
              and [row["row_ordinal"] for row in rows] == list(range(len(rows))),
              "complete ordered payload population required")
        _need(_same(intake["tables"]["paired_spans"], table) and intake["repository_id"] == inventory["repository_id"]
              and intake["revision"] == inventory["revision"]
              and intake["manifest_path_in_repo"] == selected["path_in_repo"]
              and intake.get("source_binding_population_supplied") is False,
              "payload identity or unbound custody differs from selection")
        for row in rows:
            identity = {"repository_id": inventory["repository_id"], "revision": inventory["revision"],
                "path_in_repo": table["path_in_repo"], "file_sha256": table["sha256"],
                "row_ordinal": row["row_ordinal"]}
            flattened.append((identity, row, selected))
    _need(len(flattened) == len(refs), "row reference population differs from complete payloads")
    derived, payloads = {}, {}
    for ordinal, ((identity, row, selected), ref) in enumerate(zip(flattened, refs)):
        digest = _sha(_wire(identity, 4096))
        _need(_same(ref["physical_identity"], identity) and ref["physical_identity_sha256"] == digest
              and ref["manifest_path_in_repo"] == selected["path_in_repo"] and ref["bank"] == selected["bank"]
              and ref["row_sha256"] == row["row_sha256"] and ref["observation_id"] == row["observation_id"]
              and ref["payload_disposition"] == row["disposition"] and ref["selected_occurrence"] is None,
              "row reference identity/order or unresolved custody differs")
        _need(type(ref["training_mask"]) is int and ref["training_mask"] == 0
              and type(ref["evaluation_gold_mask"]) is int and ref["evaluation_gold_mask"] == 0,
              "row reference masks must remain zero")
        if digest not in derived:
            derived[digest] = {"physical_identity": identity, "physical_identity_sha256": digest,
                "row_sha256": row["row_sha256"], "observation_id": row["observation_id"],
                "row_reference_ordinals": []}
            payloads[digest] = row
        _need(_same(payloads[digest], row), "conflicting payloads for one physical row")
        derived[digest]["row_reference_ordinals"].append(ordinal)
    _need(_same(list(derived.values()), physical), "physical population/order or reference ancestry differs")
    _need(list(derived) == request["expected_physical_ids"], "physical population differs from independent selection")
    counts = join.get("counts")
    _need(type(counts) is dict
          and all(type(counts.get(key)) is int for key in ("physical_paired_rows", "selected_row_references", "selected_bundles"))
          and counts.get("physical_paired_rows") == len(physical)
          and counts.get("selected_row_references") == len(refs) and counts.get("selected_bundles") == len(bundles),
          "retained join denominator differs")
    return physical, refs, payloads


def _replay_row(row, adapter, contracts):
    raw = row["derived_row_json"].encode("utf-8")
    _need(_sha(raw) == row["row_sha256"], "derived row bytes differ from retained pin")
    observed = _read_json(raw, 1024 * 1024, "derived paired row")
    _need(type(observed) is dict, "ordinary paired row object required")
    candidate, error, disposition = None, None, "candidate_unbound"
    try:
        candidate = adapter.adapt_paired_span_bytes(raw, expected_row_sha256=row["row_sha256"], source_binding=None)
    except contracts.CorpusContractError as refusal:
        disposition = "adapter_rejected"
        error = {"type": type(refusal).__name__, "message": str(refusal)[:512]}
    _need(_same([candidate, error, disposition], [row["candidate"], row["error"], row["disposition"]]),
          "retained candidate/refusal differs from full row replay")
    return observed, candidate


def prepare_source_span_target_eligibility(request_raw, join_manifest_raw, *, expected_request_sha256):
    """Replay every retained physical candidate and census all outputs, without dispatch."""
    request, retained = _preflight(request_raw, join_manifest_raw, expected_request_sha256)
    physical, refs, payloads = _population(retained, request)
    _freshness()
    join, adapter, contracts, span, runtime, before = _owners()
    before = _read_json(_wire(before, MAX_REQUEST_BYTES), MAX_REQUEST_BYTES, "owner pins")
    _need(join.source_span_entity_join_manifest_sha256(retained) == request["join_manifest_sha256"],
          "retained join owner canonical identity differs")
    description = _read_json(_wire(runtime.describe_runtime("legal_ir", request["decoder_profile"]), MAX_REQUEST_BYTES),
                             MAX_REQUEST_BYTES, "runtime description")
    rows, outputs, groups = [], [], {}
    for physical_row in physical:
        identity = physical_row["physical_identity_sha256"]
        observed, candidate = _replay_row(payloads[identity], adapter, contracts)
        source = observed.get("source")
        _need(type(source) is dict and type(source.get("text")) is str, "retained source text required")
        text, source_hash = source["text"], _sha(source["text"].encode("utf-8"))
        groups.setdefault(text, []).append(identity)
        entries, routes = [], []
        interpretations = [] if candidate is None else candidate["interpretations"]
        cursor = 0
        for producer, field in adapter.ROUTES:
            branch = observed.get(producer)
            emitted = branch.get(field) if type(branch) is dict else None
            _need(emitted is None or type(emitted) is list and len(emitted) <= MAX_OUTPUTS_PER_ROUTE,
                  "bounded output population required even for refused candidates")
            routes.append({"route": producer + "." + field, "output_count": len(emitted or []),
                "availability": "missing" if emitted is None else "outputs" if emitted else "empty"})
            for ordinal, formal in enumerate(emitted or []):
                _need(candidate is None or cursor < len(interpretations), "interpretation population incomplete")
                interpretation = None if candidate is None else interpretations[cursor]
                if interpretation is not None:
                    _need(interpretation["route"] == producer + "." + field
                          and type(interpretation["ordinal"]) is int and interpretation["ordinal"] == ordinal
                          and _same(interpretation["formal_output"], formal),
                          "interpretation population/order differs from producer outputs")
                cursor += 1
                canonical, audit = None, None
                status = "candidate_custody_refused" if candidate is None else "unsupported_formal_format"
                if interpretation is not None and formal.get("family") == "typed_deontic" \
                        and formal.get("format") == "typed-deontic-rule/v1":
                    payload = contracts.load_json_bytes(formal["payload_json"].encode("utf-8"),
                                                        expected_sha256=formal["sha256"])
                    canonical = {"rules": [payload]}
                    example = [{"id": identity + ":" + str(cursor - 1), "source_text": text, "canonical_ir": canonical}]
                    example_raw = _wire(example, 2 * 1024 * 1024)
                    audit = span.audit_examples(example)
                    _need(_wire(example, 2 * 1024 * 1024) == example_raw, "decoder audit mutated target inputs")
                    audit = _read_json(_wire(audit, MAX_REQUEST_BYTES), MAX_REQUEST_BYTES, "decoder audit")
                    _keys(audit, {"accepted_ids", "rejected_rows", "all_supported"}, "decoder audit")
                    _need(type(audit["rejected_rows"]) is list, "ordered decoder refusals required")
                    for rejection in audit["rejected_rows"]:
                        _keys(rejection, {"id", "reason"}, "decoder refusal")
                        _need(type(rejection["reason"]) is str, "decoder refusal reason required")
                    _need(type(audit["all_supported"]) is bool and
                          ((audit["accepted_ids"] == [example[0]["id"]] and audit["rejected_rows"] == [] and audit["all_supported"])
                           or (audit["accepted_ids"] == [] and type(audit["rejected_rows"]) is list
                               and len(audit["rejected_rows"]) == 1 and audit["rejected_rows"][0].get("id") == example[0]["id"]
                               and audit["all_supported"] is False)), "complete single-target decoder audit required")
                    status = "mechanically_supported" if audit["all_supported"] else "decoder_rejected"
                origin = formal.get("origin") if type(formal) is dict else None
                blockers = []
                if status != "mechanically_supported":
                    blockers.append(status)
                if origin not in ("authored_engineering_fixture", "model_generated_weak"):
                    blockers.append("unsupported_consumer_target_origin")
                if request["latent_dimension"] != 0:
                    blockers.append("consumer_requires_zero_latent")
                entries.append(len(outputs))
                outputs.append({"physical_identity_sha256": identity, "route": producer + "." + field,
                    "ordinal": ordinal, "interpretation_cid": None if interpretation is None else interpretation["record_cid"],
                    "formal_output": formal, "producer_origin": origin, "target_status": status,
                    "canonical_ir": canonical, "decoder_audit": audit,
                    "consumer_compatibility_blockers": blockers, "consumer_eligible": False,
                    "eligibility_blockers": list(_UNRESOLVED),
                    "field_masks": dict.fromkeys(FACETS, 0), "training_mask": 0, "evaluation_gold_mask": 0})
                _need(len(outputs) <= MAX_OUTPUTS, "complete output population exceeds bound")
        _need(candidate is None or cursor == len(interpretations), "interpretation population incomplete")
        rows.append({**physical_row, "source_text": text, "source_text_sha256": source_hash,
            "declared_source_text_sha256": source.get("text_sha256"), "route_inventory": routes,
            "source_unit_status": "unestablished", "meaning_unit_id": None, "selected_occurrence": None,
            "context_status": "unresolved", "source_review_status": "unresolved",
            "semantic_review_status": "unresolved", "exposure_status": "unresolved", "split_status": "unresolved",
            "source_role_status": "unresolved", "applicability_status": "unresolved",
            "dependency_status": "unresolved", "definition_binding_status": "unresolved",
            "meaning_unit_mask": 0, "source_binding_mask": 0, "context_mask": 0, "source_review_mask": 0,
            "source_role_mask": 0, "applicability_mask": 0, "dependency_mask": 0, "definition_binding_mask": 0,
            "field_masks": dict.fromkeys(FACETS, 0), "output_occurrence_ordinals": entries,
            "payload_disposition": payloads[identity]["disposition"], "consumer_eligible": False,
            "eligibility_blockers": list(_UNRESOLVED) + ([] if entries else ["no_formal_outputs"]),
            "consumer_compatibility_blockers": [],
            "training_mask": 0, "evaluation_gold_mask": 0})
    duplicates = [{"source_text_sha256": _sha(text.encode("utf-8")), "physical_ids": identities}
                  for text, identities in groups.items() if len(identities) > 1]
    duplicate_ids = {identity for group in duplicates for identity in group["physical_ids"]}
    for output in outputs:
        if output["physical_identity_sha256"] in duplicate_ids:
            output["consumer_compatibility_blockers"].append("duplicate_source_text")
    for row in rows:
        blockers = {blocker for index in row["output_occurrence_ordinals"]
                    for blocker in outputs[index]["consumer_compatibility_blockers"]}
        if not row["output_occurrence_ordinals"]:
            blockers.add("no_formal_outputs")
        if row["physical_identity_sha256"] in duplicate_ids:
            blockers.add("duplicate_source_text")
        if request["latent_dimension"] != 0:
            blockers.add("consumer_requires_zero_latent")
        row["consumer_compatibility_blockers"] = sorted(blockers)
    statuses = Counter(output["target_status"] for output in outputs)
    report = {"schema": SCHEMA, "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
        "request_sha256": expected_request_sha256, "join_manifest_raw_sha256": request["join_manifest_raw_sha256"],
        "join_manifest_sha256": request["join_manifest_sha256"], "selection_complete": True,
        "selection_scope": "pinned_retained_join_report_only", "upstream_reexecution_performed": False,
        "upstream_reexecution_requirement": "execution_owner_must_fully_replay_original_join_inputs_separately",
        "physical_rows": rows, "row_references": refs, "output_occurrences": outputs,
        "duplicate_source_groups": duplicates, "runtime_description": description, "checkpoint_status": "not_assessed",
        "consumer_profile": "zero-latent-declared-engineering-supervision/v1",
        "consumer_scope": "metadata_compatibility_only_no_binding_exposure_or_split_authorization",
        "counts": {"physical_rows": len(rows), "row_references": len(refs), "distinct_source_texts": len(groups),
            "duplicate_source_groups": len(duplicates), "rows_without_outputs": sum(not row["output_occurrence_ordinals"] for row in rows),
            "output_occurrences": len(outputs), "target_statuses": dict(sorted(statuses.items())),
            "mechanically_supported_outputs": statuses["mechanically_supported"], "consumer_eligible_rows": 0,
            "source_units_established": 0, "training_qualified_rows": 0, "evaluation_gold_rows": 0},
        "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0, "producer_pins": before,
        "producer_pins_scope": "listed_source_files_and_logic_tree_guard_not_complete_execution_closure"}
    raw = _wire(report, MAX_REPORT_BYTES)
    _need(_sha(_wire(retained, MAX_JOIN_BYTES)) == request["join_manifest_sha256"],
          "retained join snapshot changed during delegation")
    _freshness()
    _need(_same(_owners()[-1], before), "eligibility owners changed during preparation")
    _need(_same(runtime.describe_runtime("legal_ir", request["decoder_profile"]), description),
          "runtime description changed during preparation")
    return _read_json(raw, MAX_REPORT_BYTES, "eligibility report")


def source_span_target_eligibility_sha256(report):
    return _sha(_wire(report, MAX_REPORT_BYTES))


def validate_source_span_target_eligibility(report, request_raw, join_manifest_raw, *,
        expected_request_sha256, expected_report_sha256):
    """Require independent identity and full original-input census regeneration."""
    _digest(expected_report_sha256)
    offered = _read_json(report if type(report) is bytes else _wire(report, MAX_REPORT_BYTES),
                         MAX_REPORT_BYTES, "eligibility report")
    _need(source_span_target_eligibility_sha256(offered) == expected_report_sha256,
          "eligibility report SHA256 differs")
    expected = prepare_source_span_target_eligibility(request_raw, join_manifest_raw,
                                                      expected_request_sha256=expected_request_sha256)
    _need(_wire(offered, MAX_REPORT_BYTES) == _wire(expected, MAX_REPORT_BYTES),
          "eligibility report differs from full retained-input replay")
    return expected

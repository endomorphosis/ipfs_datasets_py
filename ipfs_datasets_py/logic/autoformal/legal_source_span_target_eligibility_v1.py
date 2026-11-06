"""Census source/span targets without selecting or qualifying them.

Legacy V1 and the explicitly named retained-coordinate V1 audit saved join
evidence. Public V2 and explicit V3 replay their complete original coordinate-join
inputs before and after the census under separate schemas. None of these profiles
grants source-meaning, review, consumer, training or gold authority.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import importlib
import json
from pathlib import Path
import re

from .legal_paired_manifest_inventory_v1 import _keys, _read_json, _wire

REQUEST_SCHEMA = "legal-source-span-target-eligibility-request/v1"
SCHEMA = "legal-source-span-target-eligibility/v1"
RETAINED_REQUEST_SCHEMA_V1 = "legal-source-span-retained-target-eligibility-request/v1"
RETAINED_SCHEMA_V1 = "legal-source-span-retained-target-eligibility/v1"
RETAINED_PROFILE_V1 = "retained-coordinate-target-eligibility/v1"
COORDINATE_JOIN_PROFILE = "paired-coordinate-three-cache-join/v1"
MAX_COORDINATE_ROWS = 64
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


def _preflight(request_raw, join_raw, expected_request_sha256, *, coordinate=False):
    _digest(expected_request_sha256)
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_REQUEST_BYTES
          and _sha(request_raw) == expected_request_sha256,
          "request bytes differ from independent pin")
    request = _read_json(request_raw, MAX_REQUEST_BYTES, "eligibility request")
    fields = {"schema", "join_manifest_raw_sha256", "join_manifest_sha256",
              "expected_physical_ids", "decoder_profile", "latent_dimension"}
    if coordinate:
        fields.update(("source_coordinate_report_sha256", "source_compatibility_profile"))
    _keys(request, fields, "eligibility request")
    _need(request["schema"] == (RETAINED_REQUEST_SCHEMA_V1 if coordinate else REQUEST_SCHEMA)
          and request["decoder_profile"] == DECODER_PROFILE,
          "unsupported eligibility profile")
    _need(type(request["latent_dimension"]) is int and request["latent_dimension"] in (0, 384),
          "explicit supported latent dimension required")
    for field in ("join_manifest_raw_sha256", "join_manifest_sha256"):
        _digest(request[field])
    if coordinate:
        _need(request["source_compatibility_profile"] == RETAINED_PROFILE_V1,
              "explicit retained coordinate eligibility profile required")
        _digest(request["source_coordinate_report_sha256"])
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


def _population(join, request, *, coordinate=False, wire_source=False):
    _need(not wire_source or coordinate, "wire metadata requires a coordinate population")
    schema = ("legal-source-span-entity-join-manifest/v3" if wire_source
              else "legal-source-span-entity-join-manifest/v2" if coordinate
              else "legal-source-span-entity-join-manifest/v1")
    _need(type(join) is dict and join.get("schema") == schema
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
    if coordinate:
        _need(len(bundles) == 1 and 1 <= len(refs) <= MAX_COORDINATE_ROWS
              and 1 <= len(physical) <= MAX_COORDINATE_ROWS,
              "one complete coordinate bundle and one through 64 physical rows required")
        _need(join.get("source_compatibility_profile") == (WIRE_JOIN_PROFILE_V4 if wire_source
                                                         else COORDINATE_JOIN_PROFILE)
              and join.get("selection_scope") == "exact_selected_paired_v3_bundle_with_complete_source_coordinates",
              "explicit retained coordinate join profile required")
    inventory = join.get("span_inventory")
    _need(type(inventory) is dict and type(inventory.get("manifests")) is list,
          "retained selected manifest inventory required")
    selections = inventory["manifests"]
    _need(len(selections) == len(bundles), "selected manifest population differs")
    _need([entry["manifest_path_in_repo"] for entry in bundles] ==
          [entry["path_in_repo"] for entry in selections], "bundle selection population/order differs")
    flattened = []
    for bundle, selected in zip(bundles, selections):
        if coordinate:
            _keys(bundle, {"manifest_path_in_repo", "payload_intake", "legacy_candidate_join"},
                  "retained coordinate join bundle")
            _need(bundle["legacy_candidate_join"] is None,
                  "coordinate join cannot carry a legacy candidate ledger")
        intake = bundle["payload_intake"]
        table = selected["manifest"]["tables"]["paired_spans"]
        rows = intake["rows"]
        _need(type(rows) is list, "ordered payload rows required")
        for row in rows:
            fields = {"row_ordinal", "observation_id", "row_sha256", "derived_row_json",
                      "disposition", "candidate", "error"}
            if coordinate:
                fields.update(("source_provenance_json", "source_coordinate_report_sha256",
                               "source_coordinate_span_index"))
            _keys(row, fields, "retained payload row")
            if coordinate:
                _need(type(row["source_provenance_json"]) is str
                      and type(row["source_coordinate_span_index"]) is int
                      and row["source_coordinate_span_index"] >= 0
                      and row["source_coordinate_report_sha256"] == request["source_coordinate_report_sha256"],
                      "exact coordinate provenance, report pin and integer global span index required")
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
        if coordinate:
            _need(all(_same(ref.get(key), row[key]) for key in
                      ("source_provenance_json", "source_coordinate_report_sha256", "source_coordinate_span_index"))
                  and ref.get("coordinate_transport_status") == "complete_report_occurrence_replayed"
                  and ref.get("source_candidate_record") is None
                  and type(row["disposition"]) is str
                  and row["disposition"] in ("candidate_unbound", "adapter_rejected")
                  and ref.get("source_disposition") == ("source_join_unavailable"
                      if row["disposition"] == "candidate_unbound" else "paired_candidate_adapter_rejected")
                  and ref.get("current_source_release_correspondence") == "unverified_no_independent_crosswalk"
                  and ref.get("entity_binding") == "unavailable_semantic_companions_not_supplied",
                  "row reference coordinate ancestry or unresolved source/entity custody differs")
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
    if coordinate:
        _need(type(counts.get("coordinate_occurrence_replayed_rows")) is int
              and counts["coordinate_occurrence_replayed_rows"] == len(refs),
              "coordinate occurrence denominator differs")
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


def _ordered_wire(value, maximum):
    """Retain ordinary mapping order as well as content for legacy source IDs."""
    _wire(value, maximum)
    return json.dumps(value, ensure_ascii=False, sort_keys=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _finish_custody(checks, primary):
    failures = []
    for label, check in checks:
        try:
            check()
        except BaseException as error:
            failures.append((label, error))
    if primary is not None:
        for label, error in failures:
            primary.add_note("secondary eligibility custody failure (" + label + "): "
                             + type(error).__name__ + ": " + str(error))
    elif failures:
        label, error = failures[0]
        error.add_note("closing eligibility custody check: " + label)
        for label, secondary in failures[1:]:
            error.add_note("secondary eligibility custody failure (" + label + "): "
                           + type(secondary).__name__ + ": " + str(secondary))
        raise error


def _coordinate_owners():
    from . import span_cache, uscode_ingest
    _need(callable(getattr(span_cache, "load_source_coordinate_report", None))
          and callable(getattr(span_cache, "validate_source_coordinate_rows", None)),
          "existing coordinate bytes and row validators required")
    root = Path(__file__).resolve().parent
    filenames = [module.__dict__.get("__file__") for module in (span_cache, uscode_ingest)]
    expected = [root / "span_cache.py", root / "uscode_ingest.py"]
    _need(all(type(name) is str and name == str(path) for name, path in zip(filenames, expected)),
          "coordinate owner escaped selected source tree")
    paths = [Path(name) for name in filenames]
    _need(all(path.resolve() == path for path in paths), "coordinate owner escaped selected source tree")
    return span_cache, {str(path): _sha(path.read_bytes()) for path in sorted(paths)}


def _coordinate_transport(retained, request, cache):
    """Recheck the retained carrier and exact selected references, without I/O."""
    bundle = retained["paired_bundles"][0]
    selected = retained["span_inventory"]["manifests"][0]
    intake, manifest = bundle["payload_intake"], selected["manifest"]
    pin = request["source_coordinate_report_sha256"]
    _need(intake.get("schema") == "legal-paired-payload-intake/v2"
          and manifest.get("schema") == "uscode-paired-span-bundle/v3"
          and selected.get("bank") == "paired-v3"
          and intake.get("manifest_schema") == manifest["schema"]
          and intake.get("manifest_sha256") == selected.get("sha256")
          and selected.get("source_coordinate_report_sha256") == pin,
          "explicit pinned v3 manifest and coordinate payload intake required")
    carrier = intake.get("source_coordinates")
    _keys(carrier, {"report_raw_utf8", "report_bytes", "report_artifact_sha256", "report_sha256"},
          "complete retained coordinate report carrier")
    _need(type(carrier["report_raw_utf8"]) is str and type(carrier["report_bytes"]) is int
          and 0 < carrier["report_bytes"] <= MAX_JOIN_BYTES and carrier["report_sha256"] == pin,
          "bounded exact coordinate report string, byte count and independent pin required")
    raw = carrier["report_raw_utf8"].encode("utf-8")
    _need(len(raw) == carrier["report_bytes"] and _sha(raw) == carrier["report_artifact_sha256"],
          "retained coordinate report raw byte identity differs")
    transport = manifest.get("coordinate_transport")
    _keys(transport, {"schema", "report_artifact_sha256", "report_sha256", "index_artifact_sha256"},
          "coordinate manifest transport")
    _need(transport["schema"] == "paired-source-coordinate-transport/v1"
          and transport["report_sha256"] == pin
          and transport["report_artifact_sha256"] == carrier["report_artifact_sha256"],
          "retained report carrier differs from selected manifest transport")
    _digest(transport["index_artifact_sha256"])
    projected, indices, revisions = [], [], []
    for row, reference in zip(intake["rows"], retained["row_references"]):
        observed = _read_json(row["derived_row_json"].encode("utf-8"), 1024 * 1024, "coordinate paired row")
        source = observed.get("source")
        _need(observed.get("schema_version") == "uscode-paired-span-census/v2"
              and type(source) is dict
              and all(type(source.get(key)) is str for key in ("span_id", "text", "legal_id", "revision"))
              and reference.get("producer_source_revision_label") == source["revision"],
              "exact v2 coordinate source identity and declared revision required")
        revisions.append(source["revision"])
        projected.append({"source_span_id": source["span_id"], "text": source["text"],
                          "legal_id": source["legal_id"], "source_provenance_json": row["source_provenance_json"]})
        indices.append(row["source_coordinate_span_index"])
    report = cache.load_source_coordinate_report(raw, expected_report_sha256=pin, max_bytes=MAX_JOIN_BYTES)
    _need(all(revision == report["release_id"] for revision in revisions),
          "paired source revision differs from retained coordinate report release")
    report_snapshot, rows_snapshot = _ordered_wire(report, MAX_JOIN_BYTES), _ordered_wire(projected, MAX_JOIN_BYTES)
    primary = None
    try:
        actual = cache.validate_source_coordinate_rows(report, projected, expected_report_sha256=pin)
        _need(type(actual) is list and _same(actual, indices), "coordinate global index population/order differs")
    except BaseException as error:
        primary = error
        raise
    finally:
        _finish_custody((("coordinate report snapshot", lambda: _need(
            _ordered_wire(report, MAX_JOIN_BYTES) == report_snapshot, "coordinate validator mutated retained report")),
            ("coordinate row snapshot", lambda: _need(_ordered_wire(projected, MAX_JOIN_BYTES) == rows_snapshot,
                "coordinate validator mutated selected rows"))), primary)
    return _read_json(_wire(carrier, MAX_JOIN_BYTES), MAX_JOIN_BYTES, "coordinate carrier")


def _target_census(request_raw, request, retained, physical, refs, payloads,
        adapter, contracts, span, runtime, before, description, *,
        expected_request_sha256, coordinate=False):
    """One mechanical census shared by explicit retained and original-input profiles."""
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
        coordinate_fields = ({key: payloads[identity][key] for key in
            ("source_provenance_json", "source_coordinate_report_sha256", "source_coordinate_span_index")}
            if coordinate else {})
        if coordinate:
            coordinate_fields["coordinate_transport_status"] = "complete_report_occurrence_replayed"
        rows.append({**physical_row, **coordinate_fields, "source_text": text, "source_text_sha256": source_hash,
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
    report = {"schema": RETAINED_SCHEMA_V1 if coordinate else SCHEMA, "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
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
    if coordinate:
        report["source_compatibility_profile"] = RETAINED_PROFILE_V1
    return report


def _prepare_eligibility(request_raw, join_manifest_raw, *, expected_request_sha256, coordinate=False):
    """Replay every retained physical candidate and census all outputs, without dispatch."""
    request, retained = _preflight(request_raw, join_manifest_raw, expected_request_sha256, coordinate=coordinate)
    physical, refs, payloads = _population(retained, request, coordinate=coordinate)
    _freshness()
    join, adapter, contracts, span, runtime, before = _owners()
    before = _read_json(_wire(before, MAX_REQUEST_BYTES), MAX_REQUEST_BYTES, "owner pins")
    retained_snapshot = _ordered_wire(retained, MAX_JOIN_BYTES) if coordinate else None
    coordinate_cache = coordinate_pins = coordinate_bindings = coordinate_carrier = None
    primary = None
    try:
        if coordinate:
            coordinate_cache, coordinate_pins = _coordinate_owners()
            coordinate_bindings = (coordinate_cache.load_source_coordinate_report,
                                   coordinate_cache.validate_source_coordinate_rows)
            coordinate_carrier = _coordinate_transport(retained, request, coordinate_cache)
        _need(join.source_span_entity_join_manifest_sha256(retained) == request["join_manifest_sha256"],
              "retained join owner canonical identity differs")
        description = _read_json(_wire(runtime.describe_runtime("legal_ir", request["decoder_profile"]), MAX_REQUEST_BYTES),
                                 MAX_REQUEST_BYTES, "runtime description")
        report = _target_census(request_raw, request, retained, physical, refs, payloads,
            adapter, contracts, span, runtime, before, description,
            expected_request_sha256=expected_request_sha256, coordinate=coordinate)
        if coordinate:
            report.update(source_coordinates=coordinate_carrier,
                source_coordinate_report_sha256=request["source_coordinate_report_sha256"],
                current_coordinate_producer_pins=coordinate_pins,
                retained_join_producer_pins=retained.get("producer_pins", {}),
                retained_join_producer_scope="historical_declaration_not_current_v2_join_execution",
                coordinate_validation_scope="stored_supplied_documents_and_exact_selected_references_only")
            report["counts"]["coordinate_rows_verified"] = len(physical)
        raw = _wire(report, MAX_REPORT_BYTES)
        _need(_sha(_wire(retained, MAX_JOIN_BYTES)) == request["join_manifest_sha256"],
              "retained join snapshot changed during delegation")
        _freshness()
        _need(_same(_owners()[-1], before), "eligibility owners changed during preparation")
        _need(_same(runtime.describe_runtime("legal_ir", request["decoder_profile"]), description),
              "runtime description changed during preparation")
        return _read_json(raw, MAX_REPORT_BYTES, "eligibility report")

    except BaseException as error:
        primary = error
        raise
    finally:
        if coordinate:
            checks = [("eligibility producer", _freshness),
                ("retained join snapshot", lambda: _need(
                    _ordered_wire(retained, MAX_JOIN_BYTES) == retained_snapshot,
                    "retained coordinate join changed during delegation")),
                ("operation owners", lambda: _need(_same(_owners()[-1], before),
                    "eligibility owners changed during preparation"))]
            if coordinate_cache is not None:
                checks.extend((("coordinate owners", lambda: _need(
                    _same(_coordinate_owners()[1], coordinate_pins),
                    "coordinate owners changed during preparation")),
                    ("coordinate callable bindings", lambda: _need(
                        coordinate_bindings == (coordinate_cache.load_source_coordinate_report,
                                                coordinate_cache.validate_source_coordinate_rows),
                        "coordinate helper changed during preparation"))))
            _finish_custody(checks, primary)


def prepare_source_span_target_eligibility(request_raw, join_manifest_raw, *, expected_request_sha256):
    """Replay the strict original retained v1 join without coordinate coercion."""
    return _prepare_eligibility(request_raw, join_manifest_raw,
        expected_request_sha256=expected_request_sha256)


def prepare_retained_source_span_target_eligibility_v1(request_raw, join_manifest_raw, *, expected_request_sha256):
    """Census saved coordinate rows through an explicit retained-only v1 contract.

    Stored supplied documents and exact occurrence references are replayed. The
    original physical source/span/entity operation is not executed here, and a
    current v1 join owner is not asserted to be the producer of the v2 evidence.
    """
    return _prepare_eligibility(request_raw, join_manifest_raw,
        expected_request_sha256=expected_request_sha256, coordinate=True)


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


def validate_retained_source_span_target_eligibility_v1(report, request_raw, join_manifest_raw, *,
        expected_request_sha256, expected_report_sha256):
    """Require the independent report pin and explicit retained v1 input replay."""
    _digest(expected_report_sha256)
    if type(report) is bytes:
        offered = _read_json(report, MAX_REPORT_BYTES, "coordinate eligibility report")
    else:
        offered = _read_json(_wire(report, MAX_REPORT_BYTES), MAX_REPORT_BYTES, "coordinate eligibility report")
    original = _ordered_wire(offered, MAX_REPORT_BYTES)
    _need(source_span_target_eligibility_sha256(offered) == expected_report_sha256,
          "eligibility report SHA256 differs")
    primary = None
    try:
        expected = prepare_retained_source_span_target_eligibility_v1(request_raw, join_manifest_raw,
            expected_request_sha256=expected_request_sha256)
        _need(_same(offered, expected), "eligibility report differs from full retained-input replay")
        return expected
    except BaseException as error:
        primary = error
        raise
    finally:
        def offered_unchanged():
            current = (_read_json(report, MAX_REPORT_BYTES, "coordinate eligibility report")
                       if type(report) is bytes else report)
            _need(_ordered_wire(current, MAX_REPORT_BYTES) == original,
                  "offered coordinate eligibility report changed during validation")
        _finish_custody((("offered eligibility report", offered_unchanged),), primary)


# The explicit retained v1 API above audits saved rows only. Public original-input
# v2 is preserved below; this separate v3 profile requires its own declared identity.
REQUEST_SCHEMA_V3 = "legal-source-span-target-eligibility-request/v3"
SCHEMA_V3 = "legal-source-span-target-eligibility/v3"
ORIGINAL_REPLAY_PROFILE_V3 = "original-input-coordinate-target-eligibility/v1"
REQUEST_SCHEMA_V4 = "legal-source-span-target-eligibility-request/v4"
SCHEMA_V4 = "legal-source-span-target-eligibility/v4"
ORIGINAL_WIRE_REPLAY_PROFILE_V4 = "original-input-wire-coordinate-target-eligibility/v1"
WIRE_JOIN_PROFILE_V4 = "paired-coordinate-hf-wire-three-cache-join/v1"
WIRE_METADATA_PROFILE_V4 = "hf-default-parquet-envelope/v1"
COORDINATE_REFERENCE_SCHEMA = "legal-source-span-target-coordinate-carrier-reference/v1"
MAX_COORDINATE_ORIGINAL_BYTES = 8 * 1024 * 1024
_JOIN_ORIGINAL_FIELDS = {
    "request_raw", "source_request_raw", "source_metadata_bytes",
    "paired_inventory_request_raw", "paired_manifest_bytes", "entity_info_raw",
    "expected_request_sha256", "legacy_join_inputs",
}
_COORDINATE_FIELDS = {
    "source_provenance_json", "source_coordinate_report_sha256",
    "source_coordinate_span_index",
}


def _replay_originals_v3(join_originals):
    """Detach the closed public replay arguments without serializing code."""
    _keys(join_originals, _JOIN_ORIGINAL_FIELDS, "coordinate join originals")
    captured, identity, total = {}, {}, 0
    for key in ("request_raw", "source_request_raw", "paired_inventory_request_raw", "entity_info_raw"):
        raw = join_originals[key]
        _need(type(raw) is bytes and 0 < len(raw) <= 256 * 1024,
              "bounded exact original join bytes required: " + key)
        captured[key] = raw
        identity[key] = {"bytes": len(raw), "sha256": _sha(raw)}
        total += len(raw)
    for key in ("source_metadata_bytes", "paired_manifest_bytes"):
        mapping = join_originals[key]
        _need(type(mapping) is dict and 0 < len(mapping) <= 16,
              "bounded ordinary original metadata mapping required")
        captured[key], identity[key] = {}, {}
        for name, raw in mapping.items():
            _need(type(name) is str and 0 < len(name.encode("utf-8")) <= 512
                  and type(raw) is bytes and 0 < len(raw) <= MAX_COORDINATE_ORIGINAL_BYTES,
                  "bounded exact metadata names and bytes required")
            captured[key][name] = raw
            identity[key][name] = {"bytes": len(raw), "sha256": _sha(raw)}
            total += len(raw)
    _need(total <= MAX_COORDINATE_ORIGINAL_BYTES, "coordinate original input aggregate exceeds bound")
    _digest(join_originals["expected_request_sha256"])
    captured["expected_request_sha256"] = join_originals["expected_request_sha256"]
    identity["expected_request_sha256"] = join_originals["expected_request_sha256"]
    legacy = join_originals["legacy_join_inputs"]
    _need(legacy is None or type(legacy) is dict and not legacy,
          "coordinate profile cannot mix legacy occurrence inputs")
    captured["legacy_join_inputs"] = None if legacy is None else {}
    identity["legacy_join_inputs"] = captured["legacy_join_inputs"]
    return captured, _sha(_wire(identity, MAX_REQUEST_BYTES))


def source_span_target_join_originals_sha256(join_originals):
    """Commit exact public replay inputs; this identity grants no authority."""
    return _coordinate_originals(join_originals)[1]


def _replay_preflight_v3(request_raw, join_manifest_raw, expected_request_sha256, join_originals, *,
                         wire_source=False):
    _digest(expected_request_sha256)
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_REQUEST_BYTES
          and _sha(request_raw) == expected_request_sha256,
          "request bytes differ from independent pin")
    request = _read_json(request_raw, MAX_REQUEST_BYTES, "coordinate eligibility request")
    fields = {"schema", "join_manifest_raw_sha256", "join_manifest_sha256",
        "expected_physical_ids", "decoder_profile", "latent_dimension", "join_originals_sha256",
        "source_coordinate_report_sha256", "source_compatibility_profile"}
    _keys(request, fields | ({"metadata_profile"} if wire_source else set()), "coordinate eligibility request")
    _need(request["schema"] == (REQUEST_SCHEMA_V4 if wire_source else REQUEST_SCHEMA_V3)
          and request["decoder_profile"] == DECODER_PROFILE
          and request["source_compatibility_profile"] == (ORIGINAL_WIRE_REPLAY_PROFILE_V4 if wire_source
                                                          else ORIGINAL_REPLAY_PROFILE_V3),
          "unsupported coordinate eligibility profile")
    if wire_source:
        _need(request["metadata_profile"] == WIRE_METADATA_PROFILE_V4,
              "explicit wire metadata profile required")
    _need(type(request["latent_dimension"]) is int and request["latent_dimension"] in (0, 384),
          "explicit supported latent dimension required")
    for key in ("join_manifest_raw_sha256", "join_manifest_sha256", "join_originals_sha256",
                "source_coordinate_report_sha256"):
        _digest(request[key])
    _need(type(join_manifest_raw) is bytes and 0 < len(join_manifest_raw) <= MAX_JOIN_BYTES
          and _sha(join_manifest_raw) == request["join_manifest_raw_sha256"],
          "retained join bytes differ from independent pin")
    retained = _read_json(join_manifest_raw, MAX_JOIN_BYTES, "coordinate join manifest")
    _need(_sha(_wire(retained, MAX_JOIN_BYTES)) == request["join_manifest_sha256"],
          "retained join canonical identity differs")
    _need(type(retained) is dict
          and retained.get("schema") == ("legal-source-span-entity-join-manifest/v3" if wire_source
                                         else "legal-source-span-entity-join-manifest/v2")
          and retained.get("source_compatibility_profile") == (WIRE_JOIN_PROFILE_V4 if wire_source
                                                               else COORDINATE_JOIN_PROFILE),
          "explicit wire-coordinate join v3 required" if wire_source else "explicit coordinate join v2 required")
    if wire_source:
        _wire_eligibility_source_binding(retained)
    ids = request["expected_physical_ids"]
    _need(type(ids) is list and 1 <= len(ids) <= MAX_COORDINATE_ROWS,
          "bounded nonempty ordered coordinate physical population required")
    for identity in ids:
        _digest(identity)
    _need(len(ids) == len(set(ids)), "duplicate expected physical identity")
    captured, commitment = _replay_originals_v3(join_originals)
    _need(commitment == request["join_originals_sha256"], "independent join originals commitment differs")
    return request, retained, captured


def _replay_population_v3(retained, request, *, wire_source=False):
    _need(retained.get("selection_complete") is True, "complete coordinate join required")
    physical, refs, payloads = _population(retained, request, coordinate=True, wire_source=wire_source)
    bundles = retained["paired_bundles"]
    _need(len(bundles) == 1 and len(refs) == len(physical) <= MAX_COORDINATE_ROWS,
          "one complete bounded coordinate bundle required")
    intake = bundles[0]["payload_intake"]
    _need(intake.get("schema") == "legal-paired-payload-intake/v2",
          "explicit coordinate payload v2 required")
    carrier = intake.get("source_coordinates")
    _keys(carrier, {"report_raw_utf8", "report_bytes", "report_artifact_sha256", "report_sha256"},
          "complete coordinate report carrier")
    _need(carrier["report_sha256"] == request["source_coordinate_report_sha256"],
          "coordinate report differs from independent eligibility pin")
    _need(type(carrier["report_raw_utf8"]) is str and type(carrier["report_bytes"]) is int
          and carrier["report_bytes"] == len(carrier["report_raw_utf8"].encode("utf-8"))
          and carrier["report_artifact_sha256"] == _sha(carrier["report_raw_utf8"].encode("utf-8")),
          "exact coordinate report artifact bytes required")
    entity = retained.get("entity_metadata")
    _need(type(entity) is dict and type(entity.get("verified_file_rows")) is int
          and entity["verified_file_rows"] == 0
          and entity.get("scope") == "metadata_only_no_entity_file_or_semantic_companions",
          "entity declarations must remain metadata only")
    by_physical = {}
    for row in refs:
        payload = payloads[row["physical_identity_sha256"]]
        _need(row.get("coordinate_transport_status") == "complete_report_occurrence_replayed"
              and row.get("current_source_release_correspondence") == "unverified_no_independent_crosswalk"
              and row.get("entity_binding") == "unavailable_semantic_companions_not_supplied"
              and row.get("source_candidate_record") is None,
              "coordinate custody cannot select source, edition or entity semantics")
        values = {key: row[key] for key in _COORDINATE_FIELDS}
        _need(type(values["source_coordinate_span_index"]) is int
              and values["source_coordinate_span_index"] >= 0
              and type(values["source_provenance_json"]) is str
              and values["source_coordinate_report_sha256"] == carrier["report_sha256"]
              and all(payload[key] == value for key, value in values.items()),
              "exact per-physical-row coordinate reference required")
        by_physical[row["physical_identity_sha256"]] = values
    return physical, refs, payloads, by_physical



def _prepare_original_coordinate_eligibility(request_raw, join_manifest_raw, *,
        expected_request_sha256, join_originals, wire_source=False):
    """One original-input census for the separately declared coordinate profiles.

    The v3 schema and mandatory profile grant no statutory or learning authority.
    The exact join artifact is retained once at this report layer; a typed path
    references its original coordinate carrier without copying that carrier.
    """
    request, retained, captured = _replay_preflight_v3(request_raw, join_manifest_raw,
        expected_request_sha256, join_originals, wire_source=wire_source)
    _freshness()
    join, adapter, contracts, span, runtime, before = _owners()
    validator_name = ("validate_source_span_entity_join_manifest_v3" if wire_source
                      else "validate_source_span_entity_join_manifest_v2")
    names = (validator_name, "_coordinate_owner_pins", "_owners")
    if wire_source:
        names += ("_coordinate_file_witnesses",)
    _need(all(callable(getattr(join, name, None)) for name in names),
          "original-input v4 requires the genuine wire-coordinate join v3 owner" if wire_source
          else "original-input v3 requires the genuine coordinate join v2 owner")
    before = _read_json(_wire(before, MAX_REQUEST_BYTES), MAX_REQUEST_BYTES, "owner pins")
    bindings = tuple(getattr(join, name) for name in names)
    coordinate_pins = join._coordinate_owner_pins(join._owners())
    retained_snapshot = _ordered_wire(retained, MAX_JOIN_BYTES)
    description, opened, primary = None, False, None
    request_snapshot = _ordered_wire(request, MAX_REQUEST_BYTES) if wire_source else None
    replay_returns = []
    file_plan, files, report, serialized, detached = (None,) * 5

    def originals_unchanged():
        _need(_replay_originals_v3(join_originals)[1] == request["join_originals_sha256"]
              and _replay_originals_v3(captured)[1] == request["join_originals_sha256"],
              "coordinate eligibility originals changed during operation")
        if wire_source:
            _need(_ordered_wire(request, MAX_REQUEST_BYTES) == request_snapshot,
                  "wire eligibility captured request changed during operation")

    def producers_unchanged():
        _freshness()
        _need(_same(_owners()[-1], before)
              and join._coordinate_owner_pins(join._owners()) == coordinate_pins,
              "coordinate eligibility owners changed during operation")
        _need(bindings == tuple(getattr(join, name) for name in names),
              "original-input coordinate join callable changed during operation")
        _need(_ordered_wire(retained, MAX_JOIN_BYTES) == retained_snapshot,
              "retained original-input coordinate join changed during delegation")
        if description is not None:
            _need(_same(runtime.describe_runtime("legal_ir", request["decoder_profile"]), description),
                  "runtime description changed during preparation")

    def replay_join():
        value = bindings[0](retained, expected_report_sha256=request["join_manifest_sha256"], **captured)
        if wire_source:
            _need(_same(value, retained),
                  "genuine wire join return differs from the independently pinned retained join")
            replay_returns.append((value, _ordered_wire(value, MAX_JOIN_BYTES)))

    def closing_join():
        if opened:
            replay_join()

    def files_unchanged():
        if wire_source and files is not None:
            location, selected = file_plan
            _need(_same(bindings[3](location, selected), files),
                  "wire eligibility paired files changed after original-input replay")

    def returns_unchanged():
        if wire_source:
            for value, original in replay_returns:
                _need(_ordered_wire(value, MAX_JOIN_BYTES) == original,
                      "genuine wire join return changed during eligibility preparation")
            if serialized is not None:
                _wire_eligibility_unqualified(report)
                _wire_eligibility_unqualified(detached)
                _need(_wire(report, MAX_REPORT_BYTES) == serialized
                      and _wire(detached, MAX_REPORT_BYTES) == serialized,
                      "wire eligibility result changed during closing or final serialization")

    try:
        replay_join()
        opened = True
        if wire_source:
            # A full genuine opening replay precedes all path nomination here.
            original_request = _read_json(captured["request_raw"], 256 * 1024, "original wire join request")
            location = original_request["paired_bundles"][0]
            selected = retained["span_inventory"]["manifests"][0]
            file_plan = (_read_json(_wire(location, MAX_REQUEST_BYTES), MAX_REQUEST_BYTES, "wire file root"),
                         _read_json(_wire(selected, MAX_JOIN_BYTES), MAX_JOIN_BYTES, "wire manifest witness"))
            files = bindings[3](*file_plan)
        physical, refs, payloads, coordinates = _replay_population_v3(retained, request,
                                                                    wire_source=wire_source)
        description = _read_json(_wire(runtime.describe_runtime("legal_ir", request["decoder_profile"]),
            MAX_REQUEST_BYTES), MAX_REQUEST_BYTES, "runtime description")
        report = _target_census(request_raw, request, retained, physical, refs, payloads,
            adapter, contracts, span, runtime, before, description,
            expected_request_sha256=expected_request_sha256, coordinate=True)
        carrier = retained["paired_bundles"][0]["payload_intake"]["source_coordinates"]
        report.update(schema=SCHEMA_V4 if wire_source else SCHEMA_V3,
            source_compatibility_profile=(ORIGINAL_WIRE_REPLAY_PROFILE_V4 if wire_source
                                          else ORIGINAL_REPLAY_PROFILE_V3),
            selection_scope=("fully_replayed_wire_coordinate_join_original_inputs" if wire_source
                             else "fully_replayed_coordinate_join_original_inputs"),
            upstream_reexecution_performed=True,
            upstream_reexecution_requirement=("opening_and_closing_public_wire_coordinate_join_replay" if wire_source
                                              else "opening_and_closing_public_coordinate_join_replay"),
            join_manifest_raw_utf8=join_manifest_raw.decode("utf-8"),
            join_originals_sha256=request["join_originals_sha256"],
            source_coordinate_report_sha256=request["source_coordinate_report_sha256"],
            source_coordinates_reference={"schema": COORDINATE_REFERENCE_SCHEMA,
                "container": "join_manifest_raw_utf8",
                "json_pointer": "/paired_bundles/0/payload_intake/source_coordinates",
                "join_manifest_raw_sha256": request["join_manifest_raw_sha256"],
                "report_sha256": carrier["report_sha256"],
                "report_artifact_sha256": carrier["report_artifact_sha256"],
                "report_bytes": carrier["report_bytes"]},
            current_source_release_correspondence="unverified_no_independent_crosswalk",
            entity_binding="unavailable_semantic_companions_not_supplied",
            coordinate_validation_scope=("complete_original_public_wire_coordinate_join_operation" if wire_source
                                          else "complete_original_public_coordinate_join_operation"),
            producer_pins={"eligibility": before, "coordinate_join": coordinate_pins})
        if wire_source:
            report.update(metadata_profile=WIRE_METADATA_PROFILE_V4,
                          source_metadata_intake_sha256=retained["source_metadata_intake_sha256"])
        for row in report["physical_rows"]:
            row.update(coordinates[row["physical_identity_sha256"]],
                coordinate_transport_status="complete_report_occurrence_replayed")
        for output in report["output_occurrences"]:
            output.update(coordinates[output["physical_identity_sha256"]])
        _need([row["physical_identity_sha256"] for row in report["physical_rows"]]
              == request["expected_physical_ids"], "coordinate output population changed")
        _need(all({key: row[key] for key in _COORDINATE_FIELDS}
                  == coordinates[row["physical_identity_sha256"]]
                  for row in report["physical_rows"] + report["output_occurrences"]),
              "coordinate output references changed")
        if wire_source:
            _wire_eligibility_unqualified(report)
            serialized = _wire(report, MAX_REPORT_BYTES)
            detached = _read_json(serialized, MAX_REPORT_BYTES, "wire original-input eligibility report")
            return detached
        return _read_json(_wire(report, MAX_REPORT_BYTES), MAX_REPORT_BYTES, "original-input eligibility report")
    except BaseException as error:
        primary = error
        raise
    finally:
        checks = (("original inputs", originals_unchanged),
            ("producer sources", producers_unchanged), ("closing public join replay", closing_join),
            ("post-replay original inputs", originals_unchanged),
            ("post-replay producer sources", producers_unchanged))
        if wire_source:
            checks += (("wire delegate and result witnesses", returns_unchanged),
                       ("wire paired files", files_unchanged),
                       ("final original inputs", originals_unchanged),
                       ("final producer sources", producers_unchanged))
        _finish_custody(checks, primary)


def prepare_source_span_target_eligibility_v3(request_raw, join_manifest_raw, *,
        expected_request_sha256, join_originals):
    """Census coordinate join v2 with its existing explicit original-input contract."""
    return _prepare_original_coordinate_eligibility(request_raw, join_manifest_raw,
        expected_request_sha256=expected_request_sha256, join_originals=join_originals)


def _validate_original_coordinate_eligibility(report, request_raw, join_manifest_raw, *,
        expected_request_sha256, expected_report_sha256, join_originals, wire_source=False):
    """Share authoritative original replay without converting either public schema."""
    _digest(expected_report_sha256)
    raw = report if type(report) is bytes else _wire(report, MAX_REPORT_BYTES)
    offered = _read_json(raw, MAX_REPORT_BYTES, "original-input eligibility report")
    _need(source_span_target_eligibility_sha256(offered) == expected_report_sha256,
          "eligibility report SHA256 differs")
    if wire_source:
        _need(type(offered) is dict and offered.get("schema") == SCHEMA_V4
              and offered.get("source_compatibility_profile") == ORIGINAL_WIRE_REPLAY_PROFILE_V4
              and offered.get("metadata_profile") == WIRE_METADATA_PROFILE_V4,
              "explicit wire-coordinate eligibility v4 report required")
    # Canonical identity is order-independent; snapshot the actual offered
    # object's order so an unchanged caller mapping is not a false mutation.
    original = _ordered_wire(offered if type(report) is bytes else report, MAX_REPORT_BYTES)
    primary = None
    expected, expected_snapshot, file_plan, file_witnesses = (None,) * 4
    if wire_source:
        request, retained, captured = _replay_preflight_v3(request_raw, join_manifest_raw,
            expected_request_sha256, join_originals, wire_source=True)
        request_snapshot = _ordered_wire(request, MAX_REQUEST_BYTES)
        retained_snapshot = _ordered_wire(retained, MAX_JOIN_BYTES)
        originals_commitment = request["join_originals_sha256"]
        _freshness()
        join, _, _, _, _, before = _owners()
        coordinate_pins = join._coordinate_owner_pins(join._owners())
        bindings = (join.validate_source_span_entity_join_manifest_v3, join._coordinate_file_witnesses,
                    join._coordinate_owner_pins, join._owners)

    def wire_outer_unchanged():
        if wire_source:
            _need(_ordered_wire(request, MAX_REQUEST_BYTES) == request_snapshot
                  and _ordered_wire(retained, MAX_JOIN_BYTES) == retained_snapshot,
                  "wire eligibility outer parsed request or join changed during validation")
            _need(_replay_originals_v3(join_originals)[1] == originals_commitment
                  and _replay_originals_v3(captured)[1] == originals_commitment,
                  "wire eligibility originals changed during validation finalization")
            _freshness()
            _need(_same(_owners()[-1], before)
                  and join._coordinate_owner_pins(join._owners()) == coordinate_pins
                  and bindings == (join.validate_source_span_entity_join_manifest_v3,
                      join._coordinate_file_witnesses, join._coordinate_owner_pins, join._owners),
                  "wire eligibility validation producer custody changed")
            if expected_snapshot is not None:
                _need(_ordered_wire(expected, MAX_REPORT_BYTES) == expected_snapshot,
                      "regenerated wire eligibility report changed during validation")
                _need(source_span_target_eligibility_sha256(expected) == expected_report_sha256,
                      "regenerated wire eligibility independent report commitment changed")
            if file_witnesses is not None:
                _need(_same(bindings[1](*file_plan), file_witnesses),
                      "wire eligibility physical files changed after full regeneration")
    try:
        if wire_source:
            expected = _prepare_original_coordinate_eligibility(request_raw, join_manifest_raw,
                expected_request_sha256=expected_request_sha256, join_originals=join_originals,
                wire_source=True)
        else:
            expected = prepare_source_span_target_eligibility_v3(request_raw, join_manifest_raw,
                expected_request_sha256=expected_request_sha256, join_originals=join_originals)
        _need(_same(offered, expected),
              "coordinate eligibility report differs from full original-input replay")
        if wire_source:
            expected_snapshot = _ordered_wire(expected, MAX_REPORT_BYTES)
            _need(source_span_target_eligibility_sha256(expected) == expected_report_sha256,
                  "wire eligibility regenerated report identity changed during serialization")
            wire_outer_unchanged()
            # The genuinely regenerated expected artifact nominates paths; the
            # independently hashed outer preflight objects never supply them.
            expected_join_raw = expected["join_manifest_raw_utf8"].encode("utf-8")
            _need(expected_join_raw == join_manifest_raw,
                  "regenerated wire eligibility retained different original join bytes")
            expected_join = _read_json(expected_join_raw, MAX_JOIN_BYTES, "regenerated original wire join")
            original_request = _read_json(expected_join["request_raw_utf8"].encode("utf-8"),
                                         256 * 1024, "regenerated original wire join request")
            file_plan = (original_request["paired_bundles"][0],
                         expected_join["span_inventory"]["manifests"][0])
            file_witnesses = bindings[1](*file_plan)
        return expected
    except BaseException as error:
        primary = error
        raise
    finally:
        def offered_unchanged():
            current = (_read_json(report, MAX_REPORT_BYTES, "offered coordinate eligibility report")
                       if type(report) is bytes else report)
            _need(_ordered_wire(current, MAX_REPORT_BYTES) == original,
                  "offered coordinate eligibility report changed during validation")
        checks = (("offered report", offered_unchanged),)
        if wire_source:
            checks += (("wire validation originals/owners/files", wire_outer_unchanged),)
        _finish_custody(checks, primary)


def validate_source_span_target_eligibility_v3(report, request_raw, join_manifest_raw, *,
        expected_request_sha256, expected_report_sha256, join_originals):
    """Validate the existing explicit v3 identity and original coordinate-join v2 replay."""
    return _validate_original_coordinate_eligibility(report, request_raw, join_manifest_raw,
        expected_request_sha256=expected_request_sha256, expected_report_sha256=expected_report_sha256,
        join_originals=join_originals)


# Preserve the published original-input v2 contract beside explicit retained v1
# and original-input v3. Every route reuses the one mechanical census above.
REQUEST_SCHEMA_V2 = "legal-source-span-target-eligibility-request/v2"
SCHEMA_V2 = "legal-source-span-target-eligibility/v2"
COORDINATE_PROFILE = "paired-coordinate-target-eligibility/v1"

def _population_rows(join, request, *, coordinate=False):
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
            fields = {"row_ordinal", "observation_id", "row_sha256", "derived_row_json",
                      "disposition", "candidate", "error"}
            if coordinate:
                fields |= {"source_provenance_json", "source_coordinate_report_sha256",
                           "source_coordinate_span_index"}
            _keys(row, fields, "retained payload row")
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


def _coordinate_originals(join_originals):
    """Detach the closed public replay arguments without serializing code."""
    _keys(join_originals, _JOIN_ORIGINAL_FIELDS, "coordinate join originals")
    captured, identity, total = {}, {}, 0
    for key in ("request_raw", "source_request_raw", "paired_inventory_request_raw", "entity_info_raw"):
        raw = join_originals[key]
        _need(type(raw) is bytes and 0 < len(raw) <= 256 * 1024,
              "bounded exact original join bytes required: " + key)
        captured[key] = raw
        identity[key] = {"bytes": len(raw), "sha256": _sha(raw)}
        total += len(raw)
    for key in ("source_metadata_bytes", "paired_manifest_bytes"):
        mapping = join_originals[key]
        _need(type(mapping) is dict and 0 < len(mapping) <= 16,
              "bounded ordinary original metadata mapping required")
        captured[key], identity[key] = {}, {}
        for name, raw in mapping.items():
            _need(type(name) is str and 0 < len(name.encode("utf-8")) <= 512
                  and type(raw) is bytes and 0 < len(raw) <= MAX_COORDINATE_ORIGINAL_BYTES,
                  "bounded exact metadata names and bytes required")
            captured[key][name] = raw
            identity[key][name] = {"bytes": len(raw), "sha256": _sha(raw)}
            total += len(raw)
    _need(total <= MAX_COORDINATE_ORIGINAL_BYTES, "coordinate original input aggregate exceeds bound")
    _digest(join_originals["expected_request_sha256"])
    captured["expected_request_sha256"] = join_originals["expected_request_sha256"]
    identity["expected_request_sha256"] = join_originals["expected_request_sha256"]
    legacy = join_originals["legacy_join_inputs"]
    _need(legacy is None or type(legacy) is dict and not legacy,
          "coordinate profile cannot mix legacy occurrence inputs")
    captured["legacy_join_inputs"] = None if legacy is None else {}
    identity["legacy_join_inputs"] = captured["legacy_join_inputs"]
    return captured, _sha(_wire(identity, MAX_REQUEST_BYTES))


def _coordinate_preflight(request_raw, join_manifest_raw, expected_request_sha256, join_originals):
    _digest(expected_request_sha256)
    _need(type(request_raw) is bytes and 0 < len(request_raw) <= MAX_REQUEST_BYTES
          and _sha(request_raw) == expected_request_sha256,
          "request bytes differ from independent pin")
    request = _read_json(request_raw, MAX_REQUEST_BYTES, "coordinate eligibility request")
    _keys(request, {"schema", "join_manifest_raw_sha256", "join_manifest_sha256",
        "expected_physical_ids", "decoder_profile", "latent_dimension", "join_originals_sha256",
        "source_coordinate_report_sha256"}, "coordinate eligibility request")
    _need(request["schema"] == REQUEST_SCHEMA_V2 and request["decoder_profile"] == DECODER_PROFILE,
          "unsupported coordinate eligibility profile")
    _need(type(request["latent_dimension"]) is int and request["latent_dimension"] in (0, 384),
          "explicit supported latent dimension required")
    for key in ("join_manifest_raw_sha256", "join_manifest_sha256", "join_originals_sha256",
                "source_coordinate_report_sha256"):
        _digest(request[key])
    _need(type(join_manifest_raw) is bytes and 0 < len(join_manifest_raw) <= MAX_JOIN_BYTES
          and _sha(join_manifest_raw) == request["join_manifest_raw_sha256"],
          "retained join bytes differ from independent pin")
    retained = _read_json(join_manifest_raw, MAX_JOIN_BYTES, "coordinate join manifest")
    _need(_sha(_wire(retained, MAX_JOIN_BYTES)) == request["join_manifest_sha256"],
          "retained join canonical identity differs")
    _need(type(retained) is dict and retained.get("schema") == "legal-source-span-entity-join-manifest/v2"
          and retained.get("source_compatibility_profile") == "paired-coordinate-three-cache-join/v1",
          "explicit coordinate join v2 required")
    ids = request["expected_physical_ids"]
    _need(type(ids) is list and 1 <= len(ids) <= MAX_COORDINATE_ROWS,
          "bounded nonempty ordered coordinate physical population required")
    for identity in ids:
        _digest(identity)
    _need(len(ids) == len(set(ids)), "duplicate expected physical identity")
    captured, commitment = _coordinate_originals(join_originals)
    _need(commitment == request["join_originals_sha256"], "independent join originals commitment differs")
    return request, retained, captured


def _coordinate_population(retained, request):
    _need(retained.get("selection_complete") is True, "complete coordinate join required")
    physical, refs, payloads = _population_rows(retained, request, coordinate=True)
    bundles = retained["paired_bundles"]
    _need(len(bundles) == 1 and len(refs) == len(physical) <= MAX_COORDINATE_ROWS,
          "one complete bounded coordinate bundle required")
    intake = bundles[0]["payload_intake"]
    _need(intake.get("schema") == "legal-paired-payload-intake/v2",
          "explicit coordinate payload v2 required")
    carrier = intake.get("source_coordinates")
    _keys(carrier, {"report_raw_utf8", "report_bytes", "report_artifact_sha256", "report_sha256"},
          "complete coordinate report carrier")
    _need(carrier["report_sha256"] == request["source_coordinate_report_sha256"],
          "coordinate report differs from independent eligibility pin")
    _need(type(carrier["report_raw_utf8"]) is str and type(carrier["report_bytes"]) is int
          and carrier["report_bytes"] == len(carrier["report_raw_utf8"].encode("utf-8"))
          and carrier["report_artifact_sha256"] == _sha(carrier["report_raw_utf8"].encode("utf-8")),
          "exact coordinate report artifact bytes required")
    entity = retained.get("entity_metadata")
    _need(type(entity) is dict and type(entity.get("verified_file_rows")) is int
          and entity["verified_file_rows"] == 0
          and entity.get("scope") == "metadata_only_no_entity_file_or_semantic_companions",
          "entity declarations must remain metadata only")
    by_physical = {}
    for row in refs:
        payload = payloads[row["physical_identity_sha256"]]
        _need(row.get("coordinate_transport_status") == "complete_report_occurrence_replayed"
              and row.get("current_source_release_correspondence") == "unverified_no_independent_crosswalk"
              and row.get("entity_binding") == "unavailable_semantic_companions_not_supplied"
              and row.get("source_candidate_record") is None,
              "coordinate custody cannot select source, edition or entity semantics")
        values = {key: row[key] for key in _COORDINATE_FIELDS}
        _need(type(values["source_coordinate_span_index"]) is int
              and values["source_coordinate_span_index"] >= 0
              and type(values["source_provenance_json"]) is str
              and values["source_coordinate_report_sha256"] == carrier["report_sha256"]
              and all(payload[key] == value for key, value in values.items()),
              "exact per-physical-row coordinate reference required")
        by_physical[row["physical_identity_sha256"]] = values
    return physical, refs, payloads, by_physical


def _finish_coordinate_eligibility(checks, primary):
    failures = []
    for label, check in checks:
        try:
            check()
        except BaseException as error:
            failures.append((label, error))
    if primary is not None:
        for label, error in failures:
            primary.add_note("secondary coordinate eligibility custody failure (" + label + "): "
                             + type(error).__name__ + ": " + str(error)[:512])
    elif failures:
        label, error = failures[0]
        error.add_note("closing coordinate eligibility custody check: " + label)
        for other, failure in failures[1:]:
            error.add_note("secondary closing check (" + other + "): " + str(failure)[:512])
        raise error


def prepare_source_span_target_eligibility_v2(request_raw, join_manifest_raw, *,
        expected_request_sha256, join_originals):
    """Replay original coordinate join inputs and census targets, without admission.

    The original complete report is retained once inside the exact join bytes.
    Coordinate transport never resolves statutory source or meaning eligibility.
    """
    request, retained, captured = _coordinate_preflight(request_raw, join_manifest_raw,
        expected_request_sha256, join_originals)
    _freshness()
    join, adapter, contracts, span, runtime, before = _owners()
    before = _read_json(_wire(before, MAX_REQUEST_BYTES), MAX_REQUEST_BYTES, "owner pins")
    coordinate_pins = join._coordinate_owner_pins(join._owners())
    description, opened, primary = None, False, None

    def originals_unchanged():
        _need(_coordinate_originals(join_originals)[1] == request["join_originals_sha256"]
              and _coordinate_originals(captured)[1] == request["join_originals_sha256"],
              "coordinate eligibility originals changed during operation")

    def producers_unchanged():
        _freshness()
        _need(_same(_owners()[-1], before)
              and join._coordinate_owner_pins(join._owners()) == coordinate_pins,
              "coordinate eligibility owners changed during operation")
        if description is not None:
            _need(_same(runtime.describe_runtime("legal_ir", request["decoder_profile"]), description),
                  "runtime description changed during preparation")

    def replay_join():
        join.validate_source_span_entity_join_manifest_v2(retained,
            expected_report_sha256=request["join_manifest_sha256"], **captured)

    def closing_join():
        if opened:
            replay_join()

    try:
        replay_join()
        opened = True
        physical, refs, payloads, coordinates = _coordinate_population(retained, request)
        description = _read_json(_wire(runtime.describe_runtime("legal_ir", request["decoder_profile"]),
            MAX_REQUEST_BYTES), MAX_REQUEST_BYTES, "runtime description")
        report = _target_census(request_raw, request, retained, physical, refs, payloads,
                               adapter, contracts, span, runtime, before, description,
                               expected_request_sha256=expected_request_sha256)
        report.update(schema=SCHEMA_V2, source_compatibility_profile=COORDINATE_PROFILE,
            selection_scope="fully_replayed_coordinate_join_original_inputs",
            upstream_reexecution_performed=True,
            upstream_reexecution_requirement="opening_and_closing_public_coordinate_join_replay",
            join_manifest_raw_utf8=join_manifest_raw.decode("utf-8"),
            join_originals_sha256=request["join_originals_sha256"],
            source_coordinate_report_sha256=request["source_coordinate_report_sha256"],
            current_source_release_correspondence="unverified_no_independent_crosswalk",
            entity_binding="unavailable_semantic_companions_not_supplied",
            producer_pins={"eligibility": before, "coordinate_join": coordinate_pins})
        for row in report["physical_rows"]:
            row.update(coordinates[row["physical_identity_sha256"]],
                coordinate_transport_status="complete_report_occurrence_replayed")
        for output in report["output_occurrences"]:
            output.update(coordinates[output["physical_identity_sha256"]])
        # Each physical slot/output keeps its original identity and reference.
        _need([row["physical_identity_sha256"] for row in report["physical_rows"]]
              == request["expected_physical_ids"], "coordinate output population changed")
        _need(all({key: row[key] for key in _COORDINATE_FIELDS}
                  == coordinates[row["physical_identity_sha256"]]
                  for row in report["physical_rows"] + report["output_occurrences"]),
              "coordinate output references changed")
        return _read_json(_wire(report, MAX_REPORT_BYTES), MAX_REPORT_BYTES, "coordinate eligibility report")
    except BaseException as error:
        primary = error
        raise
    finally:
        _finish_coordinate_eligibility((("original inputs", originals_unchanged),
            ("producer sources", producers_unchanged), ("closing public join replay", closing_join)), primary)


def validate_source_span_target_eligibility_v2(report, request_raw, join_manifest_raw, *,
        expected_request_sha256, expected_report_sha256, join_originals):
    """Regenerate the whole v2 report, including genuine original-input replay."""
    _digest(expected_report_sha256)
    raw = report if type(report) is bytes else _wire(report, MAX_REPORT_BYTES)
    offered = _read_json(raw, MAX_REPORT_BYTES, "coordinate eligibility report")
    _need(source_span_target_eligibility_sha256(offered) == expected_report_sha256,
          "eligibility report SHA256 differs")
    original = _wire(offered, MAX_REPORT_BYTES)
    primary = None
    try:
        expected = prepare_source_span_target_eligibility_v2(request_raw, join_manifest_raw,
            expected_request_sha256=expected_request_sha256, join_originals=join_originals)
        _need(original == _wire(expected, MAX_REPORT_BYTES),
              "coordinate eligibility report differs from full original-input replay")
        return expected
    except BaseException as error:
        primary = error
        raise
    finally:
        def offered_unchanged():
            current = _read_json(report, MAX_REPORT_BYTES, "offered coordinate eligibility report") \
                if type(report) is bytes else report
            _need(_wire(current, MAX_REPORT_BYTES) == original,
                  "offered coordinate eligibility report changed during validation")
        _finish_coordinate_eligibility((("offered report", offered_unchanged),), primary)


def _wire_eligibility_source_binding(retained):
    """Check explicit metadata identity; the genuine join owns full reconciliation."""
    source = retained.get("source_metadata_intake")
    _need(retained.get("source_metadata_profile") == WIRE_METADATA_PROFILE_V4
          and retained.get("source_metadata_request_schema") == "legal-source-package-intake-request/v2"
          and type(source) is dict and source.get("schema") == "legal-source-package-intake/v2"
          and source.get("metadata_profile") == WIRE_METADATA_PROFILE_V4
          and source.get("status") == "selected_wire_metadata_reconciled",
          "wire eligibility requires the explicit reconciled source-intake v2 identity")
    digest = retained.get("source_metadata_intake_sha256")
    _digest(digest)
    _need(_sha(_wire(source, MAX_JOIN_BYTES)) == digest,
          "wire join source-intake report commitment differs")
    _need(type(source.get("source_identity")) is dict
          and source["source_identity"].get("aliases_mapped") is False,
          "wire aliases cannot establish source correspondence")


def _wire_eligibility_unqualified(report):
    """Keep a mechanical target census separate from any authorized inference view."""
    _need(type(report.get("authority")) is dict and set(report["authority"]) == set(AUTHORITY)
          and all(value is False for value in report["authority"].values()),
          "wire eligibility cannot grant authority")
    for key in ("training_mask", "evaluation_gold_mask"):
        _need(type(report.get(key)) is int and report[key] == 0,
              "wire eligibility learning masks must remain plain zero integers")
    for row in report["physical_rows"] + report["output_occurrences"]:
        _need(row.get("consumer_eligible") is False,
              "wire metadata cannot make a target consumer-eligible")
        for key, value in row.items():
            if key.endswith("_mask"):
                _need(type(value) is int and value == 0, "wire target masks must remain plain zero integers")
        fields = row.get("field_masks")
        _need(type(fields) is dict and set(fields) == set(FACETS)
              and all(type(value) is int and value == 0 for value in fields.values()),
              "wire target field masks must remain plain zero integers")
    for row in report["physical_rows"]:
        _need(row.get("meaning_unit_id") is None and row.get("selected_occurrence") is None
              and row.get("context_status") == "unresolved"
              and row.get("source_review_status") == "unresolved"
              and row.get("semantic_review_status") == "unresolved",
              "wire metadata cannot create meaning, context or source/review authorization")
    for key in ("consumer_eligible_rows", "source_units_established", "training_qualified_rows", "evaluation_gold_rows"):
        _need(type(report["counts"].get(key)) is int and report["counts"][key] == 0,
              "wire metadata cannot promote census counts into eligibility")


def prepare_source_span_target_eligibility_v4(request_raw, join_manifest_raw, *,
        expected_request_sha256, join_originals):
    """Enumerate targets after opening/closing wire-coordinate join v3 replay.

    The existing source_span_formula_v1 audit and zero/384 declarations remain
    metadata mechanics. No inference view, source binding, review or model is
    authorized by the selected HF wire metadata.
    """
    return _prepare_original_coordinate_eligibility(request_raw, join_manifest_raw,
        expected_request_sha256=expected_request_sha256, join_originals=join_originals,
        wire_source=True)


def validate_source_span_target_eligibility_v4(report, request_raw, join_manifest_raw, *,
        expected_request_sha256, expected_report_sha256, join_originals):
    """Regenerate an explicit v4 report from every independently committed original."""
    return _validate_original_coordinate_eligibility(report, request_raw, join_manifest_raw,
        expected_request_sha256=expected_request_sha256, expected_report_sha256=expected_report_sha256,
        join_originals=join_originals, wire_source=True)



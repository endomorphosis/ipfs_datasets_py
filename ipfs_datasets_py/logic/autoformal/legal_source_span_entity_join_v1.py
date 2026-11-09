"""Replay selected source/span custody into an unresolved three-cache manifest.

Existing owners validate source metadata, paired tables and legacy occurrence
candidates. This adapter never selects a historical occurrence, infers an
edition crosswalk or upgrades the materialized entity schema into semantics.
Entity input in v1 is explicitly metadata-only, not a file census.
"""
from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path, PurePosixPath
import re
import stat

from .legal_paired_manifest_inventory_v1 import _keys, _read_json, _wire

REQUEST_SCHEMA = "legal-source-span-entity-join-request/v1"
SCHEMA = "legal-source-span-entity-join-manifest/v1"
REQUEST_SCHEMA_V2 = "legal-source-span-entity-join-request/v2"
SCHEMA_V2 = "legal-source-span-entity-join-manifest/v2"
COORDINATE_PROFILE = "paired-coordinate-three-cache-join/v1"
REQUEST_SCHEMA_V3 = "legal-source-span-entity-join-request/v3"
SCHEMA_V3 = "legal-source-span-entity-join-manifest/v3"
WIRE_COORDINATE_PROFILE = "paired-coordinate-hf-wire-three-cache-join/v1"
WIRE_SOURCE_METADATA_PROFILE = "hf-default-parquet-envelope/v1"
MAX_REQUEST_BYTES = 256 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_BUNDLES = 16
MAX_ROWS = 256
MAX_COORDINATE_ROWS = 64
MAX_COORDINATE_ORIGINAL_BYTES = 8 * 1024 * 1024
AUTHORITY = dict.fromkeys((
    "remote_revisions_authenticated", "whole_repository_inventory_complete",
    "current_source_table_rows_verified", "historical_occurrence_selected",
    "source_semantics_verified", "semantic_review_verified", "context_closure_verified",
    "entity_file_rows_verified", "entity_semantic_bindings_verified", "graph_admitted",
    "Lean_admitted", "proof_authority", "admitted", "formalized", "training_qualified",
), False)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OWNER_PINS = None
_JOIN_FIELDS = {"expected_population", "producer_receipt_bytes", "expected_producer_receipt_sha256",
                "source_sections", "expected_source_sections"}


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    _need(type(value) is str and _SHA.fullmatch(value), "exact SHA256 required")


def legacy_join_inputs_sha256(inputs):
    """Commit full independent join inputs, with receipt bytes hashed separately.

    This recipe is input identity, not a validation of its source assertions.
    Physical duplicate rows remain in expected_population; only delegated
    identical-row candidate computation is deduplicated later.
    """
    _keys(inputs, _JOIN_FIELDS, "legacy join inputs")
    raw = inputs["producer_receipt_bytes"]
    _need(raw is None or type(raw) is bytes and 0 < len(raw) <= 32 * 1024 * 1024,
          "bounded exact producer receipt bytes or unavailable null required")
    body = {key: value for key, value in inputs.items() if key != "producer_receipt_bytes"}
    body["producer_receipt"] = None if raw is None else {"sha256": _sha(raw), "bytes": len(raw)}
    return _sha(_wire(body, 4 * 1024 * 1024))


def _owners():
    from . import (legal_source_package_intake_v1 as source,
                   legal_paired_manifest_inventory_v1 as inventory,
                   legal_paired_payload_intake_v1 as payload,
                   corpus_legacy_source_join as legacy,
                   legal_entity_index_intake as entity)
    global _OWNER_PINS
    modules = (source, inventory, payload, legacy, entity)
    pins = {str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
            for module in modules}
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "join manifest producer changed since import")
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    if _OWNER_PINS is None:
        _OWNER_PINS = dict(pins)
    _need(pins == _OWNER_PINS, "join manifest owner changed since first use")
    return source, inventory, payload, legacy, entity, dict(pins)


def _preflight(request_raw, source_request_raw, paired_request_raw, entity_info_raw,
               expected_request_sha256, legacy_join_inputs, *, coordinate=False, wire_source=False):
    _digest(expected_request_sha256)
    _need(type(request_raw) is bytes and _sha(request_raw) == expected_request_sha256,
          "request bytes differ from independent pin")
    request = _read_json(request_raw, MAX_REQUEST_BYTES, "join request")
    _keys(request, {"schema", "source_request_sha256", "paired_inventory_request_sha256",
                    "paired_bundles", "legacy_joins", "entity"}, "join request")
    _need(not wire_source or coordinate, "wire source requires the coordinate join profile")
    schema = REQUEST_SCHEMA_V3 if wire_source else REQUEST_SCHEMA_V2 if coordinate else REQUEST_SCHEMA
    _need(request["schema"] == schema,
          "unsupported join request profile")
    for field, raw in (("source_request_sha256", source_request_raw),
                       ("paired_inventory_request_sha256", paired_request_raw)):
        _digest(request[field])
        _need(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST_BYTES and _sha(raw) == request[field],
              "nested request bytes differ: " + field)
    if wire_source:
        source_request = _read_json(source_request_raw, MAX_REQUEST_BYTES, "wire source request")
        _keys(source_request, {"schema", "repository_id", "revision", "expected_release_identity",
            "expected_graph_population", "files", "metadata_profile"}, "wire source request")
        _need(source_request["schema"] == "legal-source-package-intake-request/v2"
              and type(source_request["metadata_profile"]) is str
              and source_request["metadata_profile"] == WIRE_SOURCE_METADATA_PROFILE,
              "explicit wire intake v2 request and metadata profile required")
    bundles = request["paired_bundles"]
    _need(type(bundles) is list and len(bundles) <= MAX_BUNDLES, "bounded ordered bundle selection required")
    if coordinate:
        _need(len(bundles) == 1, "one coordinate bundle required")
    paths = set()
    for row in bundles:
        _keys(row, {"manifest_path_in_repo", "repository_root"}, "selected bundle")
        path, root = row["manifest_path_in_repo"], row["repository_root"]
        _need(type(path) is str and 0 < len(path) <= 512 and path not in paths,
              "unique explicit manifest path required")
        _need(type(root) is str and len(root) <= 4096 and PurePosixPath(root).is_absolute()
              and PurePosixPath(root).as_posix() == root and ".." not in PurePosixPath(root).parts
              and "\\" not in root, "canonical absolute retained bundle root required")
        paths.add(path)
    declared = request["legacy_joins"]
    inputs = {} if legacy_join_inputs is None else legacy_join_inputs
    _need(type(declared) is dict and type(inputs) is dict and set(declared) == set(inputs)
          and set(declared) <= paths, "legacy input population differs from declared selected banks")
    if coordinate:
        _need(not declared, "coordinate profile does not mix legacy occurrence joins")
    captured_joins = {}
    for path, digest in declared.items():
        _digest(digest)
        _need(legacy_join_inputs_sha256(inputs[path]) == digest, "legacy join input commitment differs")
        supplied = inputs[path]
        receipt = supplied["producer_receipt_bytes"]
        captured = _read_json(_wire({key: value for key, value in supplied.items()
                                    if key != "producer_receipt_bytes"}, 4 * 1024 * 1024),
                              4 * 1024 * 1024, "legacy independent inputs")
        captured["producer_receipt_bytes"] = receipt
        _need(legacy_join_inputs_sha256(captured) == digest, "legacy inputs changed during snapshot")
        captured_joins[path] = captured
    entity = request["entity"]
    _keys(entity, {"repository_id", "revision", "configuration", "info_sha256"}, "entity metadata selection")
    _need(entity["repository_id"] == "justicedao/uscode-autoformal-entity-cache"
          and type(entity["revision"]) is str and _REVISION.fullmatch(entity["revision"])
          and entity["configuration"] == "autoformal_uscode", "unsupported entity metadata profile")
    _digest(entity["info_sha256"])
    _need(type(entity_info_raw) is bytes and _sha(entity_info_raw) == entity["info_sha256"],
          "entity metadata bytes differ from independent pin")
    info = _read_json(entity_info_raw, 128 * 1024, "entity schema response")
    _need(type(info) is dict and info.get("partial") is False, "complete entity metadata response required")
    return request, captured_joins, info


def _legacy_population(inputs, rows):
    expected = inputs["expected_population"]
    _need(type(expected) is list and len(expected) == len(rows), "complete physical legacy population required")
    unique, seen = [], {}
    for row, commitment in zip(rows, expected):
        _need(type(commitment) is dict and commitment.get("row_sha256") == row["row_sha256"],
              "legacy population order or row identity differs")
        digest = row["row_sha256"]
        if digest in seen:
            _need(seen[digest] == commitment, "conflicting identical-row source expectations")
        else:
            seen[digest] = commitment
            unique.append((row["derived_row_json"].encode("utf-8"), commitment))
    return unique


def _coordinate_metadata_snapshot(source_metadata_bytes, paired_manifest_bytes, raw_inputs):
    """Detach bounded original byte mappings before any delegated operation."""
    total = sum(len(value) for value in raw_inputs)
    snapshots = []
    for offered, maximum in ((source_metadata_bytes, 5), (paired_manifest_bytes, 1)):
        _need(type(offered) is dict and len(offered) <= maximum,
              "bounded exact coordinate metadata mapping required")
        captured = {}
        for name, raw in offered.items():
            _need(type(name) is str and 0 < len(name) <= 512 and type(raw) is bytes,
                  "ordinary coordinate metadata names and exact bytes required")
            total += len(raw)
            _need(total <= MAX_COORDINATE_ORIGINAL_BYTES,
                  "coordinate original metadata aggregate byte bound exceeded")
            captured[name] = raw
        snapshots.append(captured)
    return snapshots


def _coordinate_owner_pins(owners):
    source, _, payload, _, _, pins = owners
    return {**source._owners()[-1], **payload._pins(coordinate=True), **pins}


def _coordinate_file_witnesses(location, selected):
    """Fence the same physical files around the existing payload decoder."""
    root = Path(location["repository_root"])
    _need(root.resolve(strict=True) == root and root.is_dir(),
          "unaliased retained coordinate repository root required")
    descriptors = {selected["path_in_repo"]: selected["bytes"]}
    for table in selected["manifest"]["tables"].values():
        descriptors[table["path_in_repo"]] = table["bytes"]
    witnesses = {}
    for relative, size in descriptors.items():
        path = root / relative
        _need(path.resolve(strict=True) == path
              and all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents),
              "unaliased coordinate bundle file required")
        info = path.lstat()
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == size,
              "complete regular coordinate bundle file required")
        witnesses[str(path)] = [info.st_dev, info.st_ino, info.st_mode,
                                info.st_size, info.st_mtime_ns, info.st_ctime_ns]
    return witnesses


def _finish_coordinate_custody(checks, primary):
    failures = []
    for label, check in checks:
        try:
            check()
        except BaseException as error:
            failures.append((label, error))
    if primary is not None:
        for label, error in failures:
            primary.add_note("secondary coordinate join custody failure (" + label + "): "
                             + type(error).__name__ + ": " + str(error)[:512])
    elif failures:
        label, error = failures[0]
        error.add_note("closing coordinate join custody check: " + label)
        for other_label, other in failures[1:]:
            error.add_note("additional closing custody failure (" + other_label + "): "
                           + type(other).__name__ + ": " + str(other)[:512])
        raise error


def _prepare_join(request_raw, source_request_raw, source_metadata_bytes,
        paired_inventory_request_raw, paired_manifest_bytes, entity_info_raw, *,
        expected_request_sha256, legacy_join_inputs=None, coordinate=False, wire_source=False):
    request, joins, info = _preflight(request_raw, source_request_raw, paired_inventory_request_raw,
        entity_info_raw, expected_request_sha256, legacy_join_inputs,
        coordinate=coordinate, wire_source=wire_source)
    snapshots = (_coordinate_metadata_snapshot(source_metadata_bytes, paired_manifest_bytes,
        (request_raw, source_request_raw, paired_inventory_request_raw, entity_info_raw)) if coordinate else None)
    owners = _owners()
    source, inventory, _, _, _, _ = owners
    source_identity = _read_json(source_request_raw, MAX_REQUEST_BYTES, "source request")
    if not coordinate:
        source_report = source.prepare_source_package_intake(source_request_raw, source_metadata_bytes,
            expected_request_sha256=request["source_request_sha256"])
        span_report = inventory.prepare_paired_manifest_inventory(paired_inventory_request_raw,
            paired_manifest_bytes, expected_request_sha256=request["paired_inventory_request_sha256"])
        return _assemble_join(request, joins, info, source_report, source_identity, span_report, owners,
            request_raw, entity_info_raw, expected_request_sha256)

    source_snapshot, paired_snapshot = snapshots
    before = _coordinate_owner_pins(owners)
    files, selected, primary = None, None, None
    offered_source_report, source_report, source_report_bytes = None, None, None
    assembled_report, assembled_bytes = None, None

    def wire_source_report_unchanged():
        if wire_source and source_report_bytes is not None:
            _need(_wire(offered_source_report, MAX_REPORT_BYTES) == source_report_bytes
                  and _wire(source_report, MAX_REPORT_BYTES) == source_report_bytes,
                  "wire source intake report changed during coordinate join")

    def wire_source_report_valid():
        if wire_source and source_report_bytes is not None:
            source.validate_source_package_intake_v2(source_report, source_request_raw,
                dict(source_snapshot), expected_request_sha256=request["source_request_sha256"],
                expected_report_sha256=_sha(source_report_bytes))

    def wire_join_report_unchanged():
        if wire_source and assembled_bytes is not None:
            _need(_wire(assembled_report, MAX_REPORT_BYTES) == assembled_bytes,
                  "wire coordinate join result changed during closing custody")

    def originals_unchanged():
        for offered, captured in ((source_metadata_bytes, source_snapshot),
                                  (paired_manifest_bytes, paired_snapshot)):
            _need(type(offered) is dict and set(offered) == set(captured)
                  and all(type(offered[name]) is bytes and offered[name] == raw
                          for name, raw in captured.items()),
                  "original coordinate metadata mapping changed during join")
        _need(legacy_join_inputs is None or type(legacy_join_inputs) is dict and not legacy_join_inputs,
              "original coordinate legacy inputs changed during join")

    def sources_unchanged():
        _need(_coordinate_owner_pins(_owners()) == before,
              "coordinate join owner sources changed during operation")

    def files_unchanged():
        if files is not None:
            _need(_coordinate_file_witnesses(request["paired_bundles"][0], selected) == files,
                  "coordinate bundle file witnesses changed during join")

    try:
        originals_unchanged()
        # Independent coordinate declarations and bounds precede source preparation
        # and all payload-table I/O. V1 retains its original delegate order above.
        span_report = inventory.prepare_paired_manifest_inventory_v2(paired_inventory_request_raw,
            dict(paired_snapshot), expected_request_sha256=request["paired_inventory_request_sha256"])
        selections = span_report["manifests"]
        _need(len(selections) == 1 and selections[0]["path_in_repo"]
              == request["paired_bundles"][0]["manifest_path_in_repo"],
              "one coordinate manifest in exact requested order required")
        selected = selections[0]
        count = selected["manifest"]["tables"]["paired_spans"]["row_count"]
        _need(type(count) is int and 1 <= count <= MAX_COORDINATE_ROWS,
              "bounded complete coordinate row population required")
        files = _coordinate_file_witnesses(request["paired_bundles"][0], selected)
        if wire_source:
            offered_source_report = source.prepare_source_package_intake_v2(
                source_request_raw, dict(source_snapshot),
                expected_request_sha256=request["source_request_sha256"])
            _need(type(offered_source_report) is dict
                  and offered_source_report.get("schema") == source.SCHEMA_V2
                  and offered_source_report.get("metadata_profile") == WIRE_SOURCE_METADATA_PROFILE
                  and offered_source_report.get("status") == "selected_wire_metadata_reconciled",
                  "wire source delegate returned an incompatible intake report")
            source_report_bytes = _wire(offered_source_report, MAX_REPORT_BYTES)
            source_report = _read_json(source_report_bytes, MAX_REPORT_BYTES, "wire source intake report")
        else:
            source_report = source.prepare_source_package_intake(source_request_raw, dict(source_snapshot),
                expected_request_sha256=request["source_request_sha256"])
        assembled_report = _assemble_join(request, joins, info, source_report, source_identity, span_report, owners,
            request_raw, entity_info_raw, expected_request_sha256, coordinate=True,
            coordinate_pins=before, file_witnesses=files, wire_source=wire_source)
        if wire_source:
            assembled_bytes = _wire(assembled_report, MAX_REPORT_BYTES)
        return assembled_report
    except BaseException as error:
        primary = error
        raise
    finally:
        checks = (("wire source report before validation", wire_source_report_unchanged),
                  ("wire source validation", wire_source_report_valid),
                  ("wire source report after validation", wire_source_report_unchanged)) if wire_source else ()
        closing_result = (("wire join result", wire_join_report_unchanged),) if wire_source else ()
        _finish_coordinate_custody(checks + (("original inputs", originals_unchanged),
            ("owner sources", sources_unchanged), ("retained files", files_unchanged)) + closing_result, primary)


def prepare_source_span_entity_join_manifest(request_raw, source_request_raw, source_metadata_bytes,
        paired_inventory_request_raw, paired_manifest_bytes, entity_info_raw, *,
        expected_request_sha256, legacy_join_inputs=None):
    """Replay legacy paired-v1/v2 joins without selecting text candidates."""
    return _prepare_join(request_raw, source_request_raw, source_metadata_bytes,
        paired_inventory_request_raw, paired_manifest_bytes, entity_info_raw,
        expected_request_sha256=expected_request_sha256, legacy_join_inputs=legacy_join_inputs)


def prepare_source_span_entity_join_manifest_v2(request_raw, source_request_raw, source_metadata_bytes,
        paired_inventory_request_raw, paired_manifest_bytes, entity_info_raw, *,
        expected_request_sha256, legacy_join_inputs=None):
    """Retain one complete coordinate report; source/entity semantics stay unresolved."""
    return _prepare_join(request_raw, source_request_raw, source_metadata_bytes,
        paired_inventory_request_raw, paired_manifest_bytes, entity_info_raw,
        expected_request_sha256=expected_request_sha256, legacy_join_inputs=legacy_join_inputs,
        coordinate=True)


def _assemble_join(request, joins, info, source_report, source_identity, span_report, owners,
                   request_raw, entity_info_raw, expected_request_sha256, *, coordinate=False,
                   coordinate_pins=None, file_witnesses=None, wire_source=False):
    source, inventory, payload, legacy, entity, before = owners
    selections = span_report["manifests"]
    _need([row["manifest_path_in_repo"] for row in request["paired_bundles"]]
          == [row["path_in_repo"] for row in selections], "bundle population/order differs from metadata selection")
    metadata = info.get("dataset_info")
    _need(type(metadata) is dict and metadata.get("config_name") == request["entity"]["configuration"]
          and metadata.get("dataset_name") == "uscode-autoformal-entity-cache",
          "entity dataset or configuration differs")
    features = metadata.get("features")
    _need(type(features) is dict and set(features) == set(entity.FIELDS), "exact twelve-field entity schema required")
    for key, value in features.items():
        _need(type(value) is dict and value.get("_type") == "Value"
              and value.get("dtype") == ("bool" if key in entity.BOOLEAN_FIELDS else "string"),
              "unsupported entity field type: " + key)
    splits = metadata.get("splits")
    _need(type(splits) is dict and type(splits.get("train")) is dict, "entity train metadata required")
    train = splits["train"]
    declared_rows = train.get("num_examples")
    _need(type(declared_rows) is int and 0 <= declared_rows <= entity.MAX_ROWS, "bounded entity declared population required")
    bundles, physical_rows, occurrence_cids = [], [], set()
    counts = Counter()
    for selected, location in zip(selections, request["paired_bundles"]):
        path = selected["path_in_repo"]
        prepare_payload = (payload.prepare_paired_payload_intake_v2 if coordinate
                           else payload.prepare_paired_payload_intake)
        extra = ({"expected_source_coordinate_report_sha256": selected["source_coordinate_report_sha256"],
                  "limits": {"max_rows": MAX_COORDINATE_ROWS}} if coordinate else {})
        intake = prepare_payload(repository_root=location["repository_root"],
            repository_id=span_report["repository_id"], revision=span_report["revision"],
            manifest_path_in_repo=path, expected_manifest_sha256=selected["sha256"], **extra)
        rows = intake["rows"]
        _need(len(physical_rows) + len(rows) <= MAX_ROWS, "complete selected physical population exceeds bound")
        _need(len(rows) == selected["manifest"]["tables"]["paired_spans"]["row_count"],
              "verified payload population differs from manifest")
        _need([row["row_ordinal"] for row in rows] == list(range(len(rows))), "payload physical order is incomplete")
        ledger, lookup = None, {}
        if path in joins:
            unique = _legacy_population(joins[path], rows)
            arguments = {key: value for key, value in joins[path].items() if key != "expected_population"}
            arguments["expected_population"] = [entry for _, entry in unique]
            ledger = legacy.build_legacy_source_join([raw for raw, _ in unique], **arguments)
            lookup = {row["row_sha256"]: row for row in ledger["rows"]}
            _need(set(lookup) == {row["row_sha256"] for row in rows}, "legacy ledger population differs")
            for entry in ledger["rows"]:
                _need(entry["selected_occurrence"] is None and entry["original_producer_occurrence_attested"] is False,
                      "candidate owner unexpectedly selected an occurrence")
        table = selected["manifest"]["tables"]["paired_spans"]
        for row in rows:
            raw = row["derived_row_json"].encode("utf-8")
            _need(_sha(raw) == row["row_sha256"], "derived row commitment differs")
            observed = _read_json(raw, 1024 * 1024, "derived paired row")
            candidate = lookup.get(row["row_sha256"])
            disposition = candidate["disposition"] if candidate is not None else "source_join_unavailable"
            if row["disposition"] == "adapter_rejected":
                disposition = "paired_candidate_adapter_rejected"
            _need(row["disposition"] in {"candidate_unbound", "adapter_rejected"}, "unexpected source-bound payload")
            physical = {"repository_id": span_report["repository_id"], "revision": span_report["revision"],
                        "path_in_repo": table["path_in_repo"], "file_sha256": table["sha256"],
                        "row_ordinal": row["row_ordinal"]}
            entry = {"physical_identity": physical, "physical_identity_sha256": _sha(_wire(physical, 4096)),
                "manifest_path_in_repo": path, "bank": selected["bank"],
                "row_sha256": row["row_sha256"], "observation_id": row["observation_id"],
                "producer_source_revision_label": observed["source"]["revision"],
                "payload_disposition": row["disposition"], "source_disposition": disposition,
                "source_candidate_record": candidate, "selected_occurrence": None,
                "current_source_release_correspondence": "unverified_no_independent_crosswalk",
                "entity_binding": "unavailable_semantic_companions_not_supplied",
                "training_mask": 0, "evaluation_gold_mask": 0}
            if coordinate:
                _need(row["source_coordinate_report_sha256"] == selected["source_coordinate_report_sha256"],
                      "payload coordinate report differs from independent pin")
                entry.update(source_provenance_json=row["source_provenance_json"],
                    source_coordinate_report_sha256=row["source_coordinate_report_sha256"],
                    source_coordinate_span_index=row["source_coordinate_span_index"],
                    coordinate_transport_status="complete_report_occurrence_replayed")
            physical_rows.append(entry)
            counts[disposition] += 1
            counts["candidate_occurrence_references"] += 0 if candidate is None else candidate["occurrence_count"]
            if candidate is not None:
                for occurrence in candidate["candidates"]:
                    occurrence_cids.add(occurrence["source_occurrence"]["record_cid"])
        bundles.append({"manifest_path_in_repo": path, "payload_intake": intake, "legacy_candidate_join": ledger})
    physical = {}
    for ordinal, row in enumerate(physical_rows):
        identity = row["physical_identity_sha256"]
        if identity not in physical:
            physical[identity] = {"physical_identity": row["physical_identity"],
                "physical_identity_sha256": identity, "row_sha256": row["row_sha256"],
                "observation_id": row["observation_id"], "row_reference_ordinals": []}
        _need(physical[identity]["row_sha256"] == row["row_sha256"]
              and physical[identity]["observation_id"] == row["observation_id"],
              "conflicting observations for one physical table row")
        physical[identity]["row_reference_ordinals"].append(ordinal)
    report = {"schema": SCHEMA_V3 if wire_source else SCHEMA_V2 if coordinate else SCHEMA,
        "request": request, "request_raw_utf8": request_raw.decode("utf-8"),
        "request_sha256": expected_request_sha256,
        "source_repository": {"repository_id": source_identity["repository_id"], "revision": source_identity["revision"]},
        "source_metadata_intake": source_report, "span_inventory": span_report,
        "paired_bundles": bundles, "physical_rows": list(physical.values()), "row_references": physical_rows,
        "entity_metadata": {**request["entity"], "raw_utf8": entity_info_raw.decode("utf-8"),
            "declared_rows": declared_rows, "verified_file_rows": 0, "schema_fields": list(entity.FIELDS),
            "scope": "metadata_only_no_entity_file_or_semantic_companions"},
        "counts": {"physical_paired_rows": len(physical), "selected_row_references": len(physical_rows),
            "selected_bundles": len(bundles),
            "source_dispositions": dict(sorted((key, value) for key, value in counts.items()
                                               if key != "candidate_occurrence_references")),
            "candidate_occurrence_references": counts["candidate_occurrence_references"],
            "distinct_candidate_occurrence_cids": len(occurrence_cids), "entity_file_rows_verified": 0},
        "selection_complete": True,
        "selection_scope": ("exact_selected_paired_v3_bundle_with_complete_source_coordinates" if coordinate
                            else "exact_selected_paired_bundles_and_supplied_legacy_candidate_inputs"),
        "authority": dict(AUTHORITY), "producer_pins": coordinate_pins if coordinate else before,
        "producer_pins_scope": "selected_owner_file_observations_not_complete_execution_closure",
        "training_mask": 0, "evaluation_gold_mask": 0}
    if coordinate:
        report["source_compatibility_profile"] = WIRE_COORDINATE_PROFILE if wire_source else COORDINATE_PROFILE
        report["retained_file_witnesses"] = file_witnesses
        report["counts"]["coordinate_occurrence_replayed_rows"] = len(physical_rows)
    if wire_source:
        report["source_metadata_profile"] = WIRE_SOURCE_METADATA_PROFILE
        report["source_metadata_request_schema"] = source_identity["schema"]
        report["source_metadata_intake_sha256"] = source.source_package_intake_sha256(source_report)
    _wire(report, MAX_REPORT_BYTES)
    _need(_owners()[-1] == before, "join manifest owners changed during preparation")
    return _read_json(_wire(report, MAX_REPORT_BYTES), MAX_REPORT_BYTES, "join report")


def source_span_entity_join_manifest_sha256(report):
    return _sha(_wire(report, MAX_REPORT_BYTES))


def validate_source_span_entity_join_manifest(report, *inputs, expected_report_sha256, **kwargs):
    """Require independent report identity and full original-input regeneration."""
    _digest(expected_report_sha256)
    if type(report) is bytes:
        report = _read_json(report, MAX_REPORT_BYTES, "join report")
    _need(source_span_entity_join_manifest_sha256(report) == expected_report_sha256, "join report SHA256 differs")
    expected = prepare_source_span_entity_join_manifest(*inputs, **kwargs)
    _need(_wire(report, MAX_REPORT_BYTES) == _wire(expected, MAX_REPORT_BYTES), "join report differs from full replay")
    return expected


def validate_source_span_entity_join_manifest_v2(report, *inputs, expected_report_sha256, **kwargs):
    """Regenerate the complete pinned coordinate join from its original inputs."""
    _digest(expected_report_sha256)
    if type(report) is bytes:
        report = _read_json(report, MAX_REPORT_BYTES, "coordinate join report")
    original = _wire(report, MAX_REPORT_BYTES)
    _need(_sha(original) == expected_report_sha256, "join report SHA256 differs")
    primary = None
    try:
        expected = prepare_source_span_entity_join_manifest_v2(*inputs, **kwargs)
        _need(original == _wire(expected, MAX_REPORT_BYTES), "join report differs from full replay")
        return expected
    except BaseException as error:
        primary = error
        raise
    finally:
        def offered_unchanged():
            _need(_wire(report, MAX_REPORT_BYTES) == original,
                  "offered coordinate join report changed during validation")
        _finish_coordinate_custody((("offered report", offered_unchanged),), primary)


def prepare_source_span_entity_join_manifest_v3(request_raw, source_request_raw, source_metadata_bytes,
        paired_inventory_request_raw, paired_manifest_bytes, entity_info_raw, *,
        expected_request_sha256, legacy_join_inputs=None):
    """Explicit wire-intake-v2/coordinate composition without semantic admission.

    One complete paired-v3 bundle retains the existing coordinate/file custody.
    HF aliases do not establish source correspondence or entity endpoints.
    """
    return _prepare_join(request_raw, source_request_raw, source_metadata_bytes,
        paired_inventory_request_raw, paired_manifest_bytes, entity_info_raw,
        expected_request_sha256=expected_request_sha256, legacy_join_inputs=legacy_join_inputs,
        coordinate=True, wire_source=True)


def validate_source_span_entity_join_manifest_v3(report, *inputs, expected_report_sha256, **kwargs):
    """Regenerate the full wire-coordinate join and fence the offered report."""
    _digest(expected_report_sha256)
    if type(report) is bytes:
        report = _read_json(report, MAX_REPORT_BYTES, "wire coordinate join report")
    original = _wire(report, MAX_REPORT_BYTES)
    _need(_sha(original) == expected_report_sha256, "join report SHA256 differs")
    primary = None
    try:
        expected = prepare_source_span_entity_join_manifest_v3(*inputs, **kwargs)
        _need(original == _wire(expected, MAX_REPORT_BYTES), "join report differs from full replay")
        return expected
    except BaseException as error:
        primary = error
        raise
    finally:
        def offered_unchanged():
            _need(_wire(report, MAX_REPORT_BYTES) == original,
                  "offered wire coordinate join report changed during validation")
        _finish_coordinate_custody((("offered report", offered_unchanged),), primary)

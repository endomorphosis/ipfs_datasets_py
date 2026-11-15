"""Original-bound physical cache references to unselected source candidates.

The existing cache owner replays retained Parquet originals. The existing legacy
join owner alone resolves receipt pointers and enumerates stored-text geometry.
This adapter preserves physical references and never turns a candidate into an
attested producer occurrence, source/context input, or training permission.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import re
import stat

REQUEST_SCHEMA = "legal-compact-source-candidate-crosswalk-request/v1"
SCHEMA = "legal-compact-source-candidate-crosswalk/v1"
PROFILE = "original-bound-physical-cache-source-candidates/v1"
MAX_REQUEST_BYTES = 128 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_JOIN_METADATA_BYTES = 4 * 1024 * 1024
MAX_MANIFESTS = 4
MAX_ROWS = 128
MAX_ROWS_PER_BUNDLE = 64
MAX_SECTIONS_PER_BUNDLE = 64
MAX_RECEIPT_BYTES = 32 * 1024 * 1024
MAX_CANDIDATE_REFERENCES = 4096
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_RELATIVE = "logic/autoformal/"
_SOURCE_PINS = {
    "legal_compact_source_context_cache_intake_v1": "8a23d73ec8e75abb0587768e7455ba0c29f07ca97d298bc4ba323a5657d2ff6c",
    "legal_source_span_entity_join_v1": "05f9a59b72380c066d5c36d5417d96ab655e489e1de8ecfba5918bbb4ae40bbd",
    "corpus_legacy_source_join": "120b27eed761228e67e9c560777ff355818ceb59855f1d9ffed237cfc9480609",
    "legal_paired_manifest_inventory_v1": "ec83dcda3f6b409f01c57344b9e40760f210d513b35201dc635d48dfe62fd788",
    "corpus_contracts": "b89146e2471b7335f23115222c5a9bc5298a20bb02f02cce5d91496e6563d8aa",
    "corpus_source": "6e4be77cfc27a750b11aa57bb92baa92617c57d5c4a26316e25563aa715ec257",
    "legal_statutory_context": "1f1e607c7c8d1e479ae5b79e17f928571e3da49f0ad4180dfc93e609d0d47dc2",
}
_CACHE_KEYS = {"cache_request_raw", "cache_bindings_raw", "expected_cache_request_sha256",
    "expected_cache_bindings_sha256", "manifest_bytes", "repository_root", "inventory_report",
    "inventory_originals"}
_JOIN_KEYS = {"expected_population", "producer_receipt_bytes", "expected_producer_receipt_sha256",
    "source_sections", "expected_source_sections"}
_POPULATION_KEYS = {"row_sha256", "source_span_id", "text_sha256", "source_revision"}
_SECTION_KEYS = {"repository_id", "revision", "path_in_repo", "artifact_sha256", "artifact_bytes",
    "release_id", "parquet_row_index", "entry_cid", "legal_id", "text_sha256"}
_AUTHORITY = dict.fromkeys(("source_correspondence_verified", "original_producer_occurrence_attested",
    "source_authority_authenticated", "remote_revision_authenticated", "source_semantics_verified",
    "current_source_release_correspondence_verified", "context_independence_verified",
    "context_permission_verified", "inference_permission_verified", "reviewer_authenticated",
    "shared_definition_closure_verified", "training_qualified", "evaluation_gold_qualified",
    "legal_accuracy_established", "convergence_proved", "Lean_admitted", "accepted", "admitted",
    "model_executed", "training_executed", "database_executed", "prover_executed",
    "supervisor_executed"), False)
_LIMITATIONS = [
    "Coverage is exactly the selected manifest-declared physical reference population, not the whole cache or source corpus.",
    "Exact producer receipt linkage and stored-text candidate geometry do not attest the original producer character occurrence, even when only one candidate remains.",
    "Historical parent revisions and physical rows remain separate from any current-source release; no independent edition or revision crosswalk is supplied.",
    "Source-parent reconstruction declarations are preserved unchanged and are not independently authenticated by this operation.",
    "Authored inventory occurrences remain a separate population; candidates are not inserted into SourcePartitions or assigned independent access or chronology.",
    "Paired formal targets, artifacts and vectors are read only by the existing transport owner and are excluded from this crosswalk's source records and inference views.",
    "All inference views are null, all authority flags are false, and training/evaluation masks are zero. Entity/definition closure, training, Lean and convergence remain open.",
    "Fixed source pins and ordinary Python checks are not attestation against arbitrary monkeypatching, native libraries or replacement of all originals and independent pins.",
]


class SourceCandidateCrosswalkError(ValueError):
    """A bounded original, physical population, or candidate replay differs."""


def _need(ok, message):
    if not ok:
        raise SourceCandidateCrosswalkError(message)


def _digest(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _source(path, expected):
    _need(path.resolve(strict=True) == path and all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents),
          "canonical producer source required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 512 * 1024,
          "bounded single-link producer source required")
    raw, after = path.read_bytes(), path.lstat()
    witness = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    _need(witness(before) == witness(after) and _sha(raw) == expected, "producer source changed or fixed pin differs")
    return witness(after)


def _sources(root):
    return {str(_SELF_PATH): _source(_SELF_PATH, _SELF_SHA),
        **{str(root / _RELATIVE / (name + ".py")): _source(root / _RELATIVE / (name + ".py"), digest)
           for name, digest in _SOURCE_PINS.items()}}


def _owners():
    root = None
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _RELATIVE / "legal_compact_source_context_cache_intake_v1.py").is_file():
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None and root.resolve(strict=True) == root, "canonical owner tree required")
    before, modules = _sources(root), {}
    for key, name in (("cache", "legal_compact_source_context_cache_intake_v1"),
            ("commitment", "legal_source_span_entity_join_v1"),
            ("legacy", "corpus_legacy_source_join"), ("json", "legal_paired_manifest_inventory_v1")):
        module = importlib.import_module("ipfs_datasets_py.logic.autoformal." + name)
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / _RELATIVE / (name + ".py"),
              "genuine canonical owner import required")
        modules[key] = module
    _need(_sources(root) == before, "producer sources changed during imports")
    return root, before, modules


def _capture_inputs(value, owner, metadata):
    """Bound shape before hashing/copying; receipt bytes stay immutable and separate."""
    _need(type(value) is dict and set(value) == _JOIN_KEYS, "closed complete legacy join inputs required")
    population, sections, pins = value["expected_population"], value["source_sections"], value["expected_source_sections"]
    _need(type(population) is list and len(population) <= MAX_ROWS_PER_BUNDLE,
          "bounded complete physical legacy population required")
    _need(type(sections) is list and type(pins) is list and len(sections) == len(pins) <= MAX_SECTIONS_PER_BUNDLE,
          "bounded ordered complete source sections required")
    for row in population:
        _need(type(row) is dict and set(row) == _POPULATION_KEYS, "closed expected source population row required")
        for field in ("row_sha256", "text_sha256"):
            _digest(row[field], field)
        for field in ("source_span_id", "source_revision"):
            _need(type(row[field]) is str and 0 < len(row[field]) <= 4096,
                  "bounded expected source identity required")
    total = 0
    for supplied, pin in zip(sections, pins):
        _need(type(pin) is dict and set(pin) == _SECTION_KEYS
              and type(supplied) is dict and set(supplied) == _SECTION_KEYS | {"text"},
              "closed complete stored source section required")
        for field in ("artifact_sha256", "text_sha256"):
            _digest(pin[field], field)
        for field in _SECTION_KEYS - {"artifact_bytes", "parquet_row_index"}:
            _need(type(pin[field]) is str and 0 < len(pin[field]) <= 4096,
                  "bounded source provenance string required")
        _need(type(pin["artifact_bytes"]) is int and 0 < pin["artifact_bytes"] <= 512 * 1024 * 1024
              and type(pin["parquet_row_index"]) is int and 0 <= pin["parquet_row_index"] <= 2_000_000,
              "bounded physical source provenance integers required")
        _need(all(type(supplied[key]) is type(pin[key]) and supplied[key] == pin[key] for key in _SECTION_KEYS),
              "source section provenance differs")
        text = supplied["text"]
        _need(type(text) is str and 0 < len(text) <= 128 * 1024, "bounded complete stored section text required")
        count = len(text.encode("utf-8"))
        total += count
        _need(count <= 128 * 1024 and total <= 512 * 1024, "complete source text byte bounds exceeded")
    receipt, expected = value["producer_receipt_bytes"], value["expected_producer_receipt_sha256"]
    if receipt is None:
        _need(expected is None, "unavailable producer receipt requires both receipt arguments null")
    else:
        _digest(expected, "producer receipt")
        _need(type(receipt) is bytes and 0 < len(receipt) <= MAX_RECEIPT_BYTES,
              "bounded exact producer receipt bytes required")
        _need(_sha(receipt) == expected, "producer receipt SHA256 mismatch")
    digest = owner.legacy_join_inputs_sha256(value)
    body = metadata._read_json(metadata._wire({key: item for key, item in value.items()
        if key != "producer_receipt_bytes"}, MAX_JOIN_METADATA_BYTES), MAX_JOIN_METADATA_BYTES, "join input snapshot")
    body["producer_receipt_bytes"] = receipt
    _need(owner.legacy_join_inputs_sha256(body) == digest, "legacy inputs changed during snapshot")
    return body, digest


def _request(raw, expected, inputs, owner, metadata):
    _digest(expected, "request")
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST_BYTES and _sha(raw) == expected,
          "bounded exact request bytes differ from independent pin")
    value = metadata._read_json(raw, MAX_REQUEST_BYTES, "crosswalk request")
    _need(type(value) is dict and set(value) == {"schema", "cache_intake_sha256", "legacy_joins"}
          and value["schema"] == REQUEST_SCHEMA, "closed supported crosswalk request required")
    _digest(value["cache_intake_sha256"], "cache intake report")
    rows = value["legacy_joins"]
    _need(type(rows) is list and 1 <= len(rows) <= MAX_MANIFESTS, "bounded nonempty ordered manifest joins required")
    _need(type(inputs) is dict and len(inputs) == len(rows), "complete declared legacy join mapping required")
    captured, seen = {}, set()
    for row in rows:
        _need(type(row) is dict and set(row) == {"manifest_path_in_repo", "inputs_sha256"},
              "closed declared manifest join required")
        path, digest = row["manifest_path_in_repo"], row["inputs_sha256"]
        _need(type(path) is str and 0 < len(path) <= 512 and path not in seen and path in inputs,
              "unique complete manifest join paths required")
        seen.add(path)
        if digest is None:
            _need(inputs[path] is None, "unavailable legacy join requires null inputs")
            captured[path] = None
        else:
            _digest(digest, "legacy join input")
            body, observed = _capture_inputs(inputs[path], owner, metadata)
            _need(observed == digest, "legacy join input commitment differs")
            captured[path] = body
    _need(set(inputs) == seen, "legacy join mapping population differs")
    return value, captured


def _unique_rows(records, expected):
    """Deduplicate delegated computation only; the physical output stays complete."""
    _need(len(records) == len(expected), "complete ordered physical legacy population required")
    unique, seen = [], {}
    for record, pin in zip(records, expected):
        committed = record["expected_row_sha256"]
        _need(committed is None or committed == pin["row_sha256"], "expected physical cache row commitment differs")
        if record["record_status"] != "verified":
            continue
        raw = record["derived_row_json"].encode("utf-8")
        digest = record["row_sha256"]
        _need(digest == pin["row_sha256"] and _sha(raw) == digest, "physical cache row or population order differs")
        if digest in seen:
            _need(seen[digest] == (raw, pin), "conflicting identical-byte source expectations")
        else:
            seen[digest] = (raw, pin)
            unique.append((raw, pin))
    return unique


def _cache_snapshot(arguments, cache_report, cache, metadata):
    """Reuse the inventory owner's partition custody recipe after its replay."""
    _, _, modules = cache._owners()
    inventory = modules["inventory"]
    _, _, inventory_modules = inventory._owners()
    originals = dict(arguments["inventory_originals"])
    entries = [row["entry_cid"] for row in cache_report["inventory_report"]["rows"]]
    return dict(manifest_bytes=dict(arguments["manifest_bytes"]),
        inventory_report=metadata._wire(arguments["inventory_report"], cache.MAX_REPORT_BYTES),
        inventory_originals=originals, entries=entries, inventory=inventory,
        inventory_modules=inventory_modules,
        partitions=inventory._partition_state(originals["source_partitions"], inventory_modules, entries))


def prepare_source_candidate_crosswalk_v1(request_raw, *, expected_request_sha256,
        cache_originals, legacy_join_inputs):
    """Replay original cache bytes and retain every unselected source candidate.

    ``cache_originals`` is the complete existing cache-owner argument mapping.
    ``legacy_join_inputs`` has one declared full-input mapping (or null) per
    selected manifest. No saved cache report or candidate report is an input.
    """
    _need(type(cache_originals) is dict and set(cache_originals) == _CACHE_KEYS,
          "closed complete original cache arguments required")
    root, sources, modules = _owners()
    cache, commitment, legacy, metadata = (modules[key] for key in ("cache", "commitment", "legacy", "json"))
    request, captured = _request(request_raw, expected_request_sha256, legacy_join_inputs, commitment, metadata)
    cache_arguments = dict(cache_originals)
    cache_report = cache.prepare_source_context_cache_intake_v1(**cache_arguments)
    cache_sha = cache.source_context_cache_intake_sha256(cache_report)
    _need(cache_sha == request["cache_intake_sha256"], "fresh original-bound cache report SHA256 differs")
    records, selected = cache_report["records"], cache_report["cache_manifest_inventory"]["manifests"]
    _need(len(records) <= MAX_ROWS and len(selected) <= MAX_MANIFESTS, "bounded complete cache population required")
    _need([row["manifest_path_in_repo"] for row in request["legacy_joins"]]
          == [row["path_in_repo"] for row in selected], "manifest join population/order differs from cache originals")
    cache_snapshot = _cache_snapshot(cache_arguments, cache_report, cache, metadata)

    def fence():
        _need(_sources(root) == sources, "producer sources changed during candidate crosswalk")
        _need(type(cache_originals) is dict and set(cache_originals) == _CACHE_KEYS
              and all(cache_originals[key] is item or type(cache_originals[key]) is type(item)
                      and cache_originals[key] == item for key, item in cache_arguments.items()),
              "original cache arguments changed during candidate crosswalk")
        _need(type(cache_originals["manifest_bytes"]) is dict
              and cache_originals["manifest_bytes"] == cache_snapshot["manifest_bytes"],
              "original manifest bytes changed during candidate crosswalk")
        _need(metadata._wire(cache_originals["inventory_report"], cache.MAX_REPORT_BYTES)
              == cache_snapshot["inventory_report"], "original inventory report changed during candidate crosswalk")
        originals = cache_originals["inventory_originals"]
        _need(type(originals) is dict and set(originals) == set(cache_snapshot["inventory_originals"])
              and all(originals[key] is item or type(originals[key]) is type(item) and originals[key] == item
                      for key, item in cache_snapshot["inventory_originals"].items()),
              "original inventory arguments changed during candidate crosswalk")
        _need(cache_snapshot["inventory"]._partition_state(originals["source_partitions"],
              cache_snapshot["inventory_modules"], cache_snapshot["entries"]) == cache_snapshot["partitions"],
              "source partitions changed during candidate crosswalk")
        _need(type(legacy_join_inputs) is dict and set(legacy_join_inputs) == set(captured),
              "original legacy join mapping changed")
        for path, body in captured.items():
            if body is None:
                _need(legacy_join_inputs[path] is None, "unavailable legacy inputs changed")
            else:
                expected = next(row["inputs_sha256"] for row in request["legacy_joins"]
                                if row["manifest_path_in_repo"] == path)
                _need(commitment.legacy_join_inputs_sha256(legacy_join_inputs[path]) == expected
                      and commitment.legacy_join_inputs_sha256(body) == expected,
                      "original legacy inputs changed during operation")

    failure = None
    try:
        fence()
        outputs, bundles, total = [], [], 0
        for manifest_index, selected_manifest in enumerate(selected):
            path = selected_manifest["path_in_repo"]
            rows = [row for row in records if row["manifest_index"] == manifest_index]
            _need([row["row_ordinal"] for row in rows] == list(range(selected_manifest["manifest"]["tables"]["paired_spans"]["row_count"])),
                  "complete ordered physical cache slots required")
            inputs, ledger, lookup = captured[path], None, {}
            if inputs is not None:
                unique = _unique_rows(rows, inputs["expected_population"])
                if unique:
                    arguments = dict(inputs, expected_population=[pin for _, pin in unique])
                    ledger = legacy.build_legacy_source_join([raw for raw, _ in unique], **arguments)
                    lookup = {row["row_sha256"]: row for row in ledger["rows"]}
                    _need(len(lookup) == len(unique), "legacy candidate population differs")
            declared = request["legacy_joins"][manifest_index]
            bundles.append(dict(manifest_path_in_repo=path, inputs_sha256=declared["inputs_sha256"],
                status="source_join_unavailable" if inputs is None else "cache_record_unavailable" if ledger is None
                       else "legacy_candidates_replayed", legacy_candidate_join=ledger))
            for ordinal, row in enumerate(rows):
                candidate = lookup.get(row["row_sha256"]) if row["record_status"] == "verified" else None
                if candidate is not None:
                    _need(candidate["selected_occurrence"] is None
                          and candidate["original_producer_occurrence_attested"] is False,
                          "legacy owner unexpectedly selected a source occurrence")
                count = 0 if candidate is None else candidate["occurrence_count"]
                total += count
                _need(total <= MAX_CANDIDATE_REFERENCES, "complete candidate reference population exceeds bound")
                disposition = ("cache_record_unavailable" if row["record_status"] != "verified" else
                    "source_join_unavailable" if candidate is None else candidate["disposition"])
                outputs.append({**{key: row[key] for key in ("physical_record_id", "reference_id", "manifest_index",
                    "manifest_path_in_repo", "manifest_sha256", "repository_id", "revision", "table", "row_ordinal",
                    "expected_row_sha256", "row_sha256")}, "cache_record_status": row["record_status"],
                    "expected_source_population": None if inputs is None else inputs["expected_population"][ordinal],
                    "source_disposition": disposition, "source_candidate_record": candidate,
                    "candidate_occurrence_ids": [] if candidate is None else [item["source_occurrence"]["record_cid"]
                        for item in candidate["candidates"]], "candidate_count": count,
                    "selected_occurrence": None, "original_producer_occurrence_attested": False,
                    "current_source_release_correspondence": "unverified_no_independent_crosswalk",
                    "inference_view": None, "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0})
            fence()
        statuses = sorted({row["source_disposition"] for row in outputs})
        report = dict(schema=SCHEMA, profile=PROFILE, status="complete_declared_physical_candidate_crosswalk",
            request_sha256=expected_request_sha256, request=request, cache_intake_sha256=cache_sha,
            cache_coverage=cache_report["coverage"], bundles=bundles, records=outputs,
            coverage=dict(declared_reference_rows=len(outputs),
                distinct_physical_records=len({row["physical_record_id"] for row in outputs}),
                distinct_manifest_references=len({row["reference_id"] for row in outputs}),
                candidate_occurrence_references=total,
                distinct_candidate_occurrences=len({cid for row in outputs for cid in row["candidate_occurrence_ids"]}),
                records_with_candidates=sum(row["candidate_count"] > 0 for row in outputs),
                unique_candidate_records=sum(row["candidate_count"] == 1 for row in outputs),
                ambiguous_candidate_records=sum(row["candidate_count"] > 1 for row in outputs),
                disposition_counts={key: sum(row["source_disposition"] == key for row in outputs) for key in statuses},
                selected_occurrences=0, full_declared_population_retained=True),
            producer_pins={**{_RELATIVE + name + ".py": digest for name, digest in _SOURCE_PINS.items()},
                _RELATIVE + "legal_compact_source_candidate_crosswalk_v1.py": _SELF_SHA},
            selected_occurrence=None, original_producer_occurrence_attested=False,
            authored_inventory_occurrences="separate_population_not_merged", inference_view=None,
            authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0, limitations=list(_LIMITATIONS))
        fence()
        return json.loads(metadata._wire(report, MAX_REPORT_BYTES))
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing candidate-crosswalk original/source custody check also failed.")


def source_candidate_crosswalk_sha256(report):
    """Bounded report identity only; no cache/receipt path is followed."""
    root, sources, modules = _owners()
    try:
        return _sha(modules["json"]._wire(report, MAX_REPORT_BYTES))
    finally:
        _need(_sources(root) == sources, "producer sources changed during report hashing")


def validate_source_candidate_crosswalk_v1(report, request_raw, *, expected_report_sha256,
        expected_request_sha256, cache_originals, legacy_join_inputs):
    """Regenerate physical references and all candidates from exact originals."""
    _digest(expected_report_sha256, "crosswalk report")
    root, sources, modules = _owners()
    metadata = modules["json"]
    original = metadata._wire(report, MAX_REPORT_BYTES)
    _need(_sha(original) == expected_report_sha256, "candidate crosswalk report SHA256 mismatch")
    try:
        replayed = prepare_source_candidate_crosswalk_v1(request_raw,
            expected_request_sha256=expected_request_sha256, cache_originals=cache_originals,
            legacy_join_inputs=legacy_join_inputs)
        _need(metadata._wire(replayed, MAX_REPORT_BYTES) == original,
              "candidate crosswalk differs from original-bound replay")
        _need(metadata._wire(report, MAX_REPORT_BYTES) == original, "crosswalk report changed during validation")
        return replayed
    finally:
        _need(_sources(root) == sources, "producer sources changed during validation")


__all__ = ["REQUEST_SCHEMA", "SCHEMA", "PROFILE", "SourceCandidateCrosswalkError",
    "prepare_source_candidate_crosswalk_v1", "source_candidate_crosswalk_sha256",
    "validate_source_candidate_crosswalk_v1"]

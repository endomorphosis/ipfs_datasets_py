"""Cold, complete committed-input coverage with paged per-file raw facts.

There is deliberately no repository graph, pytest reconciliation, capsule,
semantic-state bundle, native registration, or completion authority here.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import sys

from ..content import canonical_dag_json_bytes, cid_for_structured
from . import streaming_scanner as streaming
from .chunked_snapshot import ChunkedRepositorySnapshot, _hash_blob
from .committed_snapshot import _fence
from .git_decoder_profile import (DEFAULT_DECODER_PROFILE, DEFAULT_DECODER_BUDGET,
                                 GitBlobDecoderBudget, require_decoder_profile)
from .models import ArtifactRecord, DependencyEdge, SymbolRecord
from .paged_fact_store import (
    OwnedFactStore, PagedFactProfile, FactSpoolBudget, PagedFactError, _closed,
    admit_paging, build_fact_index, iter_fact_index, verify_fact_index,
)
from .paged_fact_worker import implementation_profile, run_file_worker
from .paged_snapshot import admit_chunked_snapshot_manifest
from .pytest_analysis import PytestTestFacts, PytestFixtureFacts, PytestConfigurationFacts, _dag_json
from .scanner import _artifact_path, _opaque_artifact, _typed_artifact
from .snapshot import SnapshotEntry, SnapshotError, _entry, _malformed_raw, _opaque, _kind

GROUPS = ("symbols", "edges", "artifacts", "tests", "fixtures", "configurations")
FILE_SCHEMA = "ipfs-datasets.raw-file-facts@1"
COVERAGE_SCHEMA = "ipfs-datasets.raw-file-coverage@1"
ROOT_SCHEMA = "ipfs-datasets.raw-committed-facts@1"
REQUEST_SCHEMA = "ipfs-datasets.raw-committed-fact-request@1"
DENIALS = {"semantic_reconstruction": False, "complete_analysis_authority": False,
           "completion_authority": False, "global_pytest_reconciliation": False,
           "global_graph_resolution": False}


def _record(group, value):
    """Revalidate the existing closed per-file record models, preserving bytes."""
    if group in {"symbols", "edges", "artifacts"}:
        cls = {"symbols": SymbolRecord, "edges": DependencyEdge, "artifacts": ArtifactRecord}[group]
        expected = cls.from_dict(value).to_dict()
    else:
        cls = {"tests": PytestTestFacts, "fixtures": PytestFixtureFacts,
               "configurations": PytestConfigurationFacts}[group]
        expected = _dag_json(asdict(streaming._pytest_fact(cls, value)))
    if canonical_dag_json_bytes(expected) != canonical_dag_json_bytes(value):
        raise PagedFactError("raw_record_model_changed", stage="analysis")
    return value


def _facts(value, entry, limits):
    _closed(value, {"path", "source_cid", *GROUPS})
    if value["path"] != entry.path or value["source_cid"] != entry.source_cid:
        raise PagedFactError("worker_source_identity", stage="analysis")
    if any(type(value[name]) is not list for name in GROUPS):
        raise PagedFactError("raw_fact_group", stage="analysis")
    wire_size = len(canonical_dag_json_bytes(value))
    if wire_size > limits.max_file_fact_bytes:
        raise PagedFactError("file_fact_budget", stage="analysis", limit=limits.max_file_fact_bytes, observed=wire_size)
    streaming._check_records((_record(group, item) for group in GROUPS for item in value[group]),
                             limits, phase="analysis")
    return wire_size


def _empty_facts(entry, artifact=None):
    result = {"path": entry.path, "source_cid": entry.source_cid, **{name: [] for name in GROUPS}}
    if artifact is not None:
        result["artifacts"].append(artifact.to_dict())
    return result


def _spool_file(store, facts, entry, request_cid, disposition):
    indexes = {}
    for group in GROUPS:
        def pairs():
            for ordinal, record in enumerate(facts[group]):
                store.charge_record()
                yield f"{ordinal:010d}", store.put(record)
        indexes[group] = build_fact_index(store, pairs())
    return store.put({"schema": FILE_SCHEMA, "request_cid": request_cid,
                      "snapshot_entry_cid": entry.entry_cid, "raw_path_hex": entry.raw_path_hex,
                      "path": entry.path, "source_cid": entry.source_cid,
                      "disposition": disposition, "indexes": indexes, **DENIALS})


def _request(chunked, *, manifest_cid, profile, budget, analysis_limits, decoder_profile,
             decoder_budget, implementation, max_file_bytes):
    return {"schema": REQUEST_SCHEMA, "repository_id": chunked.repository_id,
            "git_commit": chunked.git_commit, "git_tree": chunked.git_tree,
            "chunked_snapshot_cid": manifest_cid, "population_cid": chunked.population_cid,
            "population_scope": "complete-committed", "paging_profile": profile.payload(),
            "spool_budget": asdict(budget), "analysis_limits": asdict(analysis_limits),
            "source_file_limit_bytes": max_file_bytes, "retained_source_limit_bytes": 128 * 1024 * 1024,
            "manifest_limits": asdict(chunked.limits), "decoder_profile": decoder_profile.payload(),
            "decoder_budget": asdict(decoder_budget), "implementation": implementation,
            **DENIALS}


def _validate_request(request, store, chunked):
    _closed(request, {"schema", "repository_id", "git_commit", "git_tree", "chunked_snapshot_cid",
        "population_cid", "population_scope", "paging_profile", "spool_budget", "analysis_limits",
        "source_file_limit_bytes", "retained_source_limit_bytes", "manifest_limits", "decoder_profile",
        "decoder_budget", "implementation", *DENIALS}, REQUEST_SCHEMA)
    if (request["population_scope"] != "complete-committed" or
            any(request[key] is not value for key, value in DENIALS.items()) or
            type(request["source_file_limit_bytes"]) is not int or
            not 1 <= request["source_file_limit_bytes"] <= streaming.MAX_MATERIALIZED_FILE_BYTES or
            type(request["retained_source_limit_bytes"]) is not int or
            request["retained_source_limit_bytes"] != 128 * 1024 * 1024 or
            request["manifest_limits"] != asdict(chunked.limits)):
        raise PagedFactError("raw_request_scope_or_limits", stage="verification")
    streaming.StreamingScanLimits(**request["analysis_limits"])
    decoder_budget = GitBlobDecoderBudget(**request["decoder_budget"])
    require_decoder_profile(chunked.decoder_profile, chunked.decoder_profile, decoder_budget)
    if request["decoder_profile"] != chunked.decoder_profile.payload():
        raise PagedFactError("raw_request_decoder", stage="verification")
    _closed(request["implementation"], {"schema", "source_manifest_cid", "source_file_count", "source_bytes",
        "roots", "python_executable", "python_sha256", "python_version", "python_implementation",
        "analysis_process", "target_imports", "source_execution"}, "ipfs-datasets.paged-raw-fact-implementation@1")
    if request["implementation"]["target_imports"] is not False or request["implementation"]["source_execution"] is not False:
        raise PagedFactError("raw_request_implementation", stage="verification")


def verify_raw_fact_coverage(store, root_cid, *, expected_request, chunked):
    """Verify the *raw* output and exact population; never authenticate source execution.

    This verifies a cold scan's content-addressed output, not independently
    re-execution of the analyzer. Content hashing and source fences remain the
    scanner's responsibility. Callers cannot use this as completion admission.
    """
    if type(store) is not OwnedFactStore or type(chunked) is not ChunkedRepositorySnapshot:
        raise PagedFactError("typed_verification_inputs")
    _validate_request(expected_request, store, chunked)
    root = _closed(store.get(root_cid), {"schema", "request", "request_cid", "coverage_index", "entry_count",
        "unique_blob_count", "unique_blob_bytes_verified", "raw_fact_count", "complete_raw_coverage", *DENIALS}, ROOT_SCHEMA)
    if (root["request"] != expected_request or root["request_cid"] != cid_for_structured(expected_request) or
            any(root[key] is not value for key, value in DENIALS.items()) or root["complete_raw_coverage"] is not True):
        raise PagedFactError("raw_root_binding", stage="verification")
    if (expected_request["repository_id"], expected_request["git_commit"], expected_request["git_tree"],
            expected_request["population_cid"], expected_request["chunked_snapshot_cid"],
            expected_request["paging_profile"], expected_request["spool_budget"]) != (
            chunked.repository_id, chunked.git_commit, chunked.git_tree, chunked.population_cid,
            chunked.snapshot_cid, store.profile.payload(), asdict(store.budget)):
        raise PagedFactError("raw_request_population_or_admission", stage="verification")
    expected_counts = (len(chunked.entries), len(chunked.blobs), sum(b.size_bytes for b in chunked.blobs))
    actual_counts = tuple(root[key] for key in ("entry_count", "unique_blob_count", "unique_blob_bytes_verified"))
    if any(type(value) is not int for value in actual_counts) or actual_counts != expected_counts:
        raise PagedFactError("raw_population_counts", stage="verification")
    verify_fact_index(store, root["coverage_index"])
    iterator = iter(iter_fact_index(store, root["coverage_index"]))
    blobs = {item.git_object_oid: item for item in chunked.blobs}
    by_blob = defaultdict(list)
    for member in chunked.entries:
        by_blob[member.git_object_oid].append(member)
    extraction_order = {}
    for blob in chunked.blobs:
        for member in by_blob[blob.git_object_oid]:
            extraction_order[member.raw_path_hex] = len(extraction_order)
    for member in chunked.entries:
        if member.object_type != "blob":
            extraction_order[member.raw_path_hex] = len(extraction_order)
    total_records = 0
    limits = streaming.StreamingScanLimits(**expected_request["analysis_limits"])
    for member in sorted(chunked.entries, key=lambda item: item.raw_path_hex):
        pair = next(iterator, None)
        if pair is None or pair[0] != member.raw_path_hex:
            raise PagedFactError("raw_coverage_population", stage="verification")
        coverage = _closed(store.get(pair[1]), {"schema", "member", "snapshot_entry", "file_root_cid", "extraction_ordinal"}, COVERAGE_SCHEMA)
        if coverage["member"] != member.to_dict():
            raise PagedFactError("raw_coverage_member", stage="verification")
        if (type(coverage["extraction_ordinal"]) is not int or
                coverage["extraction_ordinal"] != extraction_order[member.raw_path_hex]):
            raise PagedFactError("raw_extraction_order", stage="verification")
        entry = SnapshotEntry.from_dict(coverage["snapshot_entry"])
        blob = blobs.get(member.git_object_oid)
        expected_source = blob.source_cid if member.object_type == "blob" else None
        if (entry.raw_path_hex, entry.path, entry.git_blob_oid, entry.head_blob_oid, entry.source_cid,
                entry.disposition) != (member.raw_path_hex, member.path, member.git_object_oid,
                member.git_object_oid, expected_source, "clean"):
            raise PagedFactError("raw_coverage_source", stage="verification")
        if member.object_type == "blob" and entry.size_bytes != member.size_bytes:
            raise PagedFactError("raw_coverage_size", stage="verification")
        forced_reason = ("symlink_or_nonregular" if member.object_type != "blob" else
                         "malformed_path" if _malformed_raw(bytes.fromhex(member.raw_path_hex)) else
                         "symlink_or_nonregular" if member.git_mode == "120000" else
                         "analysis_budget_exceeded" if member.size_bytes > expected_request["source_file_limit_bytes"] else None)
        if forced_reason is not None:
            if not entry.is_opaque or entry.opaque_reason != forced_reason:
                raise PagedFactError("raw_forced_opaque_entry", stage="verification")
        elif entry.is_opaque:
            if entry.opaque_reason != "undecodable":
                raise PagedFactError("raw_unexpected_opaque_reason", stage="verification")
        elif entry.kind != _kind(entry.path):
            raise PagedFactError("raw_entry_kind", stage="verification")
        file = _closed(store.get(coverage["file_root_cid"]), {"schema", "request_cid", "snapshot_entry_cid",
            "raw_path_hex", "path", "source_cid", "disposition", "indexes", *DENIALS}, FILE_SCHEMA)
        if ((file["request_cid"], file["snapshot_entry_cid"], file["raw_path_hex"], file["path"], file["source_cid"]) !=
                (root["request_cid"], entry.entry_cid, entry.raw_path_hex, entry.path, entry.source_cid) or
                any(file[key] is not value for key, value in DENIALS.items()) or
                file["disposition"] not in {"raw-analyzed", "typed-artifact", "opaque"}):
            raise PagedFactError("raw_file_binding", stage="verification")
        _closed(file["indexes"], GROUPS)
        expected_artifact = (_opaque_artifact(entry, entry.opaque_reason) if entry.is_opaque else
                             _opaque_artifact(entry, "raw_path_not_model_safe") if _artifact_path(entry) != entry.path else
                             _typed_artifact(entry) if entry.kind not in {"python", "pytest-config"} else None)
        expected_disposition = ("opaque" if entry.is_opaque or _artifact_path(entry) != entry.path else
                                "typed-artifact" if expected_artifact is not None else "raw-analyzed")
        if file["disposition"] != expected_disposition:
            raise PagedFactError("raw_file_disposition", stage="verification")
        count, byte_count, opaque_count = 0, 0, 0
        envelope_bytes = len(canonical_dag_json_bytes(_empty_facts(entry)))
        symbol_ids = set()
        for group in GROUPS:
            desc = file["indexes"][group]
            verify_fact_index(store, desc)
            if expected_artifact is not None and desc["count"] != (1 if group == "artifacts" else 0):
                raise PagedFactError("raw_projection_artifact_population", stage="verification")
            envelope_bytes += max(0, desc["count"] - 1)
            for ordinal, (key, cid) in enumerate(iter_fact_index(store, desc)):
                if key != f"{ordinal:010d}":
                    raise PagedFactError("raw_record_order", stage="verification")
                value = _record(group, store.get(cid))
                size = len(canonical_dag_json_bytes(value))
                count += 1
                byte_count += size
                envelope_bytes += size
                if (count > limits.max_records or byte_count > limits.max_fact_bytes or
                        size > limits.max_record_bytes or envelope_bytes > limits.max_file_fact_bytes):
                    raise PagedFactError("raw_file_record_budget", stage="verification")
                if group == "symbols":
                    if (value["repository_id"], value["module_path"], value["source_cid"]) != (
                            chunked.repository_id, entry.path, entry.source_cid):
                        raise PagedFactError("raw_symbol_source", stage="verification")
                    symbol_ids.add(value["stable_id"])
                elif group == "edges":
                    if value["source_id"] not in symbol_ids:
                        raise PagedFactError("raw_edge_source", stage="verification")
                elif group == "artifacts":
                    if value["source_cid"] != entry.source_cid or value["path"] != _artifact_path(entry):
                        raise PagedFactError("raw_artifact_source", stage="verification")
                    if expected_artifact is not None and value != expected_artifact.to_dict():
                        raise PagedFactError("raw_projection_artifact_binding", stage="verification")
                elif (value["path"], value["source_cid"]) != (entry.path, entry.source_cid):
                    raise PagedFactError("raw_pytest_source", stage="verification")
                if group == "artifacts" and value["confidence"] == "opaque":
                    opaque_count += 1
                    if value["source_cid"] != entry.source_cid:
                        raise PagedFactError("raw_opaque_source", stage="verification")
                    if entry.is_opaque and value["metadata"].get("opaque_reason") != entry.opaque_reason:
                        raise PagedFactError("raw_opaque_reason", stage="verification")
        if (entry.is_opaque and (file["disposition"] != "opaque" or not opaque_count) or
                member.object_type != "blob" and not entry.is_opaque):
            raise PagedFactError("raw_opaque_coverage", stage="verification")
        total_records += count
        if total_records > store.budget.max_records:
            raise PagedFactError("raw_total_record_budget", stage="verification")
    if next(iterator, None) is not None or type(root["raw_fact_count"]) is not int or total_records != root["raw_fact_count"]:
        raise PagedFactError("raw_coverage_count", stage="verification")
    return root


@dataclass(frozen=True)
class RawFactScan:
    root_cid: str
    request_cid: str
    observation_json: str

    @property
    def observation(self):
        return json.loads(self.observation_json)


def scan_chunked_repository_paged_facts(
    repository, chunked, *, expected_commit, expected_tree, expected_chunked_snapshot_cid,
    repository_id, store, profile, budget, analysis_limits=streaming.StreamingScanLimits(),
    max_file_bytes=streaming.MAX_MATERIALIZED_FILE_BYTES,
    decoder_profile=DEFAULT_DECODER_PROFILE, decoder_budget=DEFAULT_DECODER_BUDGET,
):
    """Hash every committed blob and spool bounded raw facts, with no assembly."""
    progress = {"entries_completed": 0, "blobs_verified": 0, "unique_blob_bytes_verified": 0,
                "raw_fact_bytes": 0, "workers_completed": 0, "stage": "admission", "raw_path_hex": None}
    try:
        admit_paging(profile, budget)
        if (type(store) is not OwnedFactStore or store.profile != profile or store.budget != budget or
                type(chunked) is not ChunkedRepositorySnapshot or type(analysis_limits) is not streaming.StreamingScanLimits):
            raise PagedFactError("typed_scan_inputs")
        analysis_limits.__post_init__()
        if type(max_file_bytes) is not int or not 1 <= max_file_bytes <= streaming.MAX_MATERIALIZED_FILE_BYTES:
            raise PagedFactError("fixed_source_file_limit")
        if sys.platform != "linux":
            raise PagedFactError("unsupported_analysis_platform")
        if (chunked.git_commit, chunked.git_tree, chunked.repository_id) != (expected_commit, expected_tree, repository_id):
            raise PagedFactError("immutable_request_changed")
        root = Path(repository).resolve(strict=True)
        if store.path.is_relative_to(root):
            raise PagedFactError("store_inside_target_repository")
        decoder = require_decoder_profile(chunked.decoder_profile, decoder_profile, decoder_budget)
        manifest_cid, manifest_blocks = chunked.manifest_blocks()
        if manifest_cid != expected_chunked_snapshot_cid:
            raise PagedFactError("immutable_manifest_changed")
        chunked = admit_chunked_snapshot_manifest(root, manifest_cid, manifest_blocks,
            repository_id=repository_id, expected_commit=expected_commit, expected_tree=expected_tree,
            limits=chunked.limits, decoder_profile=decoder, decoder_budget=decoder_budget)
        before = _fence(root, expected_commit, expected_tree, chunked.limits.max_metadata_bytes)
        implementation = implementation_profile()
        request = _request(chunked, manifest_cid=manifest_cid, profile=profile, budget=budget,
            analysis_limits=analysis_limits, decoder_profile=decoder, decoder_budget=decoder_budget,
            implementation=implementation, max_file_bytes=max_file_bytes)
        request_cid = store.bind_request(request)
        members = defaultdict(list)
        for member in chunked.entries:
            members[member.git_object_oid].append(member)
        coverage = []  # references only, bounded by the unchanged metadata limit
        coverage_bytes = peak_source = peak_worker_rss = 0

        def remember(member, entry, data):
            nonlocal coverage_bytes, peak_worker_rss
            progress.update(stage="analysis", raw_path_hex=entry.raw_path_hex)
            entry = replace(entry, captured_bytes=None)
            if entry.is_opaque:
                facts, disposition = _empty_facts(entry, _opaque_artifact(entry, entry.opaque_reason or "opaque_snapshot")), "opaque"
            elif _artifact_path(entry) != entry.path:
                facts, disposition = _empty_facts(entry, _opaque_artifact(entry, "raw_path_not_model_safe")), "opaque"
            elif entry.kind not in {"python", "pytest-config"}:
                facts, disposition = _empty_facts(entry, _typed_artifact(entry)), "typed-artifact"
            else:
                facts, resources = run_file_worker({"operation": "analysis", "path": entry.path,
                    "repository_id": repository_id, "source_cid": entry.source_cid, "kind": entry.kind},
                    data, analysis_limits, implementation)
                progress["workers_completed"] += 1
                peak_worker_rss = max(peak_worker_rss, resources["peak_rss_bytes"])
                disposition = "raw-analyzed"
            progress["raw_fact_bytes"] += _facts(facts, entry, analysis_limits)
            progress["stage"] = "spooling"
            file_cid = _spool_file(store, facts, entry, request_cid, disposition)
            record = {"schema": COVERAGE_SCHEMA, "member": member.to_dict(),
                      "snapshot_entry": entry.to_dict(), "file_root_cid": file_cid,
                      "extraction_ordinal": progress["entries_completed"]}
            cid = store.put(record)
            pair = [entry.raw_path_hex, cid]
            coverage_bytes += len(canonical_dag_json_bytes(pair))
            if coverage_bytes > min(chunked.limits.max_metadata_bytes, profile.working_bytes // 4):
                raise PagedFactError("coverage_metadata_budget", stage="spooling")
            coverage.append(pair)
            progress["entries_completed"] += 1

        for blob in chunked.blobs:
            progress.update(stage="content", raw_path_hex=members[blob.git_object_oid][0].raw_path_hex)
            capture = any(member.git_mode in {"100644", "100755"} and member.size_bytes <= max_file_bytes
                          and not _malformed_raw(bytes.fromhex(member.raw_path_hex)) for member in members[blob.git_object_oid])
            observed, data = _hash_blob(root, blob.git_object_oid, blob.size_bytes, chunked.limits.frame_bytes,
                                       capture=capture, decoder_profile=decoder)
            if observed != blob:
                raise PagedFactError("committed_content_mismatch", stage="content")
            progress["blobs_verified"] += 1
            progress["unique_blob_bytes_verified"] += blob.size_bytes
            peak_source = max(peak_source, len(data) if data is not None else 0)
            for member in members[blob.git_object_oid]:
                raw = bytes.fromhex(member.raw_path_hex)
                reason = ("malformed_path" if _malformed_raw(raw) else "symlink_or_nonregular" if member.git_mode == "120000" else
                          "analysis_budget_exceeded" if member.size_bytes > max_file_bytes else None)
                entry = (SnapshotEntry(member.path, "opaque", member.size_bytes, blob.source_cid, reason, member.raw_path_hex,
                         member.git_object_oid, "git-object", "clean", member.git_object_oid) if reason else
                         _entry(member.path, raw, data, max_file_bytes, member.git_object_oid, disposition="clean",
                                head_oid=member.git_object_oid, acquisition="git-object"))
                remember(member, entry, data)
            del data
        for member in chunked.entries:
            if member.object_type != "blob":
                remember(member, _opaque(member.path, "symlink_or_nonregular", None, raw=bytes.fromhex(member.raw_path_hex),
                    oid=member.git_object_oid, disposition="clean", head_oid=member.git_object_oid), None)
        progress.update(stage="verification", raw_path_hex=None)
        coverage_index = build_fact_index(store, sorted(coverage))
        del coverage
        result = {"schema": ROOT_SCHEMA, "request": request, "request_cid": request_cid,
                  "coverage_index": coverage_index, "entry_count": progress["entries_completed"],
                  "unique_blob_count": progress["blobs_verified"],
                  "unique_blob_bytes_verified": progress["unique_blob_bytes_verified"],
                  "raw_fact_count": store.usage()["records"], "complete_raw_coverage": True, **DENIALS}
        result_cid = store.put(result)
        verify_raw_fact_coverage(store, result_cid, expected_request=request, chunked=chunked)
        progress["stage"] = "final-fence"
        if _fence(root, expected_commit, expected_tree, chunked.limits.max_metadata_bytes) != before:
            raise PagedFactError("source_changed_during_scan", stage="final-fence")
        if implementation_profile() != implementation:
            raise PagedFactError("implementation_profile_changed", stage="final-fence")
        require_decoder_profile(chunked.decoder_profile, decoder_profile, decoder_budget)
        progress["stage"] = "publication"
        store.publish_raw_coverage(result_cid)
        observation = {"schema": "ipfs-datasets.paged-raw-fact-scan@1", **progress, "stage": "raw-coverage-published",
                       "request_cid": request_cid, "root_cid": result_cid, "complete_raw_coverage": True,
                       "retained_snapshot_source_bytes": 0, "peak_captured_blob_bytes": peak_source,
                       "peak_worker_rss_bytes": peak_worker_rss, "usage": store.usage(), **DENIALS}
        return RawFactScan(result_cid, request_cid, canonical_dag_json_bytes(observation).decode())
    except (PagedFactError, streaming.StreamingAnalysisError, SnapshotError, OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, PagedFactError):
            error = exc
        else:
            error = PagedFactError(getattr(exc, "code", "failure_" + type(exc).__name__), stage=progress["stage"],
                                   limit=getattr(exc, "limit", None), observed=getattr(exc, "observed", None))
        error.path = progress["raw_path_hex"]
        error.progress = {**progress, "usage": store.usage() if type(store) is OwnedFactStore else {}}
        raise error from (exc if error is not exc else None)


__all__ = ["RawFactScan", "scan_chunked_repository_paged_facts", "verify_raw_fact_coverage"]

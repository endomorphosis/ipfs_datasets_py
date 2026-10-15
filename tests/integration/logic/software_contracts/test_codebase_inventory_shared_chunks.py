"""Pure shared-manifest chunk controls with actual immutable CAS reopening.

Numerical and lifecycle documents below are explicitly synthetic advisory
records, not native worker qualification. These tests never launch inference,
fit a model, import a scanned repository, or infer process drain from a receipt.
Separate native controls exercise the real coordinator and process observer.
"""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_shared_chunks as chunks
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_resume as legacy
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_chunks as full_targets
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import SnapshotEntry


def digest(name):
    return hashlib.sha256(name.encode()).hexdigest()


def cid(name):
    return cid_for_structured({"synthetic_protocol_control": name})


def root_record(count=7, page_entries=3, max_rows=1024, optimized=True):
    snapshot = cid("snapshot")
    head = CodebaseHead("synthetic-chunk-protocol", 1, cid("manifest"), snapshot,
        "rev:synthetic-chunk-protocol:snapshot:" + snapshot, cid("publication"))
    members = []
    for index in range(count):
        raw = f"def item{index}(n):\n    return n + {index}\n".encode()
        entry = SnapshotEntry(f"item{index:04d}.py", "source", len(raw), cid_for_bytes(raw))
        members.append({"source_key": entry.source_key, "path": entry.path, "raw_path_hex": entry.raw_path_hex,
            "entry_cid": entry.entry_cid, "source_cid": entry.source_cid, "ast_cid": cid(f"ast{index}"),
            "parse_status": "ok", "source_size_bytes": len(raw), "opaque_reason": None})
    artifact = {"sha256": digest("synthetic-model"), "bytes": len(b"synthetic-model")}
    model = {"version_id": "synthetic-version", "variant_id": "synthetic-variant", "artifact": artifact,
        "artifact_cid": cid_for_bytes(b"synthetic-model"), "contract_sha256": digest("contract"),
        "state_sha256": digest("state"), "feature_space_sha256": digest("basis"), "latent_width": 8,
        "feature_columns": 2, "projection_ids": ["a", "b"], "projection_widths": {"a": 1, "b": 1},
        "ancestry": [{"version_id": "synthetic-version", "artifact": artifact}]}
    files = {"synthetic.protocol.only": digest("implementation")}
    value = {"schema": legacy.ROOT_SCHEMA, "head": head.to_dict(), "head_cid": cid_for_structured(head.to_dict()),
        "members": members, "membership_cid": cid_for_structured(members), "model": model,
        "limits": legacy.CodebaseScanResumeLimits(max_inventory_entries=512, page_entries=page_entries, max_inferred_rows=max_rows).to_dict(),
        "optimized": optimized, "implementation": {"files": files, "sha256": legacy.features.digest(files),
            "scope": "listed_local_files_only_not_execution_attestation"}, "authority": dict(legacy._FALSE)}
    return legacy.CodebaseScanResumeRoot.from_dict(cid_for_structured(value), value)


def lifecycle_document():
    # This is a protocol fixture; these PIDs are not claims about real processes.
    return {"schema": "native-owned-tool-lifecycle@1", "parent": {"pid": 100, "birth_ticks": 1000},
        "leader": {"pid": 200, "birth_ticks": 2000, "parent_pid": 100, "process_group_id": 200, "session_id": 200},
        "observed_descendants": [], "leader_reaped": True, "descendant_tracking_complete": True,
        "group_scan_complete": True, "remaining_group_members": [], "remaining_tracked_descendants": [],
        "readers": {"started": 2, "joined": 2}, "stdin_writer": {"started": 1, "joined": 1},
        "workspace": {"device": 1, "inode": 2, "removed": True}, "observation_errors": [],
        "ownership_is_sampled": True, "kernel_containment_attested": False, "cleanup_confirmed": True}


def coverage():
    return [{"projection_id": key, "known_atoms": 1, "unknown_atoms": 0} for key in ("a", "b")]


def chunk_body(root, page_start, indices, ordinal=0, previous=None):
    r = root.to_dict()
    sources = [digest(f"source-target-{index}") for index in indices]
    inference = {"schema": "native-projection-feature-inference/v1",
        **{key: r["model"][key] for key in ("contract_sha256", "state_sha256", "feature_space_sha256")},
        "rows": [{"source_digest": source, "latent": [0.25] * 8,
                  "reconstructed_projection_features": {"a": [0.0], "b": [0.5]}} for source in sources],
        "coverage": [item for _ in indices for item in coverage()], "training_executed": False,
        "decoded_formulas_generated": False,
        "representation": "native_compiler_structural_features_not_semantic_text_embeddings",
        **legacy.features.FALSE}
    receipt = {"executable_sha256": digest("python"), "worker_sha256": digest("worker"),
        "input_sha256": digest("input"), "output_sha256": digest("output"), "input_bytes": 1000 + len(indices) * 500,
        "output_bytes": 100, "elapsed_ms": 0, "returncode": 0, "workspace_cleaned": True,
        "limits": {"resident_memory_bytes": 1024 * 1024 * 1024,
            "max_input_bytes": r["limits"]["max_input_bytes"], "max_output_bytes": r["limits"]["max_output_bytes"]},
        "memory_enforcement": "sampled_process_tree_rss_with_possible_overshoot", "source_execution_attested": False}
    count, optimized = len(indices), r["optimized"]
    replays = (1 if optimized else 2) * count
    counters = {"shared_inventory_validations": 1, "shared_manifest_parses": 1,
        "shared_receipt_parses": 1, "shared_replay_preparations": 1 if optimized else 0,
        "target_restorations": count, "native_target_replays": replays,
        "native_lowering_replays": replays, "full_target_comparisons": replays,
        "streamed_feature_rows": count, "matrix_builds": 1, "vocabulary_builds": 1,
        "weight_tensor_builds": 4, "input_tensor_builds": 1,
        "contract_validations": 1 if optimized else 2, "state_validations": 1 if optimized else 2,
        "rows": count, "training_calls": 0, "max_retained_restored_targets": 1,
        "gc_collections": 0 if optimized else count}
    return {"schema": chunks.CHUNK_SCHEMA, "profile": chunks.PROFILE, "root_cid": root.artifact_cid,
        "head_cid": r["head_cid"], "membership_cid": r["membership_cid"],
        "model_artifact_cid": r["model"]["artifact_cid"], "model_state_sha256": r["model"]["state_sha256"],
        "optimized": optimized, "page_start": page_start,
        "page_end": min(page_start + r["limits"]["page_entries"], len(r["members"])),
        "chunk_ordinal": ordinal, "previous_chunk_cid": previous, "member_indices": indices,
        "target_sha256s": [digest(f"target-{index}") for index in indices], "source_digests": sources,
        "shared_inventory_sha256": digest("synthetic-shared-inventory"),
        "transport_bytes": {"shared": 200, "compact_targets": 100 * count,
            "restored_targets": 300 * count, "feature_cells": count * r["model"]["feature_columns"],
            "maximum_restored_targets": 1},
        "inference": inference, "worker_receipt": receipt, "worker_counters": counters,
        "worker_profile": {"python": "synthetic", "torch": "synthetic", "device": "cpu", "dtype": "float64",
            "cpu_threads": 1, "repository_code_executed": False, "registry_opened": False,
            "training_executed": False, "proof_authority": False, "decoded_formulas_generated": False},
        "lifecycle_receipt": lifecycle_document(), "authority": dict(legacy._FALSE)}


def record(cls, value):
    raw = legacy._wire(value)
    return cls(cid_for_bytes(raw), raw)


def page_body(root, start, records, previous=None, skipped=()):
    r = root.to_dict()
    end = min(start + r["limits"]["page_entries"], len(r["members"]))
    mapping = {index: (chunk.to_dict()["chunk_ordinal"], row_index)
               for chunk in records for row_index, index in enumerate(chunk.to_dict()["member_indices"])}
    entries = []
    for index in range(start, end):
        inferred = index not in skipped
        ordinal, row_index = mapping[index] if inferred else (None, None)
        member = r["members"][index]
        entries.append({"member_index": index, "source_key": member["source_key"], "entry_cid": member["entry_cid"],
            "disposition": "inferred" if inferred else "unsupported_target", "reason": None if inferred else "synthetic_control",
            "target_sha256": digest(f"target-{index}") if inferred else None,
            "source_digest": digest(f"source-target-{index}") if inferred else None,
            "coverage": coverage() if inferred else [], "chunk_ordinal": ordinal, "row_index": row_index})
    dispositions = {"inferred": len(mapping)} if mapping else {}
    if skipped:
        dispositions["unsupported_target"] = len(skipped)
    return {"schema": chunks.PAGE_SCHEMA, "profile": chunks.PROFILE, "root_cid": root.artifact_cid,
        "head_cid": r["head_cid"], "membership_cid": r["membership_cid"], "model_artifact_cid": r["model"]["artifact_cid"],
        "start": start, "end": end, "total_entries": len(r["members"]),
        "page_membership_cid": cid_for_structured(r["members"][start:end]), "previous_page_cid": previous,
        "entries": entries, "chunks": [chunks.chunk_descriptor(chunk) for chunk in records],
        "coverage": {"inventory_entries": end - start, "inferred_rows": len(mapping),
            "projection_records": 2 * len(mapping), "chunks": len(records), "dispositions": dispositions},
        "authority": dict(legacy._FALSE)}


def protocol_chain(root):
    pages, all_chunks, previous = [], {}, None
    r = root.to_dict()
    for start in range(0, len(r["members"]), r["limits"]["page_entries"]):
        end = min(start + r["limits"]["page_entries"], len(r["members"]))
        skipped = (start + 1,) if end - start >= 3 else ()
        records, tail = [], None
        for index in range(start, end):
            if index in skipped:
                continue
            chunk = record(chunks.CodebaseScanNumericalChunk, chunk_body(root, start, [index], len(records), tail))
            records.append(chunk)
            all_chunks[chunk.artifact_cid] = chunk
            tail = chunk.artifact_cid
        page = record(chunks.CodebaseScanChunkedPage, page_body(root, start, records, previous, skipped))
        pages.append(page)
        previous = page.artifact_cid
    value = {"schema": chunks.COMPLETION_SCHEMA, "profile": chunks.PROFILE, "root_cid": root.artifact_cid,
        "head_cid": r["head_cid"], "membership_cid": r["membership_cid"], "model_artifact_cid": r["model"]["artifact_cid"],
        **chunks.validate_codebase_scan_chunked_chain(root, pages, all_chunks), "authority": dict(legacy._FALSE)}
    return pages, all_chunks, record(chunks.CodebaseScanChunkedCompletion, value)


@pytest.mark.parametrize("optimized", [True, False])
def test_actual_cas_roundtrip_and_cold_reopen_preserve_explicit_chunk_mapping(tmp_path, optimized):
    root = root_record(optimized=optimized)
    pages, chunk_map, completion = protocol_chain(root)
    cas = ImmutableCAS(tmp_path / "chunks", max_object_bytes=chunks.MAX_ARTIFACT_BYTES)
    assert cas.put(root.to_dict()) == root.artifact_cid
    for artifact in [*chunk_map.values(), *pages, completion]:
        assert cas.put_bytes(artifact._payload) == artifact.artifact_cid
    reopened = ImmutableCAS(cas.root, max_object_bytes=chunks.MAX_ARTIFACT_BYTES)
    loaded_chunks = {identity: chunks.CodebaseScanNumericalChunk(identity, reopened.get_bytes(identity))
                     for identity in chunk_map}
    loaded_pages = [chunks.CodebaseScanChunkedPage(page.artifact_cid, reopened.get_bytes(page.artifact_cid)) for page in pages]
    loaded_completion = chunks.CodebaseScanChunkedCompletion(completion.artifact_cid, reopened.get_bytes(completion.artifact_cid))
    chunks.bind_codebase_scan_chunked_completion(loaded_completion, root, loaded_pages, loaded_chunks)
    ledger = loaded_completion.to_dict()["coverage"]
    assert ledger == {"inventory_entries": 7, "inferred_rows": 5, "projection_records": 10,
                      "chunks": 5, "pages": 3, "dispositions": {"inferred": 5, "unsupported_target": 2}}
    assert loaded_pages[0].to_dict()["chunks"][1]["member_indices"] == [2]
    cursor = chunks.CodebaseScanChunkedCursor.from_page(root, loaded_pages[0])
    assert cursor.next_offset == 3 and cursor.previous_page_cid == loaded_pages[0].artifact_cid
    assert chunks.CodebaseScanChunkedCursor.from_dict(json.loads(json.dumps(cursor.to_dict()))) == cursor
    assert chunks.CodebaseScanChunkedCursor.from_page(root, loaded_pages[-1]) is None
    refs = loaded_completion.advisory_refs(root)
    assert chunks.validate_codebase_scan_chunked_completion_refs(refs) == refs
    refs["members"][0]["path"] = "changed.py"
    with pytest.raises(chunks.CodebaseScanChunkError):
        chunks.validate_codebase_scan_chunked_completion_refs(refs)


@pytest.mark.parametrize("mutation", ["old_schema", "missing", "extra", "empty", "bool_index", "duplicate_index",
    "row_order", "source", "state", "latent_width", "projection_width", "counters", "training", "optimization",
    "receipt_cap", "prefix", "nonfinite"])
def test_rehashed_chunk_records_reject_protocol_or_registered_model_mismatch(mutation):
    root = root_record()
    value = chunk_body(root, 0, [0, 2])
    if mutation == "old_schema":
        value["schema"] = legacy.PAGE_SCHEMA
    elif mutation == "missing":
        del value["worker_receipt"]
    elif mutation == "extra":
        value["execution_authority"] = False
    elif mutation == "empty":
        value["member_indices"] = []
    elif mutation == "bool_index":
        value["member_indices"][0] = False
    elif mutation == "duplicate_index":
        value["member_indices"] = [0, 0]
    elif mutation == "row_order":
        value["inference"]["rows"].reverse()
    elif mutation == "source":
        value["source_digests"][0] = digest("foreign-source")
    elif mutation == "state":
        value["inference"]["state_sha256"] = value["model_state_sha256"] = digest("foreign-state")
    elif mutation == "latent_width":
        value["inference"]["rows"][0]["latent"].append(0.0)
    elif mutation == "projection_width":
        value["inference"]["rows"][0]["reconstructed_projection_features"]["a"].append(0.0)
    elif mutation == "counters":
        value["worker_counters"]["rows"] = True
    elif mutation == "training":
        value["worker_profile"]["training_executed"] = True
    elif mutation == "optimization":
        value["optimized"] = False
        for key in ("native_target_replays", "native_lowering_replays", "full_target_comparisons"):
            value["worker_counters"][key] = 4
        value["worker_counters"]["shared_replay_preparations"] = 0
        value["worker_counters"]["contract_validations"] = value["worker_counters"]["state_validations"] = 2
    elif mutation == "receipt_cap":
        value["worker_receipt"]["limits"]["max_input_bytes"] -= 1
    elif mutation == "prefix":
        value["previous_chunk_cid"] = cid_for_bytes(b"foreign-prefix")
    elif mutation == "nonfinite":
        value["inference"]["rows"][0]["latent"][0] = float("nan")
    with pytest.raises(chunks.CodebaseScanChunkError):
        chunk = record(chunks.CodebaseScanNumericalChunk, value)
        chunks.bind_codebase_scan_chunk(chunk, root)


@pytest.mark.parametrize("mutation", ["bool_pid", "foreign_parent", "wrong_group", "unreaped", "tracking",
    "remaining", "reader", "writer", "workspace", "errors", "kernel", "false_cleanup", "duplicate_descendant"])
def test_lifecycle_documents_refuse_incomplete_or_ambiguous_ownership_accounting(mutation):
    value = lifecycle_document()
    if mutation == "bool_pid":
        value["leader"]["pid"] = True
    elif mutation == "foreign_parent":
        value["leader"]["parent_pid"] += 1
    elif mutation == "wrong_group":
        value["leader"]["process_group_id"] += 1
    elif mutation == "unreaped":
        value["leader_reaped"] = False
    elif mutation == "tracking":
        value["group_scan_complete"] = False
    elif mutation == "remaining":
        value["remaining_group_members"] = [deepcopy(value["leader"])]
    elif mutation == "reader":
        value["readers"]["joined"] = 1
    elif mutation == "writer":
        value["stdin_writer"]["joined"] = 0
    elif mutation == "workspace":
        value["workspace"]["removed"] = False
    elif mutation == "errors":
        value["observation_errors"] = ["observation failed"]
    elif mutation == "kernel":
        value["kernel_containment_attested"] = True
    elif mutation == "false_cleanup":
        value["cleanup_confirmed"] = False
    elif mutation == "duplicate_descendant":
        item = {"pid": 300, "birth_ticks": 3000, "parent_pid": 200, "process_group_id": 200, "session_id": 200}
        value["observed_descendants"] = [item, deepcopy(item)]
    with pytest.raises(chunks.CodebaseScanChunkError):
        chunks.validate_codebase_chunk_lifecycle_receipt(value)


@pytest.mark.parametrize("mutation", ["old_schema", "missing_chunk", "reordered_chunk", "row_index", "member_index",
    "descriptor_sha", "descriptor_bytes", "target_digest", "source_digest", "coverage", "authority", "bool_offset"])
def test_page_mapping_rejects_rehashed_gaps_reorders_and_chunk_substitution(mutation):
    root = root_record()
    pages, chunk_map, _ = protocol_chain(root)
    value = pages[0].to_dict()
    if mutation == "old_schema":
        value["schema"] = legacy.PAGE_SCHEMA
    elif mutation == "missing_chunk":
        value["chunks"].pop()
    elif mutation == "reordered_chunk":
        value["chunks"].reverse()
    elif mutation == "row_index":
        value["entries"][2]["row_index"] = 1
    elif mutation == "member_index":
        value["entries"][2]["member_index"] = 1
    elif mutation == "descriptor_sha":
        value["chunks"][0]["sha256"] = digest("wrong-chunk-bytes")
    elif mutation == "descriptor_bytes":
        value["chunks"][0]["bytes"] += 1
    elif mutation == "target_digest":
        value["entries"][0]["target_sha256"] = digest("foreign-target")
    elif mutation == "source_digest":
        value["entries"][0]["source_digest"] = digest("foreign-target-source")
    elif mutation == "coverage":
        value["entries"][0]["coverage"][0]["known_atoms"] += 1
    elif mutation == "authority":
        value["authority"]["proof_authority"] = True
    elif mutation == "bool_offset":
        value["start"] = False
    with pytest.raises(chunks.CodebaseScanChunkError):
        page = record(chunks.CodebaseScanChunkedPage, value)
        chunks.bind_codebase_scan_chunked_page(page, root,
            {descriptor["chunk_cid"]: chunk_map[descriptor["chunk_cid"]] for descriptor in value["chunks"]})


def test_complete_chain_refuses_missing_foreign_reordered_chunks_and_old_pages():
    root = root_record()
    pages, chunk_map, completion = protocol_chain(root)
    first = next(iter(chunk_map))
    for bad_chunks in ({key: value for key, value in chunk_map.items() if key != first},
                       {**chunk_map, cid_for_bytes(b"foreign"): chunk_map[first]}):
        with pytest.raises(chunks.CodebaseScanChunkError):
            chunks.bind_codebase_scan_chunked_completion(completion, root, pages, bad_chunks)
    with pytest.raises(chunks.CodebaseScanChunkError):
        chunks.validate_codebase_scan_chunked_chain(root, list(reversed(pages)), chunk_map)
    with pytest.raises(chunks.CodebaseScanChunkError):
        chunks.validate_codebase_scan_chunked_chain(root, [*pages, pages[-1]], chunk_map)
    with pytest.raises(chunks.CodebaseScanChunkError):
        chunks.CodebaseScanChunkedCursor.from_dict({"schema": legacy.CURSOR_SCHEMA, "root_cid": root.artifact_cid,
            "next_offset": 3, "previous_page_cid": pages[0].artifact_cid})


def test_global_row_budget_and_foreign_root_are_checked_beyond_saved_counts():
    root = root_record(max_rows=4)
    # Each page is well formed, but the complete prefix has five numerical rows.
    normal = root_record()
    pages, chunk_map, completion = protocol_chain(normal)
    with pytest.raises(chunks.CodebaseScanChunkError):
        chunks.bind_codebase_scan_chunked_completion(completion, root, pages, chunk_map)
    with pytest.raises(chunks.CodebaseScanChunkError):
        chunks.CodebaseScanChunkedCursor.from_page(root, pages[0])
    # Rebuild identities under the smaller budget; aggregate enforcement remains.
    with pytest.raises(chunks.CodebaseScanChunkError, match="global inferred row"):
        protocol_chain(root)


@pytest.mark.parametrize("cls", [chunks.CodebaseScanNumericalChunk, chunks.CodebaseScanChunkedPage,
                                 chunks.CodebaseScanChunkedCompletion])
def test_every_immutable_artifact_independently_rejects_over_ceiling_bytes(cls):
    oversized = b" " * (chunks.MAX_ARTIFACT_BYTES + 1)
    with pytest.raises(chunks.CodebaseScanChunkError, match="bounded immutable"):
        cls(cid_for_bytes(oversized), oversized)


@pytest.mark.parametrize("raw", [b'{"schema":"one","schema":"two"}', b'{"x":NaN}', b'{"x":Infinity}',
                                  b'{ "schema" : "noncanonical" }'])
def test_json_duplicate_nonfinite_and_noncanonical_bytes_are_refused(raw):
    with pytest.raises(chunks.CodebaseScanChunkError):
        chunks.CodebaseScanNumericalChunk(cid_for_bytes(raw), raw)


def test_non_numerical_page_has_no_worker_receipt_or_empty_chunk_request():
    root = root_record(count=3)
    value = page_body(root, 0, [], skipped=(0, 1, 2))
    page = record(chunks.CodebaseScanChunkedPage, value)
    assert chunks.bind_codebase_scan_chunked_page(page, root, []) == value
    assert page.to_dict()["coverage"]["chunks"] == 0
    assert page.to_dict()["coverage"]["projection_records"] == 0
    assert "worker_receipt" not in page.to_dict()


def test_legacy_single_request_records_retain_historical_110_row_interpretation():
    """Synthetic inert ledgers preserve the old counts without upgrading them."""
    root = root_record(count=300, page_entries=64)
    r = root.to_dict()
    pages, previous, counts = [], None, {}
    for start in range(0, 300, 64):
        end = min(start + 64, 300)
        indices = list(range(start + (1 if start == 0 else 0), start + (23 if start == 0 else 22)))
        numerical = chunk_body(root, start, indices)
        entries = []
        for member_index in range(start, end):
            member = r["members"][member_index]
            disposition = "inferred" if member_index in indices else "deferred_budget"
            if member_index == 0:
                disposition = "unindexed"
            elif member_index in (295, 296):
                disposition = "opaque"
            elif member_index == 297:
                disposition = "parse_failed"
            elif member_index in (298, 299):
                disposition = "unsupported_target"
            inferred = disposition == "inferred"
            entries.append({"member_index": member_index, "source_key": member["source_key"],
                "entry_cid": member["entry_cid"], "disposition": disposition,
                "reason": None if inferred else "synthetic_legacy_control",
                "target_sha256": digest(f"target-{member_index}") if inferred else None,
                "source_digest": digest(f"source-target-{member_index}") if inferred else None,
                "coverage": coverage() if inferred else [],
                "inference_index": indices.index(member_index) if inferred else None})
        page_counts = {}
        for entry in entries:
            name = entry["disposition"]
            page_counts[name] = page_counts.get(name, 0) + 1
            counts[name] = counts.get(name, 0) + 1
        value = {"schema": legacy.PAGE_SCHEMA, "root_cid": root.artifact_cid, "head_cid": r["head_cid"],
            "membership_cid": r["membership_cid"], "model_artifact_cid": r["model"]["artifact_cid"],
            "start": start, "end": end, "total_entries": 300,
            "page_membership_cid": cid_for_structured(r["members"][start:end]), "previous_page_cid": previous,
            "entries": entries, "inference": numerical["inference"], "worker_receipt": numerical["worker_receipt"],
            "coverage": {"inventory_entries": end - start, "inferred_rows": 22,
                         "dispositions": dict(sorted(page_counts.items()))}, "authority": dict(legacy._FALSE)}
        raw = legacy._wire(value)
        page = legacy.CodebaseScanResumePage(cid_for_bytes(raw), raw)
        legacy._bind_page(page, root)
        pages.append(page)
        previous = page.artifact_cid
    value = legacy._completion_value(root, [legacy._descriptor(page) for page in pages], 300, 110, counts)
    completion = legacy.CodebaseScanResumeCompletion.from_dict(cid_for_structured(value), value)
    assert legacy.validate_codebase_scan_completion_refs(completion.advisory_refs(root))["coverage"] == {
        "inventory_entries": 300, "inferred_rows": 110, "pages": 5,
        "dispositions": {"deferred_budget": 184, "inferred": 110, "opaque": 2,
                         "parse_failed": 1, "unindexed": 1, "unsupported_target": 2}}
    assert type(pages[0].next_cursor) is legacy.CodebaseScanResumeCursor
    with pytest.raises(chunks.CodebaseScanChunkError):
        chunks.validate_codebase_scan_chunked_chain(root, pages, {})


@pytest.mark.parametrize("mutation", ["shared_sha", "transport_missing", "transport_extra", "shared_bool",
    "shared_zero", "shared_ceiling", "compact_bool", "compact_zero", "compact_ceiling", "restored_float",
    "restored_zero", "restored_ceiling", "cells_bool", "cells_ceiling", "cells_root", "retention_bool",
    "retention_zero", "retention_two", "input_conservation"])
def test_transport_records_refuse_ambiguous_or_over_budget_accounting(mutation):
    root = root_record()
    value = chunk_body(root, 0, [0, 2])
    transport = value["transport_bytes"]
    if mutation == "shared_sha":
        value["shared_inventory_sha256"] = "A" * 64
    elif mutation == "transport_missing":
        del transport["restored_targets"]
    elif mutation == "transport_extra":
        transport["saved_bytes"] = 0
    elif mutation == "shared_bool":
        transport["shared"] = True
    elif mutation == "shared_zero":
        transport["shared"] = 0
    elif mutation == "shared_ceiling":
        transport["shared"] = chunks.MAX_SHARED_BYTES + 1
    elif mutation == "compact_bool":
        transport["compact_targets"] = True
    elif mutation == "compact_zero":
        transport["compact_targets"] = 0
    elif mutation == "compact_ceiling":
        transport["compact_targets"] = 2 * chunks.MAX_TARGET_BYTES + 1
    elif mutation == "restored_float":
        transport["restored_targets"] = 600.0
    elif mutation == "restored_zero":
        transport["restored_targets"] = 0
    elif mutation == "restored_ceiling":
        transport["restored_targets"] = 2 * chunks.MAX_TARGET_BYTES + 1
    elif mutation == "cells_bool":
        transport["feature_cells"] = True
    elif mutation == "cells_ceiling":
        transport["feature_cells"] = chunks.MAX_FEATURE_CELLS + 1
    elif mutation == "cells_root":
        transport["feature_cells"] += 1
    elif mutation == "retention_bool":
        transport["maximum_restored_targets"] = True
    elif mutation == "retention_zero":
        transport["maximum_restored_targets"] = 0
    elif mutation == "retention_two":
        transport["maximum_restored_targets"] = 2
    elif mutation == "input_conservation":
        value["worker_receipt"]["input_bytes"] = transport["shared"] + transport["compact_targets"] - 1
    with pytest.raises(chunks.CodebaseScanChunkError):
        chunk = record(chunks.CodebaseScanNumericalChunk, value)
        chunks.bind_codebase_scan_chunk(chunk, root)


@pytest.mark.parametrize("counter", ["shared_inventory_validations", "shared_manifest_parses",
    "shared_receipt_parses", "shared_replay_preparations", "target_restorations", "native_target_replays",
    "native_lowering_replays", "full_target_comparisons", "streamed_feature_rows", "matrix_builds",
    "vocabulary_builds", "weight_tensor_builds", "input_tensor_builds", "contract_validations",
    "state_validations", "rows", "training_calls", "max_retained_restored_targets", "gc_collections"])
@pytest.mark.parametrize("optimized", [True, False])
def test_each_streamed_counter_requires_exact_work_accounting(counter, optimized):
    root = root_record(optimized=optimized)
    value = chunk_body(root, 0, [0, 2])
    value["worker_counters"][counter] += 1
    with pytest.raises(chunks.CodebaseScanChunkError):
        record(chunks.CodebaseScanNumericalChunk, value)


def test_root_target_limit_is_enforced_independently_of_global_transport_ceiling():
    base = root_record().to_dict()
    base["limits"]["max_target_bytes"] = 200
    root = legacy.CodebaseScanResumeRoot.from_dict(cid_for_structured(base), base)
    value = chunk_body(root, 0, [0, 2])
    chunk = record(chunks.CodebaseScanNumericalChunk, value)
    with pytest.raises(chunks.CodebaseScanChunkError, match="feature/target accounting"):
        chunks.bind_codebase_scan_chunk(chunk, root)


def test_explicit_shared_versions_cannot_replace_full_target_chunk_or_page_records():
    root = root_record()
    pages, chunk_map, _ = protocol_chain(root)
    shared_chunk = next(iter(chunk_map.values()))
    with pytest.raises(full_targets.CodebaseScanChunkError):
        full_targets.CodebaseScanNumericalChunk(shared_chunk.artifact_cid, shared_chunk._payload)
    with pytest.raises(full_targets.CodebaseScanChunkError):
        full_targets.CodebaseScanChunkedPage(pages[0].artifact_cid, pages[0]._payload)
    with pytest.raises(full_targets.CodebaseScanChunkError):
        full_targets.CodebaseScanChunkedCursor.from_dict(pages[0].next_cursor.to_dict())
    value = shared_chunk.to_dict()
    value["schema"] = full_targets.CHUNK_SCHEMA
    value["profile"] = full_targets.PROFILE
    del value["shared_inventory_sha256"], value["transport_bytes"]
    counters = value["worker_counters"]
    value["worker_counters"] = {key: counters[key] for key in ("native_target_replays", "matrix_builds",
        "vocabulary_builds", "weight_tensor_builds", "input_tensor_builds", "contract_validations",
        "state_validations", "rows", "training_calls")}
    original_chunk = record(full_targets.CodebaseScanNumericalChunk, value)
    full_targets.bind_codebase_scan_chunk(original_chunk, root)
    with pytest.raises(chunks.CodebaseScanChunkError):
        chunks.CodebaseScanNumericalChunk(original_chunk.artifact_cid, original_chunk._payload)
    with pytest.raises(chunks.CodebaseScanChunkError):
        chunks.bind_codebase_scan_chunk(original_chunk, root)


def test_shared_and_restored_transport_accounting_preserve_distinct_meanings():
    root = root_record()
    value = chunk_body(root, 0, [0, 2])
    chunk = record(chunks.CodebaseScanNumericalChunk, value)
    reopened = chunks.CodebaseScanNumericalChunk(chunk.artifact_cid, chunk._payload)
    bound = chunks.bind_codebase_scan_chunk(reopened, root)
    assert bound["transport_bytes"] == {"shared": 200, "compact_targets": 200,
        "restored_targets": 600, "feature_cells": 4, "maximum_restored_targets": 1}
    # Inert documents preserve declared wire counts; only native receiving can
    # reconstruct their actual shared and per-target bytes or observe retention.
    assert all(flag is False for flag in bound["authority"].values())


def test_shared_record_binders_refuse_a_coherently_rebased_wider_root():
    normal = root_record(count=3)
    value = normal.to_dict()
    value["limits"]["max_inventory_entries"] = 1024
    wide = legacy.CodebaseScanResumeRoot.from_dict(cid_for_structured(value), value)
    chunk = record(chunks.CodebaseScanNumericalChunk, chunk_body(wide, 0, [0, 1, 2]))
    page = record(chunks.CodebaseScanChunkedPage, page_body(wide, 0, [chunk]))
    completion = record(chunks.CodebaseScanChunkedCompletion, {
        "schema": chunks.COMPLETION_SCHEMA, "profile": chunks.PROFILE,
        "root_cid": wide.artifact_cid, "head_cid": value["head_cid"],
        "membership_cid": value["membership_cid"], "model_artifact_cid": value["model"]["artifact_cid"],
        "pages": [chunks.page_descriptor(page)],
        "coverage": {**page.to_dict()["coverage"], "pages": 1}, "authority": dict(legacy._FALSE)})
    for binder, item in ((chunks.bind_codebase_scan_chunk, chunk),
                         (chunks.bind_codebase_scan_chunked_page_root, page),
                         (chunks.bind_codebase_scan_chunked_completion_root, completion)):
        with pytest.raises(chunks.CodebaseScanChunkError, match="shared512"):
            binder(item, wide)

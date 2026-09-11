"""Independently reconstructable SPAR source evidence, without acceptance.

This module does not run the target, infer successful tests from nominations,
or issue an accepted root. Its caller supplies repository *identities*, never
prebuilt semantic roots or an issuer callback. Native execution custody and
current-owner admission belong to the accelerator owner.
"""
from __future__ import annotations

import json
import subprocess
from types import MappingProxyType
from pathlib import Path
from typing import Any

from ..content import cid_for_structured
from ..semantic_index.scanner import RepositoryScanner
from ..semantic_index.snapshot import snapshot_repository, _IGNORED_DIRECTORIES
from .api import build_semantic_state, open_semantic_state, verify_semantic_state_bundle
from .source import read_required_source, SourceAdmissionError

SCHEMA = "ipfs-datasets/spar-source-verification@1"
REQUIRED_COVERAGE = (
    "current_committed_source_chunk_semantic_reconstruction",
    "all_required_language_and_dynamic_semantics",
    "required_mode_roots_and_transitions",
    "differential_trace_selection_and_proof_execution",
    "noncompensable_safety_floors_with_failure_denominators",
    "self_hosted_capstone_and_procedure_reuse",
    "two_epoch_seven_slice_fixed_point",
    "native_runtime_callback_and_merge_settlement",
)
MAX_ENTRIES = 12000
MAX_FILE_BYTES = 8 * 1024
MAX_CHUNK_FILES = 8
MAX_CHUNK_BYTES = 16 * 1024


class SparVerificationError(ValueError):
    pass


class _CapturedSourceView:
    """Existing source-reader protocol over this execution's frozen index.

    Compute the actual full state CID once. Rehashing an immutable whole index
    twice for every symbol otherwise makes source verification quadratic.
    No caller-provided CID, symbols, reader callback or acceptance is admitted.
    """
    def __init__(self, index, captured_blobs):
        self.state_cid = index.state_cid
        self._symbols = MappingProxyType({s.stable_id: s for s in index.symbols})
        self._blobs = MappingProxyType(dict(captured_blobs))

    def symbol(self, stable_symbol_id):
        return self._symbols[stable_symbol_id]

    def read_source_blob(self, source_cid):
        return self._blobs[source_cid]


def _git(path, *args):
    return subprocess.run(["/usr/bin/git", "-c", "core.fsmonitor=false", *args],
                          cwd=path, check=True, capture_output=True, timeout=10).stdout


def _current(spec):
    state = (_git(spec["path"], "rev-parse", "HEAD").decode().strip(),
             _git(spec["path"], "rev-parse", "HEAD^{tree}").decode().strip())
    flags = _git(spec["path"], "ls-files", "-v", "-z").split(b"\0")
    if (state != (spec["head"], spec["tree"])
            or _git(spec["path"], "status", "--porcelain=v1", "--untracked-files=all")
            or any(row and (chr(row[0]).islower() or row[:1] == b"S") for row in flags)):
        raise SparVerificationError("source_generation_or_working_state_changed")


def _source_chunk(spec):
    """Deterministic first chunk; complete omitted inventory remains evidence."""
    _current(spec)
    records = _git(spec["path"], "ls-tree", "-r", "-l", "-z", spec["head"]).split(b"\0")
    inventory, selected, omitted, byte_count = [], [], [], 0
    for raw in records:
        if not raw:
            continue
        metadata, path_bytes = raw.split(b"\t", 1)
        mode, kind, oid, size = metadata.decode("ascii").split()
        path = path_bytes.decode("utf-8", "strict")
        if path.startswith("/") or any(p in {"", ".", ".."} for p in path.split("/")):
            raise SparVerificationError("unsafe_inventory_path")
        row = {"path": path, "mode": mode, "kind": kind, "oid": oid,
               "size": None if size == "-" else int(size)}
        eligible = (mode in {"100644", "100755"} and path.endswith((".py", ".pyi"))
                    and not any(part in _IGNORED_DIRECTORIES for part in path.split("/"))
                    and row["size"] <= MAX_FILE_BYTES)
        chosen = eligible and len(selected) < MAX_CHUNK_FILES and byte_count + row["size"] <= MAX_CHUNK_BYTES
        row["selected"] = chosen
        inventory.append(row)
        if chosen:
            selected.append(path); byte_count += row["size"]
        else:
            omitted.append(path)
    if not selected:
        raise SparVerificationError("no_supported_python_source_in_first_chunk")
    if len(inventory) > MAX_ENTRIES:
        raise SparVerificationError("inventory_exceeds_native_bound")
    record = {"schema": "ipfs-datasets/spar-committed-source-chunk@1",
              "repository": spec["repository"], "head": spec["head"], "tree": spec["tree"],
              "max_files": MAX_CHUNK_FILES, "max_file_bytes": MAX_FILE_BYTES,
              "max_total_bytes": MAX_CHUNK_BYTES, "inventory": inventory,
              "unprocessed_entry_count": len(omitted), "full_semantic_coverage": False}
    return record, selected, omitted


def reconstruct_source(repositories: list[dict[str, str]]) -> dict[str, Any]:
    """Read actual Git objects and verify semantic blocks and source spans.

    Opaque/unsupported source remains in each snapshot and limitation ledger.
    A reconstruction result does not attest target behavior or completeness.
    Expected negative test vectors are not interpreted as failed executions.
    """
    if (type(repositories) is not list or not 1 <= len(repositories) <= 8
            or len({r.get("repository") for r in repositories}) != len(repositories)):
        raise SparVerificationError("repository_population_invalid")
    results, blocks = [], {}
    for spec in repositories:
        if (set(spec) != {"repository", "path", "head", "tree"}
                or any(type(v) is not str or not v for v in spec.values())
                or not Path(spec["path"]).is_absolute()):
            raise SparVerificationError("repository_identity_invalid")
        inventory, selected, omitted = _source_chunk(spec)
        snapshot = snapshot_repository(
            spec["path"], repository_id="spar-source:" + spec["repository"],
            max_entries=MAX_ENTRIES, max_file_bytes=MAX_FILE_BYTES,
            exclusions=omitted,
        )
        if (snapshot.mode != "git-clean" or snapshot.git_commit != spec["head"]
                or snapshot.git_tree != spec["tree"]):
            raise SparVerificationError("source_generation_or_working_state_changed")
        captured = {entry.source_key: entry.captured_bytes for entry in snapshot.entries
                    if entry.captured_bytes is not None}
        index = RepositoryScanner(repository_id=snapshot.repository_id).scan_snapshot(snapshot, captured)
        bundle = build_semantic_state(index)
        root = verify_semantic_state_bundle(bundle)
        # Verify the consumer path against the same immutable block bytes.
        open_semantic_state(root.root_cid, bundle.get_block)
        blobs = {entry.source_cid: entry.captured_bytes for entry in snapshot.entries
                 if entry.source_cid and entry.captured_bytes is not None}
        source_view = _CapturedSourceView(index, blobs)
        source_evidence, source_limitations = [], []
        for symbol in index.symbols:
            try:
                material = read_required_source(source_view, symbol.stable_id,
                    expected_producer_state_cid=source_view.state_cid)
                source_evidence.append(material.evidence.to_dict())
            except (SourceAdmissionError, KeyError) as exc:
                source_limitations.append({"symbol_id": symbol.stable_id, "reason": type(exc).__name__})
        for cid, raw in bundle.blocks.items():
            decoded = json.loads(raw)
            if cid_for_structured(decoded) != cid:
                raise SparVerificationError("noncanonical_semantic_block")
            if cid in blocks and blocks[cid] != decoded:
                raise SparVerificationError("semantic_block_conflict")
            blocks[cid] = decoded
        snapshot_record = snapshot.to_dict()
        blocks[snapshot.snapshot_cid] = snapshot.identity_payload()
        inventory_cid = cid_for_structured(inventory)
        blocks[inventory_cid] = inventory
        _current(spec)
        results.append({
            "repository": spec["repository"], "head": spec["head"], "tree": spec["tree"],
            "snapshot_cid": snapshot.snapshot_cid, "semantic_state_root_cid": root.root_cid,
            "producer_state_cid": source_view.state_cid, "entry_count": len(snapshot.entries),
            "source_chunk_inventory_cid": inventory_cid, "selected_paths": selected,
            "unprocessed_entry_count": inventory["unprocessed_entry_count"],
            "symbol_count": len(index.symbols), "block_count": len(bundle.blocks),
            "source_evidence": source_evidence, "source_limitations": source_limitations,
            "opaque_entries": [{"path": e.path, "reason": e.opaque_reason}
                               for e in snapshot.entries if e.is_opaque],
            "snapshot_exclusions": snapshot_record["exclusions"],
            "analysis_completeness": "unverified",
        })
    report = {
        "schema": SCHEMA, "repositories": results,
        "verified_coverage": [REQUIRED_COVERAGE[0]],
        "missing_coverage": list(REQUIRED_COVERAGE[1:]),
        "target_program_executed": False, "accepted_root": False,
        "semantic_acceptance_authority": False, "completion_authority": False,
    }
    return {"report": report, "report_cid": cid_for_structured(report), "blocks": blocks}

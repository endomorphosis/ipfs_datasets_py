"""Explicit fenced draining of owner-prepared, source-manifest-bound spans.

This module never prepares missing source rows, calls legacy claim helpers,
imports a compiler, opens another database, uploads, or dispatches goals.
Full worker observations enter the existing immutable exchange before the
bounded native completion. References preserve data, not semantic authority.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Callable
import uuid

from .span_cache_claims import CLAIM_SCHEMA, MAX_LEASE_SECONDS, SpanClaimError, _hash, _revision, _token
from .span_cache_exchange import _immutable_write, _read_regular_snapshot, load_exchange_bundle
from .supervisor_queue import canonical_bytes

SOURCE_SCHEMA = "span-cache-fenced-ingest-source/v1"
RESULT_SCHEMA = "span-cache-fenced-ingest-result-reference/v1"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_CONTROL_BYTES = 65_536
MAX_BATCH = 32
MAX_SOURCE_BATCH_BYTES = 16 * 1024 * 1024
_FALSE = dict(qualified=False, admitted=False, formalized=False, roundtrip_ok=False)


class FencedIngestError(RuntimeError):
    """Explicit source, staging, or caller boundary failed; no fallback applies."""


def need(condition, message):
    if not condition:
        raise FencedIngestError(message)


def closed(value, fields, label):
    need(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def encoded(value, bound):
    raw = canonical_bytes(value)
    need(len(raw) <= bound, "fenced ingestion payload exceeds its explicit byte bound")
    return raw


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def binding_operation_id(manifest_id, binding):
    return "fenced-ingest:bind:" + digest({"manifest": manifest_id, "binding": binding})


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        need(key not in value, "duplicate source manifest JSON key")
        value[key] = item
    return value


def load_source_manifest(path):
    path = Path(path)
    body = _read_regular_snapshot(path, max_bytes=MAX_MANIFEST_BYTES)
    manifest = json.loads(body, object_pairs_hook=_unique_object)
    validate_source_manifest(manifest)
    return manifest, {"path": str(path.resolve()), "bytes": len(body),
                      "sha256": hashlib.sha256(body).hexdigest()}


def validate_source_manifest(manifest):
    closed(manifest, ("schema", "corpus_id", "release_id", "source_revision", "spans"), "source manifest")
    need(manifest["schema"] == SOURCE_SCHEMA, "source manifest version differs")
    _token(manifest["corpus_id"], "corpus ID")
    _token(manifest["release_id"], "release ID")
    _revision(manifest["source_revision"])
    spans = manifest["spans"]
    need(type(spans) is list and 0 < len(spans) <= 65536, "bounded explicit source span population required")
    seen = set()
    for row in spans:
        closed(row, ("source_span_id", "legal_id", "source_sha256", "expected_binding"), "manifest span")
        _token(row["source_span_id"], "span ID")
        _token(row["legal_id"], "legal ID")
        _hash(row["source_sha256"])
        need(row["source_span_id"] not in seen, "duplicate source span identity")
        seen.add(row["source_span_id"])
        if row["expected_binding"] is not None:
            closed(row["expected_binding"], ("source_revision", "source_sha256"), "expected binding")
            _revision(row["expected_binding"]["source_revision"])
            _hash(row["expected_binding"]["source_sha256"])
    encoded(manifest, MAX_MANIFEST_BYTES)


def file_reference(path, root, maximum=MAX_OUTPUT_BYTES):
    path = Path(path)
    need(not path.is_symlink() and path.resolve().is_relative_to(Path(root).resolve()),
         "staged artifact escapes the owner exchange directory")
    body = _read_regular_snapshot(path, max_bytes=maximum)
    return {"path": str(path.resolve()), "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest()}


def verify_reference(ref, root):
    closed(ref, ("path", "bytes", "sha256"), "staged reference")
    need(type(ref["path"]) is str and type(ref["bytes"]) is int and ref["bytes"] >= 0,
         "typed immutable file reference required")
    _hash(ref["sha256"])
    actual = file_reference(ref["path"], root, max(MAX_OUTPUT_BYTES, MAX_MANIFEST_BYTES))
    need(actual == ref, "staged immutable bytes changed")


def stage_complete_observation(output, destination, stage_exchange, *, release_id, code_identity, path_hashes):
    """Retain the whole worker row and verify the existing exchange closure."""
    original = encoded(output, MAX_OUTPUT_BYTES)
    root = Path(destination).resolve()
    output_path = root / ("fenced-output-" + hashlib.sha256(original).hexdigest() + ".json")
    _immutable_write(output_path, original)
    output_ref = file_reference(output_path, root)
    expected = {**output, "release_id": release_id, "code_identity": code_identity,
                "compiler_path_hashes": dict(path_hashes)}
    staged = stage_exchange([output])
    need(type(staged) is dict and type(staged.get("manifests")) is list and staged["manifests"],
         "existing exchange supplied no immutable manifest")
    refs, census_count, goal_count, matched = [], 0, 0, 0
    for path in staged["manifests"]:
        ref = file_reference(path, root, 1024 * 1024)
        bundle = load_exchange_bundle(path)
        need(bundle["manifest"].get("admitted") is False and bundle["manifest"].get("formalized") is False,
             "exchange cannot confer authority")
        for row in bundle["census_rows"]:
            if row["source_span_id"] == output["source_span_id"]:
                need(json.loads(row["input_json"]) == expected, "exchange discarded or changed full worker evidence")
                matched += 1
        census_count += len(bundle["census_rows"])
        goal_count += len(bundle["goal_rows"])
        refs.append(ref)
    need(matched == 1 and census_count == 1, "exact one-span staged census population required")
    result = {"schema": RESULT_SCHEMA, "worker_output": output_ref,
              "exchange_manifests": refs, "census_rows": census_count, "goal_rows": goal_count, **_FALSE}
    verify_staged_observation(result, root)
    return result


def verify_staged_observation(result, root, *, historical_evidence_roots=()):
    from ...optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import _safe_path
    from .span_cache_exchange import _manifest_file
    need(type(historical_evidence_roots) in (list, tuple) and len(historical_evidence_roots) <= 64,
         "bounded explicit historical evidence roots required")
    allowed = [_safe_path(root, directory=True)] + [_safe_path(path, directory=True) for path in historical_evidence_roots]
    def owner_root(ref):
        path = _safe_path(ref["path"])
        matches = [base for base in allowed if path.is_relative_to(base)]
        need(matches, "historical staged artifact escapes its explicit owner roots")
        return matches[0]
    need(type(result) is dict and result.get("schema") == RESULT_SCHEMA, "fenced result reference schema differs")
    base = {"schema", "worker_output", "exchange_manifests", "census_rows", "goal_rows", *_FALSE}
    scoped = {"source_manifest_digest", "source_manifest_scope"}
    need(set(result) in (base, base | scoped), "closed fenced result reference required")
    need(all(result[flag] is False for flag in _FALSE), "staged references cannot confer authority")
    need(type(result["census_rows"]) is int and result["census_rows"] == 1
         and type(result["goal_rows"]) is int and result["goal_rows"] >= 0, "exact staged population required")
    refs = result["exchange_manifests"]
    need(type(refs) is list and 0 < len(refs) <= MAX_BATCH, "bounded immutable exchange closure required")
    if scoped <= set(result):
        _hash(result["source_manifest_digest"])
        scope = result["source_manifest_scope"]
        closed(scope, ("corpus_id", "release_id", "source_revision"), "source manifest scope")
        _token(scope["corpus_id"], "corpus ID")
        _token(scope["release_id"], "release ID")
        _revision(scope["source_revision"])
    verify_reference(result["worker_output"], owner_root(result["worker_output"]))
    census_count, goal_count = 0, 0
    for ref in refs:
        base = owner_root(ref)
        verify_reference(ref, base)
        # Refuse a downloaded-layout escape before decoding either Parquet.
        manifest = json.loads(_read_regular_snapshot(ref["path"], max_bytes=1024*1024))
        for kind in ("census", "goals"):
            material = _safe_path(_manifest_file(Path(ref["path"]), manifest, manifest[kind]))
            need(material.is_relative_to(base), "historical exchange material escapes its explicit owner root")
        bundle = load_exchange_bundle(ref["path"])
        census_count += len(bundle["census_rows"])
        goal_count += len(bundle["goal_rows"])
    need(census_count == result["census_rows"] and goal_count == result["goal_rows"],
         "persisted staged population differs")


def _saved_terminal(owner, span_id, revision, source_sha, code_identity, path_hashes, root, manifest_digest, historical_evidence_roots=()):
    if owner._binding(owner._connection, span_id) != {"source_revision": revision, "source_sha256": source_sha}:
        return False
    current = owner._connection.execute(
        "SELECT decompiled,rule_json,code_identity,path_hashes FROM span_cache WHERE source_span_id=?", [span_id]).fetchone()
    if current is None or current[2] != code_identity:
        return False
    try:
        cached_paths, cached_repair = json.loads(current[3] or "{}"), json.loads(current[1] or "null")
    except (ValueError, TypeError):
        return False
    if cached_paths != path_hashes or type(cached_repair) is not dict:
        return False
    rows = owner._connection.execute(
        """SELECT operation_id,result_json,code_identity,path_hashes
           FROM span_claim_results
           WHERE source_span_id=? AND code_identity=?
             AND json_extract_string(TRY_CAST(result_json AS JSON), '$.claim.source_span_id')=?
             AND json_extract_string(TRY_CAST(result_json AS JSON), '$.claim.source_revision')=?
             AND json_extract_string(TRY_CAST(result_json AS JSON), '$.claim.source_sha256')=?
             AND json_extract_string(TRY_CAST(result_json AS JSON), '$.repair.source_manifest_digest')=?
             AND json_extract_string(TRY_CAST(result_json AS JSON), '$.decompiled')=?
             AND json_extract(TRY_CAST(result_json AS JSON), '$.repair')=TRY_CAST(? AS JSON)
           ORDER BY operation_id DESC LIMIT 64""",
        [span_id, code_identity, span_id, revision, source_sha, manifest_digest, current[0], current[1]]).fetchall()
    for operation_id, raw_result, code, paths in rows:
        try:
            row, saved_paths = json.loads(raw_result), json.loads(paths)
        except (ValueError, TypeError):
            continue
        if type(row) is not dict or type(row.get("claim")) is not dict or type(row.get("repair")) is not dict:
            continue
        claim, repair = row.get("claim", {}), row.get("repair", {})
        if (claim.get("source_revision") == revision and claim.get("source_sha256") == source_sha
                and code == code_identity and saved_paths == path_hashes
                and repair.get("schema") == RESULT_SCHEMA and repair.get("source_manifest_digest") == manifest_digest
                and row.get("decompiled") == current[0] and repair == cached_repair):
            try:
                owner.read_completion_results_fenced(operation_id, [row], code_identity=code_identity, path_hashes=path_hashes)
            except SpanClaimError:
                # A result row alone cannot stand in for its exact committed
                # operation. Keep it held for explicit owner reconciliation.
                continue
            verify_staged_observation(repair, root, historical_evidence_roots=historical_evidence_roots)
            return True
    return False


def drain_fenced_manifest(cache, manifest, *, worker_pool, compile_worker: Callable,
                          stage_exchange: Callable, exchange_dir, code_identity, path_hashes,
                          source_guard: Callable, worker_id="fenced-ingest-owner", batch_size=16,
                          max_spans=32, lease_seconds=300, start_index=0, max_examined=256,
                          historical_evidence_roots=()):
    """Bounded owner selection/resume; worker and staging boundaries are injectable.

    Tests inject metadata-only workers/stagers. Real callers must supply the
    canonical compiler preflight/source guard and retain ordinary Lake gates.
    This diagnostic profile never asserts independent autoencoder agreement.
    """
    validate_source_manifest(manifest)
    need(type(batch_size) is int and 1 <= batch_size <= MAX_BATCH, "batch_size must be 1..32")
    need(type(max_spans) is int and 1 <= max_spans <= 4096, "max_spans must be 1..4096")
    need(type(start_index) is int and 0 <= start_index <= len(manifest["spans"]), "start_index outside manifest")
    need(type(max_examined) is int and 1 <= max_examined <= 4096, "max_examined must be 1..4096")
    need(type(lease_seconds) in (float, int) and math.isfinite(lease_seconds)
         and 0 < lease_seconds <= MAX_LEASE_SECONDS, "finite bounded native lease required")
    _token(worker_id, "worker ID")
    _token(code_identity, "code identity")
    need(type(path_hashes) is dict and path_hashes, "explicit compiler source hashes required")
    for path, value in path_hashes.items():
        need(type(path) is str and path, "explicit compiler path required")
        _hash(value)
    need(callable(source_guard) and callable(compile_worker) and callable(stage_exchange), "explicit caller boundaries required")
    owner = cache.fenced_claims()
    owner._check_owner()
    need(cache._meta("dataset_id") == manifest["corpus_id"], "manifest corpus differs from existing owner-prepared cache")
    root = Path(exchange_dir).resolve()
    manifest_id = digest(manifest)
    result = {"schema": "span-cache-fenced-ingest-run/v1", "claim_profile": "fenced-v1",
              "production_state": "selected_private_fenced_profile_not_production_verified",
              "source_manifest_digest": manifest_id, "manifest_span_count": len(manifest["spans"]),
              "processed": 0, "resumed": 0, "held": [], "completions": [],
              "start_manifest_index": start_index, "examined": 0, "examined_span_limit": max_examined,
              "selected_span_limit": max_spans, "census_rows": 0, "goal_rows": 0,
              "training_started": False, "Hub_upload_performed": False, "goals_enqueued": False, **_FALSE}
    started = time.perf_counter()
    def guard():
        need(source_guard() == path_hashes, "canonical compiler source changed during fenced work")
    guard()
    selected, next_index = [], start_index
    for index in range(start_index, len(manifest["spans"])):
        if len(selected) >= max_spans or result["examined"] >= max_examined:
            break
        spec = manifest["spans"][index]
        result["examined"] += 1
        next_index = index + 1
        owner._check_owner()
        try:
            span = owner._span(owner._connection, spec["source_span_id"])
        except SpanClaimError:
            result["held"].append({"source_span_id": spec["source_span_id"], "reason": "owner_source_missing_or_invalid"})
            continue
        if span["source_sha256"] != spec["source_sha256"] or span["legal_id"] != spec["legal_id"]:
            result["held"].append({"source_span_id": spec["source_span_id"], "reason": "source_identity_drift"})
            continue
        current_binding = owner._binding(owner._connection, spec["source_span_id"])
        desired_binding = {"source_revision": manifest["source_revision"], "source_sha256": spec["source_sha256"]}
        if current_binding != spec["expected_binding"] and current_binding != desired_binding:
            result["held"].append({"source_span_id": spec["source_span_id"], "reason": "source_binding_drift"})
            continue
        if span["status"] in {"gap", "sealed"} and current_binding != desired_binding:
            result["held"].append({"source_span_id": spec["source_span_id"], "reason": "terminal_source_binding_drift"})
            continue
        if current_binding == desired_binding and current_binding != spec["expected_binding"]:
            binding = {"source_span_id": spec["source_span_id"], **desired_binding,
                       "expected_binding": spec["expected_binding"]}
            try:
                receipt = owner.resolve_operation(binding_operation_id(manifest_id, binding),
                                                  "BindSpanSources", {"bindings": [binding]})
            except SpanClaimError:
                receipt = None
            if receipt is None:
                result["held"].append({"source_span_id": spec["source_span_id"],
                                       "reason": "source_binding_requires_explicit_expected_binding"})
                continue
        if span["status"] in {"gap", "sealed"}:
            if _saved_terminal(owner, spec["source_span_id"], manifest["source_revision"], spec["source_sha256"], code_identity, path_hashes, root, manifest_id, historical_evidence_roots):
                result["resumed"] += 1
            else:
                result["held"].append({"source_span_id": spec["source_span_id"], "reason": "terminal_row_requires_explicit_owner_reconciliation"})
            continue
        if span["status"] == "claimed":
            old = owner._connection.execute("SELECT envelope FROM span_fenced_claims WHERE source_span_id=?", [spec["source_span_id"]]).fetchone()
            if old is None:
                result["held"].append({"source_span_id": spec["source_span_id"], "reason": "legacy_claim_not_reclaimable"})
                continue
            try:
                old = json.loads(old[0])
            except (ValueError, TypeError):
                old = None
            if (type(old) is not dict or old.get("schema") != CLAIM_SCHEMA
                    or old.get("source_span_id") != spec["source_span_id"]
                    or type(old.get("owner_generation")) is not int or old["owner_generation"] < 1
                    or type(old.get("expires_at")) not in (float, int) or not math.isfinite(old["expires_at"])):
                result["held"].append({"source_span_id": spec["source_span_id"], "reason": "persisted_claim_requires_owner_reconciliation"})
                continue
            if old["owner_generation"] == owner.owner_generation and old["expires_at"] > owner._now():
                result["held"].append({"source_span_id": spec["source_span_id"], "reason": "current_live_claim"})
                continue
        elif span["status"] not in {"pending", "unsealed"} or span["sealed"]:
            result["held"].append({"source_span_id": spec["source_span_id"], "reason": "unsupported_native_source_status"})
            continue
        selected.append(spec)
    result["next_manifest_index"] = next_index if next_index < len(manifest["spans"]) else None
    result["remaining_manifest_rows"] = len(manifest["spans"])-next_index
    for offset in range(0, len(selected), batch_size):
        specs = selected[offset:offset+batch_size]
        bindings = [{"source_span_id": row["source_span_id"], "source_revision": manifest["source_revision"],
                     "source_sha256": row["source_sha256"], "expected_binding": row["expected_binding"]} for row in specs]
        guard()
        for binding in bindings:
            bind_id = binding_operation_id(manifest_id, binding)
            owner.bind_sources_fenced(bind_id, [binding])
            need(owner._binding(owner._connection, binding["source_span_id"]) == {
                 "source_revision": binding["source_revision"], "source_sha256": binding["source_sha256"]},
                 "historical binding receipt differs from current source binding")
        attempt = "fenced-ingest:" + uuid.uuid4().hex
        claimed = owner.claim_batch_fenced(attempt+":claim", worker_id,
            [row["source_span_id"] for row in specs], lease_seconds=lease_seconds)
        pending = {claim["source_span_id"]: claim for claim in claimed["claims"]}
        try:
            inputs, source_bytes = [], 0
            for claim in claimed["claims"]:
                source = owner.read_claim_source_fenced(claim)
                need(claim["source_revision"] == manifest["source_revision"], "claimed source revision differs from manifest")
                item = {"source_span_id": claim["source_span_id"], "legal_id": source["legal_id"],
                        "text": source["text"], "source_revision": claim["source_revision"],
                        "source_sha256": claim["source_sha256"]}
                if "source_provenance_json" in source:
                    item["source_provenance_json"] = source["source_provenance_json"]
                source_bytes += len(encoded(item, MAX_SOURCE_BATCH_BYTES))
                need(source_bytes <= MAX_SOURCE_BATCH_BYTES, "source batch exceeds the existing bounded exchange input size")
                inputs.append(item)
            observed = set()
            # Preserve owner observations even when an in-process worker mutates its input.
            for output in worker_pool.map(compile_worker, [dict(item) for item in inputs]):
                need(type(output) is dict, "worker returned no complete observation")
                span_id = output.get("source_span_id")
                need(span_id in pending and span_id not in observed, "worker output population differs")
                claim = pending[span_id]
                source = next(item for item in inputs if item["source_span_id"] == span_id)
                need(output.get("text") == source["text"] and output.get("legal_id") == source["legal_id"], "worker source bytes or legal identity differs")
                need(type(output.get("rule")) is dict and type(output.get("decompiled")) is str,
                     "worker did not retain exact rule and decompilation")
                need(all(output.get(flag) is None or output.get(flag) is False for flag in _FALSE), "worker cannot claim qualification authority")
                for field in ("source_sha256", "source_text_sha256"):
                    need(field not in output or output[field] == claim["source_sha256"], "worker source digest differs")
                need("source_revision" not in output or output["source_revision"] == claim["source_revision"], "worker source revision differs")
                binding_evidence = {"schema": "span-cache-fenced-ingest-source-binding/v1",
                    "origin": "native_fenced_claim", "source_span_id": span_id,
                    "source_revision": claim["source_revision"], "source_sha256": claim["source_sha256"],
                    "legal_id": claim["legal_id"], **_FALSE}
                need("fenced_source_binding" not in output or output["fenced_source_binding"] == binding_evidence,
                     "worker conflicts with owner-bound source provenance")
                # Coordinate metadata is an observation supplied by the live
                # owner, separate from the unchanged closed authority envelope.
                expected_provenance = source.get("source_provenance_json")
                for echo in (output, output.get("source_provenance")):
                    if isinstance(echo, dict) and "source_provenance_json" in echo:
                        need(expected_provenance is not None
                             and echo["source_provenance_json"] == expected_provenance,
                             "worker source coordinate provenance differs from owner")
                if expected_provenance is not None:
                    output = {**output, "source_provenance_json": expected_provenance}
                # Some existing workers omit their immutable input binding.
                # Retain every observation field, add the owner's verified
                # identity, and label its origin; never replace a conflict.
                output = {**output, "source_revision": claim["source_revision"],
                          "source_sha256": claim["source_sha256"], "fenced_source_binding": binding_evidence}
                observed.add(span_id)
                guard()
                staged = stage_complete_observation(output, root, stage_exchange,
                    release_id=manifest["release_id"], code_identity=code_identity, path_hashes=path_hashes)
                staged["source_manifest_digest"] = manifest_id
                staged["source_manifest_scope"] = {key: manifest[key] for key in ("corpus_id", "release_id", "source_revision")}
                control_row = {"claim": claim, "agrees": False, "rule": output["rule"], "decompiled": output["decompiled"],
                               "repair": staged, "reason": "diagnostic_fenced_ingest_no_independent_model_qualification"}
                payload = {"rows": [control_row], "code_identity": code_identity, "path_hashes": path_hashes}
                encoded(payload, MAX_CONTROL_BYTES)
                guard()
                verify_staged_observation(staged, root)
                operation = attempt+":complete:"+digest(span_id)
                receipt = owner.complete_claimed_fenced(operation, **payload)
                result["completions"].append({"source_span_id": span_id, "operation_id": operation,
                    "receipt": receipt, "worker_output": staged["worker_output"], "exchange_manifests": staged["exchange_manifests"], **_FALSE})
                result["processed"] += 1
                result["census_rows"] += staged["census_rows"]
                result["goal_rows"] += staged["goal_rows"]
                pending.pop(span_id)
            need(observed == {row["source_span_id"] for row in specs}, "worker omitted a claimed source span")
        except BaseException as exc:
            # Never release by bare IDs or replace stale foreign/current claims.
            failures = []
            for span_id, claim in list(pending.items()):
                try:
                    owner.release_claims_fenced(attempt+":release:"+digest(span_id), [claim])
                except BaseException as release_error:
                    failures.append({"source_span_id": span_id, "refusal_type": type(release_error).__name__})
            if failures:
                exc.add_note("Exact claim cleanup refused: " + json.dumps(failures, sort_keys=True))
            raise
    guard()
    result["wall_seconds"] = time.perf_counter()-started
    result["status"] = "held_requires_owner_reconciliation" if result["held"] else "completed_selected_fenced_work"
    return result

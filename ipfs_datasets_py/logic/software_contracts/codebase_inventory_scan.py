"""Finite whole-inventory structural inference with source and model fences.

This additive profile never fits a feature basis, executes repository code,
registers a model, promotes a head, or grants proof/planning authority.  Its
raw CIDv1 record uses canonical finite native JSON because numerical values
are deliberately excluded from this project's DAG-JSON identity codec.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import importlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import sysconfig
import time

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.logic.backends.process import BoundedToolRunner, ToolRunLimits, run_bounded_stdin_tool
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_feature_worker as numerical
from . import codebase_source_training as training
from .codebase_ir import CodebaseScanLimits, StaleCodebaseError
from .codebase_resources import acquire_codebase_resources
from .content import cid_for_bytes, cid_for_structured
from .semantic_index.snapshot import snapshot_repository

SCHEMA = "codebase-inventory-feature-scan@1"
PROFILE = "source_bound_inventory_scan_v1"
_FALSE = {**training._FALSE, "training_executed": False, "decoded_formulas_generated": False,
          "repository_code_executed": False, "semantic_formula_decoder": False}
_DISPOSITIONS = frozenset(("inferred", "opaque", "unindexed", "parse_failed", "parse_partial",
                          "unsupported_target", "feature_incompatible", "deferred_budget"))
_TABLES = ("meta", "variants", "versions", "heads", "runs", "operations", "events", "outbox")


class CodebaseInventoryScanError(ValueError):
    """A bound, evidence identity, numerical result or final fence failed."""


def _require(condition, message):
    if not condition:
        raise CodebaseInventoryScanError(message)


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise CodebaseInventoryScanError("finite inert native JSON required") from exc


@dataclass(frozen=True, slots=True)
class CodebaseInventoryScanLimits:
    max_entries: int = 256
    max_file_bytes: int = 64 * 1024
    max_shards: int = 16
    max_rows_per_shard: int = 16
    max_inferred_rows: int = 256
    max_target_bytes: int = 4 * 1024 * 1024
    max_shard_bytes: int = 8 * 1024 * 1024
    max_input_bytes: int = 32 * 1024 * 1024
    max_output_bytes: int = 16 * 1024 * 1024
    max_registry_rows: int = 4096
    max_registry_bytes: int = 8 * 1024 * 1024

    def __post_init__(self):
        ceilings = (256, 64 * 1024, 16, 16, 256, 4 * 1024 * 1024,
                    8 * 1024 * 1024, 32 * 1024 * 1024, 16 * 1024 * 1024, 4096, 8 * 1024 * 1024)
        for name, ceiling in zip(self.__dataclass_fields__, ceilings):
            value = getattr(self, name)
            _require(type(value) is int and 0 < value <= ceiling, "invalid bounded " + name)

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class CodebaseInventoryScanRecord:
    artifact_cid: str
    _payload: bytes

    def __post_init__(self):
        _require(type(self._payload) is bytes, "immutable native scan bytes required")
        value = json.loads(self._payload)
        _require(_wire(value) == self._payload and cid_for_bytes(self._payload) == self.artifact_cid,
                 "scan raw CID identity differs")
        fields = {"schema", "profile", "codec", "head", "model", "membership", "entries", "shards",
                  "worker_receipt", "counters", "timings", "limits", "implementation", "authority"}
        _require(type(value) is dict and set(value) == fields and value["schema"] == SCHEMA
                 and value["profile"] == PROFILE and value["codec"] == "canonical-finite-native-json/raw-cidv1"
                 and type(value["authority"]) is dict and set(value["authority"]) == set(_FALSE)
                 and all(flag is False for flag in value["authority"].values()),
                 "closed nonauthoritative scan record required")
        entries = value["entries"]
        _require(type(entries) is list and len(entries) <= 256 and all(
            type(entry) is dict and entry.get("disposition") in _DISPOSITIONS for entry in entries),
            "closed inventory dispositions required")
        ordered = [{"source_key": row["source_key"], "entry_cid": row["entry_cid"]} for row in entries]
        _require(value["membership"] == {"cid": cid_for_structured(ordered), "ordered": ordered}
                 and len({row["source_key"] for row in entries}) == len(entries), "inventory membership differs")

    def to_dict(self):
        return json.loads(self._payload)


def _implementation():
    files = dict(training._pins()["files"])
    for name in (__name__, numerical.__name__, "ipfs_datasets_py.logic.software_contracts.codebase_inventory_targets",
                 "ipfs_datasets_py.logic.software_contracts.codebase_inventory_replay",
                 "ipfs_datasets_py.logic.software_contracts.codebase_inventory_lineage"):
        module = importlib.import_module(name)
        files[name] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    return {"files": files, "sha256": features.digest(files),
            "scope": "listed_local_files_only_not_execution_attestation"}


def _registry_inventory(registry, limits, checkpoint):
    """Bounded read of the closed owner namespace; no lock crosses execution."""
    result, count, byte_count = {}, 0, 0
    with registry._transaction() as connection:
        for table in _TABLES:
            checkpoint()
            cursor = connection.execute("SELECT * FROM autoencoder_control." + table + " ORDER BY ALL")
            rows = []
            while True:
                batch = cursor.fetchmany(32)
                if not batch:
                    break
                checkpoint()
                count += len(batch)
                _require(count <= limits.max_registry_rows, "registry namespace row bound exceeded")
                byte_count += len(_wire(batch))
                _require(byte_count <= limits.max_registry_bytes, "registry namespace byte bound exceeded")
                rows.extend(batch)
            result[table] = rows
    raw = _wire(result)
    _require(len(raw) <= limits.max_registry_bytes, "registry namespace byte bound exceeded")
    return raw


def _observe(index, repository, head, *, lease, signal, remaining, admission, memory_mb, target_limits):
    """Read complete CAS/index evidence and re-capture the exact live profile."""
    from .codebase_inventory_targets import seal_inventory, CodebaseInventoryLimits
    with acquire_codebase_resources(parent_lease=lease, cancel_event=signal,
            timeout_seconds=min(admission, remaining()), memory_mb=memory_mb):
        remaining()
        if index.current(head.repository_id) != head:
            raise StaleCodebaseError("inventory catalog head changed")
        seal = seal_inventory(index, expected_head=head, limits=target_limits,
            inventory_limits=CodebaseInventoryLimits(max_source_bytes=target_limits.max_source_bytes,
                                                      max_target_bytes=target_limits.max_target_bytes),
            checkpoint=remaining)
        captured = seal.manifest.snapshot
        CodebaseScanLimits(captured.max_entries, captured.max_file_bytes).validate_reservation(memory_mb)
        for member in seal.members:
            remaining()
            index.lookup(seal.manifest, member.entry.path)
        observed = snapshot_repository(repository, repository_id=head.repository_id,
            max_file_bytes=captured.max_file_bytes, max_entries=captured.max_entries,
            exclusions=captured.exclusions)
        remaining()
        if observed.snapshot_cid != captured.snapshot_cid or index.current(head.repository_id) != head:
            raise StaleCodebaseError("current repository differs from sealed inventory")
        return seal


def _history_heads(chain, binding=training._binding):
    """Include captured replay/evaluation heads, not just producer heads."""
    heads = {}
    for _, _, provenance, *batches in chain:
        values = [provenance["head"], *(binding(target)["head"] for batch in batches for target in batch)]
        for value in values:
            head = CodebaseHead.from_dict(value)
            heads[head.receipt_cid] = head
    return tuple(heads[key] for key in sorted(heads))


def _history_fence(index, heads, checkpoint, current_seal):
    """Recheck full immutable historical inventories and native receipts."""
    from .codebase_inventory_targets import seal_inventory
    result = []
    for head in heads:
        checkpoint()
        # The exact current head is verified by the operation's two complete
        # live observations.  Historical heads get independent bounded seals,
        # including parser-failure envelopes, without active-index claims.
        seal = current_seal if head == current_seal.head else seal_inventory(
            index, expected_head=head, checkpoint=checkpoint)
        result.append({"head": head.to_dict(), "receipt": seal.receipt.to_dict(), "manifest_cid": seal.manifest.cid})
    return _wire(result)


def _model_fence(registry, chain, checkpoint):
    for version_row, _, *_ in chain:
        checkpoint()
        _require(registry.get_version(version_row["version_id"]) == version_row, "model ancestry row changed")
        _require(registry.verify_artifact(version_row["artifact"]) == version_row["artifact"],
                 "model ancestry artifact changed")


def _worker(payload, *, lease, signal, remaining, memory_mb, limits):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLane
    raw = _wire(payload)
    _require(len(raw) <= limits.max_input_bytes, "inventory worker input byte bound exceeded")
    executable, script = Path(sys.executable).resolve(), Path(numerical.__file__).resolve()
    spec = importlib.util.find_spec("torch")
    _require(spec is not None and spec.origin is not None, "installed numerical dependency required")
    libraries = list(dict.fromkeys((str(Path(sysconfig.get_path("purelib")).resolve()),
                                   str(Path(spec.origin).resolve().parent.parent))))
    _require(all(Path(path).is_dir() for path in libraries), "installed numerical library directories required")
    executable_sha = hashlib.sha256(executable.read_bytes()).hexdigest()
    script_sha = hashlib.sha256(script.read_bytes()).hexdigest()
    runner = BoundedToolRunner(base_environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"})
    with lease.acquire_child(lane=ResourceLane.TRAINER, cpu_slots=1, memory_mb=memory_mb,
            child_process_slots=1, timeout=remaining(), cancel_event=signal,
            request_id="codebase-inventory:finite-inference") as child:
        child_payload = dict(payload)
        child_payload["max_seconds"] = min(payload["max_seconds"], remaining())
        raw = _wire(child_payload)
        _require(len(raw) <= limits.max_input_bytes, "inventory worker input byte bound exceeded")
        bounds = ToolRunLimits(timeout_seconds=remaining(), resident_memory_bytes=memory_mb * 1024 * 1024,
            max_output_bytes=limits.max_output_bytes, max_input_bytes=limits.max_input_bytes,
            max_workspace_bytes=limits.max_input_bytes + limits.max_output_bytes)
        process = run_bounded_stdin_tool([str(executable), "-I", "-B", str(script), json.dumps(libraries)], raw,
            runner=runner, limits=bounds, cancellation=child.combined_cancellation_signal(signal))
    remaining()
    _require(process.returncode == 0 and not any((process.timed_out, process.cancelled, process.unavailable,
        process.output_truncated, process.resource_exhausted)) and process.workspace_cleaned,
        "inventory numerical child failed: " + str(process.termination_reason or process.error or "execution error")
        + ": " + process.stderr[-2048:])
    _require(hashlib.sha256(executable.read_bytes()).hexdigest() == executable_sha
             and hashlib.sha256(script.read_bytes()).hexdigest() == script_sha, "numerical producer changed")
    response = json.loads(process.stdout, object_pairs_hook=numerical._json_pairs,
                          parse_constant=numerical._json_constant)
    _require(len(_wire(response)) <= limits.max_output_bytes, "inventory numerical response exceeds bound")
    receipt = {"executable_sha256": executable_sha, "worker_sha256": script_sha,
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "output_sha256": hashlib.sha256(process.stdout.encode("utf-8")).hexdigest(),
        "input_bytes": len(raw), "output_bytes": len(process.stdout.encode("utf-8")),
        "elapsed_ms": process.elapsed_ms, "returncode": process.returncode,
        "workspace_cleaned": process.workspace_cleaned,
        "limits": {"resident_memory_bytes": bounds.resident_memory_bytes,
                   "max_input_bytes": bounds.max_input_bytes, "max_output_bytes": bounds.max_output_bytes},
        "memory_enforcement": "sampled_process_tree_rss_with_possible_overshoot",
        "source_execution_attested": False}
    return response, receipt


def _accept_response(response, entries, shard_entries, saved, optimized):
    _require(type(response) is dict and set(response) == {"schema", "optimized", "shards", "metrics", "worker"}
             and response["schema"] == numerical.SCHEMA and response["optimized"] is optimized,
             "closed inventory numerical response required")
    worker = response["worker"]
    expected_worker = {"python", "torch", "device", "dtype", "cpu_threads", "repository_code_executed",
                       "registry_opened", "training_executed", "proof_authority", "decoded_formulas_generated"}
    _require(type(worker) is dict and set(worker) == expected_worker and worker["device"] == "cpu"
             and worker["dtype"] == "float64" and type(worker["cpu_threads"]) is int
             and worker["cpu_threads"] == 1 and all(worker[key] is False for key in
                 ("repository_code_executed", "registry_opened", "training_executed", "proof_authority",
                  "decoded_formulas_generated")), "numerical execution/authority profile differs")
    outputs = response["shards"]
    _require(type(outputs) is list and len(outputs) == len(shard_entries), "returned shard inventory differs")
    receipts = []
    space, state = saved["feature_space"], saved["state"]
    for index, (output, indices) in enumerate(zip(outputs, shard_entries)):
        _require(type(output) is dict and set(output) == {"shard_index", "inference"}
                 and type(output["shard_index"]) is int and output["shard_index"] == index,
                 "returned shard order differs")
        inference = output["inference"]
        expected = {"schema", "contract_sha256", "state_sha256", "feature_space_sha256", "rows", "coverage",
                    "training_executed", "decoded_formulas_generated", "representation", *features.FALSE}
        coverage = [row for entry_index in indices for row in entries[entry_index]["coverage"]]
        _require(type(inference) is dict and set(inference) == expected
            and inference["schema"] == "native-projection-feature-inference/v1"
            and inference["contract_sha256"] == state["contract_sha256"]
            and inference["state_sha256"] == features.digest(state)
            and inference["feature_space_sha256"] == features.digest(space)
            and inference["training_executed"] is False and inference["decoded_formulas_generated"] is False
            and all(inference[key] is False for key in features.FALSE)
            and _wire(inference["coverage"]) == _wire(coverage)
            and inference["representation"] == "native_compiler_structural_features_not_semantic_text_embeddings",
            "returned feature identities/coverage/authority differ")
        rows = inference["rows"]
        _require(type(rows) is list and len(rows) == len(indices), "returned row count differs")
        for row, entry_index in zip(rows, indices):
            entry = entries[entry_index]
            _require(type(row) is dict and set(row) == {"source_digest", "latent", "reconstructed_projection_features"}
                and row["source_digest"] == entry["source_digest"] and type(row["latent"]) is list
                and len(row["latent"]) == state["latent_width"]
                and type(row["reconstructed_projection_features"]) is dict
                and set(row["reconstructed_projection_features"]) == set(space["projection_ids"]),
                "returned feature row binding differs")
            numbers = list(row["latent"])
            for name in space["projection_ids"]:
                values = row["reconstructed_projection_features"][name]
                _require(type(values) is list and len(values) == sum(column[0] == name for column in space["columns"]),
                         "returned projection width differs")
                numbers.extend(values)
            _require(all(type(number) in (int, float) and math.isfinite(number) for number in numbers),
                     "returned numerical values must be finite")
            entry["inference"] = row
        receipts.append({"shard_index": index, "row_count": len(indices),
            "target_source_digests": [entries[i]["source_digest"] for i in indices],
            "inference_sha256": features.digest(inference)})
    metrics = response["metrics"]
    rows_count, shards_count = sum(map(len, shard_entries)), len(shard_entries)
    preparations = 1 if optimized else shards_count
    expected_counters = {"shared_inventory_validations": 1, "target_restorations": rows_count,
        "native_target_replays": rows_count, "matrix_builds": shards_count, "vocabulary_builds": preparations,
        "weight_tensor_builds": 4 * preparations, "input_tensor_builds": shards_count,
        "contract_validations": preparations, "state_validations": preparations,
        "rows": rows_count, "shards": shards_count}
    expected_counters.update({"replay_" + name: rows_count for name in (
        "target_replay_attempts", "target_replays", "source_digest_checks", "ast_digest_checks",
        "authored_contract_replays", "native_lowering_replays", "full_target_comparisons")})
    expected_counters.update(replay_shared_replay_preparations=int(optimized),
        replay_shared_manifest_parses_avoided=rows_count if optimized else 0,
        replay_shared_receipt_parses_avoided=rows_count if optimized else 0)
    _require(type(metrics) is dict and set(metrics) == {"counters", "stage_seconds", "elapsed_seconds", "time_scope"}
        and type(metrics["counters"]) is dict and all(type(value) is int and value >= 0 for value in metrics["counters"].values())
        and metrics["counters"] == expected_counters
        and metrics["time_scope"] == "execute_before_final_protocol_serialization_and_write"
        and type(metrics["stage_seconds"]) is dict and all(type(value) in (int, float) and math.isfinite(value)
            and value >= 0 for value in [metrics["elapsed_seconds"], *metrics["stage_seconds"].values()]),
        "returned numerical accounting differs")
    return receipts


def scan_current_codebase_features(index, repository, *, expected_head, registry, version_id,
        optimized=True, limits=None, scheduler=None, parent_lease=None, cancel_event=None,
        admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    """Scan every admitted member using one exact existing current-head model.

    ``optimized=False`` invokes unchanged native lineage/target replay and the
    v1 numerical routine per shard. Reuse belongs to this operation only.
    Dispositions cover the complete inventory; unsupported/OOV/budget entries
    never acquire training, held-out, semantic or proof labels.  Returned bytes
    are immutable but are not published into any CAS or mutable owner index.
    The deadline is cooperative around bounded native Git commands; memory is
    reserved and the child process tree is sampled, with possible overshoot.
    """
    from . import codebase_inventory_targets as transport
    from . import codebase_inventory_lineage as lineage
    from .codebase_ir_targets import CodebaseTargetLimits
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError

    training._native_owners(index, registry)
    _require(type(expected_head) is CodebaseHead and type(optimized) is bool, "exact head and boolean opt-out required")
    training._text(version_id, "version_id")
    limits = CodebaseInventoryScanLimits() if limits is None else limits
    _require(type(limits) is CodebaseInventoryScanLimits, "exact inventory limits required")
    _require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds) and 0 < timeout_seconds <= 600,
             "bounded finite scan deadline required")
    _require(type(admission_timeout_seconds) in (int, float) and math.isfinite(admission_timeout_seconds)
             and admission_timeout_seconds >= 0, "bounded finite admission timeout required")
    _require(type(memory_mb) is int and memory_mb >= 1024, "at least 1024 MB reserved for complete inventory scan")
    lineage_limits = training.CodebaseFeatureTrainingLimits()
    cache_ceiling = lineage_limits.max_ancestry_bytes + lineage_limits.max_target_bytes if optimized else 0
    worker_phase_ceiling = (lineage_limits.max_ancestry_bytes + 96 * 1024 * 1024 + limits.max_input_bytes
                            + limits.max_output_bytes + 2 * limits.max_registry_bytes + limits.max_target_bytes
                            + cache_ceiling)
    # Historical seals are released before allocating worker streams and the
    # final current seal. Account the two phases independently, in serialized
    # bytes; these bounds do not describe Python RSS containment.
    lineage_phase_ceiling = (lineage_limits.max_ancestry_bytes + 48 * 1024 * 1024
        + lineage.MAX_HISTORICAL_SEAL_BYTES + cache_ceiling + limits.max_registry_bytes + limits.max_target_bytes)
    retained_ceiling = max(worker_phase_ceiling, lineage_phase_ceiling if optimized else 0)
    _require(retained_ceiling <= memory_mb * 1024 * 1024 // 4, "scan retained byte bounds exceed reservation")
    target_limits = CodebaseTargetLimits(max_source_bytes=limits.max_file_bytes, max_target_bytes=limits.max_target_bytes)
    started = time.monotonic()
    deadline = started + timeout_seconds
    times = {}

    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=min(admission_timeout_seconds, timeout_seconds), memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)

        def remaining():
            if signal.is_set():
                raise LeaseCancelledError("inventory scan cancelled")
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise LeaseTimeoutError("inventory scan deadline exceeded")
            return seconds

        def timed(name, operation):
            before = time.monotonic()
            try:
                return operation()
            finally:
                times[name] = time.monotonic() - before

        remaining()
        implementation = _implementation()
        registry_before = timed("registry_entry", lambda: _registry_inventory(registry, limits, remaining))
        seal = timed("source_entry", lambda: _observe(index, repository, expected_head, lease=lease, signal=signal,
            remaining=remaining, admission=admission_timeout_seconds, memory_mb=memory_mb, target_limits=target_limits))
        captured = seal.manifest.snapshot
        _require(captured.max_entries <= limits.max_entries and captured.max_file_bytes <= limits.max_file_bytes
                 and len(seal.members) <= limits.max_entries, "captured inventory exceeds scan profile")
        lineage_context = None
        if optimized:
            replay = timed("lineage_replay", lambda: lineage.replay_inventory_lineage(
                index, registry, version_id, lineage_limits, current_seal=seal, checkpoint=remaining))
            chain, lineage_context = replay.chain, replay.context
        else:
            chain = timed("lineage_replay", lambda: training._lineage(index, registry, version_id, lineage_limits))
        remaining()
        row, saved, provenance = chain[0][:3]
        _require(provenance["head"] == expected_head.to_dict(), "selected model is not bound to the exact current head")
        heads = _history_heads(chain, binding=lineage_context.binding) if lineage_context else _history_heads(chain)
        if lineage_context:
            lineage_context.release_historical_seals()
        history_before = timed("historical_entry", lambda: _history_fence(index, heads, remaining, seal))
        selected = {item.path: item for item in (training.CodebaseTrainingSelection.from_dict(value)
                                                for value in provenance["selections"])}
        vocabulary = numerical.prepare_inventory_vocabulary(saved["feature_space"])
        shared = transport.shared_inventory_envelope(seal)
        shared_token = transport.validate_shared_inventory_envelope(shared)
        payload = {"schema": numerical.SCHEMA, "optimized": optimized, "contract": saved["contract"],
            "feature_space": saved["feature_space"], "state": saved["state"], "shared_inventory": shared,
            "shards": [], "max_seconds": 600.0, "limits": {
                "max_shards": limits.max_shards, "max_rows_per_shard": limits.max_rows_per_shard,
                "max_target_bytes": limits.max_target_bytes, "max_input_bytes": limits.max_input_bytes,
                "max_output_bytes": limits.max_output_bytes}}
        # Reserve extra bytes for the actual remaining-time float's encoding.
        request_base_bytes = len(_wire(payload)) + 64
        entries, shards, shard_entries = [], [], []
        pending, pending_indices, pending_bytes = [], [], 0
        retained_shard_bytes = 0
        inferred = 0
        preparation_start = time.monotonic()

        def flush():
            nonlocal pending, pending_indices, pending_bytes, retained_shard_bytes
            if pending:
                shard = {"shard_index": len(shards), "targets": pending}
                exact_bytes = len(_wire(shard))
                _require(exact_bytes == pending_bytes and exact_bytes <= limits.max_shard_bytes,
                         "compact shard serialized byte bound differs")
                shards.append(shard)
                shard_entries.append(pending_indices)
                retained_shard_bytes += exact_bytes
                pending, pending_indices, pending_bytes = [], [], 0

        for member in seal.members:
            remaining()
            entry, unit = member.entry, member.unit
            selection = selected.get(entry.path)
            result = {"path": entry.path, "source_key": entry.source_key,
                "raw_path_hex": entry.raw_path_hex, "source_size_bytes": entry.size_bytes,
                "source_sha256": None if member.raw is None else hashlib.sha256(member.raw).hexdigest(),
                "captured_source_available": member.raw is not None,
                "entry_cid": entry.entry_cid, "source_cid": entry.source_cid,
                "ast_cid": unit.ast_cid, "parse_status": unit.parse_status, "disposition": member.disposition,
                "frontiers": [dict(frontier) for frontier in member.frontiers],
                "cohort_membership": selection.role if selection else "not_in_registered_cohort",
                "authored_contracts_origin": "registered_selection" if selection else "none_declared",
                "target_sha256": None, "source_digest": None, "coverage": [], "shard_index": None, "inference": None}
            if member.disposition == "unsupported_extension":
                result["disposition"] = "unsupported_target"
            if member.disposition == "captured_python":
                if lineage_context and selection and target_limits == CodebaseTargetLimits():
                    # Registered selections already passed inherited native
                    # replay. Other members retain bounded frontier handling.
                    target = lineage_context.prepare(expected_head, selection.path, selection.contracts)
                    frontier = None
                else:
                    target, frontier = transport.prepare_inventory_target_or_frontier(seal, entry.source_key,
                        contracts=selection.contracts if selection else ())
                if frontier is not None:
                    result["disposition"] = frontier["disposition"]
                    result["frontiers"].extend(frontier["frontiers"])
                    entries.append(result)
                    continue
                value = target.to_dict()
                result["target_sha256"] = hashlib.sha256(target.canonical_bytes).hexdigest()
                result["source_digest"] = target.source_digest
                if not target.ready_for_training:
                    result["disposition"] = "unsupported_target"
                    result["frontiers"].extend(value["unsupported"])
                else:
                    coverage = numerical.inventory_target_coverage(vocabulary, target)
                    result["coverage"] = coverage["coverage"]
                    if not coverage["compatible"]:
                        result["disposition"] = "feature_incompatible"
                        result["frontiers"].append({"reason": "zero_coverage_in_frozen_projection_basis"})
                    elif inferred >= min(limits.max_inferred_rows, limits.max_shards * limits.max_rows_per_shard):
                        result["disposition"] = "deferred_budget"
                        result["frontiers"].append({"reason": "explicit_inferred_row_budget"})
                    else:
                        compact = transport.compact_inventory_target(target, shared_token, counters=seal.counters)
                        compact_bytes = len(_wire(compact))
                        candidate_bytes = (pending_bytes + compact_bytes + 1 if pending else
                            len(_wire({"shard_index": len(shards), "targets": []})) + compact_bytes)
                        if pending and (len(pending) >= limits.max_rows_per_shard
                                        or candidate_bytes > limits.max_shard_bytes):
                            flush()
                            candidate_bytes = len(_wire({"shard_index": len(shards), "targets": []})) + compact_bytes
                        if candidate_bytes > limits.max_shard_bytes or len(shards) >= limits.max_shards:
                            result["disposition"] = "deferred_budget"
                            result["frontiers"].append({"reason": "explicit_shard_byte_budget"})
                        elif request_base_bytes + retained_shard_bytes + candidate_bytes + len(shards) > limits.max_input_bytes:
                            result["disposition"] = "deferred_budget"
                            result["frontiers"].append({"reason": "explicit_worker_input_byte_budget"})
                        else:
                            result["disposition"] = "inferred"
                            result["shard_index"] = len(shards)
                            pending.append(compact)
                            pending_indices.append(len(entries))
                            pending_bytes = candidate_bytes
                            inferred += 1
            _require(result["disposition"] in _DISPOSITIONS, "unclosed native inventory disposition")
            entries.append(result)
        flush()
        times["target_preparation"] = time.monotonic() - preparation_start
        membership = [{"source_key": result["source_key"], "entry_cid": result["entry_cid"]} for result in entries]
        response = receipt = None
        shard_receipts = []
        if shards:
            payload["shards"] = shards
            payload["max_seconds"] = min(600.0, remaining())
            response, receipt = timed("numerical_process", lambda: _worker(payload, lease=lease, signal=signal,
                remaining=remaining, memory_mb=memory_mb, limits=limits))
            shard_receipts = _accept_response(response, entries, shard_entries, saved, optimized)
        remaining()
        history_final = timed("historical_final", lambda: _history_fence(index, heads, remaining, seal))
        _require(history_final == history_before, "historical captured evidence changed")
        before = time.monotonic()
        _model_fence(registry, chain, remaining)
        _require(_registry_inventory(registry, limits, remaining) == registry_before, "model owner state changed during scan")
        _require(_implementation() == implementation, "scan/checkpoint producer changed during operation")
        times["model_final"] = time.monotonic() - before
        final_seal = timed("source_final", lambda: _observe(index, repository, expected_head, lease=lease, signal=signal,
            remaining=remaining, admission=admission_timeout_seconds, memory_mb=memory_mb, target_limits=target_limits))
        _require(final_seal.manifest.to_dict() == seal.manifest.to_dict()
                 and final_seal.receipt.to_dict() == seal.receipt.to_dict(), "sealed source/publication changed")
        timed("model_closing", lambda: _model_fence(registry, chain, remaining))
        _require(_registry_inventory(registry, limits, remaining) == registry_before, "model owner state changed during scan")
        _require(_implementation() == implementation, "scan/checkpoint producer changed during operation")
        remaining()
        times["elapsed_seconds_before_record_serialization"] = time.monotonic() - started
        counters = {"source_observations": 2, "lineage_replays": 1, "model_versions": len(chain),
            "inventory_entries": len(entries), "inferred_rows": inferred, "shards": len(shards),
            "numerical_process_starts": int(bool(shards)), "training_calls": 0,
            "dispositions": dict(sorted(Counter(entry["disposition"] for entry in entries).items())),
            "entry_seal": seal.counters.to_dict(), "final_seal": final_seal.counters.to_dict(),
            "lineage": lineage_context.counters.to_dict() if lineage_context else {},
            "worker": response["metrics"]["counters"] if response else {}}
        model = {"version_id": version_id, "variant_id": row["variant_id"], "artifact": row["artifact"],
            "artifact_cid": cid_for_bytes(training._wire(saved)), "contract_sha256": saved["state"]["contract_sha256"],
            "state_sha256": features.digest(saved["state"]), "feature_space_sha256": features.digest(saved["feature_space"]),
            "runtime_version": training.runtimes.CODEBASE_SOURCE_FEATURE_VERSION, "optimized": optimized,
            "basis_policy": "unchanged_registered_vocabulary", "dtype": "float64", "device": "cpu"}
        value = {"schema": SCHEMA, "profile": PROFILE, "codec": "canonical-finite-native-json/raw-cidv1",
            "head": expected_head.to_dict(), "model": model,
            "membership": {"cid": cid_for_structured(membership), "ordered": membership}, "entries": entries,
            "shards": shard_receipts, "worker_receipt": receipt, "counters": counters,
            "timings": {"coordinator": times, "worker": response["metrics"] if response else None,
                        "scope": "admission_through_final_fences_before_record_serialization"},
            "limits": limits.to_dict(), "implementation": implementation, "authority": _FALSE}
        raw = _wire(value)
        _require(len(raw) <= limits.max_output_bytes, "complete scan record exceeds output bound")
        remaining()
        return CodebaseInventoryScanRecord(cid_for_bytes(raw), raw)


__all__ = ["SCHEMA", "PROFILE", "CodebaseInventoryScanError", "CodebaseInventoryScanLimits",
           "CodebaseInventoryScanRecord", "scan_current_codebase_features"]

"""Opt-in, source-bound 384D repository adaptation using the shared decoder.

The envelope is CodebaseIR; its numerical payload remains the unchanged
SecurityIR structured decoder. This deliberately narrow profile handles one
annotated two-operand Python function per selected file. It refits a frozen
vocabulary ridge head, not a language model or an optimizer continuation.
Neither a fitted model nor a source-aligned prediction is a proof.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import time
import uuid

from .codebase_ir import RepositoryCodebaseIndex
from .codebase_resources import acquire_codebase_resources

PROFILE = "codebase_ir/source_conditioned_384_v1"
SCHEMA = "codebase-source-384-generation@1"
CORPUS_SCHEMA = "codebase-source-384-corpus@1"
MAX_BYTES = 32 * 1024 * 1024
FALSE = dict(proof_authority=False, admitted=False, promotion_performed=False,
             source_runtime_semantics_verified=False, behavioral_satisfaction=False)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _stage(registry, value):
    """Stage canonical JSON without importing training or proof-workspace owners."""
    with tempfile.TemporaryDirectory(prefix="codebase-generation-") as directory:
        path = Path(directory) / "artifact.json"
        path.write_bytes(_raw(value))
        return registry.stage_artifact(path)


def _pins():
    from ..formalization.autoencoder import structured_source_384 as decoder
    from ..formalization.autoencoder import source_embeddings_384 as embedding
    from ..formalization.autoencoder import source_program_runtime_384_v2 as compatibility
    from ..formalization.autoencoder.security import source_program_binding_384 as binding
    from ..formalization.autoencoder.security import source_program_binding_384_v2 as effects
    from ..formalization.autoencoder.distributed_384 import numerics
    from . import codebase_source_384_worker as worker
    from ..backends import codebase_process
    return {"files": {m.__name__: _sha(Path(m.__file__).read_bytes())
        for m in (sys.modules[__name__], worker, embedding, binding, effects, compatibility, codebase_process)},
        "decoder": decoder._implementation(), "numerics": numerics._producer()}


def _target(source):
    """Independent deterministic label generation; never used to fix inference."""
    from ..formalization.autoencoder.security import source_program_binding_384 as binding
    from ..formalization.autoencoder.security import source_program_binding_384_v2 as effects
    from ..software_verification.program import ProgramExpression
    guarded = binding._guard(source)
    _, _, operands, _, operator, _, sort = guarded
    ids = tuple("expr:" + operand.id for operand in operands)
    target = {"kind": "program_expression", "document": ProgramExpression(
        "expr:result", "binary", sort, operand_ids=ids, evaluation_order=ids,
        operator=operator, source_ref_ids=("source",)).to_dict()}
    checked = effects.qualify_source_candidate(source, target)
    _require(checked["status"] == "qualified", "source target is outside the reviewed scalar profile")
    return target


def _clone(source):
    # Type-1 clones plus function-name variants. Parameter alpha-equivalence is
    # not claimed: parameters remain semantic decoder output slots here.
    tree = ast.parse(source)
    tree.body[0].name = "function"
    return _sha(ast.dump(tree, include_attributes=False).encode())


def prepare_corpus(index, *, expected_head, selections):
    """Read enumerated immutable source bytes; do not execute target code.

    Selections are closed path/role/group_id dictionaries. Caller groups are
    indivisible and augmented by exact-source and AST clone exclusion. This is
    a historical preparation API; training separately requires live observation.
    """
    _require(type(index) is RepositoryCodebaseIndex and index.catalog is not None,
             "native durable source owner required")
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    _require(type(expected_head) is CodebaseHead, "native exact source head required")
    _require(type(selections) in (list, tuple) and 3 <= len(selections) <= 128,
             "three to 128 explicit source selections required")
    manifest = index.load(expected_head.manifest_cid)
    _require(manifest.snapshot.snapshot_cid == expected_head.snapshot_cid
        and manifest.ast_revision_id == expected_head.ast_revision_id
        and manifest.snapshot.repository_id == expected_head.repository_id, "source head differs")
    rows, seen, roles = [], set(), {}
    for selection in selections:
        _require(type(selection) is dict and set(selection) == {"path", "role", "group_id"},
                 "closed source selection required")
        path, role, group = (selection[k] for k in ("path", "role", "group_id"))
        _require(type(path) is str and len(path) <= 1024 and path not in seen
            and PurePosixPath(path).as_posix() == path and not PurePosixPath(path).is_absolute()
            and ".." not in PurePosixPath(path).parts and path.endswith(".py"), "unique canonical Python path required")
        _require(role in ("train", "validation", "holdout") and type(group) is str
            and 0 < len(group) <= 256 and group.strip() == group, "explicit split and group required")
        seen.add(path)
        entry = next((x for x in manifest.snapshot.entries if x.path == path), None)
        _require(entry is not None and entry.source_cid is not None, "selected source is not captured")
        blob = index.artifacts.get_bytes(entry.source_cid)
        _require(0 < len(blob) <= 65536, "bounded complete source unit required")
        source = blob.decode("utf-8")
        target = _target(source)
        row = dict(id=_sha(path.encode()), path=path, role=role, group_id=group,
            source_cid=entry.source_cid, source_sha256=_sha(blob), source_text=source,
            clone_sha256=_clone(source), target=target, target_sha256=_sha(_raw(target)))
        for key in ("source_sha256", "clone_sha256", "group_id"):
            previous = roles.setdefault((key, row[key]), role)
            _require(previous == role, "source/clone/group crosses corpus splits")
        rows.append(row)
    _require({r["role"] for r in rows} == {"train", "validation", "holdout"}, "all three split roles required")
    return dict(schema=CORPUS_SCHEMA, profile=PROFILE, head=expected_head.to_dict(),
        selections=sorted(deepcopy(list(selections)), key=lambda x: x["path"]),
        rows=sorted(rows, key=lambda x: x["path"]), inventory_coverage=manifest.coverage,
        selection_coverage={r: sum(x["role"] == r for x in rows) for r in ("train", "validation", "holdout")},
        labels="independent_reviewed_source_AST_and_native_ProgramIR_alignment",
        clone_policy="AST_without_locations_and_function_name; parameter_alpha_clones_not_detected",
        holdout_used_for_selection=False, desired_intent_used_as_label=False, **FALSE)


def _validate_corpus(index, value):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    _require(type(value) is dict and value.get("schema") == CORPUS_SCHEMA, "source corpus required")
    head = CodebaseHead.from_dict(value["head"])
    expected = prepare_corpus(index, expected_head=head, selections=value["selections"])
    _require(_raw(expected) == _raw(value), "captured corpus replay differs")
    return head


def _read_generation(registry, version_id):
    version = registry.get_version(version_id)
    blob = registry.read_artifact(version["artifact"], max_bytes=MAX_BYTES)
    value = json.loads(blob)
    _require(value.get("schema") == SCHEMA and value.get("profile") == PROFILE
        and value.get("producer") == _pins() and value.get("authority") == FALSE,
        "model generation profile/producer/authority differs")
    return version, value


def _root_view(saved):
    from ..formalization.autoencoder import source_program_runtime_384_v2 as compatibility
    from ..formalization.autoencoder import structured_source_384 as decoder
    expected_fields = {"schema", "profile", "kind", "producer", "parent_version_id", "checkpoint",
        "compatibility", "original_checkpoint_sha256", "original_checkpoint_utf8", "authority"}
    _require(set(saved) == expected_fields and saved["kind"] == "shared_parent"
        and saved["parent_version_id"] is None, "closed shared parent envelope required")
    blob = saved["original_checkpoint_utf8"].encode("utf-8")
    _require(_sha(blob) == saved["original_checkpoint_sha256"]
        and _raw(json.loads(blob)) == _raw(saved["checkpoint"]), "original parent artifact bytes differ")
    original = saved["checkpoint"]
    view = deepcopy(original)
    view["implementation"] = decoder._implementation()
    compatibility._delta(original["implementation"], view["implementation"])
    expected = compatibility._receipt(original, view, saved["original_checkpoint_sha256"])
    _require(_raw(expected) == _raw(saved["compatibility"]), "shared parent compatibility receipt differs")
    decoder.Runtime(view)
    return view


def _checkpoint_corpus(saved):
    from ..formalization.autoencoder import structured_source_384 as decoder
    fields = {"id", "source_sha256", "normalized_source_sha256", "target_sha256"}
    for role, name in (("train", "training_manifest"), ("validation", "validation_manifest")):
        expected = [dict(id=row["id"], source_sha256=row["source_sha256"],
            normalized_source_sha256=_sha(" ".join(row["source_text"].casefold().split()).encode()),
            target_sha256=decoder.digest(row["target"])) for row in saved["corpus"]["rows"] if row["role"] == role]
        actual = [{key: row[key] for key in fields} for row in saved["checkpoint"][name]]
        # Numerical workers group training shards by stable group ID; source
        # ownership is an exact population join, independent of shard order.
        _require(sorted(actual, key=lambda r: r["id"]) == sorted(expected, key=lambda r: r["id"]),
                 "checkpoint source/target manifest differs from captured corpus")
    _require(saved["fit"]["plan_id"] == saved["checkpoint"]["training"]["plan_id"],
             "fit report and numerical plan differ")


def _lineage(index, registry, version_id):
    seen, chain = set(), []
    while version_id is not None:
        _require(version_id not in seen and len(chain) < 8, "bounded acyclic model ancestry required")
        seen.add(version_id)
        version, saved = _read_generation(registry, version_id)
        _require(saved["parent_version_id"] == version["parent_version_id"], "model ancestry differs")
        if saved["kind"] == "repository_child":
            _require(set(saved) == {"schema", "profile", "kind", "producer", "parent_version_id", "corpus", "request",
                "checkpoint", "evaluation", "fit", "embedding_assets", "worker_receipt", "authority"},
                "closed child generation required")
            _validate_corpus(index, saved["corpus"])
            request = saved["request"]
            _require(set(request) == {"profile", "corpus_sha256", "producer", "parent_version_id", "embedding_snapshot"}
                and request["profile"] == PROFILE and request["producer"] == saved["producer"]
                and request["parent_version_id"] == version["parent_version_id"]
                and request["corpus_sha256"] == _sha(_raw(saved["corpus"])), "child request binding differs")
            from ..formalization.autoencoder.structured_source_384 import Runtime
            Runtime(saved["checkpoint"])
            _checkpoint_corpus(saved)
        else:
            _root_view(saved)
        chain.append((version, saved))
        version_id = version["parent_version_id"]
    _require(chain[-1][1]["kind"] == "shared_parent", "shared parent lineage required")
    for position, ((version, child), (parent_version, parent)) in enumerate(zip(chain, chain[1:])):
        checkpoint = _root_view(parent) if parent["kind"] == "shared_parent" else parent["checkpoint"]
        _require(version["variant_id"] == parent_version["variant_id"]
            and child["checkpoint"]["domain_id"] == checkpoint["domain_id"] == "security_ir"
            and child["checkpoint"]["projection_state"] == checkpoint["projection_state"]
            and child["checkpoint"]["target_schema"] == checkpoint["target_schema"]
            and child["checkpoint"]["training"]["base_checkpoint_sha256"] == _sha(_raw(checkpoint)),
            "child numerical parent/projection/vocabulary differs")
        _check_successor(child["corpus"], chain[position + 1:])
    return chain


def _check_successor(corpus, chain):
    children = [saved for _, saved in chain if saved["kind"] == "repository_child"]
    if not children:
        return
    root = children[-1]["corpus"]
    _require(corpus["selections"] == root["selections"]
        and corpus["head"]["repository_id"] == root["head"]["repository_id"], "ancestral source cohort changed")
    fixed = lambda c: [(r["path"], r["role"], r["source_sha256"], r["target_sha256"])
        for r in c["rows"] if r["role"] != "train"]
    _require(fixed(corpus) == fixed(root), "fixed tuning/holdout cohort changed; fork the lineage")
    historical = {r[k] for child in children for r in child["corpus"]["rows"]
        if r["role"] == "train" for k in ("source_sha256", "clone_sha256")}
    _require(not historical & {r[k] for r in corpus["rows"] if r["role"] != "train"
        for k in ("source_sha256", "clone_sha256")}, "ancestral training leaked into evaluation")


def register_shared_parent(registry, *, checkpoint_path, expected_sha256):
    """Register exact shared weights without altering them or selecting a head."""
    from ..formalization.autoencoder.source_program_runtime_384_v2 import _read_view
    from ..formalization.autoencoder.structured_source_384 import Runtime
    _, blob, view, receipt = _read_view(checkpoint_path, expected_sha256)
    Runtime(view)
    value = dict(schema=SCHEMA, profile=PROFILE, kind="shared_parent", producer=_pins(),
        parent_version_id=None, checkpoint=json.loads(blob), compatibility=receipt,
        original_checkpoint_sha256=expected_sha256, original_checkpoint_utf8=blob.decode("utf-8"), authority=dict(FALSE))
    variant = "codebase-source384:" + _sha(_raw({"profile": PROFILE, "parent": expected_sha256, "producer": _pins()}))
    registry.register_variant("variant:" + variant, variant,
        {"profile": PROFILE, "input_dimension": 384, "payload_domain": "security_ir",
         "objective": "source_conditioned_fixed_schema_head_refit", "parent_sha256": expected_sha256})
    with tempfile.TemporaryDirectory(prefix="codebase384-parent-") as directory:
        path = Path(directory) / "parent.json"
        path.write_bytes(_raw(value))
        artifact = registry.stage_artifact(path)
    return registry.register_version("parent:" + variant, variant, artifact,
        metadata={"profile": PROFILE, "authority": dict(FALSE)})["version_id"]


def _worker(payload, *, lease, signal, timeout, memory_mb):
    from . import codebase_source_384_worker as module
    from ..backends.codebase_process import BoundedToolRunner, ToolRunLimits, run_bounded_stdin_tool
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLane
    import site
    paths = list(dict.fromkeys([str(Path(__file__).resolve().parents[3]), *site.getsitepackages(), site.getusersitepackages()]))
    runner = BoundedToolRunner(base_environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8", "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", "TOKENIZERS_PARALLELISM": "false"})
    deadline = time.monotonic() + timeout
    with lease.acquire_child(lane=ResourceLane.TRAINER, cpu_slots=1, memory_mb=memory_mb,
            child_process_slots=1, timeout=timeout, cancel_event=signal,
            request_id="codebase-source384:" + payload["action"]) as child:
        remaining = deadline - time.monotonic()
        _require(remaining > 0 and not signal.is_set(), "worker admission consumed deadline or was cancelled")
        limits = ToolRunLimits(timeout_seconds=remaining, resident_memory_bytes=memory_mb * 1024 * 1024,
            max_input_bytes=MAX_BYTES, max_output_bytes=MAX_BYTES, max_workspace_bytes=2 * MAX_BYTES)
        result = run_bounded_stdin_tool([sys.executable, "-I", "-B", str(Path(module.__file__).resolve()), json.dumps(paths)],
            _raw(payload), runner=runner, limits=limits, cancellation=child.combined_cancellation_signal(signal))
    _require(result.returncode == 0 and result.workspace_cleaned and not any((result.timed_out,
        result.cancelled, result.unavailable, result.output_truncated, result.resource_exhausted)),
        "bounded source384 worker failed: " + str(result.termination_reason) + ": " + result.stderr[-2048:])
    return json.loads(result.stdout), dict(elapsed_ms=result.elapsed_ms, returncode=result.returncode,
        workspace_cleaned=result.workspace_cleaned, input_sha256=_sha(_raw(payload)),
        output_sha256=_sha(result.stdout.encode()), memory_mb=memory_mb,
        memory_enforcement="sampled_process_tree_RSS_may_overshoot", device="cpu", provider_calls=0)


def _limits(timeout_seconds, memory_mb, operation_id):
    _require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
        and 0 < timeout_seconds <= 600, "bounded positive deadline required")
    _require(type(memory_mb) is int and 1024 <= memory_mb <= 16384, "bounded numerical memory reservation required")
    _require(type(operation_id) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", operation_id),
             "bounded operation ID required")


def _owners(index, registry):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    _require(type(index) is RepositoryCodebaseIndex and index.catalog is not None
        and type(registry) is AutoencoderRegistry, "native source and model owners required")
    registry._ensure_owner()
    databases = index.catalog.store._connection.execute("PRAGMA database_list").fetchall()
    _require(not any(row[2] and Path(row[2]).resolve() == registry.database_path for row in databases),
             "separate source and model database ownership required")


def train_current_source384(index, repository, *, expected_head, registry, parent_version_id,
        selections, operation_id, embedding_snapshot, scheduler=None, parent_lease=None,
        cancel_event=None, timeout_seconds=180.0, memory_mb=2048):
    """Explicit bounded immutable child fit; never train during load or admission.

    Every round refits the complete selected training corpus. Frozen validation
    chooses regularization; the holdout is measured only after fitting. The
    registry's native run lease fences stale completions. Promotion remains a
    separate qualified owner policy, and source/model owners are not one SQL
    transaction.
    """
    _limits(timeout_seconds, memory_mb, operation_id)
    _owners(index, registry)
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, timeout_seconds=min(30., timeout_seconds), memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def remaining():
            _require(not signal.is_set() and time.monotonic() < deadline, "training cancelled or deadline expired")
            return deadline - time.monotonic()
        def observe():
            index.observe_current(repository, expected_head=expected_head, parent_lease=lease,
                cancel_event=signal, timeout_seconds=remaining(), memory_mb=memory_mb)
        observe()
        corpus = prepare_corpus(index, expected_head=expected_head, selections=selections)
        chain = _lineage(index, registry, parent_version_id)
        _require(len(chain) < 8, "prospective child exceeds ancestry bound")
        _check_successor(corpus, chain)
        parent, saved = chain[0]
        pins = _pins()
        request = dict(profile=PROFILE, corpus_sha256=_sha(_raw(corpus)), producer=pins,
            parent_version_id=parent_version_id, embedding_snapshot=str(Path(embedding_snapshot).resolve()))
        run = "source384:" + operation_id
        registry.create_run("create:" + run, run, parent["variant_id"], parent_version_id, request)
        previous = registry.get_run_completion(run)
        if previous is not None:
            loaded = _lineage(index, registry, previous["candidate_version"]["version_id"])[0]
            _require(loaded[1]["request"] == request, "completed request differs")
            observe()
            return {"version_id": loaded[0]["version_id"], "replayed": True, "training_executed": False, **FALSE}
        token = uuid.uuid4().hex
        claim = registry.claim_run("claim:" + token, run, "source384:" + token,
                                   lease_seconds=remaining() + 10.)["lease"]
        try:
            payload = dict(action="train", parent=saved, corpus=corpus,
                           embedding_snapshot=request["embedding_snapshot"], producer=pins)
            result, receipt = _worker(payload, lease=lease, signal=signal, timeout=remaining(), memory_mb=memory_mb)
            _require(result["producer"] == pins == _pins() and result["corpus_sha256"] == request["corpus_sha256"],
                     "training source/producer changed")
            observe()
            generation = dict(schema=SCHEMA, profile=PROFILE, kind="repository_child", producer=pins,
                parent_version_id=parent_version_id, corpus=corpus, request=request,
                checkpoint=result["checkpoint"], evaluation=result["evaluation"], fit=result["fit"],
                embedding_assets=result["embedding_assets"], worker_receipt=receipt, authority=dict(FALSE))
            from ..formalization.autoencoder.structured_source_384 import Runtime
            Runtime(generation["checkpoint"])
            with tempfile.TemporaryDirectory(prefix="codebase384-child-") as directory:
                path = Path(directory) / "child.json"
                path.write_bytes(_raw(generation))
                _require(path.stat().st_size <= MAX_BYTES, "candidate exceeds checkpoint byte budget")
                artifact = registry.stage_artifact(path)
            observe()
            completion = registry.complete_run("complete:" + run, claim, artifact,
                {"admitted": False, "profile": PROFILE, "source_head": expected_head.to_dict(),
                 "request_sha256": _sha(_raw(request)), "promotion_performed": False})
            return {**completion, "replayed": False, "training_executed": True,
                "evaluation": result["evaluation"], "worker_receipt": receipt, **FALSE}
        except BaseException as error:
            # Never let a failure acquire fresh authority. Lease loss may make
            # even recording failure unavailable; keep the original exception.
            try:
                registry.fail_run("fail:" + token, claim, {"admitted": False, "reason": type(error).__name__})
            except Exception:
                pass
            raise


def infer_current_source384(index, repository, *, expected_head, registry, version_id,
        paths, embedding_snapshot, scheduler=None, parent_lease=None, cancel_event=None,
        timeout_seconds=120., memory_mb=2048, weight_ablation=None):
    """Actual target-free inference on captured source, with independent alignment."""
    _limits(timeout_seconds, memory_mb, "inference")
    _owners(index, registry)
    _require(weight_ablation in (None, "zero_head", "zero_projection", "shuffle_embeddings"), "unknown model control")
    started = time.monotonic()
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, timeout_seconds=min(30., timeout_seconds), memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def observe():
            _require(not signal.is_set() and time.monotonic() - started < timeout_seconds, "inference cancelled/expired")
            index.observe_current(repository, expected_head=expected_head, parent_lease=lease,
                cancel_event=signal, timeout_seconds=timeout_seconds - (time.monotonic() - started), memory_mb=memory_mb)
        observe()
        _, saved = _lineage(index, registry, version_id)[0]
        _require(saved["kind"] == "repository_child" and saved["corpus"]["head"] == expected_head.to_dict(),
                 "model belongs to another source generation")
        _require(type(paths) in (list, tuple) and 1 <= len(paths) <= 128
            and all(type(p) is str for p in paths) and len(set(paths)) == len(paths), "distinct bounded paths required")
        by_path = {r["path"]: r for r in saved["corpus"]["rows"]}
        _require(set(paths) <= set(by_path), "inference outside registered cohort")
        rows = [{k: by_path[p][k] for k in ("id", "source_text")} for p in paths]
        result, receipt = _worker(dict(action="infer", checkpoint=saved["checkpoint"], rows=rows,
            producer=saved["producer"], weight_ablation=weight_ablation,
            embedding_snapshot=str(Path(embedding_snapshot).resolve())), lease=lease, signal=signal,
            timeout=timeout_seconds - (time.monotonic() - started), memory_mb=memory_mb)
        observe()
        _require(result["producer"] == saved["producer"] == _pins()
            and result["training_executed"] is False and result["embedding_assets"] == saved["embedding_assets"],
            "inference producer, embedding assets or mode changed")
        return dict(profile=PROFILE, source_head=expected_head.to_dict(), version_id=version_id,
            inference=result["inference"], worker_receipt=receipt, training_executed=False, **FALSE)

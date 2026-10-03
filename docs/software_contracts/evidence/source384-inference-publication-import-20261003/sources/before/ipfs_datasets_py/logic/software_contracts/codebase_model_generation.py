"""Versioned adaptation envelope over existing source384 and registry owners.

The numerical child remains readable by the original inference owner. This
separate immutable envelope binds the stricter pre-fit cohort and launch
environment. Candidate attachment never moves a registry head. Promotion uses
the existing independently validated native compare-and-swap operation.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import tempfile
import time

from . import codebase_source_384 as source384
from . import codebase_training_corpus as corpus_owner

SCHEMA = "codebase-model-generation@1"
_require, _raw, _sha = source384._require, source384._raw, source384._sha
FALSE = dict(source384.FALSE, quality_improvement_claimed=False, model_head_advanced=False)
RANDOMNESS = dict(seed=None, policy="no_random_parameters_or_stochastic_training",
    parent_projection_frozen=True, algorithm="global-centered-ridge-sufficient-statistics/v1")
OBJECTIVES = dict(trained=["source_to_fixed_typed_program_expression"],
    auxiliary_retained=["syntax", "finite_checked_property"],
    auxiliary_objectives_used_to_update_weights=False,
    semantic_definitions_and_checker_owners_outside_latent_space=True)


def _pins():
    return dict(generation_owner=_sha(Path(__file__).read_bytes()),
                corpus_owner=corpus_owner._pins(), numerical_owner=source384._pins())


def _environment():
    """Bind the frozen worker launch and installed numerical metadata.

The isolated worker uses this exact interpreter and the owner's fixed CPU
environment. This is not a complete OS/container or wheel-file closure.
"""
    import numpy as np
    from numpy.linalg import _umath_linalg
    packages = {}
    for name in ("numpy", "torch", "transformers", "sentence-transformers", "threadpoolctl"):
        distribution = importlib.metadata.distribution(name)
        record = distribution.read_text("RECORD")
        packages[name] = dict(version=distribution.version,
            installed_record_sha256=_sha(record.encode()) if record is not None else None)
    binary = Path(sys.executable).resolve()
    native = Path(_umath_linalg.__file__).resolve()
    return dict(python=dict(version=sys.version, implementation=platform.python_implementation(),
        executable=str(binary), executable_sha256=_sha(binary.read_bytes())),
        platform=dict(system=platform.system(), machine=platform.machine(), release=platform.release()),
        numerical=dict(dtype="float64", numpy_version=np.__version__, linalg_binary=str(native),
            linalg_binary_sha256=_sha(native.read_bytes())), distributions=packages,
        worker_launch=dict(isolated=True, bytecode_disabled=True, device="cpu",
            environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", "TOKENIZERS_PARALLELISM": "false"},
            owner_sha256=source384._pins()["files"][source384.__name__]),
        scope="exact_interpreter_numpy_linalg_distribution_metadata_and_frozen_worker_launch_not_full_OS_closure")


def _head(registry, parent_version_id, branch, expected):
    _require(type(expected) is dict and set(expected) == {"variant_id", "branch", "version_id", "generation"}
        and type(expected["generation"]) is int and expected["generation"] >= 1
        and expected["version_id"] == parent_version_id, "exact parent version/generation head required")
    parent = registry.get_version(parent_version_id)
    _require(expected["variant_id"] == parent["variant_id"] and expected["branch"] == branch
        and registry.resolve_head(parent["variant_id"], branch) == expected,
             "expected model head changed")
    return parent


def _weights(checkpoint):
    projection = checkpoint["projection_state"]
    return dict(checkpoint_sha256=_sha(_raw(checkpoint)),
        head_sha256=_sha(_raw(checkpoint["head_state"])),
        projection_sha256=_sha(_raw(projection)), codebook_sha256=_sha(_raw(checkpoint["target_schema"])),
        layout=dict(dimension=384, arithmetic_dtype="float64", tensor_encoding="canonical_JSON_nested_lists",
            head_weights=[len(checkpoint["head_state"]["weights"]), len(checkpoint["head_state"]["bias"])],
            head_bias=[len(checkpoint["head_state"]["bias"])],
            projection_shapes={key: ([len(value), len(value[0])] if value and isinstance(value[0], list)
                else [len(value)]) for key, value in sorted(projection.items())}))


def _stage(registry, value):
    with tempfile.TemporaryDirectory(prefix="codebase-generation-") as directory:
        path = Path(directory) / "artifact.json"
        path.write_bytes(_raw(value))
        return registry.stage_artifact(path)


def _parent_exposure(parent_checkpoint, corpus):
    """Known manifest overlap is reported; absent pretraining data stays unknown."""
    known = {row["source_sha256"] for role in ("training_manifest", "validation_manifest")
             for row in parent_checkpoint[role]}
    rows = [dict(path=row["path"], role=row["role"], source_sha256=row["source_sha256"])
            for row in corpus["rows"] if row["source_sha256"] in known]
    return dict(status="partial_manifest_only", known_source_overlap=rows,
        complete_parent_training_corpus_available=False,
        absence_of_recorded_overlap_proves_no_pretraining_exposure=False,
        parent_manifest_sha256=_sha(_raw({key: parent_checkpoint[key]
            for key in ("training_manifest", "validation_manifest")})))


def adapt_current_source384(index, repository, *, expected_head, frozen_corpus, registry,
        parent_version_id, branch, expected_model_head, operation_id, embedding_snapshot,
        scheduler=None, parent_lease=None, cancel_event=None, timeout_seconds=180., memory_mb=2048):
    """Fit a numerical child, attach its envelope only while both heads match."""
    source384._limits(timeout_seconds, memory_mb, operation_id)
    deadline = time.monotonic() + timeout_seconds
    def remaining():
        seconds = deadline - time.monotonic()
        _require(seconds > 0 and (cancel_event is None or not cancel_event.is_set()),
                 "adaptation cancelled or deadline expired")
        return seconds

    remaining()
    source384._owners(index, registry)
    parent = _head(registry, parent_version_id, branch, expected_model_head)
    corpus = corpus_owner.verify_frozen_corpus(frozen_corpus, index, expected_head=expected_head)
    chain = source384._lineage(index, registry, parent_version_id)
    parent_saved = chain[0][1]
    parent_checkpoint = (source384._root_view(parent_saved) if parent_saved["kind"] == "shared_parent"
                         else parent_saved["checkpoint"])
    producer, environment = _pins(), _environment()
    request = dict(schema=SCHEMA, operation_id=operation_id, parent_version_id=parent_version_id, branch=branch,
        expected_model_head=deepcopy(expected_model_head), source_head=expected_head.to_dict(),
        corpus_sha256=corpus["corpus_sha256"], producer=producer, environment=environment,
        embedding_snapshot=str(Path(embedding_snapshot).resolve()))
    # The digest includes every pre-fit guard. Reusing an operation ID with a
    # different strict cohort cannot attach an old numerical result.
    fit_operation = "generation:" + _sha(_raw(request))
    result = source384.train_current_source384(index, repository, expected_head=expected_head,
        registry=registry, parent_version_id=parent_version_id,
        selections=corpus["fit_source_corpus"]["selections"], operation_id=fit_operation,
        embedding_snapshot=embedding_snapshot, scheduler=scheduler, parent_lease=parent_lease,
        cancel_event=cancel_event, timeout_seconds=remaining(), memory_mb=memory_mb)
    remaining()
    _head(registry, parent_version_id, branch, expected_model_head)
    corpus_owner.verify_frozen_corpus(frozen_corpus, index, expected_head=expected_head)
    _require(environment == _environment() and producer == _pins(), "adaptation environment/producer changed")
    index.observe_current(repository, expected_head=expected_head, scheduler=scheduler, parent_lease=parent_lease,
        cancel_event=cancel_event, timeout_seconds=remaining(), memory_mb=memory_mb)
    child_version, child = source384._lineage(index, registry, result["version_id"])[0]
    _require(child["corpus"] == corpus["fit_source_corpus"], "numerical child fitted a different frozen cohort")
    remaining()
    value = dict(schema=SCHEMA, profile=corpus_owner.PROFILE, kind="source384_child_adaptation",
        request=request, parent=dict(version_id=parent_version_id, artifact=parent["artifact"],
            checkpoint_sha256=_sha(_raw(parent_checkpoint))),
        numerical_child=dict(version_id=result["version_id"], artifact=child_version["artifact"]),
        source_head=expected_head.to_dict(), corpus_artifact=_stage(registry, corpus),
        corpus_sha256=corpus["corpus_sha256"], weights=_weights(child["checkpoint"]),
        producer=producer, environment=environment, randomness=deepcopy(RANDOMNESS),
        parent_exposure=_parent_exposure(parent_checkpoint, corpus),
        objectives=deepcopy(OBJECTIVES),
        evaluation=child["evaluation"], worker_receipt=child["worker_receipt"],
        numerical_run_id="source384:" + fit_operation, **FALSE)
    value["generation_sha256"] = _sha(_raw(value))
    remaining()
    artifact = _stage(registry, value)
    # Registration is immutable candidate attachment, not head advancement.
    # Recheck immediately before attachment; separate owner stores are not a
    # distributed source/model transaction. Publication uses native CAS below.
    _head(registry, parent_version_id, branch, expected_model_head)
    remaining()
    receipt = registry.register_version("attach:" + fit_operation, parent["variant_id"], artifact,
        metadata={"schema": SCHEMA, "numerical_child_version_id": result["version_id"]},
        parent_version_id=parent_version_id)
    _head(registry, parent_version_id, branch, expected_model_head)
    remaining()
    return {**receipt, "numerical_child_version_id": result["version_id"],
        "training_executed": result["training_executed"], "replayed": result["replayed"],
        "generation_sha256": value["generation_sha256"], "evaluation": deepcopy(value["evaluation"]), **FALSE}


def load_generation(index, registry, version_id):
    """Replay exact artifact/source/weights/codebook joins; never train on load."""
    version = registry.get_version(version_id)
    value = json.loads(registry.read_artifact(version["artifact"], max_bytes=source384.MAX_BYTES))
    fields = {"schema", "profile", "kind", "request", "parent", "numerical_child", "source_head",
        "corpus_artifact", "corpus_sha256", "weights", "producer", "environment", "randomness",
        "parent_exposure", "objectives", "evaluation", "worker_receipt", "numerical_run_id",
        "generation_sha256", *FALSE}
    _require(type(value) is dict and set(value) == fields and value["schema"] == SCHEMA
        and value["profile"] == corpus_owner.PROFILE and value["kind"] == "source384_child_adaptation"
        and all(value[key] is False for key in FALSE), "closed non-authoritative model generation required")
    _require(value["generation_sha256"] == _sha(_raw({k: v for k, v in value.items() if k != "generation_sha256"}))
        and value["producer"] == _pins(), "generation identity or producer differs")
    parent_version, parent = source384._lineage(index, registry, value["parent"]["version_id"])[0]
    parent_checkpoint = source384._root_view(parent) if parent["kind"] == "shared_parent" else parent["checkpoint"]
    child_version, child = source384._lineage(index, registry, value["numerical_child"]["version_id"])[0]
    _require(version["parent_version_id"] == parent_version["version_id"] == child_version["parent_version_id"]
        and version["variant_id"] == parent_version["variant_id"] == child_version["variant_id"]
        and value["parent"] == dict(version_id=parent_version["version_id"], artifact=parent_version["artifact"],
            checkpoint_sha256=_sha(_raw(parent_checkpoint)))
        and value["numerical_child"]["artifact"] == child_version["artifact"], "generation parent/child artifact differs")
    corpus = json.loads(registry.read_artifact(value["corpus_artifact"], max_bytes=source384.MAX_BYTES))
    _require(corpus["schema"] == corpus_owner.SCHEMA
        and corpus["corpus_sha256"] == value["corpus_sha256"]
        and corpus["corpus_sha256"] == _sha(_raw({k: v for k, v in corpus.items() if k != "corpus_sha256"}))
        and child["corpus"] == corpus["fit_source_corpus"]
        and value["source_head"] == child["corpus"]["head"] == corpus["source_corpus"]["head"],
        "generation source/corpus differs")
    completion = registry.get_run_completion(value["numerical_run_id"])
    _require(completion is not None and completion["candidate_version"]["version_id"] == child_version["version_id"],
             "generation has no completed native numerical run")
    _require(value["weights"] == _weights(child["checkpoint"])
        and value["evaluation"] == child["evaluation"] and value["worker_receipt"] == child["worker_receipt"],
        "generation weight/layout/evaluation differs")
    request = value["request"]
    _require(type(request) is dict and set(request) == {"schema", "operation_id", "parent_version_id", "branch",
        "expected_model_head", "source_head", "corpus_sha256", "producer", "environment", "embedding_snapshot"}
        and request["schema"] == SCHEMA and request["parent_version_id"] == parent_version["version_id"]
        and request["corpus_sha256"] == value["corpus_sha256"]
        and request["source_head"] == value["source_head"] and request["producer"] == value["producer"]
        and request["environment"] == value["environment"]
        and request["embedding_snapshot"] == child["request"]["embedding_snapshot"], "generation pre-fit request differs")
    _require(value["numerical_run_id"] == "source384:generation:" + _sha(_raw(request))
        and value["randomness"] == RANDOMNESS and value["objectives"] == OBJECTIVES
        and value["parent_exposure"] == _parent_exposure(parent_checkpoint, corpus),
        "generation run/seed/objective/exposure binding differs")
    return value


def promote_generation(index, registry, version_id, *, operation_id):
    """Retention gate plus independent registry policy and native expected-head CAS."""
    value = load_generation(index, registry, version_id)
    evaluation = value["evaluation"]
    parent, child = evaluation["parent_holdout"], evaluation["child_holdout"]
    _require(parent["count"] > 0 and child["count"] == parent["count"]
        and child["exact_targets"] >= parent["exact_targets"]
        and child["valid_candidates"] == child["count"], "child retention gate failed; candidate stays unpromoted")
    request = value["request"]
    parent_version = registry.get_version(value["parent"]["version_id"])
    expected = request["expected_model_head"]
    return registry.promote_head(operation_id, parent_version["variant_id"], request["branch"],
        value["numerical_child"]["version_id"], expected_version_id=expected["version_id"],
        expected_generation=expected["generation"], evaluation=dict(generation_version_id=version_id,
            candidate_version_id=value["numerical_child"]["version_id"], protocol_id=SCHEMA,
            generation_sha256=value["generation_sha256"], retention=evaluation))


__all__ = ["adapt_current_source384", "load_generation", "promote_generation", "SCHEMA"]

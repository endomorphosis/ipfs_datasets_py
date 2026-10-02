"""Explicit CodebaseIR runtime registration and source-bound parent inference.

The existing SecurityIR structured decoder is a partial numerical inheritance.
Source/checker semantics remain native and independent of its learned output.
This module never silently trains, selects a head, or promotes a checkpoint.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path, PurePosixPath
import time

from . import codebase_source_384 as numerical
from . import codebase_training_corpus as corpus_owner
from . import codebase_training_lifecycle as lifecycle
from .codebase_resources import acquire_codebase_resources
from ...optimizers.logic_theorem_optimizer import autoencoder_modality_contracts as contracts
from ...optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as embedding

SCHEMA = "codebase-runtime-contract@1"
INFERENCE_SCHEMA = "codebase-parent-source-inference@1"
VERSION = "source_conditioned_384_v1"
_raw, _sha, _require = numerical._raw, numerical._sha, numerical._require
OBJECTIVES = dict(feature=dict(kind="gte_small_source_features", dimension=384, learned_here=False),
    structured=dict(kind="source_conditioned_fixed_schema_head_refit", learned_here=True,
                    label_authority="independent_native_AST_and_ProgramIR_alignment"),
    property=dict(kind="independent_finite_ProgramIR_state_correspondence", learned_here=False,
                  missing_is_unknown=True, requires_live_native_checker=True))


def _pins():
    return dict(runtime=_sha(Path(__file__).read_bytes()), numerical=numerical._pins(),
        modality_contracts=_sha(Path(contracts.__file__).read_bytes()),
        embedding=_sha(Path(embedding.__file__).read_bytes()),
        corpus=corpus_owner._pins(), lifecycle=lifecycle._pins())


def describe_runtime():
    """Read an explicit declaration; no models, corpora, training or admission."""
    return dict(schema=SCHEMA, domain="codebase_ir", runtime_version=VERSION,
        runtime_id="codebase_ir:"+VERSION, payload_domain="security_ir", input_dimension=384,
        source_contract="captured_repository_exact_utf8_bytes@1",
        target_contract="independently_source_qualified_ProgramIR@1",
        decoder_contract="unchanged_shared_security_structured_384",
        validator_contract="native_source_alignment_then_explicit_independent_checker",
        resume_contract=dict(mode="partial_inheritance_full_selected_head_refit",
            inherited=["frozen_legal_projection", "target_shape", "target_vocabulary"],
            head_weight_initialization=False, exact_optimizer_resume=False,
            optimizer_steps=0, prior_statistics_recovered_from_weights=False),
        objectives=deepcopy(OBJECTIVES), producer=_pins(),
        capabilities=["prepare_targets", "validate_targets", "train", "evaluate"],
        authority=dict(numerical.FALSE), training_executed=False)


def modality_contract():
    """Use the existing immutable modality contract and local adapter registry."""
    identity = lambda name, payload: contracts.ImplementationIdentity(name, "1", _sha(_raw(payload)))
    return contracts.ModalityContract(domain="codebase_ir", ir_schema="ProgramIR/scalar-source@1",
        source_language="python-pure-annotated-scalar", input_schema="captured-source-gte384@1",
        embedding=contracts.EmbeddingIdentity("thenlper/gte-small", embedding.PINNED_REVISION, 384,
            _sha(_raw(embedding._PINNED_ASSETS))),
        projections=(contracts.ProjectionSpec("codebase-program", "program", "ProgramIR@1"),),
        target_codec=identity("source-qualified-program-target", numerical._pins()),
        state_codec=identity("codebase-source384-generation", dict(schema=numerical.SCHEMA,producer=numerical._pins())),
        optimizer=identity("full-corpus-ridge-head-refit", describe_runtime()["resume_contract"]),
        objective_id="codebase-feature-structured-property-separate@1",
        objective_sha256=_sha(_raw(OBJECTIVES)),
        validators=(contracts.ValidatorRequirement("native-source-alignment", "bounded", "candidate", ("codebase-program",)),
            contracts.ValidatorRequirement("explicit-finite-model-checker", "independently_checkable", "kernel_checked_proof", ("codebase-program",), False)),
        adapter=identity("codebase-source384-local-adapter", _pins()))


def _source_inputs(index, expected_head, paths):
    from ...duckdb_control.codebase_catalog import CodebaseHead
    _require(type(expected_head) is CodebaseHead, "native exact source head required")
    _require(type(paths) in (list, tuple) and 1 <= len(paths) <= 128
        and all(type(path) is str and 0 < len(path) <= 1024 for path in paths)
        and len(set(paths)) == len(paths), "distinct bounded source paths required")
    manifest = index.load(expected_head.manifest_cid)
    _require(manifest.snapshot.snapshot_cid == expected_head.snapshot_cid
        and manifest.ast_revision_id == expected_head.ast_revision_id
        and manifest.snapshot.repository_id == expected_head.repository_id, "source head differs")
    by_path = {entry.path: entry for entry in manifest.snapshot.entries}
    rows, inventory = [], []
    for path in paths:
        parsed = PurePosixPath(path)
        _require(parsed.as_posix() == path and not parsed.is_absolute() and ".." not in parsed.parts
            and path.endswith(".py"), "canonical captured Python source path required")
        entry = by_path.get(path)
        _require(entry is not None and entry.source_cid is not None, "selected source is not captured")
        blob = index.artifacts.get_bytes(entry.source_cid)
        _require(0 < len(blob) <= 65536, "bounded complete source unit required")
        identity = _sha(path.encode())
        rows.append(dict(id=identity, source_text=blob.decode("utf-8")))
        inventory.append(dict(id=identity, path=path, source_cid=entry.source_cid,
                              source_sha256=_sha(blob), bytes=len(blob)))
    return rows, inventory


def infer_shared_parent(index, repository, *, expected_head, registry, version_id, paths,
        embedding_snapshot, scheduler=None, parent_lease=None, cancel_event=None,
        timeout_seconds=120., memory_mb=4096, weight_ablation=None):
    """Infer with exact shared weights on current source without training labels.

    Both unsupported and mismatched predictions are retained by the frozen
    independent source validator. A parent inference is never a trained child
    and never claims repository-specific holdout quality or proof authority.
    """
    numerical._limits(timeout_seconds, memory_mb, "parent-inference")
    numerical._owners(index, registry)
    _require(weight_ablation in (None, "zero_head", "zero_projection", "shuffle_embeddings"), "unknown model control")
    deadline = time.monotonic()+timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, timeout_seconds=min(30., timeout_seconds), memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def remaining():
            _require(not signal.is_set() and time.monotonic() < deadline, "parent inference cancelled or deadline expired")
            return deadline-time.monotonic()
        def observe():
            index.observe_current(repository, expected_head=expected_head, parent_lease=lease,
                cancel_event=signal, timeout_seconds=remaining(), memory_mb=memory_mb)
        observe()
        version, saved = numerical._lineage(index, registry, version_id)[0]
        _require(saved["kind"] == "shared_parent", "exact registered shared_parent required")
        checkpoint = numerical._root_view(saved)
        inputs, inventory = _source_inputs(index, expected_head, paths)
        snapshot = str(Path(embedding_snapshot).resolve())
        _, assets = embedding._snapshot_assets(snapshot)
        pins = _pins()
        payload = dict(action="infer", checkpoint=checkpoint, rows=inputs, producer=numerical._pins(),
                       embedding_snapshot=snapshot, weight_ablation=weight_ablation)
        result, receipt = numerical._worker(payload, lease=lease, signal=signal,
                                            timeout=remaining(), memory_mb=memory_mb)
        observe()
        _, final_assets = embedding._snapshot_assets(snapshot)
        _require(pins == _pins() and assets == final_assets == result["embedding_assets"]
            and result["producer"] == numerical._pins() and result["training_executed"] is False,
            "parent inference source/embedding/producer changed")
        _require(numerical._lineage(index, registry, version_id)[0] == (version, saved), "parent version changed")
        remaining()
        return dict(schema=INFERENCE_SCHEMA, profile=numerical.PROFILE,
            provenance_kind="pinned_shared_parent_inference", source_head=expected_head.to_dict(),
            version_id=version_id, parent_artifact=deepcopy(version["artifact"]),
            original_checkpoint_sha256=saved["original_checkpoint_sha256"],
            runtime_checkpoint_sha256=_sha(_raw(checkpoint)), source_inventory=inventory,
            source_input_sha256=_sha(_raw(inputs)), producer=pins, embedding_assets=assets,
            inference=result["inference"], worker_receipt=receipt, training_executed=False,
            training_labels_used=False, weight_ablation=weight_ablation, **numerical.FALSE)


class CodebaseRuntime384:
    def __init__(self):
        self.contract = modality_contract()
        self._implementation = _pins()

    def _check(self):
        _require(self._implementation == _pins(), "registered CodebaseIR runtime implementation changed")

    def prepare_targets(self, index, **options):
        self._check()
        return corpus_owner.freeze_corpus(index, **options)

    def validate_targets(self, frozen_corpus, index, **options):
        self._check()
        return corpus_owner.verify_frozen_corpus(frozen_corpus, index, **options)

    def train(self, job, **options):
        self._check()
        return lifecycle.execute_job(job, **options)

    def evaluate(self, index, repository, **options):
        self._check()
        return infer_shared_parent(index, repository, **options)


def register_runtime(registry):
    """Register trusted local callables in the existing exact-contract registry."""
    _require(type(registry) is contracts.ModalityAdapterRegistry, "native local modality adapter registry required")
    adapter = CodebaseRuntime384()
    registry.register(adapter.contract, adapter, capabilities=describe_runtime()["capabilities"])
    return adapter


__all__ = ["CodebaseRuntime384", "register_runtime", "modality_contract", "describe_runtime", "infer_shared_parent"]

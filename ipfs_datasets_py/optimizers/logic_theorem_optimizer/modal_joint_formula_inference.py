"""Opt-in faster inference with the original joint checkpoint/source checks.

The additive projection preserves historical addition order and uses the signed
core's feature helpers. A private state view avoids rebuilding every sparse row;
one sample snapshot lets helpers share an observation cache without repeatedly
fingerprinting the embedding. Identical view readouts are reused within the
owned sample, and view candidates only within one checked inference request.
Private caches are discarded on return, including when inference raises.
No candidate names, sample observations or predictions survive a call.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
from itertools import chain
from pathlib import Path

from . import modal_joint_formula as joint
from .autoencoder_lineages._contract import validate_sample, validate_vector


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


_SOURCE_AT_IMPORT = _source_sha256()
_SAMPLE_READOUTS = (
    "_compiler_quality_slot_distribution_for", "_logic_signature_distribution_for",
    "_round_trip_signal_distribution_for", "_decompiler_plan_distribution_for",
    "_predicate_argument_distribution_for", "_semantic_slot_distribution_for",
    "_family_distribution_for_embedding", "_family_distribution_for_semantic_slot_embedding",
    "_target_family_distribution_for_semantic_slot_embedding",
    "_legal_ir_view_target_distribution_for_sample",
)


def inference_implementation():
    """Report the opt-in projector independently of existing checkpoint pins."""
    joint._require(_source_sha256() == _SOURCE_AT_IMPORT,
                   "joint inference implementation changed since import")
    return {"schema": "modal-joint-formula-inference-implementation/v1",
            "projection": "private-state-view-request-candidates-validated-empty-heads/v6",
            "source_sha256": _SOURCE_AT_IMPORT,
            "original_checkpoint_source_binding_preserved": True,
            "checkpoint_conversion_performed": False}


def _view_family_candidates(worker):
    """Preserve the core's candidate order while deduplicating before filtering.

    Most large logit tables repeat the same handful of names. Normalize every
    key exactly as the core does, then merge each table in C rather than calling
    the Python ``add`` helper for every repeated name. The dictionaries only
    retain unique names, including modal names until the final filter.
    """
    cached = worker._legal_ir_view_family_candidates_cache
    if cached is not None:
        return cached
    names = dict.fromkeys(map(str, worker.state.legal_ir_view_embedding_weights))
    for table, width in (
        (worker.state.family_legal_ir_view_embedding_weights, 2),
        (worker.state.semantic_slot_legal_ir_view_embedding_weights, 2),
        (worker.state.family_semantic_slot_legal_ir_view_embedding_weights, 3),
    ):
        for key in table:
            parts = str(key).split("||")
            if len(parts) == width:
                names[parts[-1]] = None
    names.update(dict.fromkeys(map(str, worker.state.legal_ir_view_logits)))
    for table in (
        worker.state.feature_legal_ir_view_logits,
        worker.state.feature_family_logits,
        worker.state.semantic_slot_legal_ir_view_logits,
        worker.state.logic_signature_legal_ir_view_logits,
        worker.state.round_trip_signal_legal_ir_view_logits,
        worker.state.decompiler_plan_legal_ir_view_logits,
        worker.state.predicate_argument_legal_ir_view_logits,
        worker.state.family_semantic_slot_legal_ir_view_logits,
    ):
        names.update(dict.fromkeys(map(str, chain.from_iterable(table.values()))))
    cached = tuple(name for name in names if worker._is_legal_ir_view_family(name))
    worker._legal_ir_view_family_candidates_cache = cached
    return cached


def _worker(model):
    """Create one request-private read view, excluding all sample memories."""
    worker = copy.copy(model)
    # TrainingState.__copy__ intentionally performs a full transactional copy.
    # Allocate this extraction-only read view without invoking that protocol or
    # a dataclass constructor. Its own attribute dictionary shares sparse rows
    # read-only; none of the projection helpers performs state writes.
    worker.state = object.__new__(type(model.state))
    worker.state.__dict__.update(model.state.__dict__)
    # dataclasses.replace reconstructs recursive tracking for every sparse row.
    # This view only reads those rows. Bypass state __setattr__ as well: its
    # tracker is owned by the caller and must not observe private memory masks.
    object.__setattr__(worker.state, "family_logits", {})
    object.__setattr__(worker.state, "decoded_embeddings", {})
    worker._sample_feature_cache = {}
    worker._invalidate_legal_ir_view_family_candidates()
    worker._request_sample_cache_for = worker._sample_cache_for
    worker._request_view_distribution_for_embedding = worker._legal_ir_view_distribution_for_embedding
    worker._request_sample_readouts = {name: getattr(worker, name) for name in _SAMPLE_READOUTS}
    worker._request_cue_names_for_text = worker._cue_names_for_text
    worker._legal_ir_view_family_candidates = lambda: _view_family_candidates(worker)
    return worker


def _release_worker(worker):
    """Discard observations and break private bound-method/closure cycles."""
    worker._sample_feature_cache.clear()
    worker._invalidate_legal_ir_view_family_candidates()
    for name in ("_sample_cache_for", "_request_sample_cache_for",
                 "_legal_ir_view_family_candidates", "_legal_ir_view_distribution_for_embedding",
                 "_request_view_distribution_for_embedding", "_request_sample_readouts",
                 "_cue_names_for_text", "_request_cue_names_for_text", *_SAMPLE_READOUTS):
        worker.__dict__.pop(name, None)


def _project_sample(worker, sample, *, _validated_package_sample=False):
    """Extract from an owned nested snapshot, keeping observation caches local."""
    validate_sample(sample, worker.DIMENSION)
    sample = copy.deepcopy(sample)
    validate_sample(sample, worker.DIMENSION)
    worker._sample_feature_cache = {}
    cache_for = worker._request_sample_cache_for
    sample_cache = {}
    worker._sample_cache_for = lambda observed: (
        sample_cache if observed is sample else cache_for(observed)
    )
    def readout_for(original):
        memo = {}
        def readout(observed, **options):
            if observed is not sample:
                return original(observed, **options)
            joint._require(not worker._legal_ir_view_target_cache and not worker._legal_ir_loss_target_cache,
                           "joint formula input cannot use cached teacher bridge targets")
            key = (worker.state.state_revision, tuple(options.items()))
            if key not in memo:
                memo[key] = dict(original(observed, **options))
            return dict(memo[key])
        return readout
    for name, original in worker._request_sample_readouts.items():
        setattr(worker, name, readout_for(original))
    cue_cache = {}
    cues_for = worker._request_cue_names_for_text
    def cue_names(text):
        if type(text) is not str:
            return cues_for(text)
        if text in cue_cache:
            return list(cue_cache[text])
        value = cues_for(text)
        # Retain at most 128 exact strings for this owned sample. Uncached
        # overflow uses the original implementation with identical results.
        if len(cue_cache) < 128:
            cue_cache[text] = tuple(value)
        return value
    worker._cue_names_for_text = cue_names
    view_for = worker._request_view_distribution_for_embedding
    view_cache = {}
    def view_distribution(observed, *, use_sample_memory):
        if observed is not sample:
            return view_for(observed, use_sample_memory=use_sample_memory)
        joint._require(not worker._legal_ir_view_target_cache and not worker._legal_ir_loss_target_cache,
                       "joint formula input cannot use cached teacher bridge targets")
        # The owned sample is read-only. A sparse write changes the shared
        # tracking revision, so a changed readout cannot reuse an earlier value.
        key = (worker.state.state_revision, bool(use_sample_memory))
        if key not in view_cache:
            view_cache[key] = dict(view_for(observed, use_sample_memory=use_sample_memory))
        # Helpers receive fresh dictionaries, preserving independent ownership.
        return dict(view_cache[key])
    worker._legal_ir_view_distribution_for_embedding = view_distribution
    base = worker._base_decoded_for(sample)
    dimensions = len(base)
    names = (
        ("compiler_quality", False), ("logic_signature", False),
        ("round_trip_signal", False), ("decompiler_plan", False),
        ("predicate_argument", False), ("family", True),
        ("semantic_slot", False), ("family_semantic_slot", True),
        ("semantic_slot_legal_ir_view", True), ("family_semantic_slot_legal_ir_view", True),
        ("family_legal_ir_view", True), ("legal_ir_view", True), ("feature", False),
    )
    adjustments = []
    empty_table_types = ()
    if _validated_package_sample:
        # Both supported cores install this exact dict subclass for sparse
        # state. Arbitrary mapping subclasses retain the original helper path.
        state_module = importlib.import_module(type(worker.state._state_identity_tracker).__module__)
        empty_table_types = (dict, state_module._TrackedDict)
    for name, memory in names:
        weights = getattr(worker.state, name + "_embedding_weights")
        if type(weights) in empty_table_types and dict.__len__(weights) == 0:
            # The original helper returns these positive zeros when its sole
            # embedding table is empty. Preserve every ordered zero addition,
            # including the historical conversion of negative zero to +0.0.
            # This shortcut is restricted to freshly built package samples;
            # custom samples still run the original feature compatibility work.
            adjustments.append([0.0] * dimensions)
            continue
        options = {"dimensions": dimensions}
        if memory:
            options["use_sample_memory"] = False
        adjustments.append(getattr(worker, "_" + name + "_embedding_adjustment")(sample, **options))
    adjustments.append(worker._legacy_embedding_tail_adjustment(
        sample, dimensions=dimensions, use_sample_memory=False))
    result = []
    for index, value in enumerate(base):
        for adjustment in adjustments:
            value = value + adjustment[index]
        result.append(float(value))
    validate_vector(result, worker.DIMENSION, "raw joint formula input")
    return result


def raw_projection(model, sample, *, _validated_package_sample=False):
    """Run the historical additive readout over a private state/sample view.

    Frozen sample dataclasses can contain mutable lists/dicts. Copy their full
    nested contents before using object identity for this single extraction;
    later calls always observe later source/vector/parser mutations. Both the
    owner and the worker inside the original readout keep their own caches.
    """
    inference_implementation()
    joint._require(type(_validated_package_sample) is bool,
                   "validated package sample flag must be boolean")
    joint._require(not model._legal_ir_view_target_cache and not model._legal_ir_loss_target_cache,
                   "joint formula input cannot use cached teacher bridge targets")
    worker = _worker(model)
    try:
        return _project_sample(worker, sample, _validated_package_sample=_validated_package_sample)
    finally:
        _release_worker(worker)


def _rows(model, samples, *, _validated_package_samples=False):
    """Project samples already checked by the original source/identity boundary."""
    joint._require(not model._legal_ir_view_target_cache and not model._legal_ir_loss_target_cache,
                   "joint formula input cannot use cached teacher bridge targets")
    joint._require(type(_validated_package_samples) is bool,
                   "validated package samples flag must be boolean")
    worker = _worker(model)
    try:
        return [{"id": sample.sample_id, "source_text": sample.text,
                 "latent": _project_sample(worker, sample,
                                           _validated_package_sample=_validated_package_samples)}
                for sample in samples]
    finally:
        _release_worker(worker)


def _attached_checkpoint(model, guard):
    """Keep original runtime/source checks around an exact content snapshot."""
    if guard is None:
        return joint._attached_checkpoint(model, validate_runtime=True)
    checkpoint = getattr(model, "_joint_formula_checkpoint", None)
    decoder = getattr(model, "_joint_formula_decoder", None)
    joint._require(checkpoint is not None and decoder is not None,
                   "learned latent formula decoder requires training or an attached checkpoint")
    joint._require(decoder.checkpoint_sha256 == guard.sha256,
                   "cached formula decoder differs from attached checkpoint; reattach explicitly")
    guard.check(checkpoint,
                message="cached formula decoder differs from attached checkpoint; reattach explicitly")
    # This remains the original decoder's full source and tensor-value check,
    # including parameter writes through .data that do not advance versions.
    decoder._check()
    return checkpoint


def infer(model, samples, decoder=None, *, _checkpoint_guard=None, _joint_profile=None,
          _validated_package_samples=False):
    """Preserve joint results and integrity checks with an optional owned decoder.

    A separately restored fast decoder must describe the exact attached
    checkpoint. It remains private to the caller; the model's decoder is never
    replaced, and full core/source bindings are checked before and after work.
    """
    inference_implementation()
    joint._require(type(_validated_package_samples) is bool,
                   "validated package samples flag must be boolean")
    checkpoint = _attached_checkpoint(model, _checkpoint_guard)
    binding = joint._core_binding(model)
    joint._require(checkpoint["binding"] == binding, "core changed after decoder attachment")
    if decoder is None:
        decoder = model._joint_formula_decoder
    joint._require(decoder.checkpoint_sha256 == model._joint_formula_decoder.checkpoint_sha256,
                   "inference decoder differs from attached checkpoint")
    samples = joint._samples(model, samples)
    joint._require(len(samples) <= 128, "joint formula inference requires at most 128 samples")
    rows = _rows(model, samples, _validated_package_samples=_validated_package_samples)
    if hasattr(decoder, "infer_with_projection"):
        result, vectors = decoder.infer_with_projection(rows)
    else:
        result = decoder.infer(rows)
        vectors = decoder.project([row["latent"] for row in rows])
    result["decoded_embeddings"] = {row["id"]: vector for row, vector in zip(rows, vectors)}
    result["reconstruction_loss"] = sum(
        sum((float(expected) - actual) ** 2 for expected, actual in zip(sample.embedding_vector, vector))
        / model.DIMENSION for sample, vector in zip(samples, vectors)) / len(samples)
    result["reconstruction_scope"] = "learned_projection_before_target_safety_or_sample_memory"
    joint._require(joint._core_binding(model) == binding, "core changed during formula inference")
    _attached_checkpoint(model, _checkpoint_guard)
    inference_implementation()
    result["joint_profile"] = (joint.describe(model) if _joint_profile is None
                               else copy.deepcopy(_joint_profile))
    return result


class JointInferenceSession:
    """Reuse a worker-private batched head while retaining full binding checks."""

    def __init__(self, model):
        from .checkpoint_content_guard import CheckpointContentGuard
        from .modal_latent_formula_inference import BatchedLatentFormulaDecoder
        inference_implementation()
        checkpoint = joint._attached_checkpoint(model, validate_runtime=True)
        binding = joint._core_binding(model)
        joint._require(checkpoint["binding"] == binding, "core changed after decoder attachment")
        self._model = model
        self._binding = copy.deepcopy(binding)
        self._decoder = BatchedLatentFormulaDecoder(checkpoint, expected_binding=binding)
        self._checkpoint_guard = CheckpointContentGuard(
            checkpoint, expected_sha256=self._decoder.checkpoint_sha256)
        self._joint_profile = joint.describe(model)

    @property
    def binding(self):
        """A diagnostic copy; callers cannot modify the session's identity."""
        return copy.deepcopy(self._binding)

    def infer(self, samples, *, _validated_package_samples=False):
        result = infer(self._model, samples, self._decoder,
                       _checkpoint_guard=self._checkpoint_guard, _joint_profile=self._joint_profile,
                       _validated_package_samples=_validated_package_samples)
        result["inference_implementation"] = {
            "joint_projection": inference_implementation(),
            "formula_decoder": result.get("inference_implementation"),
            "checkpoint_content_guard": self._checkpoint_guard.inference_implementation,
            "view_candidates": {"scope": "one_inference_request",
                                "retained_after_request": 0},
        }
        return result

__all__ = ["JointInferenceSession", "infer", "raw_projection", "inference_implementation"]

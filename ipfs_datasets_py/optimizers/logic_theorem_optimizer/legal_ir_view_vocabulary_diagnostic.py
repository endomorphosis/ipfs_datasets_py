"""Separate, bounded diagnostics over the existing optimizer contract lanes.

This module changes no training objective, evaluation loss, checkpoint, or
acceptance rule.  Targets remain compiler observations, not reviewed meanings.
Imports of the existing product owners are deferred until an API is called.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import math
import stat
import threading
from pathlib import Path


PROFILE_SCHEMA = "legal-ir-bridge-contract-view-profile/v1"
PROFILE_ID = "compiled-bridge-contract-lanes-seven/v1"
REPORT_SCHEMA = "legal-ir-fixed-view-vocabulary-diagnostic/v1"
MAX_ROWS = 256
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_STATE_BYTES = 128 * 1024 * 1024
MAX_NODES = 2_000_000
MAX_DEPTH = 48
MAX_NUMBER = 1e100
_PACKAGE = Path(__file__).resolve().parents[2]
_ADAPTER_BUSY = threading.Lock()
_PROFILE_SOURCES = ("logic/bridge/multiview.py", "logic/bridge/registry.py")
_MODEL_SOURCES = (
    "optimizers/logic_theorem_optimizer/modal_autoencoder.py",
    "optimizers/logic_theorem_optimizer/legal_samples.py",
    "optimizers/logic_theorem_optimizer/modal_ir.py",
    "optimizers/logic_theorem_optimizer/modal_registry.py",
    "optimizers/logic_theorem_optimizer/modal_autoencoder_state_version.py",
    "optimizers/logic_theorem_optimizer/legal_ir_view_vocabulary_diagnostic.py",
)
_HEAD_SCALES = {
    "legal_ir_view_logits": "legal_ir_view_logit_scale",
    "feature_legal_ir_view_logits": "legal_ir_view_logit_scale",
    "feature_family_logits": "legal_ir_view_logit_scale",
    "semantic_slot_legal_ir_view_logits": "semantic_slot_legal_ir_view_logit_scale",
    "logic_signature_legal_ir_view_logits": "logic_signature_legal_ir_view_logit_scale",
    "round_trip_signal_legal_ir_view_logits": "round_trip_signal_legal_ir_view_logit_scale",
    "decompiler_plan_legal_ir_view_logits": "decompiler_plan_legal_ir_view_logit_scale",
    "predicate_argument_legal_ir_view_logits": "predicate_argument_legal_ir_view_logit_scale",
    "family_semantic_slot_legal_ir_view_logits": "family_semantic_slot_legal_ir_view_logit_scale",
}
_CACHE_FIELDS = frozenset({
    "_sample_feature_cache", "_legal_ir_loss_target_cache", "_legal_ir_view_target_cache",
    "_legal_ir_view_family_candidates_cache", "_cuda_resident_projection_state",
    "_cuda_resident_proof_state", "_cuda_residency_reports",
})
_CONTEXT_FIELDS = frozenset({
    "ir_family", "ir_schema_version", "decoder_task", "embedding_dimensions",
    "encoder_model", "encoder_revision", "token_profile", "max_tokens", "checkpoint_sha256",
})


class ViewVocabularyDiagnosticError(ValueError):
    """Unsupported profile, stale inputs, or malformed finite observations."""


def _need(condition, message):
    if not condition:
        raise ViewVocabularyDiagnosticError(message)


def _number(value):
    _need(type(value) in (int, float), "plain finite numeric value required")
    _need(abs(value) <= MAX_NUMBER and math.isfinite(value), "bounded finite numeric value required")
    return float(value)


def _sha(value):
    _need(type(value) is str and len(value) == 64
          and all(c in "0123456789abcdef" for c in value), "lowercase SHA256 required")
    return value


def _text(value, *, maximum=512):
    _need(type(value) is str and 0 < len(value) <= maximum, "bounded nonempty string required")
    return value


def _plain(value, *, maximum=MAX_JSON_BYTES):
    """Detach closed ordinary JSON before any owner or feature callbacks."""
    nodes = 0

    def visit(item, depth):
        nonlocal nodes
        nodes += 1
        _need(nodes <= MAX_NODES and depth <= MAX_DEPTH, "JSON traversal bound exceeded")
        kind = type(item)
        if item is None or kind in (str, bool):
            if kind is str:
                _need(len(item) <= maximum, "JSON string bound exceeded")
            return item
        if kind in (int, float):
            _number(item)
            return item
        if kind is list:
            return [visit(child, depth + 1) for child in item]
        if kind is dict:
            _need(all(type(key) is str for key in item), "plain string JSON keys required")
            return {key: visit(child, depth + 1) for key, child in item.items()}
        raise ViewVocabularyDiagnosticError("ordinary JSON containers required")

    detached = visit(value, 0)
    _need(len(_wire(detached)) <= maximum, "JSON byte bound exceeded")
    return detached


def _wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _source_rows(names):
    rows = []
    for name in names:
        path = _PACKAGE / name
        before = path.stat()
        _need(stat.S_ISREG(before.st_mode) and before.st_size <= 3 * 1024 * 1024,
              "bounded regular producer source required")
        raw = path.read_bytes()
        after = path.stat()
        witness = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
        _need(witness(before) == witness(after) and len(raw) == before.st_size,
              "producer source changed during read")
        rows.append({"path": "ipfs_datasets_py/" + name,
                     "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return rows


def build_bridge_contract_view_profile():
    """Declare the actual optimizer lanes, independently of rows and state keys.

    These existing private declarations own this namespace.  Payload view
    contracts and aggregate reporting families are different namespaces.
    Source hashes bind the existing mapper and bridge-registry generation.
    """
    before = _source_rows(_PROFILE_SOURCES)
    from ...logic.bridge import multiview

    _need(Path(multiview.__file__).resolve() == _PACKAGE / _PROFILE_SOURCES[0],
          "profile owner imported from a different repository")
    core = multiview._BRIDGE_CONTRACT_CORE_COMPONENTS
    tail = multiview._BRIDGE_CONTRACT_TAIL_PRESERVED_COMPONENTS
    excluded = multiview._BRIDGE_CONTRACT_EXCLUDED_COMPONENTS
    _need(all(type(group) is tuple and all(type(label) is str for label in group)
              for group in (core, tail, excluded)), "unsupported lane declaration ABI")
    labels = list(dict.fromkeys(label for label in (*core, *tail) if label not in excluded))
    _need(len(labels) == 7 and len(set(labels)) == 7, "unsupported seven-lane profile generation")
    _need(all(multiview._bridge_contract_lane_component(label) == label for label in labels),
          "lane declaration and existing mapper differ")
    _need(before == _source_rows(_PROFILE_SOURCES), "profile producer changed")
    return {"schema": PROFILE_SCHEMA, "profile": PROFILE_ID,
            "namespace": "optimizer_bridge_contract_lane", "labels": labels,
            "excluded_components": list(excluded), "producer_sources": before,
            "supported_adapter": "python-codec-free-no-sample-memory/v1"}


def view_profile_sha256(profile):
    """Hash the complete bounded profile, including its producer-source pins."""
    return _digest(_plain(profile))


def _checked_profile(profile, expected):
    offered = _plain(profile)
    _need(_digest(offered) == _sha(expected), "independent profile pin differs")
    _need(offered == build_bridge_contract_view_profile(), "unsupported or stale lane profile")
    return offered


def _distribution(value, labels, *, logits=False):
    _need(type(value) is dict and set(value) <= set(labels), "unknown or malformed lane labels")
    observed = {label: _number(weight) for label, weight in value.items()}
    if logits:
        return {label: observed.get(label, 0.0) for label in labels}
    _need(observed and all(weight >= 0.0 for weight in observed.values()),
          "nonnegative target weights required")
    # Scale first so valid large finite weights cannot overflow their sum.
    scale = max(observed.values())
    _need(scale > 0.0, "positive target mass required")
    total = math.fsum(weight / scale for weight in observed.values())
    return {label: (observed.get(label, 0.0) / scale) / total for label in labels}


def _authority():
    return {name: False for name in (
        "semantic_equivalence", "legal_meaning_verified", "source_authenticated",
        "review_performed", "gold_admitted", "proof_admitted", "model_promoted",
    )}


def _score(rows, profile, profile_sha256):
    labels = profile["labels"]
    _need(type(rows) is list and 0 < len(rows) <= MAX_ROWS, "bounded nonempty row list required")
    results, seen = [], set()
    for row in rows:
        _need(type(row) is dict and set(row) == {"sample_id", "logits", "target_distribution"},
              "closed score row required")
        sample_id = _text(row["sample_id"])
        _need(sample_id not in seen, "duplicate sample ID")
        seen.add(sample_id)
        logits = _distribution(row["logits"], labels, logits=True)
        target = _distribution(row["target_distribution"], labels)
        peak = max(logits.values())
        shifted = {label: value - peak for label, value in logits.items()}
        log_total = math.log(math.fsum(math.exp(value) for value in shifted.values()))
        log_probabilities = {label: value - log_total for label, value in shifted.items()}
        probabilities = {label: math.exp(value) for label, value in log_probabilities.items()}
        ce = math.fsum(-weight * log_probabilities[label] for label, weight in target.items() if weight > 0)
        entropy = math.fsum(-weight * math.log(weight) for weight in target.values() if weight > 0)
        excess = ce - entropy
        _need(excess >= -1e-12, "negative excess beyond roundoff tolerance")
        results.append({"sample_id": sample_id, "logits": logits,
                        "target_distribution": target, "predicted_distribution": probabilities,
                        "target_support": [label for label in labels if target[label] > 0.0],
                        "cross_entropy": ce, "entropy": entropy,
                        "excess_cross_entropy": max(0.0, excess),
                        "uniform_cross_entropy": math.log(len(labels))})
    metrics = {key: math.fsum(row[key] for row in results) / len(results)
               for key in ("cross_entropy", "entropy", "excess_cross_entropy", "uniform_cross_entropy")}
    return {"schema": REPORT_SCHEMA, "profile": profile, "profile_sha256": profile_sha256,
            "rows": results, "row_count": len(results), "metrics": metrics,
            "used_for_acceptance": False, "changes_training": False, "authority": _authority()}


def score_fixed_view_logits(rows, *, profile, expected_profile_sha256):
    """Score finite effective logits; never alter official clamped CE losses.

    Missing known logits mean zero. Unknown keys, including zero-valued keys,
    are refused. CE uses shifted log-sum-exp without the official 1e-12 floor.
    Excess is floored only within the declared 1e-12 roundoff tolerance.
    """
    offered = _plain(rows)
    checked = _checked_profile(profile, expected_profile_sha256)
    result = _score(offered, checked, expected_profile_sha256)
    _need(checked == build_bridge_contract_view_profile(), "profile producer changed while scoring")
    return result


def _context(value):
    context = _plain(value)
    _need(type(context) is dict and set(context) == _CONTEXT_FIELDS, "closed checkpoint context required")
    _need(context["ir_family"] == "legal_ir", "only declared legal_ir context is supported")
    _need(type(context["embedding_dimensions"]) is int
          and context["embedding_dimensions"] in (8, 384, 768), "unsupported declared embedding dimension")
    _need(context["max_tokens"] is None or type(context["max_tokens"]) is int
          and 0 < context["max_tokens"] <= 8192, "bounded declared token profile or explicit unknown required")
    for key in ("encoder_model", "encoder_revision", "token_profile"):
        if context[key] is not None:
            _text(context[key])
    for key in ("ir_family", "ir_schema_version", "decoder_task"):
        _text(context[key])
    _sha(context["checkpoint_sha256"])
    return context


def _model_configuration(model):
    """Keep only the reviewed constructor's scalar ABI and immutable families."""
    config = {}
    for key, value in vars(model).items():
        if key in _CACHE_FIELDS or key in {"state", "feature_codec", "_torch", "_legacy_embedding_adapters"}:
            continue
        if key == "modal_families":
            _need(type(value) is tuple and all(type(label) is str for label in value), "plain modal families required")
            config[key] = list(value)
        else:
            _need(value is None or type(value) in (str, int, float, bool), "unsupported model attribute ABI")
            config[key] = value
    return _plain(config)


def _sample_value(sample, legal_sample_type):
    _need(type(sample) is legal_sample_type, "exact LegalSample objects required")
    count = 0

    def check(value, depth):
        nonlocal count
        count += 1
        _need(count <= MAX_NODES and depth <= MAX_DEPTH, "sample traversal bound exceeded")
        kind = type(value)
        if value is None or kind in (str, bool):
            if kind is str:
                _need(len(value) <= MAX_JSON_BYTES, "sample string bound exceeded")
            return value
        if kind in (int, float):
            _number(value)
            return value
        if kind in (list, tuple):
            return [check(child, depth + 1) for child in value]
        if kind is dict:
            _need(all(type(key) is str for key in value), "plain sample mapping required")
            return {key: check(child, depth + 1) for key, child in value.items()}
        _need(dataclasses.is_dataclass(value) and not isinstance(value, type)
              and kind.__module__ in {legal_sample_type.__module__,
                                     "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir"},
              "unsupported sample object ABI")
        return {field.name: check(object.__getattribute__(value, field.name), depth + 1)
                for field in dataclasses.fields(value)}

    # Existing serializers may sort formula/frame lists, but the readout uses
    # their original order for transition features. Preserve all field/list
    # order in the diagnostic identity and closing witness without invoking
    # any serializer or custom copy hook on caller objects.
    return _plain(check(sample, 0))


def _check_head_labels(state_values, labels, modal_families):
    for name in _HEAD_SCALES:
        buckets = state_values[name]
        _need(type(buckets) is dict, "checkpoint head mapping required")
        rows = [buckets] if name == "legal_ir_view_logits" else buckets.values()
        for row in rows:
            _need(type(row) is dict, "checkpoint logit row required")
            allowed = set(labels)
            if name == "feature_family_logits":
                allowed.update(modal_families)
            _need(set(row) <= allowed, "unsupported checkpoint view label in " + name)
    # Sample-memory labels are ignored by this adapter, but may only use the
    # same finite declared namespaces. Their values never enter prediction.
    for row in state_values["family_logits"].values():
        _need(set(row) <= set(labels) | set(modal_families), "unsupported sample-memory view label")
    for name in ("legal_ir_view_embedding_weights", "legal_ir_view_family_logits"):
        _need(set(state_values[name]) <= set(labels), "unsupported checkpoint view key in " + name)
    for name in ("semantic_slot_legal_ir_view_embedding_weights", "family_legal_ir_view_embedding_weights",
                 "family_semantic_slot_legal_ir_view_embedding_weights", "semantic_slot_legal_ir_view_family_logits"):
        _need(all("||" in key and key.rsplit("||", 1)[1] in labels for key in state_values[name]),
              "unsupported checkpoint composite view key in " + name)


def _cache_snapshot(value):
    """Observe ordinary feature caches without executing user copy hooks."""
    count = 0

    def visit(item, depth):
        nonlocal count
        count += 1
        _need(count <= MAX_NODES and depth <= MAX_DEPTH, "cache traversal bound exceeded")
        kind = type(item)
        if item is None or kind in (str, bool):
            return item
        if kind in (int, float):
            _number(item)
            return item
        if kind in (list, tuple, set, frozenset):
            children = [visit(child, depth + 1) for child in item]
            if kind in (set, frozenset):
                children.sort(key=_wire)
            return [kind.__name__, children]
        _need(kind is dict, "unsupported mutable feature-cache value")
        pairs = [[visit(key, depth + 1), visit(child, depth + 1)] for key, child in item.items()]
        pairs.sort(key=lambda pair: _wire(pair[0]))
        return ["dict", pairs]

    result = visit(value, 0)
    _need(len(_wire(result)) <= MAX_STATE_BYTES, "feature-cache byte bound exceeded")
    return result


def evaluate_fixed_view_vocabulary(model, samples, targets, *, profile,
                                   expected_profile_sha256, expected_state_identity,
                                   checkpoint_context, expected_targets_sha256):
    """Read the existing fixed-lane head on an isolated Python/codec-free copy.

    Checkpoint context is an explicit caller declaration, not authenticated
    metadata inferred from legacy vectors or a file read by this function.
    No compiler, training step, acceptance gate, or new disk cache is invoked.
    Copied existing target/loss context is explicitly hash-bound because it
    affects feature selection. Shared trusted-module monkeypatching is not an
    authority model.
    """
    detached_targets = _plain(targets)
    _need(type(detached_targets) is list and 0 < len(detached_targets) <= MAX_ROWS,
          "bounded nonempty target list required")
    context = _context(checkpoint_context)
    _need(_digest(detached_targets) == _sha(expected_targets_sha256), "independent targets pin differs")
    _sha(expected_state_identity)
    checked = _checked_profile(profile, expected_profile_sha256)
    _need(type(samples) in (list, tuple) and 0 < len(samples) <= MAX_ROWS,
          "bounded nonempty samples required")
    _need(_ADAPTER_BUSY.acquire(blocking=False), "diagnostic adapter already active")
    try:
        sources = _source_rows(_MODEL_SOURCES)
        from . import modal_autoencoder as autoencoder_owner
        from .modal_autoencoder import AdaptiveModalAutoencoder, ModalAutoencoderTrainingState
        from .legal_samples import LegalSample
        from .modal_registry import ModalLogicFamily

        _need(Path(autoencoder_owner.__file__).resolve() == _PACKAGE / _MODEL_SOURCES[0],
              "model owner imported from a different repository")
        _need(type(model) is AdaptiveModalAutoencoder and type(model.state) is ModalAutoencoderTrainingState,
              "exact supported autoencoder and state types required")
        _need(model.compute_backend == "python" and model._torch is None and model.compute_device is None,
              "Python-only diagnostic adapter required")
        _need(model.max_codec_feature_keys == 0 and model.feature_codec is None,
              "codec-free diagnostic profile required")
        _need(model._legacy_embedding_adapters is None, "legacy adapter plugins are unsupported")
        original_state = model.state
        _need(original_state._active_state_transaction is None, "active state transaction unsupported")
        token = original_state.state_revision_token()
        _need(original_state.state_identity() == expected_state_identity, "independent state identity differs")
        config = _model_configuration(model)
        _need(config["modal_families"] and len(set(config["modal_families"])) == len(config["modal_families"])
              and set(config["modal_families"]) <= {family.value for family in ModalLogicFamily},
              "unsupported modal-family declaration")
        _need(set(config["modal_families"]).isdisjoint(checked["labels"]), "modal and view namespaces overlap")
        _need(all(_number(config[name]) >= 0.0 for name in set(_HEAD_SCALES.values()))
              and _number(config["feature_logit_clip"]) >= 0.0
              and type(config["feature_activity_reference"]) is int and config["feature_activity_reference"] >= 8,
              "unsupported head scale or activity configuration")
        values = _plain(original_state.to_dict(), maximum=MAX_STATE_BYTES)
        _need(values["architecture_version"] in autoencoder_owner.MODAL_AUTOENCODER_COMPATIBLE_ARCHITECTURE_VERSIONS,
              "unsupported checkpoint architecture")
        _check_head_labels(values, checked["labels"], config["modal_families"])
        for name, vectors in values.items():
            if name.endswith("embedding_weights") or name == "decoded_embeddings":
                _need(all(type(vector) is list and len(vector) == context["embedding_dimensions"]
                          for vector in vectors.values()), "checkpoint vector dimension differs: " + name)
        sample_refs = tuple(samples)
        sample_values, sample_bytes = [], 0
        for sample in sample_refs:
            observed_sample = _sample_value(sample, LegalSample)
            sample_bytes += len(_wire(observed_sample))
            _need(sample_bytes <= MAX_STATE_BYTES, "aggregate sample byte bound exceeded")
            sample_values.append(observed_sample)
        _need(len(detached_targets) == len(sample_refs), "complete ordered targets required")
        ids = []
        for sample, target in zip(sample_refs, detached_targets, strict=True):
            _need(type(target) is dict and set(target) == {"sample_id", "distribution"}, "closed target row required")
            sample_id = _text(sample.sample_id)
            _need(target["sample_id"] == sample_id and sample_id not in ids, "ordered unique sample/target IDs required")
            ids.append(sample_id)
            _distribution(target["distribution"], checked["labels"])
            _need(len(sample.embedding_vector) == context["embedding_dimensions"], "declared sample dimension differs")
            _need(context["encoder_model"] is None or sample.embedding_model == context["encoder_model"],
                  "declared sample encoder differs")
        attrs = dict(vars(model))
        cache_refs = {name: attrs[name] for name in _CACHE_FIELDS}
        cache_values = {name: _cache_snapshot(value) for name, value in cache_refs.items()}
        target_cache = _plain(attrs["_legal_ir_view_target_cache"])
        loss_cache = _plain(attrs["_legal_ir_loss_target_cache"])
        evaluator_context = {"view_targets": target_cache, "loss_targets": loss_cache}
        for distribution in target_cache.values():
            _distribution(distribution, checked["labels"])
        original_plugins = {name: attrs[name] for name in ("feature_codec", "_torch", "_legacy_embedding_adapters")}

        def current():
            _need(model.state is original_state and set(vars(model)) == set(attrs), "model/state object substituted")
            _need(original_state.is_current_state_revision(token), "caller state revision changed")
            _need(original_state._active_state_transaction is None, "state transaction opened during diagnostic")
            _need(original_state.state_identity() == expected_state_identity
                  and _plain(original_state.to_dict(), maximum=MAX_STATE_BYTES) == values,
                  "caller state changed during diagnostic")
            _need(_model_configuration(model) == config, "model configuration changed")
            _need(all(vars(model)[name] is value for name, value in cache_refs.items()), "caller cache object substituted")
            _need(all(_cache_snapshot(vars(model)[name]) == value for name, value in cache_values.items()),
                  "caller cache contents changed")
            _need(all(vars(model)[name] is value for name, value in original_plugins.items()),
                  "model plugin object substituted")
            _need(len(samples) == len(sample_refs) and all(left is right for left, right in zip(samples, sample_refs))
                  and [_sample_value(sample, LegalSample) for sample in sample_refs] == sample_values,
                  "caller samples changed during diagnostic")
            _need(_plain(targets) == detached_targets and _context(checkpoint_context) == context,
                  "caller target or checkpoint declaration changed")
            _need(_source_rows(_MODEL_SOURCES) == sources
                  and checked == build_bridge_contract_view_profile(), "diagnostic producer changed")

        current()
        isolated = object.__new__(AdaptiveModalAutoencoder)
        isolated.__dict__.update(attrs)
        isolated.state = original_state.copy()
        isolated._sample_feature_cache = {}
        isolated._legal_ir_view_family_candidates_cache = None
        isolated._legal_ir_view_target_cache = copy.deepcopy(target_cache)
        isolated._legal_ir_loss_target_cache = copy.deepcopy(loss_cache)
        isolated._cuda_resident_projection_state = None
        isolated._cuda_resident_proof_state = None
        isolated._cuda_residency_reports = []
        isolated_samples = copy.deepcopy(sample_refs)
        rows = []
        for sample, target in zip(isolated_samples, detached_targets, strict=True):
            logits = isolated._legal_ir_view_logits_for(sample, checked["labels"], use_sample_memory=False)
            rows.append({"sample_id": sample.sample_id, "logits": logits,
                         "target_distribution": target["distribution"]})
            current()
        result = _score(_plain(rows), checked, expected_profile_sha256)
        activity = {name: {"scale": config[scale], "active": config[scale] > 0.0,
                           "stored_rows": len(values[name])}
                    for name, scale in _HEAD_SCALES.items()}
        result.update({"state_identity": expected_state_identity, "state_revision": token.revision,
                       "state_schema_version": values["schema_version"],
                       "architecture_version": values["architecture_version"],
                       "checkpoint_context": context, "checkpoint_context_sha256": _digest(context),
                       "checkpoint_context_is_caller_declaration": True,
                       "checkpoint_file_independently_authenticated": False,
                       "targets_sha256": expected_targets_sha256, "samples_sha256": _digest(sample_values),
                       "model_configuration": config, "model_configuration_sha256": _digest(config),
                       "evaluator_context_sha256": _digest(evaluator_context),
                       "head_activity": activity, "producer_sources": sources,
                       "caller_state_unchanged": True, "caller_caches_untouched": True})
        current()
        return result
    finally:
        _ADAPTER_BUSY.release()


__all__ = [
    "ViewVocabularyDiagnosticError", "build_bridge_contract_view_profile",
    "view_profile_sha256", "score_fixed_view_logits", "evaluate_fixed_view_vocabulary",
]

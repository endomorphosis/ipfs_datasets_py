"""Bounded, training-only cross-modal retrieval for LegalIR experiments.

Two linear encoders align supplied 384-dimensional source/formal embeddings.
This adapts contrastive retrieval from ProofBridge; it has no proof DAG encoder,
does not generate formulas, and grants no semantic or proof authority. Callers
own embedding provenance and must keep evaluation targets out of the index.
"""
from __future__ import annotations

import copy
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from . import legal_formula_codec as codec

SCHEMA = "legal-joint-retrieval-checkpoint/v1"
ARCHITECTURE = "two-linear-normalized-contrastive-retrievers/v1"
INPUT_DIMENSION = 384
MAX_ROWS = 1024
MAX_BYTES = 16 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TRAIN_FIELDS = {"id", "source_text", "source_sha256", "family_group", "embedding",
                 "canonical_ir", "formal_embedding"}
_QUERY_FIELDS = {"id", "source_text", "family_group", "embedding"}
_FALSE = {"qualified": False, "admitted": False, "proof_authority": False,
          "semantic_correctness_verified": False, "target_access": False,
          "teacher_forcing": False, "training_executed": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def checkpoint_digest(value):
    """Canonical JSON content digest; a saved file has its own byte digest."""
    return hashlib.sha256(_raw(value)).hexdigest()


def _capture_implementation():
    from ...logic.legal_ir import canonical_contracts
    from . import legal_ir_grammar_decoder
    return {"scope": "listed_files_only", "files": {
        "legal_joint_retrieval.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "legal_formula_codec.py": hashlib.sha256(Path(codec.__file__).read_bytes()).hexdigest(),
        "canonical_contracts.py": hashlib.sha256(Path(canonical_contracts.__file__).read_bytes()).hexdigest(),
        "legal_ir_grammar_decoder.py": hashlib.sha256(Path(legal_ir_grammar_decoder.__file__).read_bytes()).hexdigest(),
    }}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    value = _capture_implementation()
    _require(value == _IMPLEMENTATION_AT_IMPORT, "retrieval implementation changed since import")
    return value


def _text(value, name, maximum=16384):
    _require(type(value) is str and 0 < len(value.strip()) <= maximum, "invalid " + name)
    return value


def _vector(value):
    _require(type(value) is list and len(value) == INPUT_DIMENSION,
             "embedding must contain exactly 384 numbers")
    _require(all(type(x) in (int, float) and math.isfinite(x) and abs(x) <= 1e6 for x in value),
             "embedding must contain bounded finite numbers")
    _require(any(x != 0 for x in value), "embedding must have nonzero norm")
    return list(value)


def _training_rows(rows):
    _require(type(rows) in (list, tuple) and 3 <= len(rows) <= MAX_ROWS,
             "training index requires 3 to 1024 rows")
    seen_ids, seen_sources, seen_targets, modalities = set(), set(), set(), set()
    result = []
    for row in rows:
        _require(type(row) is dict and set(row) == _TRAIN_FIELDS, "closed training row schema required")
        identifier = _text(row["id"], "id", 512)
        source = _text(row["source_text"], "source_text")
        _text(row["family_group"], "family_group", 512)
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        _require(row["source_sha256"] == source_hash, "source hash differs")
        rule = codec._rule(row["canonical_ir"])
        modalities.add(rule["modality"])
        source_key = " ".join(source.casefold().split())
        target_key = checkpoint_digest(row["canonical_ir"])
        _require(identifier not in seen_ids, "duplicate training id")
        _require(source_key not in seen_sources, "duplicate training source")
        _require(target_key not in seen_targets, "duplicate training target")
        seen_ids.add(identifier)
        seen_sources.add(source_key)
        seen_targets.add(target_key)
        result.append({**copy.deepcopy(row), "embedding": _vector(row["embedding"]),
                       "formal_embedding": _vector(row["formal_embedding"])})
    _require(modalities == {"O", "P", "F"}, "training requires O/P/F negatives in the full batch")
    # The order is part of the training/index contract, not silently normalized.
    return result


def _queries(rows):
    _require(type(rows) in (list, tuple) and 0 < len(rows) <= MAX_ROWS,
             "query batch requires 1 to 1024 rows")
    result, identifiers = [], set()
    for row in rows:
        _require(type(row) is dict and set(row) == _QUERY_FIELDS, "closed target-free query schema required")
        identifier = _text(row["id"], "query id", 512)
        _require(identifier not in identifiers, "duplicate query id")
        identifiers.add(identifier)
        _text(row["source_text"], "source_text")
        _text(row["family_group"], "family_group", 512)
        result.append({**row, "embedding": _vector(row["embedding"])})
    return result


def _config(torch, *, seed, joint_dimension, learning_rate, temperature):
    _require(type(seed) is int and 0 <= seed < 2**31, "invalid seed")
    _require(type(joint_dimension) is int and 8 <= joint_dimension <= 128, "invalid joint dimension")
    for name, value, maximum in (("learning_rate", learning_rate, .1), ("temperature", temperature, 1)):
        _require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= maximum,
                 "invalid " + name)
    return {"architecture": ARCHITECTURE, "input_dimension": INPUT_DIMENSION,
            "joint_dimension": joint_dimension, "seed": seed,
            "learning_rate": float(learning_rate), "temperature": float(temperature),
            "device": "cpu", "dtype": "float32", "torch_version": str(torch.__version__),
            "loss": "symmetric_infonce_full_batch", "input_normalization": "l2",
            "output_normalization": "l2", "optimizer": "adam_fresh_no_resume"}


def _model(torch, config):
    class JointProjection(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.source = torch.nn.Linear(INPUT_DIMENSION, config["joint_dimension"])
            self.formal = torch.nn.Linear(INPUT_DIMENSION, config["joint_dimension"])

        def forward(self, source, formal):
            normalize = torch.nn.functional.normalize
            return (normalize(self.source(normalize(source, dim=-1)), dim=-1),
                    normalize(self.formal(normalize(formal, dim=-1)), dim=-1))

    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config["seed"])
        return JointProjection()


def _state(model):
    return {key: value.detach().cpu().tolist() for key, value in model.state_dict().items()}


def _restore_legacy(checkpoint, *, source_profile=None):
    import torch
    _require(type(checkpoint) is dict and set(checkpoint) == {
        "schema", "config", "implementation", "index_sha256", "training_rows",
        "training_modalities", "model_state", "progress"}, "closed retrieval checkpoint required")
    _require(checkpoint["schema"] == SCHEMA, "retrieval checkpoint schema differs")
    _require(_legacy_implementation_compatible(checkpoint, source_profile), "retrieval source pins differ")
    config = checkpoint["config"]
    _require(type(config) is dict and all(key in config for key in (
        "seed", "joint_dimension", "learning_rate", "temperature")), "retrieval configuration missing")
    expected = _config(torch, **{key: config[key] for key in (
        "seed", "joint_dimension", "learning_rate", "temperature")})
    _require(config == expected and _raw(config) == _raw(expected), "retrieval config/runtime differs")
    _require(type(checkpoint["index_sha256"]) is str and _SHA.fullmatch(checkpoint["index_sha256"]),
             "invalid index digest")
    _require(type(checkpoint["training_rows"]) is int and 3 <= checkpoint["training_rows"] <= MAX_ROWS,
             "invalid training row count")
    counts = checkpoint["training_modalities"]
    _require(type(counts) is dict and set(counts) == {"O", "P", "F"}
             and all(type(value) is int and value > 0 for value in counts.values())
             and sum(counts.values()) == checkpoint["training_rows"], "invalid training modality counts")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"optimizer_steps"}
             and type(progress["optimizer_steps"]) is int and 0 <= progress["optimizer_steps"] <= 10000,
             "invalid retrieval progress")
    model = _model(torch, config)
    state = checkpoint["model_state"]
    _require(type(state) is dict and set(state) == set(model.state_dict()), "retrieval parameter names differ")
    restored = {}
    for key, template in model.state_dict().items():
        try:
            value = torch.tensor(state[key], dtype=torch.float32)
        except (TypeError, ValueError, RuntimeError) as error:
            raise ValueError("invalid retrieval tensor") from error
        _require(value.shape == template.shape and bool(torch.isfinite(value).all()),
                 "retrieval parameter shape/values differ")
        _require(_raw(value.tolist()) == _raw(state[key]), "retrieval tensor must preserve exact float32 values")
        restored[key] = value
    model.load_state_dict(restored)
    model.eval()
    return torch, model


def validate_checkpoint(checkpoint, *, source_profile=None):
    _restore(checkpoint, source_profile=source_profile)


def train_retriever(training_rows, *, steps=600, seed=2718, learning_rate=.003,
                    joint_dimension=64, temperature=.1):
    """Fit once on the entire training index; no evaluation or tuning targets."""
    import torch
    _require(type(steps) is int and 0 <= steps <= 10000, "steps must be an integer in [0, 10000]")
    rows = _training_rows(training_rows)
    config = _config(torch, seed=seed, joint_dimension=joint_dimension,
                     learning_rate=learning_rate, temperature=temperature)
    pins = _implementation()
    model = _model(torch, config)
    initial = _state(model)
    source = torch.tensor([row["embedding"] for row in rows], dtype=torch.float32)
    formal = torch.tensor([row["formal_embedding"] for row in rows], dtype=torch.float32)
    labels = torch.arange(len(rows))
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    losses, started = [], time.monotonic()
    model.train()
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        source_projected, formal_projected = model(source, formal)
        similarity = source_projected @ formal_projected.T / temperature
        loss = .5 * (torch.nn.functional.cross_entropy(similarity, labels)
                     + torch.nn.functional.cross_entropy(similarity.T, labels))
        _require(bool(torch.isfinite(loss)), "nonfinite retrieval loss")
        loss.backward()
        _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all())
                     for parameter in model.parameters()), "nonfinite or missing retrieval gradients")
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5, error_if_nonfinite=True)
        optimizer.step()
        losses.append(float(loss.detach()))
    model.eval()
    with torch.no_grad():
        source_projected, formal_projected = model(source, formal)
        scores = source_projected @ formal_projected.T
        training_recall = float((scores.argmax(dim=-1) == labels).float().mean())
    weights = _state(model)
    _require(pins == _implementation(), "retrieval implementation changed during training")
    checkpoint = {"schema": SCHEMA, "config": config, "implementation": pins,
        "index_sha256": checkpoint_digest(rows), "training_rows": len(rows),
        "training_modalities": {modality: sum(row["canonical_ir"]["rules"][0]["modality"] == modality
                                             for row in rows) for modality in ("O", "P", "F")},
        "model_state": weights, "progress": {"optimizer_steps": steps}}
    validate_checkpoint(checkpoint)
    report = {"schema": "legal-joint-retrieval-training/v1", "optimizer_steps": steps,
        "full_batch_rows": len(rows), "losses": losses, "elapsed_seconds": time.monotonic() - started,
        "training_recall_at_1": training_recall, "recall_scope": "resubstitution_on_training_index_only",
        "changed_parameter_names": [key for key in weights if weights[key] != initial[key]],
        "index_sha256": checkpoint["index_sha256"], "checkpoint_sha256": checkpoint_digest(checkpoint),
        "embedding_dimension": INPUT_DIMENSION, "joint_projection_dimension": joint_dimension,
        "evaluation_targets_used": False, "proofbridge_reproduction": False,
        **_FALSE, "training_executed": steps > 0, "target_access": True,
        "target_access_scope": "training_pairs_only", "query_target_access": False}
    return {"checkpoint": checkpoint, "report": report}


class LegalJointRetriever:
    """Frozen index; query interface cannot accept a formal target or embedding."""
    def __init__(self, training_rows, checkpoint, *, source_profile=None):
        _require(type(checkpoint) is dict and checkpoint.get("schema") == SCHEMA,
                 "legacy one-to-one retrieval requires a v1 checkpoint")
        self._source_profile = copy.deepcopy(source_profile)
        self._rows = _training_rows(training_rows)
        self._checkpoint = copy.deepcopy(checkpoint)
        self._torch, self._model = _restore(checkpoint, source_profile=self._source_profile)
        _require(checkpoint_digest(self._rows) == checkpoint["index_sha256"], "training index digest differs")
        _require(len(self._rows) == checkpoint["training_rows"], "training index count differs")
        self.index_sha256 = checkpoint["index_sha256"]
        self._checkpoint_sha256 = checkpoint_digest(checkpoint)
        self._state_sha256 = checkpoint_digest(_state(self._model))
        self._formal = self._torch.tensor([row["formal_embedding"] for row in self._rows], dtype=self._torch.float32)

    @property
    def checkpoint(self):
        return copy.deepcopy(self._checkpoint)

    def _integrity(self):
        _require(_legacy_implementation_compatible(self._checkpoint, self._source_profile), "retrieval source pins changed")
        _require(checkpoint_digest(self._checkpoint) == self._checkpoint_sha256, "retrieval checkpoint mutated")
        _require(checkpoint_digest(self._rows) == self.index_sha256, "retrieval index mutated")
        _require(checkpoint_digest(_state(self._model)) == self._state_sha256, "retrieval model mutated")
        _require(self._torch.equal(self._formal, self._torch.tensor(
            [row["formal_embedding"] for row in self._rows], dtype=self._torch.float32)), "formal index tensor mutated")

    def _retrieve_core(self, query_rows, *, mode="joint", top_k=3, exclude_same_family=True):
        """Return softmax-weighted original formal vectors, never query targets.

        The same source/id is always excluded. Family exclusion additionally
        removes every training exemplar in the query's declared value family.
        Random ranking uses hashed query/index identities and uniform weights.
        """
        _require(mode in ("raw", "joint", "random"), "unsupported retrieval mode")
        _require(type(top_k) is int and 1 <= top_k <= 16, "top_k must be in [1, 16]")
        _require(type(exclude_same_family) is bool, "exclude_same_family must be boolean")
        queries = _queries(query_rows)
        self._integrity()
        torch = self._torch
        source = torch.tensor([row["embedding"] for row in queries], dtype=torch.float32)
        with torch.no_grad():
            if mode == "joint":
                source_projected, formal_projected = self._model(source, self._formal)
            else:
                source_projected = torch.nn.functional.normalize(source, dim=-1)
                formal_projected = torch.nn.functional.normalize(self._formal, dim=-1)
            similarities = source_projected @ formal_projected.T
        result = []
        for query_index, query in enumerate(queries):
            source_hash = hashlib.sha256(query["source_text"].encode("utf-8")).hexdigest()
            source_key = " ".join(query["source_text"].casefold().split())
            eligible = [index for index, row in enumerate(self._rows)
                if row["id"] != query["id"] and " ".join(row["source_text"].casefold().split()) != source_key
                and (not exclude_same_family or row["family_group"] != query["family_group"])]
            _require(len(eligible) >= top_k, "insufficient eligible training rows after exclusions")
            if mode == "random":
                ranked = sorted(eligible, key=lambda index: checkpoint_digest([
                    self._checkpoint["config"]["seed"], query["id"], source_hash, self.index_sha256,
                    self._rows[index]["id"]]))
            else:
                ranked = sorted(eligible, key=lambda index: (-float(similarities[query_index, index]),
                                                             self._rows[index]["id"]))
            selected = ranked[:top_k]
            scores = [float(similarities[query_index, index]) for index in selected]
            weights = (torch.full((top_k,), 1 / top_k) if mode == "random" else
                       torch.softmax(torch.tensor(scores) / self._checkpoint["config"]["temperature"], dim=0))
            context = (self._formal[selected] * weights[:, None]).sum(dim=0).tolist()
            result.append({"id": query["id"], "source_sha256": source_hash,
                "context": context, "context_sha256": checkpoint_digest(context),
                "retrieved_ids": [self._rows[index]["id"] for index in selected], "scores": scores,
                "weights": weights.tolist(), "index_sha256": self.index_sha256,
                "checkpoint_sha256": self._checkpoint_sha256, "mode": mode,
                "excluded_same_family": exclude_same_family, "eligible_rows": len(eligible),
                "index_scope": "caller_supplied_training_rows_only", "context_dimension": INPUT_DIMENSION,
                "query_target_access": False, "training_target_exemplars_accessed": True, **_FALSE})
        self._integrity()
        return {"schema": "legal-joint-retrieval-result/v1", "rows": result,
                "index_sha256": self.index_sha256, "mode": mode,
                "query_target_access": False, "training_target_exemplars_accessed": True, **_FALSE}



    @property
    def runtime_source_profile(self):
        """Separate runtime identity; the historical checkpoint is unchanged."""
        if self._source_profile is not None:
            _require(_legacy_implementation_compatible(self._checkpoint, self._source_profile),
                     "selected legacy runtime source profile changed")
            return copy.deepcopy(self._source_profile)
        return {"schema": "legal-joint-retrieval-runtime-source-profile/v1",
            "generation": "current_exact_source", "producer_implementation": copy.deepcopy(self._checkpoint["implementation"]),
            "runtime_implementation": _implementation(), "legal_admission": False}

    def retrieve(self, query_rows, *, mode="joint", top_k=3, exclude_same_family=True):
        result = self._retrieve_core(query_rows, mode=mode, top_k=top_k, exclude_same_family=exclude_same_family)
        if self._source_profile is not None:
            result["runtime_source_profile"] = self.runtime_source_profile
        return result


def save_checkpoint(checkpoint, path, *, source_profile=None):
    """Create a new JSON artifact and return its exact file-byte SHA-256."""
    validate_checkpoint(checkpoint, source_profile=source_profile)
    payload = _raw(checkpoint) + b"\n"
    _require(len(payload) <= MAX_BYTES, "retrieval checkpoint exceeds byte bound")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)
    return hashlib.sha256(payload).hexdigest()


def load_checkpoint(path, expected_sha256=None, *, source_profile=None):
    """Load bounded JSON only; optional digest binds exact file bytes."""
    target = Path(path)
    details = target.lstat()
    _require(stat.S_ISREG(details.st_mode) and 0 < details.st_size <= MAX_BYTES,
             "retrieval checkpoint must be a bounded regular file")
    payload = target.read_bytes()
    _require(len(payload) == details.st_size, "retrieval file changed during read")
    if expected_sha256 is not None:
        _require(type(expected_sha256) is str and _SHA.fullmatch(expected_sha256), "invalid expected digest")
        _require(hashlib.sha256(payload).hexdigest() == expected_sha256, "retrieval file digest differs")

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("nonfinite JSON constant: " + value)

    checkpoint = json.loads(payload, object_pairs_hook=pairs, parse_constant=invalid_constant)
    validate_checkpoint(checkpoint, source_profile=source_profile)
    return checkpoint


# This is an opt-in training asset. Its reviewed rectangular endpoint index is
# intentionally distinct from the legacy one-to-one LegalJointRetriever index.
REVIEWED_SCHEMA = "legal-joint-retrieval-checkpoint/v2"
REVIEWED_ARCHITECTURE = "two-linear-normalized-reviewed-masked-retrievers/v2"
REVIEWED_MAX_ROWS = 128


def _reviewed_owners():
    from ...logic.formalization.autoencoder import alignment_masked_contrastive as objective
    from ...logic.formalization.autoencoder import alignment_relation_mask_handoff as handoff
    from ...logic.formalization.autoencoder import alignment_relation_declarations as declarations
    from ...logic.autoformal import legal_norm_content_adjudication_v1 as admission
    _require(callable(getattr(handoff, "compile_reviewed_train_relation_masks_v2", None)),
             "the canonical reviewed relation handoff v2 is required")
    return objective, handoff, declarations, admission


def _reviewed_implementation():
    owners = _reviewed_owners()
    result = {"legacy_numerical_owner": _implementation(), "reviewed_owners": {}}
    for module in owners:
        path = Path(module.__file__).resolve()
        result["reviewed_owners"][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _reviewed_config(torch, **values):
    _require(torch.get_default_dtype() == torch.float32, "reviewed retrieval requires the float32 profile")
    result = _config(torch, **values)
    result.update(architecture=REVIEWED_ARCHITECTURE,
        loss="symmetric_masked_multi_positive_contrastive/v1",
        relation_scope="full_canonical_reviewed_handoff_replay/v2")
    return result


def _reviewed_arrays(handoff):
    """Check a numerical asset's internal layout, without granting review authority."""
    _, owner, _, admission = _reviewed_owners()
    _require(type(handoff) is dict and len(_raw(handoff)) <= MAX_BYTES // 2,
             "bounded complete reviewed training handoff required")
    _require(handoff.get("schema") == owner.REVIEWED_SCHEMA
             and handoff.get("status") == "reviewed_objective_mask_ready"
             and handoff.get("reviewed_objective_mask_ready") is True
             and handoff.get("reviewed_pair_labels_authenticated") is True,
             "complete reviewed relation objective is not ready")
    body = {key: value for key, value in handoff.items() if key != "content_sha256"}
    _require(handoff.get("content_sha256") == admission.norm_content_adjudication_sha256(body),
             "reviewed handoff content digest differs")
    source, formal = handoff.get("source_vectors"), handoff.get("formal_vectors")
    _require(type(source) is list and type(formal) is list
             and 1 <= len(source) <= REVIEWED_MAX_ROWS and 1 <= len(formal) <= REVIEWED_MAX_ROWS,
             "reviewed rectangular lanes require 1 to 128 rows per side")
    source, formal = [_vector(row) for row in source], [_vector(row) for row in formal]
    _require(handoff.get("representation_dimension") == INPUT_DIMENSION
             and handoff.get("source_row_count") == len(source)
             and handoff.get("formal_row_count") == len(formal),
             "reviewed native384 endpoint populations differ")
    positive, negative = handoff.get("objective_positive_mask"), handoff.get("objective_permitted_negative_mask")
    for name, mask in (("positive", positive), ("permitted negative", negative)):
        _require(type(mask) is list and len(mask) == len(source)
                 and all(type(row) is list and len(row) == len(formal)
                         and all(type(value) is bool for value in row) for row in mask),
                 "reviewed " + name + " mask has an invalid rectangular layout")
    _require(all(not (positive[i][j] and negative[i][j]) for i in range(len(source))
                 for j in range(len(formal))), "reviewed positive/negative masks overlap")
    _require(all(any(row) for row in positive)
             and all(any(positive[i][j] for i in range(len(source))) for j in range(len(formal))),
             "reviewed rows and columns require positive coverage")
    return source, formal, copy.deepcopy(positive), copy.deepcopy(negative)


def _restore_reviewed(checkpoint):
    """Restore a historical numerical asset; this does not re-admit its labels."""
    _require(type(checkpoint) is dict and set(checkpoint) == {
        "schema", "config", "implementation", "training_handoff", "training_handoff_sha256",
        "initial_model_state_sha256", "model_state", "progress"}
        and checkpoint["schema"] == REVIEWED_SCHEMA, "closed reviewed retrieval checkpoint required")
    _require(checkpoint["implementation"] == _reviewed_implementation(),
             "reviewed retrieval source pins differ")
    _reviewed_arrays(checkpoint["training_handoff"])
    _require(checkpoint["training_handoff_sha256"] == checkpoint_digest(checkpoint["training_handoff"]),
             "reviewed training handoff identity differs")
    config = checkpoint["config"]
    _require(type(config) is dict and all(key in config for key in (
        "seed", "joint_dimension", "learning_rate", "temperature")), "reviewed retrieval configuration missing")
    import torch
    expected = _reviewed_config(torch, **{key: config[key] for key in (
        "seed", "joint_dimension", "learning_rate", "temperature")})
    _require(config == expected and _raw(config) == _raw(expected), "reviewed config/runtime differs")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"optimizer_steps", "optimizer_state_retained"}
             and type(progress["optimizer_steps"]) is int and 0 <= progress["optimizer_steps"] <= 10000
             and progress["optimizer_state_retained"] is False, "invalid reviewed optimizer progress")
    with torch.device("cpu"):
        model = _model(torch, config)
    _require(checkpoint["initial_model_state_sha256"] == checkpoint_digest(_state(model)),
             "reviewed initialization identity differs")
    state = checkpoint["model_state"]
    _require(type(state) is dict and set(state) == set(model.state_dict()), "reviewed parameter names differ")
    restored = {}
    for key, template in model.state_dict().items():
        try:
            value = torch.tensor(state[key], dtype=torch.float32, device="cpu")
        except (TypeError, ValueError, RuntimeError) as error:
            raise ValueError("invalid reviewed retrieval tensor") from error
        _require(value.shape == template.shape and bool(torch.isfinite(value).all()),
                 "reviewed parameter shape/values differ")
        _require(_raw(value.tolist()) == _raw(state[key]), "reviewed tensor must preserve exact float32 values")
        restored[key] = value
    model.load_state_dict(restored)
    model.eval()
    return torch, model


def _restore(checkpoint, *, source_profile=None):
    if type(checkpoint) is dict and checkpoint.get("schema") == REVIEWED_SCHEMA:
        _require(source_profile is None, "a legacy source port cannot authorize a reviewed v2 asset")
        return _restore_reviewed(checkpoint)
    return _restore_legacy(checkpoint, source_profile=source_profile)


def train_reviewed_retriever(preparation, registry, policy, reviews, *,
        expected_preparation_sha256, preparation_inputs, expected_registry_sha256,
        expected_policy_sha256, expected_reviews_sha256, at_time_utc,
        observed_artifact_sha256s, observed_pins, evidence_artifacts, current_endpoint_observations,
        steps=0, seed=2718, learning_rate=.003, joint_dimension=64, temperature=.1):
    """Fit the existing projections using a complete canonical reviewed replay.

    Callers own the existing resource admission for numerical execution. Mask
    preparation confers no runtime permission. This function creates no lease,
    model-provider call, legal review, gold label, proof or corpus admission.
    Its checkpoint preserves the historical decision; reuse needs current
    eligibility checks at the caller's admission/retrieval boundary.
    """
    _require(type(steps) is int and 0 <= steps <= 10000, "steps must be an integer in [0, 10000]")
    objective, owner, _, _ = _reviewed_owners()
    replay = dict(expected_preparation_sha256=expected_preparation_sha256,
        preparation_inputs=preparation_inputs, expected_registry_sha256=expected_registry_sha256,
        expected_policy_sha256=expected_policy_sha256, expected_reviews_sha256=expected_reviews_sha256,
        at_time_utc=at_time_utc, observed_artifact_sha256s=observed_artifact_sha256s,
        observed_pins=observed_pins, evidence_artifacts=evidence_artifacts,
        current_endpoint_observations=current_endpoint_observations)
    # No Torch import, model, optimizer or caller-supplied bare masks precede
    # the canonical complete replay of endpoint and independent pair reviews.
    handoff = owner.compile_reviewed_train_relation_masks_v2(preparation, registry, policy, reviews, **replay)
    source_rows, formal_rows, positive_rows, negative_rows = _reviewed_arrays(handoff)
    pins = _reviewed_implementation()
    import torch
    config = _reviewed_config(torch, seed=seed, joint_dimension=joint_dimension,
        learning_rate=learning_rate, temperature=temperature)
    with torch.device("cpu"):
        model = _model(torch, config)
    initial = _state(model)
    source = torch.tensor(source_rows, dtype=torch.float32, device="cpu")
    formal = torch.tensor(formal_rows, dtype=torch.float32, device="cpu")
    positive = torch.tensor(positive_rows, dtype=torch.bool, device="cpu")
    negative = torch.tensor(negative_rows, dtype=torch.bool, device="cpu")
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    losses, started = [], time.monotonic()
    model.train()
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        projected_source, projected_formal = model(source, formal)
        # The canonical objective is already symmetric. Call it once.
        loss = objective.masked_multi_positive_contrastive_loss(projected_source, projected_formal,
            positive_mask=positive, permitted_negative_mask=negative, temperature=temperature)
        _require(bool(torch.isfinite(loss)), "nonfinite reviewed retrieval loss")
        loss.backward()
        _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all())
                     for parameter in model.parameters()), "nonfinite or missing reviewed retrieval gradients")
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5, error_if_nonfinite=True)
        optimizer.step()
        _require(all(bool(torch.isfinite(parameter).all()) for parameter in model.parameters()),
                 "nonfinite reviewed retrieval parameters")
        losses.append(float(loss.detach()))
    model.eval()
    with torch.no_grad():
        projected_source, projected_formal = model(source, formal)
        scores = projected_source @ projected_formal.T
        allowed_scores = scores.masked_fill(~(positive | negative), -torch.inf)
        source_recall = float(positive.gather(1, allowed_scores.argmax(dim=1).unsqueeze(1)).float().mean())
        formal_recall = float(positive.gather(0, allowed_scores.argmax(dim=0).unsqueeze(0)).float().mean())
    # Fail if producer sources, supplied evidence, current observations or
    # review/purpose state changed while the numerical operation was running.
    after = owner.compile_reviewed_train_relation_masks_v2(preparation, registry, policy, reviews, **replay)
    _require(_raw(after) == _raw(handoff), "reviewed handoff changed during training")
    _require(pins == _reviewed_implementation(), "reviewed retrieval implementation changed during training")
    weights = _state(model)
    checkpoint = {"schema": REVIEWED_SCHEMA, "config": config, "implementation": pins,
        "training_handoff": copy.deepcopy(handoff), "training_handoff_sha256": checkpoint_digest(handoff),
        "initial_model_state_sha256": checkpoint_digest(initial), "model_state": weights,
        "progress": {"optimizer_steps": steps, "optimizer_state_retained": False}}
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "reviewed retrieval checkpoint exceeds byte bound")
    _, restored = _restore_reviewed(checkpoint)
    _require(_state(restored) == weights, "reviewed checkpoint restoration changed parameters")
    report = {"schema": "legal-joint-retrieval-training/v2", "optimizer_steps": steps,
        "source_rows": len(source_rows), "formal_rows": len(formal_rows), "losses": losses,
        "elapsed_seconds": time.monotonic() - started,
        "training_source_positive_recall_at_1": source_recall, "training_formal_positive_recall_at_1": formal_recall,
        "recall_scope": "reviewed_training_grid_resubstitution_only",
        "changed_parameter_names": [key for key in weights if weights[key] != initial[key]],
        "training_handoff_sha256": checkpoint["training_handoff_sha256"],
        "handoff_content_sha256": handoff["content_sha256"], "checkpoint_sha256": checkpoint_digest(checkpoint),
        "embedding_dimension": INPUT_DIMENSION, "joint_projection_dimension": joint_dimension,
        "unknown_pair_count": handoff["unknown_pair_count"],
        "analogy_retrieval_only_pair_count": handoff["analogy_retrieval_only_pair_count"],
        "no_separation_signal": not any(any(row) for row in negative_rows),
        "provenance_kind": handoff["provenance_kind"], "fixture_only": handoff["fixture_only"],
        "input_embedding_runtime_computation_proven": handoff["runtime_computation_proven"],
        "resource_admission_scope": "caller_owned_not_validated_here",
        "checkpoint_restore_verified": True, "previous_task_retention_evaluated": False,
        "heldout_evaluation_performed": False, "evaluation_targets_used": False,
        "legacy_retrieval_index_compatible": False, "proofbridge_reproduction": False,
        **_FALSE, "training_executed": steps > 0, "model_executed": True,
        "target_access": True, "target_access_scope": "reviewed_training_pairs_only", "query_target_access": False}
    return {"checkpoint": checkpoint, "report": report}


LEGACY_SOURCE_PORT_SCHEMA = "legal-joint-retrieval-selected-legacy-source-port/v1"
SELECTED_LEGACY_OWNER_SHA256 = "577698c99d0cdd2209bdaaee01b40778f46251e9e1256d7537312d6655cdcb9d"
SELECTED_LEGACY_NUMERICAL_AST_SHA256 = "32a137b51bcd1f609b1d639a80a2e58d9982aa133283ae40aa53e9ac7035caa4"


def _legacy_ast_view(value):
    if isinstance(value, ast.AST):
        return {"node": type(value).__name__, "fields": [[name, _legacy_ast_view(child)]
            for name, child in ast.iter_fields(value) if not (name == "type_params" and child == [])]}
    if isinstance(value, list):
        return [_legacy_ast_view(child) for child in value]
    return value


def _legacy_numerical_ast_identity(raw):
    """Finite selected bodies, including the exact validation-only port edits.

    This is an AST identity policy, not proof of runtime numerical equivalence
    or attestation of mutable Python globals. Full runtime source bytes and
    every other dependency/config/state pin remain separately enforced.
    """
    tree = ast.parse(raw)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LegalJointRetriever")
    methods = {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}
    new_restore_guard = ast.parse('_require(_legacy_implementation_compatible(checkpoint, source_profile), "retrieval source pins differ")').body[0]
    old_restore_guard = ast.parse('_require(checkpoint["implementation"] == _implementation(), "retrieval source pins differ")').body[0]
    new_integrity_guard = ast.parse('_require(_legacy_implementation_compatible(self._checkpoint, self._source_profile), "retrieval source pins changed")').body[0]
    old_integrity_guard = ast.parse('_require(self._checkpoint["implementation"] == _implementation(), "retrieval source pins changed")').body[0]
    added_metadata = [ast.parse('self._source_profile = copy.deepcopy(source_profile)').body[0],
        ast.parse('_require(type(checkpoint) is dict and checkpoint.get("schema") == SCHEMA, "legacy one-to-one retrieval requires a v1 checkpoint")').body[0]]
    def equal(left, right):
        return _legacy_ast_view(left) == _legacy_ast_view(right)
    def normalize(node, name):
        node = copy.deepcopy(node)
        node.name = name
        port_args = [index for index, value in enumerate(node.args.kwonlyargs) if value.arg == "source_profile"]
        if port_args:
            _require(len(port_args) == 1 and isinstance(node.args.kw_defaults[port_args[0]], ast.Constant)
                     and node.args.kw_defaults[port_args[0]].value is None, "unselected legacy signature changed")
            index = port_args[0]
            del node.args.kwonlyargs[index]
            del node.args.kw_defaults[index]
        body = []
        for statement in node.body:
            if name == "__init__" and any(equal(statement, item) for item in added_metadata):
                continue
            if equal(statement, new_restore_guard): statement = copy.deepcopy(old_restore_guard)
            if equal(statement, new_integrity_guard): statement = copy.deepcopy(old_integrity_guard)
            if name == "__init__":
                for child in ast.walk(statement):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "_restore":
                        _require(not child.keywords or (len(child.keywords) == 1 and child.keywords[0].arg == "source_profile"
                            and equal(child.keywords[0].value, ast.parse('self._source_profile', mode='eval').body)),
                            "unselected legacy restore call changed")
                        child.keywords = []
            body.append(statement)
        node.body = body
        return _legacy_ast_view(node)
    selected = {}
    for name in ("_raw", "checkpoint_digest", "_text", "_vector", "_training_rows", "_queries", "_config", "_model", "_state", "train_retriever"):
        selected[name] = normalize(functions[name], name)
    selected["_restore"] = normalize(functions.get("_restore_legacy", functions.get("_restore")), "_restore")
    for name in ("__init__", "_integrity", "retrieve"):
        actual = methods.get("_retrieve_core") if name == "retrieve" and "_retrieve_core" in methods else methods[name]
        selected["LegalJointRetriever." + name] = normalize(actual, name)
    selected_globals = {"SCHEMA", "ARCHITECTURE", "INPUT_DIMENSION", "MAX_ROWS", "MAX_BYTES", "_SHA", "_TRAIN_FIELDS", "_QUERY_FIELDS", "_FALSE"}
    selected["globals"] = [_legacy_ast_view(node) for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in selected_globals for target in node.targets)]
    return checkpoint_digest({"schema": "selected-legacy-numerical-ast/v1", "selected": selected})


def _selected_legacy_source_profile(checkpoint):
    _require(type(checkpoint) is dict and checkpoint.get("schema") == SCHEMA
             and len(_raw(checkpoint)) <= MAX_BYTES, "bounded historical v1 checkpoint required")
    current = _implementation()
    offered = checkpoint.get("implementation")
    _require(type(offered) is dict and set(offered) == set(current) == {"scope", "files"}
             and offered["scope"] == current["scope"] and type(offered["files"]) is dict
             and set(offered["files"]) == set(current["files"]), "complete selected legacy source recipe required")
    _require(offered["files"]["legal_joint_retrieval.py"] == SELECTED_LEGACY_OWNER_SHA256,
             "only the exact selected legacy retrieval source is supported")
    _require(all(digest == current["files"][name] for name, digest in offered["files"].items()
                 if name != "legal_joint_retrieval.py"), "selected legacy dependency pins differ")
    numerical = _legacy_numerical_ast_identity(Path(__file__).read_bytes())
    _require(numerical == SELECTED_LEGACY_NUMERICAL_AST_SHA256,
             "selected legacy numerical AST differs from the retained source")
    result = {"schema": LEGACY_SOURCE_PORT_SCHEMA, "checkpoint_sha256": checkpoint_digest(checkpoint),
        "historical_producer_implementation": copy.deepcopy(offered), "runtime_implementation": current,
        "selected_legacy_owner_sha256": SELECTED_LEGACY_OWNER_SHA256,
        "selected_legacy_owner_bytes": 20198, "numerical_ast_sha256": numerical,
        "numerical_ast_identity_verified": True, "runtime_numerical_parity_verified": False,
        "qualification_state": "pending_genuine_old_source_weight_and_query_parity",
        "checkpoint_rewritten": False, "legal_admission": False, "model_use_permission_granted": False}
    result["content_sha256"] = checkpoint_digest(result)
    return result


def select_legacy_source_profile(checkpoint, *, expected_checkpoint_sha256):
    """Select one exact historical recipe without opening paths or allocating tensors.

    This explicit opt-in does not qualify the runtime port or register/admit a
    model. The caller retains the original checkpoint and independently selected
    asset identity; numerical execution remains under its existing admission.
    """
    _require(type(expected_checkpoint_sha256) is str and _SHA.fullmatch(expected_checkpoint_sha256)
             and checkpoint_digest(checkpoint) == expected_checkpoint_sha256, "selected legacy checkpoint digest differs")
    return _selected_legacy_source_profile(checkpoint)


def _legacy_implementation_compatible(checkpoint, source_profile):
    current = _implementation()
    if checkpoint.get("implementation") == current:
        return source_profile is None
    if source_profile is None:
        return False
    expected = _selected_legacy_source_profile(checkpoint)
    return type(source_profile) is dict and _raw(source_profile) == _raw(expected)


class ReviewedLegalJointRetriever:
    """Untrusted structural ranking over a freshly replayed reviewed TRAIN index.

    Historical weights are not current legal permission. The caller owns model
    registry/license/resource admission and separately allowed governing
    definition/proof context. This adapter neither removes that context nor
    selects controlling authorities. Query embeddings use a pinned source-only
    lane; reference identifiers are used only to exclude examples.
    """
    def __init__(self, checkpoint, *, expected_checkpoint_sha256):
        _require(type(expected_checkpoint_sha256) is str and _SHA.fullmatch(expected_checkpoint_sha256)
                 and checkpoint_digest(checkpoint) == expected_checkpoint_sha256,
                 "selected reviewed checkpoint digest differs")
        _require(type(checkpoint) is dict and checkpoint.get("schema") == REVIEWED_SCHEMA,
                 "reviewed structural ranking requires an explicit v2 checkpoint")
        self._checkpoint = copy.deepcopy(checkpoint)
        self._checkpoint_sha256 = expected_checkpoint_sha256
        self._torch, self._model = _restore_reviewed(self._checkpoint)
        self._state_sha256 = checkpoint_digest(_state(self._model))

    def _integrity(self):
        _require(checkpoint_digest(self._checkpoint) == self._checkpoint_sha256,
                 "reviewed ranking checkpoint mutated")
        _require(self._checkpoint["implementation"] == _reviewed_implementation(),
                 "reviewed ranking source pins changed")
        _require(checkpoint_digest(_state(self._model)) == self._state_sha256,
                 "reviewed ranking parameters mutated")

    @property
    def checkpoint(self):
        return copy.deepcopy(self._checkpoint)

    def retrieve(self, query_rows, preparation, registry, policy, reviews, *,
            expected_preparation_sha256, preparation_inputs, expected_registry_sha256,
            expected_policy_sha256, expected_reviews_sha256, at_time_utc,
            observed_artifact_sha256s, observed_pins, evidence_artifacts, current_endpoint_observations,
            query_source_lane, expected_query_lane_bindings, expected_query_split,
            forbidden_reference_formal_sha256s, expected_forbidden_reference_sha256,
            top_k=3, mode="joint"):
        """Return TRAIN example vectors; never fit or consume query IR targets.

        Full current-index replay happens before projection and again before
        return. Invalid/revoked current evidence blocks the whole ledger; this
        adapter cannot fabricate a reviewed subset. New eligible indices under
        the same representation profiles require no weight retraining.
        """
        from ...logic.formalization.autoencoder import alignment_lane_bundle as lanes
        from . import legal_ir_eval_splits as splits
        _require(mode in ("raw", "joint", "random"), "unsupported reviewed ranking mode")
        _require(type(top_k) is int and 1 <= top_k <= 16, "top_k must be in [1, 16]")
        _require(expected_query_split in splits.PROTECTED_LEGAL_IR_SPLITS,
                 "one explicit protected query split is required")
        _require(type(query_rows) in (list, tuple) and 1 <= len(query_rows) <= REVIEWED_MAX_ROWS,
                 "reviewed queries require 1 to 128 rows")
        for query in query_rows:
            _require(type(query) is dict and set(query) == {"id", "source_text", "split_sample_id"},
                     "closed target-free reviewed query required")
            _text(query["id"], "query id", 512)
            _text(query["source_text"], "query source text", 262144)
            _text(query["split_sample_id"], "query split sample id", 512)
        _require(type(query_source_lane) is dict and type(query_source_lane.get("rows")) is list
                 and len(query_source_lane["rows"]) == len(query_rows), "complete ordered source query lane required")
        empty_context = {"role": "none_required", "text": "", "bindings": {}, "sha256": hashlib.sha256(b"").hexdigest()}
        for row in query_source_lane["rows"]:
            _require(type(row) is dict and type(row.get("input")) is dict
                     and row["input"].get("context") == empty_context,
                     "query lane cannot contain hidden target or undeclared context")
        _require(type(forbidden_reference_formal_sha256s) is dict
                 and set(forbidden_reference_formal_sha256s) == {query["id"] for query in query_rows},
                 "complete opaque reference exclusion population required")
        for values in forbidden_reference_formal_sha256s.values():
            _require(type(values) is list and len(values) <= REVIEWED_MAX_ROWS
                     and all(type(value) is str and _SHA.fullmatch(value) for value in values)
                     and len(values) == len(set(values)), "only opaque reference digests may be supplied")
        payload = dict(query_rows=list(query_rows), query_source_lane=query_source_lane,
            expected_query_lane_bindings=expected_query_lane_bindings,
            forbidden_reference_formal_sha256s=forbidden_reference_formal_sha256s)
        _require(len(_raw(payload)) <= MAX_BYTES, "bounded source-only query payload required")
        frozen = copy.deepcopy(payload)
        query_input_sha256 = checkpoint_digest(frozen)
        self._integrity()
        lane = frozen["query_source_lane"]
        lane_check = lanes.validate_lane_bundle(lane, expected_bindings=frozen["expected_query_lane_bindings"])
        _require(lane_check["profile_sha256"] == self._checkpoint["training_handoff"]["source_profile_sha256"]
                 and lane_check["dimension"] == INPUT_DIMENSION and lane_check["stage"] == "raw_embedding"
                 and lane["profile"]["inference_input_recipe"] == "exact_source_only/v1",
                 "query lane must use the exact source-only native384 representation profile")
        _, owner, _, _ = _reviewed_owners()
        replay = dict(expected_preparation_sha256=expected_preparation_sha256,
            preparation_inputs=preparation_inputs, expected_registry_sha256=expected_registry_sha256,
            expected_policy_sha256=expected_policy_sha256, expected_reviews_sha256=expected_reviews_sha256,
            at_time_utc=at_time_utc, observed_artifact_sha256s=observed_artifact_sha256s,
            observed_pins=observed_pins, evidence_artifacts=evidence_artifacts,
            current_endpoint_observations=current_endpoint_observations)
        current = owner.compile_reviewed_train_relation_masks_v2(preparation, registry, policy, reviews, **replay)
        common = dict(schema="legal-joint-retrieval-result/v2", purpose="structural_contrastive_training_examples",
            checkpoint_sha256=self._checkpoint_sha256,
            historical_training_handoff_sha256=self._checkpoint["training_handoff_sha256"],
            current_index_handoff_sha256=checkpoint_digest(current), current_index_scope="freshly_replayed_TRAIN_endpoints_only",
            model_ranking_authority="untrusted", historical_training_requalification_performed=False,
            model_use_and_resource_admission_scope="caller_owned_not_validated_here",
            legal_applicability_verified=False, controlling_authority_selected=False,
            governing_definition_or_proof_context_modified=False, decoder_context_admitted=False,
            query_target_payload_accessed=False, reference_identifier_exclusions_used=True,
            inference_reference_content_forwarded=False, heldout_evaluation_performed=False,
            input_embedding_runtime_computation_proven=False,
            historical_training_dependency_revalidation="not_performed_historical_weights_only", **_FALSE)
        if current.get("reviewed_objective_mask_ready") is not True:
            return {**common, "status": "abstained_current_index_unavailable",
                "rows": [{"id": query["id"], "status": "abstained", "context": None, "retrieved_ids": [],
                    "abstention_reasons": ["current_index_unavailable"]} for query in frozen["query_rows"]],
                "abstention_count": len(frozen["query_rows"]), "retrieved_count": 0,
                "abstention_reasons": current.get("objective_blockers", []), "training_executed": False,
                "model_forward_executed": False}
        _, formal_rows, _, _ = _reviewed_arrays(current)
        history = self._checkpoint["training_handoff"]
        if not all(current[name] == history[name] for name in ("source_profile_sha256", "formal_profile_sha256")):
            return {**common, "status": "abstained_representation_profile_incompatible",
                "rows": [{"id": query["id"], "status": "abstained", "context": None, "retrieved_ids": [],
                    "abstention_reasons": ["representation_profile_incompatible"]} for query in frozen["query_rows"]],
                "abstention_count": len(frozen["query_rows"]), "retrieved_count": 0,
                "model_forward_executed": False}
        manifest = splits.LegalIRSplitManifest.from_mapping(preparation_inputs["split_manifest"])
        _require(splits.validate_legal_ir_eval_splits(manifest).passed, "current source population has split leakage")
        examples = {example.sample_id: example for example in manifest.examples}
        queries, ids = [], set()
        _require(len(lane["rows"]) == len(frozen["query_rows"]), "complete ordered query lane required")
        for query, row in zip(frozen["query_rows"], lane["rows"], strict=True):
            _require(type(query) is dict and set(query) == {"id", "source_text", "split_sample_id"},
                     "closed target-free reviewed query required")
            identifier = _text(query["id"], "query id", 512)
            _require(identifier not in ids and row["id"] == identifier, "unique ordered query identity required")
            ids.add(identifier)
            text = _text(query["source_text"], "query source text", 262144)
            sample = examples.get(query["split_sample_id"])
            _require(sample is not None and sample.content_hash == splits._content_hash(text)
                     and sample.lineage_group_id and manifest.assignments[sample.sample_id] == expected_query_split,
                     "query source/exposure identity or declared held-out split differs")
            _require(row["input"]["source_text"] == text and row["input"]["context"] == {
                "role": "none_required", "text": "", "bindings": {}, "sha256": hashlib.sha256(b"").hexdigest()},
                "query input cannot carry hidden target or undeclared context")
            queries.append((query, row, sample))
        exclusions = frozen["forbidden_reference_formal_sha256s"]
        _require(type(exclusions) is dict and set(exclusions) == ids
                 and type(expected_forbidden_reference_sha256) is str
                 and _SHA.fullmatch(expected_forbidden_reference_sha256)
                 and checkpoint_digest(exclusions) == expected_forbidden_reference_sha256,
                 "complete independently pinned opaque reference exclusions required")
        for values in exclusions.values():
            _require(type(values) is list and len(values) <= REVIEWED_MAX_ROWS
                     and all(type(value) is str and _SHA.fullmatch(value) for value in values)
                     and len(values) == len(set(values)),
                     "bounded unique reference artifact digests required")
        torch, results = self._torch, []
        endpoints = current["formal_endpoints"]
        for query, row, sample in queries:
            raw_source_sha256 = hashlib.sha256(query["source_text"].encode("utf-8")).hexdigest()
            reasons = []
            if row["status"] != "available": reasons.append("query_representation_unavailable")
            eligible = []
            excluded = []
            for index, endpoint in enumerate(endpoints):
                candidate = examples[endpoint["split_sample_id"]]
                rule = None
                if (endpoint["id"] == query["id"] or endpoint["split_sample_id"] == sample.sample_id
                        or endpoint["source_sha256"] == raw_source_sha256 or candidate.content_hash == sample.content_hash):
                    rule = "same_source_or_identity"
                elif endpoint["exposure_group"] == sample.lineage_group_id:
                    rule = "reference_source_family"
                elif endpoint["formal_view_sha256"] in exclusions[query["id"]]:
                    rule = "forbidden_reference_artifact"
                elif sample.jurisdiction and splits._safe_key(endpoint["jurisdiction"]) != sample.jurisdiction:
                    rule = "query_jurisdiction_differs"
                if rule is None: eligible.append(index)
                else: excluded.append({"id": endpoint["id"], "reason": rule})
            if len(eligible) < top_k: reasons.append("insufficient_permitted_training_examples")
            if reasons:
                results.append({"id": query["id"], "source_sha256": raw_source_sha256,
                    "status": "abstained", "abstention_reasons": reasons, "eligible_rows": len(eligible),
                    "excluded_examples": excluded, "context": None, "retrieved_ids": []})
                continue
            query_vector = _vector(row["vector"])
            # Only permitted vectors enter projection/ranking. Complete index
            # admission is separately replayed, without forwarding query IR.
            source = torch.tensor([query_vector], dtype=torch.float32, device="cpu")
            formal = torch.tensor([formal_rows[index] for index in eligible], dtype=torch.float32, device="cpu")
            with torch.no_grad():
                if mode == "joint":
                    projected_query, projected_examples = self._model(source, formal)
                else:
                    projected_query = torch.nn.functional.normalize(source, dim=-1)
                    projected_examples = torch.nn.functional.normalize(formal, dim=-1)
                similarities = (projected_query @ projected_examples.T)[0]
                if mode == "random":
                    ranked = sorted(range(len(eligible)), key=lambda i: checkpoint_digest([
                        self._checkpoint["config"]["seed"], query["id"], raw_source_sha256,
                        common["current_index_handoff_sha256"], endpoints[eligible[i]]["id"]]))
                else:
                    ranked = sorted(range(len(eligible)), key=lambda i: (-float(similarities[i]), endpoints[eligible[i]]["id"]))
                selected = ranked[:top_k]
                scores = [float(similarities[i]) for i in selected]
                weights = (torch.full((top_k,), 1/top_k, device="cpu") if mode == "random" else
                    torch.softmax(torch.tensor(scores, dtype=torch.float32, device="cpu") /
                        self._checkpoint["config"]["temperature"], dim=0))
                context = (formal[selected] * weights[:, None]).sum(dim=0).tolist()
            chosen = [endpoints[eligible[i]] for i in selected]
            results.append({"id": query["id"], "source_sha256": raw_source_sha256, "status": "retrieved",
                "source_split": expected_query_split, "split_sample_id": sample.sample_id,
                "source_exposure_group": sample.lineage_group_id, "query_input_sha256": row["input_sha256"],
                "query_vector_sha256": row["vector_sha256"], "context": context,
                "context_sha256": checkpoint_digest(context), "context_dimension": INPUT_DIMENSION,
                "retrieved_ids": [item["id"] for item in chosen], "retrieved_endpoint_refs": copy.deepcopy(chosen),
                "scores": scores, "weights": weights.tolist(), "eligible_rows": len(eligible),
                "excluded_examples": excluded, "abstention_reasons": []})
        after = owner.compile_reviewed_train_relation_masks_v2(preparation, registry, policy, reviews, **replay)
        _require(_raw(after) == _raw(current), "current index eligibility changed during inference")
        _require(checkpoint_digest(payload) == query_input_sha256 and checkpoint_digest(frozen) == query_input_sha256,
                 "source-only query or exclusion inputs changed during inference")
        self._integrity()
        return {**common, "status": "retrieval_completed", "rows": results, "mode": mode,
            "current_index_differs_from_training": current["body_sha256"] != history["body_sha256"],
            "query_input_sha256": query_input_sha256, "query_lane_bundle_sha256": lane_check["bundle_sha256"],
            "query_split_guard_verified": True, "query_source_runtime_computation_proven": False,
            "query_target_access": False, "training_target_exemplars_accessed": True,
            "retrieved_count": sum(row["status"] == "retrieved" for row in results),
            "abstention_count": sum(row["status"] == "abstained" for row in results),
            "model_forward_executed": any(row["status"] == "retrieved" and mode == "joint" for row in results)}

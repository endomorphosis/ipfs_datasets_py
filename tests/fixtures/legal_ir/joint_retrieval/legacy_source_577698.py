"""Bounded, training-only cross-modal retrieval for LegalIR experiments.

Two linear encoders align supplied 384-dimensional source/formal embeddings.
This adapts contrastive retrieval from ProofBridge; it has no proof DAG encoder,
does not generate formulas, and grants no semantic or proof authority. Callers
own embedding provenance and must keep evaluation targets out of the index.
"""
from __future__ import annotations

import copy
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


def _restore(checkpoint):
    import torch
    _require(type(checkpoint) is dict and set(checkpoint) == {
        "schema", "config", "implementation", "index_sha256", "training_rows",
        "training_modalities", "model_state", "progress"}, "closed retrieval checkpoint required")
    _require(checkpoint["schema"] == SCHEMA, "retrieval checkpoint schema differs")
    _require(checkpoint["implementation"] == _implementation(), "retrieval source pins differ")
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


def validate_checkpoint(checkpoint):
    _restore(checkpoint)


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
    def __init__(self, training_rows, checkpoint):
        self._rows = _training_rows(training_rows)
        self._checkpoint = copy.deepcopy(checkpoint)
        self._torch, self._model = _restore(checkpoint)
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
        _require(self._checkpoint["implementation"] == _implementation(), "retrieval source pins changed")
        _require(checkpoint_digest(self._checkpoint) == self._checkpoint_sha256, "retrieval checkpoint mutated")
        _require(checkpoint_digest(self._rows) == self.index_sha256, "retrieval index mutated")
        _require(checkpoint_digest(_state(self._model)) == self._state_sha256, "retrieval model mutated")
        _require(self._torch.equal(self._formal, self._torch.tensor(
            [row["formal_embedding"] for row in self._rows], dtype=self._torch.float32)), "formal index tensor mutated")

    def retrieve(self, query_rows, *, mode="joint", top_k=3, exclude_same_family=True):
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


def save_checkpoint(checkpoint, path):
    """Create a new JSON artifact and return its exact file-byte SHA-256."""
    validate_checkpoint(checkpoint)
    payload = _raw(checkpoint) + b"\n"
    _require(len(payload) <= MAX_BYTES, "retrieval checkpoint exceeds byte bound")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)
    return hashlib.sha256(payload).hexdigest()


def load_checkpoint(path, expected_sha256=None):
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
    validate_checkpoint(checkpoint)
    return checkpoint

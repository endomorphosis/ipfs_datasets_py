"""Self-contained current384D Legal inference packages.

The sparse core and optional learned formula head retain separate identities.
Packaging never trains, downloads, or substitutes compiler output for a missing
learned head. Compatibility forks require exact replay of all retained training
and tuning inputs; that finite check is not a universal equivalence proof.
"""
from __future__ import annotations

from dataclasses import replace
from functools import wraps
import hashlib
import json
from pathlib import Path
import re
import stat

SCHEMA = "legal-current-384-inference-package/v1"
RUNTIME = "legal_current_v2"
MAX_BYTES = 96 * 1024 * 1024
FALSE = {
    "qualified": False,
    "admitted": False,
    "proof_authority": False,
    "semantic_correctness_verified": False,
    "promotion_performed": False,
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _cpu_inference(function):
    """Share the native 384D runtime's lock and restore the caller's threads."""
    @wraps(function)
    def bounded(*args, **kwargs):
        from ....optimizers.logic_theorem_optimizer.domain_384_autoencoder import _cpu
        with _cpu():
            return function(*args, **kwargs)
    return bounded


def _modules():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        modal_joint_formula as joint,
        modal_latent_formula as formula,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import (
        current_v2,
    )
    return current_v2, joint, formula


def _producer():
    _, _, formula = _modules()
    return {
        "package_sha256": _sha(Path(__file__).read_bytes()),
        "formula_implementation": formula._implementation(),
        "scope": (
            "package and formula sources; core binding separately includes "
            "core source and configuration"
        ),
    }


def _rows(rows, embedding_contract):
    current, _, _ = _modules()
    _require(
        type(rows) in (list, tuple) and 1 <= len(rows) <= 128,
        "one to 128 Legal inference rows required",
    )
    result, seen = [], set()
    for row in rows:
        _require(
            type(row) is dict
            and set(row) == {"id", "source_text", "embedding"},
            "Legal rows require exactly id/source_text/embedding",
        )
        _require(
            type(row["id"]) is str
            and 0 < len(row["id"]) <= 512
            and row["id"] not in seen,
            "unique bounded Legal row id required",
        )
        _require(
            type(row["source_text"]) is str
            and 0 < len(row["source_text"]) <= 16384,
            "bounded Legal source text required",
        )
        sample = current.build_sample(
            title="release-inference",
            section=_sha(row["id"].encode())[:16],
            text=row["source_text"],
            embedding_model=embedding_contract["model_id"],
            embedding_vector=row["embedding"],
            top_k_frames=0,
        )
        sample = replace(
            sample,
            sample_id=row["id"],
            modal_ir=replace(sample.modal_ir, document_id=row["id"]),
        )
        sample.validate()
        result.append(sample)
        seen.add(row["id"])
    return result


@_cpu_inference
def rebind_formula_head(
    model,
    parent_head,
    *,
    training_rows,
    tuning_rows,
    training_samples,
    tuning_samples,
):
    """Create an explicit compatibility branch after complete input replay.

    Parent decoder implementation pins must still pass unchanged. Every
    historical training/tuning row is required, including the original source,
    embedding, and target. No existing artifact is changed.
    """
    current, joint, formula = _modules()
    _require(
        type(model) is current.Autoencoder,
        "current384D Legal core required",
    )
    formula.validate_checkpoint(parent_head)
    _require(
        parent_head["binding"]["lineage_id"] == "current_legal_v2"
        and parent_head["progress"]["optimizer_steps"] > 0,
        "trained current384D parent required",
    )
    for name, rows, samples in (
        ("training", training_rows, training_samples),
        ("tuning", tuning_rows, tuning_samples),
    ):
        _require(
            formula.checkpoint_digest(rows)
            == parent_head[name + "_manifest_sha256"],
            "complete historical " + name + " manifest required",
        )
        _require(
            type(samples) in (list, tuple) and len(samples) == len(rows),
            name + " sample count differs",
        )
        targets = [
            {
                "id": row["id"],
                "source_text": row["source_text"],
                "canonical_ir": row["canonical_ir"],
            }
            for row in rows
        ]
        replay = joint._rows(model, samples, targets) if samples else []
        _require(
            _raw(replay) == _raw(rows),
            "current core differs from historical " + name + " inputs",
        )

    owned = json.loads(_raw(parent_head))
    parent_sha = formula.checkpoint_digest(parent_head)
    previous_binding = owned["binding"]
    owned["binding"] = joint._core_binding(model)
    _require(
        owned["binding"] != previous_binding,
        "identical core requires no compatibility fork",
    )
    owned["parent_checkpoint_sha256"] = parent_sha
    formula.validate_checkpoint(owned)

    _require(
        owned["model_state"] == parent_head["model_state"]
        and owned["optimizer_state"] == parent_head["optimizer_state"]
        and owned["progress"] == parent_head["progress"],
        "compatibility fork changed numerical state",
    )
    receipt = {
        "schema": "legal384-explicit-core-compatibility-fork/v1",
        "parent_checkpoint_sha256": parent_sha,
        "child_checkpoint_sha256": formula.checkpoint_digest(owned),
        "previous_binding": previous_binding,
        "current_binding": owned["binding"],
        "training_rows_replayed": len(training_rows),
        "tuning_rows_replayed": len(tuning_rows),
        "all_retained_inputs_exact": True,
        "neural_weights_unchanged": True,
        "optimizer_state_unchanged": True,
        "training_steps": 0,
        "scope": (
            "complete retained training/tuning core-input parity; "
            "not universal source equivalence"
        ),
        **FALSE,
    }
    return {"checkpoint": owned, "receipt": receipt}


class Runtime:
    @_cpu_inference
    def __init__(self, payload):
        current, joint, _ = _modules()
        fields = {
            "schema",
            "runtime",
            "domain",
            "dimension",
            "producer",
            "core_options",
            "core_state",
            "core_binding",
            "formula_checkpoint",
            "embedding_contract",
            "provenance",
            "fixture",
            *FALSE,
        }
        _require(
            type(payload) is dict and set(payload) == fields,
            "closed Legal package fields required",
        )
        _require(
            payload["schema"] == SCHEMA
            and payload["runtime"] == RUNTIME
            and payload["domain"] == "legal_ir"
            and payload["dimension"] == 384
            and all(payload[k] is False for k in FALSE),
            "Legal package identity/authority differs",
        )
        _require(
            payload["producer"] == _producer(),
            "Legal package producer source differs",
        )
        options = payload["core_options"]
        _require(
            type(options) is dict
            and not (
                {"state", "feature_codec", "legacy_embedding_adapters"}
                & set(options)
            ),
            "serializable constructor options required",
        )
        _require(
            options.get("compute_device") == "cpu",
            "Legal package currently requires explicit CPU runtime",
        )
        contract = payload["embedding_contract"]
        _require(
            type(contract) is dict
            and contract.get("dimension") == 384
            and type(contract.get("model_id")) is str
            and bool(contract["model_id"])
            and type(contract.get("revision")) is str
            and bool(contract["revision"]),
            "explicit384D embedding model/revision contract required",
        )
        state = current.TrainingState.from_dict(payload["core_state"])
        _require(
            _raw(state.to_dict()) == _raw(payload["core_state"]),
            "core state would be changed by compatibility loading",
        )
        self.model = current.Autoencoder(state=state, **options)
        _require(
            joint._core_binding(self.model) == payload["core_binding"],
            "Legal package core/source binding differs",
        )
        head = payload["formula_checkpoint"]
        if head is not None:
            _require(
                head["progress"]["optimizer_steps"] > 0,
                "untrained formula head cannot be released",
            )
            self.model.attach_formula_checkpoint(head)
        self._payload = json.loads(_raw(payload))
        self._bundle_sha256 = _sha(_raw(payload))

    def describe(self):
        head = self._payload["formula_checkpoint"]
        return {
            "runtime": RUNTIME,
            "domain": "legal_ir",
            "dimension": 384,
            "architecture": (
                "AdaptiveModalAutoencoder sparse residual core "
                "with optional latent formula GRU"
            ),
            "checkpoint_sha256": self._bundle_sha256,
            "core_binding": self._payload["core_binding"],
            "embedding_contract": self._payload["embedding_contract"],
            "learned_formula_head": head is not None,
            "supported_projections": (
                [] if head is None else ["typed_deontic_rule_v1"]
            ),
            "formula_checkpoint_sha256": (
                None if head is None else _sha(_raw(head))
            ),
            "source_only": False,
            "parser_features_in_input": True,
            "training_steps": 0,
            **FALSE,
        }

    @_cpu_inference
    def infer(self, rows):
        _, joint, _ = _modules()
        _require(
            self._payload["producer"] == _producer(),
            "Legal inference producer changed",
        )
        _require(
            joint._core_binding(self.model) == self._payload["core_binding"],
            "Legal core changed after loading",
        )
        samples = _rows(rows, self._payload["embedding_contract"])
        if self._payload["formula_checkpoint"] is not None:
            result = self.model.decode_formal_logic(
                samples, mode="learned_latent"
            )
        else:
            result = {
                "rows": [
                    {
                        "id": sample.sample_id,
                        "embedding": joint.raw_projection(self.model, sample),
                        "formal_logic": None,
                        "reason": "learned_formula_head_absent",
                    }
                    for sample in samples
                ]
            }
        _require(
            joint._core_binding(self.model) == self._payload["core_binding"],
            "inference mutated Legal core",
        )
        return {
            "runtime": RUNTIME,
            "checkpoint_sha256": self._bundle_sha256,
            "result": result,
            "training_steps": 0,
            "provider_calls": 0,
            **FALSE,
        }


def build_package(
    output_dir,
    *,
    model,
    core_options,
    embedding_contract,
    fixture_rows,
    provenance,
):
    """Save a fresh complete package after exact restore and inference replay."""
    current, joint, _ = _modules()
    _require(
        type(model) is current.Autoencoder,
        "current384D Legal model required",
    )
    payload = {
        "schema": SCHEMA,
        "runtime": RUNTIME,
        "domain": "legal_ir",
        "dimension": 384,
        "producer": _producer(),
        "core_options": core_options,
        "core_state": model.state.to_dict(),
        "core_binding": joint._core_binding(model),
        "formula_checkpoint": model.formula_checkpoint,
        "embedding_contract": embedding_contract,
        "provenance": provenance,
        "fixture": {"rows": fixture_rows},
        **FALSE,
    }
    runtime = Runtime(payload)
    expected = runtime.infer(fixture_rows)["result"]
    payload["fixture"]["expected_result_sha256"] = _sha(_raw(expected))
    runtime = Runtime(payload)
    _require(
        _sha(_raw(runtime.infer(fixture_rows)["result"]))
        == payload["fixture"]["expected_result_sha256"],
        "Legal package reload changed numerical inference",
    )
    raw = _raw(payload)
    _require(len(raw) <= MAX_BYTES, "Legal package exceeds byte limit")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=False)
    path = destination / "checkpoint.json"
    with path.open("xb") as stream:
        stream.write(raw)
    restored = load_package(path, expected_sha256=_sha(raw))
    return {
        "path": str(path.resolve()),
        "sha256": _sha(raw),
        "bytes": len(raw),
        "runtime": RUNTIME,
        "domain": "legal_ir",
        "dimension": 384,
        "inference_replay_verified": True,
        "description": restored.describe(),
        **FALSE,
    }


def load_package(path, *, expected_sha256):
    """Load inert JSON using installed code and an explicit artifact pin."""
    _require(
        type(expected_sha256) is str
        and re.fullmatch(r"[0-9a-f]{64}", expected_sha256),
        "exact Legal package SHA256 required",
    )
    source = Path(path)
    _require(
        not source.is_symlink()
        and stat.S_ISREG(source.stat().st_mode)
        and 0 < source.stat().st_size <= MAX_BYTES,
        "bounded regular Legal package required",
    )
    with source.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    _require(
        len(raw) <= MAX_BYTES and _sha(raw) == expected_sha256,
        "Legal package SHA256 differs",
    )

    def unique(pairs):
        value = {}
        for key, item in pairs:
            _require(key not in value, "duplicate Legal package key")
            value[key] = item
        return value

    payload = json.loads(raw, object_pairs_hook=unique)
    _require(_raw(payload) == raw, "canonical Legal package bytes required")
    runtime = Runtime(payload)
    fixture = payload["fixture"]
    _require(
        type(fixture) is dict
        and set(fixture) == {"rows", "expected_result_sha256"},
        "complete Legal inference fixture required",
    )
    _require(
        _sha(_raw(runtime.infer(fixture["rows"])["result"]))
        == fixture["expected_result_sha256"],
        "Legal package inference fixture differs",
    )
    return runtime


__all__ = [
    "build_package",
    "load_package",
    "rebind_formula_head",
    "Runtime",
    "SCHEMA",
    "RUNTIME",
]

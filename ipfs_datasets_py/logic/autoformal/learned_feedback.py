"""Checkpoint-derived repair hints, separate from source replay and proof truth.

No training, task mutation, publication or model promotion occurs here. Native
checkpoint and corpus verifiers own their respective formats. Never relabel
rule-derived ontology triples as learned decoder outputs.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import stat


SCHEMA = "autoformal-checkpoint-guidance/v1"


def _read_receipt(path: Path, expected_sha256: str) -> dict:
    maximum = 64 * 1024 * 1024
    if path.absolute() != path.resolve(strict=True):
        raise ValueError("worker receipt path is not canonical")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise ValueError("worker receipt is not bounded regular data")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    after = path.stat()
    if (len(raw) > maximum or any(getattr(before, field) != getattr(after, field)
            for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))
            or hashlib.sha256(raw).hexdigest() != expected_sha256):
        raise ValueError("worker receipt integrity mismatch")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("worker receipt must be an object")
    return value


def _finite(value, label: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValueError("invalid finite feedback metric: " + label)
    return float(value)


def compact_guidance(model, sample) -> dict:
    """Call the native learned interface without exposing vectors or targets."""
    observation = model.introspect_sample(sample, use_sample_memory=False, top_k=4,
                                         include_causal_attribution=False)
    guidance = model.compiler_guidance_for_sample(
        sample, use_sample_memory=False, top_k=4, include_causal_attribution=False,
        introspection=observation,
    )
    if (guidance.get("sample_id") != sample.sample_id
            or guidance.get("sample_memory_used") is not False
            or observation.sample_id != sample.sample_id
            or observation.sample_memory_used is not False):
        raise ValueError("guidance sample or memory binding differs")
    distribution = guidance.get("family_distribution")
    if not isinstance(distribution, dict) or not 1 <= len(distribution) <= 64:
        raise ValueError("missing or oversized learned family distribution")
    probabilities = {}
    for name, value in distribution.items():
        if not isinstance(name, str) or not 1 <= len(name) <= 64:
            raise ValueError("invalid family label")
        probability = _finite(value, "family probability")
        if not 0 <= probability <= 1:
            raise ValueError("invalid family probability")
        probabilities[name] = probability
    if not math.isclose(sum(probabilities.values()), 1.0, abs_tol=1e-8):
        raise ValueError("family probabilities are not normalized")
    similarity = _finite(observation.cosine_similarity, "cosine similarity")
    reconstruction = _finite(observation.reconstruction_loss, "reconstruction loss")
    if not -1 <= similarity <= 1 or reconstruction < 0:
        raise ValueError("feedback metrics outside their domains")
    # Source-derived feature labels are diagnostic hints, not a decoder's
    # statements of legal fact. Do not emit raw embeddings, residuals or targets.
    groups = guidance.get("feature_groups", {})
    if not isinstance(groups, dict) or len(groups) > 32:
        raise ValueError("invalid guidance feature groups")
    selected = {}
    for name, features in groups.items():
        if not isinstance(name, str) or not 1 <= len(name) <= 64 or not isinstance(features, list):
            raise ValueError("invalid guidance feature group")
        if any(not isinstance(value, str) or len(value) > 512 for value in features[:4]):
            raise ValueError("oversized or invalid guidance feature")
        selected[name] = features[:4]
    return {
        "model_sample_id": sample.sample_id,
        "family_distribution": probabilities,
        "embedding_cosine_similarity": similarity,
        "embedding_reconstruction_loss": reconstruction,
        "source_derived_feature_groups": selected,
        "sample_memory_used": False, "counts_as_validation": False,
        "symbolic_decoder_output": False,
    }


def observe_checkpoint(receipt_path: Path, expected_sha256: str, *, record_ids=None) -> dict:
    """Verify a native worker candidate and infer only on its training members.

    Caller must run in a fresh, explicitly selected source tree. Input-pipeline
    drift since training is reported, never hidden behind the checkpoint hash.
    """
    from ...optimizers.logic_theorem_optimizer import modal_autoencoder, legal_samples
    from ...optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
        TrainingJobSpec, _effective_constructor_config, _thaw,
    )
    from . import training_cycle_inputs
    from ...optimizers.logic_theorem_optimizer.modal_autoencoder_sparse_checkpoint import (
        resolve_checkpoint, artifact_ref, ResolutionLimits,
    )
    from .tree_pin import require_workspace_logic_tree, workspace_root

    receipt_path = receipt_path.absolute()
    observer_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    input_helper_hash = hashlib.sha256(Path(training_cycle_inputs.__file__).read_bytes()).hexdigest()
    receipt = _read_receipt(receipt_path, expected_sha256)
    if (receipt.get("schema_version") != "autoencoder-training-worker-receipt-v1"
            or receipt.get("execution_mode") != "native_training"
            or receipt.get("admitted") is not False
            or receipt.get("promotion_performed") is not False
            or receipt.get("use_sample_memory") is not False):
        raise ValueError("not an unpromoted native no-memory worker receipt")
    spec = TrainingJobSpec.from_dict(receipt["job_spec"])
    if spec.canonical_sha256 != receipt["job_spec_canonical_sha256"] or spec.job_id != receipt["job_id"]:
        raise ValueError("worker job identity mismatch")
    cycle_inputs = training_cycle_inputs.verify_cycle_inputs(spec, record_ids=record_ids)
    verification = cycle_inputs.verification
    train_ids = list(verification["training_record_ids"])
    records = {row.record_id: row for row in cycle_inputs.training_records}
    chosen = [row.record_id for row in cycle_inputs.training_records]
    if hashlib.sha256(Path(training_cycle_inputs.__file__).read_bytes()).hexdigest() != input_helper_hash:
        raise ValueError("feedback input helper changed during verification")
    inputs = dict(zip(train_ids, spec.samples, strict=True))
    references = {}
    for value in [receipt["candidate"], asdict(spec.base_checkpoint),
                  *(asdict(item) for item in spec.base_checkpoint_dependencies),
                  *receipt.get("sparse_patch_segments", [])]:
        reference = artifact_ref(value)
        old = references.get(reference["sha256"])
        if old is not None and old["bytes"] != reference["bytes"]:
            raise ValueError("conflicting checkpoint dependency sizes")
        references.setdefault(reference["sha256"], value)

    def resolve(reference):
        value = references[reference["sha256"]]
        if value["bytes"] != reference["bytes"]:
            raise ValueError("checkpoint dependency size mismatch")
        return Path(value["path"])

    resolved = resolve_checkpoint(receipt["candidate"], resolver=resolve,
                                  limits=ResolutionLimits(max_artifacts=258))
    state = resolved.state
    before = state.state_identity()
    if before != receipt["candidate_state_identity"]["digest"]:
        raise ValueError("candidate state differs from native worker identity")
    cls = modal_autoencoder.AdaptiveModalAutoencoder
    configuration = _effective_constructor_config(cls, spec.autoencoder_config)
    model = cls(state=state, **configuration)
    effective = {name: (_thaw(getattr(model, name)) if name != "compute_device" and hasattr(model, name)
                        else value) for name, value in configuration.items()}
    # Constructor defaults and their normalization are saved execution identity.
    if effective != receipt["effective_autoencoder_config"]:
        raise ValueError("model constructor configuration changed since training")
    paths = {**require_workspace_logic_tree(), "autoencoder": modal_autoencoder.__file__,
             "samples": legal_samples.__file__, "cycle_inputs": training_cycle_inputs.__file__}
    if any(not Path(path).resolve().is_relative_to(workspace_root()) for path in paths.values()):
        raise ValueError("feedback implementation resolved outside the selected source tree")
    hashes = {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in paths.items()}
    observations = []
    for record_id in chosen:
        row = inputs[record_id]
        record = records[record_id]
        if (row.title, row.section, row.text) != (record.sample.title, record.sample.section, record.sample.text):
            raise ValueError("inference sample and source record differ")
        sample = legal_samples.build_us_code_sample(**asdict(row))
        observations.append({"source_span_id": record_id,
                             "source_text_sha256": hashlib.sha256(row.text.encode()).hexdigest(),
                             **compact_guidance(model, sample)})
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != observer_hash:
        raise ValueError("feedback observer changed during execution")
    if hashlib.sha256(Path(training_cycle_inputs.__file__).read_bytes()).hexdigest() != input_helper_hash:
        raise ValueError("feedback input helper changed during execution")
    if state.state_identity() != before or any(
        hashlib.sha256(Path(paths[name]).read_bytes()).hexdigest() != value for name, value in hashes.items()
    ):
        raise ValueError("model state or source changed during feedback observation")
    # The input helper has its own pre-use/final guard. Worker receipts do not
    # record its hash, so its absence cannot establish post-training drift.
    return {
        "schema": SCHEMA, "worker_receipt_sha256": expected_sha256,
        "observer_source_sha256": observer_hash,
        "input_helper_source_sha256": input_helper_hash,
        "candidate": artifact_ref(receipt["candidate"]), "state_identity": before,
        "code_hashes": hashes,
        "code_changed_since_training": sorted(name for name, value in hashes.items()
                                               if name != "cycle_inputs" and receipt["tree_file_sha256"].get(name) != value),
        "model_configuration_sha256": hashlib.sha256(json.dumps(effective, sort_keys=True).encode()).hexdigest(),
        "training_selection_only": True, "sample_memory_used": False,
        "observations": observations, "observation_count": len(observations),
        "state_changed": False, "counts_as_validation": False,
        "symbolic_decoder_output": False, "admitted": False, "formalized": False,
        "production_promotion": False,
    }


def attach_guidance(agreement: dict, report: dict, model_identity: str) -> dict:
    """Attach model hints without changing compiler agreement or replay targets."""
    if (report.get("schema") != SCHEMA or report.get("training_selection_only") is not True
            or report.get("sample_memory_used") is not False
            or report.get("state_changed") is not False
            or report.get("counts_as_validation") is not False
            or report.get("symbolic_decoder_output") is not False
            or any(report.get(key) is not False for key in ("admitted", "formalized", "production_promotion"))
            or model_identity != "sha256:" + report["candidate"]["sha256"]):
        raise ValueError("feedback report has incompatible provenance or authority")
    observations = report["observations"]
    lookup = {item["source_span_id"]: item for item in observations}
    if len(lookup) != len(observations) or len(observations) != report["observation_count"]:
        raise ValueError("feedback observations are incomplete or duplicated")
    rows = []
    for row in agreement["rows"]:
        if row.get("skipped"):
            rows.append(dict(row))
            continue
        identity = row.get("source_span_id") or row["id"]
        hint = lookup.get(identity)
        if hint is None or hint["source_text_sha256"] != hashlib.sha256(row["text"].encode()).hexdigest():
            raise ValueError("feedback source differs from compiler observation")
        if any(hint.get(key) is not False for key in ("sample_memory_used", "counts_as_validation", "symbolic_decoder_output")):
            raise ValueError("feedback observation claims unsupported authority")
        rows.append({**row, "learned_guidance": {
            "candidate_sha256": report["candidate"]["sha256"],
            "worker_receipt_sha256": report["worker_receipt_sha256"],
            "code_hashes": report["code_hashes"],
            "code_changed_since_training": report["code_changed_since_training"],
            "observation": hint,
            "counts_as_validation": False,
        }})
    return {**agreement, "rows": rows}

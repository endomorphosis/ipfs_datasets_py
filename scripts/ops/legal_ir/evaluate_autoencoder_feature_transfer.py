#!/usr/bin/env python3
"""Gate a legacy feature transfer on the fixed LegalIR CUDA canary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.logic.modal import (  # noqa: E402
    DeterministicModalLogicCodec,
    ModalLogicCodecConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (  # noqa: E402
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
    _legal_ir_target_payload,
    _observed_family_distribution,
    cosine_similarity,
    cross_entropy_distribution_loss,
    cross_entropy_excess_distribution_loss,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (  # noqa: E402
    load_laws_table,
    row_to_sample,
)


FEATURE_TRANSFER_CANARY_SCHEMA_VERSION = (
    "modal-autoencoder-feature-transfer-canary-v1"
)
BRIDGE_NAMES = (
    "modal_frame_logic",
    "deontic_norms",
    "fol_tdfol",
    "cec_dcec",
    "external_prover_router",
)
LOWER_IS_BETTER = frozenset(
    {
        "autoencoder_cross_entropy_loss",
        "ir_view_cross_entropy_loss",
    }
)
GROUND_METRIC_TOLERANCES = {
    "autoencoder_cross_entropy_loss": 1.0e-4,
    "autoencoder_cosine_similarity": 0.0,
    "ir_view_cross_entropy_loss": 0.0,
    "ir_view_cosine_similarity": 0.0,
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _verify_report_digest(report: Mapping[str, Any]) -> str:
    expected = str(report.get("report_sha256") or "")
    payload = dict(report)
    payload.pop("report_sha256", None)
    observed = _sha256_value(payload)
    if expected != observed:
        raise ValueError(
            f"transfer report digest mismatch: {expected or '<missing>'} != {observed}"
        )
    return observed


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _distribution_cosine(
    left: Mapping[str, float],
    right: Mapping[str, float],
) -> float:
    keys = sorted(set(left) | set(right))
    return cosine_similarity(
        [float(left.get(key, 0.0)) for key in keys],
        [float(right.get(key, 0.0)) for key in keys],
    )


def _build_autoencoder(
    state: ModalAutoencoderTrainingState,
    *,
    feature_codec: DeterministicModalLogicCodec,
    feature_family_logit_scale: float,
    feature_embedding_weight_scale: float,
) -> AdaptiveModalAutoencoder:
    return AdaptiveModalAutoencoder(
        state=state,
        feature_codec=feature_codec,
        compute_device="cuda",
        compiler_quality_family_logit_scale=1.0,
        logic_signature_family_logit_scale=1.0,
        logic_signature_legal_ir_view_logit_scale=1.0,
        round_trip_signal_family_logit_scale=1.0,
        round_trip_signal_legal_ir_view_logit_scale=1.0,
        decompiler_plan_family_logit_scale=1.0,
        decompiler_plan_legal_ir_view_logit_scale=1.0,
        predicate_argument_family_logit_scale=1.0,
        predicate_argument_legal_ir_view_logit_scale=1.0,
        feature_embedding_weight_scale=feature_embedding_weight_scale,
        feature_family_logit_scale=feature_family_logit_scale,
        semantic_slot_family_logit_scale=1.0,
        legal_ir_view_family_logit_scale=1.0,
        family_semantic_slot_legal_ir_view_logit_scale=1.0,
        semantic_slot_legal_ir_view_family_logit_scale=1.0,
        semantic_slot_legal_ir_view_logit_scale=1.0,
        max_semantic_slot_interactions=24,
        max_codec_feature_keys=64,
        cosine_reconstruction_weight=0.25,
    )


def _evaluate_state(
    state: ModalAutoencoderTrainingState,
    *,
    samples: Sequence[Any],
    target_view_distributions: Mapping[str, Mapping[str, float]],
    target_losses: Mapping[str, Mapping[str, float]],
    feature_codec: DeterministicModalLogicCodec,
    feature_family_logit_scale: float,
    feature_embedding_weight_scale: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    autoencoder = _build_autoencoder(
        state,
        feature_codec=feature_codec,
        feature_family_logit_scale=feature_family_logit_scale,
        feature_embedding_weight_scale=feature_embedding_weight_scale,
    )
    autoencoder._cache_legal_ir_targets(
        samples,
        target_view_distributions,
        target_losses,
    )
    family_distributions: list[Mapping[str, float]] = []
    decoded_embeddings: list[list[float]] = []
    view_distributions: list[Mapping[str, float]] = []
    started = time.monotonic()
    for sample in samples:
        family_distributions.append(
            autoencoder._family_distribution(
                sample,
                use_sample_memory=False,
            )
        )
        decoded_embeddings.append(
            autoencoder._decoded_for(
                sample,
                use_sample_memory=False,
            )
        )
        view_distributions.append(
            autoencoder._legal_ir_view_distribution(
                sample,
                target_view_distributions[sample.sample_id],
                use_sample_memory=False,
            )
        )
    elapsed = time.monotonic() - started
    metrics = {
        "autoencoder_cosine_similarity": _mean(
            [
                cosine_similarity(decoded, sample.embedding_vector)
                for decoded, sample in zip(
                    decoded_embeddings,
                    samples,
                    strict=True,
                )
            ]
        ),
        "autoencoder_cross_entropy_loss": _mean(
            [
                cross_entropy_distribution_loss(
                    predicted,
                    _observed_family_distribution(sample),
                )
                for predicted, sample in zip(
                    family_distributions,
                    samples,
                    strict=True,
                )
            ]
        ),
        "ir_view_cosine_similarity": _mean(
            [
                _distribution_cosine(
                    predicted,
                    target_view_distributions[sample.sample_id],
                )
                for predicted, sample in zip(
                    view_distributions,
                    samples,
                    strict=True,
                )
            ]
        ),
        "ir_view_cross_entropy_loss": _mean(
            [
                cross_entropy_distribution_loss(
                    predicted,
                    target_view_distributions[sample.sample_id],
                )
                for predicted, sample in zip(
                    view_distributions,
                    samples,
                    strict=True,
                )
            ]
        ),
    }
    outputs = {
        "decoded_embeddings": decoded_embeddings,
        "family_distributions": family_distributions,
        "view_distributions": view_distributions,
    }
    evidence = {
        "compute_backend": str(autoencoder.compute_backend),
        "compute_device": str(autoencoder.compute_device),
        "elapsed_seconds": elapsed,
        "metrics": metrics,
    }
    return evidence, outputs


def _teacher_fidelity(
    outputs: Mapping[str, Any],
    teacher: Mapping[str, Any],
) -> dict[str, float]:
    return {
        "embedding_cosine_similarity": _mean(
            [
                cosine_similarity(left, right)
                for left, right in zip(
                    outputs["decoded_embeddings"],
                    teacher["decoded_embeddings"],
                    strict=True,
                )
            ]
        ),
        "family_cosine_similarity": _mean(
            [
                _distribution_cosine(left, right)
                for left, right in zip(
                    outputs["family_distributions"],
                    teacher["family_distributions"],
                    strict=True,
                )
            ]
        ),
        "family_kl_excess_loss": _mean(
            [
                cross_entropy_excess_distribution_loss(left, right)
                for left, right in zip(
                    outputs["family_distributions"],
                    teacher["family_distributions"],
                    strict=True,
                )
            ]
        ),
        "view_cosine_similarity": _mean(
            [
                _distribution_cosine(left, right)
                for left, right in zip(
                    outputs["view_distributions"],
                    teacher["view_distributions"],
                    strict=True,
                )
            ]
        ),
        "view_kl_excess_loss": _mean(
            [
                cross_entropy_excess_distribution_loss(left, right)
                for left, right in zip(
                    outputs["view_distributions"],
                    teacher["view_distributions"],
                    strict=True,
                )
            ]
        ),
    }


def gate_transfer_metrics(
    target_metrics: Mapping[str, float],
    candidate_metrics: Mapping[str, float],
    target_fidelity: Mapping[str, float],
    candidate_fidelity: Mapping[str, float],
) -> dict[str, Any]:
    """Apply the immutable no-regression and teacher-fidelity checks."""

    checks: dict[str, bool] = {}
    metric_deltas: dict[str, float] = {}
    for name, tolerance in GROUND_METRIC_TOLERANCES.items():
        target = float(target_metrics[name])
        candidate = float(candidate_metrics[name])
        metric_deltas[name] = candidate - target
        if name in LOWER_IS_BETTER:
            checks[f"ground:{name}"] = candidate <= target + tolerance
        else:
            checks[f"ground:{name}"] = candidate + tolerance >= target

    fidelity_deltas: dict[str, float] = {}
    for name in sorted(target_fidelity):
        target = float(target_fidelity[name])
        candidate = float(candidate_fidelity[name])
        fidelity_deltas[name] = candidate - target
        if name.endswith("_loss"):
            checks[f"teacher_fidelity:{name}"] = candidate <= target
        else:
            checks[f"teacher_fidelity:{name}"] = candidate >= target
    return {
        "accepted": all(checks.values()),
        "checks": checks,
        "fidelity_deltas": fidelity_deltas,
        "metric_deltas": metric_deltas,
        "tolerances": dict(GROUND_METRIC_TOLERANCES),
    }


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher-state", type=Path, required=True)
    parser.add_argument("--target-state", type=Path, required=True)
    parser.add_argument("--candidate-state", type=Path, required=True)
    parser.add_argument("--transfer-report", type=Path, required=True)
    parser.add_argument("--baseline-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parallel-workers", type=int, default=2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = {
        "teacher": args.teacher_state.resolve(),
        "target": args.target_state.resolve(),
        "candidate": args.candidate_state.resolve(),
        "transfer_report": args.transfer_report.resolve(),
        "baseline_summary": args.baseline_summary.resolve(),
    }
    output = args.output.resolve()
    for path in paths.values():
        if not path.is_file():
            raise SystemExit(f"required input does not exist: {path}")
    if output.exists():
        raise SystemExit(f"refusing to overwrite output: {output}")

    transfer_report = _load_json(paths["transfer_report"])
    transfer_digest = _verify_report_digest(transfer_report)
    artifacts = _mapping(transfer_report.get("artifacts"))
    if _mapping(artifacts.get("output_state")).get("sha256") != _sha256_file(
        paths["candidate"]
    ):
        raise SystemExit("candidate checkpoint does not match transfer report")
    if _mapping(artifacts.get("target_state")).get("sha256") != _sha256_file(
        paths["target"]
    ):
        raise SystemExit("target checkpoint does not match transfer report")

    baseline_summary = _load_json(paths["baseline_summary"])
    indices = tuple(
        int(value)
        for value in baseline_summary.get("validation_canary_indices", [])
    )
    if len(indices) != 8 or len(set(indices)) != 8:
        raise SystemExit("baseline summary must bind exactly eight unique canary rows")
    params = _mapping(
        _mapping(transfer_report.get("selection_lineage")).get("params")
    )
    family_scale = float(params.get("fam", 1.0))
    embedding_scale = float(params.get("emb", 0.5))

    dataset_started = time.monotonic()
    laws_table = load_laws_table()
    samples = [
        row_to_sample(laws_table.take([index]).to_pylist()[0])
        for index in indices
    ]
    dataset_seconds = time.monotonic() - dataset_started
    targets_started = time.monotonic()
    target_payload = _legal_ir_target_payload(
        samples,
        bridge_names=BRIDGE_NAMES,
        evaluate_provers=False,
        parallel_workers=max(1, int(args.parallel_workers)),
    )
    target_seconds = time.monotonic() - targets_started
    target_views = target_payload["target_view_distributions_by_sample"]
    target_losses = target_payload["target_losses_by_sample"]
    feature_codec = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(
            parser_backend="spacy",
            spacy_model_name="definitely_missing_legal_model",
            use_flogic=True,
        )
    )

    evaluations: dict[str, Any] = {}
    output_blocks: dict[str, Any] = {}
    for name in ("teacher", "target", "candidate"):
        state = ModalAutoencoderTrainingState.load_json(paths[name])
        evidence, state_outputs = _evaluate_state(
            state,
            samples=samples,
            target_view_distributions=target_views,
            target_losses=target_losses,
            feature_codec=feature_codec,
            feature_family_logit_scale=family_scale,
            feature_embedding_weight_scale=embedding_scale,
        )
        evaluations[name] = evidence
        output_blocks[name] = state_outputs

    target_fidelity = _teacher_fidelity(
        output_blocks["target"],
        output_blocks["teacher"],
    )
    candidate_fidelity = _teacher_fidelity(
        output_blocks["candidate"],
        output_blocks["teacher"],
    )
    gate = gate_transfer_metrics(
        evaluations["target"]["metrics"],
        evaluations["candidate"]["metrics"],
        target_fidelity,
        candidate_fidelity,
    )
    cuda_verified = all(
        evidence["compute_backend"] == "torch_cuda"
        and str(evidence["compute_device"]).startswith("cuda")
        for evidence in evaluations.values()
    )
    gate["checks"]["cuda_verified"] = cuda_verified
    gate["accepted"] = bool(gate["accepted"] and cuda_verified)

    report: dict[str, Any] = {
        "artifacts": {
            name: {
                "path": str(paths[name]),
                "sha256": _sha256_file(paths[name]),
            }
            for name in ("teacher", "target", "candidate")
        },
        "bridge_names": list(BRIDGE_NAMES),
        "candidate_teacher_fidelity": candidate_fidelity,
        "dataset_load_seconds": dataset_seconds,
        "decision": "passed" if gate["accepted"] else "rejected",
        "evaluations": evaluations,
        "gate": gate,
        "schema_version": FEATURE_TRANSFER_CANARY_SCHEMA_VERSION,
        "target_build_seconds": target_seconds,
        "target_teacher_fidelity": target_fidelity,
        "transfer_report": {
            "embedded_sha256": transfer_digest,
            "file_sha256": _sha256_file(paths["transfer_report"]),
            "path": str(paths["transfer_report"]),
        },
        "validation_canary_indices": list(indices),
    }
    report["report_sha256"] = _sha256_value(report)
    _atomic_json(output, report)
    print(
        f"decision={report['decision']} cuda_verified={cuda_verified} "
        f"output={output} report_sha256={report['report_sha256']}"
    )
    return 0 if gate["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

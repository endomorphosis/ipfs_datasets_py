"""Explicit execution routes; neither route grants qualification or promotion.

Inference scores immutable weights. Training may evaluate candidates internally,
but only the explicit training route may enter the projection optimizer.
"""
from __future__ import annotations

import inspect
import math
import time
from typing import Any, Mapping, Sequence

INFERENCE_PATH = "inference"
TRAINING_PATH = "training"


class AutoencoderExecutionError(ValueError):
    """The requested operation does not match its declared execution route."""


def require_execution_path(execution_mode: str, expected_path: str) -> None:
    """Reject crossed or unknown routes before accessing the model."""
    if type(execution_mode) is not str or execution_mode not in {INFERENCE_PATH, TRAINING_PATH}:
        raise AutoencoderExecutionError("unknown autoencoder execution mode")
    if execution_mode != expected_path:
        raise AutoencoderExecutionError(f"{expected_path} operation requires the {expected_path} execution mode")


def _revision(model: Any) -> tuple[int, str]:
    state = model.state
    return int(state.state_revision), str(state.state_identity())


def gated_evaluate(model: Any, samples: Sequence[Any], *, execution_mode: str,
                   **evaluation_kwargs: Any) -> Any:
    """Return the native evaluation unchanged, rejecting any weight mutation."""
    require_execution_path(execution_mode, INFERENCE_PATH)
    kwargs = {"legal_ir_bridge_names": (), "legal_ir_evaluate_provers": False,
              "legal_ir_parallel_workers": 1, "use_sample_memory": False, **evaluation_kwargs}
    if kwargs["legal_ir_evaluate_provers"] is not False or kwargs["use_sample_memory"] is not False:
        raise AutoencoderExecutionError("inference requires provers=False and use_sample_memory=False")
    before = _revision(model)
    try:
        return model.evaluate(samples, **kwargs)
    finally:
        if _revision(model) != before:
            raise RuntimeError("inference changed autoencoder state")


def gated_projection_training(model: Any, samples: Sequence[Any], *, execution_mode: str,
                              **training_kwargs: Any) -> dict[str, Any]:
    """Return the full native optimizer report; qualification remains separate."""
    require_execution_path(execution_mode, TRAINING_PATH)
    kwargs = {"legal_ir_evaluate_provers": False,
              "projection_update_backend": "python_sparse_batch",
              "epochs": 1, "max_line_search_attempts": 1, "max_seconds": 30.0,
              "projection_max_update_families": 1, "legal_ir_parallel_workers": 1,
              **training_kwargs}
    if kwargs["legal_ir_evaluate_provers"] is not False:
        raise AutoencoderExecutionError("campaign training requires provers=False")
    if kwargs["projection_update_backend"] != "python_sparse_batch":
        raise AutoencoderExecutionError("campaign training requires the profiled python_sparse_batch backend")
    for name in ("epochs", "max_line_search_attempts", "projection_max_update_families", "legal_ir_parallel_workers"):
        if type(kwargs[name]) is not int or kwargs[name] <= 0:
            raise AutoencoderExecutionError(f"training requires a positive integer {name}")
    seconds = kwargs["max_seconds"]
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
        raise AutoencoderExecutionError("training requires a finite positive max_seconds")
    if kwargs.pop("use_sample_memory", False) is not False:
        raise AutoencoderExecutionError("campaign training requires use_sample_memory=False")
    # The native projection method disables memory internally. Preserve that
    # policy for alternate compatible methods exposing an explicit argument.
    if "use_sample_memory" in inspect.signature(model.train_generalizable_projection).parameters:
        kwargs["use_sample_memory"] = False
    return model.train_generalizable_projection(samples, **kwargs)


def _telemetry(bridge_names: Sequence[str], workers: int | None) -> dict[str, Any]:
    from .modal_autoencoder import _legal_ir_target_disk_cache_enabled
    return {"bridge_names": list(bridge_names), "legal_ir_evaluate_provers": False,
            "legal_ir_parallel_workers": workers,
            "cache_enabled": _legal_ir_target_disk_cache_enabled(), "use_sample_memory": False}


def run_inference(
    model: Any,
    samples: Sequence[Any],
    *,
    legal_ir_bridge_names: Sequence[str] = (),
    legal_ir_targets: Mapping[str, Any] | Sequence[Any] | None = None,
    legal_ir_parallel_workers: int | None = 1,
) -> dict[str, Any]:
    """Score samples with the current weights. Does not train."""

    started = time.perf_counter()
    evaluation = gated_evaluate(
        model, samples, execution_mode=INFERENCE_PATH,
        legal_ir_bridge_names=legal_ir_bridge_names,
        legal_ir_targets=legal_ir_targets,
        legal_ir_parallel_workers=legal_ir_parallel_workers,
    )
    return {
        **evaluation.to_dict(),
        **_telemetry(legal_ir_bridge_names, legal_ir_parallel_workers),
        "admitted": False,
        "cosine_similarity": float(evaluation.embedding_cosine_similarity),
        "cross_entropy_loss": float(evaluation.cross_entropy_loss),
        "formalized": False,
        "path": INFERENCE_PATH,
        "execution_path": INFERENCE_PATH,
        "training_executed": False,
        "qualified": False,
        "promotion_performed": False,
        "reconstruction_loss": float(evaluation.reconstruction_loss),
        "sample_count": int(evaluation.sample_count),
        "seconds": time.perf_counter() - started,
        "state_changed": False,
    }


def run_training(
    model: Any,
    samples: Sequence[Any],
    *,
    legal_ir_bridge_names: Sequence[str] = (),
    legal_ir_targets: Mapping[str, Any] | Sequence[Any] | None = None,
    epochs: int = 1,
    max_line_search_attempts: int = 1,
    projection_max_update_families: int = 1,
    max_seconds: float = 30.0,
) -> dict[str, Any]:
    """Run the projection search. Does not require a prior inference call."""

    revision, _identity = _revision(model)
    started = time.perf_counter()
    report = gated_projection_training(
        model, list(samples), execution_mode=TRAINING_PATH,
        legal_ir_bridge_names=legal_ir_bridge_names,
        legal_ir_targets=legal_ir_targets,
        legal_ir_parallel_workers=1,
        epochs=epochs,
        max_line_search_attempts=max_line_search_attempts,
        projection_max_update_families=projection_max_update_families,
        max_seconds=max_seconds,
    )
    return {
        **report,
        **_telemetry(legal_ir_bridge_names, 1),
        "accepted_epochs": int(report.get("accepted_epochs") or 0),
        "admitted": False,
        "formalized": False,
        "path": TRAINING_PATH,
        "execution_path": TRAINING_PATH,
        "training_executed": True,
        "qualified": False,
        "promotion_performed": False,
        "seconds": time.perf_counter() - started,
        "state_changed": int(model.state.state_revision) != revision,
        "stopped_reason": report.get("stopped_reason"),
    }

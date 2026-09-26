#!/usr/bin/env python3
"""Measure one saved daemon state with the legal-IR bridge on.

This loads a checkpoint and evaluates the three compiler-gate sentences.
It does not run an optimizer step, does not download weights, and does not
treat the receipt as a Lake admit. A target count of zero means the bridge
built no compiler targets; do not train on that result.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "0")

from ipfs_datasets_py.logic.autoformal.tree_pin import (  # noqa: E402
    LogicTreePinError,
    require_workspace_logic_tree,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (  # noqa: E402
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (  # noqa: E402
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)
def _lift_from_last_run(payload: dict[str, Any]) -> dict[str, Any]:
    path = REPO_ROOT / "scripts" / "ops" / "logic" / "review_autoencoder_weight_runs.py"
    spec = importlib.util.spec_from_file_location("review_autoencoder_weight_runs_bridge", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"lift scorer is not at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.lift_from_last_run(payload)


BRIDGE_NAMES = (
    "modal_frame_logic",
    "deontic_norms",
    "fol_tdfol",
    "cec_dcec",
    "external_prover_router",
)
DEFAULT_STATE = (
    REPO_ROOT
    / "workspace"
    / "todo-queues"
    / "legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json"
)
# July 23 ten-minute smoke, deontic family. A direction only, not an admit.
SMOKE_DEONTIC = {
    "ir_cosine_similarity": 0.987677451831,
    "ir_cross_entropy_loss": 0.597011295045,
    "run_id": "legal-ir-10m-smoke-20260723T033130Z",
}
GATE_SENTENCES = (
    ("backup", "Company A shall submit backup report within 10 days unless emergency."),
    ("prohibit", "The agency shall not disclose records."),
    ("minimum", "The officer shall retain the file for at least 20 days."),
)


def gate_samples() -> list[Any]:
    return [
        build_us_code_sample(title="gate", section=section, text=text)
        for section, text in GATE_SENTENCES
    ]


def _family_metrics(evaluation: Any) -> dict[str, Any]:
    raw = getattr(evaluation, "legal_ir_view_family_metrics", {}) or {}
    return {
        str(family): {str(name): float(value) for name, value in dict(metrics).items()}
        for family, metrics in dict(raw).items()
    }


def measurement_receipt(
    evaluation: Any,
    *,
    state_path: Path,
    bridge_names: tuple[str, ...] = BRIDGE_NAMES,
) -> dict[str, Any]:
    """Build a last-run shaped receipt. Reconstruction cosine is not IR lift."""

    losses = {
        str(name): float(value)
        for name, value in dict(getattr(evaluation, "legal_ir_losses", {}) or {}).items()
    }
    try:
        target_count = int(getattr(evaluation, "legal_ir_target_count", 0) or 0)
    except (TypeError, ValueError):
        target_count = 0
    payload = {
        "bridge_names": list(bridge_names),
        "stopped_reason": "bridge_on_measurement",
        "final_evaluation": {
            "legal_ir_losses": losses,
            "legal_ir_target_count": target_count,
            "legal_ir_view_distribution": {
                str(name): float(value)
                for name, value in dict(
                    getattr(evaluation, "legal_ir_view_distribution", {}) or {}
                ).items()
            },
            "sample_count": int(getattr(evaluation, "sample_count", 0) or 0),
        },
        "steps": [
            {
                "bridge_loss_signal_count": len(losses),
                "improved": False,
            }
        ],
    }
    lift = _lift_from_last_run(payload)
    deontic = _family_metrics(evaluation).get("deontic", {})
    return {
        "admitted": False,
        "bridge_names": list(bridge_names),
        "deontic_family_metrics": deontic,
        "legal_ir_losses": losses,
        "legal_ir_target_count": target_count,
        "legal_ir_view_family_metrics": _family_metrics(evaluation),
        "lift": lift,
        "ontology_captures": list(getattr(evaluate_state, "last_ontology_captures", []) or []),
        "optimizer_step": False,
        "smoke_deontic_reference": dict(SMOKE_DEONTIC),
        "state_path": str(state_path),
        "training_allowed": target_count > 0 and lift["status"] != "bridge_off",
    }


def _evaluate(autoencoder: AdaptiveModalAutoencoder) -> Any:
    return autoencoder.evaluate(
        gate_samples(),
        legal_ir_bridge_names=BRIDGE_NAMES,
        legal_ir_evaluate_provers=False,
        legal_ir_parallel_workers=1,
        use_sample_memory=False,
    )


def evaluate_state(state_path: Path) -> Any:
    state = ModalAutoencoderTrainingState.load_json(state_path)
    autoencoder = AdaptiveModalAutoencoder(state=state)
    evaluation = _evaluate(autoencoder)
    evaluate_state.last_ontology_captures = list(getattr(autoencoder, "last_ontology_captures", []))
    return evaluation


def _loss(metrics: Mapping[str, Any], name: str) -> float | None:
    try:
        value = float(dict(metrics).get(name))
    except (TypeError, ValueError):
        return None
    return value


def train_once(state_path: Path, output_state: Path) -> dict[str, Any]:
    """One projection epoch on the gate sentences. Does not write ``state_path``."""

    if output_state.resolve() == state_path.resolve():
        raise ValueError("refusing to overwrite the daemon checkpoint")
    state = ModalAutoencoderTrainingState.load_json(state_path)
    autoencoder = AdaptiveModalAutoencoder(state=state)
    samples = gate_samples()
    report = autoencoder.train_generalizable_projection(
        samples,
        validation_samples=samples,
        legal_ir_bridge_names=BRIDGE_NAMES,
        legal_ir_evaluate_provers=False,
        legal_ir_parallel_workers=1,
        epochs=1,
        max_seconds=180,
        max_line_search_attempts=1,
        projection_max_update_families=1,
        projection_update_backend="python_sparse_batch",
    )
    accepted = int(report.get("accepted_epochs") or 0)
    saved = False
    if accepted > 0:
        autoencoder.state.save_json(output_state)
        saved = True
    before_losses = dict(report.get("before", {}).get("legal_ir_losses") or {})
    after_losses = dict(report.get("after", {}).get("legal_ir_losses") or {})
    before_ce = _loss(before_losses, "legal_ir_view_cross_entropy_loss")
    after_ce = _loss(after_losses, "legal_ir_view_cross_entropy_loss")
    ir_ce_delta = None
    if before_ce is not None and after_ce is not None:
        ir_ce_delta = after_ce - before_ce
    before_family = dict(report.get("before", {}).get("legal_ir_view_family_metrics") or {})
    after_family = dict(report.get("after", {}).get("legal_ir_view_family_metrics") or {})
    before_cos = _loss(dict(before_family.get("deontic") or {}), "ir_cosine_similarity")
    after_cos = _loss(dict(after_family.get("deontic") or {}), "ir_cosine_similarity")
    ir_cos_delta = None
    if before_cos is not None and after_cos is not None:
        ir_cos_delta = after_cos - before_cos
    target_count = int(report.get("after", {}).get("legal_ir_target_count") or 0)
    step: dict[str, Any] = {
        "bridge_loss_signal_count": 1,
        "improved": False,
    }
    if accepted > 0:
        if ir_ce_delta is not None:
            step["validation_ir_cross_entropy_delta"] = ir_ce_delta
        if ir_cos_delta is not None:
            step["validation_ir_cosine_delta"] = ir_cos_delta
    payload = {
        "bridge_names": list(BRIDGE_NAMES),
        "stopped_reason": str(report.get("stopped_reason") or "projection_epoch"),
        "final_evaluation": {
            "legal_ir_losses": after_losses,
            "legal_ir_target_count": target_count,
        },
        "steps": [step],
    }
    return {
        "accepted_epochs": accepted,
        "admitted": False,
        "bridge_names": list(BRIDGE_NAMES),
        "corpus": "three_gate_sentences_not_the_eight_row_canary",
        "elapsed_seconds": report.get("elapsed_seconds"),
        "ir_cosine_delta": ir_cos_delta,
        "ir_cross_entropy_delta": ir_ce_delta,
        "legal_ir_target_count": target_count,
        "lift": _lift_from_last_run(payload),
        "optimizer_step": True,
        "saved_state": str(output_state) if saved else "",
        "source_state": str(state_path),
        "stopped_reason": payload["stopped_reason"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--train-once", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )
    args = parser.parse_args(argv)
    if args.output is None:
        name = (
            "restart12-bridge-on-one-step.json"
            if args.train_once
            else "restart12-bridge-on-measurement.json"
        )
        args.output = REPO_ROOT / "workspace" / "todo-queues" / name
    try:
        require_workspace_logic_tree()
    except LogicTreePinError as exc:
        print(str(exc))
        return 2
    state_path = args.state.resolve()
    if not state_path.is_file() or state_path.stat().st_size <= 0:
        print(f"daemon state is missing: {state_path}")
        return 2
    output = args.output.resolve()
    if output.exists():
        print(f"refusing to overwrite measurement: {output}")
        return 2
    if args.train_once:
        receipt = train_once(
            state_path,
            output.with_name("restart12-bridge-on-one-step.state.json"),
        )
    else:
        evaluation = evaluate_state(state_path)
        receipt = measurement_receipt(evaluation, state_path=state_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"legal_ir_target_count={receipt['legal_ir_target_count']} "
        f"status={receipt['lift']['status']} "
        f"output={output}"
    )
    if receipt["legal_ir_target_count"] <= 0:
        print("bridge names were set and the target count is 0; do not train")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

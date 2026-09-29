#!/usr/bin/env python3
"""Controlled before/after NaN acceptance evidence; no native/proof claim."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import math
import sys
from types import SimpleNamespace

PACKAGE = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
RELATIVE = Path("ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py")


def exercise(source: Path, label: str, *, finite: bool = False):
    name = PACKAGE + "._controlled_nonfinite_" + label
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    state = module.ModalAutoencoderTrainingState(legal_ir_view_logits={"fixture": 0.0})
    model = module.AdaptiveModalAutoencoder(state=state, compute_device="python")
    train = [SimpleNamespace(sample_id="train", normalized_text="training", embedding_vector=[1.0])]
    validation = [SimpleNamespace(sample_id="validation", normalized_text="validation", embedding_vector=[-1.0])]
    updates = []
    def evaluate(rows, **kwargs):
        assert kwargs["use_sample_memory"] is False
        loss = (0.4 if finite else float("nan")) if state.legal_ir_view_logits["fixture"] else 0.5
        return module.AutoencoderEvaluation(len(rows), 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, {},
                    legal_ir_target_count=len(rows), legal_ir_losses={"legal_ir_multiview_total_loss": loss})
    def update(rows, **kwargs):
        assert rows == train
        updates.append(kwargs["learning_rate"])
        state.legal_ir_view_logits["fixture"] = 1.0
        return {name: {} for name in ("gradient_norms_by_family", "gradient_norms_by_head",
            "head_family_gradient_norms", "head_family_update_norms", "update_norms_by_family", "update_norms_by_head")}
    model.evaluate = evaluate
    model._apply_projection_update_batch = update
    model._select_hard_examples_for_projection = lambda rows, **kwargs: list(rows)
    before = state.to_json()
    result = model.train_generalizable_projection(train, validation_samples=validation,
                legal_ir_bridge_names=("deontic_norms",), legal_ir_evaluate_provers=False,
                epochs=1, max_seconds=5, max_line_search_attempts=1,
                projection_max_update_families=1, projection_update_backend="python_sparse_batch")
    epoch = result["epoch_reports"][0]
    candidate = epoch["candidate_reports"][0]
    return {
        "source_path": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "accepted_epochs": result["accepted_epochs"],
        "weight_before": 0.0, "weight_after": state.legal_ir_view_logits["fixture"],
        "state_unchanged": state.to_json() == before,
        "after_loss_finite": math.isfinite(result["after"]["legal_ir_losses"]["legal_ir_multiview_total_loss"]),
        "candidate_objective_delta": candidate["objective_delta"],
        "candidate_acceptance_source": candidate["acceptance_source"],
        "nonfinite_validation_metrics": candidate.get("nonfinite_validation_metrics", []),
        "transaction_closed": state._active_state_transaction is None,
        "update_call_count": len(updates),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4])
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root))
    base = Path(__file__).resolve().parent
    before = exercise(base / "before" / RELATIVE, "before")
    after = exercise(root / RELATIVE, "after")
    fixed_before = exercise(base / "before" / RELATIVE, "fixed_before", finite=True)
    fixed_after = exercise(root / RELATIVE, "fixed_after", finite=True)
    fixed_fields = ("accepted_epochs", "weight_after", "candidate_objective_delta",
                    "candidate_acceptance_source", "update_call_count", "transaction_closed")
    checks = {
        "finite_fixed_candidate_parity": all(fixed_before[key] == fixed_after[key] for key in fixed_fields),
        "before_reproduced_invalid_acceptance": before["accepted_epochs"] == 1 and not before["after_loss_finite"] and before["weight_after"] == 1.0,
        "after_rejected_and_rolled_back": after["accepted_epochs"] == 0 and after["state_unchanged"] and after["weight_after"] == 0.0,
        "after_preserved_finite_baseline": after["after_loss_finite"],
        "both_transactions_closed": before["transaction_closed"] and after["transaction_closed"],
    }
    receipt = {"schema_version": "controlled-nonfinite-projection-guard/v1", "scope": "mocked metrics and sparse nudge, no native training",
               "admitted": False, "lake_build_ran": False, "formalized": False,
               "before": before, "after": after,
               "finite_fixed_before": fixed_before, "finite_fixed_after": fixed_after, "checks": checks, "passed": all(checks.values())}
    output = base / "nonfinite-guard-comparison.json"
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"receipt": str(output), "passed": receipt["passed"]}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Render audited native convergence curves. Import matplotlib only after audit.

Example: python3 plot_convergence.py --audit native-three-arm-audit.json
The two panels show observed epoch endpoints, not a convergence certificate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

ARMS = ("fixed", "adaptive_lr", "adaptive_momentum")
LABELS = {"fixed": "Fixed search", "adaptive_lr": "Adaptive learning rate",
          "adaptive_momentum": "Adaptive + sparse momentum (beta=0.5)"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text())


def main() -> int:
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, default=base / "native-three-arm/comparison.json")
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=base / "convergence-curves.svg")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    comparison_path, audit_path = args.comparison.resolve(), args.audit.resolve()
    output = args.output.resolve()
    receipt_path = (args.receipt or output.with_suffix(".receipt.json")).resolve()
    if output.suffix.lower() != ".svg":
        raise ValueError("a standalone SVG output is required")
    if output.exists() or receipt_path.exists():
        raise FileExistsError("plot output or receipt already exists; use a fresh output name")
    comparison, audit = read(comparison_path), read(audit_path)
    if audit.get("passed") is not True or audit.get("failures"):
        raise ValueError("a complete passing native evidence audit is required")
    if comparison.get("schema") != "autoencoder-convergence-comparison/v1":
        raise ValueError("unexpected comparison schema")
    if not comparison.get("same_fixed_parent") or not comparison.get("same_effective_model_config"):
        raise ValueError("comparison does not bind the same seed/configuration")
    if comparison["producer_manifest"] != audit["producer_manifest"]:
        raise ValueError("comparison and audit source producers differ")
    rows = {row["arm"]: row for row in comparison["arms"]}
    audited_rows = {row["arm"]: row for row in audit["arms"]}
    if set(rows) != set(ARMS) or set(audited_rows) != set(ARMS):
        raise ValueError("all three completed arms are required")
    curves, threshold_rows = {}, []
    for name in ARMS:
        row, audited = rows[name], audited_rows[name]
        for field in ("initial_objective", "final_objective", "attempted_epochs", "accepted_epochs", "qualified"):
            if row[field] != audited[field]:
                raise ValueError(f"comparison and audit differ for {name}:{field}")
        curve = row["curve"]
        if len(curve) != row["attempted_epochs"] + 1 or curve[0]["epoch"] != 0:
            raise ValueError("incomplete observed epoch curve")
        epochs, evaluations, objectives = [], [], []
        for point in curve:
            epoch = point["epoch"]
            # Harness cumulative counts include one baseline tuning evaluation;
            # remove exactly that baseline for the candidate-evaluation axis.
            count = point["cumulative_tuning_search_evaluations"] - 1
            objective = point["committed_objective"]
            if type(epoch) is not int or type(count) is not int or count < 0 or not math.isfinite(objective):
                raise ValueError("invalid observed curve point")
            if epochs and (epoch <= epochs[-1] or count < evaluations[-1]):
                raise ValueError("nonmonotonic observed search coordinates")
            epochs.append(epoch)
            evaluations.append(count)
            objectives.append(objective)
        curves[name] = {"epochs": epochs, "candidate_tuning_evaluations": evaluations,
                        "committed_tuning_objective": objectives}
        threshold_rows.append({"arm": name, "threshold": row["fixed_final_objective_threshold"],
                               "first_observed_epoch": row["threshold_first_observed_epoch"],
                               "first_observed_training_seconds": row["threshold_first_observed_training_seconds"]})
    data_hash, audit_hash, script_hash = sha(comparison_path), sha(audit_path), sha(Path(__file__))
    # No heavy plotting import until all complete audit/curve guards succeed.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    matplotlib.rcParams.update({"font.family": "DejaVu Sans", "svg.hashsalt": data_hash,
                               "axes.spines.top": False, "axes.spines.right": False,
                               "axes.grid": True, "grid.alpha": 0.2, "font.size": 10})
    figure, axes = plt.subplots(1, 2, figsize=(11.0, 4.8), sharey=True)
    colors, markers = ("#1d4ed8", "#c2410c", "#047857"), ("o", "s", "D")
    for name, color, marker in zip(ARMS, colors, markers):
        curve = curves[name]
        for axis, x_values in zip(axes, (curve["epochs"], curve["candidate_tuning_evaluations"])):
            axis.plot(x_values, curve["committed_tuning_objective"], color=color,
                      marker=marker, markersize=5, linewidth=1.6, label=LABELS[name])
    axes[0].set_xlabel("Completed search epochs")
    axes[1].set_xlabel("Candidate tuning evaluations (baseline excluded)")
    axes[0].set_ylabel("Guarded tuning objective (lower is better)")
    axes[0].set_title("Quality per epoch", loc="left", fontsize=11)
    axes[1].set_title("Quality per candidate evaluation", loc="left", fontsize=11)
    for axis in axes:
        axis.xaxis.set_major_locator(MaxNLocator(integer=True))
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.065), ncol=3, frameon=False)
    figure.suptitle("Synthetic optimizer comparison: 8 training rows, 1 tuning row, same parent", fontsize=12, x=0.075, ha="left")
    figure.text(0.075, 0.025, "Points are observed epoch endpoints. One run per arm; final qualification is separate. No global-minimum claim.", fontsize=8, color="#475569")
    figure.subplots_adjust(left=0.075, right=0.985, bottom=0.24, top=0.82, wspace=0.14)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, format="svg", metadata={"Date": None,
        "Description": f"Audited comparison SHA256 {data_hash}; script SHA256 {script_hash}; source producer {comparison['producer_manifest']}."})
    plt.close(figure)
    if sha(comparison_path) != data_hash or sha(audit_path) != audit_hash:
        output.unlink()
        raise ValueError("evidence changed while rendering")
    receipt = {
        "schema_version": "autoencoder-convergence-plot/v1",
        "comparison": {"path": str(comparison_path), "sha256": data_hash},
        "audit": {"path": str(audit_path), "sha256": audit_hash, "passed": True},
        "plot_script": {"path": str(Path(__file__).resolve()), "sha256": script_hash},
        "output": {"path": str(output), "sha256": sha(output), "format": "svg"},
        "producer_manifest": comparison["producer_manifest"], "matplotlib_version": matplotlib.__version__,
        "plotted_values": curves, "observed_thresholds": threshold_rows,
        "sample_counts": {"training": 8, "tuning": 1}, "same_parent": True,
        "scope": "One synthetic run per treatment; curves contain committed epoch-end observations. Threshold times include training setup and exclude upstream loading/final qualification.",
        "admitted": False, "global_minimum_claim": False,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with receipt_path.open("x") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"output": str(output), "receipt": str(receipt_path), "sha256": receipt["output"]["sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

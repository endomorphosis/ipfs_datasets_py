#!/usr/bin/env python3
"""Render training-only loss diagnostics from hash-pinned experiment receipts."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_clause_consistency_experiment as run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generation', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    frozen = run.read(args.generation)
    run.require(frozen['all_training_selection_and_generation_complete'] is True,
                'complete frozen generation required')
    selection = run.read_ref(frozen['selections'])
    trials = selection['trials']
    output = Path(args.output).resolve()
    output.mkdir(exist_ok=False)
    data, refs = {}, []
    for trial in trials:
        components = []
        for stage in trial['stages']:
            receipt = run.read_ref(stage['training_report'])
            components.extend(receipt['batch_loss_components'])
            refs.append(stage['training_report'])
        run.require(len(components) == 800, 'all800 fitting steps required')
        data[(trial['objective'], trial['architecture'], trial['seed'])] = components

    fig, axes = plt.subplots(2, 2, figsize=(10, 7), sharex=True, constrained_layout=True)
    colors = {'ce': '#2766a8', 'consistency': '#c05824'}
    summaries = []
    for row_index, architecture in enumerate(run.ARCHITECTURES):
        for column, (key, label) in enumerate((('base_ce', 'Supervised loss'), ('consistency_js', 'Role consistency JS'))):
            ax = axes[row_index, column]
            for objective in run.OBJECTIVES:
                values = np.array([[r[key] for r in data[(objective, architecture, seed)]] for seed in run.SEEDS])
                smooth = np.array([np.convolve(v, np.ones(50) / 50, mode='valid') for v in values])
                x = np.arange(50, 801)
                ax.plot(x, smooth.mean(0), color=colors[objective], label=objective)
                ax.fill_between(x, smooth.min(0), smooth.max(0), color=colors[objective], alpha=.12)
                summaries.append({'architecture': architecture, 'objective': objective, 'component': key,
                    'mean_first50_steps': float(values[:, :50].mean()), 'mean_last50_steps': float(values[:, -50:].mean()),
                    'per_seed_last50_mean': {str(seed): float(values[i, -50:].mean()) for i, seed in enumerate(run.SEEDS)}})
            ax.set_title(architecture.capitalize() + ' — ' + label)
            ax.set_ylabel('Loss')
            ax.grid(alpha=.2)
            ax.legend(frameon=False)
            if row_index == 1:
                ax.set_xlabel('Additional optimizer updates')
    fig.suptitle('Clause decoder training: matched batches and pretrained parents\n50-step rolling means; shading is seed range, not a confidence interval', fontsize=11)
    for extension in ('png', 'svg'):
        fig.savefig(output / ('training-losses.' + extension), dpi=160)
    plt.close(fig)
    run.write(output / 'training-loss-summary.json', {'schema': 'legal-clause-consistency-training-curves/v1',
        'generation': run.ref(args.generation), 'producer': run.ref(__file__), 'training_receipts': refs,
        'smoothing_window': 50, 'shading': 'range of three fixed paired seeds, not statistical uncertainty',
        'summaries': summaries, 'training_loss_is_accuracy_evidence': False, 'fresh_targets_opened': False,
        'figures': [run.ref(output / ('training-losses.' + ext)) for ext in ('png', 'svg')]})


if __name__ == '__main__':
    main()

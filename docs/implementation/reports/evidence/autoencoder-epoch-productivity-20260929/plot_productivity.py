#!/usr/bin/env python3
"""Plot audited synthetic optimizer productivity with exact evidence bindings."""
from pathlib import Path
import argparse
import csv
import hashlib
import io
import json

BASE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_bytes())


def reference(path):
    data = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def exclusive(path, data):
    with path.open('xb') as stream:
        stream.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=BASE / 'native-three-arm')
    parser.add_argument('--audit', type=Path, default=BASE / 'native-audit.json')
    args = parser.parse_args()
    audit, comparison = read(args.audit), read(args.run / 'comparison.json')
    if not audit['passed'] or audit.get('failures') or comparison['experiment'] != 'main':
        raise ValueError('Only the audited matched main experiment is plotted')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9, 'svg.hashsalt': 'autoencoder-epoch-productivity-20260929'})
    colors = {'baseline_adaptive': '#3f5263', 'productive_lr': '#168777', 'productive_momentum': '#a453b8'}
    names = {'baseline_adaptive': 'Adaptive baseline', 'productive_lr': 'Productive LR', 'productive_momentum': 'Productive momentum'}
    figure, axes = plt.subplots(1, 3, figsize=(12.6, 4.1), sharey=True)
    csv_buffer = io.StringIO()
    csv_writer = csv.writer(csv_buffer, lineterminator='\n')
    csv_writer.writerow(['arm', 'epoch_attempt', 'accepted', 'committed_tuning_objective',
                         'cumulative_training_seconds', 'cumulative_tuning_search_evaluations'])
    for arm in comparison['arms']:
        curve = arm['curve']
        color, label = colors[arm['arm']], names[arm['arm']]
        for point in curve:
            csv_writer.writerow([arm['arm'], point['epoch'], point['accepted'], point['committed_objective'],
                                 point['cumulative_training_elapsed_seconds'], point['cumulative_tuning_search_evaluations']])
        ys = [point['committed_objective'] for point in curve]
        axes[0].plot([point['epoch'] for point in curve], ys, marker='o', markersize=4, color=color, label=label)
        axes[1].plot([point['cumulative_tuning_search_evaluations'] for point in curve], ys,
                     marker='o', markersize=4, color=color)
        timed = [point for point in curve if point['cumulative_training_elapsed_seconds'] is not None]
        axes[2].plot([point['cumulative_training_elapsed_seconds'] for point in timed],
                     [point['committed_objective'] for point in timed], marker='o', markersize=4, color=color)
    threshold = comparison['arms'][0]['final_objective']
    axes[2].axhline(threshold, color='#83909a', linestyle='--', linewidth=.9, label='Baseline final objective')
    for ax in axes:
        ax.grid(True, alpha=.22)
        ax.spines[['top', 'right']].set_visible(False)
    axes[0].set_xlabel('Epoch attempt')
    axes[1].set_xlabel('Tuning search evaluations\n(initial + candidate evaluations)')
    axes[2].set_xlabel('Measured cumulative training wall (s)')
    axes[0].set_ylabel('Committed tuning objective (lower is better)')
    axes[0].legend(loc='upper right', frameon=False, fontsize=8)
    axes[2].legend(loc='upper right', frameon=False, fontsize=7.5)
    qualified = sum(bool(arm['qualified']) for arm in comparison['arms'])
    figure.suptitle('Synthetic optimizer productivity · unchanged objective and qualification gates', fontsize=12)
    figure.text(.06, .06, f'8 training / 1 tuning rows; all 5 bridges, provers off, disk cache off, IR workers=1, sample memory off. Qualified arms: {qualified}/3.', fontsize=8)
    figure.text(.06, .02, 'One ordered experiment. Timing points are completed epoch observations; no global-minimum or federal-law generalization claim.', fontsize=8, color='#4b5563')
    figure.tight_layout(rect=(.025, .13, 1, .92))
    buffer = io.BytesIO()
    figure.savefig(buffer, format='svg', metadata={'Date': None, 'Title': 'Synthetic autoencoder epoch productivity'})
    plt.close(figure)
    # Normalize before hashing/copying so publication whitespace checks validate
    # the exact immutable bytes; no SVG exemption is required.
    svg = ('\n'.join(line.rstrip() for line in buffer.getvalue().decode().splitlines()) + '\n').encode()
    svg_path, data_path = BASE / 'productivity-curves.svg', BASE / 'productivity-curve-data.csv'
    exclusive(svg_path, svg)
    exclusive(data_path, csv_buffer.getvalue().encode())
    receipt = {'schema': 'autoencoder-productivity-plot/v1', 'audit': reference(args.audit),
        'comparison': reference(args.run / 'comparison.json'), 'plot': reference(svg_path), 'data': reference(data_path),
        'matplotlib_version': matplotlib.__version__, 'trailing_whitespace_normalized_before_hashing': True,
        'time_axis_scope': 'Only actual cumulative_training_elapsed_seconds at completed epoch reports; no fabricated epoch-zero time or nested-profile duration sums.',
        'tuning_search_count_scope': 'Initial tuning evaluation plus candidate tuning evaluations; separate training-cache prime and final qualification are excluded.',
        'qualification_count': qualified, 'admitted': False, 'global_minimum_claim': False}
    exclusive(BASE / 'productivity-plot.json', (json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode())
    print(json.dumps({'plot': str(svg_path), 'qualified': qualified, 'admitted': False}))


if __name__ == '__main__':
    main()

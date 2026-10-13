"""Freeze one completed53-file bundle before new trained-reference scoring.

Checkpoint bytes stay opaque. Reference payloads are not opened. This grants
only exposed authored diagnostic scoring, never semantic qualification.
"""
import os
from pathlib import Path

import run_split_features as r

F = Path(__file__).resolve().parent


def metadata(path):
    r.require('checkpoint' not in path.name and 'reference-packet' not in path.name,
              'model or reference JSON parsing forbidden')
    return r.read(path)


def expected_names():
    names = {'cell-checkpoint.json', 'cell-training.json', 'data-schedule-before-models.json',
             'summary.json', 'trained-modality-retention.json'}
    for stage in ('initial', 'trained'):
        names.add(stage + '-parity.json')
        names.update(stage + '-parity-' + control + '.json' for control in
                     ('zeros', 'alternate_placeholders', 'disabled', 'rotated_placeholders'))
    for state in ('baseline', 'trained'):
        for panel in ('old_tune', 'fresh_tune', 'fresh_challenge', 'old_authored_eval', 'authored_dev', 'authored_eval', 'law'):
            names.update(state + '-' + panel + '-' + kind + '.json' for kind in ('raw', 'joint'))
            if panel not in ('authored_eval', 'law'):
                names.add(state + '-' + panel + '-score.json')
    r.require(len(names) == 53, 'exact registered inventory required')
    return names


def main():
    output = F / 'split-feature-output-freeze-v01.json'
    r.require(not os.path.lexists(output), 'exclusive freeze output required')
    registration_path = F / 'registration-v01.json'
    registration = metadata(registration_path)
    plan_path = F / 'split-features-plan-v01.json'
    plan = metadata(plan_path); r.validate_plan(plan)
    attempt = r.RUN_ROOT / plan['attempt_name']; results = attempt / 'results'
    summary_path = results / 'summary.json'; summary = metadata(summary_path)
    terminal_path = attempt / 'guardian-exit.json'; terminal = metadata(terminal_path)
    r.require(summary['schema'] == 'split-feature-cell-results/v1' and summary['status'] == 'completed'
              and summary['actual_new_updates'] == 32 and summary['cell'] == plan['cell']
              and summary['actual_encoder_calls'] == 0 and summary['latent_enabled'] is False
              and summary['actual_encoder_calls_scope'] == 'external_latent_or_context_encoders'
              and summary['initial_parent_head_parity']['checked_before_training'] is True
              and summary['initial_parent_head_parity']['total_source_rows'] == 392
              and summary['initial_parent_head_parity']['all_four_heads_and_tokens_exact'] is True,
              'completed source-only32 with initial392 parity required')
    r.require(type(terminal['returncode']) is int and type(terminal['child_returncode']) is int
              and terminal['returncode'] == terminal['child_returncode'] == 0
              and terminal['artifacts_durable'] is True and terminal['resource_reservation_released'] is True,
              'successful durable released guardian required')
    files = list(results.iterdir())
    r.require({path.name for path in files} == expected_names()
              and all(path.is_file() and not path.is_symlink() for path in files), 'closed53-file inventory required')
    inventory = {}
    for path in sorted(files):
        descriptor = r.pin(path)
        inventory[str(path)] = {k: descriptor[k] for k in ('bytes', 'sha256')}
    for path, consumed in r.READ_PINS.items():
        if path in inventory:
            r.require(inventory[path] == {k: consumed[k] for k in ('bytes', 'sha256')},
                      'parsed result differs from frozen inventory identity')
    runner_pin = r.pin(F / 'run_split_features.py'); export_pin = r.pin(F / 'training-export-v01.json')
    r.require(plan['artifacts'].get(runner_pin['path']) == {k: runner_pin[k] for k in ('bytes', 'sha256')}
              and export_pin == plan['data_export'] == registration['data_export'],
              'manifest producer/export descriptors differ from admitted identities')
    cell = dict(cell=plan['cell'], plan=r.READ_PINS[str(plan_path)], summary=r.READ_PINS[str(summary_path)],
                guardian_terminal=r.READ_PINS[str(terminal_path)], pre_admission=r.pin(attempt / 'pre-admission.json'),
                results=inventory)
    manifest = dict(schema='split-feature-output-freeze/v1', all_outputs_frozen=True,
                    authorizes_authored_eval_scoring=True, new_trained_outputs_scored_before_freeze=False,
                    reference_packet_previously_scored=True, freeze_scope='new_single_cell_outputs_only; references previously exposed',
                    independent_blinding=False, reference_builder_author_visible=True,
                    runner=runner_pin, registration=r.READ_PINS[str(registration_path)],
                    training_export=export_pin, reference_packet=registration['reference_packet'],
                    cells=[cell])
    for path, expected in plan['artifacts'].items():
        r.require({k: r.pin(path)[k] for k in ('bytes', 'sha256')} == expected, 'closing admitted artifact drift')
    for path, expected in inventory.items():
        r.require({k: r.pin(path)[k] for k in ('bytes', 'sha256')} == expected, 'closing result drift')
    for path, expected in r.READ_PINS.items():
        r.require(r.pin(path) == expected, 'closing consumed metadata drift')
    descriptor = r.write(output, manifest); output.chmod(0o444)
    fd = os.open(F, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    print(r.json.dumps(dict(status='single_output_frozen_before_eval_scoring', cells=1, updates=32,
                           results=53, manifest=descriptor)))


if __name__ == '__main__':
    main()

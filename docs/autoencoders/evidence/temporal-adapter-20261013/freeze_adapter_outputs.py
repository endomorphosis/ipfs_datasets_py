"""Seal both completed actual output bundles before reference scoring.

Checkpoints are streamed as opaque bytes. Only own new output file metadata and
one exclusive freeze receipt are written; no model or resource API is invoked.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

F = Path(__file__).resolve().parent
RUN = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
CELLS = ('temporal-ce-control', 'temporal-anchor-margin')
PANELS = ('old_tune', 'fresh_tune', 'fresh_challenge', 'old_authored_eval', 'authored_dev', 'authored_eval', 'law')
OUTPUT = F / 'two-cell-output-freeze-v01.json'
sys.dont_write_bytecode = True


def require(value, message):
    if not value:
        raise ValueError(message)


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and not path.is_symlink(), 'Physical input required')
    before = path.stat()
    require(stat.S_ISREG(before.st_mode), 'Ordinary file required')
    h = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            size += len(block)
            h.update(block)
    after = path.stat()
    ident = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    require(ident(before) == ident(after), 'Input changed while hashing')
    return dict(path=str(path), bytes=size, sha256=h.hexdigest())


def read(path):
    path = Path(path)
    require('checkpoint' not in path.name and 'reference-packet' not in path.name, 'Checkpoint/reference parsing forbidden')
    before = pin(path)
    require(before['bytes'] <= 2 * 1024 * 1024, 'Bounded metadata required')
    raw = path.read_bytes()
    require(len(raw) == before['bytes'] and hashlib.sha256(raw).hexdigest() == before['sha256'] and pin(path) == before,
            'Consumed metadata identity differs')
    return json.loads(raw)


def names():
    result = {'summary.json', 'cell-checkpoint.json', 'cell-training.json', 'data-schedule-before-models.json',
              'initial-parent-head-parity.json', 'trained-frozen-head-retention.json', 'trained-training168-raw.json'}
    result.update(state + '-' + panel + '-' + kind + '.json' for state in ('baseline', 'trained')
                  for panel in PANELS for kind in ('raw', 'joint'))
    result.update(state + '-parity.json' for state in ('initial', 'trained'))
    result.update(state + '-parity-' + control + '.json' for state in ('initial', 'trained')
                  for control in ('zeros', 'alternate_placeholders', 'disabled', 'rotated_placeholders'))
    require(len(result) == 45, 'Closed45-file geometry differs')
    return result


def main():
    require(not OUTPUT.exists(), 'Exclusive freeze receipt required')
    cells, plans = [], []
    # Validate BOTH successful terminals before changing any output file mode.
    for cell in CELLS:
        plan_path = F / (cell + '-plan-v01.json')
        plan = read(plan_path)
        attempt = RUN / plan['attempt_name']
        require(plan['cell'] == cell and plan['attempt_name'] == 'temporal-adapter-20261013-' + cell + '-01', 'Exact plan/cell required')
        terminal_path = attempt / 'guardian-exit.json'
        terminal = read(terminal_path)
        require(terminal['returncode'] == terminal['child_returncode'] == 0 and terminal['artifacts_durable'] is True
                and terminal['resource_reservation_released'] is True, 'Successful durable released terminal required')
        root = attempt / 'results'
        require({path.name for path in root.iterdir()} == names(), 'Complete closed45-file result inventory required')
        summary = read(root / 'summary.json')
        require(summary['status'] == 'completed' and summary['cell'] == cell and summary['actual_new_updates'] == 32
                and summary['reference_scoring_performed'] is False and summary['reference_labels_in_diagnostics'] is False,
                'Completed unscored cell required')
        inventory = {str(path): {k: pin(path)[k] for k in ('bytes', 'sha256')} for path in sorted(root.iterdir())}
        cells.append(dict(cell=cell, plan=pin(plan_path), summary=pin(root / 'summary.json'),
                          guardian_terminal=pin(terminal_path), results=inventory))
        plans.append(plan)
    require(plans[0]['reference_source_export'] == plans[1]['reference_source_export']
            and plans[0]['reference_packet'] == plans[1]['reference_packet']
            and plans[0]['evaluation_contract'] == plans[1]['evaluation_contract'], 'Common evaluation boundary differs')
    for cell in cells:
        for path, expected in cell['results'].items():
            actual = pin(Path(path))
            require({k: actual[k] for k in ('bytes', 'sha256')} == expected, 'Output drift before freezing')
            Path(path).chmod(0o444)
            require({k: pin(Path(path))[k] for k in ('bytes', 'sha256')} == expected, 'Output bytes changed during mode freeze')
    value = dict(schema='temporal-adapter-two-cell-freeze/v1', all_outputs_frozen=True,
        authorizes_authored_eval_scoring=True, cells=cells, result_file_count=90, actual_returned_optimizer_updates=64,
        evaluation_contract=plans[0]['evaluation_contract'], reference_source_export=plans[0]['reference_source_export'],
        reference_packet=plans[0]['reference_packet'], freezer=pin(Path(__file__).resolve()),
        observed_at_utc=datetime.now(timezone.utc).isoformat(), new_pair_outputs_scored_before_freeze=False,
        independent_blinding=False, reference_packet_previously_exposed=True, checkpoint_JSON_parses=0,
        model_calls=0, resource_API_calls=0, default_promotion=False)
    with OUTPUT.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    print(json.dumps(dict(output=pin(OUTPUT), cells=2, files=90, updates=64)))


if __name__ == '__main__':
    main()

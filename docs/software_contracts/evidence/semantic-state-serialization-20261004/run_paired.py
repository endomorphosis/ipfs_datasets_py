"""Bounded fresh-process pairs; no production-source rewriting or shared stores."""
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

B = Path(__file__).resolve().parent
D = Path('/home/barberb/lift_coding/.worktrees/ir-pressure-attribution-datasets-20261004')
environment = dict(PYTHONPATH=str(D), PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
env = os.environ.copy(); env.update(environment)
records = []
for label, mode in [('paired-after-01', 'current'), ('paired-before-01', 'original'),
                    ('paired-before-02', 'original'), ('paired-after-02', 'current')]:
    command = [sys.executable, '-B', str(B / 'profile_publication.py'), label, 'plain', mode]
    (B / (label + '-command.json')).write_text(json.dumps(dict(argv=command, cwd=str(D), environment_overrides=environment,
        script_sha256=hashlib.sha256((B / 'profile_publication.py').read_bytes()).hexdigest()), indent=2) + '\n')
    start = time.monotonic()
    with (B / (label + '-stdout.txt')).open('w') as out, (B / (label + '-stderr.txt')).open('w') as err:
        process = subprocess.run(command, cwd=D, env=env, stdout=out, stderr=err, timeout=120)
    receipt = dict(returncode=process.returncode, seconds=time.monotonic() - start)
    (B / (label + '-exit.json')).write_text(json.dumps(receipt, indent=2) + '\n')
    assert process.returncode == 0, label
    record = json.loads((B / (label + '-result.json')).read_text())
    assert record['source_pins_unchanged'] and record['plain']
    assert record['manifest_producer_native_before'] and record['manifest_producer_native_after']
    assert record['manifest_memo_before'] == dict(hits=0, misses=0, evictions=0, bypasses=0)
    assert record['manifest_memo_after'] == dict(hits=0, misses=1, evictions=0, bypasses=0)
    assert record['leases_after'] == dict(active=0, waiting=0)
    records.append(record)
    print(json.dumps(dict(label=label, cpu_seconds=record['cpu_seconds'], wall_seconds=record['wall_seconds'])), flush=True)
assert len({(record['manifest_cid'], record['snapshot_cid']) for record in records}) == 1
keys = set(records[0]['source_pins_before'])
assert all(set(record['source_pins_before']) == keys for record in records)
for key in keys - {'ipfs_datasets_py/logic/software_contracts/semantic_index/models.py'}:
    assert len({record['source_pins_before'][key] for record in records}) == 1, key
measurements = {mode: {metric: [record[metric] for record in records if record['model_mode'] == mode]
    for metric in ('cpu_seconds', 'wall_seconds')} for mode in ('original', 'current')}
medians = {mode: {metric: statistics.median(values) for metric, values in metrics.items()}
    for mode, metrics in measurements.items()}
summary = dict(diagnostic_only=True, observations=4, outputs_equal=True, native_producers=True,
    fresh_manifest_misses=4, bypasses=0, private_leases_after=0, measurements=measurements, medians=medians,
    reductions_percent={metric: 100 * (1 - medians['current'][metric] / medians['original'][metric])
        for metric in ('cpu_seconds', 'wall_seconds')},
    limitations=['Two samples per mode on one public source file; not a statistical benchmark.',
        'No model, native container, full Terminal-Bench or RSS/admission recovery claim.'])
(B / 'paired-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))

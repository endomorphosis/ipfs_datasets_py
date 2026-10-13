"""Copy private terminal ledger/scheduler samples; no resource API or models."""
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

import run_split_features as r

F = Path(__file__).resolve().parent
LEDGER = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json')
SCHEDULER = Path('/tmp/ipfs-datasets-resource-scheduler-1000.json')


def main():
    plan_path = F / 'split-features-plan-v01.json'
    plan = r.read(plan_path); r.validate_plan(plan)
    terminal_path = r.RUN_ROOT / plan['attempt_name'] / 'guardian-exit.json'
    terminal = r.read(terminal_path)
    r.require(type(terminal['returncode']) is int and type(terminal['child_returncode']) is int
              and terminal['returncode'] == terminal['child_returncode'] == 0
              and terminal['artifacts_durable'] is True and terminal['resource_reservation_released'] is True,
              'successful durable released guardian required')
    root = F / 'private-runtime-snapshots/split-features'
    r.require(not os.path.lexists(root), 'exclusive private snapshot directory required')
    root.mkdir(mode=0o700)
    receipt = dict(schema='split-feature-private-terminal-endpoints/v1', cell='split-features',
                   plan=r.READ_PINS[str(plan_path)], terminal=r.READ_PINS[str(terminal_path)],
                   observed_at_utc=datetime.now(timezone.utc).isoformat(), private_bodies=True,
                   continuous_custody=False, resource_api_called=False,
                   independent_contemporaneous_copy_witness=False)
    for key, source in [('ledger', LEDGER), ('scheduler', SCHEDULER)]:
        before = r.pin(source); raw = source.read_bytes()
        r.require(r.pin(source) == before and len(raw) == before['bytes']
                  and r.hashlib.sha256(raw).hexdigest() == before['sha256'], 'sampled endpoint changed')
        target = root / (key + '.json')
        with target.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        target.chmod(0o400)
        receipt[key] = r.pin(target); receipt['source_' + key] = before
        r.require({k: receipt[key][k] for k in ('bytes', 'sha256')} ==
                  {k: before[k] for k in ('bytes', 'sha256')}, 'private copy differs')
    for path, expected in r.READ_PINS.items():
        r.require(r.pin(path) == expected, 'closing consumed metadata drift')
    output = root / 'snapshot-receipt-v01.json'
    descriptor = r.write(output, receipt); output.chmod(0o400)
    print(r.json.dumps(dict(status='private_sampled_endpoints_copied', receipt=descriptor)))


if __name__ == '__main__':
    main()

"""Verify the saved census, commit one page, then exec a fresh bounded resume."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--arguments-file', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_root.resolve()))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_archive_reconciliation import run_archive_reconciliation
    options = json.loads(args.arguments_file.read_bytes())
    partial = run_archive_reconciliation(**options, max_pages=1)
    output = Path(options['output_directory'])
    with (output / 'seed-and-first-page-report.json').open('x') as stream:
        json.dump(partial, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    if not partial['seed_applied'] or partial['accounting']['source_occurrence_count'] <= 18342:
        raise ValueError('original census was not reused before the first new page')
    command = [sys.executable, str(args.source_root / 'scripts/ops/legal_ir/reconcile_uscode_archive.py')]
    for key, value in options.items():
        if value is None or value is False:
            continue
        command.append('--' + key.replace('_', '-'))
        if value is not True:
            command.append(str(value))
    command.extend(['--max-pages', '128'])
    print(json.dumps(dict(event='fresh_process_archived_target_resume',
        next_section=partial['next_section'], next_span=partial['next_span'],
        source_occurrence_count=partial['accounting']['source_occurrence_count'])), flush=True)
    os.execv(sys.executable, command)


if __name__ == '__main__':
    main()

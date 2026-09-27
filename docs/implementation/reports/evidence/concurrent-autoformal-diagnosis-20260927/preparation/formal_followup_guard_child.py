"""Ownership-gated, pinned, offline execution of the standalone formal checks."""
import argparse
import json
from pathlib import Path
import resource
import runpy
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'harness'))
from smoke_resource_common import (DEPENDENCY, ScopedSources, bootstrap, exact, ref,
                                   require, save, verify_binding)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', type=Path, required=True)
    args = parser.parse_args()
    attempt = args.attempt.resolve(strict=True)
    require(sys.stdin.readline() == 'RUN\n', 'missing owner launch handshake')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (50_000_000, 50_000_000))
    prepared = json.loads((attempt / 'prepared-inputs.json').read_bytes())
    require(prepared['accelerate_dependency'] == DEPENDENCY, 'formal dependency selection changed')
    require(exact(prepared['files'] + prepared['evidence_inputs']), 'formal input source changed before launch')
    sources = ScopedSources()
    network = bootstrap(sources)
    result = {'schema': 'formal-followup-pinned-child/v1', 'passed': False,
              'formal_returncode': None, 'network_guard': network,
              'admitted': False, 'formalized': False, 'training_executed': False,
              'provider_calls': 0, 'database_opened': False}
    try:
        result['accelerate_dependency'] = verify_binding(DEPENDENCY)
        script = HERE / 'formal_followup.py'
        sys.argv = [str(script), '--output-directory', str(attempt / 'formal')]
        try:
            runpy.run_path(str(script), run_name='__main__')
            result['formal_returncode'] = 0
        except SystemExit as exc:
            result['formal_returncode'] = 0 if exc.code is None else exc.code
        require(result['formal_returncode'] == 0, 'standalone formal checks failed')
        formal = attempt / 'formal/followup-receipt.json'
        receipt = json.loads(formal.read_bytes())
        require(receipt.get('passed') is True, 'formal receipt does not pass')
        require(exact(prepared['files'] + prepared['evidence_inputs']), 'formal source changed during checks')
        result['accelerate_dependency_after'] = verify_binding(DEPENDENCY)
        result['scoped_sources'] = sources.verify()
        result['formal_receipt'] = ref(formal)
        result['passed'] = True
    except BaseException as exc:
        result['error'] = {'type': type(exc).__name__, 'message': str(exc)[:3000],
                           'traceback': traceback.format_exc()[-8000:]}
        try:
            result['scoped_sources'] = sources.verify()
            result['prepared_inputs_unchanged'] = exact(prepared['files'] + prepared['evidence_inputs'])
            result['accelerate_dependency_after'] = verify_binding(DEPENDENCY)
        except BaseException as drift:
            result['source_guard_error'] = str(drift)[:2000]
    save(attempt / 'child-source-receipt.json', result)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

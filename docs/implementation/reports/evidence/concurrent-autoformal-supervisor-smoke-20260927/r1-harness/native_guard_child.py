"""Wait for registered ownership, then run the unchanged native driver."""
import argparse
import json
from pathlib import Path
import resource
import runpy
import sys
import traceback
from smoke_resource_common import HERE, ScopedSources, bootstrap, exact, require, save


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', type=Path, required=True)
    args = parser.parse_args()
    attempt = args.attempt.resolve(strict=True)
    require(sys.stdin.readline() == 'RUN\n', 'missing root ownership handshake')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (80_000_000, 80_000_000))
    expected = json.loads((attempt / 'prepared-inputs.json').read_bytes())
    require(exact(expected['harness']), 'prepared harness changed')
    require(exact(expected['accelerate_sources']), 'accelerate source closure changed before child launch')
    sources = ScopedSources()
    network = bootstrap(sources)
    result = {'passed': False, 'native_driver_returncode': None, 'network_guard': network}
    try:
        sys.argv = [str(HERE / 'native_supervisor_driver.py'), '--runtime-root', str(attempt / 'supervisor'),
                    '--bundle-directory', str(HERE), '--implementation-timeout', '480']
        try:
            runpy.run_path(sys.argv[0], run_name='__main__')
            result['native_driver_returncode'] = 0
        except SystemExit as exc:
            result['native_driver_returncode'] = 0 if exc.code is None else exc.code
        require(result['native_driver_returncode'] == 0, 'native supervisor did not complete smoke task')
        require(exact(expected['harness']), 'prepared harness changed during native run')
        require(exact(expected['accelerate_sources']), 'accelerate source closure changed during native run')
        result['scoped_sources'] = sources.verify()
        result['passed'] = True
    except BaseException as exc:
        result['error'] = {'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()}
        try:
            result['scoped_sources'] = sources.verify()
        except BaseException as changed:
            result['source_guard_error'] = str(changed)
    save(attempt / 'child-source-receipt.json', result)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

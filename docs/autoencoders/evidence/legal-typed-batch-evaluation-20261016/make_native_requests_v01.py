"""Source/metadata-only freeze of already authored validation and consumer jobs."""
from pathlib import Path
import ast
import hashlib
import json
import sys

PHASE = Path('/home/barberb/lift_coding/artifacts/legal-typed-batch-evaluation-20261016-01')
PRIOR = Path('/home/barberb/lift_coding/artifacts/legal-typed-reconstruction-20261016-01')
ROOT = Path('/home/barberb/lift_coding/artifacts/legal-conditions-composition-diagnostic-20261015-01/datasets')
GUARD = Path('/home/barberb/lift_coding/artifacts/legal-primary-graph-export-20261015-01/run_export_qualification_v03.py')
ATTEMPTS = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-validation-runs')


def write_new(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)


def main():
    assert len(sys.argv) == 2 and sys.argv[1].isdigit() and len(sys.argv[1]) == 2
    revision = sys.argv[1]
    assert Path.cwd() == ROOT
    template = json.loads((PRIOR / 'qualification-request-v05.json').read_text())
    pins = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in template['source_sha256']}
    for relative in ['ipfs_datasets_py/logic/autoformal/legal_relational_batch_evaluation_v1.py',
                     'tests/unit/logic/autoformal/test_legal_relational_batch_evaluation_v1.py']:
        path = ROOT / relative
        ast.parse(path.read_text())
        pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert pins[str(GUARD)] == 'caef50be105d8280cd727ae0c14867644e223d83639454ff33f0df2df2e68854'
    helper = PHASE / 'run_retained_batch_v01.py'
    helper_ast = ast.parse(helper.read_text())
    checks = next(ast.literal_eval(node.value) for node in helper_ast.body
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'CHECKS' for t in node.targets))
    config = PHASE / 'comparison-inputs-v01.json'
    descriptor = Path(json.loads(config.read_text())['source_descriptor']['path'])
    requests = []
    for label, storage in [('qualification', 1073741824), ('retained-batch', 268435456)]:
        request_path = PHASE / (label + '-request-v' + revision + '.json')
        attempt = ATTEMPTS / ('legal-typed-batch-evaluation-20261016-' + label + revision)
        assert not request_path.exists() and not attempt.exists()
        value = dict(template, attempt_directory=str(attempt), memory_mb=2048, storage_bytes=storage,
            outputs={name: str(attempt / name) for name in ['pytest', 'tmp', 'cache', 'db', 'exports', 'logs']},
            source_sha256=dict(pins))
        if label == 'qualification':
            value['selected_checks'] = ['tests/unit/logic/autoformal/test_legal_relational_batch_evaluation_v1.py',
                *template['selected_checks']]
            value['argv'] = [sys.executable, '-B', str(GUARD), str(request_path)]
        else:
            for path in [helper, config, descriptor]:
                value['source_sha256'][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            value['selected_checks'] = checks
            value['argv'] = [sys.executable, '-B', str(helper), str(request_path), str(config)]
        assert len(value['source_sha256']) <= 256
        raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
        assert len(raw) <= 1024 * 1024
        requests.append((request_path, attempt, value, raw))
    for request_path, attempt, value, raw in requests:
        write_new(request_path, raw)
        digest = hashlib.sha256(raw).hexdigest()
        write_new(request_path.with_suffix('.sha256'), (digest + '\n').encode())
        attempt.mkdir(mode=0o700)
        print(json.dumps({'request': str(request_path), 'sha256': digest, 'source_pins': len(value['source_sha256']),
            'attempt': str(attempt), 'memory_mb': value['memory_mb'], 'storage_bytes': value['storage_bytes']}, sort_keys=True))


if __name__ == '__main__':
    main()

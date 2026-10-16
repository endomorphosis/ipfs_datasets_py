"""Freeze source-only qualification and numerical replay manifests, without payload reads."""
from pathlib import Path
import ast
import hashlib
import json
import sys

PHASE = Path('/home/barberb/lift_coding/artifacts/legal-decoder-output-integration-20261016-01')
PRIOR = Path('/home/barberb/lift_coding/artifacts/legal-typed-batch-evaluation-20261016-01')
ROOT = Path('/home/barberb/lift_coding/artifacts/legal-conditions-composition-diagnostic-20261015-01/datasets')
HISTORICAL = Path('/home/barberb/lift_coding/external/ipfs_datasets')
GUARD = Path('/home/barberb/lift_coding/artifacts/legal-primary-graph-export-20261015-01/run_export_qualification_v03.py')
ATTEMPTS = HISTORICAL / 'workspace/test-logs/federal-corpus-audits/owned-validation-runs'


def raw(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def put(path, value):
    with path.open('xb') as stream:
        stream.write(value)


def main():
    assert len(sys.argv) == 2 and sys.argv[1].isdigit() and len(sys.argv[1]) == 2
    revision = sys.argv[1]
    assert Path.cwd() == ROOT
    template = json.loads((PRIOR / 'qualification-request-v02.json').read_text())
    qualification_pins = set(template['source_sha256'])
    relatives = ['ipfs_datasets_py/logic/formalization/autoencoder/__init__.py',
        'ipfs_datasets_py/logic/formalization/autoencoder/legal_ir_decoder_output_compatibility_v1.py',
        'ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_source_generation.py',
        'ipfs_datasets_py/logic/formalization/autoencoder/contextual_legal_ir_output.py',
        'ipfs_datasets_py/logic/formalization/autoencoder/decoder_source_fidelity.py',
        'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_formula_codec.py',
        'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_grammar_decoder.py',
        'tests/unit/logic/autoformal/test_legal_ir_decoder_output_compatibility_v1.py',
        'tests/unit/logic/formalization/autoencoder/test_contextual_legal_ir_output.py',
        'tests/unit/optimizers/logic_theorem_optimizer/test_legal_formula_codec.py']
    qualification_pins.update(str(ROOT / p) for p in relatives)
    qlog = HISTORICAL / 'workspace/test-logs/federal-corpus-audits/owned-validation-runs/legal-typed-batch-evaluation-20261016-qualification02/logs/qualification.json'
    actual = json.loads(qlog.read_text())['loaded_product_source_origins']
    numerical_pins = {row['path'] for row in actual.values()}
    numerical_pins.update(json.loads((PHASE / 'storage-observer-pins-v01.json').read_text()))
    numerical_pins.update(str(ROOT / p) for p in relatives if not p.startswith('tests/'))
    numerical_pins.update(str(ROOT / p) for p in ['scripts/ops/legal_ir/run_owned_validation.py',
        'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py'])
    for base in (ROOT, HISTORICAL):
        for pattern in ('ipfs_datasets_py/logic/formalization/autoencoder/gte_*.py', 'scripts/ops/autoencoder/*gte*.py'):
            numerical_pins.update(str(p) for p in base.glob(pattern))
    numerical_pins.update(str(p) for p in [GUARD, PHASE / 'run_numerical_replay_v01.py', PHASE / 'numerical-inputs-v01.json'])
    outputs = []
    for label, sources, memory, storage in [('qualification', qualification_pins, 2048, 134217728),
        ('numerical-replay', numerical_pins, 4096, 268435456)]:
        path = PHASE / (label + '-request-v' + revision + '.json')
        attempt = ATTEMPTS / ('legal-decoder-output-integration-20261016-' + label + revision)
        assert not path.exists() and not attempt.exists()
        pins = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sorted(sources)}
        assert 0 < len(pins) <= 256
        for p in sources:
            if p.endswith('.py'):
                ast.parse(Path(p).read_text())
        value = dict(template, source_sha256=pins, memory_mb=memory, storage_bytes=storage,
            attempt_directory=str(attempt), outputs={n: str(attempt / n) for n in ['pytest','tmp','cache','db','exports','logs']})
        if label == 'qualification':
            value['selected_checks'] = [relatives[-3], relatives[-2], relatives[-1]]
            value['argv'] = [sys.executable, '-B', str(GUARD), str(path)]
        else:
            tree = ast.parse((PHASE / 'run_numerical_replay_v01.py').read_text())
            checks = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id == 'CHECKS' for t in n.targets))
            value['selected_checks'] = checks
            value['argv'] = [sys.executable, '-B', str(PHASE / 'run_numerical_replay_v01.py'), str(path), str(PHASE / 'numerical-inputs-v01.json')]
        data = raw(value)
        assert len(data) <= 1024*1024
        outputs.append((path, attempt, data, value))
    for path, attempt, data, value in outputs:
        put(path, data)
        digest = hashlib.sha256(data).hexdigest()
        put(path.with_suffix('.sha256'), (digest+'\n').encode())
        attempt.mkdir(mode=0o700)
        print(json.dumps({'request': str(path), 'sha256': digest, 'source_pins': len(value['source_sha256']),
            'attempt': str(attempt), 'memory_mb': value['memory_mb'], 'storage_bytes': value['storage_bytes']}))


if __name__ == '__main__':
    main()

"""Package successful final local-peer recovery runs; exclude native databases."""
from pathlib import Path
import hashlib
import importlib
import json
import xml.etree.ElementTree as ET

from ipfs_datasets_py.logic.software_contracts import codebase_peer_dispatched_federation as peer
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS

ROOT = Path('/home/barberb/lift_coding')
D = ROOT / '.worktrees/ir-release-datasets-20261002'
A = ROOT / '.worktrees/ir-release-accelerate-20261002'
ART = ROOT / 'artifacts/codebase-peer-recovery-20261002'
OUT = D / 'docs/software_contracts/evidence/codebase-peer-recovery-20261002'
OUT.mkdir(parents=True, exist_ok=False)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(name, value):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def copy(source, name):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(Path(source).read_bytes())


def cases(path, count):
    root = ET.parse(path).getroot()
    rows = root.findall('.//testcase')
    assert len(rows) == count
    assert not root.findall('.//failure') and not root.findall('.//error') and not root.findall('.//skipped')
    return {'passed': count, 'test_names': [row.attrib['name'] for row in rows],
            'suite_seconds': sum(float(s.attrib['time']) for s in root.findall('./testsuite'))}


matrix = {}
for name, count in [('native-02', 12), ('native-03', 13)]:
    run = ART / name
    matrix[name] = cases(run / 'tests.xml', count)
    fixture = run / 'temp/peer-native0'
    qualification = json.loads((fixture / 'qualification.json').read_text())
    assert qualification['native_default_host'] is True and qualification['injected_telemetry'] is False
    assert qualification['model_provider_calls'] == 0
    assert all(row['passed'] for row in qualification['controls'])
    cas = ImmutableCAS(fixture / 'cas')
    policy = cas.get(qualification['round']['policy_cid'])
    assert policy['implementation'] == peer._pins()
    matrix[name]['policy_cid'] = qualification['round']['policy_cid']
    matrix[name]['peer_record_cid'] = qualification['round']['artifact_cid']
    for filename in ('tests.log', 'tests.xml'):
        copy(run / filename, name + '/' + filename)
    drift = json.loads((run / 'producer-drift.json').read_text())
    assert drift == {'checked': 25, 'changed': []}
    copy(run / 'producer-drift.json', name + '/producer-drift.json')
    copy(run / 'sources-before.json', name + '/sources-before.json')
    copy(fixture / 'qualification.json', name + '/qualification.json')
    if (fixture / 'cold-recovery.json').exists():
        copy(fixture / 'cold-recovery.json', name + '/cold-recovery.json')
    for path in sorted((fixture / 'cas').rglob('*')):
        if path.is_file():
            assert not path.is_symlink()
            if path.is_relative_to(fixture / 'cas/source'):
                cas.get_bytes(path.name)
            else:
                cas.get(path.name)
            copy(path, name + '/cas/' + path.relative_to(fixture / 'cas').as_posix())
    for path in sorted((fixture / 'models').rglob('*')):
        if path.is_file():
            assert not path.is_symlink() and sha(path.read_bytes()) == path.name
            copy(path, name + '/models/' + path.relative_to(fixture / 'models').as_posix())
    for path in sorted((fixture / 'repo').glob('*.py')):
        copy(path, name + '/fixture/' + path.name)

for label, controls, basename, count in [('manifest_bounds', 'controls-02', 'manifest-02', 5), ('neighbor_dispatcher', 'controls-03', 'neighbor', 19)]:
    matrix[label] = cases(ART / controls / (basename + '.xml'), count)
    for ext in ('.log', '.xml'):
        copy(ART / controls / (basename + ext), 'controls/' + basename + ext)
for ext in ('.log', '.xml'):
    copy(ART / 'controls-02' / ('neighbor' + ext), 'historical/seal-cache-skipped-neighbor' + ext)

pins = peer._pins()
expected = {}
def gather(value):
    for key, item in value.items():
        if key.startswith('ipfs_') and type(item) is str and len(item) == 64:
            assert key not in expected or expected[key] == item
            expected[key] = item
        elif type(item) is dict:
            gather(item)
gather(pins)
expected[peer.__name__] = pins['owner_sha256']
sources = []
for name, digest in sorted(expected.items()):
    path = Path(importlib.import_module(name).__file__).resolve()
    raw = path.read_bytes()
    assert sha(raw) == digest
    repo, base = ('datasets', D) if path.is_relative_to(D) else ('accelerate', A)
    assert path.is_relative_to(base)
    rel = path.relative_to(base).as_posix()
    copy(path, 'sources/' + repo + '/' + rel)
    sources.append(dict(module=name, repository=repo, path=rel, sha256=digest, bytes=len(raw)))
for repo, base, rel in [
    ('datasets', D, 'tests/integration/logic/software_contracts/test_codebase_peer_federation.py'),
    ('datasets', D, 'tests/integration/logic/software_contracts/test_codebase_peer_recovery.py'),
    ('datasets', D, 'tests/integration/logic/software_contracts/test_codebase_peer_manifest_bounds.py'),
    ('accelerate', A, 'test/unit/test_codebase_federated_dispatch.py'),
]:
    raw = (base / rel).read_bytes()
    copy(base / rel, 'sources/' + repo + '/' + rel)
    sources.append(dict(repository=repo, path=rel, sha256=sha(raw), bytes=len(raw), test_only=True))
save('producer-sources.json', {'schema': 'codebase-peer-recovery-source-pins/v1', 'sources': sources,
    'scope': 'Exact final producer bytes joined to both successful native source policies; tests are separately marked.'})
save('qualification.json', {'schema': 'codebase-peer-recovery-qualification/v1', 'matrix': matrix,
    'distinct_controls': 49, 'native_default_host': True, 'injected_telemetry': False,
    'model_provider_calls': 0, 'authority': peer._peer().FALSE,
    'scope': 'sequential local subprocess peers; shared immutable CAS; native 8D structural feature training',
    'remaining': ['remote/libp2p deployment', 'cross-host artifact transport', 'parallel remote fleet/device accounting',
                  'distributed 384D training', 'gradient collective backend/verifier'],
    'private_exclusions': ['native databases', 'scheduler state and private lease tokens', 'peer configuration and receipt cache', 'Git administration']})
copy(Path(__file__), 'package_evidence.py')
copy(ART / 'README.final.md', 'README.md')
members = []
for path in sorted(OUT.rglob('*')):
    if path.is_file():
        assert not path.is_symlink()
        raw = path.read_bytes()
        members.append(dict(path=path.relative_to(OUT).as_posix(), bytes=len(raw), sha256=sha(raw)))
save('manifest.json', {'schema': 'codebase-peer-recovery-evidence-manifest/v1', 'files': members,
    'bytes': sum(row['bytes'] for row in members), 'scope': 'public local qualification, no live execution authority'})
print(json.dumps({'directory': str(OUT), 'members': len(members), 'bytes': sum(row['bytes'] for row in members),
                  'manifest_sha256': sha((OUT / 'manifest.json').read_bytes())}))

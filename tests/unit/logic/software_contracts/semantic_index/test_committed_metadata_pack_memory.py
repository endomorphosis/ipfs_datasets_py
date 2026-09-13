"""A real large pack remains readable within a fixed metadata process limit."""
import json
import os
from pathlib import Path
import subprocess
import sys

from ipfs_datasets_py.logic.software_contracts.semantic_index import committed_snapshot as C


def test_real_large_pack_complete_metadata_under_fixed_address_limit(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null',
            '-c', 'gc.auto=0', '-C', str(root), *args], stderr=subprocess.PIPE)
    git('init', '-b', 'main')
    # Real, distinct incompressible blobs exceed the child's address ceiling.
    # No padding, forged pack metadata or raised resource limits.
    for index in range(160):
        (root / f'input-{index:03d}.bin').write_bytes(os.urandom(1024 * 1024))
    git('add', '--all')
    git('-c', 'user.name=Fixture', '-c', 'user.email=test@example.invalid',
        'commit', '-qm', 'packed metadata fixture')
    git('-c', 'pack.threads=1', 'repack', '-adf', '--window=0', '--depth=0')
    packs = list((root / '.git/objects/pack').glob('*.pack'))
    assert len(packs) == 1 and packs[0].stat().st_size > 128 * 1024**2
    head = git('rev-parse', 'HEAD').decode().strip()
    tree = git('rev-parse', 'HEAD^{tree}').decode().strip()
    producer = str(Path(C.__file__).resolve().parents[4])
    code = '''
import json,resource,sys
sys.path.insert(0,sys.argv[1])
from ipfs_datasets_py.logic.software_contracts.semantic_index.committed_snapshot import preflight_committed_repository
resource.setrlimit(resource.RLIMIT_AS,(128*1024**2,128*1024**2))
plan=preflight_committed_repository(sys.argv[2],expected_commit=sys.argv[3],expected_tree=sys.argv[4],repository_id='fixture:packed-metadata')
print(json.dumps({'entries':len(plan.entries),'bytes':sum(e.size_bytes for e in plan.entries),'commit':plan.commit,'tree':plan.tree,'population_cid':plan.population_cid}))
'''
    result = subprocess.run([sys.executable, '-B', '-c', code, producer, str(root), head, tree],
        capture_output=True, timeout=60,
        env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1', 'IPFS_DATASETS_PY_MINIMAL_IMPORTS':'1',
             'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    observed = json.loads(result.stdout)
    assert observed['entries'] == 160 and observed['bytes'] == 160 * 1024**2
    assert observed['commit'] == head and observed['tree'] == tree
    assert observed['population_cid']
    assert git('status', '--porcelain=v1', '--untracked-files=all') == b''

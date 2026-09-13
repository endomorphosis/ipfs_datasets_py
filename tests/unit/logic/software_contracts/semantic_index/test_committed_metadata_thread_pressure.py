"""Real Git checks remain complete when pthread creation is unavailable."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_index import committed_snapshot as C


def git(root, *args, env=None, check=True):
    return subprocess.run(['git', '--no-optional-locks', '-c', 'core.hooksPath=/dev/null',
        '-c', 'gc.auto=0', '-C', str(root), *args], env=env, capture_output=True, check=check, timeout=30)


@pytest.fixture(scope='module')
def checkout(tmp_path_factory):
    if sys.platform != 'linux' or not shutil.which('cc'):
        pytest.skip('real Git pthread refusal fixture requires Linux and cc')
    base = tmp_path_factory.mktemp('git-thread-pressure')
    library = base/'deny-pthread.so'
    source = base/'deny-pthread.c'
    source.write_text('#include <errno.h>\n#include <pthread.h>\n'
        'int pthread_create(pthread_t *t,const pthread_attr_t *a,void *(*f)(void *),void *x)'
        '{(void)t;(void)a;(void)f;(void)x;return EAGAIN;}\n')
    subprocess.run(['cc','-shared','-fPIC','-o',str(library),str(source)], check=True, capture_output=True, timeout=30)
    root = base/'root'; root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    nested = root/'nested'; nested.mkdir()
    git(nested, 'init', '-q', '-b', 'main')
    for index in range(2000):
        (nested/f'input-{index:04d}.txt').write_text('original\n')
    git(nested, '-c','core.preloadIndex=false','-c','index.threads=1','add','--all')
    git(nested, '-c','user.name=Fixture','-c','user.email=test@invalid','commit','-qm','complete nested fixture')
    (root/'.gitmodules').write_text('[submodule "nested"]\n\tpath = nested\n\turl = ./nested\n')
    nested_head = git(nested,'rev-parse','HEAD').stdout.decode().strip()
    git(root,'add','.gitmodules')
    git(root,'update-index','--add','--cacheinfo','160000',nested_head,'nested')
    git(root,'-c','user.name=Fixture','-c','user.email=test@invalid','commit','-qm','nested source')
    head = git(root,'rev-parse','HEAD').stdout.decode().strip()
    tree = git(root,'rev-parse','HEAD^{tree}').stdout.decode().strip()
    return root,nested,library,head,tree


def test_exact_git_failure_reproduced_and_complete_nested_checks_remain(checkout, monkeypatch):
    root,nested,library,head,tree = checkout
    env = {**os.environ, 'LD_PRELOAD':str(library)}
    # Force the previously implicit defaults. Real nested Git fails before
    # inspecting all tracked files; no mocked return code or fake Git output.
    prior = git(root,'-c','core.preloadIndex=true','-c','index.threads=1',
        'status','--porcelain=v1','-z','--untracked-files=all',env=env,check=False)
    assert prior.returncode != 0
    assert b'unable to create threaded lstat' in prior.stderr
    assert b'failed in submodule nested' in prior.stderr
    index_before = {repo:(repo/'.git/index').read_bytes() for repo in (root,nested)}
    baseline = C.preflight_committed_repository(root, repository_id='fixture:threads', expected_commit=head, expected_tree=tree)
    monkeypatch.setenv('LD_PRELOAD',str(library))
    observed = C.preflight_committed_repository(root, repository_id='fixture:threads', expected_commit=head, expected_tree=tree)
    assert observed.to_dict() == baseline.to_dict()
    assert {repo:(repo/'.git/index').read_bytes() for repo in (root,nested)} == index_before
    changed = nested/'input-1999.txt'
    original = changed.read_bytes()
    try:
        changed.write_bytes(b'changed bytes in the last nested tracked file\n')
        with pytest.raises(C.GitSnapshotError,match='requires a clean checkout'):
            C.preflight_committed_repository(root, repository_id='fixture:threads', expected_commit=head, expected_tree=tree)
    finally:
        changed.write_bytes(original)
    untracked = nested/'untracked.txt'
    try:
        untracked.write_text('untracked nested input\n')
        with pytest.raises(C.GitSnapshotError,match='requires a clean checkout'):
            C.preflight_committed_repository(root, repository_id='fixture:threads', expected_commit=head, expected_tree=tree)
    finally:
        untracked.unlink()
    assert {repo:(repo/'.git/index').read_bytes() for repo in (root,nested)} == index_before

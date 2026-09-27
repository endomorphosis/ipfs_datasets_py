"""Real FIFO/race fixtures run in disposable children with strict deadlines."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_index import paged_fact_store as store
from ipfs_datasets_py.logic.software_contracts.semantic_index import paged_fact_worker as worker


SCRIPT = r'''
from dataclasses import asdict
import json,os,sys
from pathlib import Path
from ipfs_datasets_py.logic.software_contracts.semantic_index import paged_fact_store as s
from ipfs_datasets_py.logic.software_contracts.semantic_index import paged_fact_worker as w
path, attack = Path(sys.argv[1]), sys.argv[2]
p=s.PagedFactProfile(); b=s.FactSpoolBudget(1048576,100,100,10485760,1000)
try:
    if attack.startswith('implementation'):
        victim=path/'implementation.py'
        if attack == 'implementation-fifo':
            os.mkfifo(victim)
        else:
            victim.write_text('source')
            original=os.open
            def swap(name, flags, *args, **kwargs):
                if Path(name) == victim:
                    victim.unlink(); os.mkfifo(victim)
                return original(name, flags, *args, **kwargs)
            w.os.open=swap
        w._file_hash(victim)
    else:
        with s.OwnedFactStore(path/'facts',profile=p,budget=b) as owned:
            request=owned.bind_request({'paging_profile':p.payload(),'spool_budget':asdict(b)})
            root=owned.put({'fixture':'raw'})
            if attack == 'block-fifo':
                (owned.path/root).unlink(); os.mkfifo(owned.path/root)
                owned.get(root)
            owned.publish_raw_coverage(root)
        lease=path/'facts'/'owner.lock'
        lease.unlink(); os.mkfifo(lease)
        s.OwnedFactStore.open_published(path/'facts', expected_request_cid=request,
            expected_root_cid=root,profile=p,budget=b)
except s.PagedFactError as exc:
    print(json.dumps({'pid':os.getpid(),'code':exc.code})); sys.exit(0)
raise AssertionError('FIFO was accepted')
'''


@pytest.mark.parametrize('attack', ['block-fifo', 'lease-fifo', 'implementation-fifo', 'implementation-race'])
def test_fifo_refuses_without_blocked_or_orphaned_process(tmp_path, attack):
    process = subprocess.Popen([sys.executable, '-B', '-c', SCRIPT, str(tmp_path), attack],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        output, errors = process.communicate(timeout=4)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=2)
        pytest.fail('FIFO blocked the owned reader beyond its strict deadline')
    assert process.returncode == 0, errors
    result = json.loads(output)
    assert result['code'] in {'fact_file_shape', 'store_lease_shape', 'implementation_file_shape'}
    assert not Path('/proc') .joinpath(str(result['pid'])).exists()


def test_cas_namespace_replacement_after_descriptor_stat_refuses(tmp_path, monkeypatch):
    p=store.PagedFactProfile(); b=store.FactSpoolBudget(1048576,100,100,10485760,1000)
    with store.OwnedFactStore(tmp_path/'facts', profile=p, budget=b) as owned:
        owned.bind_request({'fixture':'request'})
        cid = owned.put({'value':1})
        path = owned.path/cid
        inode = path.stat().st_ino
        original = os.fstat
        count = 0
        def race(fd):
            nonlocal count
            result = original(fd)
            if result.st_ino == inode:
                count += 1
                if count == 2:
                    data = path.read_bytes()
                    path.rename(owned.path/'retained-old-block')
                    path.write_bytes(data)
            return result
        monkeypatch.setattr(store.os, 'fstat', race)
        with pytest.raises(store.PagedFactError, match='fact_changed_during_read'):
            owned.get(cid)


def test_implementation_namespace_replacement_after_descriptor_stat_refuses(tmp_path, monkeypatch):
    path = tmp_path/'implementation.py'
    path.write_text('trusted = True\n')
    inode, original, count = path.stat().st_ino, os.fstat, 0
    def race(fd):
        nonlocal count
        result = original(fd)
        if result.st_ino == inode:
            count += 1
            if count == 2:
                data=path.read_bytes()
                path.rename(tmp_path/'old.py')
                path.write_bytes(data)
        return result
    monkeypatch.setattr(worker.os, 'fstat', race)
    with pytest.raises(store.PagedFactError, match='implementation_changed_during_read'):
        worker._file_hash(path)


def test_implementation_enumeration_stops_during_iteration_before_sort(monkeypatch, tmp_path):
    observed = []
    class Entry:
        name='ordinary.py'
        def is_symlink(self): return False
        def is_dir(self, **kwargs): return False
        def is_file(self, **kwargs): return True
    class Entries:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def __iter__(self):
            for count in range(100000):
                observed.append(count)
                yield Entry()
    monkeypatch.setattr(worker.os, 'scandir', lambda fd: Entries())
    with pytest.raises(store.PagedFactError, match='implementation_enumeration_bound'):
        worker._bounded_tree(tmp_path, [0])
    assert len(observed) == 8193

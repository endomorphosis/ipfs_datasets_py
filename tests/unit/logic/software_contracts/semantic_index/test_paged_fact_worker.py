"""Owned worker transport and independently recomputed implementation binds."""
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index import paged_fact_worker as worker
from ipfs_datasets_py.logic.software_contracts.semantic_index import streaming_scanner as streaming
from ipfs_datasets_py.logic.software_contracts.semantic_index.paged_fact_store import PagedFactError


@pytest.mark.parametrize('attack', ['timeout', 'output', 'malformed'])
def test_owned_new_worker_transport_refuses_and_reaps(monkeypatch, attack):
    raw = b'def value(): return 1\n'
    profile = worker.implementation_profile()
    commands = {'timeout': 'import time; time.sleep(60)',
                'output': 'import os,time; os.write(1,b"x"*16384); time.sleep(60)',
                'malformed': 'import sys; sys.stdin.buffer.read(); sys.stdout.write("invalid")'}
    monkeypatch.setattr(worker, '_command', lambda: [sys.executable, '-I', '-B', '-c', commands[attack]])
    original = worker.subprocess.Popen
    children = []
    def spawn(*args, **kwargs):
        result = original(*args, **kwargs)
        children.append(result)
        return result
    monkeypatch.setattr(worker.subprocess, 'Popen', spawn)
    signals = []
    original_signal = worker.os.killpg
    def signal(pid, signum):
        signals.append(pid)
        return original_signal(pid, signum)
    monkeypatch.setattr(worker.os, 'killpg', signal)
    limits = streaming.StreamingScanLimits(max_file_fact_bytes=1024, worker_timeout_seconds=1)
    with pytest.raises(PagedFactError):
        worker.run_file_worker({'operation':'analysis','path':'module.py','kind':'python',
            'repository_id':'fixture:transport','source_cid':cid_for_bytes(raw)}, raw, limits, profile)
    assert len(children) == 1 and children[0].returncode is not None
    assert not Path(f'/proc/{children[0].pid}').exists()
    if attack == 'malformed':
        assert signals == []  # never signal the numeric group after its leader is reaped


def test_worker_recomputes_profile_and_source_identity_before_analysis():
    raw = b'def value(): return 1\n'
    header = {'operation':'analysis','path':'module.py','kind':'python',
              'repository_id':'fixture:profile','source_cid':cid_for_bytes(raw)}
    profile = worker.implementation_profile()
    with pytest.raises(PagedFactError, match='implementation_profile_changed'):
        worker.run_file_worker(header, raw, streaming.StreamingScanLimits(), profile | {'source_file_count': 1})
    with pytest.raises(PagedFactError, match='source_size_or_identity'):
        worker.run_file_worker(header | {'source_cid':cid_for_bytes(b'false')}, raw, streaming.StreamingScanLimits(), profile)

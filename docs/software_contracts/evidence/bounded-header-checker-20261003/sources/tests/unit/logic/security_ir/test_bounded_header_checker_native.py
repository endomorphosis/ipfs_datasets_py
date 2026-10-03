"""Small real-process controls under authored lease supervision, not host admission."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from ipfs_datasets_py.logic.security_ir import bounded_header_checker as module
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds


class Signal:
    def is_set(self):
        return False


class Child:
    def __init__(self, owner):
        self.owner = owner

    def combined_cancellation_signal(self, external):
        return Signal()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.owner.release_count += 1


class AuthoredParent(module.ResourceLease):
    def __init__(self):
        self.release_count = 0

    def combined_cancellation_signal(self, external):
        return Signal()

    def acquire_child(self, **kwargs):
        assert kwargs['cpu_slots'] == kwargs['child_process_slots'] == 1
        assert kwargs['memory_mb'] == 128
        return Child(self)


BOUNDS = ExecutionBounds(timeout_ms=5000, max_steps=100000,
    max_memory_bytes=128*1024**2, max_output_bytes=65536)


def test_native_z3_exact_script_and_version():
    z3 = shutil.which("z3")
    assert z3 is not None, "explicit native qualification requires installed Z3"
    parent = AuthoredParent()
    runner = module.bounded_header_runner(z3, parent_lease=parent, remaining_seconds=lambda: 10.)
    result = runner("(set-logic QF_LIA)\n(assert false)\n(check-sat)\n", BOUNDS)
    assert result.stdout.strip() == "unsat" and result.solver_version.startswith("Z3 version")
    assert parent.release_count == 1


def test_native_process_limits_and_exact_stdin(tmp_path):
    binary = tmp_path / "authored-limit-observer"
    binary.write_text(f"#!{sys.executable}\n" + '''import os,sys,resource,json,hashlib
if '-version' in sys.argv:
 print('authored process limit observer 1')
else:
 print(json.dumps(dict(as_limit=resource.getrlimit(resource.RLIMIT_AS), cpu_limit=resource.getrlimit(resource.RLIMIT_CPU), same_group=os.getpid()==os.getpgrp(), stdin_sha256=hashlib.sha256(sys.stdin.buffer.read()).hexdigest(), argv=sys.argv[1:])))
''')
    binary.chmod(0o755)
    parent = AuthoredParent()
    text = "; exact UTF-8 \u00e9\n(check-sat)\n"
    runner = module.bounded_header_runner(str(binary), parent_lease=parent, remaining_seconds=lambda: 10.)
    result = runner(text, BOUNDS)
    observation = json.loads(result.stdout)
    assert observation['as_limit'] == [128*1024**2]*2
    assert 0 < observation['cpu_limit'][0] <= 5 and observation['cpu_limit'][0] == observation['cpu_limit'][1]
    assert observation['same_group'] is True
    assert observation['stdin_sha256'] == hashlib.sha256(text.encode()).hexdigest()
    assert observation['argv'] == ['-in', '-smt2', 'rlimit=100000']
    assert parent.release_count == 1


def test_native_output_flood_refuses(tmp_path):
    binary = tmp_path / "authored-output-flood"
    binary.write_text(f"#!{sys.executable}\n" + '''import sys
if '-version' in sys.argv: print('authored output observer 1')
else: print('x'*131072)
''')
    binary.chmod(0o755)
    parent = AuthoredParent()
    runner = module.bounded_header_runner(str(binary), parent_lease=parent, remaining_seconds=lambda: 10.)
    with pytest.raises(module.BoundedHeaderCheckerError):
        runner("(check-sat)", BOUNDS)
    assert parent.release_count == 1


def test_native_query_timeout_cleans_owned_process(tmp_path):
    pid_path = tmp_path / "pid"
    binary = tmp_path / "authored-sleeper"
    binary.write_text(f"#!{sys.executable}\n" + f'''import os,sys,time
if '-version' in sys.argv: print('authored timeout observer 1')
else:
 with open({str(pid_path)!r},'w') as stream: stream.write(str(os.getpid()))
 time.sleep(10)
''')
    binary.chmod(0o755)
    parent = AuthoredParent()
    runner = module.bounded_header_runner(str(binary), parent_lease=parent, remaining_seconds=lambda: 10.)
    with pytest.raises(module.LeaseTimeoutError):
        runner("(check-sat)", ExecutionBounds(timeout_ms=400,max_steps=100000,
            max_memory_bytes=128*1024**2,max_output_bytes=65536))
    assert parent.release_count == 1 and pid_path.is_file()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)

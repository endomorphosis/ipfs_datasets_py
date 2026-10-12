"""Exercise real fdopen/tempfile audit events only in an owned inert fixture."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from owned_closeout_write_gate import ReviewedWriteGate,identity

F=Path(__file__).resolve().parent
ROOT=F/'write-gate-boundary-fixture-02';OUT=ROOT/'output';LEDGER=ROOT/'ledger/disk.json'
REAL=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json')
before=hashlib.sha256(REAL.read_bytes()).hexdigest()
ROOT.mkdir(mode=0o700);OUT.mkdir();LEDGER.parent.mkdir();LEDGER.write_bytes(b'{}\n')
lock=LEDGER.with_name(LEDGER.name+'.lock');lock.write_bytes(b'')
untracked=OUT/'untracked.bin';untracked_fd=os.open(untracked,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
aliased=OUT/'aliased.bin';aliased_fd=os.open(aliased,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
os.link(aliased,OUT/'alias.bin')
st=lock.stat();gate=ReviewedWriteGate(OUT,LEDGER,(st.st_dev,st.st_ino),identity(LEDGER.parent))
sys.addaudithook(gate.audit)
tests=[]
def denied(name,operation):
    try:operation()
    except AssertionError:tests.append(dict(name=name,passed=True));return
    raise AssertionError('Expected denial: '+name)
def saved(path,content):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        gate.register(fd,path,'owned_output')
        with os.fdopen(fd,'wb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
    finally:
        gate.forget(fd)
        try:os.close(fd)
        except OSError:pass
denied('unarmed output create',lambda:os.open(OUT/'unarmed.bin',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600))
gate.arm()
saved(OUT/'tracked.bin',b'tracked inert fixture\n');tests.append(dict(name='exclusive tracked fdopen succeeds',passed=True))
denied('untracked writable fdopen',lambda:os.fdopen(untracked_fd,'wb'))
try:os.close(untracked_fd)
except OSError:pass
denied('aliased writable descriptor registration',lambda:gate.register(aliased_fd,aliased,'owned_output'))
os.close(aliased_fd)
denied('general writable directory open',lambda:io.open(LEDGER.parent,'w+b'))
denied('genuine tempfile outside writer phase',lambda:tempfile.NamedTemporaryFile(dir=LEDGER.parent,prefix='.daemon-reservation-',delete=False))
with gate.atomic_writer():
    denied('unapproved atomic prefix',lambda:tempfile.NamedTemporaryFile(dir=LEDGER.parent,prefix='wrong-',delete=False))
    with tempfile.NamedTemporaryFile(dir=LEDGER.parent,prefix='.daemon-reservation-',delete=False) as stream:
        assert stream.fileno() in gate.fd_registry
        stream.write(b'normal atomic writer fixture\n');stream.flush();os.fsync(stream.fileno());temp_name=Path(stream.name)
    os.replace(temp_name,LEDGER)
tests.append(dict(name='genuine NamedTemporaryFile directory event and tracked atomic FD succeed',passed=True))
assert LEDGER.read_bytes()==b'normal atomic writer fixture\n'
assert not gate.fd_registry and not gate.writer_phase
assert hashlib.sha256(REAL.read_bytes()).hexdigest()==before
result=dict(schema='owned-closeout-write-boundary-tests/v1',passed=True,tests=tests,test_count=len(tests),
    real_ledger_sha256_before=before,real_ledger_sha256_after=before,real_ledger_modified=False,
    reservation_or_scheduler_activity=False,model_calls=0,owned_fixture_directory=str(ROOT))
saved(OUT/'result.json',json.dumps(result,sort_keys=True,indent=2).encode()+b'\n')
print(json.dumps(result,sort_keys=True))

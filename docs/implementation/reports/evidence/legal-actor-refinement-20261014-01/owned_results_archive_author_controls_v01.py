"""Small real temporary fixtures only; no historical outputs or preparation main."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import sys
sys.dont_write_bytecode=True
F=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('opaque_archive_fixture_subject',F/'prepare_owned_results_archive_v01.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
cases=[]
def pin(path):
    raw=Path(path).read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
def check(name,fn,refuses=False):
    try:fn()
    except ValueError:
        if not refuses:raise
    else:
        if refuses:raise AssertionError(name+' accepted')
    cases.append(dict(name=name,passed=True,expected_refusal=refuses))
with tempfile.TemporaryDirectory(prefix='archive-author-fixture-',dir=F) as temp:
    root=Path(temp);a.RUN=root/'run';a.RUN.mkdir();result=a.RUN/'owned-completed/results';result.mkdir(parents=True)
    (result/'nested').mkdir();(result/'first.bin').write_bytes(b'opaque numerical-looking bytes\x00\xff'*67)
    (result/'nested/second.json').write_bytes(b'{not JSON and never parsed}\n'*91)
    names=[result/'first.bin',result/'nested/second.json'];row=dict(attempt='owned-completed',result_directory=str(result),
        files=2,result_bytes=sum(path.stat().st_size for path in names),nested_directories=['nested'])
    deadline=time.monotonic()+30;entries,dirs=a.collect_files([row],deadline)
    check('closed nested opaque inventory',lambda:a.require(len(entries)==2 and len(dirs)==2,'inventory'))
    one=root/'archive1.tar.gz';two=root/'archive2.tar.gz';p1=a.pack(entries,one,deadline);p2=a.pack(entries,two,deadline)
    check('deterministic compressed byte representation',lambda:a.require(p1['sha256']==p2['sha256'],'determinism'))
    stage=root/'restore';stage.mkdir();verified=a.verify_restore(entries,one,stage,deadline)
    check('every member restorative fsync/rawhash/readback exact',lambda:a.require(verified['member_count']==2 and verified['raw_bytes']==row['result_bytes']
        and not (stage/'restore-probe.bin').exists(),'restoration'))
    bad=copy.deepcopy(entries);bad[0]['sha256']='0'*64
    check('altered restoration raw hash refused',lambda:a.verify_restore(bad,one,stage,deadline),True)
    if (stage/'restore-probe.bin').exists():(stage/'restore-probe.bin').unlink()
    check('traversal member rejected',lambda:a.member_name(a.RUN/'../outside/results/x'),True)
    check('protected donor member rejected',lambda:a.member_name(a.RUN/'conditions-presence-20261014-conditions-presence-ce-01/results/x'),True)
    check('cache member rejected',lambda:a.member_name(a.RUN/'arbitrary-native-cache-20261011-02/results/x'),True)
    link=result/'link';link.symlink_to(result/'first.bin')
    check('symlink original refused',lambda:a.collect_files([dict(row,files=3)],deadline),True);link.unlink()
    hard=result/'hard';os.link(result/'first.bin',hard)
    check('aliased inode refused',lambda:a.collect_files([dict(row,files=3)],deadline),True);hard.unlink()
    extra=result/'extra';extra.write_bytes(b'extra')
    check('unexpected extra member refused by fixed intake',lambda:a.collect_files([row],deadline),True);extra.unlink()
    (result/'first.bin').write_bytes(b'drifted')
    check('source identity/byte drift before packing refused',lambda:a.pack(entries,root/'refused.tar.gz',deadline),True)
    check('private endpoint path refused before access',lambda:a.opaque_pin(root/'disk-reservations.json'),True)
out=F/'owned-results-archive-author-controls-v01.json'
v=dict(schema='actor-refinement-owned-results-archive-author-controls/v1',passed=True,findings=[],control_count=len(cases),controls=cases,
    producer=pin(F/'prepare_owned_results_archive_v01.py'),source=pin(Path(__file__).resolve()),
    fixture_only=True,actual_original_result_bytes_read=0,actual_prepare_main_calls=0,private_body_reads=0,global_censuses=0,
    original_moves=0,original_unlinks=0,claims_modified=0,model_calls=0,numerical_imports=0,resource_API_calls=0)
with out.open('x') as stream:json.dump(v,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
out.chmod(0o444);print(json.dumps(pin(out),sort_keys=True))

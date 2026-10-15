"""Pure public predicates and temporary-file helpers only; never apply main."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
sys.dont_write_bytecode=True
F=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('archive_apply_fixture_subject',F/'apply_owned_results_archive_v01.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
cases=[]
def pin(path):
    raw=Path(path).read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
def check(name,fn,refuses=False):
    try:fn()
    except (ValueError,OSError):
        if not refuses:raise
    else:
        if refuses:raise AssertionError(name+' accepted')
    cases.append(dict(name=name,passed=True,expected_refusal=refuses))
prepared=json.loads((F/'owned-results-archive-prepared-v01.json').read_bytes())
check('exact actual public prepared proof passes',lambda:m.validate_prepared(prepared))
bad=copy.deepcopy(prepared);bad['target800M_met']=True
check('false800M success refused',lambda:m.validate_prepared(bad),True)
bad=copy.deepcopy(prepared);bad['projected_net_apparent_savings_lower_bound_bytes']=749999999
check('savings below concrete750M threshold refused',lambda:m.validate_prepared(bad),True)
bad=copy.deepcopy(prepared);bad['originals'][0]['path']=str(m.a.RUN/'conditions-presence-20261014-conditions-presence-ce-01/results/x')
check('protected donor archival refused',lambda:m.validate_prepared(bad),True)
bad=copy.deepcopy(prepared);bad['originals'][1]=copy.deepcopy(bad['originals'][0])
check('duplicate prepared member refused',lambda:m.validate_prepared(bad),True)
with tempfile.TemporaryDirectory(prefix='archive-apply-author-fixture-',dir=F) as temp:
    root=Path(temp);source=root/'original';source.write_bytes(b'opaque verified fixture\x00\xff'*100)
    expected=pin(source);target=root/'counted-archive';deadline=time.monotonic()+30
    actual=m.publish_copy(source,target,expected,deadline)
    check('counted publication fsynced and rawbyte exact',lambda:m.a.require(m.same_raw(actual,expected)
        and source.exists() and stat.S_IMODE(target.stat().st_mode)==0o444,'publication'))
    check('existing counted publication never overwritten',lambda:m.publish_copy(source,target,expected,deadline),True)
    info=source.stat();row=dict(**expected,member='fixture/results/original',device=info.st_dev,inode=info.st_ino,mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,mode=stat.S_IMODE(info.st_mode),uid=info.st_uid,gid=info.st_gid)
    check('exact original raw/identity fence passes',lambda:m.validate_original(row,deadline))
    bad=copy.deepcopy(row);bad['sha256']='0'*64
    check('changed original raw bytes refused before move',lambda:m.validate_original(bad,deadline),True)
    m.QUARANTINE=root/'private-quarantine';m.QUARANTINE.mkdir(mode=0o700);events=[]
    captured=m.quarantine_verified(row,0,events.append,deadline)
    check('verified quarantine preserves bytes before any deletion',lambda:m.a.require(captured.exists() and not source.exists()
        and pin(captured)['sha256']==expected['sha256'] and [x['event'] for x in events]==['intent','quarantined_verified'],'quarantine'))
    check('existing quarantine destination never overwritten',lambda:m.quarantine_verified(dict(row,path=str(captured)),0,events.append,deadline),True)
    hf=dict(schema='actor-refinement-owned-results-archive-hf-publication/v1',passed=True,findings=[],repo='Publicus/legal-ir-autoencoder',
        revision='a'*40,archive=expected,manifest=m.PREPARED_PIN,downloaded_archive=actual,downloaded_manifest=pin(F/'owned-results-archive-prepared-v01.json'),
        all_prior_file_identities_preserved=True,default_promotion=False)
    check('actual-style independent immutable readback predicate',lambda:m.validate_hf(hf,dict(archive=expected)))
    bad=copy.deepcopy(hf);bad['all_prior_file_identities_preserved']=False
    check('priorHFidentity mutation refused',lambda:m.validate_hf(bad,dict(archive=expected)),True)
    bad=copy.deepcopy(hf);bad['downloaded_archive']['sha256']='f'*64
    check('incorrect immutable raw readback refused',lambda:m.validate_hf(bad,dict(archive=expected)),True)
out=F/'owned-results-archive-apply-author-controls-v01.json'
value=dict(schema='actor-refinement-owned-results-archive-apply-author-controls/v1',passed=True,findings=[],control_count=len(cases),controls=cases,
    producer=pin(F/'apply_owned_results_archive_v01.py'),source=pin(Path(__file__).resolve()),prepared=m.PREPARED_PIN,
    fixture_only=True,actual_apply_main_calls=0,actual_original_moves=0,actual_original_unlinks=0,actual_archive_publications=0,
    private_body_reads=0,resource_API_calls=0,global_censuses=0,model_calls=0,numerical_imports=0)
with out.open('x') as stream:json.dump(value,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
out.chmod(0o444);print(json.dumps(pin(out),sort_keys=True))

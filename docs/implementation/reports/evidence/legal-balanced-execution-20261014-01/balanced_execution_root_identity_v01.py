"""Closed F14 root-identity metadata helpers; unchanged F12 records and native owner."""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

sys.dont_write_bytecode=True
F=Path(__file__).resolve().parent
P=Path('/home/barberb/lift_coding/artifacts/legal-conditions-recall-20261014-01')
PROTOCOL=P/'conditions_balanced_resource_protocol_v01.py'
PROTOCOL_PIN=dict(path=str(PROTOCOL),bytes=13965,sha256='265d96839054a16d4c4ab0f2550dc69948263a87566e9337a429b3ddb02f69f0')
BASELINE_PIN=dict(path=str(P/'resource-baseline-v01.json'),bytes=77889,sha256='9fd03480b85fb3b9a9164a4b4e87b4807bf8c65419a1037edccbb1b04723775f')
OWNER=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/native4096-four-width-20261004/resource-cap/autoencoder_daemon_resources.py')
OWNER_PIN=dict(path=str(OWNER),bytes=36724,sha256='b00d2752ba852fe73760bba4fbd51b0e845742c3527642606a2a77ed9f8f5e2c')
LEDGER=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json')
_raw=PROTOCOL.read_bytes()
if len(_raw)!=PROTOCOL_PIN['bytes'] or hashlib.sha256(_raw).hexdigest()!=PROTOCOL_PIN['sha256']:
    raise ValueError('exact qualified F12 protocol required before import')
_spec=importlib.util.spec_from_file_location('qualified_f12_root_identity_protocol',PROTOCOL)
p=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(p)
require=p.require
digest=p.digest


def snapshot(metadata,descriptor,contract):
    path=Path(descriptor['path'])
    require(path.name=='snapshot-receipt-v01.json' and path.parent.parent==F/'private-runtime-snapshots','exact F14 private receipt required')
    metadata.private.add(path);metadata.allow(path);receipt=metadata.read(path,descriptor)
    require(receipt['schema']=='conditions-balanced-private-endpoints/v1' and receipt['role']=='opening' and receipt['cell'] is None
        and type(receipt['index']) is int and 1<=receipt['index']<=99,'exact opening sample role required')
    require(path.parent.name=='opening-v'+str(receipt['index']).zfill(2),'true opening role directory required')
    for directory in (path.parent.parent,path.parent):
        require(directory.resolve(strict=True)==directory and not directory.is_symlink() and stat.S_IMODE(directory.stat().st_mode)==0o700,'private700 directories required')
    values=[]
    for name,endpoint in (('ledger',p.LEDGER),('scheduler',p.SCHEDULER)):
        target=Path(receipt[name]['path'])
        require(target==path.parent/(name+'.json') and receipt['source_'+name]['path']==str(endpoint)
            and all(receipt[name][key]==receipt['source_'+name][key] for key in ('bytes','sha256')),'exact copied endpoint bytes required')
        require(stat.S_IMODE(target.stat().st_mode)==0o400,'private400 copy required')
        metadata.private.add(target);values.append(metadata.read(target,receipt[name]))
    require(stat.S_IMODE(path.stat().st_mode)==0o400,'private400 receipt required')
    return receipt,*values


def prior_context(metadata):
    metadata.pin(PROTOCOL,PROTOCOL_PIN)
    contract=p.qualify_contract(metadata.read(p.CONTRACT,p.CONTRACT_PIN))
    baseline=metadata.read(BASELINE_PIN['path'],BASELINE_PIN)
    hashes=baseline['baseline_ledger']['record_body_hashes']
    require(baseline['schema']=='conditions-balanced-resource-baseline/v1' and baseline['passed'] is True and baseline['findings']==[]
        and len(hashes)==538 and digest(hashes)==contract['prior_record_body_hash_map_sha256']
        and baseline['baseline_ledger']['record_body_hash_map_sha256']==digest(hashes)
        and baseline['counted_root_metadata']==contract['counted_root_metadata'],'exact qualified historical538 anchor required')
    effective=copy.deepcopy(contract)
    for field in ('guardian','sampler'):
        old=contract[field];effective[field]=dict(old,path=str(F/Path(old['path']).name));metadata.pin(effective[field]['path'],effective[field])
    producers={}
    for path,brief in contract['resource_producer_pins'].items():
        target=str(F/Path(path).name) if Path(path).parent==P else path
        metadata.pin(target,dict(path=target,**brief));producers[target]=brief
    effective['resource_producer_pins']=producers
    metadata.pin(OWNER,OWNER_PIN)
    return contract,effective,baseline,hashes


def physical_roots(metadata,contract):
    helpers=p.census_helpers(metadata,contract)
    roots=[Path(row['path']) for row in contract['counted_root_metadata']]
    before=[helpers['_root_identity'](root) for root in roots]
    require(before[:3]==contract['counted_root_metadata'][:3] and len(before)==4
        and before[3]['path']==contract['counted_root_metadata'][3]['path']
        and before[3]['device']==contract['counted_root_metadata'][3]['device'],'three persistent roots and temporary device/path must remain exact')
    info=roots[3].lstat()
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_uid==1000
        and stat.S_IMODE(info.st_mode)==0o700,'real uid1000 mode0700 temporary directory required')
    require([helpers['_root_identity'](root) for root in roots]==before,'current physical root identity changed')
    return before,dict(path=str(roots[3]),device=info.st_dev,inode=info.st_ino,uid=info.st_uid,gid=info.st_gid,mode='0o700')


def qualify_ledger_roots(contract,ledger,hashes,current_roots):
    require(ledger.get('roots') in (contract['counted_root_metadata'],current_roots),'only exact historical or current physical roots allowed')
    effective=dict(contract,counted_root_metadata=ledger['roots'])
    status=p.qualify_ledger(effective,ledger,hashes)
    require(status['record_count']==538 and status['full_nonreleased_claim_bytes']==44381777216,'same538 full claims required')
    return status,ledger['roots']!=current_roots


def qualify_opening(metadata,inputs):
    require(set(inputs)=={'schema','contract','baseline','sample_receipt','check','sampler_qualification','bridge_qualification'}
        and inputs['schema']=='conditions-balanced-root-identity-preflight-inputs/v1'
        and inputs['contract']==p.CONTRACT_PIN and inputs['baseline']==BASELINE_PIN,'closed exact root-approved preflight inputs required')
    contract,effective,baseline,hashes=prior_context(metadata)
    current,temporary=physical_roots(metadata,contract)
    receipt,ledger,state=snapshot(metadata,inputs['sample_receipt'],effective)
    status,needed=qualify_ledger_roots(contract,ledger,hashes,current)
    check=metadata.read(inputs['check']['path'],inputs['check'])
    scheduler=p.qualify_check(effective,check,receipt,state)
    q=metadata.read(inputs['sampler_qualification']['path'],inputs['sampler_qualification'])
    require(q['schema']=='conditions-balanced-sampler-source-independent-review/v1' and q['passed'] is True and q['findings']==[]
        and q['sampler']==effective['sampler'],'exact relocated qualified sampler required')
    bridge=metadata.read(inputs['bridge_qualification']['path'],inputs['bridge_qualification'])
    require(bridge['schema']=='conditions-balanced-resource-bridge-source-independent-review/v1'
        and bridge['passed'] is True and bridge['findings']==[],'qualified unchanged relocated bridge required')
    for path,brief in effective['resource_producer_pins'].items():
        require(check['producers'][path]==dict(path=path,**brief),'fixed ten actual resource producer pins differ')
    require(physical_roots(metadata,contract)[0]==current,'physical roots changed across copied-state qualification')
    return dict(contract=contract,effective=effective,baseline=baseline,hashes=hashes,current=current,temporary=temporary,
        receipt=receipt,ledger=ledger,status=status,needed=needed,scheduler=scheduler)


def qualify_transition(before,after,contract,hashes,current_roots):
    require(set(before)==set(after)=={'schema','roots','limit_bytes','reservations'}
        and before['schema']==after['schema']=='daemon-resource-reservations-v1'
        and before['limit_bytes']==after['limit_bytes']==145000000000
        and after['roots']==current_roots and before['reservations']==after['reservations'],
        'only top-level roots identity bookkeeping may change')
    a,_=qualify_ledger_roots(contract,before,hashes,current_roots)
    b,_=qualify_ledger_roots(contract,after,hashes,current_roots)
    require(a['record_body_hashes']==b['record_body_hashes']==hashes,'all538 body hashes must be exact before and after')
    return b


def native_owner(metadata):
    """Compile unchanged native function/class AST; scheduler binding is a hard refusal."""
    metadata.pin(OWNER,OWNER_PIN);tree=ast.parse(OWNER.read_bytes())
    relative=[n for n in tree.body if isinstance(n,ast.ImportFrom) and n.level]
    require(len(relative)==1 and relative[0].module=='resource_scheduler'
        and [(a.name,a.asname) for a in relative[0].names]==[('ResourceLane',None),('get_global_resource_scheduler',None)],
        'exact native scheduler import required')
    def no_scheduler(*args,**kwargs):raise ValueError('administrative root migration cannot acquire scheduler admission')
    ns=dict(__name__='qualified_native_root_identity_administration',__file__=str(OWNER),
        ResourceLane=SimpleNamespace(HAMMER_LEAN='hammer_lean'),get_global_resource_scheduler=no_scheduler)
    nodes=[n for n in tree.body if n not in relative]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(OWNER),'exec'),ns)
    return SimpleNamespace(**ns)


def read_locked_raw(native,owner):
    native._safe_path(owner.ledger_path)
    descriptor=os.open(owner.ledger_path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,'rb') as stream:
        info=os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and 0<info.st_size<=native.MAX_LEDGER_BYTES,'bounded unaliased regular existing ledger required')
        raw=stream.read(native.MAX_LEDGER_BYTES+1)
        require(len(raw)==info.st_size,'locked ledger length changed')
        again=owner.ledger_path.lstat()
        require((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)==
            (again.st_dev,again.st_ino,again.st_size,again.st_mtime_ns,again.st_ctime_ns),'locked ledger identity drift')
    value=json.loads(raw,object_pairs_hook=native._json_pairs,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite ledger value')))
    return raw,value,dict(path=str(owner.ledger_path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def durable_backup(raw):
    directory=F/'private-root-identity-rebind-v01'
    os.mkdir(directory,0o700)
    require(stat.S_IMODE(directory.lstat().st_mode)==0o700 and directory.resolve(strict=True)==directory,'exclusive private700 backup directory required')
    target=directory/'ledger-before.json'
    descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
    try:
        view=memoryview(raw)
        while view:
            written=os.write(descriptor,view);require(written>0,'backup write made no progress');view=view[written:]
        os.fsync(descriptor);info=os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size==len(raw) and stat.S_IMODE(info.st_mode)==0o400,'exact private400 durable backup required')
    finally:os.close(descriptor)
    for parent in (directory,F):
        fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    copied=target.read_bytes()
    require(copied==raw,'exact before-ledger backup differs')
    return dict(path=str(target),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),mode='0o400',file_fsynced=True,directory_fsynced=True)

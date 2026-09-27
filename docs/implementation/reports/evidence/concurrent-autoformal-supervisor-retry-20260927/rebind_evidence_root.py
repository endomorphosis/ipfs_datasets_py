"""Explicit one-field evidence-root rebind after verified Git synchronization."""
import hashlib,json,os,stat,subprocess,copy
from collections import Counter
from pathlib import Path
from dependency_export_common import ROOT,HERE,LEDGER,ScopedSources,bootstrap,environment,durable,save,require

OUT=HERE/'evidence-root-rebind-20260927'
EXPECTED='ec09155e91695bd60020d9f55ee04de0e9f2866c5d6750a6adc90f55fc17cb79'
EVIDENCE=ROOT/'docs/implementation/reports/evidence'
PENDING=EVIDENCE/'concurrent-autoformal-supervisor-retry-20260927'

def raw_ledger():
    fd=os.open(LEDGER,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<8_000_000,'unsafe ledger')
        raw=stream.read()
    require(hashlib.sha256(raw).hexdigest()==EXPECTED,'ledger changed since review')
    return raw

def verify_evidence():
    raw=subprocess.check_output(['git','ls-tree','-r','-z','f24d83a2b0b646e1ac872d4f09566d8b5c31403f','--','docs/implementation/reports/evidence'],cwd=ROOT)
    rows=[]
    for record in raw.split(b'\0'):
        if not record:continue
        meta,name=record.split(b'\t',1);mode,kind,oid=meta.decode().split()
        require(kind=='blob' and mode in {'100644','100755'},'unexpected published object')
        path=ROOT/name.decode();info=path.lstat()
        require(stat.S_ISREG(info.st_mode),'published evidence not regular')
        digest=hashlib.sha1(b'blob '+str(info.st_size).encode()+b'\0')
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        require(digest.hexdigest()==oid and path.lstat()==info,'published evidence changed')
        rows.append({'path':name.decode(),'bytes':info.st_size,'git_blob':oid})
    require(len(rows)==289 and sum(x['bytes'] for x in rows)==153071181,'published inventory changed')
    raw=(PENDING/'manifest.json').read_bytes()
    require(hashlib.sha256(raw).hexdigest()=='4af29c0dcacd9e0acad5714a35184f08df293aa0f598f0c1814887c11a48efd4','pending manifest changed')
    pending=json.loads(raw)['artifacts']
    require(len(pending)==40,'pending inventory changed')
    for name,entry in pending.items():
        path=PENDING/name;require(path.resolve()==path and path.is_file(),'aliased pending artifact')
        content=path.read_bytes()
        require(len(content)==entry['bytes'] and hashlib.sha256(content).hexdigest()==entry['sha256'],'pending artifact changed: '+name)
    return {'published_commit':'f24d83a2b0b646e1ac872d4f09566d8b5c31403f','published_files':289,'published_bytes':153071181,'pending_files':40,'pending_bytes':sum(x['bytes'] for x in pending.values()),'pending_manifest_sha256':hashlib.sha256(raw).hexdigest(),'scope':'Published and pending evidence verified; no complete pre-sync untracked inventory is asserted.'}

OUT.mkdir(exist_ok=False)
os.environ.clear() if False else None
clean=environment(OUT);os.environ.clear();os.environ.update(clean)
sources=ScopedSources();bootstrap(sources)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation,MAX_STORAGE_BYTES
require(MAX_STORAGE_BYTES==75_000_000_000,'cap changed')
roots=[ROOT/'workspace/test-logs',ROOT/'workspace/todo-queues',EVIDENCE,Path('/tmp/pytest-of-barberb')]
owner=DaemonResourceReservation(LEDGER,roots=roots,storage_bytes=1,memory_mb=1,ledger_lock_timeout_seconds=5)
with owner._locked():
    oldraw=raw_ledger();old=json.loads(oldraw)
    require(set(old)=={'schema','limit_bytes','roots','reservations'} and old['schema']=='daemon-resource-reservations-v1' and old['limit_bytes']==MAX_STORAGE_BYTES,'ledger schema or cap changed')
    counts=dict(Counter(x['status'] for x in old['reservations'].values()))
    require(len(old['reservations'])==89 and counts=={'retained':36,'released':53},'reservation inventory changed')
    require(old['roots'][2]=={'path':str(EVIDENCE),'device':66306,'inode':51016135},'prior root changed')
    candidate=copy.deepcopy(old);candidate['roots'][2]['inode']=51016937
    require(candidate['roots']==owner.root_identities and candidate['reservations']==old['reservations'],'unexpected root or reservation change')
    evidence=verify_evidence();account_before=owner._account(candidate)
    require(account_before['outstanding_full_reservations_bytes']==18235000000,'retained charge changed')
    (OUT/'before-ledger.json').write_bytes(oldraw)
    (OUT/'proposed-ledger.json').write_text(json.dumps(candidate,sort_keys=True,separators=(',',':'))+'\n')
    durable(OUT)
    require(raw_ledger()==oldraw,'ledger changed before write');owner._verify_owner_roots()
    owner._write(candidate)
    observed=owner._read();require(observed==candidate,'migration readback differs')
    afterraw=LEDGER.read_bytes();(OUT/'after-ledger.json').write_bytes(afterraw)
    receipt={'schema':'explicit-evidence-root-rebind/v1','changed_field':'roots[2].inode','before_inode':51016135,'after_inode':51016937,'path':str(EVIDENCE),'device':66306,'old_ledger_sha256':EXPECTED,'new_ledger_sha256':hashlib.sha256(afterraw).hexdigest(),'reservation_records_unchanged':True,'reservation_count':89,'statuses':counts,'cap_bytes':MAX_STORAGE_BYTES,'other_root_identities_unchanged':True,'preservation':evidence,'accounting':account_before,'new_reservation_acquired':False,'claims_released':False,'authority':'Maintenance necessary for authorized main sync and bounded retry; no accounting guard relaxed.','admitted':False,'formalized':False,'sources':sources.verify()}
    save(OUT/'receipt.json',receipt)
    durable(OUT)
print(json.dumps({'rebound':True,'receipt':str(OUT/'receipt.json'),'ledger_sha256':receipt['new_ledger_sha256'],'records_preserved':89}))

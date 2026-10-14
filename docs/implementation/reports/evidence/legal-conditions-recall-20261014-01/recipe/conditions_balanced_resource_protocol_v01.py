"""Closed parameterized resource metadata predicates; no production resource imports or APIs."""
import ast
from collections import Counter
import hashlib,json,math,os,stat
from pathlib import Path

F=Path(__file__).resolve().parent
LEDGER=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json')
SCHEDULER=Path('/tmp/ipfs-datasets-resource-scheduler-1000.json')
CONTRACT=F/'resource-protocol-contract-v01.json'
CONTRACT_PIN=dict(path=str(CONTRACT),bytes=8109,sha256='34dd2cf9422d076e647f73666d4d10913ebfa62d4ceb78ba6102797cc857acd5')


def require(value,message):
    if not value:raise ValueError(message)


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()


class Metadata:
    """Exact own public input descriptors and explicitly authenticated private copies only."""
    def __init__(self,output):
        self.output=Path(output);self.reads={};self.private=set();self.allowed=set()
    def allow(self,*paths):self.allowed.update(Path(path) for path in paths)
    def pin(self,path,expected=None):
        path=Path(path)
        require(path.is_absolute() and path.resolve(strict=True)==path and not path.is_symlink(),'physical absolute file required')
        require(path not in (LEDGER,SCHEDULER) and ('private-runtime-snapshots' not in path.parts or path in self.private),'live/unqualified private bodies prohibited')
        require('checkpoint' not in path.name and 'reference-packet' not in path.name,'model/reference bodies prohibited')
        a=path.stat();require(stat.S_ISREG(a.st_mode) and 0<a.st_size<=16*1024*1024,'bounded ordinary metadata/source required')
        raw=path.read_bytes();b=path.stat();identity=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
        require(identity(a)==identity(b) and len(raw)==a.st_size,'raw metadata/source drift')
        value=dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        require(expected is None or value==expected,'exact raw descriptor differs')
        require(str(path) not in self.reads or self.reads[str(path)]==value,'consumed raw identity drift')
        self.reads[str(path)]=value;return value
    def read(self,path,expected=None):
        self.allow(path);captured=self.pin(path,expected);raw=Path(path).read_bytes()
        require(len(raw)==captured['bytes'] and hashlib.sha256(raw).hexdigest()==captured['sha256'],'consumed metadata bytes differ')
        def pairs(items):
            value={}
            for k,v in items:require(k not in value,'duplicate JSON key');value[k]=v
            return value
        def finite(raw):
            value=float(raw);require(math.isfinite(value),'nonfinite JSON');return value
        value=json.loads(raw,object_pairs_hook=pairs,parse_float=finite,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
        self.pin(path,captured);return value
    def fence(self):
        for path,expected in list(self.reads.items()):self.pin(path,expected)
    def audit(self,event,args):
        if event=='import' and args[0].split('.')[0] in {'torch','numpy','ipfs_datasets_py','transformers','huggingface_hub'}:
            raise ValueError('production/numerical/SDK import prohibited')
        if event.startswith(('subprocess.','socket.','os.exec','os.spawn')) or event in {'os.system','os.fork','os.posix_spawn','os.kill','os.killpg','fcntl.flock','os.mkdir','os.remove','os.rmdir','os.rename','os.replace','os.unlink'}:
            raise ValueError('process/network/lock/shared mutation prohibited')
        if event=='open':
            name,mode,flags=args;target=Path(os.fsdecode(name)).absolute() if isinstance(name,(str,bytes,os.PathLike)) else None
            require(target not in (LEDGER,SCHEDULER),'live global endpoint body prohibited')
            if target is not None:
                require('checkpoint' not in target.name and 'reference-packet' not in target.name,'model/reference body prohibited')
                require('private-runtime-snapshots' not in target.parts or target in self.private or target in self.allowed,'only authenticated private copies allowed')
            writing=isinstance(mode,str) and any(c in mode for c in 'wax+')
            writing|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
            require(not writing or target==self.output and bool(flags&os.O_EXCL),'only exclusive own receipt write permitted')
        if event in {'os.chmod','os.chown','os.truncate','os.utime','os.link','os.symlink'}:
            require(event=='os.chmod' and Path(args[0]).absolute()==self.output and args[1]==0o444,'only own receipt freeze permitted')
    def write(self,value):
        self.fence()
        with self.output.open('x') as out:json.dump(value,out,sort_keys=True,indent=2,allow_nan=False);out.write('\n');out.flush();os.fsync(out.fileno())
        self.output.chmod(0o444);return self.pin(self.output)


def qualify_contract(contract):
    require(contract['schema']=='conditions-balanced-resource-protocol-contract/v1'
        and contract['phase_root']==str(F) and contract['prior_record_count']==538 and contract['expected_closing_record_count']==539
        and contract['max_new_claims']==1 and contract['global_cap_bytes']==145000000000
        and contract['resources']==dict(cpu_slots=2,memory_mb=1536,child_process_slots=1,storage_bytes=200000000,
            child_deadline_seconds=300,admission_timeout_seconds=120,ledger_lock_timeout_seconds=60)
        and len(contract['counted_root_metadata'])==4 and len(contract['resource_producer_pins'])==10
        and contract['body_change_authorized'] is contract['claim_reconciliation_authorized'] is contract['foreign_mutation_authorized'] is False,
        'closed one-candidate538-to539 resource contract required')
    return contract


def prior_hashes(contract,baseline,terminal):
    hashes=dict(baseline['baseline_ledger']['record_body_hashes']);claim=terminal['only_new_own_claim']
    require(baseline['schema']=='conditions-presence-resource-baseline/v1' and baseline['passed'] is True and baseline['findings']==[]
        and terminal['schema']=='conditions-presence-terminal-resource-audit/v1' and terminal['passed'] is True and terminal['findings']==[]
        and len(hashes)==terminal['opening_record_count']==terminal['preserved_prior_record_count']==537
        and digest(hashes)==terminal['prior_record_body_hash_map_sha256'],'qualified full N11 opening custody required')
    require(claim['reservation_id'] not in hashes and claim['status']=='released' and claim['storage_bytes']==200000000,'exact new released N11 claim required')
    hashes[claim['reservation_id']]=claim['record_body_sha256']
    require(len(hashes)==terminal['closing_record_count']==contract['prior_record_count']
        and digest(hashes)==terminal['closing_record_body_hash_map_sha256']==contract['prior_record_body_hash_map_sha256'],
        'authenticated full current538 body hash map required')
    return hashes


def qualify_ledger(contract,ledger,hashes,*,own_id=None):
    require(type(ledger) is dict and set(ledger)=={'schema','roots','limit_bytes','reservations'}
        and ledger['schema']=='daemon-resource-reservations-v1' and type(ledger['limit_bytes']) is int
        and ledger['limit_bytes']==contract['global_cap_bytes'] and ledger['roots']==contract['counted_root_metadata'],'same global schema/cap/fourroots required')
    bodies=ledger['reservations'];require(type(bodies) is dict and len(bodies)<=4096
        and all(type(k) is str and type(v) is dict for k,v in bodies.items()),'bounded ordinary reservation map required')
    actual={key:digest(body) for key,body in bodies.items()}
    require(all(actual.get(key)==value for key,value in hashes.items()),'every authenticated prior record body must remain exact')
    expected_extra=set() if own_id is None else {own_id}
    require(own_id is None or own_id not in hashes,'fresh own claim ID required')
    require(set(actual)-set(hashes)==expected_extra and len(actual)==len(hashes)+len(expected_extra),'only one exact public-bound own new claim allowed')
    require(all(body.get('reservation_id')==key and body.get('status') in {'released','retained','active','reserved'}
        and type(body.get('storage_bytes')) is int and body['storage_bytes']>=0 for key,body in bodies.items()),'valid fullclaims required')
    for preserved in contract['required_preserved_claims']:
        body=bodies[preserved['reservation_id']]
        require(body['status']==preserved['status'] and body['storage_bytes']==preserved['storage_bytes'],'historical own claim status must remain conserved')
    statuses=dict(Counter(body['status'] for body in bodies.values()));claims=sum(body['storage_bytes'] for body in bodies.values() if body['status']!='released')
    expected=contract['prior_record_status_counts'] if own_id is None else contract['expected_closing_record_status_counts']
    require(statuses==expected and claims==contract['prior_full_nonreleased_claim_bytes'],'conserved statuses/fullclaims required')
    if own_id is not None:require(bodies[own_id]['status']=='released' and bodies[own_id]['storage_bytes']==contract['resources']['storage_bytes'],'own successful claim must be released within unchanged200M')
    return dict(record_count=len(actual),record_body_hashes=actual,record_body_hash_map_sha256=digest(actual),record_status_counts=statuses,
        full_nonreleased_claim_bytes=claims,all_prior_record_bodies_unchanged=True,preserved_prior_record_count=len(hashes),additional_current_records=list(expected_extra))


def snapshot(metadata,descriptor,role,contract):
    path=Path(descriptor['path']);require(path.name=='snapshot-receipt-v01.json' and path.parent.parent==F/'private-runtime-snapshots','exact owned private receipt required')
    metadata.private.add(path);metadata.allow(path);receipt=metadata.read(path,descriptor)
    require(receipt['schema']=='conditions-balanced-private-endpoints/v1' and receipt['role']==role
        and (receipt['cell'] is None if role=='opening' else receipt['cell']==contract['cell']) and type(receipt['index']) is int and 1<=receipt['index']<=99,'exact phase/role/index required')
    label=role+('' if role=='opening' else '-'+contract['cell'])+'-v'+str(receipt['index']).zfill(2)
    require(path.parent.name==label,'true sample role directory required')
    for directory in (path.parent.parent,path.parent):require(directory.resolve(strict=True)==directory and not directory.is_symlink() and stat.S_IMODE(directory.stat().st_mode)==0o700,'private700 directories required')
    values=[]
    for name,endpoint in (('ledger',LEDGER),('scheduler',SCHEDULER)):
        target=Path(receipt[name]['path']);require(target==path.parent/(name+'.json') and receipt['source_'+name]['path']==str(endpoint)
            and all(receipt[name][key]==receipt['source_'+name][key] for key in ('bytes','sha256')),'exact copied endpoint bytes required')
        require(stat.S_IMODE(target.stat().st_mode)==0o400,'private400 copy required');metadata.private.add(target);values.append(metadata.read(target,receipt[name]))
    require(stat.S_IMODE(path.stat().st_mode)==0o400,'private400 receipt required')
    return receipt,*values


def census_helpers(metadata,contract):
    path=next(Path(p) for p in contract['resource_producer_pins'] if Path(p).name=='autoencoder_daemon_resources.py')
    metadata.pin(path,dict(path=str(path),**contract['resource_producer_pins'][str(path)]));tree=ast.parse(path.read_bytes())
    names={'_safe_path','_checked_path','_root_identity','_inventory_descendant','_inventory_entry_disappeared','_inventory'}
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    error=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DaemonResourceError')
    require(len(nodes)==len(names) and len(error.body)==1 and isinstance(error.body[0],ast.Expr),'exact read-only original census guard closure required')
    ns=dict(Path=Path,os=os,stat=stat,MAX_INVENTORY_ENTRIES=contract['limits']['max_inventory_entries'])
    exec(compile(ast.Module(body=[error,*nodes],type_ignores=[]),str(path),'exec'),ns);return ns


def qualify_check(contract,check,receipt,state):
    require(check['schema']=='scope-pilot-resource-compatibility/v1' and check['passed'] is True and check['findings']==[]
        and check['resources']==contract['resources'] and check['disk_limit_bytes']==contract['global_cap_bytes']
        and check['outstanding_full_reservations_bytes']==contract['prior_full_nonreleased_claim_bytes']
        and check['shared_config']==state['config']==contract['scheduler_config'] and digest(state['config'])==contract['scheduler_config_sha256']
        and type(state['leases']) is dict and type(state['waiters']) is dict
        and check['lease_count']==len(state['leases']) and check['waiter_count']==len(state['waiters'])
        and all(check[k] is False for k in ('model_started','reservation_acquired','scheduler_client_constructed','shared_state_modified','admission_guaranteed')),
        'exact contemporaneous compatibility/config/typed occupancy required')
    for name,key in (('ledger','disk_ledger'),('scheduler','shared_state')):
        require(all(check[key][field]==receipt[name][field] for field in ('bytes','sha256')),'freshcheck must join true copied endpoint bytes')
    require(set(check['producers'])==set(contract['resource_producer_pins']),'fixed exact ten producer paths required')
    return dict(schema_version=state['schema_version'],config=state['config'],config_sha256=digest(state['config']),resource_contract=contract['resources'],
        lease_count=len(state['leases']),waiter_count=len(state['waiters']),sampled_coexistence=True,admission_guaranteed=False)

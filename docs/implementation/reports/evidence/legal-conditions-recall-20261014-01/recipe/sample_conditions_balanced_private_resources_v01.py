"""Copy two current endpoints to new private files without resource APIs.

No reservation, client, lock, census, model or shared write occurs. Terminal
sampling also binds a successful released guardian and its own exact plan.
"""
import argparse
from datetime import datetime,timezone
import hashlib,json,math,os,stat,sys
from pathlib import Path

F=Path(__file__).resolve().parent
RUN=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
LEDGER=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json')
SCHEDULER=Path('/tmp/ipfs-datasets-resource-scheduler-1000.json')
CELLS=('conditions-balanced-ce',)
READ_PINS={}

def require(value,message):
    if not value:raise ValueError(message)

def pin(path):
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path and not path.is_symlink(),'physical absolute source required')
    a=path.stat();require(stat.S_ISREG(a.st_mode) and a.st_size<=16*1024*1024,'bounded ordinary source required before allocation')
    raw=path.read_bytes();b=path.stat()
    identity=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
    require(identity(a)==identity(b) and len(raw)==a.st_size,'source changed during read')
    return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),device=a.st_dev,inode=a.st_ino)

def brief(value):return {k:value[k] for k in ('path','bytes','sha256')}

def read(path):
    path=Path(path);require('checkpoint' not in path.name and 'reference-packet' not in path.name,'model/reference JSON prohibited')
    captured=pin(path);raw=path.read_bytes()
    require(len(raw)==captured['bytes'] and hashlib.sha256(raw).hexdigest()==captured['sha256'] and pin(path)==captured,'consumed metadata differs from captured source')
    require(str(path) not in READ_PINS or READ_PINS[str(path)]==captured,'previous parsed identity changed');READ_PINS[str(path)]=captured
    def unique(pairs):
        value={}
        for key,item in pairs:require(key not in value,'duplicate metadata key');value[key]=item
        return value
    def finite(raw):
        value=float(raw);require(math.isfinite(value),'nonfinite metadata number');return value
    return json.loads(raw,object_pairs_hook=unique,parse_float=finite,parse_constant=lambda value:(_ for _ in ()).throw(ValueError(value)))

def write(path,raw):
    with path.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    path.chmod(0o400);return pin(path)

def main(args):
    sys.dont_write_bytecode=True
    own=brief(pin(Path(__file__).resolve()))
    qualification=read(F/'sampler-source-independent-review-v01.json')
    require(qualification['schema']=='conditions-balanced-sampler-source-independent-review/v1'
        and qualification['passed'] is True and qualification['findings']==[] and qualification['sampler']==own,
        'exact independently source-qualified sampler required before any endpoint read')
    require(args.role in ('opening','terminal') and type(args.index) is int and 1<=args.index<=99,'closed sample role/index required')
    require((args.role=='opening' and args.cell is None) or (args.role=='terminal' and args.cell in CELLS),'exact cell for terminal sample required')
    label=args.role+('' if args.cell is None else '-'+args.cell)+'-v'+str(args.index).zfill(2)
    private=F/'private-runtime-snapshots';root=private/label
    require(not os.path.lexists(root),'exclusive new private sample root required')
    metadata={}
    if args.role=='terminal':
        plan_path=F/(args.cell+'-plan-v01.json');plan=read(plan_path)
        attempt='conditions-balanced-20261014-'+args.cell+'-01'
        require(plan['attempt_name']==attempt and plan['cell']==args.cell,'exact terminal cell/plan identity required')
        terminal_path=RUN/attempt/'guardian-exit.json';terminal=read(terminal_path)
        require(type(terminal['returncode']) is int and type(terminal['child_returncode']) is int
            and terminal['returncode']==terminal['child_returncode']==0 and terminal['artifacts_durable'] is True
            and terminal['resource_reservation_released'] is True,'successful durable released guardian required')
        metadata=dict(plan=brief(READ_PINS[str(plan_path)]),terminal=brief(READ_PINS[str(terminal_path)]))
    if not private.exists():private.mkdir(mode=0o700)
    require(private.resolve(strict=True)==private and private.is_dir() and not private.is_symlink()
        and stat.S_IMODE(private.stat().st_mode)==0o700,'owned physical private directory mode required')
    root.mkdir(mode=0o700)
    sources={};copies={}
    for name,source in (('ledger',LEDGER),('scheduler',SCHEDULER)):
        captured=pin(source);raw=source.read_bytes()
        require(len(raw)==captured['bytes'] and hashlib.sha256(raw).hexdigest()==captured['sha256'] and pin(source)==captured,'sampled endpoint bytes or physical identity changed')
        target=root/(name+'.json');copies[name]=write(target,raw);sources[name]=captured
        require({k:copies[name][k] for k in ('bytes','sha256')}=={k:captured[k] for k in ('bytes','sha256')},'private copy identity differs')
    for name,source in (('ledger',LEDGER),('scheduler',SCHEDULER)):
        require(pin(source)==sources[name] and pin(copies[name]['path'])==copies[name],'closing endpoint/copy sample changed')
    for path,expected in READ_PINS.items():require(pin(path)==expected,'closing consumed terminal metadata changed')
    value=dict(schema='conditions-balanced-private-endpoints/v1',role=args.role,cell=args.cell,index=args.index,observed_at_utc=datetime.now(timezone.utc).isoformat(),
        private_bodies=True,continuous_custody=False,independent_contemporaneous_copy_witness=False,resource_API_calls=0,shared_state_modified=False,
        ledger=brief(copies['ledger']),scheduler=brief(copies['scheduler']),source_ledger=sources['ledger'],source_scheduler=sources['scheduler'],**metadata)
    output=root/'snapshot-receipt-v01.json';descriptor=write(output,(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode())
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    print(json.dumps(dict(status='private_sampled_endpoints_copied',receipt=brief(descriptor))))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--role',choices=('opening','terminal'),required=True)
    parser.add_argument('--cell',choices=CELLS);parser.add_argument('--index',type=int,default=1)
    main(parser.parse_args())

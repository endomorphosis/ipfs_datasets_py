"""Prepare and restore-verify an opaque archive; never modify original results.

Only fixed, independently ownership-qualified released result subtrees are read.
This has no apply mode, native resource API, model import or checkpoint parser.
"""
from datetime import datetime,timezone
import gzip
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import stat
import sys
import tarfile
import time

F=Path(__file__).resolve().parent
RUN=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
INTAKE=F/'owned-released-results-storage-intake-v01.json'
INTAKE_PIN=dict(path=str(INTAKE),bytes=67366,sha256='520ab94ce21a4bfce3aea05b3678b3c8a7820ea3c3d456a3af3fdf8e8b789074')
GATE=F/'owned-results-archive-source-independent-review-v01.json'
STAGE=F/'owned-results-archive-staging-v01'
OUTPUT=F/'owned-results-archive-prepared-v01.json'
FINAL_ARCHIVE=RUN/'attempt-01/owned-released-results-20261014-v01.tar.gz'
FINAL_MANIFEST=RUN/'attempt-01/owned-released-results-20261014-v01.manifest.json'
EXCLUDED={'arbitrary-native-cache-20261011-02','retained-pointer-cache-20261011-03','retained-joint-readout-20261011-01'}
PROTECTED={'conditions-presence-20261014-conditions-presence-ce-01','conditions-balanced-20261014-conditions-balanced-ce-01'}
CHUNK=1048576
MAX_FILES=2048
MAX_BYTES=1100000000
MAX_MEMBER=268435456
MAX_ARCHIVE=1200000000
COUNTED_METADATA_BOUND=2000000


def require(value,message):
    if not value:raise ValueError(message)


def tick(deadline):require(time.monotonic()<=deadline,'bounded archival preparation deadline exceeded')


def physical(path,directory=False):
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path,'physical absolute path required')
    for part in (*reversed(path.parents),path):
        info=part.lstat();require(not stat.S_ISLNK(info.st_mode),'symlink ancestry refused')
        require(stat.S_ISDIR(info.st_mode) if part!=path or directory else stat.S_ISREG(info.st_mode),'ordinary physical path required')
    return path.lstat()


def identity(info):
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns,info.st_mode,info.st_uid,info.st_gid,info.st_nlink)


def opaque_pin(path,deadline=None):
    path=Path(path)
    require('private-runtime-snapshots' not in path.parts and 'private-root-identity-rebind-v01' not in path.parts
        and path.name not in ('disk-reservations.json','ipfs-datasets-resource-scheduler-1000.json','resources-start.json','resources-final.json'),
        'private global and own resource bodies prohibited')
    info=physical(path);require(info.st_nlink==1 and info.st_uid==os.getuid(),'exclusive owned regular file required')
    digest=hashlib.sha256();size=0
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        require(identity(os.fstat(stream.fileno()))==identity(info),'opened source identity differs')
        while True:
            if deadline is not None:tick(deadline)
            block=stream.read(CHUNK)
            if not block:break
            digest.update(block);size+=len(block)
        require(identity(os.fstat(stream.fileno()))==identity(info),'open source changed during hash')
    require(identity(physical(path))==identity(info) and size==info.st_size,'source changed during opaque hash')
    return dict(path=str(path),bytes=size,sha256=digest.hexdigest())


def read_public(path,expected=None):
    path=Path(path);require(not path.is_relative_to(RUN) or path.name in ('command.json','guardian-exit.json'),
        'only public runtime command/terminal metadata may be parsed under run root')
    require('private-runtime-snapshots' not in path.parts and 'private-root-identity-rebind-v01' not in path.parts
        and 'checkpoint' not in path.name and 'reference-packet' not in path.name,'private/model/reference JSON prohibited')
    pin=opaque_pin(path);require(pin['bytes']<=16*1024*1024 and (expected is None or pin==expected),'exact bounded public metadata required')
    def unique(items):
        result={}
        for key,value in items:require(key not in result,'duplicate public metadata key');result[key]=value
        return result
    value=json.loads(path.read_bytes(),object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite public JSON')))
    require(opaque_pin(path)==pin,'public metadata drift');return value,pin


def member_name(path):
    name=Path(path).relative_to(RUN).as_posix();parts=PurePosixPath(name).parts
    require(len(parts)>=3 and len(parts)<=10 and parts[0] not in PROTECTED|EXCLUDED and parts[1]=='results'
        and not PurePosixPath(name).is_absolute() and all(part not in ('','.','..') for part in parts),'closed relative result member required')
    return name


def collect_files(rows,deadline):
    entries=[];directories=[];total=0
    for row in rows:
        root=RUN/row['attempt']/'results';require(str(root)==row['result_directory'],'exact selected result root required')
        root_info=physical(root,True);pending=[root];local=[];nested=[]
        while pending:
            tick(deadline);directory=pending.pop();before=physical(directory,True)
            directories.append(dict(path=str(directory),device=before.st_dev,inode=before.st_ino,mode=stat.S_IMODE(before.st_mode)))
            with os.scandir(directory) as scan:
                for item in sorted(scan,key=lambda x:x.name):
                    path=Path(item.path);info=item.stat(follow_symlinks=False)
                    require(not stat.S_ISLNK(info.st_mode),'symlink result member refused')
                    if stat.S_ISDIR(info.st_mode):
                        require(len(path.relative_to(root).parts)<=8,'nested directory bound exceeded')
                        pending.append(path);nested.append(str(path.relative_to(root)))
                    else:
                        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid()
                            and info.st_size<=MAX_MEMBER,'ordinary unaliased bounded owned result file required')
                        captured=opaque_pin(path,deadline);require(identity(physical(path))==identity(info),'result metadata changed')
                        local.append(dict(**captured,member=member_name(path),mode=stat.S_IMODE(info.st_mode),uid=info.st_uid,gid=info.st_gid,
                            mtime_ns=info.st_mtime_ns,atime_ns=info.st_atime_ns,ctime_ns=info.st_ctime_ns,device=info.st_dev,inode=info.st_ino))
            require(identity(physical(directory,True))==identity(before),'selected directory changed during capture')
        require(len(local)==row['files'] and sum(x['bytes'] for x in local)==row['result_bytes']
            and sorted(nested)==sorted(row['nested_directories']),'exact fixed metadata-only intake inventory required')
        require(identity(physical(root,True))==identity(root_info),'result root identity changed')
        entries.extend(local);total+=sum(x['bytes'] for x in local)
        require(len(entries)<=MAX_FILES and total<=MAX_BYTES,'bounded selected file/byte inventory required')
    return sorted(entries,key=lambda x:x['member']),directories


def pack(entries,target,deadline):
    """A second opaque read verifies every original byte while tar receives it."""
    class Reader:
        def __init__(self,stream):self.stream=stream;self.sha=hashlib.sha256();self.size=0
        def read(self,n=-1):
            tick(deadline);require(0<=n<=CHUNK,'bounded tar read required');block=self.stream.read(n)
            self.sha.update(block);self.size+=len(block);return block
    with target.open('xb') as raw:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,compresslevel=9,mtime=0) as compressed:
            with tarfile.open(fileobj=compressed,mode='w|',format=tarfile.PAX_FORMAT) as archive:
                for entry in entries:
                    tick(deadline);path=Path(entry['path']);info=physical(path)
                    require((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)==
                        (entry['device'],entry['inode'],entry['bytes'],entry['mtime_ns'],entry['ctime_ns']),'captured original identity changed')
                    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
                    with os.fdopen(fd,'rb') as stream:
                        require(identity(os.fstat(stream.fileno()))==identity(info),'tar opened source identity differs')
                        reader=Reader(stream);member=tarfile.TarInfo(entry['member']);member.size=entry['bytes'];member.mode=entry['mode']
                        member.uid=entry['uid'];member.gid=entry['gid'];member.mtime=entry['mtime_ns']//1000000000
                        archive.addfile(member,reader)
                        require(reader.size==entry['bytes'] and reader.sha.hexdigest()==entry['sha256']
                            and identity(os.fstat(stream.fileno()))==identity(info),'tar source bytes/identity differ')
                    require(identity(physical(path))==identity(info),'original changed during compression')
                    require(raw.tell()<=MAX_ARCHIVE,'compressed archive bound exceeded')
        raw.flush();os.fsync(raw.fileno())
    target.chmod(0o444);return opaque_pin(target,deadline)


def verify_restore(entries,target,stage,deadline):
    expected={row['member']:row for row in entries};seen=set();restored=0
    with gzip.open(target,'rb') as compressed:
        with tarfile.open(fileobj=compressed,mode='r|') as archive:
            for member in archive:
                tick(deadline);require(member.name in expected and member.name not in seen and member.isreg()
                    and member_name(RUN/member.name)==member.name,'exact unique regular archive member required')
                row=expected[member.name];require(member.size==row['bytes'] and member.mode==row['mode']
                    and member.uid==row['uid'] and member.gid==row['gid'],'restoration metadata differs')
                probe=stage/'restore-probe.bin';sha=hashlib.sha256();count=0
                stream=archive.extractfile(member);require(stream is not None,'regular archive stream required')
                with probe.open('xb') as out:
                    while True:
                        tick(deadline);block=stream.read(CHUNK)
                        if not block:break
                        count+=len(block);require(count<=row['bytes'],'decompressed member size exceeded')
                        out.write(block);sha.update(block)
                    out.flush();os.fsync(out.fileno())
                stream.close();probe.chmod(row['mode'])
                require(count==row['bytes'] and sha.hexdigest()==row['sha256'] and opaque_pin(probe,deadline)['sha256']==row['sha256']
                    and stat.S_IMODE(probe.stat().st_mode)==row['mode'],'full restorative write/readback differs')
                probe.unlink() # ONLY a newly created, verified staging probe; never an original.
                seen.add(member.name);restored+=count
    require(seen==set(expected) and restored==sum(x['bytes'] for x in entries),'complete archive member/restoration set differs')
    return dict(member_count=len(seen),raw_bytes=restored,every_member_restored_fsynced_and_readback_byte_exact=True)


def main():
    require(sys.argv[1:]==[] and not any(os.path.lexists(p) for p in (STAGE,OUTPUT,FINAL_ARCHIVE,FINAL_MANIFEST)),
        'exclusive argument-free prepare-only action required')
    deadline=time.monotonic()+300;own=opaque_pin(Path(__file__).resolve());gate,gate_pin=read_public(GATE)
    require(gate['schema']=='actor-refinement-owned-results-archive-source-independent-review/v1'
        and gate['passed'] is True and gate['findings']==[] and gate['producer']==own and gate['intake']==INTAKE_PIN,
        'exact independently source-qualified and ownership-qualified producer required')
    for path,item in gate['artifacts'].items():require(opaque_pin(Path(path))==dict(path=path,**{k:item[k] for k in ('bytes','sha256')}),'source qualification artifact drift')
    intake,_=read_public(INTAKE,INTAKE_PIN);require(intake['metadata_only'] is True and intake['mutations']==0
        and set(intake['protected_attempts'])==PROTECTED,'exact protected metadata-only intake required')
    rows=[row for row in intake['proposed_attempts'] if row['attempt'] not in EXCLUDED]
    require(len(rows)==27 and sum(x['files'] for x in rows)==1162 and sum(x['result_bytes'] for x in rows)==934325529
        and set(gate['qualified_attempts'])=={row['attempt'] for row in rows},'exact separately ownership-qualified fixed selection required')
    evidence={}
    for row in rows:
        require(row['attempt'] not in PROTECTED and Path(row['result_directory'])==RUN/row['attempt']/'results','protected/outside selection refused')
        command,cp=read_public(Path(row['command']['path']),row['command']);terminal,tp=read_public(Path(row['terminal']['path']),row['terminal'])
        require(command==row['command_metadata'] and terminal['returncode']==terminal['child_returncode']==0
            and terminal['artifacts_durable'] is True and terminal['resource_reservation_released'] is True,
            'exact successful durable released command/terminal evidence required')
        args=command['argv'];qualified=gate['qualified_attempts'][row['attempt']]
        require(len(args)==6 and args[2]=='--plan' and args[4:] == ['--output',row['result_directory']]
            and command['cwd']==command['candidate_pythonpath'] and command['no_cuda'] is command['no_proof_workers'] is True
            and command['model_authority'] is False and qualified['command']==cp and qualified['terminal']==tp
            and qualified['plan']['path']==args[3] and qualified['runner']['path']==args[1]
            and Path(args[1]).parent==Path(args[3]).parent and Path(args[1]).parent.parent==F.parent,
            'exact owner-phase runner/plan/output command custody required')
        for key in ('plan','runner'):require(opaque_pin(Path(qualified[key]['path']))==qualified[key],'qualified owner source/plan drift')
        evidence[row['attempt']]=qualified
    entries,dirs=collect_files(rows,deadline)
    STAGE.mkdir(mode=0o700);archive=STAGE/'owned-released-results.tar.gz';archive_pin=pack(entries,archive,deadline)
    verified=verify_restore(entries,archive,STAGE,deadline);require(opaque_pin(archive,deadline)==archive_pin,'verified compressed archive changed')
    for row in entries:
        info=physical(Path(row['path']));require((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)==
            (row['device'],row['inode'],row['bytes'],row['mtime_ns'],row['ctime_ns']),'closing original identity fence differs')
    for path,item in gate['artifacts'].items():require(opaque_pin(Path(path))==dict(path=path,**{k:item[k] for k in ('bytes','sha256')}),'closing public source fence differs')
    raw_bytes=sum(x['bytes'] for x in entries);net_lower=raw_bytes-archive_pin['bytes']-COUNTED_METADATA_BOUND
    value=dict(schema='actor-refinement-owned-results-archive-prepared/v1',passed=True,findings=[],producer=own,source_qualification=gate_pin,
        intake=INTAKE_PIN,prepared_at_utc=datetime.now(timezone.utc).isoformat(),archive=archive_pin,final_counted_archive=str(FINAL_ARCHIVE),
        final_counted_manifest=str(FINAL_MANIFEST),originals=entries,preserved_directories=dirs,qualified_ownership=evidence,
        protected_attempts=sorted(PROTECTED),excluded_ambiguous_attempts=sorted(EXCLUDED),file_count=len(entries),raw_bytes=raw_bytes,
        verification=verified,counted_metadata_bound_bytes=COUNTED_METADATA_BOUND,actual_archive_bytes=archive_pin['bytes'],
        projected_net_apparent_savings_lower_bound_bytes=net_lower,target800M_met=net_lower>=800000000,
        source_archive_temporary_outside_counted_roots=True,final_archive_must_remain_inside_counted_root=True,
        originals_modified=False,original_moves=0,original_unlinks=0,new_claims=0,claim_mutations=0,cap_changed=False,
        native_capacity_PASS_claimed=False,training_authorized=False,model_calls=0,numerical_imports=0,checkpoint_JSON_parses=0,
        global_censuses=0,private_endpoint_body_reads=0,resource_API_calls=0,
        apply_requires_separate_actual_concrete_review=True,restoration_preserves_raw_bytes_mode_but_not_original_inode_ctime=True)
    raw=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode();require(len(raw)<=COUNTED_METADATA_BOUND,'counted restoration manifest bound exceeded')
    with OUTPUT.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    fd=os.open(STAGE,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    print(json.dumps(opaque_pin(OUTPUT),sort_keys=True))


if __name__=='__main__':main()

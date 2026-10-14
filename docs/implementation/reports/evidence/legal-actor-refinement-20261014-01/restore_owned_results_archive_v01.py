"""Verify an exact owned-results archive; optionally restore selected attempts to NEW staging.

Default verification writes nothing. Materialization never writes original counted
paths and requires a fresh direct child of this tool's owned phase directory.
File bytes/modes and declared directory modes are restored; original inode/ctime,
ownership and timestamp identities cannot be recreated. Native headroom approval
for any counted-original restoration is a separate workflow, absent from this tool.
"""
import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile
import time

F=Path(__file__).resolve().parent
RUN=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
COUNTED_ROOTS=(RUN.parent,Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/todo-queues'),
    Path('/home/barberb/lift_coding/external/ipfs_datasets/docs/implementation/reports/evidence'),Path('/tmp/pytest-of-barberb'))
PREPARER_SHA256='e24e09b8e8734d4feacb38d679154556cc0c9a7bacfdf5d917eb097077445a38'
PROTECTED={'conditions-presence-20261014-conditions-presence-ce-01','conditions-balanced-20261014-conditions-balanced-ce-01'}
EXCLUDED={'arbitrary-native-cache-20261011-02','retained-pointer-cache-20261011-03','retained-joint-readout-20261011-01'}
CHUNK=1048576
MAX_MANIFEST=2000000
MAX_FILES=2048
MAX_DIRS=4096
MAX_RAW=1100000000
MAX_MEMBER=268435456
MAX_ARCHIVE=1200000000
MAX_PAX=65536
MAX_SECONDS=300
SHA=re.compile(r'[0-9a-f]{64}\Z')
ENTRY_KEYS={'path','member','bytes','sha256','mode','uid','gid','mtime_ns','atime_ns','ctime_ns','device','inode'}
MANIFEST_KEYS={'actual_archive_bytes','apply_requires_separate_actual_concrete_review','archive','cap_changed','checkpoint_JSON_parses',
    'claim_mutations','counted_metadata_bound_bytes','excluded_ambiguous_attempts','file_count','final_archive_must_remain_inside_counted_root',
    'final_counted_archive','final_counted_manifest','findings','global_censuses','intake','model_calls','native_capacity_PASS_claimed',
    'new_claims','numerical_imports','original_moves','original_unlinks','originals','originals_modified','passed','prepared_at_utc',
    'preserved_directories','private_endpoint_body_reads','producer','projected_net_apparent_savings_lower_bound_bytes','protected_attempts',
    'qualified_ownership','raw_bytes','resource_API_calls','restoration_preserves_raw_bytes_mode_but_not_original_inode_ctime','schema',
    'source_archive_temporary_outside_counted_roots','source_qualification','target800M_met','training_authorized','verification'}
sys.dont_write_bytecode=True


def require(value,message):
    if not value:raise ValueError(message)


def tick(deadline):require(time.monotonic()<=deadline,'bounded restore deadline exceeded')


def physical(path,*,directory=False):
    p=Path(path);require(p.is_absolute() and p.resolve(strict=True)==p,'physical absolute path required')
    for part in (*reversed(p.parents),p):
        value=part.lstat();require(not stat.S_ISLNK(value.st_mode),'symlink ancestry refused')
        require(stat.S_ISDIR(value.st_mode) if part!=p or directory else stat.S_ISREG(value.st_mode),'ordinary physical path required')
    value=p.lstat();require(value.st_uid==os.getuid(),'owned path required')
    return value


def stamp(value):
    return (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns,value.st_mode,value.st_uid,value.st_gid,value.st_nlink)


def private(path):
    p=Path(path)
    return bool({'private-runtime-snapshots','private-root-identity-rebind-v01'}&set(p.parts)) or p.name in {
        'disk-reservations.json','ipfs-datasets-resource-scheduler-1000.json','resources-start.json','resources-final.json'}


def opaque_pin(path,maximum,deadline):
    path=Path(path);require(not private(path),'private/global resource bodies refused')
    before=physical(path);require(before.st_nlink==1 and 0<=before.st_size<=maximum,'bounded exclusive regular file required')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK);sha=hashlib.sha256();count=0
    with os.fdopen(fd,'rb') as source:
        require(stamp(os.fstat(source.fileno()))==stamp(before),'opened file identity differs')
        while True:
            tick(deadline);block=source.read(CHUNK)
            if not block:break
            count+=len(block);require(count<=maximum,'raw file exceeds byte bound');sha.update(block)
        require(stamp(os.fstat(source.fileno()))==stamp(before),'opened file changed during hash')
    require(stamp(physical(path))==stamp(before) and count==before.st_size,'physical file changed during hash')
    return dict(path=str(path),bytes=count,sha256=sha.hexdigest())


def descriptor(value):
    require(type(value) is dict and set(value)=={'path','bytes','sha256'} and type(value['path']) is str
        and Path(value['path']).is_absolute() and type(value['bytes']) is int and value['bytes']>0
        and type(value['sha256']) is str and SHA.fullmatch(value['sha256']),'full typed raw descriptor required')
    return value


def safe_member(name):
    require(type(name) is str and 1<=len(name.encode('utf-8'))<=4096 and '\\' not in name
        and all(ord(c)>=32 and ord(c)!=127 for c in name),'bounded ordinary member name required')
    parts=name.split('/')
    require(3<=len(parts)<=10 and all(p not in ('','.','..') for p in parts) and parts[1]=='results'
        and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,255}',parts[0]) and parts[0] not in PROTECTED|EXCLUDED
        and not PurePosixPath(name).is_absolute() and PurePosixPath(name).as_posix()==name,'safe relative selected result member required')
    return parts


def validate_manifest(value):
    require(type(value) is dict and set(value)==MANIFEST_KEYS and value['schema']=='actor-refinement-owned-results-archive-prepared/v1'
        and value['passed'] is True and value['findings']==[],'closed passed preparation manifest required')
    require(descriptor(value['producer'])['sha256']==PREPARER_SHA256 and value['producer']['bytes']==16909,
        'exact sealed preparer lineage required')
    for key in ('intake','source_qualification','archive'):descriptor(value[key])
    require(value['protected_attempts']==sorted(PROTECTED) and value['excluded_ambiguous_attempts']==sorted(EXCLUDED)
        and value['originals_modified'] is value['cap_changed'] is value['native_capacity_PASS_claimed'] is value['training_authorized'] is False,
        'protected originals and no authority expansion required')
    for key in ('checkpoint_JSON_parses','claim_mutations','global_censuses','model_calls','new_claims','numerical_imports','original_moves','original_unlinks','private_endpoint_body_reads','resource_API_calls'):
        require(type(value[key]) is int and value[key]==0,'no model/resource/original mutation authority required')
    require(value['apply_requires_separate_actual_concrete_review'] is value['restoration_preserves_raw_bytes_mode_but_not_original_inode_ctime'] is True
        and value['final_archive_must_remain_inside_counted_root'] is value['source_archive_temporary_outside_counted_roots'] is True,
        'restoration limitations and counted archive preservation required')
    require(type(value['originals']) is list and 1<=len(value['originals'])<=MAX_FILES
        and type(value['file_count']) is int and value['file_count']==len(value['originals']),'bounded exact member count required')
    entries={};attempts=set();total=0
    for row in value['originals']:
        require(type(row) is dict and set(row)==ENTRY_KEYS,'closed original member metadata required')
        parts=safe_member(row['member']);attempts.add(parts[0])
        require(row['member'] not in entries and row['path']==str(RUN/row['member']),'unique member and exact original coordinate required')
        require(type(row['bytes']) is int and 0<=row['bytes']<=MAX_MEMBER and type(row['sha256']) is str and SHA.fullmatch(row['sha256'])
            and type(row['mode']) is int and 0<=row['mode']<=0o777,'bounded bytes/SHA/plain permission bits required')
        require(all(type(row[k]) is int and row[k]>=0 for k in ('uid','gid','mtime_ns','atime_ns','ctime_ns','device','inode')),
            'typed nonnegative original metadata required')
        entries[row['member']]=row;total+=row['bytes'];require(total<=MAX_RAW,'expanded member byte bound exceeded')
    require(type(value['raw_bytes']) is int and value['raw_bytes']==total and type(value['actual_archive_bytes']) is int
        and 0<value['actual_archive_bytes']==value['archive']['bytes']<=MAX_ARCHIVE,'exact compressed/expanded inventory bytes required')
    require(type(value['qualified_ownership']) is dict and set(value['qualified_ownership'])==attempts,'exact qualified attempt map required')
    directories={}
    require(type(value['preserved_directories']) is list and len(value['preserved_directories'])<=MAX_DIRS,'bounded preserved directories required')
    for row in value['preserved_directories']:
        require(type(row) is dict and set(row)=={'path','device','inode','mode'} and type(row['path']) is str,'closed directory metadata required')
        path=Path(row['path']);require(path.is_absolute() and path.is_relative_to(RUN),'original directory coordinate required')
        name=path.relative_to(RUN).as_posix();safe_member(name+'/_directory_placeholder_')
        require(name not in directories and name.split('/')[0] in attempts and type(row['mode']) is int and 0<=row['mode']<=0o777
            and all(type(row[k]) is int and row[k]>=0 for k in ('device','inode')),'unique typed selected directory required')
        directories[name]=row
    for name in entries:
        parent=PurePosixPath(name).parent
        while len(parent.parts)>=2:
            require(parent.as_posix() in directories,'every original member directory must be described');parent=parent.parent
    return entries,directories,attempts


def read_manifest(path,expected_bytes,expected_sha256,deadline):
    require(type(expected_bytes) is int and 0<expected_bytes<=MAX_MANIFEST and type(expected_sha256) is str
        and SHA.fullmatch(expected_sha256),'explicit bounded trusted manifest identity required')
    path=Path(path);require('checkpoint' not in path.name.lower() and 'reference-packet' not in path.name.lower(),
        'checkpoint/reference JSON parsing refused')
    expected=dict(path=str(path),bytes=expected_bytes,sha256=expected_sha256)
    require(opaque_pin(path,MAX_MANIFEST,deadline)==expected,'manifest raw identity differs')
    with path.open('rb') as source:raw=source.read(MAX_MANIFEST+1)
    require(len(raw)==expected_bytes and hashlib.sha256(raw).hexdigest()==expected_sha256,'consumed manifest identity differs')
    def unique(pairs):
        result={}
        for key,item in pairs:require(key not in result,'duplicate manifest JSON key');result[key]=item
        return result
    def finite(text):
        number=float(text);require(math.isfinite(number),'nonfinite manifest scalar refused');return number
    value=json.loads(raw,object_pairs_hook=unique,parse_float=finite,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite manifest JSON refused')))
    require(opaque_pin(path,MAX_MANIFEST,deadline)==expected,'manifest changed during parse')
    return value,expected


class ExpandedReader:
    def __init__(self,stream,maximum,deadline):self.stream,self.maximum,self.deadline,self.count=stream,maximum,deadline,0
    def read(self,count):
        require(type(count) is int and 0<=count<=CHUNK,'bounded positive archive stream read required');tick(self.deadline)
        block=self.stream.read(count);self.count+=len(block);require(self.count<=self.maximum,'expanded archive overhead bound exceeded');return block
    def exact(self,count):
        result=self.read(count);require(len(result)==count,'truncated tar member/header/padding');return result


class StrictTarInfo(tarfile.TarInfo):
    @classmethod
    def fromtarfile(cls,archive):
        # ignore_zeros traverses concatenated/trailing blocks, but stdlib would
        # also silently skip invalid headers. Keep standard parsing and make
        # malformed nonzero/truncated headers a hard refusal.
        try:return super().fromtarfile(archive)
        except (tarfile.InvalidHeaderError,tarfile.TruncatedHeaderError) as error:
            raise tarfile.ReadError('malformed archive header refused') from error


def walk_archive(archive_path,archive_pin,entries,deadline,open_output=None):
    """Use stdlib tar/PAX decoding; extract only regular streams, never filesystem paths."""
    require(opaque_pin(archive_path,MAX_ARCHIVE,deadline)==archive_pin,'archive compressed identity differs')
    before=physical(archive_path);seen=set();raw_count=0
    fd=os.open(archive_path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as source:
        require(stamp(os.fstat(source.fileno()))==stamp(before),'archive opened identity differs')
        with gzip.GzipFile(fileobj=source,mode='rb') as compressed:
            bounded=ExpandedReader(compressed,sum(r['bytes'] for r in entries.values())+len(entries)*(MAX_PAX+2048)+10240,deadline)
            with tarfile.open(fileobj=bounded,mode='r|',ignore_zeros=True,tarinfo=StrictTarInfo) as archive:
                for member in archive:
                    tick(deadline);safe_member(member.name)
                    require(member.type in (tarfile.REGTYPE,tarfile.AREGTYPE) and member.isreg() and not member.issparse()
                        and not member.linkname,'only ordinary nonsparse regular archive members permitted')
                    require(set(member.pax_headers)<= {'path'} and all(len(v.encode('utf-8'))<=4096 for v in member.pax_headers.values()),
                        'only bounded stdlib PAX path metadata permitted')
                    name=member.name;require(name in entries and name not in seen,'unknown or duplicate archive member refused')
                    row=entries[name];require(member.size==row['bytes'] and member.mode==row['mode'] and member.uid==row['uid'] and member.gid==row['gid']
                        and member.mtime==row['mtime_ns']//1000000000,'member bytes/mode/ownership/mtime metadata differs')
                    stream=archive.extractfile(member);require(stream is not None,'regular member stream required')
                    output=None if open_output is None else open_output(name,row)
                    sha=hashlib.sha256();count=0
                    try:
                        while True:
                            tick(deadline);block=stream.read(CHUNK)
                            if not block:break
                            count+=len(block);require(count<=row['bytes'],'member exceeds declared byte bound');sha.update(block)
                            if output is not None:require(output.write(block)==len(block),'short staging write refused')
                        require(count==row['bytes'] and sha.hexdigest()==row['sha256'],'member byte count/raw SHA differs')
                        if output is not None:
                            output.flush();os.fsync(output.fileno())
                    finally:
                        stream.close()
                        if output is not None:output.close()
                    seen.add(name);raw_count+=count
            # Consume any remaining decompressed bytes so gzip CRC/trailer and the
            # expansion bound are checked even if tarfile has buffered its EOF.
            while True:
                tail=bounded.read(CHUNK)
                if not tail:break
                require(not tail.strip(b'\0'),'nonzero data after tar stream refused')
        require(stamp(os.fstat(source.fileno()))==stamp(before),'open archive changed during traversal')
    require(seen==set(entries) and raw_count==sum(row['bytes'] for row in entries.values()),'complete exact archive member set required')
    require(opaque_pin(archive_path,MAX_ARCHIVE,deadline)==archive_pin,'archive changed during traversal')
    return dict(member_count=len(seen),raw_bytes=raw_count)


def directory_fd(stage_fd,parts,create=False):
    fd=os.dup(stage_fd)
    try:
        for part in parts:
            if create:
                try:os.mkdir(part,0o700,dir_fd=fd)
                except FileExistsError:pass
            following=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            info=os.fstat(following);require(stat.S_ISDIR(info.st_mode) and info.st_uid==os.getuid(),'fresh owned staging directory required')
            os.close(fd);fd=following
        return fd
    except BaseException:
        os.close(fd);raise


def restore_archive(manifest_path,*,manifest_bytes,manifest_sha256,archive_path,materialize=False,selected_attempts=(),stage=None):
    deadline=time.monotonic()+MAX_SECONDS
    require(type(materialize) is bool and type(selected_attempts) in (list,tuple),'explicit restore mode required')
    manifest,manifest_pin=read_manifest(manifest_path,manifest_bytes,manifest_sha256,deadline)
    entries,directories,attempts=validate_manifest(manifest)
    archive_path=Path(archive_path);archive_pin=dict(path=str(archive_path),bytes=manifest['archive']['bytes'],sha256=manifest['archive']['sha256'])
    require(type(selected_attempts) in (list,tuple) and all(type(x) is str for x in selected_attempts)
        and len(selected_attempts)==len(set(selected_attempts)),'unique explicit selected attempts required')
    require(materialize and selected_attempts and set(selected_attempts)<=attempts and stage is not None
        or not materialize and not selected_attempts and stage is None,'materialization requires explicit selected attempts plus fresh stage; verify-only has no output')
    stage_path=None
    if materialize:
        stage_path=Path(stage);require(stage_path.is_absolute() and stage_path.parent==F and not os.path.lexists(stage_path)
            and not any(stage_path.is_relative_to(root) for root in COUNTED_ROOTS),'fresh direct owned phase staging outside all counted roots required')
        physical(stage_path.parent,directory=True)
    verified=walk_archive(archive_path,archive_pin,entries,deadline)
    written=[]
    if materialize:
        # Entire archive has passed before the only mkdir or payload write.
        os.mkdir(stage_path,0o700);stage_fd=os.open(stage_path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            selected=set(selected_attempts)
            chosen_dirs={name:row for name,row in directories.items() if name.split('/')[0] in selected}
            for name in sorted(chosen_dirs,key=lambda x:(len(x.split('/')),x)):
                fd=directory_fd(stage_fd,name.split('/'),create=True);os.close(fd)
            def open_output(name,row):
                if name.split('/')[0] not in selected:return None
                parts=name.split('/');parent=directory_fd(stage_fd,parts[:-1])
                try:fd=os.open(parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
                finally:os.close(parent)
                written.append(name);return os.fdopen(fd,'wb')
            require(walk_archive(archive_path,archive_pin,entries,deadline,open_output)==verified,'second archive verification differs')
            require(set(written)=={name for name in entries if name.split('/')[0] in selected},'selected materialized set differs')
            for name in written:
                row=entries[name];actual=opaque_pin(stage_path/name,MAX_MEMBER,deadline)
                require(actual['bytes']==row['bytes'] and actual['sha256']==row['sha256'],'staged byte readback differs')
                # Read back while the fresh file is private0600, then restore even
                # unreadable original modes through an already-open descriptor.
                fd=os.open(stage_path/name,os.O_RDONLY|os.O_NOFOLLOW)
                try:os.fchmod(fd,row['mode']);os.fsync(fd)
                finally:os.close(fd)
                require(stat.S_IMODE(physical(stage_path/name).st_mode)==row['mode'],'staged file mode differs')
            for name,row in sorted(chosen_dirs.items(),key=lambda x:(-len(x[0].split('/')),x[0])):
                fd=directory_fd(stage_fd,name.split('/'))
                try:os.fsync(fd);os.fchmod(fd,row['mode']);os.fsync(fd)
                finally:os.close(fd)
            os.fsync(stage_fd)
        finally:os.close(stage_fd)
    require(opaque_pin(manifest_path,MAX_MANIFEST,deadline)==manifest_pin,'closing manifest drift')
    require(opaque_pin(archive_path,MAX_ARCHIVE,deadline)==archive_pin,'closing archive drift')
    return dict(schema='actor-refinement-owned-results-restore-verification/v1',passed=True,findings=[],manifest=manifest_pin,archive=archive_pin,
        archive_origin_descriptor=manifest['archive'],archive_relocated=str(archive_path)!=manifest['archive']['path'],verified=verified,
        mode='materialize-selected' if materialize else 'verify-only',stage=None if stage_path is None else str(stage_path),
        selected_attempts=list(selected_attempts),materialized_file_count=len(written),materialized_raw_bytes=sum(entries[n]['bytes'] for n in written),
        file_bytes_and_modes_readback_verified=materialize,declared_directory_modes_restored=materialize,original_inode_ctime_restored=False,
        original_ownership_or_timestamps_restored=False,original_paths_opened=False,original_paths_written=False,counted_original_restoration_implemented=False,
        archive_and_manifest_unchanged=True,new_claims=0,claim_mutations=0,cap_changed=False,model_calls=0,numerical_imports=0,checkpoint_JSON_parses=0,
        resource_API_calls=0,network_calls=0,partial_failure_cleanup_performed=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path);parser.add_argument('--manifest-bytes',required=True,type=int)
    parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--archive',required=True,type=Path)
    parser.add_argument('--materialize-selected',action='store_true');parser.add_argument('--attempt',action='append',default=[])
    parser.add_argument('--stage',type=Path)
    args=parser.parse_args()
    print(json.dumps(restore_archive(args.manifest,manifest_bytes=args.manifest_bytes,manifest_sha256=args.manifest_sha256,archive_path=args.archive,
        materialize=args.materialize_selected,selected_attempts=args.attempt,stage=args.stage),sort_keys=True))

if __name__=='__main__':main()

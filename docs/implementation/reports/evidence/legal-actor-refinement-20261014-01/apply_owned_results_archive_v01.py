"""Replace exactly approved cold result files with a durable counted archive.

Requires exact successful preparation, immutable HF byte readback, independent
source qualification and concrete approval. No claim/cap/resource API exists.
"""
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time

F=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
HELPER=F/'prepare_owned_results_archive_v01.py'
HELPER_PIN=dict(path=str(HELPER),bytes=16909,sha256='e24e09b8e8734d4feacb38d679154556cc0c9a7bacfdf5d917eb097077445a38')
_raw=HELPER.read_bytes()
if len(_raw)!=HELPER_PIN['bytes'] or hashlib.sha256(_raw).hexdigest()!=HELPER_PIN['sha256']:
    raise ValueError('exact qualified opaque archive helper required')
_spec=importlib.util.spec_from_file_location('qualified_archive_apply_helpers',HELPER)
a=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(a)
PREPARED=F/'owned-results-archive-prepared-v01.json'
PREPARED_PIN=dict(path=str(PREPARED),bytes=801434,sha256='5be5dfc877425e0fcc94ce00a2a5416b07d638133f3eeeaee791e326a18e39b3')
SOURCE_GATE=F/'owned-results-archive-apply-source-independent-review-v01.json'
REVIEW=F/'owned-results-archive-apply-independent-review-v01.json'
HF=F/'owned-results-archive-hf-publication-v01.json'
OUTPUT=F/'owned-results-archive-applied-v01.json'
JOURNAL=a.RUN/'attempt-01/owned-released-results-20261014-v01.journal.jsonl'
QUARANTINE=a.RUN/'attempt-01/owned-results-archive-quarantine-v01'
MINIMUM_SAVINGS=750000000


def same_raw(actual,expected):
    return all(actual[key]==expected[key] for key in ('bytes','sha256'))


def sync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def publish_copy(source,target,expected,deadline):
    """Exclusive publication; a partial copy never permits original removal."""
    a.require(a.opaque_pin(source,deadline)==expected,'exact copy source required')
    a.physical(target.parent,True);sha=hashlib.sha256();count=0
    fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as incoming,target.open('xb') as outgoing:
        while True:
            a.tick(deadline);block=incoming.read(a.CHUNK)
            if not block:break
            count+=len(block);a.require(count<=expected['bytes'],'publication source grew')
            outgoing.write(block);sha.update(block)
        outgoing.flush();os.fsync(outgoing.fileno())
    target.chmod(0o444);sync_directory(target.parent)
    actual=a.opaque_pin(target,deadline)
    a.require(count==expected['bytes'] and sha.hexdigest()==expected['sha256'] and same_raw(actual,expected)
        and a.opaque_pin(source,deadline)==expected,'durable counted publication bytes differ')
    return actual


def validate_prepared(value):
    a.require(value['schema']=='actor-refinement-owned-results-archive-prepared/v1' and value['passed'] is True
        and value['findings']==[] and value['file_count']==1162 and value['raw_bytes']==934325529
        and value['archive']['bytes']==149504694 and value['archive']['sha256']=='76f81402e57a5782abd7fb76b91b62e8af20886239187dd8603425eb4caee47f'
        and value['final_counted_archive']==str(a.FINAL_ARCHIVE) and value['final_counted_manifest']==str(a.FINAL_MANIFEST)
        and value['counted_metadata_bound_bytes']==2000000
        and value['projected_net_apparent_savings_lower_bound_bytes']==782820835>=MINIMUM_SAVINGS
        and value['target800M_met'] is False and value['originals_modified'] is False
        and value['verification']['every_member_restored_fsynced_and_readback_byte_exact'] is True,
        'exact measured prepared proof required;800M target remains false')
    entries=value['originals'];a.require(len(entries)==1162 and len({row['path'] for row in entries})==len(entries)
        and len({row['member'] for row in entries})==len(entries)
        and sum(row['bytes'] for row in entries)==934325529,'exact unique complete approved raw member set required')
    allowed=set(value['qualified_ownership'])
    for row in entries:
        path=Path(row['path']);member=a.member_name(path)
        a.require(member==row['member'] and path.relative_to(a.RUN).parts[0] in allowed
            and type(row['mode']) is int and row['uid']==os.getuid() and type(row['bytes']) is int and row['bytes']>=0,
            'approved exclusive owned member path/metadata required')
    return entries


def validate_original(row,deadline):
    path=Path(row['path']);info=a.physical(path)
    a.require((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns,stat.S_IMODE(info.st_mode),info.st_uid,info.st_gid,info.st_nlink)==
        (row['device'],row['inode'],row['bytes'],row['mtime_ns'],row['ctime_ns'],row['mode'],row['uid'],row['gid'],1),
        'original member identity drift; refuse replacement')
    actual=a.opaque_pin(path,deadline);a.require(same_raw(actual,row),'original member raw bytes differ')
    return info


def validate_hf(value,prepared):
    a.require(value['schema']=='actor-refinement-owned-results-archive-hf-publication/v1' and value['passed'] is True
        and value['findings']==[] and value['archive']==prepared['archive'] and value['manifest']==PREPARED_PIN
        and value['repo']=='Publicus/legal-ir-autoencoder' and type(value['revision']) is str and len(value['revision'])==40
        and all(c in '0123456789abcdef' for c in value['revision'])
        and value['all_prior_file_identities_preserved'] is True and value['default_promotion'] is False,
        'actual immutable additive archive+manifest publication proof required')
    for label,expected in (('downloaded_archive',prepared['archive']),('downloaded_manifest',PREPARED_PIN)):
        actual=a.opaque_pin(Path(value[label]['path']))
        a.require(actual==value[label] and same_raw(actual,expected),'actual immutable HF raw readback differs')


def quarantine_verified(row,index,event,deadline):
    """Retain any raced pathname intact; return only a verified private member."""
    validate_original(row,deadline)
    source=Path(row['path']);captured=QUARANTINE/(str(index).zfill(4)+'.opaque')
    a.require(not os.path.lexists(captured),'fresh private quarantine member required')
    event(dict(event='intent',index=index,member=row['member'],bytes=row['bytes'],sha256=row['sha256']))
    os.rename(source,captured);sync_directory(source.parent);sync_directory(QUARANTINE)
    info=a.physical(captured)
    a.require((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,stat.S_IMODE(info.st_mode),info.st_uid,info.st_gid,info.st_nlink)==
        (row['device'],row['inode'],row['bytes'],row['mtime_ns'],row['mode'],row['uid'],row['gid'],1)
        and same_raw(a.opaque_pin(captured,deadline),row),'quarantined member differs; retained intact for review')
    event(dict(event='quarantined_verified',index=index));return captured


def main():
    a.require(sys.argv[1:]==[] and not any(os.path.lexists(path) for path in
        (OUTPUT,JOURNAL,QUARANTINE,a.FINAL_ARCHIVE,a.FINAL_MANIFEST)),'exclusive one-shot archival replacement required; no automatic retry')
    deadline=time.monotonic()+300;own=a.opaque_pin(Path(__file__).resolve())
    gate,gate_pin=a.read_public(SOURCE_GATE)
    a.require(gate['schema']=='actor-refinement-owned-results-archive-apply-source-independent-review/v1'
        and gate['passed'] is True and gate['findings']==[] and gate['producer']==own and gate['prepared']==PREPARED_PIN,
        'exact independent apply source qualification required')
    for path,item in gate['artifacts'].items():a.require(a.opaque_pin(Path(path))==dict(path=path,**{k:item[k] for k in ('bytes','sha256')}),'qualified apply source drift')
    prepared,_=a.read_public(PREPARED,PREPARED_PIN);entries=validate_prepared(prepared)
    hf,hf_pin=a.read_public(HF);validate_hf(hf,prepared)
    review,review_pin=a.read_public(REVIEW)
    a.require(review['schema']=='actor-refinement-owned-results-archive-apply-independent-review/v1'
        and review['passed'] is True and review['findings']==[] and review['producer']==own
        and review['source_qualification']==gate_pin and review['prepared']==PREPARED_PIN and review['hf_publication']==hf_pin
        and review['minimum_conservative_savings_bytes']==MINIMUM_SAVINGS
        and review['authorize_exact_archival_replacement'] is True
        and review['claim_mutation_authorized'] is review['cap_change_authorized'] is False,
        'actual independently reviewed exact replacement and HF publication required')
    for row in entries:validate_original(row,deadline)
    for row in prepared['preserved_directories']:
        info=a.physical(Path(row['path']),True)
        a.require((info.st_dev,info.st_ino,stat.S_IMODE(info.st_mode))==(row['device'],row['inode'],row['mode']),
            'original result directory identity changed')
    # Both complete local copies are durable inside the counted root before ANY raw move/removal.
    archive=publish_copy(Path(prepared['archive']['path']),a.FINAL_ARCHIVE,prepared['archive'],deadline)
    manifest=publish_copy(PREPARED,a.FINAL_MANIFEST,PREPARED_PIN,deadline)
    QUARANTINE.mkdir(mode=0o700);sync_directory(QUARANTINE.parent)
    removed=0;raw_removed=0
    with JOURNAL.open('xb') as journal:
        def event(value):
            raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
            a.require(journal.tell()+len(raw)+manifest['bytes']<=prepared['counted_metadata_bound_bytes'],
                'counted manifest+journal exceeds predeclared2M bound')
            journal.write(raw);journal.flush();os.fsync(journal.fileno())
        event(dict(event='durable_counted_archive_and_manifest',archive=archive,manifest=manifest,prepared=PREPARED_PIN,
            hf_publication=hf_pin,concrete_review=review_pin))
        sync_directory(JOURNAL.parent)
        for index,row in enumerate(entries):
            a.tick(deadline)
            # Rename into a new private directory FIRST: any pathname race is
            # retained for review instead of unlinking an unverified replacement.
            captured=quarantine_verified(row,index,event,deadline)
            captured.unlink();sync_directory(QUARANTINE)
            removed+=1;raw_removed+=row['bytes'];event(dict(event='removed',index=index))
        event(dict(event='complete',removed_count=removed,raw_removed_bytes=raw_removed))
    JOURNAL.chmod(0o444);sync_directory(JOURNAL.parent)
    journal_pin=a.opaque_pin(JOURNAL,deadline)
    a.require(removed==1162 and raw_removed==934325529 and all(not os.path.lexists(row['path']) for row in entries)
        and all(not os.path.lexists(QUARANTINE/(str(i).zfill(4)+'.opaque')) for i in range(len(entries))),
        'exact complete member replacement required')
    a.require(same_raw(a.opaque_pin(a.FINAL_ARCHIVE,deadline),prepared['archive'])
        and same_raw(a.opaque_pin(a.FINAL_MANIFEST,deadline),PREPARED_PIN),'closing durable recovery archive/manifest differs')
    for row in prepared['preserved_directories']:
        info=a.physical(Path(row['path']),True);a.require((info.st_dev,info.st_ino)==(row['device'],row['inode']),'original directories must remain')
    net=raw_removed-archive['bytes']-manifest['bytes']-journal_pin['bytes']
    a.require(net>=MINIMUM_SAVINGS and manifest['bytes']+journal_pin['bytes']<=2000000,'measured counted savings below concrete threshold')
    for path,item in gate['artifacts'].items():a.require(a.opaque_pin(Path(path))==dict(path=path,**{k:item[k] for k in ('bytes','sha256')}),'closing qualified public source drift')
    a.require(a.opaque_pin(REVIEW)==review_pin and a.opaque_pin(HF)==hf_pin and a.opaque_pin(PREPARED)==PREPARED_PIN,
        'closing concrete review/HF/prepared evidence drift')
    value=dict(schema='actor-refinement-owned-results-archive-applied/v1',passed=True,findings=[],applied_at_utc=datetime.now(timezone.utc).isoformat(),
        producer=own,source_qualification=gate_pin,prepared=PREPARED_PIN,hf_publication=hf_pin,concrete_review=review_pin,
        counted_archive=archive,counted_restoration_manifest=manifest,counted_progress_journal=journal_pin,
        removed_original_file_count=removed,raw_removed_bytes=raw_removed,measured_net_apparent_savings_bytes=net,
        minimum_conservative_savings_bytes=MINIMUM_SAVINGS,target800M_met=prepared['target800M_met'],
        counted_metadata_bound_bytes=2000000,counted_metadata_actual_bytes=manifest['bytes']+journal_pin['bytes'],
        all_original_directories_preserved=True,all_runtime_command_terminal_metadata_preserved=True,
        protected_attempts=sorted(a.PROTECTED),all_removed_bytes_recoverable_from_durable_counted_archive_and_HF=True,
        temporary_private_quarantine=str(QUARANTINE),quarantine_empty=True,
        claims_modified=0,new_claims=0,cap_changed=False,private_endpoint_reads=0,resource_API_calls=0,actual_tree_censuses=0,
        model_calls=0,numerical_imports=0,checkpoint_JSON_parses=0,training_authorized=False,
        fresh_qualified_post_apply_native_baseline_required=True,continuous_original_raw_path_availability_claimed=False)
    with OUTPUT.open('x') as stream:json.dump(value,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    OUTPUT.chmod(0o444);print(json.dumps(a.opaque_pin(OUTPUT),sort_keys=True))


if __name__=='__main__':main()

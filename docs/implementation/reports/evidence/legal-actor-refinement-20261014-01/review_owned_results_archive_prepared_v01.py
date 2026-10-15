"""Independent opaque archive-member / public-manifest review; no original writes."""
from pathlib import Path,PurePosixPath
from collections import Counter
import gzip
import hashlib
import json
import os
import stat
import tarfile
import time
F=Path(__file__).resolve().parent
RUN=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
OUT=F/'owned-results-archive-prepared-independent-review-v01.json'
EXPECTED_MANIFEST=dict(path=str(F/'owned-results-archive-prepared-v01.json'),bytes=801434,sha256='5be5dfc877425e0fcc94ce00a2a5416b07d638133f3eeeaee791e326a18e39b3')
EXPECTED_ARCHIVE=dict(path=str(F/'owned-results-archive-staging-v01/owned-released-results.tar.gz'),bytes=149504694,sha256='76f81402e57a5782abd7fb76b91b62e8af20886239187dd8603425eb4caee47f')
PROTECTED={'conditions-presence-20261014-conditions-presence-ce-01','conditions-balanced-20261014-conditions-balanced-ce-01'}
EXCLUDED={'arbitrary-native-cache-20261011-02','retained-joint-readout-20261011-01','retained-pointer-cache-20261011-03'}
ARTIFACTS={};DEADLINE=time.monotonic()+90

def require(value,message):
    if not value:raise ValueError(message)

def tick():require(time.monotonic()<=DEADLINE,'bounded review deadline exceeded')

def physical(path):
    p=Path(path);require(p.is_absolute() and p.resolve(strict=True)==p,'physical absolute file required')
    for a in (*reversed(p.parents),p):require(not a.is_symlink(),'symlink ancestry refused')
    require(p.is_file(),'ordinary file required');return p

def pin(path,expected=None):
    tick();p=physical(path);a=p.stat();h=hashlib.sha256();n=0
    require(a.st_nlink==1 and a.st_size<=1200000000,'bounded unaliased file required')
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):tick();h.update(block);n+=len(block)
    b=p.stat();identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode)
    require(identity(a)==identity(b) and n==a.st_size,'hash input drift')
    v=dict(path=str(p),bytes=n,sha256=h.hexdigest());require(expected is None or all(v[k]==expected[k] for k in ('bytes','sha256')),'raw pin mismatch')
    ARTIFACTS[str(p)]=v;return v

def read(path,expected=None):
    p=Path(path);require('checkpoint' not in p.name and 'reference-packet' not in p.name and 'private-runtime-snapshots' not in p.parts,'model/gold/private parse denied')
    v=pin(p,expected);require(v['bytes']<=4*1024*1024,'bounded public metadata required')
    raw=p.read_bytes();require(len(raw)==v['bytes'] and hashlib.sha256(raw).hexdigest()==v['sha256'],'public read drift')
    return json.loads(raw)

def main():
    require(not os.path.lexists(OUT),'exclusive new review output required')
    own=pin(Path(__file__).resolve());m=read(EXPECTED_MANIFEST['path'],EXPECTED_MANIFEST);a=pin(EXPECTED_ARCHIVE['path'],EXPECTED_ARCHIVE)
    gate=read(m['source_qualification']['path'],m['source_qualification']);intake=read(m['intake']['path'],m['intake'])
    require(m['schema']=='actor-refinement-owned-results-archive-prepared/v1' and m['passed'] is True and m['findings']==[]
        and m['archive']==a and m['producer']==gate['producer'] and gate['passed'] is True and gate['findings']==[]
        and gate['schema']=='actor-refinement-owned-results-archive-source-independent-review/v1','exact source-qualified prepared join required')
    require(m['originals_modified'] is False and m['original_moves']==m['original_unlinks']==m['new_claims']==m['claim_mutations']==0
        and m['cap_changed'] is m['native_capacity_PASS_claimed'] is m['training_authorized'] is False,'prepare-only conservation required')
    rows=m['originals'];require(m['file_count']==len(rows)==1162 and m['raw_bytes']==sum(r['bytes'] for r in rows)==934325529,'exact1162/934325529 member inventory required')
    selected={r['attempt']:r for r in intake['proposed_attempts'] if r['attempt'] not in EXCLUDED}
    require(len(selected)==27 and set(m['qualified_ownership'])==set(gate['qualified_attempts'])==set(selected)
        and m['qualified_ownership']==gate['qualified_attempts'] and set(m['protected_attempts'])==PROTECTED
        and set(m['excluded_ambiguous_attempts'])==EXCLUDED,'exact27 ownership/protection joins required')
    expected={};counts=Counter();sizes=Counter()
    for row in rows:
        p=Path(row['path']);name=row['member'];parts=PurePosixPath(name).parts
        require(len(parts)>=3 and len(parts)<=10 and all(v not in ('','.','..') for v in parts)
            and not PurePosixPath(name).is_absolute() and parts[0] in selected and parts[1]=='results'
            and p==RUN/name and name not in expected and parts[0] not in PROTECTED|EXCLUDED,'closed selected member path required')
        info=physical(p).stat();require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns,stat.S_IMODE(info.st_mode),info.st_uid,info.st_gid)
            ==tuple(row[k] for k in ('device','inode','bytes','mtime_ns','ctime_ns','mode','uid','gid')),'current original identity differs from prepared record')
        expected[name]=row;counts[parts[0]]+=1;sizes[parts[0]]+=row['bytes']
    require(all(counts[k]==r['files'] and sizes[k]==r['result_bytes'] for k,r in selected.items()),'all27 exact intake per-attempt counts/bytes required')
    seen=set();total=0
    with gzip.open(a['path'],'rb') as compressed:
        with tarfile.open(fileobj=compressed,mode='r|') as archive:
            for member in archive:
                tick();require(member.name in expected and member.name not in seen and member.isreg(),'closed unique regular tar member required')
                r=expected[member.name];require((member.size,member.mode,member.uid,member.gid)==tuple(r[k] for k in ('bytes','mode','uid','gid')),'archive member metadata differs')
                stream=archive.extractfile(member);require(stream is not None,'opaque regular member required');h=hashlib.sha256();n=0
                for block in iter(lambda:stream.read(1048576),b''):
                    tick();n+=len(block);require(n<=r['bytes'],'decompression member bound exceeded');h.update(block)
                stream.close();require(n==r['bytes'] and h.hexdigest()==r['sha256'],'independent opaque member raw hash differs')
                seen.add(member.name);total+=n
    require(seen==set(expected) and total==934325529,'complete independent1162-member raw rehash required')
    require(m['verification']==dict(every_member_restored_fsynced_and_readback_byte_exact=True,member_count=1162,raw_bytes=934325529),'source-qualified actual physical restore receipt differs')
    require(m['counted_metadata_bound_bytes']==2000000 and m['actual_archive_bytes']==a['bytes']
        and m['projected_net_apparent_savings_lower_bound_bytes']==934325529-a['bytes']-2000000==782820835
        and m['target800M_met'] is False,'actual compression/savings arithmetic differs')
    protected={}
    for phase,filename,schema in [('legal-head-repair-20261014-01','conditions-presence-output-freeze-v01.json','conditions-presence-output-freeze/v1'),
            ('legal-balanced-execution-20261014-01','conditions-balanced-output-freeze-v01.json','conditions-balanced-output-freeze/v1')]:
        freeze=read(F.parent/phase/filename);require(freeze['schema']==schema and freeze['all_outputs_frozen'] is True and len(freeze['results'])==62,'existing protected freeze differs')
        for path,v in freeze['results'].items():require(path not in {r['path'] for r in rows},'protected source selected for archival');pin(path,v)
        protected[phase]=dict(exact_raw_outputs_rehashed=62,member_bytes=sum(v['bytes'] for v in freeze['results'].values()))
    contract=read(F/'evaluation-contract-v01.json');parent=contract['source_parent']
    require(parent['path'] not in {r['path'] for r in rows} and parent['sha256']=='34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd','protected exact N11 donor must remain outside archive')
    for path in (F/'prepare_actor_refinement_v01.py',F/'run_actor_refinement_v01.py',F/'analyze_actor_refinement_v01.py',F/'review_actor_refinement_result_recount_v01.py'):
        pin(path)
    for d in m['preserved_directories']:
        path=Path(d['path']);info=path.lstat();require(path.resolve(strict=True)==path and stat.S_ISDIR(info.st_mode)
            and (info.st_dev,info.st_ino,stat.S_IMODE(info.st_mode))==(d['device'],d['inode'],d['mode']),'preserved original directory identity differs')
    pin(EXPECTED_ARCHIVE['path'],a);pin(EXPECTED_MANIFEST['path'],EXPECTED_MANIFEST)
    value=dict(schema='actor-refinement-owned-results-archive-prepared-independent-review/v1',passed=True,findings=[],observer=own,
        prepared_manifest=EXPECTED_MANIFEST,archive=a,source_qualification=m['source_qualification'],intake=m['intake'],
        member_count=1162,raw_bytes=934325529,selected_attempt_count=27,independent_all_member_SHA256_rehash=True,
        actual_archive_bytes=a['bytes'],counted_metadata_allowance_bytes=2000000,conservative_net_apparent_savings_bytes=782820835,
        original800M_target_met=False,root_revised750M_minimum_met=True,actual_source_qualified_physical_restore_all_members=True,
        independent_physical_restoration_rerun=False,current_original_identities_match_prepared_manifest=True,
        protected_frozen_outputs=protected,protected_N11_donor_unchanged=True,protected_N11_N14_excluded=True,
        named_future_input_boundary='F15 source preparer builds fresh N11 donor/capture closure; it does not inherit old artifacts wholesale. All N11/N14 outputs remain exact; source exports/reference artifact files lie outside selected resultdirs.',
        future_actual_training_plan_exists_and_audited=False,
        required_before_eviction=['Publish exact archive+prepared manifest to HF; independently verify immutable full-byte readback and bind actual receipt.',
        'Source-qualify both explicit apply and standalone restore tools; actual concrete apply review/root authorization must join this actual manifest/HF readback.',
        'Recheck current originals/complete hash set, archive durable final counted copy, all protected/live input paths and counted metadata/journal bound before approved member removal.',
        'Run fresh qualified copied resource observation/native accounting after any authorized apply; this review is no capacity PASS or model authority.'],
        limits=['Historical HF coverage is partial for8 trigger/action checkpoints and all temporal03 members; exact newly prepared complete local archive proof is independent of those older receipts.',
        'Raw bytes and mode recoverability is proven by qualified producer; original inode/ctime continuity cannot be preserved by restoration.'],
        raw_checkpoint_JSON_parses=0,raw_score_JSON_parses=0,private_body_reads=0,network_calls=0,resource_API_calls=0,full_root_censuses=0,
        original_moves=0,original_unlinks=0,claims_modified=0,cap_changed=False,model_calls=0,numerical_imports=0,eviction_authorized=False,artifacts=ARTIFACTS)
    with OUT.open('x') as out:json.dump(value,out,sort_keys=True,indent=2,allow_nan=False);out.write('\n')
    OUT.chmod(0o444);print(json.dumps(pin(OUT),sort_keys=True))

if __name__=='__main__':main()

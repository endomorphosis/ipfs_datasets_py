"""One source-qualified, read-only observation of the interrupted F16 Hub release.

Five exact metadata queries and two forced immutable .gitattributes downloads.
The checkpoint is never opened: its published LFS SHA256/size are compared to
its already reviewed opaque preparation descriptor. Other created files are
hashed as opaque bytes, never parsed as predictions or references. No repair,
commit, upload, resource call, model call or automatic application retry exists.
"""
import hashlib
import os
from pathlib import Path
import types

F=Path(__file__).resolve().parent
REPO='Publicus/legal-ir-autoencoder'
PREFIX='releases/20261014-actor-context-ranking-v1'
HELPER='archive_actor_context_ranking_hf_v01.py'
HELPER_BYTES=30925
HELPER_SHA256='e6c383eed91d6cee2405ce401fb0ab6692b714e0a2d3e99c09dbf4abe9f6a1ee'
BASELINE='1622817fd804ff5333fce7dc8d04433e4acef2e4'
FIRST='59b54a18f8c685a2097746c88ae2176c43e7169f'
SECOND='88876ef24d5566f6dc5d6c640b3d6cbcfe20907b'
PARTIAL='246e7793db1399341387fabbb740781ea23251c8'
CHECKPOINT=PREFIX+'/cells/actor-context-ranking-hinge/results/cell-checkpoint.json'
CHECKPOINT_BYTES=15143581
CHECKPOINT_SHA256='5bb6425888b4cffe5c9875b5d262b2895c8c02e4745acd231f33c4a79908ff84'
GATE=F/'hf-partial-observer-source-independent-review-v01.json'
OUTPUT=F/'hf-publication-partial-observation-v01.json'
ATTRS=F/'hf-partial-attrs-readback-v01'
LABELS=('baseline','chunk01','chunk02','chunk03','live')
REQUESTED=(BASELINE,FIRST,SECOND,PARTIAL,'main')


def require(condition,message):
    if not condition:raise ValueError(message)


def helper():
    path=F/HELPER
    require(path.is_file() and not path.is_symlink() and path.resolve()==path,'Exact physical retained helper source required')
    raw=path.read_bytes()
    require(len(raw)==HELPER_BYTES and hashlib.sha256(raw).hexdigest()==HELPER_SHA256,'Original publisher source must remain exact')
    module=types.ModuleType('_F16_readonly_Hub_helper');module.__file__=str(path);module.__package__=''
    exec(compile(raw,str(path),'exec',dont_inherit=True),module.__dict__)
    require(module.F==F and module.REPO==REPO and module.PREFIX==PREFIX,'Retained helper phase differs')
    return module


def qualify_local(before,receipt,spec,created,verified,groups):
    require(before['revision']==BASELINE and len(before['files'])==5646,'Exact interrupted baseline required')
    require(receipt['schema']=='actor-context-ranking-Hub-preparation/v1' and receipt['repository']==REPO
        and receipt['release_prefix']==PREFIX and receipt['expected_parent_revision']==BASELINE
        and receipt['payload_files']==len(receipt['entries'])==201 and receipt['payload_bytes']==81437344
        and receipt['algorithm_source_count']==len(receipt['algorithm_sources'])==41
        and receipt['default_promotion'] is False and receipt['additions_only'] is True,
        'The unchanged201-file reviewed preparation is required')
    require(spec['schema']=='actor-context-ranking-Hub-release-spec/v1' and spec['repository']==REPO
        and spec['release_prefix']==PREFIX and spec['baseline']==receipt['baseline']
        and {r['destination']:{k:r['source'][k] for k in ('bytes','sha256')} for r in spec['files']}
            =={n:{k:d[k] for k in ('bytes','sha256')} for n,d in receipt['entries'].items()}
        and len(spec['files'])==201,'Exact unchanged spec/preparation mapping required')
    require(type(groups) is list and [len(g) for g in groups]==[18,1,1,15,18,37,48,48,15]
        and len({n for g in groups for n in g})==201 and groups[2]==[CHECKPOINT],
        'Exact original nine chunks with checkpoint singleton third required')
    for i,(parent,revision) in enumerate(((BASELINE,FIRST),(FIRST,SECOND),(SECOND,PARTIAL))):
        require(created[i]==dict(parent_revision=parent,revision=revision,names=groups[i]),'Original created chunk custody differs')
        if i<2:require(verified[i]==dict(parent_revision=parent,revision=revision,new_files=len(groups[i]),
            old_identities_exact=True,new_byte_identities_exact=True),'Original first two verified receipts differ')
    checkpoint=receipt['entries'][CHECKPOINT]
    require(checkpoint['bytes']==CHECKPOINT_BYTES and checkpoint['sha256']==CHECKPOINT_SHA256,'Original opaque checkpoint descriptor differs')
    return groups[0]+groups[1]+groups[2]


def payload_matches(identity,descriptor,git_blob_id):
    if type(identity) is not dict or identity.get('size')!=descriptor['bytes']:return False
    lfs=identity.get('lfs')
    if lfs is not None:
        return lfs.get('size')==descriptor['bytes'] and lfs.get('sha256')==descriptor['sha256']
    return git_blob_id is not None and identity.get('blob_id')==git_blob_id


def compare_snapshot(original,current,names,descriptors,git_blobs):
    require(type(original) is dict and type(current) is dict and type(names) is list,'Typed identity maps and created names required')
    missing_old=sorted(set(original)-set(current))
    changed_old={n:dict(before=d,after=current[n]) for n,d in original.items() if n in current and current[n]!=d}
    missing_new=sorted(set(names)-set(current))
    unexpected=sorted(set(current)-set(original)-set(names))
    new_matches={n:n in current and payload_matches(current[n],descriptors[n],git_blobs.get(n)) for n in names}
    return dict(old_identity_differences=changed_old,missing_old_paths=missing_old,missing_created_paths=missing_new,
        unexpected_paths=unexpected,new_payload_byte_identities=new_matches,
        all_original_identities_exact=not missing_old and not changed_old,
        all_original_non_attributes_identities_exact=not missing_old and set(changed_old)<= {'.gitattributes'},
        all_created_payload_byte_identities_exact=all(new_matches.values()),
        exact_path_inventory=not missing_old and not missing_new and not unexpected)


def classify_attributes(baseline_raw,partial_raw):
    line=(CHECKPOINT+' filter=lfs diff=lfs merge=lfs -text\n').encode()
    old=baseline_raw.splitlines(keepends=True);new=partial_raw.splitlines(keepends=True)
    from collections import Counter
    before,after=Counter(old),Counter(new)
    return dict(baseline_bytes=len(baseline_raw),partial_bytes=len(partial_raw),byte_delta=len(partial_raw)-len(baseline_raw),
        baseline_sha256=hashlib.sha256(baseline_raw).hexdigest(),partial_sha256=hashlib.sha256(partial_raw).hexdigest(),
        exact_checkpoint_LFS_rule_append=partial_raw==baseline_raw+line,expected_append_bytes=len(line),
        added_line_count=sum((after-before).values()),removed_line_count=sum((before-after).values()),
        attributes_equal=baseline_raw==partial_raw,interpretation_scope='public attributes byte difference only; no corrective authority')


def main():
    import sys
    require(sys.argv[1:]==[],'Argument-free finite observation required')
    h=helper();own=h.pin(Path(__file__).resolve());gate=h.read(GATE)
    h.clean(gate,'actor-context-ranking-Hub-partial-observer-source-independent-review/v1')
    require(gate['observer']==own and gate['helper']==h.pin(F/HELPER),'Exact source observer/helper gate required')
    require(type(gate['artifacts']) is dict and all('checkpoint' not in Path(p).name and not h.private(p)
        for p in gate['artifacts']),'Source gate may bind only public metadata/source and noncheckpoint opaque bytes')
    allowed=h.approved(gate)
    require(allowed.get(own['path'])==h.brief(own),'Observer source must be independently admitted')
    def bound(name):
        path=F/name;descriptor=h.pin(path)
        require(allowed.get(str(path))==h.brief(descriptor),'Every local input must be source-gate admitted before parsing')
        return h.read(path,descriptor)
    before=h.qualify_hf_baseline(bound('hf-before-file-identities-v01.json'))
    receipt=bound('hf-preparation-receipt-v01.json');spec=bound('hf-release-spec-v01.json')
    publication=bound('hf-publication-independent-review-v01.json');h.clean(publication,'actor-context-ranking-Hub-publication-independent-review/v1')
    require(publication['expected_parent_revision']==BASELINE and publication['payload_files']==201
        and publication['payload_bytes']==81437344,'Original concrete publication gate differs')
    created=[bound('hf-chunk-%02d-created-v01.json'%i) for i in (1,2,3)]
    verified=[bound('hf-chunk-%02d-verified-v01.json'%i) for i in (1,2)]
    groups=h.chunks(receipt['entries']);names=qualify_local(before,receipt,spec,created,verified,groups)
    require(receipt['source_archive']==h.pin(F/HELPER) and receipt['source_spec']==h.pin(F/'hf-release-spec-v01.json')
        and receipt['upload_root']==str(F/'hf-upload-v01'),'Exact original source/spec/payload custody required')
    require(not os.path.lexists(F/'hf-chunk-03-verified-v01.json')
        and not any(os.path.lexists(F/('hf-chunk-%02d-created-v01.json'%i)) for i in range(4,10)),
        'Only first two verified and third created receipts may exist')
    snapshots={label:F/('hf-'+label+'-immutable-observed-v01.json') for label in LABELS}
    require(not any(os.path.lexists(p) for p in [OUTPUT,ATTRS,*snapshots.values()]),'Exclusive new observation destinations required')
    # Read only19 already-created noncheckpoint files as opaque bytes; no JSON parsing.
    git_blobs={}
    for name in names:
        descriptor=receipt['entries'][name]
        require(descriptor['path']==str(F/'hf-upload-v01'/name),'Exact original created payload path required')
        if name==CHECKPOINT:continue
        path=Path(descriptor['path'])
        require(allowed.get(str(path))==h.brief(descriptor) and h.pin(path)==descriptor,'Created noncheckpoint bytes must be independently admitted')
        raw=path.read_bytes()
        require(len(raw)==descriptor['bytes'] and hashlib.sha256(raw).hexdigest()==descriptor['sha256'] and h.pin(path)==descriptor,'Created opaque file drift')
        git_blobs[name]=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    require(len(git_blobs)==19,'Exactly19 noncheckpoint opaque byte hashes required')
    h.fence(allowed)
    require(os.environ.get('HF_ENDPOINT','https://huggingface.co')=='https://huggingface.co','Exact public Hub endpoint required')
    import huggingface_hub
    require(huggingface_hub.__version__=='0.36.2','Reviewed SDK0.36.2 required')
    from huggingface_hub import HfApi,hf_hub_download
    api=HfApi(endpoint='https://huggingface.co');records={};maps={}
    for label,requested in zip(LABELS,REQUESTED):
        info=api.model_info(REPO,revision=requested,files_metadata=True);files=h.identities(info)
        require(requested=='main' or info.sha==requested,'Immutable metadata response revision differs')
        value=dict(schema='actor-context-ranking-Hub-immutable-file-snapshot/v1',repository=REPO,
            requested_revision=requested,returned_revision=info.sha,metadata_queries=1,files=files)
        records[label]=h.write_json(snapshots[label],value);maps[label]=value
    require(maps['baseline']['files']==before['files'],'Immutable baseline differs from the original observed baseline')
    ATTRS.mkdir(mode=0o700);downloads={};raw_attrs={}
    for label,rev in (('baseline',BASELINE),('chunk03',PARTIAL)):
        identity=maps[label]['files'].get('.gitattributes')
        require(type(identity) is dict and identity['lfs'] is None and 0<identity['size']<=65536,'Bounded ordinary immutable attributes required')
        directory=ATTRS/label;directory.mkdir(mode=0o700)
        path=Path(hf_hub_download(repo_id=REPO,repo_type='model',filename='.gitattributes',revision=rev,
            local_dir=str(directory),force_download=True))
        require(path==directory/'.gitattributes' and path.resolve()==path and not path.is_symlink(),'Fresh exact physical attributes target required')
        raw=path.read_bytes();require(h.byte_identity(identity,raw),'Immutable attributes raw Git identity differs')
        path.chmod(0o444);descriptor=h.pin(path);raw_attrs[label]=raw
        downloads[label]=dict(**descriptor,revision=rev,remote_identity=identity,immutable_download_byte_identity_matches=True,force_download=True)
    comparisons={label:compare_snapshot(before['files'],maps[label]['files'],names[:count],receipt['entries'],git_blobs)
        for label,count in (('chunk01',18),('chunk02',19),('chunk03',20),('live',20))}
    partial=comparisons['chunk03'];live_matches=maps['live']['returned_revision']==PARTIAL and maps['live']['files']==maps['chunk03']['files']
    observation=dict(schema='actor-context-ranking-Hub-partial-observation/v1',observation_completed=True,
        observer=own,source_qualification=h.pin(GATE),repository=REPO,release_prefix=PREFIX,
        original_baseline=h.pin(F/'hf-before-file-identities-v01.json'),preparation=h.pin(F/'hf-preparation-receipt-v01.json'),
        original_publication_review=h.pin(F/'hf-publication-independent-review-v01.json'),source_spec=h.pin(F/'hf-release-spec-v01.json'),
        baseline_revision=BASELINE,first_verified_revision=FIRST,second_verified_revision=SECOND,created_but_unverified_revision=PARTIAL,
        last_verified_chunk=2,created_but_unverified_chunk=3,metadata_queries=5,immutable_attributes_downloads=2,
        immutable_snapshots=records,comparisons=comparisons,attributes_readback=downloads,
        attributes_difference=classify_attributes(raw_attrs['baseline'],raw_attrs['chunk03']),
        live_exactly_matches_known_partial=live_matches,original_file_count=5646,created_payload_files=20,
        created_checkpoint_verified_by_LFS_size_and_SHA256_only=True,checkpoint_opened=False,
        noncheckpoint_created_opaque_files_hashed=19,remaining_original_chunk_indices=[4,5,6,7,8,9],
        strict_publication_invariants_passed=partial['all_original_identities_exact'] and partial['all_created_payload_byte_identities_exact'] and partial['exact_path_inventory'],
        remote_mutations=0,payload_downloads=0,payload_uploads=0,automatic_retry_performed=False,corrective_action_performed=False,
        final_publication_complete=False,default_promotion=False,model_calls=0,checkpoint_JSON_parses=0,private_body_reads=0,resource_API_calls=0)
    h.fence(allowed);h.write_json(OUTPUT,observation)
    print(h.pin(OUTPUT))

if __name__=='__main__':main()

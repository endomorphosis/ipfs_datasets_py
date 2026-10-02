"""Resumable model-dependent pages in existing source and model artifact owners.

The existing registry operation log owns executed page-run artifacts. A cursor
only references a replayed contiguous prefix; no competing SQL head or model
promotion exists. Source/AST/graph pages remain independently authoritative for
their structural scope. Learned rows remain unverified candidates.
"""
from __future__ import annotations
import hashlib
from importlib.metadata import version as package_version
import json
import math
from pathlib import Path
import site
import sys
import time

from . import codebase_repository_shards as shards
from . import codebase_prior_384 as prior
from . import codebase_model_generation as generations
from .codebase_resources import acquire_codebase_resources
from .codebase_scan_policy_live import verify_policy_current
from .content import cid_for_structured
from ...duckdb_control.contracts import canonical_json_bytes
from ...duckdb_control.codebase_catalog import CodebaseHead
from ...optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLane,LeaseCancelledError,LeaseTimeoutError

SCHEMA='codebase-resident-inference@1'
REQUEST_SCHEMA='codebase-resident-inference-worker-request@1'
WORKER_SCHEMA='codebase-resident-inference-worker-result@1'
CURSOR_SCHEMA='codebase-resident-inference-cursor@1'
MAX_BYTES=32*1024**2
FALSE={k:v for k,v in shards.FALSE.items() if k!='inference_executed'}
require=shards.require
raw=canonical_json_bytes
sha=lambda value:hashlib.sha256(value).hexdigest()


def pins():
    from ..formalization.autoencoder import source_embeddings_384,source_program_runtime_384
    from ..backends import codebase_process
    return dict(owner=sha(Path(__file__).read_bytes()),worker=sha(Path(__file__).with_name('codebase_resident_inference_worker.py').read_bytes()),
        source_shards=shards.pins(),prior384=prior.pins(),
        embedding_cache=sha(Path(source_embeddings_384.__file__).read_bytes()),
        source_decoder=sha(Path(source_program_runtime_384.__file__).read_bytes()),
        process=sha(Path(codebase_process.__file__).read_bytes()))


def _context(index,registry,*,root_cid,version_id,embedding_snapshot,mode,batch_size,device):
    require(device=='cpu','CUDA inference is unqualified for this profile; explicit CPU opt-out required')
    require(mode in ('resident','cold_per_page'),'explicit model residency mode required')
    require(type(batch_size) is int and 1<=batch_size<=16,'bounded exact batch size required')
    from ...optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as embedding
    prior.source384._owners(index,registry)
    source=shards.load_repository_shards(index,root_cid)
    version,saved=prior.load(index,registry,version_id)[0]
    snapshot,assets=embedding._snapshot_assets(embedding_snapshot)
    checkpoint=saved['checkpoint']
    context=dict(schema=SCHEMA,producer=pins(),source_root_cid=root_cid,source_head=source['source_head'],
        policy_receipt_cid=source['policy_receipt_cid'],model_version_id=version_id,model_artifact=version['artifact'],
        checkpoint_sha256=sha(raw(checkpoint)),embedding_snapshot=str(snapshot),embedding_assets=assets,
        mode=mode,batch_size=batch_size,device=device,
        runtime_versions={name:package_version(name) for name in ('torch','numpy','transformers','sentence-transformers','tokenizers')},
        python=sys.version,model_authority='existing_prior384_registry_version',
        source_authority='existing_complete_source_policy_owner',inference_authority='unverified_source_conditioned_candidates')
    require(len(raw(context))<=256*1024,'bounded inference context required')
    return context,source,checkpoint


def _inputs(index,source,start,count):
    require(type(start) is int and type(count) is int and 0<=start<len(source['pages']) and 1<=count<=16
            and start+count<=len(source['pages']),'bounded exact contiguous page run required')
    pages=[];inventory=[]
    for ordinal in range(start,start+count):
        cid=source['pages'][ordinal];page=shards._read(index,cid,source['profile']['max_page_bytes']);rows=[]
        for row in page['rows']:
            inventory.append(row)
            if row['inference_disposition']!='pending_source_conditioned_inference':continue
            body=index.artifacts.get_bytes(row['source_cid'])
            require(len(body)==row['bytes'] and 0<len(body)<=65536,'bounded exact complete inference source required')
            rows.append(dict(ordinal=row['ordinal'],path=row['path'],source_cid=row['source_cid'],
                source_sha256=sha(body),source_text=body.decode('utf-8')))
        pages.append(dict(page_ordinal=ordinal,page_cid=cid,rows=rows))
    return pages,inventory


def _validate_output(value,key,pages):
    require(type(value) is dict and value.get('schema')==WORKER_SCHEMA and value.get('key')==key
        and value.get('producer')==pins() and value.get('device')=='cpu' and value.get('inputs_truncated') is False
        and value.get('targets_used_for_inference') is False and all(value.get(k) is False for k in FALSE),
        'native resident output context or authority differs')
    observed=value.get('pages')
    require(type(observed) is list and len(observed)==len(pages),'native inference page coverage differs')
    from ..formalization.autoencoder.source_program_runtime_384 import FALSE as decoder_false
    for actual,expected in zip(observed,pages):
        require(actual['page_ordinal']==expected['page_ordinal'] and actual['page_cid']==expected['page_cid'],
                'native inference page belongs to another captured source shard')
        inputs={r['ordinal']:r for r in expected['rows']};rows=actual['rows']
        require(type(rows) is list and [r['ordinal'] for r in rows]==sorted(inputs),'native inference omitted or duplicated source rows')
        features={sha(raw(f)):f for f in actual['features']}
        for feature in features.values():
            require(set(feature)=={'source_sha256','embedding','embedding_sha256','assets_sha256'}
                and feature['embedding_sha256']==sha(raw(feature['embedding']))
                and feature['assets_sha256']==sha(raw(key['embedding_assets']))
                and type(feature['embedding']) is list and len(feature['embedding'])==384
                and all(type(v) in (int,float) and math.isfinite(v) for v in feature['embedding']),
                'exact native 384D feature microbatch required')
        for row in rows:
            expected_row=inputs[row['ordinal']]
            require(all(row[k]==expected_row[k] for k in ('path','source_cid','source_sha256')),'decoded source binding differs')
            status=row['status'];candidate=row['candidate']
            if status=='decoded_unverified_candidate':
                require(type(candidate) is dict and candidate['id']==str(row['ordinal'])
                    and candidate['source_sha256']==row['source_sha256'] and all(candidate[k] is False for k in decoder_false),
                    'decoder candidate acquired authority or changed source')
                require(row['feature_sha256'] in features and features[row['feature_sha256']]['source_sha256']==row['source_sha256'],
                        'decoded feature reference differs')
            else:
                require(candidate is None and status in ('deferred_source_character_limit','deferred_gte_token_limit'),
                        'unknown source inference disposition')
                require(len(expected_row['source_text'])>32768 if status=='deferred_source_character_limit'
                        else type(row.get('tokens')) is int and row['tokens']>512,'deferred source limit differs')
    require(len(raw(value))<=MAX_BYTES,'native resident output exceeds bound')
    return value


def _worker(payload,lease,signal,timeout,memory_mb):
    from . import codebase_resident_inference_worker as worker
    from ..backends.codebase_process import BoundedToolRunner,ToolRunLimits,run_bounded_stdin_tool
    roots=list(dict.fromkeys([str(Path(__file__).resolve().parents[3]),*site.getsitepackages(),site.getusersitepackages()]))
    runner=BoundedToolRunner(base_environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8',
        'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1',
        'NUMEXPR_NUM_THREADS':'1','TOKENIZERS_PARALLELISM':'false','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
    wire=raw(payload);require(len(wire)<=MAX_BYTES,'resident worker input exceeds bound');deadline=time.monotonic()+timeout
    with lease.acquire_child(lane=ResourceLane.ORCHESTRATION,cpu_slots=1,memory_mb=memory_mb,child_process_slots=1,
            timeout=timeout,cancel_event=signal,request_id='codebase-resident-inference') as child:
        remaining=deadline-time.monotonic();require(remaining>0,'resident worker admission consumed deadline')
        limits=ToolRunLimits(timeout_seconds=remaining,resident_memory_bytes=memory_mb*1024**2,
            max_input_bytes=MAX_BYTES,max_output_bytes=MAX_BYTES,max_workspace_bytes=2*MAX_BYTES)
        result=run_bounded_stdin_tool([sys.executable,'-I','-B',str(Path(worker.__file__).resolve()),json.dumps(roots)],
            wire,runner=runner,limits=limits,cancellation=child.combined_cancellation_signal(signal))
    require(result.returncode==0 and result.workspace_cleaned and not any((result.timed_out,result.cancelled,
        result.unavailable,result.output_truncated,result.resource_exhausted,result.error)),
        'bounded resident worker failed: '+str(result.termination_reason)+': '+result.stderr[-2048:])
    return json.loads(result.stdout),dict(elapsed_ms=result.elapsed_ms,input_sha256=sha(wire),output_sha256=sha(result.stdout.encode()),
        memory_mb=memory_mb,device='cpu',workspace_cleaned=result.workspace_cleaned,returncode=result.returncode,
        memory_enforcement='sampled_process_tree_RSS_may_overshoot',provider_calls=0,
        command=list(result.command),parent_lease_id=lease.lease_id,child_lease_id=child.lease_id)


def _load_run(index,registry,artifact,context,source,checkpoint):
    registry.verify_artifact(artifact);path=registry.artifact_path(artifact)
    require(path.stat().st_size<=MAX_BYTES,'bounded immutable resident run required')
    value=json.loads(path.read_bytes())
    require(set(value)=={'schema','key','worker_output','worker_receipt','feature_artifacts','inventory','authority'}
        and value['schema']==SCHEMA and value['authority']==FALSE,'closed immutable resident run required')
    key=value['key'];require({k:v for k,v in key.items() if k not in ('start_page','page_count','source_input_sha256')}==context,
                            'resident run belongs to another source/model context')
    pages,inventory=_inputs(index,source,key['start_page'],key['page_count'])
    require(key['source_input_sha256']==sha(raw(pages)) and value['inventory']==inventory,'complete native page input population differs')
    _validate_output(value['worker_output'],key,pages)
    receipt=value['worker_receipt']
    payload=dict(schema=REQUEST_SCHEMA,producer=pins(),key=key,checkpoint=checkpoint,pages=pages)
    require(receipt['input_sha256']==sha(raw(payload)) and receipt['output_sha256']==sha(raw(value['worker_output']))
        and receipt['device']=='cpu' and receipt['returncode']==0 and receipt['workspace_cleaned'] is True
        and receipt['provider_calls']==0 and receipt['child_lease_id'],'exact native resident process receipt differs')
    expected_features=[f for page in value['worker_output']['pages'] for f in page['features']]
    require(len(expected_features)==len(value['feature_artifacts']),'native feature artifact coverage differs')
    for feature,ref in zip(expected_features,value['feature_artifacts']):
        registry.verify_artifact(ref)
        require(registry.artifact_path(ref).read_bytes()==raw(feature),'exact existing feature microbatch bytes differ')
    operation='resident-inference:'+sha(raw(key))
    receipt=registry.resolve_operation(operation,'IndexResidentInference',dict(key=key,artifact=artifact))
    require(receipt is not None and receipt['artifact']==artifact,'native resident execution operation is missing')
    return value


def load_resident_cursor(index,registry,cursor_cid,*,root_cid,version_id,embedding_snapshot,mode='resident',batch_size=16,device='cpu'):
    context,source,checkpoint=_context(index,registry,root_cid=root_cid,version_id=version_id,
        embedding_snapshot=embedding_snapshot,mode=mode,batch_size=batch_size,device=device)
    value=shards._read(index,cursor_cid)
    require(set(value)=={'schema','context','runs','next_page','authority'} and value['schema']==CURSOR_SCHEMA
            and value['context']==context and value['authority']==FALSE,'closed exact model-dependent cursor required')
    require(type(value['runs']) is list and len(value['runs'])<=256,'bounded inference run history required')
    position=0;records=[]
    for artifact in value['runs']:
        record=_load_run(index,registry,artifact,context,source,checkpoint)
        require(record['key']['start_page']==position,'inference cursor omits, duplicates or reorders a page run')
        position+=record['key']['page_count'];records.append(record)
    require(type(value['next_page']) is int and value['next_page']==position<=len(source['pages']),
            'inference progress does not reconstruct from executed owner records')
    return value,records


def run_resident_inference_pages(index,repository,*,expected_head,root_cid,registry,version_id,embedding_snapshot,
        cursor_cid=None,max_pages=4,mode='resident',batch_size=16,device='cpu',
        scheduler=None,parent_lease=None,cancel_event=None,timeout_seconds=180,memory_mb=4096):
    require(device=='cpu','CUDA inference is unqualified for this profile; explicit CPU opt-out required')
    require(type(expected_head) is CodebaseHead and type(max_pages) is int and 1<=max_pages<=16,'bounded exact source/page request required')
    prior.source384._limits(timeout_seconds,memory_mb,'resident-inference');deadline=time.monotonic()+timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler,parent_lease=parent_lease,cancel_event=cancel_event,
            timeout_seconds=timeout_seconds,memory_mb=memory_mb) as lease:
        signal=lease.combined_cancellation_signal(cancel_event)
        def remaining():
            if signal.is_set():raise LeaseCancelledError('resident inference cancelled')
            duration=deadline-time.monotonic()
            if duration<=0:raise LeaseTimeoutError('resident inference deadline expired')
            return duration
        context,source,checkpoint=_context(index,registry,root_cid=root_cid,version_id=version_id,
            embedding_snapshot=embedding_snapshot,mode=mode,batch_size=batch_size,device=device)
        require(source['source_head']==expected_head.to_dict(),'resident source root differs from current requested head')
        def observe():verify_policy_current(index,repository,expected_head=expected_head,receipt_cid=source['policy_receipt_cid'],
            parent_lease=lease,cancel_event=signal,timeout_seconds=remaining(),memory_mb=memory_mb)
        observe()
        cursor=dict(schema=CURSOR_SCHEMA,context=context,runs=[],next_page=0,authority=FALSE)
        if cursor_cid is not None:
            cursor,_=load_resident_cursor(index,registry,cursor_cid,root_cid=root_cid,version_id=version_id,
                embedding_snapshot=embedding_snapshot,mode=mode,batch_size=batch_size,device=device)
        start=cursor['next_page'];count=min(max_pages,len(source['pages'])-start);executed=False
        if count:
            pages,inventory=_inputs(index,source,start,count)
            key=dict(**context,start_page=start,page_count=count,source_input_sha256=sha(raw(pages)))
            operation='resident-inference:'+sha(raw(key))
            with registry._transaction() as cx:
                stored=cx.execute('SELECT receipt FROM autoencoder_control.operations WHERE operation_id=?',[operation]).fetchone()
            if stored is not None:
                artifact=json.loads(stored[0])['artifact'];_load_run(index,registry,artifact,context,source,checkpoint)
            else:
                payload=dict(schema=REQUEST_SCHEMA,producer=pins(),key=key,checkpoint=checkpoint,pages=pages)
                output,receipt=_worker(payload,lease,signal,remaining(),memory_mb)
                _validate_output(output,key,pages);observe();remaining()
                fresh,_,_=_context(index,registry,root_cid=root_cid,version_id=version_id,
                    embedding_snapshot=embedding_snapshot,mode=mode,batch_size=batch_size,device=device)
                require(fresh==context,'resident source/model/producer context changed')
                features=[generations._stage(registry,f) for p in output['pages'] for f in p['features']]
                value=dict(schema=SCHEMA,key=key,worker_output=output,worker_receipt=receipt,
                    feature_artifacts=features,inventory=inventory,authority=FALSE)
                require(len(raw(value))<=MAX_BYTES,'resident projection exceeds byte bound')
                artifact=generations._stage(registry,value)
                registry._mutate(operation,'IndexResidentInference',dict(key=key,artifact=artifact),lambda cx:dict(artifact=artifact))
                executed=True
            cursor={**cursor,'runs':[*cursor['runs'],artifact],'next_page':start+count}
        observe();remaining()
        result_cid=index.artifacts.put(cursor)
        verified,records=load_resident_cursor(index,registry,result_cid,root_cid=root_cid,version_id=version_id,
            embedding_snapshot=embedding_snapshot,mode=mode,batch_size=batch_size,device=device)
        return dict(cursor_cid=result_cid,next_page=verified['next_page'],total_pages=len(source['pages']),
            inventory_complete=verified['next_page']==len(source['pages']),native_worker_executed=executed,
            inference_executed=executed and any(p['decoded_rows'] for p in records[-1]['worker_output']['pages']) if records else False,
            model_version_id=version_id,source_root_cid=root_cid,**FALSE)


__all__=['run_resident_inference_pages','load_resident_cursor']

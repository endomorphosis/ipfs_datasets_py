"""Versioned ordered parent-centered head adaptation on exact source cohorts.

This separate numerical lineage inherits the full parent head and fixes its
bias/input normalization while refitting all head weights around that prior.
It never resumes an optimizer, implicitly merges lanes, or changes proof rules.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
import json
import math
from pathlib import Path
import site
import sys
import time
import uuid

from . import codebase_source_384 as source384
from . import codebase_training_corpus as corpus_owner
from . import codebase_model_generation as generations
from . import codebase_runtime_384 as runtime_contract
from .codebase_resources import acquire_codebase_resources
from .codebase_ir import StaleCodebaseError
from ...duckdb_control import autoencoder_registry as native

SCHEMA='codebase-prior384-generation@1'
PROFILE='codebase_ir/parent_centered_head_refit_v1'
ALGORITHM='parent-centered-fixed-bias-ridge-head/v1'
RIDGES=(10.,30.,100.)
MAX_BYTES=source384.MAX_BYTES
raw,sha,require=source384._raw,source384._sha,source384._require
FALSE=dict(source384.FALSE)


def pins():
    worker=Path(__file__).with_name('codebase_prior_384_worker.py')
    return dict(owner=sha(Path(__file__).read_bytes()),worker=sha(worker.read_bytes()),
        source384=source384._pins(),corpus=corpus_owner._pins(),runtime=runtime_contract._pins(),
        registry=sha(Path(native.__file__).read_bytes()))


def describe():
    return dict(schema=SCHEMA,profile=PROFILE,algorithm=ALGORITHM,producer=pins(),ridges=list(RIDGES),
        selection='validation exact targets then semantic leaves; first ridge on ties',
        initialization='all parent head weights plus fixed inherited bias/input transform/projection/vocabulary',
        full_selected_training_head_refit=True,optimizer_steps=0,exact_optimizer_resume=False,
        topology='one ordered native candidate parent; native expected-head CAS',
        holdout_role='fixed_deployment_canary_not_final_unseen_test',
        source_contract=runtime_contract.describe_runtime()['source_contract'],
        target_contract=runtime_contract.describe_runtime()['target_contract'],
        decoder_contract=runtime_contract.describe_runtime()['decoder_contract'],
        microbatch='content-addressed source embedding rows reused only under exact model assets',
        objectives=deepcopy(runtime_contract.OBJECTIVES),**FALSE)


def register_parent(index,registry,*,source_parent_version_id):
    source384._owners(index,registry)
    version,saved=source384._lineage(index,registry,source_parent_version_id)[0]
    require(saved['kind']=='shared_parent','exact native shared parent required')
    value=dict(schema=SCHEMA,profile=PROFILE,producer=pins(),kind='parent',parent_version_id=None,
        source_parent_version_id=source_parent_version_id,source_parent_artifact=version['artifact'],
        checkpoint=source384._root_view(saved),authority=FALSE)
    variant='codebase-prior384:'+sha(raw(dict(profile=PROFILE,parent=source_parent_version_id,producer=pins())))
    registry.register_variant('variant:'+variant,variant,dict(profile=PROFILE,contract=describe(),
        original_parent_version_id=source_parent_version_id))
    artifact=generations._stage(registry,value)
    return registry.register_version('parent:'+variant,variant,artifact,metadata=dict(profile=PROFILE,authority=FALSE))['version_id']


def _corpus(index,value):
    from ...duckdb_control.codebase_catalog import CodebaseHead
    require(type(value) is dict and value['producer']==corpus_owner._pins(),'exact strict corpus producer required')
    copy=deepcopy(value);digest=copy.pop('corpus_sha256')
    require(digest==sha(raw(copy)),'strict corpus digest differs')
    source=value['source_corpus']
    rebuilt=corpus_owner._build(index,expected_head=CodebaseHead.from_dict(source['head']),
        selections=source['selections'],lineage_edges=[r for r in value['lineage_edges']
            if r['relation'] in ('rename','revision','conservative_related')],input_domains={},
        checked_execution=None,transductive_source_context=value['transductive_source_context'])
    # The fit uses structured source targets only. Independently checked labels
    # remain auxiliary and cannot silently become fitted targets here.
    require(rebuilt['fit_source_corpus']==value['fit_source_corpus']
        and rebuilt['components']==value['components']
        and [(r['path'],r['objectives']['syntax'],r['objectives']['semantic']) for r in rebuilt['rows']]
        ==[(r['path'],r['objectives']['syntax'],r['objectives']['semantic']) for r in value['rows']],
        'strict source/labels/connected roles differ')
    return value


def load(index,registry,version_id):
    """Historical immutable replay only; never fit, publish, or claim freshness."""
    from ..formalization.autoencoder import structured_source_384 as decoder
    chain=[];seen=set()
    while version_id is not None:
        require(version_id not in seen and len(chain)<8,'bounded acyclic prior lineage required')
        seen.add(version_id)
        version=registry.get_version(version_id)
        value=json.loads(registry.read_artifact(version['artifact'],max_bytes=MAX_BYTES))
        root_fields={'schema','profile','producer','kind','parent_version_id','source_parent_version_id','source_parent_artifact','checkpoint','authority'}
        child_fields={'schema','profile','producer','kind','parent_version_id','checkpoint','corpus','features','feature_artifacts',
            'embedding_assets','request','run_id','evaluation','fit','worker_receipt','canary_floor','authority'}
        require(type(value) is dict and set(value)==(root_fields if value.get('kind')=='parent' else child_fields),
            'closed prior root/child generation required')
        require(value['schema']==SCHEMA and value['profile']==PROFILE and value['producer']==pins()
            and value['authority']==FALSE and value['parent_version_id']==version['parent_version_id'],
            'prior generation profile/producer/parent differs')
        decoder.Runtime(value['checkpoint'])
        if value['kind']=='parent':
            original,saved=source384._lineage(index,registry,value['source_parent_version_id'])[0]
            require(original['artifact']==value['source_parent_artifact']
                and source384._root_view(saved)==value['checkpoint'] and version['parent_version_id'] is None,
                'exact original parent differs')
        else:
            require(value['kind']=='child','known prior generation kind required')
            _corpus(index,value['corpus'])
            require(type(value['features']) is list and len(value['features'])==len(value['feature_artifacts'])
                ==len(value['corpus']['fit_source_corpus']['rows']),'complete microbatch inventory required')
            require([r.get('source_sha256') for r in value['features']]
                ==[r['source_sha256'] for r in value['corpus']['fit_source_corpus']['rows']],
                'exact microbatch source population/order differs')
            for feature,artifact in zip(value['features'],value['feature_artifacts']):
                require(type(feature) is dict and set(feature)=={'source_sha256','embedding','embedding_sha256','assets_sha256'}
                    and type(feature['embedding']) is list and len(feature['embedding'])==384
                    and all(type(x) in (int,float) and math.isfinite(x) for x in feature['embedding']),
                    'closed finite 384D microbatch vector required')
                require(feature['embedding_sha256']==sha(raw(feature['embedding']))
                    and feature['assets_sha256']==sha(raw(value['embedding_assets'])),
                    'microbatch vector or declared embedding assets hash differs')
                require(registry.read_artifact(artifact,max_bytes=len(raw(feature)))==raw(feature),
                        'immutable microbatch artifact differs')
            completion=registry.get_run_completion(value['run_id'])
            require(completion is not None and completion['candidate_version']==version,
                'actual completed numerical producer required')
            request=value['request']
            request_fields={'profile','producer','parent_version_id','expected_model_head','source_head','corpus_sha256',
                'operation_id','embedding_snapshot','ridges','environment','randomness','topology'}
            require(type(request) is dict and set(request)==request_fields,'closed prior generation request required')
            require(completion['run']['spec']==request and request['profile']==PROFILE and request['producer']==pins()
                and request['ridges']==list(RIDGES) and request['topology']=='ordered_single_parent_no_implicit_merge'
                and request['parent_version_id']==value['parent_version_id']==completion['run']['base_version_id']
                and request['corpus_sha256']==value['corpus']['corpus_sha256']
                and request['source_head']==value['corpus']['source_corpus']['head']
                and value['run_id']=='prior384:'+sha(raw(request)),'prior completed request/source/parent binding differs')
            policy=registry.get_run_lifecycle(value['run_id'])
            require(policy is not None and policy['expected_head']==request['expected_model_head']
                and request['expected_model_head']['version_id']==value['parent_version_id']
                and request['expected_model_head']['variant_id']==version['variant_id'],
                'prior lifecycle expected parent head differs')
            require(value['request']['environment']==generations._environment()
                and value['request']['randomness']==generations.RANDOMNESS,'prior environment/randomness differs')
            require(value['fit']['algorithm']==ALGORITHM and value['fit']['nonzero_weight_update']
                and not value['fit']['exact_optimizer_resume'],'actual prior head refit required')
        chain.append((version,value));version_id=version['parent_version_id']
    require(chain[-1][1]['kind']=='parent','prior lineage must end in original shared weights')
    for position,((child_version,child),(parent_version,parent)) in enumerate(zip(chain,chain[1:])):
        require(child_version['variant_id']==parent_version['variant_id']
            and child['checkpoint']['training']['base_checkpoint_sha256']==sha(raw(parent['checkpoint']))
            and all(child['checkpoint'][field]==parent['checkpoint'][field] for field in
                ('projection_state','input_transform','target_schema'))
            and child['checkpoint']['head_state']['bias']==parent['checkpoint']['head_state']['bias'],
            'prior weights/projection/vocabulary/normalization parent differs')
        _successor(child['corpus'],chain[position+1:])
        expected_floor=(child['evaluation']['parent_holdout'] if parent['kind']=='parent' else parent['canary_floor'])
        require(child['canary_floor']==expected_floor,'fixed ancestral canary floor differs')
        payload=dict(action='train',producer=pins(),parent=parent['checkpoint'],corpus=child['corpus'],
            embedding_snapshot=child['request']['embedding_snapshot'],previous_features=parent.get('features',[]))
        output=dict(producer=pins(),checkpoint=child['checkpoint'],features=child['features'],
            embedding_assets=child['embedding_assets'],evaluation=child['evaluation'],fit=child['fit'])
        receipt=child['worker_receipt']
        require(set(receipt)=={'elapsed_ms','input_sha256','output_sha256','workspace_cleaned','provider_calls','memory_mb','memory_enforcement'}
            and receipt['input_sha256']==sha(raw(payload)) and receipt['output_sha256']==sha(raw(output))
            and receipt['workspace_cleaned'] is True and receipt['provider_calls']==0,
            'exact prior numerical worker input/output receipt differs')
        with decoder._numeric() as np:
            delta=float(np.linalg.norm(np.asarray(child['checkpoint']['head_state']['weights'])
                -np.asarray(parent['checkpoint']['head_state']['weights'])))
        require(delta>1e-12 and math.isclose(delta,child['fit']['weight_delta_l2'],rel_tol=1e-12,abs_tol=1e-14)
            and child['fit']['head_bytes_changed'] is True
            and child['checkpoint']['head_sha256']!=parent['checkpoint']['head_sha256'],
            'actual parent-relative numerical weight update differs')
    return chain


def _successor(corpus,chain):
    children=[v for _,v in chain if v['kind']=='child']
    if not children:return
    root=children[-1]['corpus'];current=corpus['source_corpus']
    require(current['selections']==root['source_corpus']['selections']
        and current['head']['repository_id']==root['source_corpus']['head']['repository_id'],
        'complete ancestral source roles required')
    fixed=lambda c:[(r['path'],r['role'],r['source_sha256'],r['target_sha256'])
        for r in c['rows'] if r['role']!='train']
    require(fixed(corpus)==fixed(root),'fixed ancestral validation/holdout canaries changed')
    past={r['alpha_clone_sha256'] for c in children for r in c['corpus']['rows'] if r['role']=='train'}
    require(not past & {r['alpha_clone_sha256'] for r in corpus['rows'] if r['role']!='train'},
        'ancestral training leakage into evaluation')


def _worker(payload,lease,signal,timeout,memory_mb):
    from ..backends.codebase_process import BoundedToolRunner,ToolRunLimits,run_bounded_stdin_tool
    from ...optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLane
    paths=list(dict.fromkeys([str(Path(__file__).resolve().parents[3]),*site.getsitepackages(),site.getusersitepackages()]))
    runner=BoundedToolRunner(base_environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8',
        'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1',
        'NUMEXPR_NUM_THREADS':'1','TOKENIZERS_PARALLELISM':'false'})
    deadline=time.monotonic()+timeout
    with lease.acquire_child(lane=ResourceLane.TRAINER,cpu_slots=1,memory_mb=memory_mb,child_process_slots=1,
        timeout=timeout,cancel_event=signal,request_id='codebase-prior384:train') as child:
        seconds=deadline-time.monotonic();require(seconds>0 and not signal.is_set(),'prior child admission consumed deadline')
        result=run_bounded_stdin_tool([sys.executable,'-I','-B',str(Path(__file__).with_name('codebase_prior_384_worker.py')),json.dumps(paths)],raw(payload),
            runner=runner,limits=ToolRunLimits(timeout_seconds=seconds,resident_memory_bytes=memory_mb*1024**2,
                max_input_bytes=MAX_BYTES,max_output_bytes=MAX_BYTES,max_workspace_bytes=2*MAX_BYTES),
            cancellation=child.combined_cancellation_signal(signal))
    require(result.returncode==0 and result.workspace_cleaned and not any((result.timed_out,result.cancelled,
        result.unavailable,result.output_truncated,result.resource_exhausted)),
        'bounded prior worker failed: '+str(result.termination_reason)+': '+result.stderr[-2048:])
    return json.loads(result.stdout),dict(elapsed_ms=result.elapsed_ms,input_sha256=sha(raw(payload)),
        output_sha256=sha(result.stdout.encode()),workspace_cleaned=True,provider_calls=0,memory_mb=memory_mb,
        memory_enforcement='sampled_process_tree_RSS_may_overshoot')


class _Signal:
    def __init__(self,registry,run_id,head,external,deadline):
        self.registry,self.run_id,self.head,self.external,self.deadline=registry,run_id,head,external,deadline
    def stop(self,status,reason):
        row=self.registry.get_run(self.run_id)
        if row['status'] in {'cancelled','superseded','completed'}:return
        self.registry.terminate_run('prior-stop:'+sha(raw([self.run_id,status,row['fence'],reason])),self.run_id,
            terminal=status,expected_attempt=row['attempt'],expected_fence=row['fence'],reason=reason)
    def is_set(self):
        row=self.registry.get_run(self.run_id)
        if row['status'] in {'cancelled','superseded'}:return True
        if self.registry.resolve_head(self.head['variant_id'],self.head['branch'])!=self.head:
            self.stop('superseded','expected model head changed');return True
        if time.monotonic()>=self.deadline or self.external is not None and self.external.is_set():
            self.stop('cancelled','deadline or external cancellation');return True
        return False


def train(index,repository,*,expected_head,frozen_corpus,registry,parent_version_id,expected_model_head,
        operation_id,embedding_snapshot,scheduler=None,parent_lease=None,cancel_event=None,
        timeout_seconds=120.,memory_mb=4096):
    """Fit a new native candidate; quality qualification and CAS remain separate."""
    started=time.monotonic()
    source384._limits(timeout_seconds,memory_mb,operation_id);source384._owners(index,registry)
    require(registry.resolve_head(expected_model_head['variant_id'],expected_model_head['branch'])==expected_model_head
        and expected_model_head['version_id']==parent_version_id,'exact selected prior parent head required')
    corpus=corpus_owner.verify_frozen_corpus(frozen_corpus,index,expected_head=expected_head)
    chain=load(index,registry,parent_version_id);parent_version,parent=chain[0]
    require(parent_version['variant_id']==expected_model_head['variant_id'],'prior parent variant differs')
    require(len(chain)<8,'prior ancestry limit exceeded');_successor(corpus,chain)
    request=dict(profile=PROFILE,producer=pins(),parent_version_id=parent_version_id,
        expected_model_head=deepcopy(expected_model_head),source_head=expected_head.to_dict(),
        corpus_sha256=corpus['corpus_sha256'],operation_id=operation_id,
        embedding_snapshot=str(Path(embedding_snapshot).resolve()),ridges=list(RIDGES),
        environment=generations._environment(),randomness=deepcopy(generations.RANDOMNESS),
        topology='ordered_single_parent_no_implicit_merge')
    run_id='prior384:'+sha(raw(request))
    registry.create_run('create:'+run_id,run_id,parent_version['variant_id'],parent_version_id,request)
    policy=dict(schema=native.RUN_LIFECYCLE_SCHEMA,max_attempts=1,
        wall_time_seconds=timeout_seconds,memory_bytes=memory_mb*1024**2,max_input_bytes=MAX_BYTES,
        max_samples=128,optimizer_steps=0,head_refits=1,max_checkpoint_bytes=MAX_BYTES,
        expected_head=deepcopy(expected_model_head))
    existing=registry.get_run_lifecycle(run_id)
    if existing is None:registry.configure_run_lifecycle(run_id,policy)
    else:
        require({k:v for k,v in existing.items() if k!='wall_time_seconds'}
            =={k:v for k,v in policy.items() if k!='wall_time_seconds'},'immutable prior lifecycle budget differs')
        timeout_seconds=min(timeout_seconds,existing['wall_time_seconds'])
    signal=_Signal(registry,run_id,expected_model_head,cancel_event,started+timeout_seconds)
    def remaining():
        require(not signal.is_set(),'prior training cancelled/superseded/expired');return signal.deadline-time.monotonic()
    with acquire_codebase_resources(scheduler=scheduler,parent_lease=parent_lease,cancel_event=signal,
        timeout_seconds=min(30.,remaining()),memory_mb=memory_mb) as lease:
        def observe():index.observe_current(repository,expected_head=expected_head,parent_lease=lease,
            cancel_event=signal,timeout_seconds=remaining(),memory_mb=memory_mb)
        observe()
        previous=registry.get_run_completion(run_id)
        if previous is not None:
            value=load(index,registry,previous['candidate_version']['version_id'])[0][1]
            return dict(version_id=previous['candidate_version']['version_id'],training_executed=False,replayed=True,
                evaluation=value['evaluation'],fit=value['fit'],**FALSE)
        token=uuid.uuid4().hex
        claim=registry.claim_run('claim:'+token,run_id,'prior384:'+token,lease_seconds=remaining()+10)['lease']
        try:
            previous_features=parent.get('features',[])
            payload=dict(action='train',producer=pins(),parent=parent['checkpoint'],corpus=corpus,
                embedding_snapshot=request['embedding_snapshot'],previous_features=previous_features)
            require(len(raw(payload))<=MAX_BYTES,'bounded prior fit input required')
            result,receipt=_worker(payload,lease,signal,remaining(),memory_mb)
            require(result['producer']==pins() and request['environment']==generations._environment()
                and request['randomness']==generations.RANDOMNESS,'prior producer/environment/randomness changed')
            observe();remaining()
            value=dict(schema=SCHEMA,profile=PROFILE,producer=pins(),kind='child',parent_version_id=parent_version_id,
                checkpoint=result['checkpoint'],corpus=corpus,features=result['features'],
                feature_artifacts=[generations._stage(registry,row) for row in result['features']],
                embedding_assets=result['embedding_assets'],
                request=request,run_id=run_id,evaluation=result['evaluation'],fit=result['fit'],worker_receipt=receipt,
                canary_floor=deepcopy(result['evaluation']['parent_holdout'] if parent['kind']=='parent' else parent['canary_floor']),
                authority=FALSE)
            artifact=generations._stage(registry,value);observe();remaining()
            completed=registry.complete_run('complete:'+run_id,claim,artifact,dict(admitted=False,profile=PROFILE,
                request_sha256=sha(raw(request)),promotion_performed=False))
            load(index,registry,completed['version_id'])
            return dict(**completed,training_executed=True,replayed=False,evaluation=result['evaluation'],fit=result['fit'])
        except BaseException as error:
            if isinstance(error,StaleCodebaseError):signal.stop('superseded','current source changed')
            elif signal.is_set():pass
            try:registry.fail_run('fail:'+token,claim,dict(admitted=False,reason=type(error).__name__))
            except Exception:pass
            raise


class RetentionPolicy:
    """Independent exact completed-run/source-canary policy for native CAS.

    Construct this as the native registry's promotion_validator. It loads and
    validates the completed generation; caller metrics cannot waive retention.
    This policy selects model candidates, never program or proof authority.
    """
    def __init__(self,index):self.index,self.registry=index,None
    def bind(self,registry):
        require(type(registry) is native.AutoencoderRegistry and self.registry is None,'one native registry binding required')
        self.registry=registry
    def __call__(self,version,evaluation):
        try:
            require(self.registry is not None,'native retention registry not bound')
            chain=load(self.index,self.registry,version['version_id'])
            loaded,value=chain[0]
            require(loaded==version and value['kind']=='child','actual prior child required')
            require(evaluation==dict(candidate_version_id=version['version_id'],protocol_id='prior384-fixed-canary-retention@1',
                evaluation_sha256=sha(raw(value['evaluation']))),'exact native canary evaluation required')
            observed=value['evaluation'];floor=value['canary_floor']
            require(observed['holdout_used_for_selection'] is False,'holdout selection prohibited')
            # Reevaluate exact weights with already verified immutable source
            # features and native targets. This is cached-feature inference,
            # not a fresh GTE run or trust in caller-supplied metric numbers.
            from ..formalization.autoencoder import structured_source_384 as decoder
            features={row['source_sha256']:row for row in value['features']}
            require(len(features)==len(value['features']),'unique canary features required')
            def rows(role):
                return [dict(id=row['id'],source_text=row['source_text'],target=row['target'],
                    embedding=features[row['source_sha256']]['embedding'])
                    for row in value['corpus']['fit_source_corpus']['rows'] if row['role']==role]
            def score(checkpoint,role):
                result=decoder.evaluate(checkpoint,rows(role))
                return {key:result[key] for key in ('count','exact_targets','semantic_leaf_correct','semantic_leaf_count','valid_candidates')}
            require(observed['child_holdout']==score(value['checkpoint'],'holdout')
                and observed['parent_holdout']==score(chain[1][1]['checkpoint'],'holdout')
                and observed['child_validation']==score(value['checkpoint'],'validation')
                and observed['parent_validation']==score(chain[1][1]['checkpoint'],'validation')
                and floor==score(chain[-1][1]['checkpoint'],'holdout'),
                'independent cached-feature retention scores differ')
            for candidate,baseline in ((observed['child_holdout'],observed['parent_holdout']),
                    (observed['child_holdout'],floor),(observed['child_validation'],observed['parent_validation'])):
                require(candidate['count']==baseline['count']>0 and candidate['valid_candidates']==candidate['count']
                    and (candidate['exact_targets'],candidate['semantic_leaf_correct'])>=
                    (baseline['exact_targets'],baseline['semantic_leaf_correct']),'fixed canary retention regressed')
            require(value['fit']['weight_delta_l2']>1e-12,'byte-identical copies are not trained child improvement')
            return True
        except (ValueError,KeyError,TypeError):return False


def promote(index,repository,*,expected_head,registry,version_id,operation_id,
        scheduler=None,parent_lease=None,cancel_event=None,timeout_seconds=30.,memory_mb=4096):
    value=load(index,registry,version_id)[0][1]
    require(value['kind']=='child' and value['request']['source_head']==expected_head.to_dict(),'current prior child source required')
    index.observe_current(repository,expected_head=expected_head,scheduler=scheduler,parent_lease=parent_lease,
        cancel_event=cancel_event,timeout_seconds=timeout_seconds,memory_mb=memory_mb)
    expected=value['request']['expected_model_head']
    return registry.promote_head(operation_id,expected['variant_id'],expected['branch'],version_id,
        expected_version_id=expected['version_id'],expected_generation=expected['generation'],
        evaluation=dict(candidate_version_id=version_id,protocol_id='prior384-fixed-canary-retention@1',
            evaluation_sha256=sha(raw(value['evaluation']))))


def _projection_key(index,registry,*,expected_head,version_id,paths,embedding_snapshot):
    from ...optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as embedding
    version,value=load(index,registry,version_id)[0]
    inputs,inventory=runtime_contract._source_inputs(index,expected_head,paths)
    _,assets=embedding._snapshot_assets(embedding_snapshot)
    return dict(schema='codebase-model-projection-index@1',profile=PROFILE,producer=pins(),
        source_head=expected_head.to_dict(),source_inventory=inventory,source_input_sha256=sha(raw(inputs)),
        model_version_id=version_id,model_artifact=version['artifact'],checkpoint_sha256=sha(raw(value['checkpoint'])),
        embedding_assets=assets),inputs,value


def infer_and_index(index,repository,*,expected_head,registry,version_id,paths,embedding_snapshot,
        scheduler=None,parent_lease=None,cancel_event=None,timeout_seconds=120.,memory_mb=4096):
    """Build a learned projection for exact model/source dependencies only.

    Native model operation/CAS ownership persists the immutable index artifact;
    deterministic source/semantic artifacts remain separate. Changed decoder
    versions derive a new key even when their emitted candidates happen to match.
    """
    source384._limits(timeout_seconds,memory_mb,'prior-inference')
    source384._owners(index,registry);deadline=time.monotonic()+timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler,parent_lease=parent_lease,cancel_event=cancel_event,
        timeout_seconds=min(30.,timeout_seconds),memory_mb=memory_mb) as lease:
        signal=lease.combined_cancellation_signal(cancel_event)
        def remaining():
            require(not signal.is_set() and time.monotonic()<deadline,'prior inference cancelled/expired')
            return deadline-time.monotonic()
        def observe():index.observe_current(repository,expected_head=expected_head,parent_lease=lease,
            cancel_event=signal,timeout_seconds=remaining(),memory_mb=memory_mb)
        observe()
        key,inputs,value=_projection_key(index,registry,expected_head=expected_head,version_id=version_id,
            paths=paths,embedding_snapshot=embedding_snapshot)
        operation='prior-projection:'+sha(raw(key))
        with registry._transaction() as cx:
            row=cx.execute('SELECT receipt FROM autoencoder_control.operations WHERE operation_id=?',[operation]).fetchone()
        if row is not None:
            saved=json.loads(row[0]);artifact=saved['artifact']
            require(registry.resolve_operation(operation,'IndexPriorProjection',dict(key=key,artifact=artifact))==saved,
                'exact native projection operation required')
            result=load_projection(index,registry,artifact,expected_head=expected_head,version_id=version_id,
                paths=paths,embedding_snapshot=embedding_snapshot)
            observe()
            return dict(artifact=artifact,projection=result,inference_executed=False,training_executed=False,**FALSE)
        result,receipt=source384._worker(dict(action='infer',checkpoint=value['checkpoint'],rows=inputs,
            producer=source384._pins(),embedding_snapshot=str(Path(embedding_snapshot).resolve()),weight_ablation=None),
            lease=lease,signal=signal,timeout=remaining(),memory_mb=memory_mb)
        observe()
        final,_,_=_projection_key(index,registry,expected_head=expected_head,version_id=version_id,
            paths=paths,embedding_snapshot=embedding_snapshot)
        require(key==final and result['producer']==source384._pins() and result['embedding_assets']==key['embedding_assets']
            and result['training_executed'] is False,'prior inference dependency changed')
        projection=dict(schema=key['schema'],key=key,inference=result['inference'],worker_receipt=receipt,
            training_executed=False,targets_used_for_inference=False,**FALSE)
        artifact=generations._stage(registry,projection);observe();remaining()
        registry._mutate(operation,'IndexPriorProjection',dict(key=key,artifact=artifact),lambda cx:dict(artifact=artifact))
        return dict(artifact=artifact,projection=projection,inference_executed=True,training_executed=False,**FALSE)


def load_projection(index,registry,artifact,*,expected_head,version_id,paths,embedding_snapshot):
    """Historical projection replay; exact new model dependencies are mandatory."""
    registry.verify_artifact(artifact)
    saved=json.loads(registry.artifact_path(artifact).read_bytes())
    expected,_,_=_projection_key(index,registry,expected_head=expected_head,version_id=version_id,
        paths=paths,embedding_snapshot=embedding_snapshot)
    require(saved['schema']=='codebase-model-projection-index@1' and saved['key']==expected
        and saved['training_executed'] is False and saved['targets_used_for_inference'] is False
        and all(saved[field] is False for field in FALSE),'model-dependent projection key differs')
    operation='prior-projection:'+sha(raw(expected))
    receipt=registry.resolve_operation(operation,'IndexPriorProjection',dict(key=expected,artifact=artifact))
    require(receipt is not None and receipt['artifact']==artifact,'durable native projection operation missing')
    return saved


class PriorRuntime384:
    """Trusted local adapter for the explicitly separate parent-centered profile."""
    def __init__(self):
        from ...optimizers.logic_theorem_optimizer import autoencoder_modality_contracts as contracts
        identity=lambda name,value:contracts.ImplementationIdentity(name,'1',sha(raw(value)))
        self.contract=replace(runtime_contract.modality_contract(),
            state_codec=identity('codebase-prior384-generation',dict(schema=SCHEMA,producer=pins())),
            optimizer=identity('parent-centered-head-refit',describe()),
            adapter=identity('codebase-prior384-local-adapter',pins()))
        self._implementation=pins()
    def _check(self):require(self._implementation==pins(),'registered prior runtime implementation changed')
    def prepare_targets(self,index,**options):
        self._check();return corpus_owner.freeze_corpus(index,**options)
    def validate_targets(self,handle,index,**options):
        self._check();return corpus_owner.verify_frozen_corpus(handle,index,**options)
    def train(self,index,repository,**options):
        self._check();return train(index,repository,**options)
    def evaluate(self,index,repository,**options):
        self._check();return infer_and_index(index,repository,**options)


def register_runtime(registry):
    from ...optimizers.logic_theorem_optimizer import autoencoder_modality_contracts as contracts
    require(type(registry) is contracts.ModalityAdapterRegistry,'native local modality adapter registry required')
    adapter=PriorRuntime384()
    registry.register(adapter.contract,adapter,capabilities=['prepare_targets','validate_targets','train','evaluate'])
    return adapter

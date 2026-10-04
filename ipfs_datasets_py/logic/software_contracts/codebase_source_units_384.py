"""Versioned, target-free pinned-parent inference on captured function units.

Source heads and model generations stay with their native owners. Function
normalization is an explicit source view, never a whole-file semantics claim.
The native operation receipt authenticates replay; no replay performs inference.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path, PurePosixPath
import site
import sys
import time
from collections import Counter
from importlib.metadata import version as package_version

from ...duckdb_control.codebase_catalog import CodebaseHead
from ...duckdb_control import autoencoder_registry
from ..formalization.autoencoder import source_function_units as units
from . import codebase_source_384 as shared
from .codebase_resources import acquire_codebase_resources

SCHEMA = "codebase-source-unit-inference@1"
PREPARATION_SCHEMA = "codebase-source-unit-preparation@1"
WORKER_SCHEMA = "codebase-source-unit-worker@1"
EMBEDDING_CACHE_POLICY = "verified_snapshot_dontneed_best_effort@1"
MAX_BYTES = 32 * 1024**2
FALSE = dict(proof_authority=False, execution_authority=False, completion_authority=False,
    source_semantics_verified=False, whole_file_semantics_verified=False,
    promotion_performed=False, training_executed=False, training_labels_used=False,
    source_executed=False, claim_proved=False)
raw, sha, require = shared._raw, shared._sha, shared._require


def pins():
    from . import codebase_source_units_384_worker as worker
    from ..formalization.autoencoder import source_program_runtime_384 as runtime
    from ..formalization.autoencoder import source_embeddings_384 as embeddings
    from ...optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as verifier
    return dict(owner=sha(Path(__file__).read_bytes()), worker=sha(Path(worker.__file__).read_bytes()),
        extraction=units.pins(), shared=shared._pins(), runtime=sha(Path(runtime.__file__).read_bytes()),
        embeddings=sha(Path(embeddings.__file__).read_bytes()),
        embedding_verifier=sha(Path(verifier.__file__).read_bytes()),
        registry=sha(Path(autoencoder_registry.__file__).read_bytes()))


def prepare_source_units(index, *, expected_head, paths, max_functions=1024, max_selected_units=128):
    """Read a historical captured population; current authority needs observation.

    Selection is a deterministic path/byte-order prefix of AST-preserved units.
    Every supplied file and function remains inventoried, including deferrals.
    """
    require(type(expected_head) is CodebaseHead, "exact source head required")
    require(type(paths) in (list, tuple) and 1 <= len(paths) <= 128
        and all(type(p) is str and 0 < len(p.encode()) <= 1024
                and PurePosixPath(p).as_posix() == p and not PurePosixPath(p).is_absolute()
                and '..' not in p.split('/') and '\\' not in p for p in paths)
        and len(set(paths)) == len(paths), "distinct canonical captured source paths required")
    require(type(max_functions) is int and 1 <= max_functions <= 1024
        and type(max_selected_units) is int and 1 <= max_selected_units <= 128,
        "explicit bounded function inventory and selection required")
    manifest = index.load(expected_head.manifest_cid)
    require(manifest.snapshot.repository_id == expected_head.repository_id
        and manifest.snapshot.snapshot_cid == expected_head.snapshot_cid
        and manifest.ast_revision_id == expected_head.ast_revision_id, "captured source head differs")
    entries = {e.path:e for e in manifest.snapshot.entries}
    files=[]; selected=[]; function_count=0; byte_count=0; mapped_bytes=0
    for path in sorted(paths):
        require(path in entries, "selected path is outside captured inventory")
        entry=entries[path]
        file=dict(path=path, entry_cid=entry.entry_cid, source_cid=entry.source_cid,
            bytes=entry.size_bytes, disposition=None, extraction=None)
        files.append(file)
        if entry.is_opaque:
            file['disposition']='opaque:'+entry.opaque_reason
            continue
        if not 0 < entry.size_bytes <= units.MAX_SOURCE_BYTES:
            file['disposition']='deferred_source_byte_limit'
            continue
        byte_count += entry.size_bytes
        require(byte_count <= 4 * 1024**2, "complete source population exceeds byte budget")
        body=index.artifacts.get_bytes(entry.source_cid)
        require(len(body)==entry.size_bytes, "captured source byte count differs")
        extracted=units.extract_function_units(source_bytes=body, source_sha256=sha(body),
            source_path=path, max_functions=max_functions)
        file.update(source_sha256=sha(body), disposition=extracted['frontier'] or 'inventoried', extraction=extracted)
        function_count += len(extracted['units'])
        require(function_count <= max_functions, "whole source population function bound exceeded; no truncation")
        for unit in extracted['units']:
            mapped_bytes += len(unit['normalized_source_text'].encode())
            require(mapped_bytes <= 4 * 1024**2, "normalized function population exceeds byte budget")
            status=unit['status']
            if status=='eligible':
                if len(unit['normalized_source_text']) > 32768:
                    status='deferred_source_character_limit'
                elif len(selected) >= max_selected_units:
                    status='deferred_selection_budget'
                else:
                    status='selected_for_token_check'
                    selected.append(dict(id=unit['unit_id'],source_text=unit['normalized_source_text']))
            unit['inference_disposition']=status
    value=dict(schema=PREPARATION_SCHEMA,source_head=expected_head.to_dict(),paths=sorted(paths),
        max_functions=max_functions,max_selected_units=max_selected_units,files=files,
        selected_inputs=selected,producer=pins(),selection='canonical_path_then_source_byte_order',
        counts=dict(files=len(files),functions=function_count,selected_units=len(selected)),**FALSE)
    require(len(raw(value)) <= MAX_BYTES, "function preparation exceeds artifact bound")
    return value


def validate_source_units(index, report):
    actual=prepare_source_units(index, expected_head=CodebaseHead.from_dict(report['source_head']),
        paths=report['paths'],max_functions=report['max_functions'],max_selected_units=report['max_selected_units'])
    require(raw(actual)==raw(report), "captured function source maps or preparation changed")
    return actual


def _context(index,registry,*,expected_head,version_id,paths,embedding_snapshot,max_functions,max_selected_units):
    from ...optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as embeddings
    preparation=prepare_source_units(index,expected_head=expected_head,paths=paths,
        max_functions=max_functions,max_selected_units=max_selected_units)
    version,saved=shared._lineage(index,registry,version_id)[0]
    require(saved['kind']=='shared_parent', "pinned shared parent required; trained children are not selected")
    checkpoint=shared._root_view(saved)
    snapshot,assets=embeddings._snapshot_assets(embedding_snapshot,release_verified_pages=True)
    key=dict(schema=SCHEMA,source_head=expected_head.to_dict(),preparation_sha256=sha(raw(preparation)),
        version_id=version_id,parent_artifact=version['artifact'],original_checkpoint_sha256=saved['original_checkpoint_sha256'],
        runtime_checkpoint_sha256=sha(raw(checkpoint)),embedding_snapshot=str(snapshot),embedding_assets=assets,
        producer=pins(),embedding_cache_policy=EMBEDDING_CACHE_POLICY,device='cpu',batch_size=16,python=sys.version,
        runtime_versions={n:package_version(n) for n in ('torch','numpy','transformers','sentence-transformers','tokenizers')})
    return key,preparation,checkpoint


def _coverage(preparation,output):
    by_id={r['id']:r for r in output['rows']}
    dispositions=Counter();candidates=Counter()
    for file in preparation['files']:
        for unit in (file['extraction'] or {}).get('units',[]):
            row=by_id.get(unit['unit_id'])
            dispositions[row['status'] if row else unit['inference_disposition']]+=1
            if row and row['candidate'] is not None:
                candidates[row['candidate']['status']]+=1
    return dict(**preparation['counts'],unit_dispositions=dict(sorted(dispositions.items())),
        candidate_statuses=dict(sorted(candidates.items())),
        file_dispositions=dict(sorted(Counter(f['disposition'] for f in preparation['files']).items())))


def _validate_output(output,key,preparation):
    require(type(output) is dict and set(output)=={'schema','key','rows','model_loads',*FALSE}
        and output['schema']==WORKER_SCHEMA and output['key']==key
        and all(output[k] is False for k in FALSE), "closed non-authoritative source-unit output required")
    inputs=preparation['selected_inputs'];rows=output['rows']
    require(type(rows) is list and len(rows)==len(inputs)
        and type(output['model_loads']) is int and output['model_loads']==int(bool(inputs)),
        "complete source-unit inference population required")
    from ..formalization.autoencoder.source_program_runtime_384 import FALSE as decoder_false
    for row,source in zip(rows,inputs):
        require(set(row)=={'id','source_sha256','status','tokens','embedding','candidate'}
            and row['id']==source['id'] and row['source_sha256']==sha(source['source_text'].encode())
            and type(row['tokens']) is int and row['tokens']>0, "exact normalized inference source binding required")
        if row['status']=='deferred_gte_token_limit':
            require(row['tokens']>512 and row['embedding'] is None and row['candidate'] is None,
                "token-deferred unit cannot carry inference")
        else:
            require(row['status']=='decoded_unverified_candidate' and row['tokens']<=512
                and type(row['embedding']) is list and len(row['embedding'])==384
                and all(type(v) in (int,float) and math.isfinite(v) for v in row['embedding']),
                "exact finite384D feature required")
            candidate=row['candidate']
            require(type(candidate) is dict and candidate['id']==row['id']
                and candidate['source_sha256']==row['source_sha256']
                and all(candidate[k] is False for k in decoder_false),
                "candidate changed normalized source or gained authority")
    require(len(raw(output))<=MAX_BYTES, "source-unit output exceeds bound")


def _worker(payload,*,lease,signal,timeout,memory_mb):
    from . import codebase_source_units_384_worker as worker
    from ..backends.codebase_process import BoundedToolRunner,ToolRunLimits,run_bounded_stdin_tool
    from ...optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLane
    roots=list(dict.fromkeys([str(Path(__file__).resolve().parents[3]),*site.getsitepackages(),site.getusersitepackages()]))
    runner=BoundedToolRunner(base_environment=dict(PATH='/usr/bin:/bin',LANG='C.UTF-8',LC_ALL='C.UTF-8',
        CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',
        NUMEXPR_NUM_THREADS='1',TOKENIZERS_PARALLELISM='false',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1'))
    wire=raw(payload);require(len(wire)<=MAX_BYTES,'source-unit worker input exceeds bound')
    deadline=time.monotonic()+timeout
    with lease.acquire_child(lane=ResourceLane.ORCHESTRATION,cpu_slots=1,memory_mb=memory_mb,
            child_process_slots=1,timeout=timeout,cancel_event=signal,request_id='source-unit384:infer') as child:
        left=deadline-time.monotonic();require(left>0,'source-unit worker admission exhausted deadline')
        result=run_bounded_stdin_tool([sys.executable,'-I','-B',str(Path(worker.__file__).resolve()),json.dumps(roots)],wire,
            runner=runner,limits=ToolRunLimits(timeout_seconds=left,resident_memory_bytes=memory_mb*1024**2,
                max_input_bytes=MAX_BYTES,max_output_bytes=MAX_BYTES,max_workspace_bytes=2*MAX_BYTES),
            cancellation=child.combined_cancellation_signal(signal))
    require(result.returncode==0 and result.workspace_cleaned and not any((result.timed_out,result.cancelled,
        result.unavailable,result.output_truncated,result.resource_exhausted,result.error)),
        'bounded source-unit worker failed: '+str(result.termination_reason)+': '+result.stderr[-2048:])
    return json.loads(result.stdout),dict(input_sha256=sha(wire),output_sha256=sha(result.stdout.encode()),
        returncode=0,workspace_cleaned=True,device='cpu',provider_calls=0,elapsed_ms=result.elapsed_ms,
        memory_mb=memory_mb,memory_enforcement='sampled_process_tree_RSS_may_overshoot',
        parent_lease_id=lease.lease_id,child_lease_id=child.lease_id)


def load_source_unit_inference(index,registry,artifact,*,expected_head,version_id,paths,embedding_snapshot,
        max_functions=1024,max_selected_units=128):
    """Historical exact owner-backed replay; no inference and no current-source claim."""
    key,preparation,checkpoint=_context(index,registry,expected_head=expected_head,version_id=version_id,
        paths=paths,embedding_snapshot=embedding_snapshot,max_functions=max_functions,max_selected_units=max_selected_units)
    saved=json.loads(registry.read_artifact(artifact,max_bytes=MAX_BYTES))
    require(set(saved)=={'schema','key','preparation','output','worker_receipt','retention','coverage',*FALSE}
        and saved['schema']==SCHEMA and saved['key']==key and saved['preparation']==preparation
        and saved['retention']=='unknown_not_evaluated' and all(saved[k] is False for k in FALSE),
        'exact source-unit execution context required')
    _validate_output(saved['output'],key,preparation)
    require(saved['coverage']==_coverage(preparation,saved['output']),'source-unit coverage differs')
    payload=dict(schema=WORKER_SCHEMA,key=key,checkpoint=checkpoint,rows=preparation['selected_inputs'])
    receipt=saved['worker_receipt']
    require(receipt['input_sha256']==sha(raw(payload)) and receipt['output_sha256']==sha(raw(saved['output']))
        and receipt['returncode']==0 and receipt['workspace_cleaned'] is True and receipt['device']=='cpu'
        and receipt['provider_calls']==0,'native source-unit worker receipt differs')
    operation='source-unit384:'+sha(raw(key))
    committed=registry.resolve_operation(operation,'IndexSourceUnitInference',dict(key=key))
    require(committed is not None and committed['artifact']==artifact,'native source-unit execution operation missing')
    return saved


def infer_shared_parent_units(index,repository,*,expected_head,registry,version_id,paths,embedding_snapshot,
        max_functions=1024,max_selected_units=128,scheduler=None,parent_lease=None,cancel_event=None,
        timeout_seconds=180.,memory_mb=4096):
    """Execute/replay pinned-parent unit inference under live source/model fences."""
    shared._owners(index,registry);shared._limits(timeout_seconds,memory_mb,'source-unit-inference')
    deadline=time.monotonic()+timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler,parent_lease=parent_lease,cancel_event=cancel_event,
            timeout_seconds=min(30.,timeout_seconds),memory_mb=memory_mb) as lease:
        signal=lease.combined_cancellation_signal(cancel_event)
        def remaining():
            require(not signal.is_set() and time.monotonic()<deadline,'source-unit inference cancelled or deadline expired')
            return deadline-time.monotonic()
        def observe():
            index.observe_current(repository,expected_head=expected_head,parent_lease=lease,cancel_event=signal,
                timeout_seconds=remaining(),memory_mb=memory_mb)
        options=dict(expected_head=expected_head,version_id=version_id,paths=paths,embedding_snapshot=embedding_snapshot,
            max_functions=max_functions,max_selected_units=max_selected_units)
        observe();key,preparation,checkpoint=_context(index,registry,**options)
        operation='source-unit384:'+sha(raw(key))
        previous=registry.resolve_operation(operation,'IndexSourceUnitInference',dict(key=key))
        executed=previous is None
        if previous is None:
            payload=dict(schema=WORKER_SCHEMA,key=key,checkpoint=checkpoint,rows=preparation['selected_inputs'])
            output,receipt=_worker(payload,lease=lease,signal=signal,timeout=remaining(),memory_mb=memory_mb)
            # Numerical inputs are no longer needed while acquiring the next
            # source fence. The selected checkpoint is independently reloaded
            # and rebound by the context comparison and immutable replay below.
            del payload,checkpoint
            _validate_output(output,key,preparation);observe()
            require(_context(index,registry,**options)[0]==key,'source-unit model or source changed during inference')
            saved=dict(schema=SCHEMA,key=key,preparation=preparation,output=output,worker_receipt=receipt,
                coverage=_coverage(preparation,output),
                retention='unknown_not_evaluated',**FALSE)
            artifact=shared._stage(registry,saved)
            remaining();observe()
            previous=registry._mutate(operation,'IndexSourceUnitInference',dict(key=key),lambda cx:dict(artifact=artifact))
            del output,receipt,saved
        else:
            del checkpoint
        # The committed report is reconstructed independently. Do not overlap
        # its bulk graphs with the completed construction context at that gate.
        del key,preparation
        saved=load_source_unit_inference(index,registry,previous['artifact'],**options)
        observe();remaining()
        return dict(artifact=previous['artifact'],report=saved,native_worker_executed=executed,
            inference_executed=executed and any(r['candidate'] is not None for r in saved['output']['rows']),**FALSE)


def validate_shared_parent_units(index,repository,report,*,registry,embedding_snapshot,
        scheduler=None,parent_lease=None,cancel_event=None,timeout_seconds=90.,memory_mb=4096):
    """Fresh source fences around cold immutable replay, without loading models.

    ``report`` is the complete result returned by infer_shared_parent_units.
    Execution flags describe that retained attempt; validation never executes it.
    """
    shared._owners(index,registry);shared._limits(timeout_seconds,memory_mb,'source-unit-replay')
    require(type(report) is dict and set(report)=={'artifact','report','native_worker_executed','inference_executed',*FALSE}
        and all(report[k] is False for k in FALSE)
        and type(report['native_worker_executed']) is bool and type(report['inference_executed']) is bool,
        'closed source-unit result required')
    saved=report['report'];head=CodebaseHead.from_dict(saved['key']['source_head'])
    deadline=time.monotonic()+timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler,parent_lease=parent_lease,cancel_event=cancel_event,
            timeout_seconds=min(30.,timeout_seconds),memory_mb=memory_mb) as lease:
        signal=lease.combined_cancellation_signal(cancel_event)
        def observe():
            left=deadline-time.monotonic()
            require(left>0 and not signal.is_set(),'source-unit replay deadline or cancellation')
            index.observe_current(repository,expected_head=head,parent_lease=lease,cancel_event=signal,
                timeout_seconds=left,memory_mb=memory_mb)
        observe()
        actual=load_source_unit_inference(index,registry,report['artifact'],expected_head=head,
            version_id=saved['key']['version_id'],paths=saved['preparation']['paths'],embedding_snapshot=embedding_snapshot,
            max_functions=saved['preparation']['max_functions'],max_selected_units=saved['preparation']['max_selected_units'])
        require(raw(actual)==raw(saved),'retained source-unit result differs from immutable native execution')
        require(report['inference_executed']==(report['native_worker_executed']
            and any(r['candidate'] is not None for r in actual['output']['rows'])),
            'retained source-unit execution flags differ')
        del actual
        observe()
        return deepcopy(report)

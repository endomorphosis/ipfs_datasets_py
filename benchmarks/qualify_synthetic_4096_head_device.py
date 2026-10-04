"""Real CPU/CUDA execution of an untrained synthetic 4096D architecture fixture.

No Leanstral model, embeddings, service, trained checkpoint or optimizer is
opened. Positive results qualify only this fixture's numerical/device protocol.
"""
import argparse
from copy import deepcopy
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import time
import traceback


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def pin(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def write(path, value):
    with path.open('xb') as stream:
        stream.write(wire(value))
    path.chmod(0o444)
    return pin(path)


def run(output, configuration):
    output.mkdir()
    start = time.monotonic()
    result = {'schema':'native4096-synthetic-head-device-qualification/v1',
        'architecture_fixture_qualified':False,'native_leanstral_qualified':False,
        'production_qualified':False,'proof_authority':False,'execution_attestation':False,
        'scope':'untrained synthetic4096 head and owned tensor guard only',
        'encoder_calls':0,'optimizer_steps':0,'training_calls':0,'foreign_process_actions':False,
        'observed_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'error':None}
    scheduler = lease = session = torch = device = None
    states, references = {}, {}
    safe_close = True
    try:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
            resource_scheduler as resources, legal_span_4096 as head,
            legal_span_4096_device_inference as resident, legal_span_formula as span,
            legal_span_device_inference as original, legal_span_device_batch_inference as batch,
            owned_tensor_value_guard as guard)
        modules = [head,resident,span,original,batch,guard,resources]
        sources = output/'producers'
        sources.mkdir()
        result['source_pins'] = []
        for index,module in enumerate(modules):
            path=Path(module.__file__).absolute();item=pin(path)
            copy=sources/f'{index:02d}-{path.name}';copy.write_bytes(path.read_bytes());copy.chmod(0o444)
            item['retained_copy']=pin(copy);result['source_pins'].append(item)
        result['benchmark_source']=pin(Path(__file__).resolve())
        result['configuration']=pin(configuration)
        if result['configuration']['sha256'] != 'c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575':
            raise ValueError('shared configuration differs')
        settings=json.loads(configuration.read_bytes())
        scheduler=resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig(**settings['persisted_config'],
            state_path=settings['state_path'],lease_ttl_seconds=settings['lease_ttl_seconds'],
            auto_renew_leases=settings['auto_renew_leases']))
        result['resources_before']=scheduler.snapshot()
        lease=scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION,cpu_slots=2,memory_mb=2048,
            gpu_memory_mb=512,unified_memory_mb=2560,requires_gpu=True,timeout=30,
            request_id='synthetic4096-head-device-qualification')
        result['admission']=lease.to_dict()
        import torch as runtime
        torch=runtime
        if not torch.cuda.is_available():raise RuntimeError('actual CUDA required')
        torch.cuda.init();device=torch.cuda.current_device()
        result['gpu_allocated_before_owned_sessions_bytes']=torch.cuda.memory_allocated(device)
        initial_probe=torch.tensor([2.],device=f'cuda:{device}')
        if (initial_probe*initial_probe).cpu().tolist()!=[4.]:raise ValueError('actual initial CUDA kernel differs')
        del initial_probe
        torch.cuda.synchronize(device)
        result['actual_initial_cuda_kernel']=True
        result['hardware']={'torch':str(torch.__version__),'cuda_runtime':torch.version.cuda,
                            'device':torch.cuda.get_device_name(device),'device_index':device}
        def sync():torch.cuda.synchronize(device)
        def timed(function, repetitions=1):
            values=[];actual=None
            for _ in range(3):
                sync();t0=time.monotonic()
                for _ in range(repetitions):actual=function()
                sync();values.append((time.monotonic()-t0)/repetitions)
            return {'samples_seconds_per_call':values,'median_seconds':statistics.median(values),
                    'repetitions_per_sample':repetitions},actual
        texts=['Lark must retain books.']+[f'Worker{i} may publish records.' for i in range(1,32)]
        vectors=[[.0001]*4096 for _ in texts]
        for i,vector in enumerate(vectors):vector[4095]=float(i+1)/32
        rows=[{'id':f'synthetic4096-{i}','source_text':text,'latent':vector} for i,(text,vector) in enumerate(zip(texts,vectors))]
        training=[{**rows[0],'canonical_ir':{'rules':[{'actor':'Lark','modality':'O','action':'retain',
            'object':'books','conditions':[],'exceptions':[],'temporal':[]}]}}]
        context={'dimension':4096,'representation_id':'synthetic-4096-untrained-architecture-control',
                 'producer_sha256':hashlib.sha256(b'authored synthetic vectors; no encoder').hexdigest(),
                 'training_index_sha256':span.checkpoint_digest(training)}
        checkpoint=head.build_synthetic_fixture(training,context_contract=context,
            hidden_size=8,embedding_dim=4,projection_width=4,batch_size=1,seed=1729)
        checkpoint_sha=span.checkpoint_digest(checkpoint)
        adam_sha=span.checkpoint_digest(checkpoint['optimizer_state'])
        result['checkpoint']=write(output/'synthetic-untrained-checkpoint.json',checkpoint)
        result['rows']=write(output/'synthetic-inputs.json',rows)
        result['latent_adapter_shape']=[4,4096]
        result['zero_output_adapter']=True
        result['latent_conditioning_trained']=False
        def forbid(*args,**kwargs):raise AssertionError('optimizer or training forbidden during fixture qualification')
        with __import__('unittest.mock',fromlist=['patch']).patch.object(torch.optim,'Adam',forbid), \
             __import__('unittest.mock',fromlist=['patch']).patch.object(head,'train_decoder',forbid):
            baseline=head.Leanstral4096SpanDecoder(checkpoint)
            result['lanes']={}
            for optimized,label in ((False,'cpu'),(True,'cuda_batched')):
                session=resident.DeviceLeanstral4096SpanSession(checkpoint,expected_checkpoint_sha256=checkpoint_sha,
                    optimized=optimized,synthetic_unreceipted=True,scheduler=scheduler,parent_lease=lease,
                    memory_mb=1024,gpu_memory_mb=256,unified_memory_mb=1280,max_seconds=120)
                session.decode_formal_logic(texts,vectors)
                lane={'profile':session.describe(),'batches':{}}
                for count in (1,16,32):
                    reference=baseline.decode_formal_logic(texts[:count],vectors[:count])
                    timing,actual=timed(lambda:session.decode_formal_logic(texts[:count],vectors[:count]))
                    if actual['rows'] != reference['rows']:raise ValueError('synthetic4096 canonical CPU/CUDA parity differs')
                    lane['batches'][str(count)]={**timing,'result':write(output/f'head-{label}-batch{count}.json',actual),
                                               'canonical_rows_match_cpu':True}
                records=[{'tokens':span.tokenize_source(text),'latent':vector} for text,vector in zip(texts[:16],vectors[:16])]
                cpu_inputs=span._batch(torch,records)
                gpu_inputs=span._batch(session._tensor_factory,records)
                with torch.inference_mode():
                    expected=baseline.model(*cpu_inputs)
                    actual=session._model(*gpu_inputs)
                errors={key:float((actual[key].cpu()-value).abs().max()) for key,value in expected.items()}
                if max(errors.values())>5e-5:raise ValueError('synthetic4096 numeric parity exceeds5e-5')
                lane['four_logit_max_abs_errors']=errors
                lane['logits']=write(output/f'head-{label}-logits.json',
                    {key:value.detach().cpu().tolist() for key,value in actual.items()})
                del actual,expected,gpu_inputs,cpu_inputs
                result['lanes'][label]=lane
                session.close();session=None
            del baseline
        result['head_warm_speedups_cpu_over_cuda_batched']={key:
            result['lanes']['cpu']['batches'][key]['median_seconds']/
            result['lanes']['cuda_batched']['batches'][key]['median_seconds'] for key in ('1','16','32')}
        states={'adapter':torch.zeros((128,4096),device=f'cuda:{device}',dtype=torch.float32),
                'gru':torch.ones((128,128),device=f'cuda:{device}',dtype=torch.float32)}
        references={key:value.detach().clone() for key,value in states.items()}
        result['guard']={}
        for optimized,label in ((False,'cuda_reference'),(True,'cuda_combined')):
            function=lambda:guard.check_owned_tensor_values(torch,states,references,optimized=optimized)
            function();timing,actual=timed(function,repetitions=8)
            result['guard'][label]={**timing,'receipt':actual}
        result['guard']['speedup_reference_over_combined']=result['guard']['cuda_reference']['median_seconds']/result['guard']['cuda_combined']['median_seconds']
        result['guard']['native_corruption_refusals']=[]
        for corruption in ('changed_value','signed_zero','nan','inf'):
            value={'changed_value':1.,'signed_zero':-0.,'nan':float('nan'),'inf':float('inf')}[corruption]
            states['adapter'].data[0,0]=value
            for optimized in (False,True):
                try:guard.check_owned_tensor_values(torch,states,references,optimized=optimized)
                except ValueError:result['guard']['native_corruption_refusals'].append({'corruption':corruption,'optimized':optimized})
                else:raise ValueError('native CUDA tensor corruption escaped guard')
            states['adapter'].data.copy_(references['adapter']);sync()
            for optimized in (False,True):guard.check_owned_tensor_values(torch,states,references,optimized=optimized)
        states,references={},{}
        result['checkpoint_unchanged']=span.checkpoint_digest(checkpoint)==checkpoint_sha
        result['adam_unchanged']=span.checkpoint_digest(checkpoint['optimizer_state'])==adam_sha
        if not result['checkpoint_unchanged'] or not result['adam_unchanged']:raise ValueError('checkpoint/Adam changed')
        for item in result['source_pins']:
            if pin(Path(item['path']))['sha256'] != item['sha256']:raise ValueError('fixture producer source changed')
        result['architecture_fixture_qualified']=True
    except BaseException as error:
        result['error']={'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()}
    finally:
        if session is not None:
            try:session.close()
            except BaseException as error:
                safe_close=False;result['close_error']={'type':type(error).__name__,'message':str(error)}
        states,references={},{}
        gc.collect()
        if torch is not None:
            try:
                p=Path(__file__).with_name('qualify_native_768_device.py')
                s=importlib.util.spec_from_file_location('fixture_cuda_cleanup',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
                m._cleanup_owned_cuda(torch,device,result)
            except BaseException as error:
                safe_close=False;result['cuda_cleanup_error']={'type':type(error).__name__,'message':str(error)}
        if lease is not None:
            if safe_close:lease.release()
            result['own_root_lease_released']=lease.released
        if scheduler is not None:result['resources_after']=scheduler.snapshot()
        result['architecture_fixture_qualified']=result['architecture_fixture_qualified'] and safe_close
        result['elapsed_seconds']=time.monotonic()-start
        item=write(output/'result.json',result)
        print(json.dumps({'architecture_fixture_qualified':result['architecture_fixture_qualified'],
                         'result':item,'error':result['error']}))
    return 0 if result['architecture_fixture_qualified'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--configuration',type=Path,required=True);args=parser.parse_args()
    raise SystemExit(run(args.output.absolute(),args.configuration.absolute()))

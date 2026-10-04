"""Bounded head-only precision diagnostic against an exact fresh artifact.

No fitting or encoder/model service calls. This diagnostic does not qualify a
model; it compares the unchanged native CPU forward to owned CUDA forwards.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time


def main(args):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        GlobalResourceScheduler, ResourceSchedulerConfig, ResourceLane)
    config = json.loads(args.configuration.read_bytes())
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig(**config['persisted_config'],
        state_path=config['state_path'], lease_ttl_seconds=config['lease_ttl_seconds'],
        auto_renew_leases=config['auto_renew_leases']))
    args.output.mkdir()
    raw = (args.input / 'result.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == args.expected_result_sha256
    old = json.loads(raw)
    for pin in (old['head_setup']['child'], old['encoder']['cuda']['batches']['32']['result']):
        assert hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest() == pin['sha256']
    cp = json.loads((args.input / 'diagnostic-native768-head.json').read_bytes())
    embeddings = json.loads((args.input / 'encoder-cuda-batch32.json').read_bytes())
    rows = json.loads((args.input / 'source-rows.json').read_bytes())
    result = {'schema': 'native768-head-precision-diagnostic/v1', 'qualification': False,
              'input_result_sha256': args.expected_result_sha256, 'training_calls': 0,
              'embedding_calls': 0, 'comparisons': {}}
    lease = scheduler.acquire(ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1, memory_mb=1024,
        gpu_memory_mb=256, unified_memory_mb=1280, requires_gpu=True, timeout=30,
        request_id='native768-head-only-precision-diagnostic')
    session = None
    try:
        import torch
        torch.set_num_threads(1)
        torch.cuda.init()
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dims
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_device_inference import DeviceDimensionalSpanSession
        result['initial_precision'] = {'cudnn_tf32': torch.backends.cudnn.allow_tf32,
            'matmul_tf32': torch.backends.cuda.matmul.allow_tf32,
            'float32_precision': torch.get_float32_matmul_precision()}
        baseline_flags = {name: getattr(torch.backends.cudnn, name) for name in (
            'enabled', 'benchmark', 'benchmark_limit', 'deterministic', 'allow_tf32')}
        result['baseline_cudnn_flags'] = baseline_flags
        examples = [{'tokens': span.tokenize_source(row['source_text']), 'latent': vector}
                    for row, vector in zip(rows[:16], embeddings['vectors'][:16])]
        with torch.random.fork_rng(devices=[torch.cuda.current_device()]):
            native = dims.DimensionalSpanDecoder(cp)
        with torch.inference_mode():
            expected = native.model(*span._batch(torch, examples))
        session = DeviceDimensionalSpanSession(cp, expected_checkpoint_sha256=span.checkpoint_digest(cp),
            scheduler=scheduler, parent_lease=lease, unified_memory_mb=1280)
        def flatten(value):
            return [x for part in value for x in flatten(part)] if isinstance(value,list) else [value]
        for label, flags in (('default', {}), ('cudnn_tf32_false', {'allow_tf32': False}),
                              ('cudnn_disabled', {'enabled': False})):
            t0=time.monotonic()
            selected = {**baseline_flags, **flags}
            with torch.backends.cudnn.flags(**selected), torch.inference_mode():
                output=session._model(*span._batch(session._tensor_factory, examples))
                torch.cuda.synchronize()
            errors={name: max(abs(a-b) for a,b in zip(flatten(expected[name].tolist()),
                        flatten(output[name].cpu().tolist()))) for name in expected}
            result['comparisons'][label]={'max_abs_errors':errors,'elapsed_seconds':time.monotonic()-t0,
                                         'actual_flags': selected}
            del output
        session.close()
        session=None
        result['gpu_allocated_after_close']=torch.cuda.memory_allocated()
        torch.cuda.empty_cache()
        result['gpu_allocated_after_empty_cache']=torch.cuda.memory_allocated()
        if hasattr(torch._C,'_cuda_clearCublasWorkspaces'):
            torch._C._cuda_clearCublasWorkspaces()
            torch.cuda.synchronize()
            result['gpu_allocated_after_clear_cublas_workspaces']=torch.cuda.memory_allocated()
        result['final_precision']={'cudnn_tf32':torch.backends.cudnn.allow_tf32,
            'matmul_tf32':torch.backends.cuda.matmul.allow_tf32,
            'float32_precision':torch.get_float32_matmul_precision()}
    finally:
        if session is not None:
            session.close()
        lease.release()
        result['own_lease_released']=lease.released
        result['resources_after']=scheduler.snapshot()
        path=args.output/'result.json'
        path.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
        path.chmod(0o444)
        print(json.dumps(result,sort_keys=True),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--expected-result-sha256',required=True)
    p.add_argument('--configuration',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    main(p.parse_args())

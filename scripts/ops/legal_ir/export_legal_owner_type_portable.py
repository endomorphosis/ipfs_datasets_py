#!/usr/bin/env python3
"""Verify original checkpoints, export data-only tensors, and replay after relocation.

Publication belongs to a separate explicitly authorized caller. This script
does not contact Hugging Face or change original checkpoints/producer checks.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['OMP_NUM_THREADS'] = '1'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_owner_type_portable as portable


def reference(path):
    p = Path(path); raw = p.read_bytes()
    return {'path': str(p.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def read(ref):
    actual = reference(ref['path'])
    portable.require(all(actual[k] == ref[k] for k in actual), 'authenticated input differs')
    return portable._read_json(Path(ref['path']).read_bytes())


def write(path, value):
    with Path(path).open('xb') as stream: stream.write(portable.canonical(value) + b'\n')
    return reference(path)


def export_checkpoint(checkpoint_ref, destination):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_paired_temporal_ownership as paired
    from safetensors.torch import save
    cp = read(checkpoint_ref)
    source_owner = cp['parent'] if cp['schema'] == paired.SCHEMA else cp
    portable.require(source_owner['config']['arm'] in ('finetune_occurrence', 'frozen_occurrence'), 'query-agnostic source-only head is not this export profile')
    portable.require(all(cp['model_config'].get(k) == v for k,v in {'embedding_dim':16,'hidden_size':32,'latent_dimension':0}.items()), 'unsupported source encoder profile')
    if cp['schema'] == paired.SCHEMA:
        torch, original, _ = paired._restore(cp)
    else:
        torch, original, _ = paired.previous._restore(cp)
    # Original restore performs all nested producer/config/provenance checks.
    needed = portable._model(torch).state_dict()
    state = original.state_dict()
    portable.require(all(k in state and tuple(state[k].shape) == tuple(v.shape) for k,v in needed.items()), 'source inference tensor mismatch')
    tensors = {k: state[k].detach().cpu().contiguous().clone() for k in needed}
    dest = Path(destination); dest.mkdir(parents=True, exist_ok=False)
    payload = save(tensors)
    (dest / 'weights.safetensors').write_bytes(payload)
    manifest = {'schema': portable.SCHEMA, 'config': portable.CONFIG,
                'environment': {'torch_version': str(torch.__version__), 'inference_threads': 1, 'device': 'cpu'},
                'weights': {'filename': 'weights.safetensors', 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(),
                            'tensors': {k: {'shape': list(v.shape), 'dtype': 'float32'} for k,v in tensors.items()}},
                'source_checkpoint': {k: checkpoint_ref[k] for k in ('sha256','bytes')} | {'schema': cp['schema']},
                'loader_sha256': reference(portable.__file__)['sha256'], 'authority': portable.FALSE}
    result = write(dest / 'manifest.json', manifest)
    return {'manifest': result, 'weights': reference(dest/'weights.safetensors'), 'source_checkpoint': checkpoint_ref,
            'inference_tensors': len(tensors), 'inference_parameters': sum(v.numel() for v in tensors.values()),
            'original_strict_restore_passed': True, 'original_checkpoint_unchanged': reference(checkpoint_ref['path']) == {k:checkpoint_ref[k] for k in ('path','sha256','bytes')}}


def run(generation_path, output, relocated):
    generation_ref = reference(generation_path); generation = read(generation_ref)
    dest, moved = Path(output), Path(relocated)
    dest.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(portable.__file__, dest/'owner_type_loader.py')
    checkpoints = {row['checkpoint']['sha256']: row['checkpoint'] for row in generation['logical_generations']}
    exports = {sha: export_checkpoint(ref, dest/'models'/sha) for sha,ref in sorted(checkpoints.items())}
    write(dest/'bundle-manifest.json', {'schema':'legal-owner-type-portable-bundle/v1',
          'loader': {'filename':'owner_type_loader.py','sha256':reference(dest/'owner_type_loader.py')['sha256']},
          'models': {sha:{'manifest':'models/'+sha+'/manifest.json','manifest_sha256':row['manifest']['sha256']} for sha,row in exports.items()},
          'scope':'owner TYPE only; manual local loader; no remote serialized code; no gate override'})
    (dest/'README.md').write_text('''# Portable temporal owner-type research heads

These data-only safetensors exports classify a supplied time occurrence as norm,
condition, exception or ambiguous. They do not locate the owner occurrence,
produce formal logic, verify statutory meaning, or change existing gates.
The fixed confidence threshold is 0.8; ambiguous predictions always defer.

Use Python 3.12 with torch 2.13.0+cu130 (CPU execution) and safetensors.
The exact environment used for verification is recorded in the export receipt.
Authenticate the Hub commit, bundle/manifest hashes and loader source before
manually copying/importing this loader. No `trust_remote_code` or pickle is used.

```python
from owner_type_loader import PortableOwnerType
model = PortableOwnerType("models/<original-checkpoint-sha256>",
    expected_manifest_sha256="<pinned-manifest-sha256>")
rows = model.predict_many([{"id": "opaque-query", "source_text": source,
    "source_sha256": source_sha256,
    "proposed_time_span": {"char_start": start, "char_end": end}}])
```

Offsets are Python character offsets, end-exclusive and token-aligned. Inputs
contain no labels or owner spans. A maximum 64 queries per call, 256 tokens per
source, 16,384 characters and 2,048 UTF-8 bytes per casefolded token is enforced;
no truncation occurs. Bounded parity was checked at the original 48-query batch
policy; identical results across different platforms/batch policies are not
asserted. This inference export has no optimizer and cannot resume training.
Raw checkpoint archives preserve training provenance separately. No new license
grant for inherited weights is made; source licensing remains separately bound.
''')
    shutil.copytree(dest, moved)
    spec = importlib.util.spec_from_file_location('relocated_owner_loader', moved/'owner_type_loader.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    models = {sha: module.PortableOwnerType(moved/'models'/sha, expected_manifest_sha256=row['manifest']['sha256']) for sha,row in exports.items()}
    reports = []; total_rows = total_batches = 0
    for item in generation['executed_generations']:
        saved = read(item['generation']); sources = read(saved['sources'])
        if isinstance(sources, dict): sources = sources['rows']
        sha = saved['model']['checkpoint']['sha256']; model = models[sha]
        actual = []
        for offset in range(0, len(sources), 48): actual.extend(model.predict_many(sources[offset:offset+48]))
        portable.require(actual == saved['rows'], 'relocated exact prediction parity failed: '+item['generation']['path'])
        batches = (len(sources)+47)//48; total_rows += len(sources); total_batches += batches
        reports.append({'saved_generation':item['generation'], 'sources':saved['sources'], 'checkpoint_sha256':sha,
                        'rows':len(sources),'encoder_batch_forwards':batches,'all_output_fields_bit_exact':True,
                        'predictions_sha256':hashlib.sha256(portable.canonical(actual)).hexdigest()})
    import torch, safetensors, platform
    result = {'schema':'legal-owner-type-portable-export-receipt/v1', 'generation_freeze':generation_ref,
              'producer':reference(__file__), 'loader':reference(portable.__file__), 'exported_models':exports,
              'bundle_manifest':reference(dest/'bundle-manifest.json'), 'relocated_directory':str(moved.resolve()),
              'unique_checkpoints':len(exports),'physical_generation_files':len(reports),'query_rows':total_rows,
              'encoder_batch_forwards':total_batches,'parity':reports,'all_exact':True,
              'original_restore_model_forwards':0,'optimizer_updates':0,'remote_calls':0,
              'environment':{'python':platform.python_version(),'torch':str(torch.__version__),'safetensors':safetensors.__version__},
              'limits':'bounded saved source/query parity, not all inputs or statutory/latent qualification',**portable.FALSE}
    return write(dest.parent/'portable-export-receipt.json', result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--generation-freeze',required=True)
    parser.add_argument('--output',required=True); parser.add_argument('--relocated',required=True)
    args=parser.parse_args(); print(json.dumps(run(args.generation_freeze,args.output,args.relocated)),flush=True)

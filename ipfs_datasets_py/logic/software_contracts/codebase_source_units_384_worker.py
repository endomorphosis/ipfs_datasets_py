"""Isolated CPU GTE + shared384D decoder; no source imports or training."""
from __future__ import annotations
from contextlib import redirect_stdout
import json
import os
import sys
from importlib.metadata import version as package_version


def execute(request):
    from . import codebase_source_units_384 as owner
    from ..formalization.autoencoder import source_embeddings_384 as embeddings
    from ..formalization.autoencoder import structured_source_384 as decoder
    from ..formalization.autoencoder.source_program_runtime_384 import SourceProgramDecoder384
    from ...optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
    import torch
    owner.require(set(request)=={'schema','key','checkpoint','rows'} and request['schema']==owner.WORKER_SCHEMA,
        'closed source-unit worker request required')
    key=request['key'];rows=request['rows']
    owner.require(key['python']==sys.version and key['runtime_versions']=={
        n:package_version(n) for n in ('torch','numpy','transformers','sentence-transformers','tokenizers')},
        'source-unit native runtime versions differ')
    owner.require(key['producer']==owner.pins() and key['device']=='cpu'
        and os.environ.get('CUDA_VISIBLE_DEVICES')=='' and not torch.cuda.is_available(),
        'exact source-unit producer and explicit CPU profile required')
    owner.require(owner.sha(owner.raw(request['checkpoint']))==key['runtime_checkpoint_sha256'],
        'source-unit checkpoint differs')
    owner.require(type(rows) is list and len(rows)<=128 and all(type(r) is dict and set(r)=={'id','source_text'}
        and type(r['id']) is str and type(r['source_text']) is str and 0<len(r['source_text'])<=32768 for r in rows)
        and len({r['id'] for r in rows})==len(rows),'bounded target-free normalized source rows required')
    snapshot,assets=producer._snapshot_assets(key['embedding_snapshot'])
    owner.require(assets==key['embedding_assets'],'source-unit embedding assets differ')
    embeddings.clear_embedding_cache();old_threads=torch.get_num_threads();torch.set_num_threads(1)
    result=[];eligible=[]
    try:
        if rows:
            with embeddings._MODEL_LOCK:
                model=embeddings._cached_model(snapshot,'cpu',torch,producer,assets)
                for row in rows:
                    count=len(model.tokenizer(row['source_text'],add_special_tokens=True,truncation=False)['input_ids'])
                    item=dict(id=row['id'],source_sha256=owner.sha(row['source_text'].encode()),tokens=count,
                        status='deferred_gte_token_limit',embedding=None,candidate=None)
                    result.append(item)
                    if count<=producer.MAX_TOKENS:eligible.append((row,item))
            if eligible:
                vectors=embeddings.embed_texts([r['source_text'] for r,_ in eligible],snapshot_path=snapshot)
                runtime=SourceProgramDecoder384(decoder.Runtime(request['checkpoint']),
                    checkpoint_sha256=key['runtime_checkpoint_sha256'])
                predictions=runtime.infer([dict(**r,embedding=v) for (r,_),v in zip(eligible,vectors)])['rows']
                owner.require(len(predictions)==len(eligible),'source-unit decoder omitted predictions')
                for (_,item),vector,prediction in zip(eligible,vectors,predictions):
                    item.update(status='decoded_unverified_candidate',embedding=vector,candidate=prediction)
        owner.require(producer._snapshot_assets(snapshot)[1]==assets and key['producer']==owner.pins(),
            'source-unit inference producer or embedding assets changed')
        return dict(schema=owner.WORKER_SCHEMA,key=key,rows=result,model_loads=int(bool(rows)),**owner.FALSE)
    finally:
        embeddings.clear_embedding_cache();torch.set_num_threads(old_threads)


def main():
    sys.path[:0]=json.loads(sys.argv[1])
    with redirect_stdout(sys.stderr):
        from ipfs_datasets_py.logic.software_contracts import codebase_source_units_384 as owner
        from ipfs_datasets_py.logic.software_contracts.codebase_source_units_384_worker import execute as run
        data=sys.stdin.buffer.read(owner.MAX_BYTES+1)
        owner.require(len(data)<=owner.MAX_BYTES,'source-unit input exceeds bound')
        output=owner.raw(run(json.loads(data)))
        owner.require(len(output)<=owner.MAX_BYTES,'source-unit output exceeds bound')
    sys.stdout.buffer.write(output)


if __name__=='__main__':main()

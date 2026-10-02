"""Isolated CPU pages using the existing private GTE/384D decoder cache."""
from __future__ import annotations
from contextlib import redirect_stdout
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sys
import time


def execute(request):
    from . import codebase_resident_inference as owner
    from ..formalization.autoencoder import structured_source_384 as decoder
    from ..formalization.autoencoder import source_embeddings_384 as embeddings
    from ..formalization.autoencoder.source_program_runtime_384 import SourceProgramDecoder384
    from ...optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
    from importlib.metadata import version as package_version
    import torch
    owner.require(set(request)=={'schema','producer','key','checkpoint','pages'},'closed resident inference request required')
    owner.require(request['schema']==owner.REQUEST_SCHEMA and request['producer']==owner.pins(),'exact resident producer required')
    key=request['key'];checkpoint=request['checkpoint']
    owner.require(key['python']==sys.version and key['runtime_versions']=={
        name:package_version(name) for name in ('torch','numpy','transformers','sentence-transformers','tokenizers')},
        'resident runtime versions differ from the admitted process')
    owner.require(key['device']=='cpu' and os.environ.get('CUDA_VISIBLE_DEVICES')=='' and not torch.cuda.is_available(),
                  'explicit CPU model profile requires CUDA opt-out before loading torch')
    owner.require(owner.sha(owner.raw(checkpoint))==key['checkpoint_sha256'],'resident checkpoint differs')
    snapshot,assets=producer._snapshot_assets(key['embedding_snapshot'])
    owner.require(assets==key['embedding_assets'],'exact resident embedding assets required')
    pages=request['pages'];owner.require(type(pages) is list and 1<=len(pages)<=16,'bounded nonempty inference page set required')
    owner.require(key['mode'] in ('resident','cold_per_page'),'explicit model residency mode required')
    owner.require(type(key['batch_size']) is int and 1<=key['batch_size']<=16,'bounded native batch size required')
    embeddings.clear_embedding_cache()
    old_threads=torch.get_num_threads();torch.set_num_threads(1)
    records=[];seen=set();runtime=None;loads=0;started=time.monotonic()
    def infer_page(page):
        nonlocal runtime,loads
        begin=time.monotonic();rows=page['rows']
        owner.require(type(rows) is list and len(rows)<=16,'bounded complete source page required')
        if key['mode']=='cold_per_page':
            embeddings.clear_embedding_cache();runtime=None;gc.collect()
        result=[];eligible=[];model=None;load_seconds=0.
        for row in rows:
            owner.require(set(row)=={'ordinal','path','source_cid','source_sha256','source_text'},'target-free source row required')
            text=row['source_text'];owner.require(type(text) is str and 0<len(text.encode())<=65536,'bounded source text required')
            owner.require(row['ordinal'] not in seen and owner.sha(text.encode())==row['source_sha256'],'unique exact captured source required')
            seen.add(row['ordinal'])
            from .content import cid_for_bytes
            owner.require(cid_for_bytes(text.encode())==row['source_cid'],'source CID differs')
            base={k:row[k] for k in ('ordinal','path','source_cid','source_sha256')}
            if len(text)>32768:
                result.append(dict(**base,status='deferred_source_character_limit',candidate=None));continue
            if model is None:
                before=time.monotonic()
                with embeddings._MODEL_LOCK:
                    cache_key=(os.getpid(),str(snapshot),'cpu')
                    was_loaded=cache_key in embeddings._MODEL_CACHE
                    model=embeddings._cached_model(snapshot,'cpu',torch,producer,assets)
                if not was_loaded:loads+=1
                load_seconds+=time.monotonic()-before
            tokens=model.tokenizer(text,add_special_tokens=True,truncation=False)['input_ids']
            if len(tokens)>producer.MAX_TOKENS:
                result.append(dict(**base,status='deferred_gte_token_limit',tokens=len(tokens),candidate=None));continue
            eligible.append((row,base))
        embedded=[]
        if eligible:
            # Reuse the existing validated model and its explicit batching API.
            # The producer's native encode path is identical to embed_texts;
            # only its already-supported batch-size argument is selected here.
            with torch.inference_mode():
                vectors=model.encode([r['source_text'] for r,_ in eligible],batch_size=key['batch_size'],
                    convert_to_numpy=True,normalize_embeddings=True,show_progress_bar=False).tolist()
            owner.require(type(vectors) is list and len(vectors)==len(eligible)
                and all(type(v) is list and len(v)==384 and all(type(x) in (int,float) and math.isfinite(x) for x in v)
                        for v in vectors),'native encoder must return exactly one finite 384D vector per source')
            if runtime is None:
                runtime=SourceProgramDecoder384(decoder.Runtime(checkpoint),checkpoint_sha256=key['checkpoint_sha256'])
            decoded=runtime.infer([dict(id=str(r['ordinal']),source_text=r['source_text'],embedding=v) for (r,_),v in zip(eligible,vectors)])
            predictions={r['id']:r for r in decoded['rows']}
            owner.require(len(predictions)==len(eligible),'decoder omitted or duplicated source rows')
            for (row,base),vector in zip(eligible,vectors):
                feature=dict(source_sha256=row['source_sha256'],embedding=vector,
                    embedding_sha256=owner.sha(owner.raw(vector)),assets_sha256=owner.sha(owner.raw(assets)))
                embedded.append(feature)
                result.append(dict(**base,status='decoded_unverified_candidate',candidate=predictions[str(row['ordinal'])],
                    feature_sha256=owner.sha(owner.raw(feature))))
        _,after=producer._snapshot_assets(snapshot)
        owner.require(after==assets,'resident model assets changed during a page')
        return dict(page_ordinal=page['page_ordinal'],page_cid=page['page_cid'],rows=sorted(result,key=lambda r:r['ordinal']),
            features=embedded,elapsed_seconds=time.monotonic()-begin,model_lookup_seconds=load_seconds,
            decoded_rows=len(eligible),source_rows=len(rows),cached_models=len(embeddings._MODEL_CACHE))
    try:
        for page in pages:records.append(infer_page(page))
        owner.require(request['producer']==owner.pins(),'resident worker producer changed')
        return dict(schema=owner.WORKER_SCHEMA,key=key,pages=records,producer=owner.pins(),device='cpu',
            elapsed_seconds=time.monotonic()-started,model_loads=loads,maximum_resident_models=embeddings._MAX_CACHED_MODELS,
            peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            inputs_truncated=False,targets_used_for_inference=False,**owner.FALSE)
    finally:
        embeddings.clear_embedding_cache();torch.set_num_threads(old_threads)


def main():
    sys.path[:0]=json.loads(sys.argv[1])
    with redirect_stdout(sys.stderr):
        # Executed as an isolated file: import the package owner after roots.
        from ipfs_datasets_py.logic.software_contracts import codebase_resident_inference as owner
        from ipfs_datasets_py.logic.software_contracts.codebase_resident_inference_worker import execute as run
        raw=sys.stdin.buffer.read(owner.MAX_BYTES+1)
        owner.require(len(raw)<=owner.MAX_BYTES,'resident input exceeds bound')
        output=owner.raw(run(json.loads(raw)))
        owner.require(len(output)<=owner.MAX_BYTES,'resident output exceeds bound')
    sys.stdout.buffer.write(output)


if __name__=='__main__':main()

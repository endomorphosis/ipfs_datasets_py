"""Revision-pinned, verified HF reads, one owned source shard at a time; no HF cache writes."""
import hashlib, re
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_url, get_token
import requests

def specs(repo, paths, revision=None, api=None):
    api=api or HfApi()
    revision=revision or api.repo_info(repo,repo_type='dataset').sha
    if not re.fullmatch('[0-9a-f]{40}',revision): raise ValueError('immutable 40-hex revision required')
    info=api.get_paths_info(repo,paths=list(paths),repo_type='dataset',revision=revision)
    found={x.path:x for x in info}
    result=[]
    for path in sorted(paths):
        x=found.get(path); lfs=getattr(x,'lfs',None)
        sha=lfs.get('sha256') if isinstance(lfs,dict) else getattr(lfs,'sha256',None)
        size=getattr(x,'size',None)
        if not sha or size is None: raise ValueError('Missing LFS hash/size for '+path)
        result.append(dict(path=path,size=size,sha256=sha))
    return revision,result

def fetch(repo,revision,spec,path,guard,session=None,token=None):
    """Caller owns path; remove incomplete file on every failure. Never touches HF cache."""
    if not re.fullmatch('[0-9a-f]{40}',revision): raise ValueError('immutable revision required')
    path=Path(path)
    if path.exists(): raise FileExistsError(path)
    guard.check(spec['size']) # reserve whole shard BEFORE requesting bytes
    session=session or requests
    url=hf_hub_url(repo,spec['path'],repo_type='dataset',revision=revision)
    headers={'Authorization':'Bearer '+token} if token else {}
    n=0; digest=hashlib.sha256()
    try:
        with session.get(url,headers=headers,stream=True,timeout=(20,90)) as response:
            response.raise_for_status()
            with guard.open(path) as out:
                for b in response.iter_content(chunk_size=1024**2):
                    if not b: continue
                    if n+len(b)>spec['size']: raise ValueError('source exceeds metadata size')
                    out.write(b); digest.update(b); n+=len(b)
        if n!=spec['size'] or digest.hexdigest()!=spec['sha256']:
            raise ValueError('source SHA256/size verification failed')
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise

def sources(repo,paths,root,guard,stats,revision=None,api=None,session=None,token=None):
    revision,items=specs(repo,paths,revision,api)
    print('US_SOURCE revision',revision,flush=True)
    token=get_token() if token is None else token
    owned=Path(root)/'owned_source.parquet'
    for item in items:
        fetch(repo,revision,item,owned,guard,session,token)
        stats['us_source_shards_verified']=stats.get('us_source_shards_verified',0)+1
        stats['us_source_bytes_verified']=stats.get('us_source_bytes_verified',0)+item['size']
        print('US_SOURCE verified',item['path'],item['size'],flush=True)
        try: yield owned
        finally: owned.unlink(missing_ok=True)

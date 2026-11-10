#!/usr/bin/env python3
"""Offline normalize/structure job (NO network). Streaming gz line-by-line, resumes by chunk, atomic outputs, sources never touched.
  nl : scan/*.jsonl.gz + rescan_bom/*.jsonl.gz -> normalized/nl_municipal/<chunk>.jsonl.gz   (dedupe by id; rescan_bom record wins over scan stub;
       real record wins over manifest_parse_fail/stop stubs). Output = normalized index record (id, status, jur, dates, creator, rtype, counts).
  cz : t2/index/laws_shards/*.jsonl.gz (+t1 shards) -> normalized/cz_sbirkapp/<shard>.jsonl.gz  (NFC text, whitespace-collapsed, sha256 of text, article stats; dedupe by law id)
Run: MALLOC_ARENA_MAX=2 nice -n 19 ionice -c3 python normalize_offline.py {nl|cz} [--limit N] [--out DIR]
Guards: refuses to start if MemAvail < 3584; self-checks RSS every 500 lines (cap 200MB -> exit 4, resumable); pauses if MemAvail < 3584; STOP file normalized/STOP_NORM.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, gzip, json, glob, hashlib, unicodedata, re, time, resource
R='{_CORPORA}'; OUT=f'{R}/normalized'; RSS_CAP=200
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable'): return int(l.split()[1])//1024
def rss():
    for l in open('/proc/self/status'):
        if l.startswith('VmRSS'): return int(l.split()[1])//1024
def gate(n):
    if os.path.exists(f'{OUT}/STOP_NORM'): print('STOP_NORM present; exiting clean'); sys.exit(0)
    if n%500==0:
        if rss()>RSS_CAP: print('RSS cap exceeded',rss()); sys.exit(4)
        t=time.time()
        while memavail()<3584:
            if os.path.exists(f'{OUT}/STOP_NORM') or time.time()-t>900: print('mem pause exit'); sys.exit(5)
            time.sleep(5)
def aw(path, lines):
    tmp=path+'.tmp'
    with gzip.open(tmp,'wt',encoding='utf-8',compresslevel=6) as f:
        for l in lines: f.write(l)
    os.replace(tmp,path)
RANK={'ok':5,'in_force_no_text_in_xml':4,'expired':3,'future_only':3,'in_force_out_of_scope':3,'absent':2}
def nl_norm(d):
    s=d.get('s')
    o=dict(id=d['id'],status=s)
    for k in ('creator','scheme','jur','auth','atype','rtype','rubriek','inw','uit','n_article','n_annex','n_section','oper_chars','title'):
        if d.get(k) is not None: o[k]=d[k]
    if d.get('rescan'): o['rescan']=d['rescan']
    return o
def run_nl(limit,out):
    out=out or f'{OUT}/nl_municipal'; os.makedirs(out,exist_ok=True)
    chunks={}
    for sub in ('scan','rescan_bom'):
        for f in glob.glob(f'{R}/nl_municipal/index/{sub}/*.jsonl.gz'):
            chunks.setdefault(os.path.basename(f),[]).append((sub,f))
    done=0; n=0
    for name in sorted(chunks, reverse=True):
        dst=f'{out}/{name}'
        # resume by chunk: skip if output newer than all sources
        if os.path.exists(dst) and os.path.getmtime(dst)>=max(os.path.getmtime(f) for _,f in chunks[name]): continue
        recs={}
        for sub,f in chunks[name]:
            try:
                with gzip.open(f,'rt',encoding='utf-8-sig') as fh:
                    for l in fh:
                        n+=1; gate(n)
                        try: d=json.loads(l.lstrip('\ufeff'))
                        except Exception: continue
                        i=d.get('id'); 
                        if i is None: continue
                        r=(RANK.get(d.get('s'),1), 1 if sub=='rescan_bom' else 0)
                        if i not in recs or r>=recs[i][0]: recs[i]=(r,nl_norm(d))
            except (EOFError,OSError) as e: print('skip unreadable',f,e)
        aw(dst,(json.dumps(v[1],ensure_ascii=False,separators=(',',':'))+'\n' for _,v in sorted(recs.items(),reverse=True)))
        done+=1
        if limit and done>=limit: break
    print('nl chunks written',done,'lines',n,'peak_rss_mb',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024)
WS=re.compile(r'[ \t\u00a0]+'); NL3=re.compile(r'\n{3,}')
def clean(t):
    if not isinstance(t,str): return t
    t=unicodedata.normalize('NFC',t).replace('\r\n','\n').replace('\r','\n'); t=WS.sub(' ',t)
    return NL3.sub('\n\n',t).strip()
def run_cz(limit,out):
    out=out or f'{OUT}/cz_sbirkapp'; os.makedirs(out,exist_ok=True)
    seen=set(); done=0; n=0
    files=sorted(glob.glob(f'{R}/cz_sbirkapp/t2/index/laws_shards/*.jsonl.gz')+glob.glob(f'{R}/cz_sbirkapp/t1/index/laws_shards/*.jsonl.gz'))
    for f in files:
        dst=f'{out}/{os.path.basename(f)}'
        # ids from already-normalized shards still feed the dedupe set (streamed ids only)
        if os.path.exists(dst) and os.path.getmtime(dst)>=os.path.getmtime(f):
            with gzip.open(dst,'rt',encoding='utf-8') as fh:
                for l in fh:
                    try: seen.add(json.loads(l)['law']['id'])
                    except Exception: pass
            continue
        tmp=dst+'.tmp'
        with gzip.open(f,'rt',encoding='utf-8') as fh, gzip.open(tmp,'wt',encoding='utf-8',compresslevel=6) as oh:
            for l in fh:
                n+=1; gate(n)
                try: d=json.loads(l)
                except Exception: continue
                law=d.get('law') or {}; lid=law.get('id')
                if lid in seen: continue
                seen.add(lid)
                law['text']=clean(law.get('text')); law['text_sha256']=hashlib.sha256((law['text'] or '').encode()).hexdigest()
                arts=d.get('articles') or []
                for a in arts: a['text']=clean(a.get('text'))
                law['article_count_norm']=len(arts); law['text_chars']=len(law['text'] or '')
                oh.write(json.dumps(dict(law=law,articles=arts),ensure_ascii=False,separators=(',',':'))+'\n')
        os.replace(tmp,dst); done+=1
        if limit and done>=limit: break
    print('cz shards written',done,'lines',n,'peak_rss_mb',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024)
if __name__=='__main__':
    a=sys.argv; lim=int(a[a.index('--limit')+1]) if '--limit' in a else 0; out=a[a.index('--out')+1] if '--out' in a else None
    if memavail()<3584: print('REFUSED MemAvail low'); sys.exit(3)
    {'nl':run_nl,'cz':run_cz}[a[1]](lim,out)

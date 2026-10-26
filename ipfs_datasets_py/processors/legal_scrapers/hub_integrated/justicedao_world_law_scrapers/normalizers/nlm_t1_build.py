#!/usr/bin/env python3
"""NL-M tranche 1 OFFLINE build (CoS option A, 2026-10-14): ids 600000..767599 = index/scan overlaid by index/rescan_bom (rescan wins).
Sources per ok id: packed shard (index/out_packed) | out/ loose (rescan + others) | in-memory rebuild from cached raw (collector helpers, network disabled).
Never writes into out/, raw/, index/scan or the PIN. No network, no Hub push. Writes hf-staging/ipfs_netherlands_municipal_laws_tranche1_<ts>/data/{laws,articles}.parquet
Mem: start only if MemAvail>=5000MB; pause while <4500 (max 15 min); abort <3600 or own RSS >300MB."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, gzip, json, glob, time, datetime, collections, resource, importlib.util, random
import pyarrow as pa, pyarrow.parquet as pq
B='{_CORPORA}/nl_municipal'; LO=600000
spec=importlib.util.spec_from_file_location('nlc','/workspace/scripts/nl_municipal_collect.py'); C=importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
def nonet(*a,**k): raise RuntimeError('network disabled')
C.F.get=nonet
LAW_SCHEMA=pa.schema([(c, pa.int32() if c=='article_count' else pa.string()) for c in ['id','title','text','source_url','source_type','jurisdiction','country','language','eli','date','date_issued','retrieved_at','license','law_status','identifier','official_identifier','article_count','json_path','metadata_json']])
ART_SCHEMA=pa.schema([(c, pa.string()) for c in ['law_id','id','title','text','source_url','document_number','article_number','record_type','metadata_json']])
def mem():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1])//1024
def rss():
    for l in open('/proc/self/status'):
        if l.startswith('VmRSS:'): return int(l.split()[1])//1024
def log(*x): print(time.strftime('%H:%M:%S'), *x, flush=True)
def guard():
    m=mem(); r=rss()
    if r>300: log('ABORT rss',r); sys.exit(5)
    if m<3600: log('ABORT memavail',m); sys.exit(3)
    w=0
    while m<4500:
        if w>=900: log('ABORT memavail stayed <4500 for 15min',m); sys.exit(3)
        time.sleep(10); w+=10; m=mem()
        if m<3600: log('ABORT memavail',m); sys.exit(3)
    if w: log('paused',w,'s mem',m)
if mem()<5000: log('START REFUSED memavail',mem()); sys.exit(2)
st={}; resc=set(); scanrow={}
for p in sorted(glob.glob(f'{B}/index/scan/*.jsonl.gz')):
    if int(os.path.basename(p).split('.')[0])<LO: continue
    with gzip.open(p,'rt') as f:
        for l in f:
            r=json.loads(l)
            if r['id']>=LO:
                st[r['id']]=r['s']
                if r['s']=='ok': scanrow[r['id']]=(r.get('expr'),r.get('auth'),r.get('jur'),r.get('atype'),r.get('rows'))
for p in sorted(glob.glob(f'{B}/index/rescan_bom/*.jsonl.gz')):
    with gzip.open(p,'rt') as f:
        for l in f:
            r=json.loads(l)
            if r['id']>=LO:
                st[r['id']]=r['s']; resc.add(r['id'])
                if r['s']=='ok': scanrow[r['id']]=(r.get('expr'),r.get('auth'),r.get('jur'),r.get('atype'),r.get('rows'))
                else: scanrow.pop(r['id'],None)
ok=set(i for i,s in st.items() if s=='ok')
ts=time.strftime('%Y%m%dT%H%M%S'); S=f'{_CORPORA}/hf-staging/ipfs_netherlands_municipal_laws_tranche1_{ts}'; os.makedirs(f'{S}/data'); os.makedirs(f'{S}/scrapers')
lw=pq.ParquetWriter(f'{S}/data/laws.parquet',LAW_SCHEMA,compression='zstd'); aw=pq.ParquetWriter(f'{S}/data/articles.parquet',ART_SCHEMA,compression='zstd')
LB=[];AB=[]; done=set(); src=collections.Counter(); bad=[]; skip=collections.Counter(); skipped=[]; artn=0; rt=collections.Counter(); emptyart=0
atype=collections.Counter(); jur=collections.Counter(); arts_by_type=collections.Counter(); dates=[]
def flush(force=False):
    if LB and (force or len(LB)>=200): lw.write_table(pa.Table.from_pylist(LB,schema=LAW_SCHEMA)); LB.clear()
    if AB and (force or len(AB)>=2000): aw.write_table(pa.Table.from_pylist(AB,schema=ART_SCHEMA)); AB.clear(); guard()
def emit(i, law, arts, how):
    global artn, emptyart
    if i in done: bad.append(f'dup {i}'); return
    done.add(i); law=dict(law); law['article_count']=int(law.get('article_count') or 0)
    if law['article_count']!=len(arts): bad.append(f'article_count {i} {law["article_count"]}!={len(arts)}')
    LB.append({k:(None if law.get(k) is None else (law[k] if k=='article_count' else str(law[k]))) for k in LAW_SCHEMA.names})
    for a in arts:
        AB.append({k:(None if a.get(k) is None else str(a[k])) for k in ART_SCHEMA.names}); rt[a.get('record_type')]+=1
        if not (a.get('text') or '').strip(): emptyart+=1
    artn+=len(arts); src[how]+=1; sr=scanrow.get(i); t=sr[3] if sr else None
    atype[t]+=1; arts_by_type[t]+=len(arts); jur[law.get('jurisdiction')]+=1
    if law.get('date'): dates.append(law['date'])
    flush()
# 1) packed shards (non-rescan ok ids)
man=json.load(open(f'{B}/index/out_packed/manifest.json'))
for name in man['shards']:
    with gzip.open(f'{B}/index/out_packed/{name}','rt') as f:
        for l in f:
            r=json.loads(l); i=int(r['id'][4:]) if isinstance(r['id'],str) else int(r['id'])
            if i in ok and i not in resc: emit(i, r['law'], r['articles'], 'packed')
    log('shard',name,'laws',len(done),'arts',artn,'mem',mem(),'rss',rss())
# 2) out/ loose and 3) raw rebuild
C.AUTH=C.Authorities(); today=datetime.date.today().isoformat()
rest=sorted(ok-done, reverse=True); log('rest',len(rest))
for n,i in enumerate(rest,1):
    lid=f'CVDR{i}'; pl=C.OUTL/f'{lid}.json.gz'; pa_=C.OUTA/f'{lid}.jsonl.gz'
    if pl.exists() and pa_.exists():
        try:
            law=json.loads(gzip.decompress(pl.read_bytes()))
            with gzip.open(pa_,'rt',encoding='utf-8') as f: arts=[json.loads(x) for x in f]
            emit(i, law, arts, 'rescan_out' if i in resc else 'out_loose'); continue
        except Exception as e: bad.append(f'out_read {i} {e!r}'[:200])
    pm=C.RAWM/f'{lid}.xml.gz'
    if not pm.exists(): skip['no_raw_manifest']+=1; skipped.append((i,'no_raw_manifest')); continue
    try: m=C.parse_manifest(gzip.decompress(pm.read_bytes()))
    except Exception as e: skip['manifest_bad']+=1; skipped.append((i,'manifest_bad')); continue
    chosen=None; why=None
    for e in [e for e in m['exprs'] if not e['deleted']][:4]:
        px=C.RAWX/f"{lid}_{e['expr']}.xml.gz"
        if not px.exists(): why='raw_xml_missing'; break
        raw=gzip.decompress(px.read_bytes()); meta=C.nlm_split.parse_meta(raw)
        if meta.get('inwerkingtreding') and meta['inwerkingtreding']>today: continue
        chosen=(e,f"{C.BASE}/cvdr/{lid}/{e['expr']}/xml/{e['item']}",raw,meta,px); break
    if chosen is None: skip[why or 'no_inforce_expr']+=1; skipped.append((i,why or 'no_inforce_expr')); continue
    e,url,raw,meta,px=chosen; uit=meta.get('uitwerkingtreding')
    if uit and uit<=today: skip['now_expired']+=1; skipped.append((i,'now_expired')); continue
    auth,method,conflict=C.AUTH.match(m['owms'],meta.get('creator_scheme'),meta.get('creator'))
    if auth is None or not auth['current']: skip['now_out_of_scope']+=1; skipped.append((i,'out_of_scope')); continue
    try: rows,stt,full=C.nlm_split.split_cvdr(raw,lid,url,e['expr'])
    except Exception as ex: skip['split_fail']+=1; skipped.append((i,'split_fail')); continue
    if not rows: skip['no_rows']+=1; skipped.append((i,'no_rows')); continue
    fetched_at=datetime.datetime.fromtimestamp(px.stat().st_mtime,datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    law=C.build_law(i,m,e,url,raw,meta,auth,method,rows,stt,full,today,fetched_at); law['json_path']=None
    emit(i, law, rows, 'raw_rebuild')
    if n%500==0: log('rest',n,'/',len(rest),dict(src),dict(skip),'mem',mem(),'rss',rss())
flush(True); lw.close(); aw.close()
R=dict(stage_dir=S, built_pt=C.now_pt(), id_range=[LO,767599], n_ids_scanned=len(st), status_counts=collections.Counter(st.values()),
  remote_gap_band='ids 640600..664399 (scan chunks hi 664399..640599) not on this disk (vda/older boots) -> GAP, not in tranche',
  n_ok=len(ok), laws=len(done), articles=artn, source=src, rebuild_skips=skip, skipped_sample=skipped[:50], bad=bad[:100], n_bad=len(bad),
  record_types=rt, empty_text_articles=emptyart, by_authority_type=atype, articles_by_authority_type=arts_by_type, n_jurisdictions=len(jur),
  top_jurisdictions=jur.most_common(15), date_min=min(dates) if dates else None, date_max=max(dates) if dates else None,
  peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024)
json.dump(R,open(f'{S}/build_report.json','w'),indent=1,default=str); log('DONE',json.dumps(R,default=str)[:1500])

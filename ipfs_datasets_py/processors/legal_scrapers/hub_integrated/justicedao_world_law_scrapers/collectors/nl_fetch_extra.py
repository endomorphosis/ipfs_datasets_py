#!/usr/bin/env python3
"""One-off: (1) retry BWBR0052939 once (+manifest _latestItem fallback only on 404); (2) add BWBR0015091 via manifest.
KOOP repository only, >=2.2s between requests, single attempt per request, no redirects off-host. Writes into the same cache."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, re, json, gzip, time, os
sys.path.insert(0, '/workspace/scripts')
import requests, nl_split
from nl_collect import RAW, OUT, B, HOST, UA, memavail, version_of
TERM=3584; S=requests.Session(); S.headers['User-Agent']=UA; last=[0.0]; LOG=[]
def log(*a):
    s=time.strftime('%Y-%m-%d %H:%M:%S ')+' '.join(map(str,a)); print(s, flush=True); LOG.append(s)
def get(url):
    assert url.startswith(f'https://{HOST}/'), url
    m=memavail()
    if m<=TERM: log(f'MEMGUARD TERM MemAvailable={m}MB'); sys.exit(3)
    w=2.2-(time.time()-last[0]);
    if w>0: time.sleep(w)
    last[0]=time.time()
    try: r=S.get(url, timeout=(20,180), allow_redirects=False)
    except Exception as e: log('ERR', url, repr(e)[:200]); return None
    log('GET', url, r.status_code, len(r.content), r.headers.get('location',''))
    return r
def save(lid, url, note, content):
    p=RAW/f'{lid}.xml.gz'; p.write_bytes(gzip.compress(content,6))
    (RAW/f'{lid}.meta.json').write_text(json.dumps(dict(url=url, version_note=note, bytes=len(content), fetched_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'))))
    rows, st = nl_split.split_xml(content, lid, url, version_of(url))
    with gzip.open(OUT/f'{lid}.jsonl.gz','wt',encoding='utf-8') as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False)+'\n')
    return rows, st
res={}
# (1) retry
lid='BWBR0052939'; t=[json.loads(l) for l in open(B/'index/hub_targets.jsonl') if lid in l][0]
r=get(t['url']); url=t['url']; note='hub_version_retry'
if r is not None and r.status_code==404:
    m=get(t['manifest'])
    li=re.search(rb'_latestItem="([^"]+)"', m.content) if (m is not None and m.status_code==200) else None
    if li: url=f"https://{HOST}/bwb/{lid}/{li.group(1).decode()}"; note='latest_item_fallback'; r=get(url)
if r is not None and r.status_code==200 and r.content.lstrip().startswith(b'<?xml'):
    rows, st = save(lid, url, note, r.content); res[lid]=dict(status='ok', url=url, note=note, rows=len(rows), stats=st)
else: res[lid]=dict(status='fail', http=getattr(r,'status_code',None), url=url)
# (2) new law
lid='BWBR0015091'; r=get(f'https://{HOST}/bwb/{lid}/')
murl=None
if r is not None and r.status_code in (301,302,303,307,308):
    loc=r.headers.get('location',''); murl=loc if loc.startswith('http') else f'https://{HOST}'+loc
    r=get(murl) if murl.startswith(f'https://{HOST}/') else None
if r is None or r.status_code!=200: res[lid]=dict(status='manifest_fail', http=getattr(r,'status_code',None))
else:
    (B/'extra'/f'manifest_{lid}.xml').write_bytes(r.content)
    import xml.etree.ElementTree as ET
    w=ET.fromstring(r.content); exps=[]
    for e in w.findall('expression'):
        md=e.find('metadata'); g=lambda k:(md.findtext(k) if md is not None else None)
        it=e.find('manifestation[@label="xml"]/item')
        exps.append(dict(label=e.get('label'), van=g('datum_inwerkingtreding'), tot=g('einddatum'), zs=g('zichtdatum_start'), ze=g('zichtdatum_eind'),
                         deleted=(it.get('_deleted') if it is not None else None), item=(it.get('label') if it is not None else None)))
    D='2026-09-02'
    cand=[x for x in exps if x['item'] and x['deleted']!='true' and (x['van'] or '')<=D<=(x['tot'] or '9999-12-31')]
    cand.sort(key=lambda x:(x['van'] or '', x['label']))
    if cand: x=cand[-1]; choice='in_force_on_2026-09-02'
    else:
        li=w.get('_latestItem'); x=dict(label=li.split('/')[0], item=li.split('/')[-1]) if li else None; choice='latestItem_fallback(no expression in force on 2026-09-02)'
    res[lid]=dict(manifest_url=murl, n_expressions=len(exps), expressions=exps, work_attrs=dict(w.attrib), work_metadata={c.tag:c.text for c in (w.find('metadata') or [])}, choice=choice, chosen=x)
    if x:
        url=f"https://{HOST}/bwb/{lid}/{x['label']}/xml/{x['item']}"; r=get(url)
        if r is not None and r.status_code==200 and r.content.lstrip().startswith(b'<?xml'):
            rows, st = save(lid, url, choice, r.content); res[lid].update(status='ok', url=url, rows=len(rows), stats=st)
        else: res[lid].update(status='xml_fail', http=getattr(r,'status_code',None), url=url)
res['log']=LOG
json.dump(res, open(B/'extra/fetch_extra_result.json','w'), indent=1, ensure_ascii=False)
print(json.dumps({k:(v if k=='log' else {kk:vv for kk,vv in v.items() if kk!='expressions'}) for k,v in res.items()}, indent=1, ensure_ascii=False)[:5000])

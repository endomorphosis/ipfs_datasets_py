# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,subprocess,os,sys,datetime
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline'))
os.environ['ARCHIVE_LANE']='sasia_ru'
for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','all_proxy'): os.environ.pop(k,None)
from archive.ratelimit import wayback_available
from archive.core import ArchiveFetcher, ArchiveDeferred, ArchiveTransient
import time
# 2026-10-18: ArchiveFetcher no longer retries 429/5xx; it raises ArchiveDeferred (or, inside fetch_newest, swallows it and
# sets F.last_wb_deferred). Deferred docs are recorded as 'archive:deferred' with not_before and are never 'done'
# (pk_sd_deferred.jsonl only); this one-shot script has no in-process retry of a deferred doc.
def archive_try(F, url, p, tries):
    """Archive step for one PDF; appends to tries, writes p on success. Returns not_before (epoch) if deferred, else None."""
    nb=None
    try:
        # 12:10 API: fetch_newest RAISES ArchiveDeferred when nothing usable was found and CC or Wayback (CDX or
        # capture) was throttled; None = genuine miss. The PDF validator keeps it looking past non-PDF captures,
        # so a deferred PDF capture can't hide behind an HTML hit.
        d=F.fetch_newest(url,validator=lambda dd: dd.body[:4]==b'%PDF')
        b=getattr(d,'body',b'') if d else b''
        if b[:4]==b'%PDF': open(p,'wb').write(b); tries.append('archive:ok')
        elif d is None and getattr(F,'last_wb_deferred',0):      # Wayback breaker open: skipped, not raised
            from archive import deferral
            nb=time.time()+max(deferral.host_cooldown('web.archive.org'),600); tries.append('archive:breaker_skipped')
        else: tries.append('archive:nocapture')
    except ArchiveDeferred as e: nb=e.not_before or time.time()+60; tries.append('archive:deferred:'+','.join(getattr(e,'families',[]) or []))
    except ArchiveTransient as e: nb=time.time()+600; tries.append('archive:transient')   # timeouts (1 retry) / breaker
    except Exception as e: tries.append(f'archive:{type(e).__name__}')
    return nb


def main():
    os.chdir((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ocr'))
    RAW=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_raw/pk_sd')
    L=[json.loads(l) for l in open('../../pdf/_state/text_layer_pk_sd.jsonl') if l.strip()]
    D={json.loads(l)['doc_id'] for l in open('pk_sd_done.jsonl')}
    todo=[x for x in L if x['doc_id'] not in D]
    now=datetime.datetime.now(datetime.UTC); ra=(now+datetime.timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
    wb=wayback_available(); F=ArchiveFetcher(lane='sasia_ru',use_wayback=wb)
    out=[]
    for x in todo:
        did=x['doc_id']; p=f'{RAW}/{did}.pdf'; tries=[]
        for name,args,url in [('tlsv1.2',['--tlsv1.2','--tls-max','1.2'],x['pdf_url']),('http',[],x['pdf_url'].replace('https://','http://'))]:
            if os.path.exists(p): break
            rc=subprocess.run(['curl','-sfL','--noproxy','*','-m','120',*args,'-A','world-law-research-bot/1.0','-o',p+'.part',url]).returncode
            ok=rc==0 and open(p+'.part','rb').read(4)==b'%PDF'
            tries.append(f'{name}:rc{rc}{"" if ok or rc else ":notpdf"}')
            if ok: os.rename(p+'.part',p)
        nb=None
        if not os.path.exists(p): nb=archive_try(F, x['pdf_url'], p, tries)
        if os.path.exists(p+'.part'): os.remove(p+'.part')
        out.append({**x,'status':'fetched' if os.path.exists(p) else 'failed_ssl','error':'curl rc 35 (SSL connect error), repeated passes since ~13:16 PT','retry_attempts':tries,'wayback_breaker_open':not wb,'retry_after':ra,'retries':1,**({'archive_deferred':True,'not_before':round(nb,1),'not_before_utc':datetime.datetime.fromtimestamp(nb,datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} if nb else {})})
        print(did,out[-1]['status'],tries,flush=True)
    with open('pk_sd_deferred.jsonl.tmp','w') as f:
        for r in out:
            if r['status']!='fetched': f.write(json.dumps(r)+'\n')
    os.rename('pk_sd_deferred.jsonl.tmp','pk_sd_deferred.jsonl')


if __name__ == '__main__':
    main()

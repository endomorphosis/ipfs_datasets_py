"""Cache ru labels + OKTMO (P764) + OKATO (P721) for all RU places from Wikidata. -> _ru/wd_ru.jsonl"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,json,requests,time,os
OUT=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/wd_ru.jsonl')
done=set(json.loads(l)['qid'] for l in open(OUT)) if os.path.exists(OUT) else set()
q=[x['qid'] for x in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + '/global_municipalities_candidate.csv'))) if x['country_code']=='RU' and x['qid'] and x['qid'] not in done]
S=requests.Session(); S.headers['User-Agent']='WorldLawMunicipalResearch/1.0 (sasia_ru lane)'
with open(OUT,'a') as o:
    for i in range(0,len(q),50):
        ids=q[i:i+50]
        for att in range(5):
            try:
                r=S.get('https://www.wikidata.org/w/api.php',params={'action':'wbgetentities','ids':'|'.join(ids),'props':'labels|claims','languages':'ru','format':'json'},timeout=60); d=r.json()['entities']; break
            except Exception: time.sleep(10*(att+1))
        else: continue
        for k,e in d.items():
            c=e.get('claims',{})
            g=lambda p:[x['mainsnak'].get('datavalue',{}).get('value') for x in c.get(p,[])]
            o.write(json.dumps({'qid':k,'ru':e.get('labels',{}).get('ru',{}).get('value'),'oktmo':g('P764'),'okato':g('P721'),'p31':[v.get('id') for v in g('P31') if isinstance(v,dict)]},ensure_ascii=False)+'\n')
        o.flush(); time.sleep(1)

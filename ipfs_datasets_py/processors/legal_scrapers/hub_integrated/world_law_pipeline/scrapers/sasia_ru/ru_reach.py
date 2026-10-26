"""Reachability sweep of RU place-list websites (no proxy/VPN). Writes _ru/reach.jsonl"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,re,json,requests,concurrent.futures as cf,collections,time
r=[x for x in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + '/global_municipalities_candidate.csv'))) if x['country_code']=='RU' and x['source_url'].startswith('http')]
byhost=collections.defaultdict(list)
for x in r:
    u=x['source_url'].split(',')[0].strip(); h=re.sub(r'^https?://([^/]+).*',r'\1',u)
    byhost[(h,u.split('://')[0])].append(x['place_id'])
def chk(k):
    h,sch=k; res={'host':h,'places':byhost[k]}
    for s in ([sch]+(['http'] if sch=='https' else ['https'])):
        try:
            x=requests.get(f'{s}://{h}/robots.txt',timeout=(10,20),headers={'User-Agent':'Mozilla/5.0 (world-law municipal research)'},allow_redirects=True)
            res.update(scheme=s,status=x.status_code,robots=x.text[:3000] if x.status_code==200 and 'html' not in x.headers.get('content-type','') else None,final=x.url); return res
        except Exception as e: res['err_'+s]=type(e).__name__
    return res
out=open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/reach.jsonl'),'w')
with cf.ThreadPoolExecutor(12) as ex:
    for res in ex.map(chk,list(byhost)): out.write(json.dumps(res,ensure_ascii=False)+'\n'); out.flush()

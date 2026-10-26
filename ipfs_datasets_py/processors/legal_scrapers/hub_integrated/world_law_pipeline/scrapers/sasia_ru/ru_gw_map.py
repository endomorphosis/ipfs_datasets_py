"""Map discovered Gosweb hosts to RU places by site title; keep only unique name matches. Writes _ru/gosweb_hosts_mapped.jsonl"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys,re,json,csv,time,collections,html as H,requests,concurrent.futures as cf
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/sasia_ru'))
import ru_gosweb as G
translit,norm,STOP=G.translit,G.norm,G.STOP
places=[x for x in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + '/global_municipalities_candidate.csv'))) if x['country_code']=='RU']
idx=collections.defaultdict(list)
for p in places:
    ks=[norm(w) for w in re.split(r'[\s\-]+',p['place_name']) if norm(w) and w.lower() not in STOP]
    if ks: idx[ks[0][:max(4,len(ks[0])-3)]].append(p)
done={json.loads(l)['host'] for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/gosweb_hosts.jsonl'))}
hosts=[h for h in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/gosweb_found.txt')).read().split() if h not in done and not re.match(r'^(www|dom|max|knd|zagorodsreda|beta|pos|esia|lk|gu|vote|pgu|partners|contract|do|epgu|\d+)\.',h)]
LEVEL={'сельское поселение':'rural settlement','сельского поселения':'rural settlement','городское поселение':'urban settlement','городского поселения':'urban settlement','муниципальный район':'District','муниципального района':'District','городской округ':'Okrug','городского округа':'Okrug','муниципальный округ':'Okrug','муниципального округа':'Okrug'}
def title(h):
    try:
        r=requests.get(f'https://{h}/',timeout=(10,25),headers={'User-Agent':'Mozilla/5.0 (compatible; WorldLawMunicipalResearch/1.0)'})
        m=re.search(r'<title>(.*?)</title>',r.text,re.S); return h,re.sub(r'\s+',' ',H.unescape(m.group(1))).strip() if m else ''
    except Exception: return h,None
out=open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/gosweb_hosts_mapped.jsonl'),'w'); log=open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/gosweb_map.log'),'w')
with cf.ThreadPoolExecutor(6) as ex:
    for h,t in ex.map(title,hosts):
        if not t: log.write(f'{h}\tNOTITLE\n'); continue
        tt=norm(translit(t)); lvl=[v for k,v in LEVEL.items() if k in t.lower()]
        cands=[p for k,ps in idx.items() if len(k)>=5 and k in tt for p in ps]
        if lvl: cands=[p for p in cands if lvl[0].lower() in p['place_name'].lower()] or cands
        u={p['place_id']:p for p in cands}
        if len(u)==1:
            p=list(u.values())[0]; out.write(json.dumps({'host':h,'place_id':p['place_id'],'place_name':p['place_name'],'site_title':t},ensure_ascii=False)+'\n'); out.flush()
            log.write(f'{h}\tOK\t{p["place_name"]}\t{t}\n')
        else: log.write(f'{h}\tAMBIG{len(u)}\t{t}\n')
        log.flush()

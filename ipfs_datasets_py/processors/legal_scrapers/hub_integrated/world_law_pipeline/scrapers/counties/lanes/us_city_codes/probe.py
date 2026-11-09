# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
_CITY = _ipfs_Path(_ipfs_os.environ.get("US_CITY_CODES_ROOT", str(_LEGAL_WS / "us_city_codes")))
import json,random,re,urllib.request,urllib.robotparser,urllib.parse,collections,concurrent.futures as cf,ssl
UA='world-laws-planning/0.1 (research; contact: benjamin barber)'
c=json.load(open(str(_CITY/'raw'/'cand_seed.json')))
new=[o for o in c if o['already_covered']=='no' and o['source_url'] and o['type']=='municipality']
random.seed(7); samp=random.sample(new,80)
PAT={'municode':r'library\.municode\.com|municode\.com','amlegal':r'codelibrary\.amlegal\.com|amlegal\.com','ecode360':r'ecode360\.com','municipal.codes':r'\.municipal\.codes|codepublishing\.com','civicplus_mco':r'municipalcodeonline\.com','encodeplus':r'encodeplus\.com','qcode':r'qcode\.us','sterling':r'sterlingcodifiers\.com','franklin':r'franklinlegal\.net','citycode':r'citycode\.net','generalcode':r'generalcode\.com','pdf_code':r'(?i)(code|ordinance)[^"\']{0,60}\.pdf','civicplus_docs':r'DocumentCenter|ArchiveCenter|/Archive\.aspx'}
def probe(o):
    u=o['source_url']; p=urllib.parse.urlparse(u)
    r={'j':o['jurisdiction'],'url':u,'status':'','plats':[]}
    try:
        rp=urllib.robotparser.RobotFileParser(); 
        req=urllib.request.Request(f'{p.scheme}://{p.netloc}/robots.txt',headers={'User-Agent':UA})
        try:
            txt=urllib.request.urlopen(req,timeout=10).read().decode('utf-8','ignore'); rp.parse(txt.splitlines())
        except Exception: rp.parse([])
        if not rp.can_fetch(UA,u): r['status']='robots_disallow'; return r
        resp=urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':UA}),timeout=12)
        html=resp.read(400000).decode('utf-8','ignore'); r['status']=str(resp.status)
        r['plats']=[k for k,v in PAT.items() if re.search(v,html)]
    except Exception as e:
        r['status']='err:'+type(e).__name__+str(e)[:40]
    return r
with cf.ThreadPoolExecutor(6) as ex: res=list(ex.map(probe,samp))
json.dump(res,open('raw/probe_sample.json','w'))
print(collections.Counter(r['status'][:20] for r in res).most_common(8))
ok=[r for r in res if r['status']=='200']
print(len(ok),'ok; with any code link',sum(1 for r in ok if r['plats']))
print(collections.Counter(p for r in ok for p in r['plats']))

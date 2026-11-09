# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import requests,time,json,hashlib,shutil,re
from pathlib import Path
from urllib.parse import urlparse,urljoin,urldefrag
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from datetime import datetime,timezone
B=Path((str(_LEGAL_WS) + '/courts_asia_africa/kenya_v2/step2')); UA='KenyaCourtsGapAudit/1.0'; blocked={}; robots={}; last={}; cache={}
def limits():
 free=shutil.disk_usage(B).free/2**30
 mem=int(next(l for l in open('/proc/meminfo') if l.startswith('MemAvailable:')).split()[1])/2**20
 size=sum(p.stat().st_size for p in B.rglob('*') if p.is_file())
 if free<11 or mem<3.5 or size>900*2**20: raise RuntimeError(f'SOFT PAUSE free={free:.2f}GiB mem={mem:.2f}GiB size={size}')
def log(x):
 with open(B/'fetch.jsonl','a') as f:f.write(json.dumps(x)+'\n')
def fetch(url,isrobot=False):
 url=urldefrag(url)[0]; host=urlparse(url).netloc
 if url in cache:return cache[url]
 if host in blocked:return None
 if not isrobot and (host not in robots or not robots[host].can_fetch(UA,url)):
  log({'url':url,'skipped':'robots disallow or unavailable'});return None
 limits(); delay=max(2,robots[host].crawl_delay(UA) or robots[host].crawl_delay('*') or 0) if host in robots else 2
 time.sleep(max(0,delay-(time.monotonic()-last.get(host,0)))); last[host]=time.monotonic()
 rec={'url':url,'retrieved_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get(url,headers={'User-Agent':UA},timeout=(15,50),allow_redirects=False,stream=True);rec.update(status=r.status_code,content_type=r.headers.get('Content-Type'),location=r.headers.get('Location'))
  if r.status_code in (403,429):blocked[host]=f'HTTP {r.status_code}; no retry or fallback';log(rec);return None
  if r.is_redirect:
   log(rec); dest=urljoin(url,r.headers['Location'])
   if urlparse(dest).netloc!=host and urlparse(dest).netloc not in robots:return None
   return fetch(dest,isrobot)
  if r.status_code!=200:log(rec);return None
  chunks=[];n=0
  for c in r.iter_content(65536):
   n+=len(c)
   if n>15*2**20:rec['skipped']='15MiB response cap';log(rec);return None
   chunks.append(c)
  data=b''.join(chunks);h=hashlib.sha256(data).hexdigest(); ext='.pdf' if data.startswith(b'%PDF') else '.html';p=B/'raw'/(h+ext);p.write_bytes(data);rec.update(path=str(p),sha256=h,bytes=n);log(rec);cache[url]=rec;return rec
 except requests.RequestException as e:blocked[host]=str(e);rec['error']=str(e);log(rec);return None

def init():
 for host in ['judiciary.go.ke','kenyalaw.org','new.kenyalaw.org','tribunals.judiciary.go.ke']:
  x=fetch('https://'+host+'/robots.txt',True)
  if x:
   rp=RobotFileParser();rp.parse(Path(x['path']).read_text(errors='replace').splitlines());robots[host]=rp
  else:blocked.setdefault(host,'robots unavailable; no content fetched')

def soup(rec):return BeautifulSoup(Path(rec['path']).read_bytes(),'html.parser')
def main():
 init()
 seeds=['the-supreme-court','supreme-court-judges','court-of-appeal','court-of-appeal-judges','the-high-court','high-court-judges','environment-and-land-court','environment-and-land-court-judges','employment-and-labour-relations-court','employment-and-labour-relations-court-judges','magistrate-courts','kadhis-courts','small-claims-court','forms','judiciary-rules-committee']
 for p in seeds:fetch('https://judiciary.go.ke/'+p+'/')
 for u in ['https://kenyalaw.org/','https://new.kenyalaw.org/','https://tribunals.judiciary.go.ke/']:fetch(u)
 (B/'state.json').write_text(json.dumps({'blocked':blocked,'cache':cache},indent=2))
 print('FETCHED',len(cache),'BLOCKS',blocked,flush=True)
if __name__=='__main__':main()

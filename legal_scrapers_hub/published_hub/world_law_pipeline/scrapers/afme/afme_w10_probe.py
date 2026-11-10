"""wave 10: robots.txt probe (1 GET per host, RFC 9309 classification) -> afme/_w10_probe.tsv. usage: afme_w10_probe.py CC [CC...]"""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,sys,requests
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
UA="JusticeDAO-WorldLaw/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law; municipal law research)"
R=[r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + '/global_municipalities_candidate.csv'))) if r['country_code'] in sys.argv[1:] and r['url_class']=='official_site' and r['source_url'].startswith('http')]
def pr(r):
    p=urlparse(r['source_url']); u=f"{p.scheme}://{p.netloc}/robots.txt"
    try:
        x=requests.get(u,timeout=15,headers={"User-Agent":UA}); ct=x.headers.get('content-type','')
        st="html" if "html" in ct and x.status_code==200 else str(x.status_code)
        dis="disallow_all" if st=="200" and any(l.strip().lower()=="disallow: /" for l in x.text.splitlines()) else ""
    except Exception as e: st=type(e).__name__; dis=""
    return f"{r['country_code']}\t{r['place_id']}\t{r['place_name']}\t{r['source_url']}\t{st}\t{dis}"
with ThreadPoolExecutor(8) as ex, open('afme/_w10_probe.tsv','a') as o:
    for l in ex.map(pr,R): o.write(l+"\n"); print(l,flush=True)

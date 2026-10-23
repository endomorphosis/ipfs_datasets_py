"""Fetch Gosweb homepages; extract header (logo alt + header text), footer org, metricRegion. -> _ru/gw_headers.jsonl"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,re,requests,html as H,concurrent.futures as cf,os
D=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/')
hosts=set(open(D+'gosweb_found.txt').read().split())|{json.loads(l)['host'] for l in open(D+'gosweb_hosts.jsonl')}
hosts={h for h in hosts if not re.match(r'^(www|dom|max|knd|zagorodsreda|beta|pos|esia|lk|gu|vote|pgu|partners|contract|do|epgu|\d+)\.',h)}
done={json.loads(l)['host'] for l in open(D+'gw_headers.jsonl')} if os.path.exists(D+'gw_headers.jsonl') else set()
def clean(s): return re.sub(r'\s+',' ',H.unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def f(h):
    try:
        r=requests.get(f'https://{h}/',timeout=(10,30),headers={'User-Agent':'Mozilla/5.0 (compatible; WorldLawMunicipalResearch/1.0)'})
        t=r.text; out={'host':h,'status':r.status_code,'final':r.url}
        out['title']=clean((re.search(r'<title>(.*?)</title>',t,re.S) or [None,''])[1])
        out['logo_alt']=[clean(a) for a in re.findall(r'class="[^"]*logo[^"]*"[^>]*alt="([^"]+)"',t)][:3]
        hd=re.search(r'class="gw-header-info[^"]*"(.*?)</div>\s*</div>',t,re.S); out['header']=clean(hd.group(1))[:400] if hd else ''
        hi=re.search(r'class="gw-header__top[^"]*"(.*?)<nav',t,re.S); out['header_top']=clean(hi.group(1))[:600] if hi else ''
        ft=re.search(r'<footer(.*?)</footer>',t,re.S); out['footer']=clean(ft.group(1))[-600:] if ft else ''
        m=re.search(r'metricRegion\s*=\s*"r?(\d+)"',t); out['region']=m.group(1) if m else None
        out['gosweb']='gw-' in t
        return out
    except Exception as e: return {'host':h,'err':type(e).__name__}
with cf.ThreadPoolExecutor(6) as ex, open(D+'gw_headers.jsonl','a') as o:
    for r in ex.map(f,sorted(hosts-done)): o.write(json.dumps(r,ensure_ascii=False)+'\n'); o.flush()

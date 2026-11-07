"""wave 11 cfg builder: afme_w11_cfg.py <CC> <lang> [live|both]  (run with out/.afme_venv python)
Places: global_municipalities_candidate.csv rows of CC, url_class official_site, aggregator/media hosts dropped, one place per host, population desc, max 200.
Each host gets ONE robots.txt GET (RFC 9309 via rfc9309.Robots; cached in afme/_w11_probe.tsv):
  robots 200/404 and UA allowed at '/'  -> live cfg   (afme_live11.py)
  robots disallow-all for our UA        -> arch cfg   (archived_policy archived_robots_disallowed)
  unreachable / HTML robots / 4xx / 5xx -> arch cfg   (live_status says why)
Laws.Africa / LII hosts always go to arch with source_policy content_signal_ai_train_no.
Writes afme/<cc>_{live,arch}_w11_cfg.json + _test_cfg.json (first 20) and prints counts. mode 'arch' = skip live (probe not needed)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,json,sys,re,os
from urllib.parse import urlparse,quote
from concurrent.futures import ThreadPoolExecutor
import requests
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/web")); from rfc9309 import Robots
cc=sys.argv[1]; lang=sys.argv[2]; mode=sys.argv[3] if len(sys.argv)>3 else "both"; lc=cc.lower()
UA="JusticeDAO-WorldLaw/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law; municipal law research)"
JUNK=re.compile(r"(?i)(globaldatalab|citypopulation|wikipedia|wikidata|facebook|twitter|instagram|youtube|tripadvisor|mapcarta|mindat|gadm\.org|elevationmap|soundcloud|reliefweb|zawya|radio|media|news|stat\.|ansade|geonames|web\.archive\.org|archive\.org|google\.|booking\.com|linkedin|yerelnet|liberiadata|\.wordpress\.com|blogspot|statoids|allafrica|observer|backpack|travel|tour|hotel|blog|forum|wiki|nigeriagalleria|bbc|cnn|worldbank|un\.org|undp|unicef|usaid)")
GOV=re.compile(r"(?i)((^|\.)(gov|go|gouv|govt|gob|gv|bel|muni|mun|lg|lga|dc|mc|municipality|city|council|kep)\.|\.gov$|municipal|mairie|commune|council|ville|district|county|belediye|shahr|shora|mayor|\.mr$)")
LII=re.compile(r"(?i)(laws\.africa|(zim|namib|lesotho|eswatini|gha|sierra|nigeria|sey|malawi|zambia|tanz|u|kenya|botswana|liber)lii\.org|africanlii\.org|kenyalaw\.org)")
BADB=r"(?i)(application|\bform\b|checklist|fact\s*sheet|brochure|guideline|submission|consultation|survey|draft|proposed|agenda|minutes|report|annual|budget|newsletter|media\s+release|tender|bid|advert|vacanc|recruit|job|procurement|shortlist|results)"
# per-language: (law words, extra bad words, regulation words)
L={"en":(["by-?laws?","bye-?laws?","ordinance","regulation","act\\b","order\\b","rules"],["quotation","vacancy"],"regulation|rules"),
 "fr":(["arr[eê]t[eé]","arrete","d[eé]lib[eé]ration","deliberation","r[eè]glement","reglement","fiscal","code[-_ ]?(general|des|de)","d[eé]cret","statut","journal[-_ ]?officiel","by-?law"],["formulaire","rapport","offre","appel","recrutement","avis"],"r[eè]glement"),
 "tr":(["y[öo]netmelik","t[üu]z[üu]k","meclis\\s*karar","karar","tarife","z[aâ]bıta","zabita","imar","by-?law","ordinance"],["ihale","ilan","faaliyet","b[üu]tçe","butce","duyuru","personel","basın","basin","form\\b"],"y[öo]netmelik|t[üu]z[üu]k"),
 "he":(["חוק\\s*עזר","חוקי\\s*עזר","תקנות","צו\\s","by-?law"],["מכרז","דוח","טופס","פרוטוקול"],"תקנות"),
 "fa":(["آیین\\s*نامه","آیین‌نامه","مقررات","ضوابط","مصوبه","دستورالعمل","by-?law"],["مناقصه","گزارش","فرم","استخدام"],"آیین"),
 "ar":(["لائحة","نظام","قرار","تعليمات","by-?law","regulation","ordinance"],["مناقصة","تقرير","نموذج","وظائف"],"لائحة|نظام")}
words,xbad,regw=L[lang]
def enc(w):   # also match percent-encoded non-ASCII keyword in URLs
    plain=re.sub(r"[\\\[\]\(\)\?\+\*|^$]|\bb\b","",w)
    return w if plain.isascii() and "\\" not in w and "[" not in w else w
alts=set(words)
for w in words:
    if not w.isascii() and re.fullmatch(r"[^\\\[\]\(\)\?\+\*|^$]+",w): alts.add(re.escape(quote(w)))
law="(?i)("+"|".join(sorted(alts))+")"
bad=BADB[:-1]+"|"+"|".join(xbad)+")"
R=[r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + '/global_municipalities_candidate.csv'))) if r['country_code']==cc and r['url_class']=='official_site' and r['source_url'].startswith('http')]
R.sort(key=lambda r:-float(r['population'] or 0)); seen=set(); P=[]
for r in R:
    h=urlparse(r['source_url']).netloc.lower().removeprefix('www.')
    if h in seen or (JUNK.search(h) and not LII.search(h)): continue
    if not (LII.search(h) or GOV.search(h) or (cc=='IR' and h.endswith('.ir'))): continue
    seen.add(h); P.append((r,h))
P=P[:200]
PR="afme/_w11_probe.tsv"; cache={}
if os.path.exists(PR):
    for l in open(PR):
        a=l.rstrip("\n").split("\t")
        if len(a)>=4: cache[(a[0],a[2])]=(a[3],a[4] if len(a)>4 else "")
def probe(x):
    r,h=x
    if (cc,h) in cache: return x,cache[(cc,h)]
    p=urlparse(r['source_url']); sch=p.scheme
    for u in (f"https://{p.netloc}/robots.txt",):   # https first (port 80 times out from the box)
        try:
            q=requests.get(u,timeout=15,headers={"User-Agent":UA},verify=False); ct=q.headers.get('content-type','')
            if q.status_code in (404,410): res=("live","robots_404")
            elif q.status_code>=400: res=("arch",f"robots HTTP {q.status_code}")
            elif "html" in ct.lower() or re.search(r"(?i)<html|<!doctype",q.text[:500]): res=("arch","robots_html")
            else:
                Rb=Robots(q.text)
                res=("live","robots_ok") if Rb.can_fetch(UA,f"https://{p.netloc}/") else ("arch","robots_disallowed")
        except Exception as e: res=("arch","robots_unreachable: "+type(e).__name__)
        return x,res
import urllib3; urllib3.disable_warnings()
live=[];arch=[]
todo=[x for x in P if not LII.search(x[1]) and mode!="arch"]
res={}
with ThreadPoolExecutor(3) as ex, open(PR,"a") as o:
    for x,rs in ex.map(probe,todo):
        res[x[1]]=rs
        if (cc,x[1]) not in cache: o.write(f"{cc}\t{x[0]['place_id']}\t{x[1]}\t{rs[0]}\t{rs[1]}\n"); o.flush()
for r,h in P:
    base=dict(place_id=r['place_id'],name=r['place_name'],admin_level=r['admin_level'] or 'municipality')
    if LII.search(h):
        arch.append(dict(base,host=h,live_status="Laws.Africa/LII (archive only)",archived_policy=["content_signal_ai_train_no","archive_fallback"])); continue
    if mode=="arch": arch.append(dict(base,host=h,live_status="w11 arch-only (live tested in w10)")); continue
    st,why=res[h]
    if st=="live": live.append(dict(base,site=r['source_url'].rstrip('/'),state=None))
    else:
        p=dict(base,host=h,live_status=why)
        if why=="robots_disallowed": p["archived_policy"]="archived_robots_disallowed"
        arch.append(p)
batch=lambda m:f"{lc}_{m}_w11"
common=dict(cc=cc,language=lang,doc_cap=40)
livecfg=dict(common,platform=f"{lc}_council_site",batch=batch("live"),threads=3,page_cap=25,places=live,lawtxt=law,navtxt=law[:-1]+"|documents?|publications?|downloads?|legislation|policies|المستندات|وثائق|قوانين)",
  navurl=r"(?i)(by-?law|bye-?law|ordinance|document|publication|download|resource|legislation|polic|arrete|deliberation|reglement|yonetmelik|mevzuat|qavanin|laws)",
  bad=bad,bad_title=bad,title_re=r"(?im)^\s*([^\n]{0,80}"+law.replace('(?i)','')+r"[^\n]{0,80})",regulation_re="(?i)("+regw+")")
archcfg=dict(common,batch=batch("arch"),places=arch,crawls=["CC-MAIN-2026-39","CC-MAIN-2025-30"],cc_filters=[],url_regex=law,exclude_regex=bad,bad_title=bad,regulation_re="(?i)("+regw+"|regulation)",defer_rounds=3)
for nm,c in (("live",livecfg),("arch",archcfg)):
    json.dump(c,open(f"afme/{lc}_{nm}_w11_cfg.json","w"),ensure_ascii=False,indent=0)
    json.dump(dict(c,places=c["places"][:20],batch=c["batch"]+"t"),open(f"afme/{lc}_{nm}_w11_test_cfg.json","w"),ensure_ascii=False)
print(f"{cc} hosts={len(P)} live={len(live)} arch={len(arch)}",flush=True)

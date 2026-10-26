"""wave 10 cfg builder: afme_w10_cfg.py <CC> <live|arch> <lang> <lawtxt-regex> [batch]  -> afme/<cc>_<mode>_w10_cfg.json + _test_cfg.json (first 20)
Places: global_municipalities_candidate.csv rows of CC with url_class official_site, sorted by population desc."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv,json,sys
from urllib.parse import urlparse
cc,mode,lang,law=sys.argv[1:5]; batch=sys.argv[5] if len(sys.argv)>5 else f"{cc.lower()}_{mode}_w10"
R=[r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + '/global_municipalities_candidate.csv'))) if r['country_code']==cc and r['url_class']=='official_site' and r['source_url'].startswith('http')]
R.sort(key=lambda r:-float(r['population'] or 0))
seen=set(); pl=[]
for r in R:
    h=urlparse(r['source_url']).netloc.lower().removeprefix('www.')
    if h in seen: continue
    seen.add(h)
    p=dict(place_id=r['place_id'],name=r['place_name'],admin_level=r['admin_level'] or 'municipality')
    if mode=='live': p.update(site=r['source_url'].rstrip('/'),state=None)
    else: p.update(host=h,live_status='robots/live unavailable (w10 probe)')
    pl.append(p)
BAD=r"(?i)(application|\bform\b|checklist|fact\s*sheet|brochure|guideline|submission|consultation|survey|draft|proposed|agenda|minutes|report|annual|budget|newsletter|media\s+release|tender|bid|advert|vacanc|recruit|job|procurement|shortlist|results)"
if mode=='live':
    cfg=dict(cc=cc,language=lang,platform=f"{cc.lower()}_council_site",batch=batch,threads=4,page_cap=25,doc_cap=40,places=pl,lawtxt=law,
      navtxt=law[:-1]+r"|documents|publications|downloads|resources|legislation|policies)" if law.endswith(')') else law,
      navurl=r"(?i)(by-?law|bye-?law|ordinance|document|publication|download|resource|legislation|polic|arrete|deliberation|reglement)",
      bad=BAD,title_re=r"(?im)^\s*([^\n]{0,80}"+law.replace('(?i)','')+r"[^\n]{0,80})",regulation_re=r"(?i)(regulation|polic|r[eè]glement)")
else:
    cfg=dict(cc=cc,language=lang,batch=batch,places=pl,doc_cap=40,crawls=["CC-MAIN-2026-39","CC-MAIN-2025-30"],cc_filters=[],url_regex=law,exclude_regex=BAD,
      bad_title=BAD,regulation_re=r"(?i)(regulation|kanuni|r[eè]glement)")
json.dump(cfg,open(f'afme/{cc.lower()}_{mode}_w10_cfg.json','w'),indent=0)
json.dump(dict(cfg,places=pl[:20],batch=batch+"t"),open(f'afme/{cc.lower()}_{mode}_w10_test_cfg.json','w'))
print(cc,mode,len(pl))

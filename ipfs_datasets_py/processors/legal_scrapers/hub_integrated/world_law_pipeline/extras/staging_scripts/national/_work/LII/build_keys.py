"""Build allow-key lists for archive targets TZ_lii, TZ_lii_gn, GH_lii, UG_lii from saved legislation sitemaps.
Key = AKN work URI '<cc>/act/[<subtype>/]<year>/<num>' (lower-case), matching specs.py include group 1.
Only URLs the LIVE robots.txt allows (RFC 9309 checker, robots.txt fetched live) are kept. TZ: polis.bunge acts
(same year/number, principal acts only) are written to skip keys."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import re, sys, json, requests
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/national/common"))
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/asia_latam/common"))
from robots import UA
from rfc9309 import Robots
SITES = {"tanzlii.org": "tz", "ghalii.org": "gh", "ulii.org": "ug"}
KEEP = {None, "gn", "ord", "ln", "si", "li", "ci", "ei", "nlcd", "pndcl", "smcd", "afrcd", "ca", "nrcd", "rules", "statute", "decree", "reg"}
RX = re.compile(r"/akn/(([a-z]{2})/act/(?:([a-z]+)/)?\d{4}/[^/@]+)")
out = {}
for host, cc in SITES.items():
    rt = requests.get(f"https://{host}/robots.txt", headers={"User-Agent": UA}, timeout=30)
    assert rt.status_code == 200, (host, rt.status_code)
    rb = Robots(rt.text)
    sig = sorted({l.strip() for l in rt.text.splitlines() if l.lower().startswith("content-signal")})
    urls = re.findall(r"<loc>([^<]*)", open(f"sm_{host}.xml").read())
    stats = {"urls": len(urls), "robots_disallowed": 0, "out_of_scope": 0}
    keys = {"main": set(), "gn": set()}
    for u in urls:
        m = RX.search(u)
        if not m or m.group(2) != cc or m.group(3) not in KEEP: stats["out_of_scope"] += 1; continue
        if not (rb.can_fetch(UA, u) and rb.can_fetch("*", u)): stats["robots_disallowed"] += 1; continue
        keys["gn" if (cc == "tz" and m.group(3) == "gn") else "main"].add(m.group(1).lower())
    stats.update({k: len(v) for k, v in keys.items()}); stats["content_signal_lines"] = sig
    out[host] = stats
    for k, v in keys.items():
        if v: open(f"keys_{cc}_{k}.txt", "w").write("\n".join(sorted(v)) + "\n")
# TZ polis.bunge skip list
B = (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/state/tls/ca_bundle_plus_aia.pem")
items, s = [], 0
while True:
    j = requests.get(f"https://polis.bunge.go.tz/api/acts/async?draw=1&start={s}&length=500", headers={"User-Agent": UA}, verify=B, timeout=60).json()
    d = j.get("data") or []; items += d; s += len(d)
    if not d or s >= j["recordsFiltered"]: break
staged = set(open((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/national/_work/TZ/tz_bunge.done")).read().split())
skip = set()
for it in items:
    if f"act{it['id']}" not in staged: continue   # only acts actually staged with text
    n = re.search(r"(\d+)", it.get("act_no") or ""); y = str(it.get("posted") or "")
    if n and re.fullmatch(r"\d{4}", y): skip.add(f"tz/act/{y}/{int(n.group(1))}")
main = set(open("keys_tz_main.txt").read().split())
open("skip_tz_polis.txt", "w").write("\n".join(sorted(skip)) + "\n")
out["polis_skip"] = {"polis_staged_with_year_no": len(skip), "overlap_with_tanzlii_main": len(skip & main)}
print(json.dumps(out, indent=1))

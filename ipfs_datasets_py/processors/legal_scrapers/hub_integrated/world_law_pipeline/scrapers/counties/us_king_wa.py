"""King County WA code (aqua.kingcounty.gov/council/clerk/code/*.htm), one doc per title.
robots.txt on aqua.kingcounty.gov returns 404 -> allowed (RFC 9309)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import re, sys, time, datetime, urllib.request, html as H
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline"))
from archive import StagedWriter
UA = "Mozilla/5.0 (world_law county lane)"
IDX = "https://kingcounty.gov/en/dept/council/governance-leadership/county-legislation-codes/king-county-code"
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60).read()
idx = get(IDX).decode("utf-8", "replace")
urls = sorted(set(re.findall(r'https://aqua\.kingcounty\.gov/council/clerk/code/[^"]+\.htm', idx)))
w = StagedWriter((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/counties"), "US", "gnis:1531933", batch_prefix="kingwa", chunk=500)
now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"); ok = fail = 0
for i, u in enumerate(urls):
    try:
        raw = get(u); s = raw.decode("windows-1252", "replace")
        name = u.rsplit("/", 1)[1][:-4]; label = re.sub(r"^\d+_", "", name).replace("_", " ")
        body = re.search(r"<body[^>]*>(.*)</body>", s, re.S | re.I); body = body.group(1) if body else s
        body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S | re.I)
        rec = {"place_id": "gnis:1531933", "country_code": "US", "gnis": "1531933", "doc_id": "kcc:" + name,
               "doc_order": i, "source_platform": "us_kingcounty_wa_code", "source_url": u,
               "doc_type": "code_section", "language": "en", "title_native": "King County Code - " + label,
               "consolidated": True, "content_format": "html", "html": '<div class="chunk-content">' + body + "</div>",
               "retrieved_at": now, "source_policy": "robots_404_allow_rfc9309", "source_official": True,
               "source_org": "King County Council Clerk", "place_name": "King County", "qid": "Q108861",
               "iso_3166_2": "US-WA", "admin_level": "county", "state_code": "WA", "platform": "us_kingcounty_wa_code"}
        e = w.add(rec)
        if e: print("INVALID", u, e); fail += 1
        else: ok += 1
    except Exception as ex:
        print("FAIL", u, ex); fail += 1
    time.sleep(2)
print("written:", w.flush(), "ok", ok, "fail", fail)

# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, shutil, subprocess
from pathlib import Path
H=Path(str(_SCRAPERS) + '/handoffs'); d=json.load(open(str(_SCRAPERS) + '/rebuild_20261027/hub_rebuild.json'))
NOTE=("REBUILT after the 2026-10-27 20:49 PT box restore (rebuild run 2026-10-27 ~22:2x PT) from Hugging Face Hub main (read-only; nothing uploaded/pushed/deleted).\n"
      "Hub = source of truth: tip+31zza went LIVE 2026-10-27 19:00 PT. Scripts: legal_scrapers/rebuild_20261027/. Hub data: legal_scrapers/rebuild_20261027/hub_rebuild.json (commit + sha256 per file).\n")
tab="cc\trepo\tcommit_sha\tL\tA\tmatches_expected\n"+"".join(f"{c}\t{r['repo']}\t{r['commit']}\t{r['L']}\t{r['A']}\t{str(r['match']).lower()}\n" for c,r in d.items())
bodies={
"20261027_tip31zza_13_HUB_LIVE.txt":"tip+31zza HUB LIVE (13 CCs, rebuilt from Hub main)\n"+NOTE+"\n"+tab+"\nrow counts read from Hub parquet metadata; staged parquet sha256 == Hub LFS sha256 for all 26 parquets. Hub README/MANIFEST sha256 recorded in hub_rebuild.json.\nunchanged-since-31zy (carried) CCs: ao,do,et,ir,mw,zm,la,rs (Hub commits are their tip+31zy commits); uploaded in zza: bo,az,al,lk,tn.\n",
"20261027_tip31zza_VERIFY_ASKED.txt":"tip+31zza verify delta asked of Countries Laws Verifier (rebuilt marker)\n"+NOTE,
"20261027_tip31zza_PINGS_SENT_BY_COS.txt":"tip+31zza pings sent by CoS (rebuilt marker)\n"+NOTE,
"20261027_tip31zza_LIVE_PARENT_DONE.txt":"tip+31zza LIVE_PARENT_DONE (rebuilt marker): zza LIVE on Hub 2026-10-27 19:00 PT; 13/13 Hub main counts verified post-restore.\n"+NOTE,
"20261027_tip31zza_RESTORE_REBUILT.txt":"tip+31zza RESTORE_REBUILT\n"+NOTE+"\nRebuilt: legal_scrapers/staging_<cc> x13 (old dirs moved to staging_<cc>.sep_snapshot), countries-laws-verifier/baseline_tip31zza (old moved to baseline_tip31zza.sep_snapshot), these handoffs.\nGuard: logs/cos_article_perlaw_guard.py vs baseline_tip31zza and vs baseline_tip31zy -> GUARD PASS.\n"+tab,
}
for n,b in bodies.items():
    p=H/n
    if p.exists():
        bak=H/(n+".orig_pre_rebuild"); shutil.copy2(p,bak)
        b+="\n----- ORIGINAL CONTENT FOUND ON BOX BEFORE REBUILD (preserved verbatim; copy at "+bak.name+") -----\n"+p.read_text()
    p.write_text(b)
    print("wrote",n)

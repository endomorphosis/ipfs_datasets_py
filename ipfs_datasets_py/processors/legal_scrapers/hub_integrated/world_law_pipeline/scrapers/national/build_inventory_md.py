# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json
from collections import Counter
from pathlib import Path
S=Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/national'))
rows=json.load(open(S/'_inventory_rows.json'))
P3=json.load(open(S/'_phase3_status.json'))
for r in rows:
    p=P3.get(r['CC'])
    if p and p.get('status'): r['works/broken/blocked']=p['status']
    if p and p.get('note'): r['notes']=p['note']+' | '+r['notes']
    if p and p.get('note_sub'): r['local_law_available']+=' | subnational '+p.get('status_sub','')+': '+p['note_sub']
c=Counter(r['works/broken/blocked'] for r in rows)
L=["# National-law collector inventory (world_law / national lane)\n",
"Updated by build_inventory_md.py. Repo: `/workspace/ipfs_datasets_py_latest` @ a1b5c73e (2026-10-07). Repo collectors copied unmodified to `/workspace/world_law/pipeline/scrapers/national/shared/`; phase-3 collectors in `.../national/<cc>/` (cn, es, fr) with shared `common/natlib.py` (RFC 9309 robots gate via asia_latam/common/rfc9309.py, unreachable/5xx robots => disallow-all).\n",
"Folders `europe/ africa/ americas/ asia_pacific/ mena/` are empty stubs; `legal_corpus/` is interfaces only; canonical list = `international/data/snapshot_catalog.json` (203).\n",
"## Status counts\n"]+[f"- {k}: {v}" for k,v in c.most_common()]+[
"\nSmoke-test caveats: web.archive.org was unreachable 15:05–16:00 PT; it came back at 16:01 PT and the 77 archive-dependent/slow collectors were re-tested 16:14–17:10 PT over HTTPS, 300 s window (`_logs/smoke/results_retest.jsonl`; re-test results supersede the first pass for those CCs). Statuses from the first pass are a coarse heuristic.\n",
"## Phase 3 (high-population thin/broken countries)\n","| CC | source | status | note |","|---|---|---|---|"]
for cc,p in P3.items():
    if p.get('status'): L.append(f"| {cc} | {p.get('source','')} | {p['status']} | {p.get('note','').replace('|','/')} |")
    if p.get('note_sub'): L.append(f"| {cc} (subnational) | | {p['status_sub']} | {p['note_sub'].replace('|','/')} |")
L+=["\n## Table\n","| country | CC | collector | source | works/broken/blocked | local_law_available | on_HF | notes |","|---|---|---|---|---|---|---|---|"]
esc=lambda s: str(s).replace('|','/').replace('\n',' ')
for r in rows:
    L.append(f"| {esc(r['country'])} | {r['CC']} | {r['collector']} | {esc(r['source'])} | {esc(r['works/broken/blocked'])} | {esc(r['local_law_available'])} | {esc(r['on_HF'])} | {esc(r['notes'])[:260]} |")
L.append("")
L.append((S/'_inventory_md_tail.md').read_text())
(S/'INVENTORY.md').write_text('\n'.join(L))
print('ok')

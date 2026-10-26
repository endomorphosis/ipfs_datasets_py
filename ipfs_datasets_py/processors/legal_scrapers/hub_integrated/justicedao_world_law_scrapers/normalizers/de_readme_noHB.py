#!/usr/bin/env python3
"""README / MANIFEST / PACK_META for the noHB staging (DE-HB HELD pending licence review)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, time, re
from pathlib import Path
B = Path('{_CORPORA}/de_subnational'); D = Path(open(B / 'last_stage_path_noHB.txt').read().strip())
chk = json.load(open(B / 'stage_check_noHB.json')); pj = chk['post']['per_jurisdiction']
nl, na = chk['laws']['new_rows'], chk['articles']['new_rows']; ll, la = nl - 6127, na - 129983
r = (D / 'README.md').read_text(); n0 = len(r)
def rep(old, new, count=1):
    global r
    assert old in r, old[:80]; r = r.replace(old, new, count)
rep('and, appended, from the official Landesrecht portals of Brandenburg, Bremen, Nordrhein-Westfalen and Sachsen (`jurisdiction=DE-<Land>`).',
    'and, appended, from the official Landesrecht portals of Brandenburg, Nordrhein-Westfalen and Sachsen (`jurisdiction=DE-<Land>`).\nBremen (DE-HB) was collected but is **held back** pending a licence review (see below).')
rep('| Laws / instruments | 10453 (federal 6127 + Landesrecht 4326) |', f'| Laws / instruments | {nl} (federal 6127 + Landesrecht {ll}) |')
rep('| Articles | 212715 (federal 129983 + Landesrecht 82732) |', f'| Articles | {na} (federal 129983 + Landesrecht {la}) |')
rep('## Landesrecht (state law) append — staged 2026-10-02 (not yet published)', f"## Landesrecht (state law) append — {time.strftime('%Y-%m-%d')} (DE-NW, DE-SN, DE-BB; DE-HB held)")
r = re.sub(r'\| Bremen \| DE-HB \|[^\n]*\n', '', r)
rep('| **Landesrecht total** | | | **4326** | | | **82732** | |', f'| **Landesrecht total (published)** | | | **{ll}** | | | **{la}** | |')
rep('hand check 20/20 laws (5 per Land) and random spot check 48/48 article rows matched the cached source pages;',
    'hand check 20/20 laws (5 per Land, incl. 5 held DE-HB laws) and random spot check 48/48 article rows (12 per Land) matched the cached source pages; 0 DE-HB rows in this release;')
held = """
**Held, not in this release:**

| Land | jurisdiction | laws | articles | status |
| --- | --- | ---: | ---: | --- |
| Bremen | DE-HB | 1166 | 18581 | HELD pending licence review: every document in the Transparenzportal Bremen Vorschriften database carries a "CC Namensnennung - Nicht-kommerziell - Keine Bearbeitung" (CC BY-NC-ND) label, while the portal Nutzungsbedingungen allow use "für alle Zwecke" with attribution. Decision pending; rows are kept locally. |

Not collected (see `PACK_META.json` and the gap list):"""
rep('\nNot collected (see `PACK_META.json` and the gap list):', held)
rep('- Coverage is 4 of 16 Länder (BB, HB, NW, SN).', '- Coverage is 3 of 16 Länder published (BB, NW, SN); HB collected but held pending licence review.')
rep('GVBl. Bbg) are authoritative.', 'GVBl. Bbg) are authoritative.')
rep(' DE-HB includes Ortsgesetze of the Stadtgemeinde Bremen as filed by the portal.', ' (Held DE-HB rows include Ortsgesetze of the Stadtgemeinde Bremen as filed by the portal.)')
rep('not staged: NW 7, SN 15, HB 1 (listed in the gap list).', 'not staged: NW 7, SN 15 (held HB: 1) (listed in the gap list).')
rep('- HB scope: university', '- HB (held) scope: university')
r = re.sub(r'\| DE-HB \| 18581 \|[^\n]*\n', '', r)
rep('- **Bremen (DE-HB)**: Public domain', '- **Bremen (DE-HB) — HELD, not published in this release**: Public domain')
assert 'DE-HB | 1166 | 529' not in r
(D / 'README.md').write_text(r)
# MANIFEST
m = (D / 'MANIFEST.md').read_text(); i = m.find('\n## Landesrecht append')
m = m[:i] if i >= 0 else m
m += f"""
## Landesrecht append ({time.strftime('%Y-%m-%dT%H:%M:%S%z')})
base_tip: {chk['live_tip']}
laws_rows_after: {nl}
articles_rows_after: {na}
per_jurisdiction: {', '.join(f"{j} {v['laws']}/{v['articles']}" for j, v in pj.items())}
appended_jurisdictions: DE-BB, DE-NW, DE-SN
held_local_only: DE-HB 1166/18581 (licence review: CC BY-NC-ND label vs. portal terms 'für alle Zwecke')
laws_sha256: {chk['laws_sha256_staged']}
articles_sha256: {chk['articles_sha256_staged']}
collector: scrapers/de_collect.py; parser: scrapers/de_build.py; dedupe: scrapers/de_finalize.py
never_thin_precheck: {'PASS' if chk['PASS'] else 'FAIL'}
"""
(D / 'MANIFEST.md').write_text(m)
# PACK_META
pm = json.load(open(D / 'PACK_META.json'))
pm.update({'staged_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'uploaded': False, 'variant': 'noHB', 'source_stage': chk['source_stage'],
    'subnational_laws_added': {j: v['laws'] for j, v in pj.items() if j != 'DE'}, 'subnational_articles_added': {j: v['articles'] for j, v in pj.items() if j != 'DE'},
    'held_local_only': {'DE-HB': {'laws': 1166, 'articles': 18581, 'reason': "licence review pending: every HB document labelled CC BY-NC-ND while portal terms say 'für alle Zwecke' with attribution"}},
    'totals': {'laws': nl, 'articles': na}, 'never_thin': chk, 'never_thin_independent': {'laws': chk['laws'], 'articles': chk['articles']}})
for k in ('dedupe',):
    if k in pm: pm[k]['note_noHB'] = 'dedupe numbers cover all 4 collected Länder; HB had 0 drops'
pm['schema_parity'] = {'laws': chk['laws']['schema_equal_incl_metadata'], 'articles': chk['articles']['schema_equal_incl_metadata'], 'PASS': chk['laws']['schema_equal_incl_metadata'] and chk['articles']['schema_equal_incl_metadata']}
(D / 'PACK_META.json').write_text(json.dumps(pm, indent=2, ensure_ascii=False))
print('README', n0, '->', len(r)); print(open(D / 'MANIFEST.md').read()[-900:])

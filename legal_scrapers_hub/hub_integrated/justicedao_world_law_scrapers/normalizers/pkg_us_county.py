#!/usr/bin/env python3
"""Normalize + dedupe US_COUNTY (us_local) staged output into a review package. Offline; no network; no push."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import gzip, json, glob, os, subprocess, hashlib, collections, re
SRC = str(_CORPORA) + '/us_local'; OUT = '/workspace/packaging/out/us_county_rc1'
def pdftext(p):
    try: return subprocess.run(['pdftotext', '-q', '-l', '300', '-enc', 'UTF-8', p, '-'], capture_output=True, timeout=120).stdout.decode('utf-8', 'replace')
    except Exception: return ''
LAWRX = re.compile(r'ordinance|code|resolution|zoning|regulation|charter|bylaw|statute|municipal', re.I)
rows = []; seen_sha = set(); seen_url = set(); c = collections.Counter(); seeds = collections.Counter()
for f in sorted(glob.glob(f'{SRC}/chunks/*.jsonl.gz')):
    for l in gzip.open(f, 'rt'):
        o = json.loads(l)
        if o.get('type') != 'seed': continue
        seeds[o.get('s')] += 1
        for d in o.get('docs') or []:
            c['docs_total'] += 1
            if d.get('s') != 'ok' or not d.get('sha256'): c['skip_not_ok'] += 1; continue
            if d['sha256'] in seen_sha: c['dup_sha'] += 1; continue
            fu = (d.get('final_url') or d['url']).rstrip('/')
            if fu in seen_url: c['dup_url'] += 1; continue
            seen_sha.add(d['sha256']); seen_url.add(fu)
            t = d.get('text') or ''
            if d.get('kind') == 'pdf' and not t and d.get('raw_path') and os.path.exists(d['raw_path']): t = pdftext(d['raw_path'])
            role = 'homepage' if d.get('via') == 'homepage' else ('law_candidate' if LAWRX.search((d.get('via') or '') + ' ' + (d.get('title') or '') + ' ' + fu) else 'linked_doc')
            c['role_' + role] += 1; c['kind_' + str(d.get('kind'))] += 1
            if d.get('kind') == 'pdf' and len(t.strip()) < 50: c['pdf_needs_ocr'] += 1
            rows.append(dict(id=d['sha256'][:24], jurisdiction=o.get('jurisdiction'), state_code=o.get('state_code'), family=o.get('family'),
                             title=d.get('title'), url=d['url'], final_url=d.get('final_url'), kind=d.get('kind'), content_type=d.get('content_type'),
                             doc_role=role, via=d.get('via'), depth=d.get('depth'), sha256=d['sha256'], text=t, text_chars=len(t),
                             ocr_needed=bool(d.get('kind') == 'pdf' and len(t.strip()) < 50), robots_disallowed=bool(d.get('robots_disallowed')),
                             retrieved_at=o.get('retrieved_at'), source='official county/municipal websites (US)'))
rows.sort(key=lambda r: (r['state_code'] or '', r['jurisdiction'] or '', r['final_url'] or ''))
n = 0
for i in range(0, len(rows), 2000):
    with gzip.open(f'{OUT}/data/train-{i // 2000:05d}.jsonl.gz', 'wt') as g:
        for r in rows[i:i + 2000]: g.write(json.dumps(r, ensure_ascii=False) + '\n'); n += 1
S = dict(rows=n, jurisdictions_with_docs=len({(r['state_code'], r['jurisdiction']) for r in rows}), states=len({r['state_code'] for r in rows}),
         seeds_total=sum(seeds.values()), seed_status=dict(seeds), doc_counts=dict(c), robots_disallowed_rows=sum(r['robots_disallowed'] for r in rows),
         text_chars_total=sum(r['text_chars'] for r in rows), dedupe='sha256 then final_url', pushed=False)
json.dump(S, open(f'{OUT}/summary.json', 'w'), indent=1)
open(f'{OUT}/README.md', 'w').write(f"""---
license: other
pretty_name: US county & local government documents (rc1, REVIEW ONLY)
---
# US_COUNTY rc1 — review package (not published)
Documents fetched from official US county/municipal websites (seed list of counties/municipalities), normalized one row per unique document.
- Rows: {n} (dedupe by sha256, then final URL); jurisdictions with docs: {S['jurisdictions_with_docs']}; states: {S['states']}.
- `doc_role`: `law_candidate` (ordinance/code/resolution/zoning keywords), `linked_doc`, or `homepage` (navigation page, not law). Filter to `law_candidate` for legal text.
- `ocr_needed=true`: scanned PDF with no text layer ({c['pdf_needs_ocr']} rows).
- `robots_disallowed`: robots.txt treated as advisory on government hosts; flag recorded per row.
- Coverage gaps: seeds with no code found, TLS failures, network errors and held hosts are listed in summary.json `seed_status`. Vendor-hosted codes (Municode etc.) are not included.
- Copyright: US government edicts are not copyrightable (edicts-of-government doctrine); non-edict material on these sites may be.
""")
print(json.dumps(S, indent=1))

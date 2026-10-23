"""Wave 10 staging builder — adapted from wave6_code/stage_wave6.py.

For each target country: merge local instruments additively by ID
(longest-text-wins) over the FRESH remote parquet snapshot in
../dedupe/{cc}_remote.parquet, with the wave-6 normalized-title duplicate
guard. Writes staged outputs to ../staging/{repo}/ (data/laws.parquet,
README.md, MANIFEST.md). Validation: unique IDs, zero empty texts, zero
texts under 300 chars among NEW rows (remote rows are grandfathered as in
wave 6, which asserted only uniqueness + non-empty overall).
Emits ../stats/staging_summary.json.
"""
import hashlib, json, os, sys
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common10 import TARGETS, WAVE10, norm

PARQUET_COLS = ['id', 'title', 'text', 'source_url', 'source_type', 'jurisdiction',
                'country', 'language', 'eli', 'date', 'date_issued', 'retrieved_at',
                'license', 'law_status', 'identifier', 'official_identifier',
                'article_count', 'json_path', 'metadata_json']
EXTRA_KEYS = ['schema_version', 'record_type', 'law_identifier', 'document_type',
              'is_current', 'canonical_law_url', 'article_extraction_status',
              'documents', 'metadata']
REPO_BASE = os.path.expanduser('~/.ipfs_datasets/legal-corpora')
STAGING = os.path.join(WAVE10, 'staging')

def load_local(cc):
    d = os.path.join(REPO_BASE, cc, 'instruments')
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if fn.endswith('.json'):
            try:
                out.append(json.load(open(os.path.join(d, fn))))
            except Exception:
                pass
    return out

def record_to_row(rec):
    row = {}
    for k in PARQUET_COLS:
        if k in ('json_path', 'metadata_json'):
            continue
        v = rec.get(k)
        row[k] = '' if v is None else v
    row['article_count'] = int(rec.get('article_count') or 0)
    row['json_path'] = f"instruments/{rec['id']}.json"
    meta = {k: rec.get(k) for k in EXTRA_KEYS if rec.get(k) is not None}
    row['metadata_json'] = json.dumps(meta, ensure_ascii=False) if meta else ''
    return row

def build_readme(display, total):
    return f"""---
license: other
language:
- en
- multilingual
tags:
- law
- legal
- ipfs
- datasets
---

# IPFS {display} Laws

Structured corpus of {display} national laws and legal instruments.

This dataset follows the same schema used by the IPFS Datasets legal corpora:

- `data/laws.parquet`: one row per law / legal instrument with full text.

Wave 10 build (2026-10-13): additive merge by instrument ID
(longest-text-wins) of the previously published corpus with newly collected
instruments (FAOLEX via Wayback CDX enumeration + live FAO PDF hosts, and
WIPO Lex), with a normalized-title duplicate guard.

## Counts

- laws_rows: {total}

## Schema (data/laws.parquet)

Columns: id, title, text, source_url, source_type, jurisdiction, country,
language, eli, date, date_issued, retrieved_at, license, law_status,
identifier, official_identifier, article_count, json_path, metadata_json

## Provenance

Primary legal texts are public legal information. Dataset compilation is a
research artifact; always verify against the official source before relying on
a text. Not legal advice.
"""

def stage(cc):
    repo_name, display = TARGETS[cc][0], TARGETS[cc][1]
    snap = os.path.join(WAVE10, 'dedupe', f'{cc}_remote.parquet')
    remote = pd.read_parquet(snap)
    # align remote columns to schema (fill any missing)
    for c in PARQUET_COLS:
        if c not in remote.columns:
            remote[c] = ''
    remote = remote[PARQUET_COLS]
    remote_ids = set(remote['id'].astype(str))
    remote_titles = {}
    for r in remote.itertuples():
        nt = norm(r.title)
        if nt:
            remote_titles[nt] = max(remote_titles.get(nt, 0),
                                    len(r.text) if isinstance(r.text, str) else 0)
    local = load_local(cc)
    by_id = {}
    for rec in local:
        rid = str(rec.get('id') or '')
        if not rid:
            continue
        txt = rec.get('text') or ''
        if rid not in by_id or len(txt) > len(by_id[rid].get('text') or ''):
            by_id[rid] = rec
    new_recs, skipped_id, skipped_title, skipped_short = [], 0, 0, 0
    for rid, rec in by_id.items():
        if rid in remote_ids:
            skipped_id += 1
            continue
        if len(rec.get('text') or '') < 300:
            skipped_short += 1
            continue
        nt = norm(rec.get('title'))
        if nt and nt in remote_titles and len(rec.get('text') or '') <= remote_titles[nt]:
            skipped_title += 1
            continue
        new_recs.append(rec)
    merged = remote.copy()
    if new_recs:
        new_df = pd.DataFrame([record_to_row(r) for r in new_recs], columns=PARQUET_COLS)
        merged = pd.concat([merged, new_df], ignore_index=True)
    merged = merged.sort_values('id').reset_index(drop=True)
    assert merged['id'].is_unique, f'{cc}: duplicate ids after merge'
    empty = int((merged['text'].fillna('').str.len() == 0).sum())
    assert empty == 0, f'{cc}: {empty} empty texts'
    short_new = int(sum(1 for r in new_recs if len(r.get('text') or '') < 300))
    assert short_new == 0
    stage_dir = os.path.join(STAGING, repo_name)
    os.makedirs(os.path.join(stage_dir, 'data'), exist_ok=True)
    table = pa.Table.from_pandas(merged, preserve_index=False)
    pq_path = os.path.join(stage_dir, 'data', 'laws.parquet')
    pq.write_table(table, pq_path, compression='zstd')
    sha = hashlib.sha256(open(pq_path, 'rb').read()).hexdigest()[:16]
    total = len(merged)
    with open(os.path.join(stage_dir, 'README.md'), 'w') as f:
        f.write(build_readme(display, total))
    with open(os.path.join(stage_dir, 'MANIFEST.md'), 'w') as f:
        f.write(f"""# Manifest

- repo: endomorphosis/{repo_name}
- updated_at: 2026-10-13
- wave: 10

## Files

### data/laws.parquet
- laws_rows: {total}
- laws_sha256: {sha}
- compression: zstd
- merge: additive by instrument ID (longest-text-wins) over the previously
  published parquet, plus a title-level duplicate guard.
- local_instruments_total: {len(by_id)}
- local_new_instruments: {len(new_recs)}
- local_skipped_already_on_hf_by_id: {skipped_id}
- local_skipped_title_duplicate: {skipped_title}
- local_skipped_short_text: {skipped_short}
""")
    return {'cc': cc, 'repo': repo_name, 'remote_rows': int(len(remote)),
            'local_total': len(by_id), 'new_added': len(new_recs),
            'skipped_id': skipped_id, 'skipped_title': skipped_title,
            'skipped_short': skipped_short,
            'merged_rows': int(total), 'sha16': sha, 'parquet': pq_path}

if __name__ == '__main__':
    ccs = sys.argv[1:] or list(TARGETS)
    summary = {}
    for cc in ccs:
        try:
            summary[cc] = stage(cc)
            print(cc, json.dumps(summary[cc]))
        except Exception as e:
            summary[cc] = {'error': str(e)}
            print(cc, 'ERROR', str(e)[:300])
    os.makedirs(os.path.join(WAVE10, 'stats'), exist_ok=True)
    json.dump(summary, open(os.path.join(WAVE10, 'stats', 'staging_summary.json'), 'w'), indent=1)

#!/usr/bin/env python3
"""Build the HF staging folder for endomorphosis/ipfs_estonia_municipal_laws (T1, status EXPAND) from index/laws_shards (offline, no network).
Layout and parquet format follow the CZ T1 push (endomorphosis/ipfs_czech_municipal_laws @34e3d33c5860): README.md card with configs
(default -> data/laws.parquet, articles -> data/articles.parquet), manifest.json, zstd parquet with the national hub schema (19 law cols / 9 article cols).
Usage: nice -n 19 /workspace/venv/bin/python /workspace/scripts/ee_t1_hf_stage.py  -> prints the staging dir"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, json, gzip, time, collections, hashlib
sys.path.insert(0, '/workspace/scripts')
import ee_t1_fix as F
import pyarrow as pa, pyarrow.parquet as pq
import pa_exit_guard as _EG  # exit guard (pa_exit_guard)
REPO = 'endomorphosis/ipfs_estonia_municipal_laws'
LAW_SCHEMA = pa.schema([(c, pa.int32() if c == 'article_count' else pa.string()) for c in
                        ['id', 'title', 'text', 'source_url', 'source_type', 'jurisdiction', 'country', 'language', 'eli', 'date', 'date_issued', 'retrieved_at',
                         'license', 'law_status', 'identifier', 'official_identifier', 'article_count', 'json_path', 'metadata_json']])
ART_SCHEMA = pa.schema([(c, pa.string()) for c in ['law_id', 'id', 'title', 'text', 'source_url', 'document_number', 'article_number', 'record_type', 'metadata_json']])
def main():
    ts = time.strftime('%Y%m%dT%H%M%S'); out = f'{_CORPORA}/hf-staging/ipfs_estonia_municipal_laws_t1_{ts}'; os.makedirs(f'{out}/data')
    man = json.load(open(F.MAN)); msha = F.sha_file(F.MAN); guard = F.Guard()
    lw = pq.ParquetWriter(f'{out}/data/laws.parquet', LAW_SCHEMA, compression='zstd'); aw = pq.ParquetWriter(f'{out}/data/articles.parquet', ART_SCHEMA, compression='zstd')
    LB = []; AB = []; S = collections.Counter(); lgs = collections.Counter(); dates = []; ret = []; law_ids = set(); art_ids = set(); bad = []
    def flush(force=False):
        if LB and (force or len(LB) >= 200): lw.write_table(pa.Table.from_pylist(LB, schema=LAW_SCHEMA)); LB.clear()
        if AB and (force or len(AB) >= 1000): aw.write_table(pa.Table.from_pylist(AB, schema=ART_SCHEMA)); AB.clear()
    for _, r in F.stream(F.SH, guard):
        law = r['law']; md = json.loads(law['metadata_json'])
        if law['id'] in law_ids: bad.append(f"dup law {law['id']}")
        law_ids.add(law['id']); LB.append({k: law[k] for k in LAW_SCHEMA.names})
        if law['article_count'] != len(r['articles']): bad.append(f"article_count {law['id']}")
        for a in r['articles']:
            if a['id'] in art_ids: bad.append(f"dup article {a['id']}")
            if a['law_id'] != law['id']: bad.append(f"orphan {a['id']}")
            art_ids.add(a['id']); AB.append({k: a[k] for k in ART_SCHEMA.names})
        S[f"status:{law['law_status']}"] += 1; S['canonical'] += md['is_canonical']; S['feeds'] += md['feeds_articles']; S['articles'] += len(r['articles'])
        S[f"ehak:{md['ehak_match']}"] += 1; S['att'] += md.get('attachments_stripped_n', 0); S['att_acts'] += bool(md.get('attachments_stripped_n'))
        S['titles'] += bool(md.get('title_note')); S['amb'] += bool(md['is_canonical'] and md['canonical_ambiguous']); S[f"type:{md.get('doc_type')}"] += 1
        S['superseded'] += bool(md.get('superseded_by_repeal_stub')); S['att_bytes'] += sum(e['bytes'] or 0 for e in md.get('attachments_stripped', []))
        lgs[md.get('ehak_successor_name') if md['ehak_match'] == 'successor' else md.get('lg_name')] += 1; S['lg_original:' + (md.get('lg_name') or '')] += 0
        if law.get('date'): dates.append(law['date'])
        if law.get('retrieved_at'): ret.append(law['retrieved_at'])
        flush()
    flush(True); lw.close(); aw.close(); guard.alive = False; del lw, aw  # exit guard (pa_exit_guard): writers closed first, then dropped
    n_laws, n_arts = len(law_ids), len(art_ids)
    assert not bad, bad[:5]
    assert n_laws == man['n_laws'] and n_arts == man['n_articles'], (n_laws, n_arts)
    rl = pq.ParquetFile(f'{out}/data/laws.parquet').metadata.num_rows; ra = pq.ParquetFile(f'{out}/data/articles.parquet').metadata.num_rows
    assert (rl, ra) == (n_laws, n_arts)
    n_lg_orig = sum(1 for k in S if k.startswith('lg_original:')); st = {k[7:]: v for k, v in S.items() if k.startswith('status:')}
    strip = man['fix']['strip']; src = man['source'] if isinstance(man.get('source'), dict) else {}
    card = CARD.format(n_laws=n_laws, n_arts=n_arts, cur=st.get('current', 0), rep=st.get('repealed', 0), hist=st.get('historical_version', 0), fut=st.get('future_version', 0),
                       can=S['canonical'], noncan=n_laws - S['canonical'], feeds=S['feeds'], amb=S['amb'], sup=S['superseded'], d0=min(dates)[:10], d1=max(dates)[:10],
                       rr=min(ret) if min(ret) == max(ret) else f'{min(ret)} – {max(ret)}', n_lg=n_lg_orig, n_lg_now=len(lgs), direct=S['ehak:direct'], succ=S['ehak:successor'], unm=S.get('ehak:unmapped', 0),
                       att=S['att'], att_acts=S['att_acts'], att_mb=S['att_bytes'] / 1e6, titles=S['titles'], tb0=strip['text_bytes_before'] / 1e6, tb1=strip['text_bytes_after'] / 1e6,
                       maxt=strip['max_text_bytes_after']['bytes'], msha=msha[:16], types=', '.join(f"{k[5:]} {v:,}" for k, v in sorted(S.items(), key=lambda kv: -kv[1]) if k.startswith('type:')))
    open(f'{out}/README.md', 'w').write(card)
    mf = dict(validation=dict(laws=n_laws, articles=n_arts, duplicate_law_ids=0, duplicate_article_ids=0, orphan_articles=0, article_count_mismatches=0, ok=True),
              source_manifest=F.MAN, source_manifest_sha256=msha, as_of_date=F.AS_OF, review=sorted(f for f in os.listdir(f'{F.ROOT}/review') if f.startswith('ee_t1_review_strip_') and f.endswith('.json'))[-1],
              built=ts, files={p: dict(bytes=os.path.getsize(f'{out}/{p}'), sha256=F.sha_file(f'{out}/{p}')) for p in ('README.md', 'data/laws.parquet', 'data/articles.parquet')})
    json.dump(mf, open(f'{out}/manifest.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps(dict(staging=out, laws=n_laws, articles=n_arts, stats=dict((k, v) for k, v in S.items() if not k.startswith('lg_original:')), guard=guard.stats()), ensure_ascii=False))
    _EG.release()  # exit guard (pa_exit_guard): gc before returning
CARD = '''---
pretty_name: Estonian municipal legal acts (Riigi Teataja IV, KOV) — tranche 1
license: other
license_name: ee-legal-acts-not-copyrighted
language:
- et
task_categories:
- text-retrieval
tags:
- legal
- law
- estonia
- municipal-law
- riigi-teataja
- official-texts
size_categories:
- n<1K
configs:
- config_name: default
  default: true
  data_files:
  - split: train
    path: data/laws.parquet
- config_name: articles
  data_files:
  - split: train
    path: data/articles.parquet
---

# Estonian municipal legal acts (Riigi Teataja IV) — `ipfs_estonia_municipal_laws`

> [!IMPORTANT]
> **Status: EXPAND (tranche 1 only).** This release holds the **{n_laws} RT IV local-government (KOV) records in the Riigi Teataja open-data file `xml.2024`**. The roughly **11,000 KOV acts in force** will follow in **tranche 2 (T2)**. Existing `id` values will not change.

Regulations (määrused) and other acts of Estonian local governments (vald / linn councils and governments), as published in Riigi Teataja part IV.

**Not legal advice.** This is not the official version. The authoritative text is the one published in Riigi Teataja ([riigiteataja.ee](https://www.riigiteataja.ee)).

## Legal basis

- **Autoriõiguse seadus § 5** (p 3): legislation and administrative documents (õigusaktid ja haldusdokumendid) are **not protected by copyright**.
- The `license` column carries this statement on every row.

## Snapshot

| Field | Value |
| --- | --- |
| Source | Riigi Teataja avaandmed **xml.2024**: https://www.riigiteataja.ee/avaandmed/ERT/xml.2024.zip (official open data; file generated 2026-10-04, sha256 `3157f628…5866`) |
| **Snapshot as of** | **2024-11-01** (latest publication date in xml.2024). `law_status`, `in_force_as_of` and the canonical version are all evaluated on this date, and every row carries `metadata_json.as_of_date = "2024-11-01"`. |
| Retrieved | `retrieved_at` {rr} (parse of the downloaded xml.2024.zip) |
| Records (laws) | {n_laws:,}: {cur} current, {hist} historical_version, {fut} future_version, {rep} repealed |
| Canonical / other versions | {can} canonical, {noncan} non-canonical (`version_of` → canonical) |
| Articles (§) | {n_arts:,}, from the {feeds} canonical non-repealed acts only |
| Local governments | {n_lg} issuer LGs (names as published); {n_lg_now} current EHAK municipalities after successor mapping |
| Act dates (`date`) | {d0} – {d1} (dates after 2024-11-01 are scheduled entries published by then: repeal notices carry their repeal effective date, future versions their start date) |
| Document types | {types} |

## Tranche 1 scope and modelling

- **T1 scope:** all {n_laws} RT IV KOV records in `xml.2024` (full texts and versions published in that file). It is not the full in-force set; that comes in T2 (about 11k acts).
- **Repeals are kept as metadata.** {rep} records are RT "Kehtetu" repeal notices. They have `law_status = "repealed"` and **no articles**. `metadata_json.repeal_*` holds the repealing act (`repeal_rt_ref`, `repeal_rt_akt_id`, `repeal_rt_url`, `repeal_published`, `repeal_effective`), and `repeal_in_effect_as_of` says whether the repeal had already taken effect on 2024-11-01.
- **Versions** of the same act (key: LG + doc type + act number + issuer + adoption date) are linked with `metadata_json.is_canonical`, `version_of`, `canonical_id`, `version_group_key` and `version_rank`.
  - **Canonical** = the version in force on 2024-11-01. Ties go to the latest valid_from, then the latest publication.
  - If no version was in force, the canonical is the latest version started by then, or else the earliest future version. These {amb} groups are flagged `canonical_ambiguous = true`.
  - {sup} versions that a later repeal notice cancelled before they took effect are `historical_version`, with `superseded_by_repeal_stub` and `valid_to_effective` set.
- `law_status` (as of 2024-11-01): `current` = in force on that date, `future_version` = starts later, `historical_version` = ended before (or never took effect), `repealed` = repeal notice. No row claims to be in force after 2024-11-01.

## EHAK (administrative units)

- `jurisdiction` is `EE-<EHAK code>`, using the Statistics Estonia **EHAK2026v1** code of the issuing local government (`metadata_json.ehak_code`, `ehak_match = "direct"`, {direct} records).
- Acts of local governments abolished in the 2017 administrative reform or later ({succ} records) are mapped to their **current successor**. The mapping uses Statistics Estonia's floating classifier **EHAK2017ap** (version 45, https://klassifikaatorid.stat.ee): settlement continuity plus official change notes, and every successor is validated against EHAK2026v1.
  - Fields: `ehak_match = "successor"`, `ehak_successor`, `ehak_successor_name`, `ehak_successor_county`, `ehak_successor_method`, `ehak_chain`, `ehak_abolished_code`, `ehak_change_note`.
  - The original name stays in `lg_name_original`.
  - Unmapped: {unm}.

## Attachments: placeholders only

Riigi Teataja embeds attachments (lisad, mostly PDF) in the XML as base64. In this dataset, **every embedded file is replaced by a placeholder** of the form

```
[attachment: <name>, <mime>, <bytes>, <sha256>]
```

`<bytes>` and `<sha256>` are those of the decoded file. {att} placeholders in {att_acts} records replace {att_mb:.0f} MB of decoded files, so total text drops from {tb0:.0f} MB to {tb1:.1f} MB; the largest text is {maxt:,} bytes. The files themselves are **not included**; the originals remain available from the source (Riigi Teataja). `metadata_json.attachments_stripped` lists each file with these fields:
- `name`, `name_source` (an XML attachment file name where it could be matched, else the text label)
- `mime`, `bytes`, `sha256`
- `label`, `location`

`metadata_json.attachments` keeps the attachment file names from the XML. In {titles} titles, Riigi Teataja appends a note (e.g. the "Kehtetu"-marked version note). That note was moved to `metadata_json.title_note` (+ `title_note_ts`), leaving a clean `title`.

## Configs and schema

Laws and articles have different schemas, so each one has its own config.

| config | rows | file |
| --- | --- | --- |
| `default` | {n_laws:,} laws | `data/laws.parquet` |
| `articles` | {n_arts:,} articles | `data/articles.parquet` |

```python
from datasets import load_dataset
laws = load_dataset("endomorphosis/ipfs_estonia_municipal_laws", split="train")
arts = load_dataset("endomorphosis/ipfs_estonia_municipal_laws", "articles", split="train")
```

- `laws` uses the same schema as the other ipfs_*_laws datasets:
  - `id` (`EE-RT-<RT akt id>`), `title`, `text`, `source_url` (riigiteataja.ee/akt/<id>), `source_type`
  - `jurisdiction` (`EE-<EHAK>`), `country`, `language`, `eli`, `date`, `date_issued`, `retrieved_at`, `license`
  - `law_status` (`current` / `historical_version` / `future_version` / `repealed`, as of 2024-11-01)
  - `identifier`, `official_identifier`, `article_count`, `json_path`
  - `metadata_json`: RT metadata (issuer, doc type, act number, adoption/publication/validity dates), `as_of_date`, version links, repeal fields, EHAK fields, `attachments`, `attachments_stripped` and `title_note`.
- `articles`: `law_id`, `id`, `title`, `text`, `source_url`, `document_number`, `article_number`, `record_type`, `metadata_json`. Articles exist only for canonical, non-repealed acts.

## Validation

- 0 duplicate law IDs, 0 duplicate article IDs, 0 orphan articles, 0 `article_count` mismatches.
- 0 texts over 1 MB, and no base64-looking run over 1,000 chars in any field.
- A 20-item hand check found 0 FAIL. Placeholders were checked by re-decoding the original blobs.
- Source manifest sha256 `{msha}…`.
'''
if __name__ == '__main__': _EG.run_guarded(main)  # exit guard (pa_exit_guard)

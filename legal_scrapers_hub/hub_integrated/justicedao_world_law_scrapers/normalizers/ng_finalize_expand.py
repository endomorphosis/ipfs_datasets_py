# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, json, re, os, hashlib, time
TS = sys.argv[1]
ST = f'{_CORPORA}/hf-staging/ipfs_nigeria_laws_expand_{TS}'; TIP = '{_CORPORA}/ng_expand/ng_tip'
R = json.load(open(f'/workspace/country-law-triage/ng_expand_review_{TS}.json'))
c = R['counts']; o = R['ocr']; s = R['sections']; wb = R['wayback_rows_live_copy']
rd = open(f'{TIP}/README.md').read()
rd = rd.replace('- 1K<n<10K', '- 10K<n<100K')
rd = rd.replace('| Snapshot date | 2026-09-10 |', '| Snapshot date | 2026-09-10 (base) + 2026-10-03 (NG national EXPAND, live gov.ng) |')
rd = rd.replace('| Collector | `scrapers/collect_ng.py` |', '| Collector | `scrapers/collect_ng.py` (base), `scrapers/ng_collect.py` (expand) |')
rd = rd.replace('| Laws / instruments | 222 |', f"| Laws / instruments | {c['laws_after']:,} |").replace('| Articles | 7,216 |', f"| Articles | {c['articles_after']:,} |")
rd = rd.replace("- `scrapers/collect_ng.py` — research collector used to build this snapshot.",
                "- `scrapers/collect_ng.py` — research collector used to build the base snapshot (222 instruments).\n- `scrapers/ng_collect.py` — collector for the 2026-10-03 national EXPAND (live gov.ng only).")
exp = f"""
## Expansion 2026-10-03 — national EXPAND (append-only)

- **Appended:** {c['laws_added']} instruments / {c['articles_added']:,} rows to the 222 / 7,216 base rows. The base rows are unchanged (never-thin).
- **Source:** live official government hosts only.
  - {c['laws_added'] - 1} Acts come from the National Assembly "Acts & Publications" catalog (`https://nass.gov.ng/documents/magazine`, downloads `https://nass.gov.ng/documents/download/<id>`).
  - 1 instrument (Child Rights Enforcement Procedure Rules 2015) comes from `justice.gov.ng`.
  - Fetched 2026-10-03 PT. robots.txt was obeyed, with at least 2.5 s between requests per host. No LII, mirror or web-archive copies were used.
- **Dedup:** against the base snapshot by NASS download id, normalized title + year / Cap number, and text-shingle similarity. 6 catalog items were left out: 3 identical re-uploads, 2 already in the base snapshot, and 1 whose official PDF is corrupt.
- **Text extraction:** `pdftotext` word boxes are used, with marginal notes separated from the body text.
  - Where the PDF text layer is missing or poor, pages are OCR'd with Tesseract (`{o['engine']}`, English, 300 dpi). This applied to {o['docs_with_any_ocr']} documents ({o['ocr_pages']:,} pages).
  - Each instrument records its method (`text_layer` / `text_layer+ocr_pages` / `ocr`) and quality metrics in `metadata_json.metadata.text_extraction`: dictionary-word ratio, garbage-character ratio, characters per page, and grade.
  - Method counts: {o['method_counts']}. Median dictionary-word ratio {o['dict_word_ratio']['median']}.
  - {len(o['below_threshold'])} instruments fall below the quality threshold (dict ≥ 0.85, garbage ≤ 0.02) and are flagged.
- **Rows:**
  - One row per numbered section (`<id>-section-<n>`). Court rules are split by Order.
  - The text before section 1 (title, explanatory memorandum, arrangement, long title) becomes a `preamble` annex row, and schedules become `schedule` annex rows.
  - Some scans lack reliable section numbers. In that case the complete text is kept as ONE `text` row and flagged `whole_text_fallback`.
  - Instruments where fewer sections were recovered than the document's own numbering are flagged `partial_sections`. In those, all the text is still present: unsplit sections are merged into their neighbours.
  - Section split status: {s['structure_counts']}.
- **Provenance note on the base snapshot:** 175 of the 222 base instruments were retrieved from web-archive (Wayback `id_`) copies of official nass.gov.ng / nigeriarights.gov.ng URLs. See `metadata_json.metadata.retrieval`; `source_url` shows the official URL. These rows are flagged and left unchanged.
"""
rd = rd.replace('## License / reuse', exp.strip('\n') + '\n\n## License / reuse')
rd = rd.replace('## Source\n\n- https://nass.gov.ng/', '## Source\n\n- https://nass.gov.ng/\n- https://justice.gov.ng/')
open(f'{ST}/README.md', 'w').write(rd)
mf = open(f'{TIP}/MANIFEST.md').read()
def sub(k, v):
    global mf; mf = re.sub(rf'(?m)^{k}: .*$', f'{k}: {v}', mf)
f = R['files']
sub('generated_utc', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())); sub('laws_rows', c['laws_after']); sub('articles_rows', c['articles_after'])
sub('laws_bytes', f['data/laws.parquet']['bytes']); sub('articles_bytes', f['data/articles.parquet']['bytes'])
sub('laws_sha256', f['data/laws.parquet']['sha256']); sub('articles_sha256', f['data/articles.parquet']['sha256'])
sub('laws_parquet', f'{ST}/data/laws.parquet'); sub('articles_parquet', f'{ST}/data/articles.parquet')
sub('collector', 'scrapers/collect_ng.py (base) + scrapers/ng_collect.py (expand 2026-10-03)')
sub('live_instruments', 47 + c['laws_added'])
mf = mf.rstrip('\n') + f"""
base_tip: 955aadec57e54fbed468ab793ab40538f2a7a99a
expand_batch: ng_expand_{TS} (append-only; base rows byte-identical)
expand_laws_added: {c['laws_added']}
expand_articles_added: {c['articles_added']}
expand_sources: nass.gov.ng/documents/magazine catalog (live), justice.gov.ng (live)
expand_ocr_docs: {o['docs_with_any_ocr']}
expand_whole_text_fallback: {s['structure_counts'].get('WHOLE_TEXT_FALLBACK', 0)}
expand_partial_sections: {s['structure_counts'].get('PARTIAL', 0)}
provenance_flag: 175 base instruments retrieved via Wayback id_ copies of official URLs (unchanged)
"""
open(f'{ST}/MANIFEST.md', 'w').write(mf)
print(open(f'{ST}/MANIFEST.md').read())

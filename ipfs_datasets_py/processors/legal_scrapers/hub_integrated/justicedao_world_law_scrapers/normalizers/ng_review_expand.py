#!/usr/bin/env python3
"""Verify + review the NG EXPAND staging (local only, no network)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, json, gzip, re, hashlib, time, collections, random, subprocess, tempfile, shutil, statistics as S
import pyarrow as pa, pyarrow.parquet as pq
TS = sys.argv[1]
B = '{_CORPORA}/ng_expand'; TIP = f'{B}/ng_tip'; TIPSHA = '955aadec57e54fbed468ab793ab40538f2a7a99a'
ST = f'{_CORPORA}/hf-staging/ipfs_nigeria_laws_expand_{TS}'
OUTJ = f'/workspace/country-law-triage/ng_expand_review_{TS}.json'; OUTM = OUTJ[:-5] + '.md'
build = json.load(open(f'{ST}.build.json'))
L0 = pq.read_table(f'{TIP}/data/laws.parquet'); A0 = pq.read_table(f'{TIP}/data/articles.parquet')
L1 = pq.read_table(f'{ST}/data/laws.parquet'); A1 = pq.read_table(f'{ST}/data/articles.parquet')
nL0, nA0 = L0.num_rows, A0.num_rows
R = dict(generated_pt=time.strftime('%Y-%m-%dT%H:%M:%S%z'), order='CoS 2026-10-04 NG EXPAND stage APPEND on 955aadec57e5; no upload, no IR',
         staging_dir=ST, hub=dict(repo='endomorphosis/ipfs_nigeria_laws', tip=TIPSHA, tip_confirmed_unchanged_pt='2026-10-04T12:49PT (HfApi.dataset_info sha; last_modified 2026-09-10 14:39 PT)'))
# ---- card / licence text ----
card = open(f'{TIP}/README.md').read()
fm = card.split('---')[1]
R['hub']['licence_card'] = dict(front_matter_license=re.search(r'license:\s*(\S+)', fm).group(1), license_name=re.search(r'license_name:\s*(\S+)', fm).group(1),
                                card_license_section=card.split('## License / reuse')[1].split('## Source')[0].strip(),
                                row_license_field=L0.column('license')[0].as_py())
# ---- counts ----
R['counts'] = dict(laws_before=nL0, articles_before=nA0, laws_after=L1.num_rows, articles_after=A1.num_rows, laws_added=L1.num_rows - nL0, articles_added=A1.num_rows - nA0)
newL = L1.slice(nL0).to_pylist(); newA = A1.slice(nA0).to_pylist()
R['new_law_ids'] = dict(count=len(newL), ids=[r['id'] for r in newL])
# ---- never-thin ----
nt = dict(laws_prefix_equal=L1.slice(0, nL0).equals(L0), articles_prefix_equal=A1.slice(0, nA0).equals(A0))
def rowhash(t): return [hashlib.sha256(json.dumps(r, sort_keys=True, ensure_ascii=False).encode()).hexdigest() for r in t.to_pylist()]
nt['laws_rowhash_equal'] = rowhash(L1.slice(0, nL0)) == rowhash(L0); nt['articles_rowhash_equal'] = rowhash(A1.slice(0, nA0)) == rowhash(A0)
hub_lids = set(L0.column('id').to_pylist()); hub_aids = set(A0.column('id').to_pylist())
nt['all_hub_law_ids_present'] = hub_lids <= set(L1.column('id').to_pylist()); nt['all_hub_article_ids_present'] = hub_aids <= set(A1.column('id').to_pylist())
nt['PASS'] = all(nt.values()); R['never_thin'] = nt
# ---- schema parity ----
R['schema_parity'] = dict(laws=L1.schema.equals(L0.schema, check_metadata=True), articles=A1.schema.equals(A0.schema, check_metadata=True),
                          laws_columns=L1.schema.names, articles_columns=A1.schema.names)
# ---- ids / orphans / article_count ----
lids = L1.column('id').to_pylist(); aids = A1.column('id').to_pylist()
cnt = collections.Counter(A1.column('law_id').to_pylist())
dupa = [k for k, v in collections.Counter(aids).items() if v > 1]; new_aid_set = {a['id'] for a in newA}
R['integrity'] = dict(duplicate_law_ids=[k for k, v in collections.Counter(lids).items() if v > 1], duplicate_article_ids_involving_new_rows=[k for k in dupa if k in new_aid_set],
                      duplicate_article_ids_preexisting_in_hub=dict(count=len(dupa), extra_rows=sum(v - 1 for v in collections.Counter(A0.column('id').to_pylist()).values() if v > 1), examples=dupa[:8], note='pre-existing in hub tip 955aadec57e5 (ng-fmj ACJA 2015 / Data Protection Bill 2018 part ids); left untouched (never-thin)'),
                      orphan_articles=sum(1 for x in A1.column('law_id').to_pylist() if x not in set(lids)),
                      laws_without_articles_new=[r['id'] for r in newL if cnt.get(r['id'], 0) == 0],
                      laws_without_articles_hub=sum(1 for r in L0.to_pylist() if cnt.get(r['id'], 0) == 0),
                      article_count_mismatch_new=[(r['id'], r['article_count'], cnt.get(r['id'], 0)) for r in newL if r['article_count'] != cnt.get(r['id'], 0)],
                      article_count_mismatch_all=sum(1 for r in L1.to_pylist() if r['article_count'] != cnt.get(r['id'], 0)),
                      new_article_ids_colliding_with_hub=sum(1 for a in newA if a['id'] in hub_aids))
# ---- field consistency ----
R['field_consistency'] = {c: dict(hub=sorted({str(v) for v in L0.column(c).to_pylist()}), new=sorted({str(r[c]) for r in newL})) for c in ('source_type', 'jurisdiction', 'country', 'language', 'license', 'law_status')}
R['field_consistency_ok'] = all(v['hub'] == v['new'] for v in R['field_consistency'].values())
R['record_types_new'] = dict(collections.Counter(a['record_type'] for a in newA)); R['record_types_hub'] = dict(collections.Counter(A0.column('record_type').to_pylist()))
# ---- empty / short ----
def rates(rows):
    n = len(rows); t = [len((a['text'] or '').strip()) for a in rows]
    return dict(n=n, empty=sum(1 for x in t if x == 0), lt20=sum(1 for x in t if x < 20), lt50=sum(1 for x in t if x < 50),
                lt20_pct=round(100 * sum(1 for x in t if x < 20) / n, 2) if n else None, lt50_pct=round(100 * sum(1 for x in t if x < 50) / n, 2) if n else None)
R['text_rates'] = dict(new_articles=rates(newA), hub_articles=rates(A0.to_pylist()), new_laws=rates(newL),
                       new_articles_lt50_examples=[(a['id'], a['text'][:60]) for a in newA if len((a['text'] or '').strip()) < 50][:15])
# ---- OCR / quality ----
M = {r['id']: json.loads(r['metadata_json']) for r in newL}
te = {k: v['metadata']['text_extraction'] for k, v in M.items()}
dicts = sorted(v['quality']['dict_word_ratio'] for v in te.values())
def q(p): return dicts[min(len(dicts) - 1, int(p * (len(dicts) - 1)))]
R['ocr'] = dict(method_counts=dict(collections.Counter(v['method'] for v in te.values())), docs_with_any_ocr=sum(1 for v in te.values() if v['n_ocr_pages']),
                ocr_pages=sum(v['n_ocr_pages'] for v in te.values()), engine=next((v['ocr_engine'] for v in te.values() if v['ocr_engine']), None),
                final_grade_counts=dict(collections.Counter(v['quality']['grade'] for v in te.values())),
                text_layer_grade_counts=dict(collections.Counter(v['quality_text_layer']['grade'] for v in te.values())),
                dict_word_ratio=dict(min=dicts[0], p10=q(0.1), p25=q(0.25), median=q(0.5), p90=q(0.9)),
                garbage_char_ratio_max=max(v['quality']['garbage_char_ratio'] for v in te.values()),
                threshold=next(iter(te.values()))['quality_threshold'],
                below_threshold=[dict(law_id=k, title=next(r['title'] for r in newL if r['id'] == k), method=v['method'], grade=v['quality']['grade'], **{x: v['quality'][x] for x in ('dict_word_ratio', 'garbage_char_ratio', 'chars_per_page')}) for k, v in te.items() if v['below_quality_threshold']])
R['ocr']['below_threshold_pct'] = round(100 * len(R['ocr']['below_threshold']) / len(te), 1)
# ---- sections ----
part, whole = [], []
for r in newL:
    ss = M[r['id']]['metadata']['section_split']; fl = M[r['id']]['metadata']['flags']
    e = dict(law_id=r['id'], title=r['title'][:90], sections=ss['n_sections'], doc_own_numbering=ss['doc_own_numbering'], arrangement_count=ss['arrangement_count'], n_missing=ss['n_missing'], splitter=ss['splitter'], method=te[r['id']]['method'])
    if fl['whole_text_fallback']: whole.append(e)
    elif fl['partial_sections']: part.append(e)
R['sections'] = dict(structure_counts=dict(collections.Counter(M[r['id']]['metadata']['flags']['structure'] for r in newL)), partial=part, whole_text_fallback=whole,
                     resplit_v2_used=[k for k, v in build['resplit'].items() if v['used'] == 'v2' and k in M],
                     note='structure OK = sections >= 90% of the document\'s own numbering (ARRANGEMENT OF SECTIONS count, else highest number) with <=10% numbers missing; PARTIAL rows keep all text (unsplit sections merged into neighbours). 5960 kept as ONE whole-text row per CoS ruling.')
# ---- fragments ----
frag = []
for r in newL:
    t = te[r['id']]; fl = M[r['id']]['metadata']['flags']
    if t['pages'] <= 1 or len(r['text']) < 2500 or fl.get('catalog_title_vs_content'):
        frag.append(dict(law_id=r['id'], title=r['title'], pages=t['pages'], chars=len(r['text']), doc_type=M[r['id']]['document_type'], note=fl.get('catalog_title_vs_content'),
                         has_citation_or_enactment=bool(re.search(r'(?i)cited\s+as|enacted\s+by', r['text']))))
R['possible_fragments'] = frag
R['dedup'] = build['dedup']; R['dropped'] = build['dedup']['dropped']
# ---- post-collect hand check (20 random new laws, fixed seed) ----
rnd = random.Random(20261004); sample = sorted(rnd.sample([r['id'] for r in newL], 20))
words = set(w.strip().lower() for w in open('/usr/share/dict/words') if w.strip().isalpha())
def toks(t): return [w for w in re.findall(r'[a-z]{4,}', (t or '').lower())]
hc = []
byid = {r['id']: r for r in newL}; arts = collections.defaultdict(list)
for a in newA: arts[a['law_id']].append(a)
for lid in sample:
    p = f'{B}/cache/pdf/{lid}.pdf.gz'; isdoc = False
    if not os.path.exists(p): p = f'{B}/cache/pdf/{lid}.doc.gz'; isdoc = True
    raw = gzip.decompress(open(p, 'rb').read()); d = tempfile.mkdtemp(prefix='nghc_')
    src = f'{d}/x.doc' if isdoc else f'{d}/x.pdf'; open(src, 'wb').write(raw)
    if isdoc:
        subprocess.run(['soffice', '--headless', '--convert-to', 'pdf', '--outdir', d, src], capture_output=True, timeout=300); src = f'{d}/x.pdf'
    pages = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', src], capture_output=True, text=True).stdout).group(1))
    rawt = subprocess.run(['pdftotext', src, '-'], capture_output=True).stdout.decode('utf-8', 'replace'); shutil.rmtree(d, ignore_errors=True)
    law = byid[lid]; m = M[lid]; t = te[lid]
    rt = set(w for w in toks(rawt) if w in words); lt = set(toks(law['text'])); at = set(toks(' '.join(a['text'] for a in arts[lid])))
    cov_raw = round(len(rt & lt) / len(rt), 3) if rt else None
    lt_d = set(w for w in lt if w in words); cov_art = round(len(lt_d & at) / len(lt_d), 3) if lt_d else None
    last_dw = [w for w in toks(rawt) if w in words][-12:]
    tail_ok = (sum(1 for w in last_dw if w in lt) >= 0.6 * len(last_dw)) if last_dw else None
    ss = m['metadata']['section_split']; fl = m['metadata']['flags']
    verdict = 'OK'
    notes = []
    if pages != t['pages']: verdict = 'CHECK'; notes.append(f'page count {pages} vs staged {t["pages"]}')
    if t['method'] == 'text_layer' and cov_raw is not None and cov_raw < 0.9: verdict = 'CHECK'; notes.append('text-layer coverage < 0.90')
    if cov_art is not None and cov_art < 0.9: verdict = 'CHECK'; notes.append('articles cover < 90% of law text vocabulary')
    if tail_ok is False and t['method'] == 'text_layer': verdict = 'CHECK'; notes.append('end of document not found in staged text')
    if fl['partial_sections']: notes.append(f"partial sections {ss['n_sections']}/{ss['doc_own_numbering']}")
    if fl['whole_text_fallback']: notes.append('whole-text fallback')
    hc.append(dict(law_id=lid, title=law['title'][:80], year=m['metadata'].get('year'), pdf_pages=pages, staged_pages=t['pages'], method=t['method'], n_ocr_pages=t['n_ocr_pages'],
                   grade=t['quality']['grade'], dict_word_ratio=t['quality']['dict_word_ratio'], raw_text_layer_dict_words=len(rt),
                   coverage_raw_textlayer_in_staged=cov_raw, coverage_lawtext_in_articles=cov_art, document_end_found=tail_ok,
                   sections=ss['n_sections'], doc_own_numbering=ss['doc_own_numbering'], rows=law['article_count'], verdict=verdict, notes='; '.join(notes)))
R['post_collect_handcheck'] = dict(seed=20261004, n=len(hc), ok=sum(1 for x in hc if x['verdict'] == 'OK'), check=sum(1 for x in hc if x['verdict'] != 'OK'),
                                   method='re-extracted cached official PDF (pdfinfo + pdftotext raw); coverage = share of dictionary words of the raw text layer present in staged law text (meaningful for text-layer docs; for OCR docs the raw layer is the poor/absent layer that triggered OCR); articles coverage = share of law-text dictionary vocabulary present in the article rows; end check = last 12 dictionary words of raw layer found in staged text',
                                   docs=hc)
# ---- Wayback rows: live official copy? (from existing catalog/probe/cache data only; no crawl) ----
STOP = set('act acts bill the of and for to a an in on etc establishment amendment repeal as amended federal republic nigeria no cap lfn'.split())
def ntitle(t):
    t = re.sub(r'[^a-z0-9 ]', ' ', (t or '').lower()); return ' '.join(w for w in t.split() if w not in STOP and not re.fullmatch(r'(19|20)\d\d', w))
def shingles(t, k=5, maxw=30000):
    w = re.findall(r'[a-z]{2,}', (t or '').lower())[:maxw]; return {hash(' '.join(w[i:i + k])) for i in range(max(0, len(w) - k + 1))}
cat = json.load(open(f'{B}/index/nass_magazine_catalog.json')); media = json.load(open(f'{B}/index/justice_pdf_media.json'))
live = {}
for f in os.listdir(f'{B}/out'):
    d = json.load(gzip.open(f'{B}/out/{f}'))
    if len(d['text'].strip()) >= 500: live[d['law_id']] = dict(url=d['source_url'], title=d['title'], sh=shingles(d['text']), fetched_at=d['fetch'].get('fetched_at'), status='HTTP 200 PDF fetched 2026-10-03')
arch = []
for r in L0.to_pylist():
    m = json.loads(r['metadata_json']); md = m['metadata']
    if md.get('retrieval', {}).get('method') != 'archive': continue
    arch.append(r)
wb = []
for r in arch:
    m = json.loads(r['metadata_json']); md = m['metadata']; sh = shingles(r['text']); head = ' ' + ' '.join(re.findall(r'[a-z0-9]+', r['text'][:3000].lower())) + ' '
    best = None
    for lid, v in live.items():
        a, b = len(sh & v['sh']), len(sh | v['sh']); j = a / b if b else 0; c = a / min(len(sh), len(v['sh'])) if sh and v['sh'] else 0
        nt_ = ntitle(v['title']); yr = (re.findall(r'(19|20)\d\d', v['title']) and re.findall(r'\b((?:19|20)\d\d)\b', v['title'])[-1]) or None
        tih = bool(nt_) and all(f' {w} ' in head for w in nt_.split()) and (yr is None or yr in head)
        if j >= 0.6 or (tih and j >= 0.3):
            if best is None or j > best['jaccard']: best = dict(official_url=v['url'], evidence=f'content match to live-fetched official copy ({v["status"]})', matched_doc=lid, matched_title=v['title'], jaccard=round(j, 3), containment=round(c, 3), confidence='high' if j >= 0.6 else 'medium (same title+year printed; text differs, e.g. gazette vs NASS print)')
    if best is None:
        did = md.get('nass_download_id')
        for row in cat:
            if did and row[6] == did and r['id'] == f'ng-nass-{did}':
                best = dict(official_url=f'https://nass.gov.ng/documents/download/{did}', evidence='same NASS download id listed in live Acts & Publications catalog JSON (2026-10-03); not re-fetched', matched_title=row[0], confidence='high (same id + same URL scheme)')
    if best is None:
        for row in cat:
            nt_ = ntitle(row[0]); yrs = re.findall(r'\b((?:19|20)\d\d)\b', row[0])
            head8 = ' ' + ' '.join(re.findall(r'[a-z0-9]+', (r['title'] + ' ' + r['text'][:800]).lower())) + ' '
            if m.get('document_type') != 'bill' and nt_ and yrs and len(nt_.split()) >= 2 and all(f' {w} ' in head8 for w in nt_.split()) and yrs[-1] in head8 and not re.search(r'(?i)\bbill\b', r['title']):
                best = dict(official_url=f'https://nass.gov.ng/documents/download/{row[6]}', evidence='catalog title+year printed in hub row opening text; catalog item listed live 2026-10-03; not content-verified', matched_title=row[0], confidence='low-medium'); break
    if best is None:
        u = (md.get('retrieval', {}).get('used_url') or '') + ' ' + (m.get('canonical_law_url') or '')
        for it in media:
            fn = it['source_url'].rsplit('/', 1)[-1].lower()
            if fn and fn in u.lower(): best = dict(official_url=it['source_url'], evidence='same file listed in justice.gov.ng WP media API (2026-10-03)', confidence='high'); break
    wb.append(dict(law_id=r['id'], title=r['title'][:90], document_type=m.get('document_type'), wayback_used_url=md.get('retrieval', {}).get('used_url'),
                   original_official_url=m.get('canonical_law_url'), live_official_copy=best))
matched = [x for x in wb if x['live_official_copy']]; unmatched = [x for x in wb if not x['live_official_copy']]
R['wayback_rows_live_copy'] = dict(total_wayback_rows=len(wb), with_live_official_copy=len(matched), without_match=len(unmatched),
                                   by_confidence=dict(collections.Counter(x['live_official_copy']['confidence'].split(' ')[0] for x in matched)),
                                   unmatched_by_document_type=dict(collections.Counter(x['document_type'] for x in unmatched)),
                                   method='matched ONLY against data already on disk: 146 NASS/justice docs fetched live 2026-10-03 (content shingle Jaccard / title+year), NASS Acts & Publications catalog JSON (171 items), justice.gov.ng WP media list (142 PDFs). No crawl. Old-scheme URLs nass.gov.ng/document/download/<n> were NOT probed, so "no match" means "no evidence on disk", not "dead".',
                                   matched=[dict(law_id=x['law_id'], official_url=x['live_official_copy']['official_url'], confidence=x['live_official_copy']['confidence'], evidence=x['live_official_copy']['evidence'], matched_title=x['live_official_copy'].get('matched_title'), jaccard=x['live_official_copy'].get('jaccard')) for x in matched],
                                   unmatched=[dict(law_id=x['law_id'], title=x['title'], document_type=x['document_type'], original_official_url=x['original_official_url']) for x in unmatched])
# ---- verdict ----
chk = dict(never_thin=R['never_thin']['PASS'], schema_parity=R['schema_parity']['laws'] and R['schema_parity']['articles'], no_new_dup_ids=not R['integrity']['duplicate_law_ids'] and not R['integrity']['duplicate_article_ids_involving_new_rows'],
           no_orphans=R['integrity']['orphan_articles'] == 0, article_count_consistent=R['integrity']['article_count_mismatch_all'] == 0, field_consistency=R['field_consistency_ok'],
           new_laws_have_rows=not R['integrity']['laws_without_articles_new'], ocr_below_threshold_le_20pct=R['ocr']['below_threshold_pct'] <= 20)
R['checks'] = chk; R['verdict'] = 'STAGED_PASS' if all(chk.values()) else 'STAGED_WITH_ISSUES'
R['files'] = {f: dict(bytes=os.path.getsize(f'{ST}/{f}'), sha256=hashlib.sha256(open(f'{ST}/{f}', 'rb').read()).hexdigest()) for f in ('data/laws.parquet', 'data/articles.parquet')}
json.dump(R, open(OUTJ, 'w'), indent=1, ensure_ascii=False, default=list)
print(json.dumps(dict(verdict=R['verdict'], checks=chk, counts=R['counts'], ocr={k: R['ocr'][k] for k in ('method_counts', 'final_grade_counts', 'below_threshold_pct', 'dict_word_ratio')},
                      sections=R['sections']['structure_counts'], rates=R['text_rates']['new_articles'], hc=(R['post_collect_handcheck']['ok'], R['post_collect_handcheck']['check']),
                      wb={k: R['wayback_rows_live_copy'][k] for k in ('total_wayback_rows', 'with_live_official_copy', 'without_match', 'by_confidence', 'unmatched_by_document_type')}), indent=1))

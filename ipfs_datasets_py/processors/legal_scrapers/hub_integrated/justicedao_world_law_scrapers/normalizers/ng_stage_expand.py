#!/usr/bin/env python3
"""Stage NG national EXPAND as an APPEND on endomorphosis/ipfs_nigeria_laws @955aadec57e5. Local only (no network).
Never-thin: hub rows are copied verbatim (Arrow concat of the original tables); new rows appended."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, json, gzip, re, hashlib, time, shutil, collections, random, subprocess, tempfile
import types
try:
    import requests
except ImportError:
    _r = types.ModuleType('requests'); _r.Session = lambda *a, **k: types.SimpleNamespace(headers={}); sys.modules['requests'] = _r  # no network used in staging
sys.path.insert(0, '/workspace/scripts'); import ng_collect as N
import pyarrow as pa, pyarrow.parquet as pq
TS = sys.argv[1]
B = '{_CORPORA}/ng_expand'; TIP = f'{B}/ng_tip'
TIPSHA = '955aadec57e54fbed468ab793ab40538f2a7a99a'
ST = f'{_CORPORA}/hf-staging/ipfs_nigeria_laws_expand_{TS}'
os.makedirs(f'{ST}/data', exist_ok=True); os.makedirs(f'{ST}/scrapers', exist_ok=True)
L0 = pq.read_table(f'{TIP}/data/laws.parquet'); A0 = pq.read_table(f'{TIP}/data/articles.parquet')
hubL = L0.to_pylist(); hubA = A0.to_pylist()
LIC = hubL[0]['license']; assert len({r['license'] for r in hubL}) == 1
T = {json.loads(l)['law_id']: json.loads(l) for l in open(f'{B}/index/ng_targets.jsonl')}
OCR_ENGINE = subprocess.run(['tesseract', '--version'], capture_output=True, text=True).stdout.split('\n')[0].strip()
QTH = dict(dict_word_ratio_min=0.85, garbage_char_ratio_max=0.02, chars_per_page_min=150)
# ---------- helpers ----------
STOP = set('act acts bill the of and for to a an in on etc establishment amendment repeal as amended federal republic nigeria no cap lfn'.split())
def ntitle(t):
    t = re.sub(r'[^a-z0-9 ]', ' ', (t or '').lower()); return ' '.join(w for w in t.split() if w not in STOP and not re.fullmatch(r'(19|20)\d\d', w))
def year_of(t):
    m = re.findall(r'\b(19[5-9]\d|20[0-2]\d)\b', t or ''); return m[-1] if m else None
def caps(t): return set(re.findall(r'(?i)\bcap\.?\s*([a-z]?\s?\d+[a-z]?)', t or ''))
def shingles(t, k=5, maxw=30000):
    w = re.findall(r'[a-z]{2,}', (t or '').lower())[:maxw]
    return {hash(' '.join(w[i:i + k])) for i in range(max(0, len(w) - k + 1))}
def jac(a, b): return len(a & b) / len(a | b) if a and b else 0.0
def cont(a, b): return len(a & b) / min(len(a), len(b)) if a and b else 0.0
def is_amend(t): return bool(re.search(r'(?i)amendment|amend', t or ''))
def score(st):
    own = st.get('arrangement_count') or st['max_section']
    n, miss = st['n_sections'], st['n_missing']
    if st.get('split_fallback_whole_text'): return -1e9
    return min(n, own or n) - 2 * miss - 2 * max(0, n - (own or n))
def structure(st):
    if st.get('split_fallback_whole_text'): return 'WHOLE_TEXT_FALLBACK'
    own = st.get('arrangement_count') or st['max_section']
    if not own: return 'NO_NUMBERING'
    r = st['n_sections'] / own
    if r >= 0.9 and st['n_missing'] <= max(1, 0.1 * st['max_section']) and st['n_sections'] <= 1.1 * own + 1: return 'OK'
    return 'PARTIAL'
def to_utc(s):
    try: return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.mktime(time.strptime(s[:19], '%Y-%m-%dT%H:%M:%S')) - 0)) if s.endswith('-0700') is False else \
        time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(int(time.mktime(time.strptime(s[:19], '%Y-%m-%dT%H:%M:%S')))))
    except Exception: return s
def src_bytes(lid):
    p = f'{B}/cache/pdf/{lid}.pdf.gz'
    if not os.path.exists(p): p = f'{B}/cache/pdf/{lid}.doc.gz'
    return gzip.decompress(open(p, 'rb').read()), p
# ---------- build new records ----------
recs = {}
for f in sorted(os.listdir(f'{B}/out')):
    d = json.load(gzip.open(f'{B}/out/{f}')); recs[d['law_id']] = d
assert len(recs) == 146 and set(recs) == set(T)
resplit = {}
for lid, d in recs.items():
    smeta = dict(title=d['title'], year=d.get('year'), backend=d['backend'], source_host=d['host'], toc_source='document', catalog=d.get('catalog'))
    rows2, st2 = N.split_act(d['text'], lid, d['source_url'], smeta)
    st1 = d['split']; use_new = score(st2) > score(st1)
    if lid == 'ng-nass-5960': use_new = False  # CoS ruling: keep as ONE whole-text row
    resplit[lid] = dict(old=dict(n=st1['n_sections'], miss=st1['n_missing'], own=st1.get('arrangement_count') or st1['max_section']),
                        new=dict(n=st2['n_sections'], miss=st2['n_missing'], own=st2.get('arrangement_count') or st2['max_section']), used='v2' if use_new else 'v1')
    if use_new:
        d['rows'], d['split'] = rows2, dict(st2, struct_ocr_tried=st1.get('struct_ocr_tried'), struct_ocr_used=st1.get('struct_ocr_used'))
# ---------- completeness guard: article rows + preamble must cover the whole law text ----------
def nz(x): return re.sub(r'\s+', '', x or '')
ENACTN = re.compile(r'(?i)(beit)?enactedbythe(national|senate)')
def mkrow(lid, url, unit, nr, title, text, rtype, d):
    m = dict(law_identifier=lid, unit=unit, title=d['title'], year=d.get('year'), backend=d['backend'], source_host=d['host'], toc_source='document')
    return dict(law_id=lid, id=f'{lid}-{unit}' + (f'-{nr}' if nr else ''), title=title, text=text, source_url=url, document_number=title, article_number=nr if rtype == 'article' else None,
                record_type=rtype, metadata_json=json.dumps(m, ensure_ascii=False))
guard = {}
for lid, d in recs.items():
    text = d['text']; T_ = nz(text); rows = d['rows']; st = d['split']
    whole = bool(st.get('split_fallback_whole_text')) or lid == 'ng-nass-5960'
    reason = None
    if not whole and rows:
        first = nz(rows[0]['text'])[:80]; pos = T_.find(first) if first else -1
        m = ENACTN.search(T_); epos = m.start() if m else None
        covered = (pos if pos >= 0 else 0) + sum(len(nz(r['text'])) for r in rows)
        own_ = st.get('arrangement_count') or st['max_section']
        if own_ and own_ >= 8 and st['n_sections'] < 0.25 * own_: reason = f"split recovered only {st['n_sections']} of {own_} numbered sections (would mislabel the act as 'Section 1')"
        elif pos < 0: reason = 'first section not locatable in law text'
        elif epos is not None and pos - epos > max(1500, 0.15 * len(T_)): reason = f'first section starts {pos - epos} chars after the enacting formula (split anchored in a list/schedule)'
        elif covered < 0.97 * len(T_): reason = f'rows cover only {covered / len(T_):.2f} of the law text'
        if reason: whole = True
        elif pos >= 20:
            # text before section 1 (title, explanatory memorandum, arrangement of sections, long title, enacting formula)
            k = 0; acc = 0; L_ = text.split('\n')
            pre_lines = []
            for ln in L_:
                if acc >= pos: break
                pre_lines.append(ln); acc += len(nz(ln))
            pre = re.sub(r'\n{3,}', '\n\n', '\n'.join(x.rstrip() for x in pre_lines)).strip()
            if pre: rows = [mkrow(lid, d['source_url'], 'preamble', None, 'Preamble (title, explanatory memorandum, arrangement, long title)', pre, 'annex', d)] + rows
    if whole:
        # ONE whole-text row holding the complete law text (CoS ruling for 5960; also used when no reliable split exists)
        rows = [mkrow(lid, d['source_url'], 'text', '1', 'Whole text (no reliable section numbering)', re.sub(r'\n{3,}', '\n\n', text).strip(), 'article', d)]
        st = dict(st, split_fallback_whole_text=True, whole_text_reason=reason or ('CoS ruling: keep as one whole-text row' if lid == 'ng-nass-5960' else 'no section numbers recoverable'),
                  sections_before_fallback=st['n_sections'], n_sections=0, n_missing=0, missing_numbers=[], n_annex=0)
    cov = sum(len(nz(r['text'])) for r in rows) / max(1, len(T_))
    guard[lid] = dict(whole=whole, reason=reason, coverage=round(cov, 3))
    d['rows'], d['split'] = rows, st
# ---------- dedup ----------
hub_ids = {r['id'] for r in hubL}; hub_aids = {a['id'] for a in hubA}
hub_info = []
for r in hubL:
    m = json.loads(r['metadata_json']); md = m.get('metadata', {})
    hub_info.append(dict(id=r['id'], title=r['title'], nt=ntitle(r['title']), year=year_of(r['title']) or year_of(r['text'][:3000]), caps=caps(r['title']),
                         did=md.get('nass_download_id'), sh=shingles(r['text']), head=r['text'][:3000], retrieval=md.get('retrieval', {}).get('method'),
                         used_url=md.get('retrieval', {}).get('used_url'), canon=m.get('canonical_law_url'), doc_type=m.get('document_type')))
new_sh = {lid: shingles(d['text']) for lid, d in recs.items()}
sha = {lid: hashlib.sha256(src_bytes(lid)[0]).hexdigest() for lid in recs}
dedup = dict(id_collisions=[], nass_id_matches=[], title_year_matches=[], content_matches=[], intra_batch=[], dropped=[], kept_near_matches=[])
drop = {}
# intra-batch identical source files / identical text
by_sha = collections.defaultdict(list)
for lid in sorted(recs, key=lambda x: (T[x].get('uploaded') or '', x)): by_sha[sha[lid]].append(lid)
for s_, ls in by_sha.items():
    if len(ls) > 1:
        dedup['intra_batch'].append(dict(sha256=s_, law_ids=ls, kept=ls[0], dropped=ls[1:]))
        for x in ls[1:]: drop[x] = f'intra-batch duplicate of {ls[0]} (identical source file sha256)'
ids_sorted = sorted(recs)
for i, a in enumerate(ids_sorted):
    for b in ids_sorted[i + 1:]:
        if a in drop or b in drop: continue
        j = jac(new_sh[a], new_sh[b])
        if j >= 0.8:
            keep, dr = sorted([a, b], key=lambda x: (T[x].get('uploaded') or '', x))
            dedup['intra_batch'].append(dict(law_ids=[a, b], jaccard=round(j, 3), kept=keep, dropped=[dr])); drop[dr] = f'intra-batch duplicate of {keep} (text Jaccard {j:.2f})'
for lid, d in recs.items():
    t = T[lid]; did = t.get('nass_download_id'); nt = ntitle(t['title']); yr = t.get('year') or year_of(t['title']); cp = caps(t['title'])
    if lid in hub_ids: dedup['id_collisions'].append(lid); drop[lid] = 'id collision with hub'
    for h in hub_info:
        j = jac(new_sh[lid], h['sh']); c = cont(new_sh[lid], h['sh'])
        idm = did and h['did'] == did
        tym = nt and nt == h['nt'] and yr and yr == h['year']
        capm = bool(cp & h['caps'])
        if idm: dedup['nass_id_matches'].append(dict(new=lid, hub=h['id'], hub_url=h['canon'], jaccard=round(j, 3), title_new=t['title'], title_hub=h['title'][:100]))
        if tym or capm: dedup['title_year_matches'].append(dict(new=lid, hub=h['id'], title_new=t['title'], title_hub=h['title'][:100], year=yr, cap_match=capm, jaccard=round(j, 3)))
        if j >= 0.3 or c >= 0.7:
            dedup['content_matches'].append(dict(new=lid, hub=h['id'], jaccard=round(j, 3), containment=round(c, 3), title_new=t['title'], title_hub=h['title'][:100], hub_retrieval=h['retrieval']))
        hh = ' ' + ' '.join(re.findall(r'[a-z0-9]+', h['head'].lower())) + ' '
        tih = bool(nt) and all(f' {w} ' in hh for w in nt.split()) and bool(yr) and yr in hh  # new title + year printed in the hub row's opening text
        dup = j >= 0.6 or ((idm or tym) and j >= 0.3) or (tih and c >= 0.6 and j >= 0.3)
        if tih and (j >= 0.3 or c >= 0.6): dedup['title_year_matches'].append(dict(new=lid, hub=h['id'], title_new=t['title'], title_hub=h['title'][:100], year=yr, how='title+year in hub opening text', jaccard=round(j, 3), containment=round(c, 3)))
        if dup and lid not in drop:
            drop[lid] = f'duplicate of hub {h["id"]} (jaccard {j:.2f}{", same NASS id" if idm else ""}{", same title+year" if tym else ""})'
        elif (tym or (c >= 0.7 and j < 0.6)) and lid not in drop:
            dedup['kept_near_matches'].append(dict(new=lid, hub=h['id'], jaccard=round(j, 3), containment=round(c, 3), why='title+year' if tym else 'containment', title_new=t['title'], title_hub=h['title'][:100]))
for lid, d in recs.items():
    if len(d['text'].strip()) < 500 and lid not in drop:
        drop[lid] = f"no usable text: official PDF is corrupt/unreadable ({len(d['text'].strip())} chars extracted from {d['pages']} pages, text layer and OCR)"
dedup['dropped'] = [dict(law_id=k, reason=v, title=T[k]['title']) for k, v in sorted(drop.items())]
keep = [lid for lid in sorted(recs, key=lambda x: (T[x]['host'], int(T[x].get('nass_download_id') or 0), x)) if lid not in drop]
# ---------- rows ----------
newL, newA, flags = [], [], {}
for lid in keep:
    d = recs[lid]; t = T[lid]; st = d['split']; q = d['quality']
    raw, _ = src_bytes(lid)
    struct = structure(st); own = st.get('arrangement_count') or st['max_section']
    head = d['text'][:2500]
    doc_type = 'rules' if lid.startswith('ng-fmj-') else ('bill' if re.search(r'(?i)sponsored\s+by', head) else 'statute')
    below = q['dict_word_ratio'] < QTH['dict_word_ratio_min'] or q['garbage_char_ratio'] > QTH['garbage_char_ratio_max'] or q['chars_per_page'] < QTH['chars_per_page_min']
    fl = dict(structure=struct, partial_sections=(struct == 'PARTIAL'), whole_text_fallback=bool(st.get('split_fallback_whole_text')),
              below_quality_threshold=below, possible_fragment=(d['pages'] <= 1), catalog_title_vs_content=('catalog says ACT; document is a BILL' if doc_type == 'bill' else None))
    flags[lid] = fl
    rows = d['rows']
    for r in rows:
        m = json.loads(r['metadata_json']); m.pop('catalog', None)
        m['metadata'] = dict(text_extraction=dict(source='official', backend=d['backend'], method=('ocr' if d['backend'] == 'ocr_tesseract' else 'text_layer+ocr_pages' if d['backend'] == 'pdftotext+ocr_pages' else 'text_layer')))
        r['metadata_json'] = json.dumps(m, ensure_ascii=False)
    status = 'whole_text_fallback' if fl['whole_text_fallback'] else ('partial' if fl['partial_sections'] else 'ok')
    meta = dict(schema_version='collection_record.v1', record_type='law', law_identifier=lid, document_type=doc_type, is_current=True,
                canonical_law_url=t['url'], article_extraction_status=status,
                metadata=dict(collector='ng_collect.py', schema='collection_record.v1', source_host=t['host'], content_sha256=hashlib.sha256(raw).hexdigest(),
                              rights=dict(not_legal_advice=True, official_reuse_url=t['url'], license=LIC),
                              text_extraction=dict(source='official', backend=d['backend'],
                                                   method=('ocr' if d['backend'] == 'ocr_tesseract' else 'text_layer+ocr_pages' if d['backend'] == 'pdftotext+ocr_pages' else 'text_layer'),
                                                   source_format=d['source_format'], pages=d['pages'], ocr_pages=d['ocr_pages'], n_ocr_pages=len(d['ocr_pages']),
                                                   ocr_engine=(f'{OCR_ENGINE} eng, pdftoppm 300dpi gray, psm 3' if d['ocr_pages'] else None),
                                                   quality=dict(q, grade=d['grade']), quality_text_layer=dict(d['quality_text_layer'], grade=d['grade_text_layer']),
                                                   quality_ocr=(dict(d['quality_ocr'], grade=d['grade_ocr']) if d['quality_ocr'] else None),
                                                   quality_threshold=QTH, below_quality_threshold=below, margin_notes_chars=len(d.get('margin_notes') or '')),
                              discovery=dict(method=('nass_magazine_catalog' if t['host'] == 'nass.gov.ng' else 'justice_wp_media_api'), catalog=t.get('catalog'),
                                             catalog_title=t['title'], uploaded=t.get('uploaded'), chamber=t.get('chamber'), parliament=t.get('parliament'), session=t.get('session')),
                              retrieval=dict(method='live', used_url=d['fetch'].get('final_url') or t['url'], fetched_at=d['fetch'].get('fetched_at'),
                                             content_type=d['fetch'].get('content_type'), bytes=d['fetch'].get('bytes'), last_modified=d['fetch'].get('last_modified')),
                              nass_download_id=t.get('nass_download_id'), year=t.get('year'),
                              section_split=dict(unit=next((json.loads(r['metadata_json']).get('unit') for r in rows if r['record_type'] == 'article'), None), preamble_row=any(r['id'].endswith('-preamble') for r in rows), whole_text_reason=st.get('whole_text_reason'), sections_before_fallback=st.get('sections_before_fallback'), rows_cover_law_text=guard[lid]['coverage'], n_sections=st['n_sections'],
                                                 max_section=st['max_section'], arrangement_count=st.get('arrangement_count'), doc_own_numbering=own,
                                                 missing_numbers=st['missing_numbers'], n_missing=st['n_missing'], n_annex=st['n_annex'],
                                                 splitter=resplit[lid]['used'], struct_ocr_used=bool(st.get('struct_ocr_used'))),
                              flags=fl, expand_batch=f'ng_expand_{TS}', content_class='legislative'))
    fa = d['fetch'].get('fetched_at') or ''
    try: ra = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.mktime(time.strptime(fa[:19], '%Y-%m-%dT%H:%M:%S'))))
    except Exception: ra = fa
    newL.append(dict(id=lid, title=t['title'], text=d['text'], source_url=t['url'], source_type='nigeria_official', jurisdiction='NG', country='Nigeria', language='en',
                     eli=None, date=None, date_issued=None, retrieved_at=ra, license=LIC, law_status='current', identifier=lid, official_identifier=lid,
                     article_count=len(rows), json_path=f'{B}/out/{lid}.json.gz', metadata_json=json.dumps(meta, ensure_ascii=False)))
    newA.extend(rows)
# ---------- write ----------
Ln = pa.Table.from_pylist(newL, schema=L0.schema); An = pa.Table.from_pylist(newA, schema=A0.schema)
L1 = pa.concat_tables([L0, Ln]); A1 = pa.concat_tables([A0, An])
pq.write_table(L1, f'{ST}/data/laws.parquet', compression='zstd')
pq.write_table(A1, f'{ST}/data/articles.parquet', compression='zstd', row_group_size=2000)
for f in os.listdir(f'{TIP}/scrapers'): shutil.copy2(f'{TIP}/scrapers/{f}', f'{ST}/scrapers/{f}')
shutil.copy2('/workspace/scripts/ng_collect.py', f'{ST}/scrapers/ng_collect.py')
json.dump(dict(ts=TS, staging=ST, tip=TIPSHA, keep=keep, drop=drop, resplit=resplit, guard=guard, flags=flags, dedup=dedup, ocr_engine=OCR_ENGINE),
          open(f'{ST}.build.json', 'w'), indent=1, ensure_ascii=False, default=list)
print('staged', ST, 'new laws', len(newL), 'new articles', len(newA), 'dropped', len(drop))

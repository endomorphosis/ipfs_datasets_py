#!/usr/bin/env python3
"""Parse fetched raw CA subnational docs into rows matching the ipfs_canada_laws schema (jsonl.gz per jurisdiction)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, re, json, gzip, hashlib, datetime, collections, threading, time
sys.path.insert(0, '/workspace/scripts')
import ca_parse as P
BASE = '{_CORPORA}/ca_subnational'
OUT = f'{BASE}/parsed'; os.makedirs(OUT, exist_ok=True)
HOST = {'ON': 'www.ontario.ca', 'MB': 'web2.gov.mb.ca', 'SK': 'publications.saskatchewan.ca', 'NS': 'nslegislature.ca / novascotia.ca', 'NB': 'laws.gnb.ca',
        'NT': 'www.justice.gov.nt.ca', 'NU': 'www.nunavutlegislation.ca'}
LIC = {
 'ON': "Crown copyright \u00a9 King's Printer for Ontario. Per https://www.ontario.ca/page/copyright-information the King's Printer permits anyone to reproduce the text of Ontario statutes and regulations without permission and without charge, provided it is reproduced accurately, Crown copyright is acknowledged ('\u00a9 King's Printer for Ontario, <year>') and a reproduction that is not an official copy states that it is not an official version. This is NOT an official version; e-Laws (ontario.ca/laws) is the official source. Not legal advice.",
 'MB': "Crown copyright \u00a9 King's Printer for Manitoba. RESTRICTED: per https://www.gov.mb.ca/legal/mb_laws.html copies of Manitoba Acts and regulations may be made without permission only for study or research, for use in legal proceedings, or for providing legal advice; any other reproduction requires the written consent of the King's Printer for Manitoba. The HTML consolidation (web2.gov.mb.ca/laws) is unofficial; the bilingual PDF is the official version. Included for research; not an official version. Not legal advice.",
 'SK': "Crown copyright \u00a9 Province of Saskatchewan (Office of the King's Printer). RESTRICTED: Freelaw consolidations (publications.saskatchewan.ca) are provided free for personal use and research; reproduction in another publication or on another website requires a written copyright release from the Office of the King's Printer (publications@gov.sk.ca). Unofficial copy for research; not an official version. Not legal advice.",
 'NS': "Crown copyright \u00a9 Province of Nova Scotia. Statutes: Office of the Legislative Counsel (nslegislature.ca), regulations: Registry of Regulations (novascotia.ca/just/regulations). Per https://nslegislature.ca/legal/copyright material may be downloaded and reproduced for non-commercial purposes if reproduced accurately and attributed; commercial reproduction requires permission. The electronic versions state they are for personal use and may not be copied for resale. Unofficial; not an official version. Not legal advice.",
 'NB': "Crown copyright \u00a9 Province of New Brunswick. Consolidated acts and regulations from laws.gnb.ca (Office of the Attorney General). Per the Government of New Brunswick copyright notice, non-commercial reproduction is permitted without permission if reproduced accurately and the source is identified; commercial redistribution requires the written permission of the King's/Queen's Printer. Unofficial copy; not an official version. Not legal advice.",
 'NT': "Copyright \u00a9 Government of the Northwest Territories (Territorial Printer). Unofficial consolidations from justice.gov.nt.ca prepared for convenience of reference; non-commercial reproduction permitted if accurate and the GNWT is acknowledged; commercial reproduction requires consent. English column only of the bilingual PDF. Not an official version. Not legal advice.",
 'NU': "Copyright \u00a9 Government of Nunavut (Territorial Printer). Consolidations from nunavutlegislation.ca (some 'official consolidations', others unofficial office consolidations that may not be up to date; see official_metadata.note). Free reproduction for personal use; may not be copied for resale without the consent of the Territorial Printer. Not legal advice.",
}
BACKEND = {'ON': 'elaws_api_json_html_pclass', 'MB': 'mb_html_regcol_e_secnum', 'NB': 'gnb_html_border_section_ids', 'NS': 'ns_html_text_linestart',
           'SK': 'pdftotext_layout_linestart', 'NT': 'pdftotext_layout_leftcolumn_linestart', 'NU': 'pdftotext_layout_linestart'}
DISC = {'ON': ('elaws_browse_search_api', 'https://www.ontario.ca/laws/api/v2/legislation/en/browse-search?selection=current'),
        'MB': ('mb_ccsm_and_consolidated_regs_index', 'https://web2.gov.mb.ca/laws/statutes/index_ccsm.php'),
        'SK': ('freelaw_acts_api', 'https://publications.saskatchewan.ca/api/v1/freelaw/acts'),
        'NS': ('ns_consolidated_statutes_and_regsbyact', 'https://nslegislature.ca/legislative-business/bills-statutes/consolidated-public-statutes'),
        'NB': ('gnb_chapters_all', 'https://laws.gnb.ca/en/chapters?corpus=statutes&selection=all'),
        'NT': ('nwt_justice_legislation_filebrowser', 'https://www.justice.gov.nt.ca/en/legislation/'),
        'NU': ('nunavut_consolidated_law_current', 'https://www.nunavutlegislation.ca/en/consolidated-law/current')}
def rawp(st, sid, ext): return f'{BASE}/raw/{st}/{re.sub(r"[^A-Za-z0-9._-]", "_", sid)}.{ext}.gz'
def slug(s): return re.sub(r'-{2,}', '-', re.sub(r'[^a-z0-9.]+', '-', s.lower())).strip('-.')
def utc(ts):
    try: return datetime.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S%z').astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception: return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
def d10(x): return x[:10] if x and re.match(r'\d{4}-\d{2}-\d{2}', x) else None
MONTHS = {m: i for i, m in enumerate(['january','february','march','april','may','june','july','august','september','october','november','december'], 1)}
def date_words(s):
    m = re.search(r'([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})', s or '')
    if m and m.group(1).lower() in MONTHS: return f'{int(m.group(3)):04d}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}'
    m = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', s or '')
    if m and m.group(2).lower() in MONTHS: return f'{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}'
    return None

def law_ident(st, it, meta, text, raw=''):
    t = it.get('title') or ''
    if st == 'ON':
        if it['kind'] == 'statute':
            m = re.search(r',\s*((?:R\.S\.O\.|S\.O\.)\s*\d{4},\s*c\.\s*[\w.]+(?:,\s*Sched\.\s*\w+)?)\s*$', t); return m.group(1) if m else it['src_id']
        return it.get('volume') or it['src_id']
    if st == 'MB': return it.get('citation') or it['src_id']
    if st == 'NB':
        c = it.get('citation') or ''
        if not c: return it['src_id']
        if it['kind'] == 'regulation': return f'N.B. Reg. {c}'
        return f'S.N.B. {c}' if re.match(r'\d{4}', c) else f'N.B. chapter {c}'
    if st == 'NS':
        if it['kind'] == 'regulation':
            m = re.match(r'(N\.S\. Reg\. \d+/\d+)', it.get('citation') or ''); return m.group(1) if m else (it.get('citation') or it['src_id'])
        m = re.search(r'R\.S\.N\.S\.\s*\d{4},\s*c\.\s*\d+[A-Z]?|S\.N\.S\.\s*\d{4}(?:-\d{2,4})?,\s*c\.\s*\d+', text[:3000])
        if m: return m.group(0)
        m = re.search(r'CHAPTER\s+(\d+[A-Z]?)\s+OF THE\s+REVISED STATUTES,?\s*(\d{4})', text[:3000])
        if m: return f'R.S.N.S. {m.group(2)}, c. {m.group(1)}'
        m = re.search(r'CHAPTER\s+(\d+[A-Z]?)\s+OF THE\s+ACTS OF\s*(\d{4}(?:-\d{2,4})?)', text[:3000])
        if m: return f'S.N.S. {m.group(2)}, c. {m.group(1)}'
        return it['src_id']
    if st == 'SK':
        m = re.search(r',\s*((?:SS|RSS)\s*\d{4},?\s*c\s*[\w.\-]+|[A-Z][\w.\-]* Reg \d+|RRS c [\w.\-]+ Reg \d+)\s*$', t); return m.group(1) if m else (it.get('citation') or it['src_id'])
    if st in ('NT', 'NU'):
        h = (raw or text)[:5000]
        pats = [r'R-\d{3}-\d{2,4}', r'R\.R\.N\.W\.T\.\s*\d{4},\s*c\.\s*[\w-]+', r'(?:R\.S\.N\.W\.T\.|S\.N\.W\.T\.|S\.Nu\.)\s*\d{4},\s*c\.\s*[\w-]+'] if it['kind'] == 'regulation' else \
               [r'R\.S\.N\.W\.T\.\s*\d{4},\s*c\.\s*[\w-]+', r'S\.N\.W\.T\.\s*\d{4},\s*c\.\s*\d+', r'S\.Nu\.\s*\d{4},\s*c\.\s*\d+', r'R\.S\.N\.W\.T\.\s*\(Nu\)\s*\d{4},\s*c\.\s*[\w-]+']
        pats = pats + [r'\b(?:RSNWT|SNWT|SNu|RSNWT\s*\(Nu\))\s*\d{4}\s*,\s*c\.?\s*[\w-]+', r'\bR\.?R\.?N\.?W\.?T\.?\s*\d{4}\s*,\s*c\.?\s*[\w-]+', r'\b(?:SI|R)-\d{3}-\d{2,4}']
        ms = [m for m in (re.search(pt, h) for pt in pats) if m]   # earliest citation in the header wins (base citation precedes amendments)
        if ms: return re.sub(r'\s+', ' ', min(ms, key=lambda m: m.start()).group(0))
        return it['src_id']
    return it['src_id']

def build(st, sample=False):
    items = {}
    for fn in [f'{BASE}/index/{st}_fetch_sample.jsonl', f'{BASE}/index/{st}_fetch.jsonl'] if not sample else [f'{BASE}/index/{st}_fetch_sample.jsonl']:
        if os.path.exists(fn):
            for l in open(fn):
                it = json.loads(l)
                prev = items.get(it['src_id'])
                if prev and prev.get('fetch_status', '').startswith('ok') and it.get('fetch_status') == 'cached':
                    it = {**it, **{k: prev[k] for k in prev if k not in it or it.get(k) is None}}
                if it.get('fetch_status', '').startswith(('ok', 'cached')) or it['src_id'] not in items: items[it['src_id']] = it
    sfx = '_sample' if sample else ''
    lw = gzip.open(f'{OUT}/{st}_laws{sfx}.jsonl.gz', 'wt'); aw = gzip.open(f'{OUT}/{st}_articles{sfx}.jsonl.gz', 'wt')
    stats = collections.Counter(); checks = []; gaps = []; seen_ids = set()
    for sid, it in sorted(items.items()):
        ext = next((e for e in ('json', 'html', 'txt') if os.path.exists(rawp(st, sid, e))), None)
        if ext is None:
            stats['not_fetched'] += 1; gaps.append(dict(jurisdiction=f'CA-{st}', src_id=sid, title=it.get('title'), kind=it.get('kind'), reason=it.get('fetch_status', 'not_fetched'))); continue
        b = gzip.open(rawp(st, sid, ext)).read(); meta = {}; rawtxt = b.decode('utf-8', 'replace') if ext == 'txt' else ''
        try:
            if st == 'ON': full, units, meta = P.parse_on(b)
            elif st == 'MB': full, units, meta = P.parse_mb(b)
            elif st == 'NB': full, units, meta = P.parse_nb(b)
            elif st == 'NS': full = P.ns_html_text(b); units = P.parse_generic(full, max_jump=250)   # HTML line starts are reliable; long repealed ranges
            else:
                src = b.decode('utf-8', 'replace')
                if st in ('NU', 'SK'):
                    src, bi = P.left_column(src); meta['bilingual_two_column_english_left_only'] = bi
                full = P.pdf_text_clean(src); units = P.parse_generic(full); full = P.clean(re.sub(r'[ \t]{2,}', ' ', full))
        except Exception as e:
            full, units = '', []; stats['parse_error'] += 1; gaps.append(dict(jurisdiction=f'CA-{st}', src_id=sid, title=it.get('title'), kind=it.get('kind'), reason=f'parse_error {type(e).__name__}: {str(e)[:120]}'))
        title = (it.get('title') or sid).strip()
        if st == 'NU': title = re.sub(r',\s*(Official\s+)?Consolidation of\s*$', '', title, flags=re.I).strip(); title = title.title() if title.isupper() else title
        if st == 'ON' and it['kind'] == 'regulation': title = f"{(it.get('title') or '').title()} ({it.get('volume')}, under the {it.get('act')})"
        law_id = f'ca-{st.lower()}-{slug(sid if st != "SK" else it["kind"] + "-" + sid)}'
        if law_id in seen_ids: stats['dup_law_id'] += 1; gaps.append(dict(jurisdiction=f'CA-{st}', src_id=sid, title=title, kind=it.get('kind'), reason=f'duplicate law id {law_id}')); continue
        seen_ids.add(law_id)
        # genuine duplicates: exact same unit text dropped; same number different text gets -2,-3
        exact = set(); u2 = []
        for u in units:
            k = (u['kind'], u['num'], u['text'])
            if k in exact: stats['exact_duplicate_units_dropped'] += 1; continue
            exact.add(k); u2.append(u)
        units = u2
        status = 'ok' if units else 'no_units_fulltext_only'
        text = (title + '\n\n' + '\n\n'.join(((u['heading'] + '\n') if u.get('heading') else '') + u['text'] for u in units)) if units else (title + '\n\n' + P.clean(full) if not P.clean(full).startswith(title) else P.clean(full))
        if len(text) - len(title) < 20:
            stats['empty_text'] += 1; gaps.append(dict(jurisdiction=f'CA-{st}', src_id=sid, title=title, kind=it.get('kind'), reason='empty_text')); continue
        sha = hashlib.sha256(b).hexdigest()
        src_url = it.get('page_url') or it.get('final_url') or it.get('url')
        if st in ('SK',): src_url = it.get('pdf_url') or it.get('url')
        if st == 'NU': src_url = it.get('url') or it.get('page_url')
        info_url = it.get('page_url') or src_url
        ident = law_ident(st, it, meta, full, rawtxt)
        date = None
        if st == 'ON': date = d10(meta.get('dateFrom')) or d10(it.get('date_from'))
        elif st == 'NT': date = date_words(it.get('modified'))
        elif st == 'NU':
            m = re.search(r'(?:Current to|Consolidation date):?\s*([A-Z][a-z]+ \d{1,2},\s*\d{4}|\d{4}-\d{2}-\d{2})', rawtxt[:20000])
            date = (m.group(1) if re.match(r'\d{4}-', m.group(1)) else date_words(m.group(1))) if m else it.get('current_to_page')
        elif st == 'NB':
            m = re.search(r'Current to (\d{1,2} [A-Z][a-z]+ \d{4})', b.decode('utf-8', 'replace')); date = date_words(m.group(1)) if m else None
        elif st == 'SK': m = re.search(r'Last update posted:\s*([^<]+)', it.get('description') or ''); date = date_words(m.group(1)) if m else None
        elif st == 'NS' and it['kind'] == 'statute': m = re.search(r'consolidated? (?:to|as of)\s+([A-Z][a-z]+ \d{1,2}, \d{4})', full[:3000], re.I); date = date_words(m.group(1)) if m else None
        seen = collections.Counter(); arts = []
        for u in units:
            num = u['num'] or '?'
            base = re.sub(r'[^a-z0-9._-]', '_', (f'{law_id}-s-{num.lower()}' if u['kind'] == 'section' else f'{law_id}-sch-{num.lower()}'))
            seen[base] += 1; aid = base if seen[base] == 1 else f'{base}-{seen[base]}'
            head = u.get('heading'); atext = ((head + '\n') if head else '') + u['text']
            arts.append(dict(law_id=law_id, id=aid, title=(f'{num} {head}' if head else P.first_line(u['text']))[:500], text=atext, source_url=src_url,
                             document_number=num, article_number=num if u['kind'] == 'section' else f'Schedule {num}', record_type='article',
                             metadata_json=json.dumps({'date_filed': date, 'article_heading': head, 'law_identifier': law_id,
                                                       'metadata': {'text_extraction': {'source': 'official', 'backend': BACKEND[st]}, 'unit': u['kind']},
                                                       'jurisdiction': f'CA-{st}'}, ensure_ascii=False)))
        nc = P.numbering_check(units)
        for a in arts: aw.write(json.dumps(a, ensure_ascii=False) + '\n')
        kind = it['kind']
        md = {'schema_version': 'collection_record.v1', 'record_type': 'law', 'law_identifier': ident, 'document_type': kind, 'is_current': True,
              'canonical_law_url': info_url, 'article_extraction_status': status,
              'metadata': {'collector': f'ca-subnational-{st.lower()}', 'schema': 'collection_record.v1', 'source_host': HOST[st], 'content_sha256': sha,
                           'rights': {'not_legal_advice': True, 'official_reuse_url': info_url, 'license': LIC[st]},
                           'text_extraction': {'source': 'official', 'backend': BACKEND[st], 'raw_format': {'json': 'json_html', 'html': 'html', 'txt': 'pdf'}[ext]},
                           'discovery': {'method': DISC[st][0], 'seed_url': DISC[st][1]},
                           'official_metadata': {k: it.get(k) for k in ('src_id', 'title', 'kind', 'citation', 'act', 'volume', 'date_from', 'enacted', 'modified', 'note', 'publication_date', 'pdf_name', 'current_to_page') if it.get(k) is not None} | ({'page_meta': meta} if meta else {}),
                           'numbering_check': nc},
              'canonical_title': title, 'citation': ident, 'last_modified_date': date, 'effective_date': date, 'valid_from': date,
              'languages': ['en'], 'canonical_document_url': src_url, 'subnational_jurisdiction': f'CA-{st}'}
        law = dict(id=law_id, title=title, text=text, source_url=src_url, source_type=f'ca_{st.lower()}_legislation', jurisdiction=f'CA-{st}', country='Canada',
                   language='en', eli=None, date=date, date_issued=None, retrieved_at=utc(it.get('fetched_at', '')), license=LIC[st], law_status='current',
                   identifier=ident, official_identifier=sid, article_count=len(arts), json_path=rawp(st, sid, ext), metadata_json=json.dumps(md, ensure_ascii=False))
        lw.write(json.dumps(law, ensure_ascii=False) + '\n')
        stats['laws'] += 1; stats['articles'] += len(arts); stats['status_' + status] += 1; stats[kind + 's'] += 1; stats[kind + '_articles'] += len(arts)
        checks.append(dict(id=law_id, kind=kind, **nc))
        if status != 'ok': gaps.append(dict(jurisdiction=f'CA-{st}', src_id=sid, title=title, kind=kind, reason='no_sections_parsed_fulltext_only'))
    lw.close(); aw.close()
    agg = dict(laws=stats['laws'], nonmono_laws=sum(1 for c in checks if c['nonmonotonic']), int_regress_laws=sum(1 for c in checks if c['int_regress']),
               dup_laws=sum(1 for c in checks if c['duplicates']), laws_with_int_gaps=sum(1 for c in checks if c['int_gaps']), zero_section_laws=sum(1 for c in checks if c['n_sections'] == 0))
    json.dump(dict(stats=dict(stats), numbering=agg, gaps=gaps), open(f'{OUT}/{st}_stats{sfx}.json', 'w'), indent=1, ensure_ascii=False)
    print(st, dict(stats), agg, flush=True)

def _memguard():
    def run():
        while True:
            for ln in open('/proc/meminfo'):
                if ln.startswith('MemAvailable:') and int(ln.split()[1]) // 1024 <= 3584:
                    print('MEMGUARD TERM', ln.strip(), flush=True); os._exit(3)
            time.sleep(10)
    threading.Thread(target=run, daemon=True).start()
if __name__ == '__main__':
    _memguard(); sample = '--sample' in sys.argv
    for st in sys.argv[1].split(','): build(st, sample)

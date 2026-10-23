#!/usr/bin/env python3
"""Parse fetched raw AU subnational docs into rows matching the ipfs_australia_laws schema (jsonl.gz per jurisdiction)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, re, json, gzip, hashlib, datetime, collections
sys.path.insert(0, '/workspace/scripts')
import au_parse as P
import lxml.html
BASE = '{_CORPORA}/au_subnational'
OUT = f'{BASE}/parsed'; os.makedirs(OUT, exist_ok=True)
HOST = {'NSW': 'legislation.nsw.gov.au', 'QLD': 'www.legislation.qld.gov.au', 'TAS': 'www.legislation.tas.gov.au',
        'WA': 'www.legislation.wa.gov.au', 'NT': 'legislation.nt.gov.au'}
LIC = {
 'NSW': 'Creative Commons Attribution 4.0 International (CC BY 4.0), as stated by NSW Legislation (Parliamentary Counsel\'s Office) at https://legislation.nsw.gov.au (exception: coat of arms, logos and content otherwise noted). Attribute the State of New South Wales / NSW Legislation website, link to the CC BY 4.0 licence, and indicate any changes. Not legal advice; the authorised text on legislation.nsw.gov.au prevails.',
 'QLD': 'Creative Commons Attribution 4.0 International (CC BY 4.0), as stated by Queensland Legislation (Office of the Queensland Parliamentary Counsel) at https://www.legislation.qld.gov.au (exception: coat of arms, logos and content otherwise noted). Attribute the State of Queensland, link to the CC BY 4.0 licence, and indicate any changes. Not legal advice; the authorised text on legislation.qld.gov.au prevails.',
 'TAS': 'Creative Commons Attribution 4.0 International (CC BY 4.0), as stated by Tasmanian Legislation Online at https://www.legislation.tas.gov.au/copyrightanddisclaimer (exception: coat of arms, logos, trade marks). Attribution: "Based on material from the Tasmanian Legislation website at [date of download]. For the latest information on Tasmanian Government legislation please go to www.legislation.tas.gov.au." Not legal advice.',
 'WA': 'Creative Commons Attribution 4.0 International (CC BY 4.0), as stated by Western Australian Legislation at https://www.legislation.wa.gov.au/legislation/statutes.nsf/copyright.html (exception: coat of arms, logos, trade marks, Government Gazette). Attribution: "Based on content from the Western Australian Legislation website at [date of download]. For the latest information on Western Australian legislation, visit www.legislation.wa.gov.au." Not legal advice.',
 'NT': 'Northern Territory of Australia copyright policy (https://legislation.nt.gov.au/en/Footer/Terms-of-Use): copyright owned by the Northern Territory; permission granted to publish or deal with NT legislation provided the publication does not indicate it is an official version, the NT arms are not used, and the material is accurately reproduced in a non-misleading context. NOT a Creative Commons licence; this is an unofficial reproduction. Not legal advice.',
}
BACKEND = {'NSW': 'pco_whole_html_anchor', 'QLD': 'pco_whole_html_anchor', 'TAS': 'enact_whole_html_anchor', 'WA': 'wa_word_html_charsectno', 'NT': 'nt_pdftotext_layout_linestart'}

def rawp(st, sid, ext):
    return f'{BASE}/raw/{st}/{re.sub(r"[^A-Za-z0-9._-]", "_", sid)}.{ext}.gz'
def d10(x):
    return x[:10] if x and re.match(r'\d{4}-\d{2}-\d{2}', x) and not x.startswith('9999') else None
MONTHS = {m: i for i, m in enumerate(['january','february','march','april','may','june','july','august','september','october','november','december'], 1)}
def parse_date_words(s):
    m = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', s or '')
    if m and m.group(2).lower() in MONTHS:
        return f'{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}'
    return None
def utc(ts):
    try:
        return datetime.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S%z').astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception:
        return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

def plain_fallback(st, ext, b):
    if ext == 'txt': return P.clean(b.decode('utf-8', 'replace'))
    doc = lxml.html.fromstring(b)
    fv = doc.get_element_by_id('fragview', None) if st in ('NSW', 'QLD', 'TAS') else None
    el = fv if fv is not None else doc.body if doc.body is not None else doc
    for bad in el.xpath('.//script|.//style'): bad.drop_tree()
    return P.clean(el.text_content())

def build(st):
    items = {}
    for fn in [f'{BASE}/index/{st}_fetch_sample.jsonl', f'{BASE}/index/{st}_fetch.jsonl']:
        if os.path.exists(fn):
            for l in open(fn):
                it = json.loads(l)
                if it.get('fetch_status', '').startswith(('ok', 'cached')) or it['src_id'] not in items:
                    prev = items.get(it['src_id'])
                    if prev and prev.get('fetch_status', '').startswith('ok') and it.get('fetch_status') == 'cached':
                        it = {**it, **{k: prev[k] for k in ('final_url', 'url', 'fetched_at', 'in_force_at', 'pdf_bytes', 'is_pdf') if k in prev}}
                    items[it['src_id']] = it
    lw = gzip.open(f'{OUT}/{st}_laws.jsonl.gz', 'wt'); aw = gzip.open(f'{OUT}/{st}_articles.jsonl.gz', 'wt')
    stats = collections.Counter(); checks = []; gaps = []
    for sid, it in sorted(items.items()):
        ext = 'html' if os.path.exists(rawp(st, sid, 'html')) else ('txt' if os.path.exists(rawp(st, sid, 'txt')) else None)
        if ext is None:
            stats['not_fetched'] += 1; gaps.append(dict(jurisdiction=f'AU-{st}', src_id=sid, title=it.get('title'), reason=it.get('fetch_status', 'not_fetched'))); continue
        b = gzip.open(rawp(st, sid, ext)).read()
        try:
            if ext == 'txt': t, units = P.parse_nt_text(b.decode('utf-8', 'replace'))
            elif st in ('NSW', 'QLD'): t, units = P.parse_pco(b)
            elif st == 'TAS': t, units = P.parse_pco(b, tas=True)
            else: t, units = P.parse_wa(b)
        except Exception as e:
            t, units = None, []; stats['parse_error'] += 1
        backend = BACKEND[st] if ext == 'html' or st == 'NT' else 'pdftotext_layout_linestart'
        nc = P.numbering_check(units)
        law_id = f'au-{st.lower()}-{sid.lower()}'
        title = (it.get('title') or t or sid).strip()
        if st == 'NT': title = title.title().replace(' Of ', ' of ').replace(' And ', ' and ').replace(' The ', ' the ').replace(' For ', ' for ').replace(' In ', ' in ') if title.isupper() else title
        # identifiers / dates
        kind = 'act'
        if st in ('NSW', 'QLD', 'TAS'):
            kind = 'act' if (it.get('print_type') == 'act.reprint') else 'regulation'
            pref = 'Act' if kind == 'act' else ('SR' if st == 'TAS' else 'SL')
            no = (it.get('no') or '').lstrip('0') or it.get('no'); yr = it.get('year')
            identifier = f'{pref} {no}/{yr}' if no and yr else sid
            date = d10(it.get('first_valid_date')); date_issued = d10(it.get('assent_date')) or (f'{yr}' if False else None)
            pub = d10(it.get('publication_date'))
            src_url = it['url']
        elif st == 'WA':
            kind = 'act' if it.get('kind') == 'act' else 'regulation'
            m = re.match(r'0*(\d+) of (\d{4})', it.get('number') or '')
            identifier = f'Act {m.group(1)}/{m.group(2)}' if m else sid
            yr = m.group(2) if m else (re.search(r'(\d{4})\s*$', title).group(1) if re.search(r'(\d{4})\s*$', title) else None)
            date = None; date_issued = None; pub = None
            src_url = it['url']
        else:
            kind = 'act' if it.get('kind') == 'act' else 'regulation'
            identifier = sid; yr = (re.search(r'(\d{4})\s*$', title).group(1) if re.search(r'(\d{4})\s*$', title) else None)
            txt0 = b[:4000].decode('utf-8', 'replace')
            m = re.search(r'As in force at\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})', txt0)
            date = parse_date_words(m.group(1)) if m else None; date_issued = None; pub = None
            src_url = it.get('url') or it.get('page_url')
        if units:
            text = title + '\n\n' + '\n\n'.join(u['text'] for u in units)
            status = 'ok'
        else:
            text = plain_fallback(st, ext, b); status = 'no_units_fulltext_only'
            if not text.startswith(title): text = title + '\n\n' + text
        if len(text) < 80:
            stats['empty_text'] += 1; gaps.append(dict(jurisdiction=f'AU-{st}', src_id=sid, title=title, reason='empty_text')); continue
        sha = hashlib.sha256(b).hexdigest()
        info_url = it.get('page_url') or (f'https://{HOST[st]}/view/html/inforce/current/{sid}' if st in ('NSW', 'QLD', 'TAS') else src_url)
        # articles
        seen = collections.Counter(); arts = []
        exact = set(); dropped_dups = 0
        for u in list(units):
            k = (u['kind'], u['num'], u['text'])
            if k in exact:
                units.remove(u); dropped_dups += 1; continue
            exact.add(k)
        stats['exact_duplicate_units_dropped'] += dropped_dups
        # genuine duplicates: editorial placeholders like "[21. Deleted: ...]" / "[16A. 1M Modification ...]" sharing a number with another unit
        grp = collections.defaultdict(list)
        for u in units: grp[(u['kind'], u['num'])].append(u)
        for key, us in grp.items():
            if len(us) < 2: continue
            br = [u for u in us if u['text'].lstrip().startswith('[')]
            nb = [u for u in us if not u['text'].lstrip().startswith('[')]
            if br and nb:
                for u in br: units.remove(u)
                stats['placeholder_duplicates_dropped'] += len(br); dropped_dups += len(br)
            elif len(br) == len(us):
                us[0]['text'] = '\n'.join(u['text'] for u in us)
                for u in us[1:]: units.remove(u)
                stats['placeholder_duplicates_merged'] += len(us) - 1; dropped_dups += len(us) - 1
        nc = P.numbering_check(units)
        for u in units:
            num = u['num'] or '?'
            base = (f'{law_id}-s-{num.lower()}' if u['kind'] == 'section' else f'{law_id}-sch-{num.lower()}')
            base = re.sub(r'[^a-z0-9._-]', '_', base)
            seen[base] += 1
            aid = base if seen[base] == 1 else f'{base}-{seen[base]}'
            first = u['text'].split('\n', 1)[0].strip()
            arts.append(dict(law_id=law_id, id=aid, title=first[:500], text=u['text'], source_url=src_url,
                             document_number=num, article_number=num if u['kind'] == 'section' else f'Schedule {num}', record_type='article',
                             metadata_json=json.dumps({'text_extraction': {'source': 'official', 'backend': backend}, 'unit': u['kind'],
                                                       'jurisdiction': f'AU-{st}', **({'anchor': u['anchor']} if u.get('anchor') else {})})))
        for a in arts: aw.write(json.dumps(a, ensure_ascii=False) + '\n')
        md = {
            'schema_version': 'collection_record.v1', 'record_type': 'law', 'law_identifier': identifier, 'document_type': kind,
            'is_current': True, 'canonical_law_url': info_url, 'article_count': len(arts), 'article_extraction_status': status,
            'canonical_title': title, 'citation': title, 'publication_date': pub or date_issued, 'effective_date': date, 'valid_from': date,
            'last_modified_date': pub or date, 'law_version_identifier': sid, 'version_specific_identifier': (f'{sid}@{date}' if date else sid),
            'canonical_document_url': src_url, 'information_url': info_url,
            'subnational_jurisdiction': st,
            'metadata': {
                'collector': f'au-subnational-{st.lower()}', 'schema': 'collection_record.v1', 'source_host': HOST[st], 'content_sha256': sha,
                'rights': {'not_legal_advice': True, 'official_reuse_url': info_url, 'license': LIC[st]},
                'text_extraction': {'source': 'official', 'backend': backend, 'raw_format': 'pdf' if (ext == 'txt') else 'html'},
                'discovery': {'method': {'NSW': 'pco_projectdata_pointintime', 'QLD': 'pco_projectdata_pointintime', 'TAS': 'pco_projectdata_pointintime',
                                         'WA': 'statutes_nsf_in_force_lists', 'NT': 'legislation_portal_by_title'}[st],
                              'seed_url': {'NSW': 'https://legislation.nsw.gov.au/projectdata', 'QLD': 'https://www.legislation.qld.gov.au/projectdata',
                                           'TAS': 'https://www.legislation.tas.gov.au/projectdata', 'WA': 'https://www.legislation.wa.gov.au/legislation/statutes.nsf/actsif.html',
                                           'NT': 'https://legislation.nt.gov.au/en/LegislationPortal/Acts/By-Title'}[st]},
                'official_metadata': {k: it.get(k) for k in ('src_id', 'title', 'year', 'no', 'number', 'type', 'print_type', 'kind', 'publication_date', 'first_valid_date', 'assent_date', 'mrdoc', 'in_force_at') if it.get(k) is not None},
                'numbering_check': nc,
            }}
        law = dict(id=law_id, title=title, text=text, source_url=src_url, source_type=f'au_{st.lower()}_legislation', jurisdiction=f'AU-{st}',
                   country='Australia', language='en', eli=None, date=date, date_issued=date_issued or pub, retrieved_at=utc(it.get('fetched_at', '')),
                   license=LIC[st], law_status='current', identifier=identifier, official_identifier=sid, article_count=len(arts),
                   json_path=rawp(st, sid, ext), metadata_json=json.dumps(md, ensure_ascii=False))
        lw.write(json.dumps(law, ensure_ascii=False) + '\n')
        stats['laws'] += 1; stats['articles'] += len(arts); stats['status_' + status] += 1
        if kind == 'act': stats['acts'] += 1
        else: stats['regulations'] += 1
        checks.append(dict(id=law_id, **nc))
        if status != 'ok': gaps.append(dict(jurisdiction=f'AU-{st}', src_id=sid, title=title, reason='no_sections_parsed_fulltext_only'))
    lw.close(); aw.close()
    agg = dict(laws=stats['laws'], nonmono_laws=sum(1 for c in checks if c['nonmonotonic']), int_regress_laws=sum(1 for c in checks if c.get('int_regress')), dup_laws=sum(1 for c in checks if c['duplicates']),
               laws_with_int_gaps=sum(1 for c in checks if c['int_gaps']), zero_section_laws=sum(1 for c in checks if c['n_sections'] == 0))
    json.dump(dict(stats=dict(stats), numbering=agg, gaps=gaps), open(f'{OUT}/{st}_stats.json', 'w'), indent=1, ensure_ascii=False)
    print(st, dict(stats), agg, flush=True)

def _memguard():
    import threading, time as _t
    def run():
        while True:
            for ln in open('/proc/meminfo'):
                if ln.startswith('MemAvailable:') and int(ln.split()[1]) // 1024 <= 3584:
                    print('MEMGUARD TERM', ln.strip(), flush=True); os._exit(3)
            _t.sleep(30)
    threading.Thread(target=run, daemon=True).start()

if __name__ == '__main__':
    _memguard()
    for st in sys.argv[1].split(','):
        build(st)

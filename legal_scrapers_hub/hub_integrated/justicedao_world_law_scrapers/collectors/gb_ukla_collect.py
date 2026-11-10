#!/usr/bin/env python3
"""UK Local Acts (legislation.gov.uk type 'ukla') collector.

Modes:
  handcheck <ids-file>  - build records for listed items (cached fetches) -> handcheck parquet
  full                  - enumerate the Atom feed (/ukla/data.feed?results-count=500) and fetch per item:
                          XML items -> CLML data.xml; PDF-only items -> static print PDF (/pdfs/*.pdf, text layer via
                          pdftotext; no OCR); metadata-only items -> no fetch. Resume-safe, gz cache, lean.
  build [outdir]        - out/records.jsonl.gz -> laws.parquet / articles.parquet (NL staging schema)
Rules: robots Crawl-delay 5 (we use 5.5 s), never */data.pdf or */data.docx, single connection,
stop after 3 consecutive 403/429/503, memguard MemAvailable<=3700MB or RSS(tree)>300MB -> SIGTERM self.
Licence: OGL-UK-3.0. Attribution: (c) Crown and database right, legislation.gov.uk, OGL v3.0.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import datetime as dt, gzip, json, os, re, signal, subprocess, sys, threading, time
sys.path.insert(0, '/workspace/scripts')
import gb_ukla_client as G

BASE = '{_CORPORA}/gb_ukla'
FEED = 'https://www.legislation.gov.uk/ukla/data.feed?results-count=500&page={p}'
STATE = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'
MEMAVAIL_MIN_MB = 3700
RSS_MAX_MB = 300
LICENSE = 'OGL-UK-3.0'
FETCH_PDF = os.environ.get('GBLA_FETCH_PDF') == '1'   # off by default: PDF-only items are image scans (no text layer)
ATTRIBUTION = ('© Crown and database right. Derived from content available under the Open Government Licence v3.0 '
               'from legislation.gov.uk (https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)')
A = '{http://www.w3.org/2005/Atom}'; UKM = '{http://www.legislation.gov.uk/namespaces/metadata}'
LEG = '{http://www.legislation.gov.uk/namespaces/legislation}'
DC = '{http://purl.org/dc/elements/1.1/}'

# ---------------------------------------------------------------- memory / state
def memavail_mb():
    for ln in open('/proc/meminfo'):
        if ln.startswith('MemAvailable:'): return int(ln.split()[1]) // 1024
    return 0

def rss_tree_mb(pid=None):
    pid = pid or os.getpid(); tot = 0; todo = [pid]; seen = set()
    while todo:
        p = todo.pop()
        if p in seen: continue
        seen.add(p)
        try:
            for ln in open(f'/proc/{p}/status'):
                if ln.startswith('VmRSS:'): tot += int(ln.split()[1])
            todo += [int(x) for x in open(f'/proc/{p}/task/{p}/children').read().split()]
        except Exception: pass
    return tot // 1024

def merge_state(upd, collectors_delta=0):
    """Re-read state, merge ONLY gbla_* keys, adjust collectors. Never touches nlm_*, atm_*, mode."""
    assert all(k.startswith('gbla_') for k in upd), upd
    for _ in range(5):
        try:
            st = json.load(open(STATE))
            st.update(upd)
            if collectors_delta: st['collectors'] = max(0, int(st.get('collectors') or 0) + collectors_delta)
            tmp = STATE + f'.tmp_gbla_{os.getpid()}'
            json.dump(st, open(tmp, 'w'), indent=2, ensure_ascii=False); os.replace(tmp, STATE); return st
        except json.JSONDecodeError: time.sleep(0.5)
    raise RuntimeError('state merge failed')

class Guard:
    def __init__(self, log):
        self.log = log; self.tripped = None
        threading.Thread(target=self._run, daemon=True).start()
    def _run(self):
        while True:
            ma, rs = memavail_mb(), rss_tree_mb()
            if ma <= MEMAVAIL_MIN_MB or rs > RSS_MAX_MB:
                self.tripped = f'MemAvailable={ma}MB RSS={rs}MB'; self.log(f'MEMGUARD {self.tripped} -> SIGTERM self')
                os.kill(os.getpid(), signal.SIGTERM); return
            time.sleep(5)

def mk_logger(path):
    def log(msg):
        line = f"{dt.datetime.now().isoformat(timespec='seconds')} PT {msg}"
        print(line, flush=True)
        if path: open(path, 'a').write(line + '\n')
    return log

# ---------------------------------------------------------------- feed
def parse_feed(xml_bytes):
    from xml.etree import ElementTree as ET
    r = ET.fromstring(xml_bytes); out = []
    for e in r.findall(A + 'entry'):
        alts = {l.get('title'): l.get('href') for l in e.findall(A + 'link') if l.get('rel') == 'alternate'}
        if not alts.get('PDF'):   # 5 feed entries title the print PDF 'Print Version' or with the Act title
            pdfs = [l.get('href') for l in e.findall(A + 'link') if l.get('rel') == 'alternate' and l.get('type') == 'application/pdf']
            if pdfs: alts['PDF'] = pdfs[0]
        y = e.find(UKM + 'Year'); n = e.find(UKM + 'Number'); isbn = e.find(UKM + 'ISBN'); cd = e.find(UKM + 'CreationDate')
        out.append({'uri': (e.findtext(A + 'id') or '').strip(), 'title': (e.findtext(A + 'title') or '').strip(),
                    'year': y.get('Value') if y is not None else '', 'number': n.get('Value') if n is not None else '',
                    'isbn': isbn.get('Value') if isbn is not None else '', 'creation_date': cd.get('Date') if cd is not None else '',
                    'summary': (e.findtext(A + 'summary') or '').strip(), 'updated': e.findtext(A + 'updated'),
                    'xml': alts.get('XML'), 'pdf': alts.get('PDF'), 'akn': alts.get('AKN'), 'html5': alts.get('HTML5'),
                    'availability': 'xml' if alts.get('XML') else ('pdf' if alts.get('PDF') else 'metadata_only')})
    more = b'rel="next"' in xml_bytes
    return out, more

def https(u):
    return re.sub(r'^http://', 'https://', u or '')

# ---------------------------------------------------------------- CLML parsing
def _lname(e): return e.tag.rsplit('}', 1)[-1]

def _text(e, skip=('Commentary', 'Commentaries', 'CommentaryRef', 'Citation_skip')):
    parts = []
    BLOCK = {'P', 'P1', 'P2', 'P3', 'P4', 'P1para', 'P2para', 'P3para', 'Para', 'Text', 'Title', 'Pnumber', 'Number',
             'Tabular', 'tr', 'Row', 'ListItem', 'BlockText', 'Subtitle', 'TitleBlock', 'LongTitle', 'Reference', 'Footnote'}
    def rec(x, parent=''):
        n = _lname(x)
        if n in ('Commentaries', 'Commentary', 'Metadata', 'Contents', 'Versions', 'Resources', 'Footnotes'): return
        if n in BLOCK and n != 'Pnumber': parts.append('\n')
        if n == 'Pnumber' and x.text:
            v = x.text.strip()
            parts.append(('\n' + v + ' ') if parent == 'P1' else f'\n({v}) ')
        elif x.text: parts.append(x.text)
        for ch in x:
            rec(ch, n)
            if ch.tail: parts.append(ch.tail)
        if n in ('td', 'th', 'entry'): parts.append(' | ')
    rec(e)
    s = ''.join(parts).replace('\xa0', ' ')
    s = re.sub(r'[ \t]+', ' ', s); s = re.sub(r' *\n *', '\n', s); s = re.sub(r'\n{2,}', '\n', s)
    return s.strip()

def parse_clml(xml_bytes):
    """-> dict(meta, prelims_text, sections[(num, title, text)], schedules[(num, title, text)], full_text, pdf_alternatives)"""
    from xml.etree import ElementTree as ET
    r = ET.fromstring(xml_bytes)
    meta = {}
    md = next((e for e in r.iter() if _lname(e) == 'Metadata'), None)
    if md is not None:
        for e in md.iter():
            n = _lname(e)
            if n in ('title', 'description', 'identifier', 'modified', 'subject', 'language', 'publisher') and (e.text or '').strip():
                meta.setdefault('dc_' + n, (e.text or '').strip())
            if n == 'EnactmentDate': meta['enactment_date'] = e.get('Date')
            if n in ('ISBN',): meta['isbn'] = e.get('Value')
            if n == 'Alternative': meta.setdefault('pdf_alternatives', []).append({'uri': e.get('URI'), 'title': e.get('Title'), 'date': e.get('Date')})
            if n == 'Number' and e.get('Value'): meta['number'] = e.get('Value')
    prim = next((e for e in r.iter() if _lname(e) in ('Primary', 'Secondary')), None)
    prelims = next((e for e in r.iter() if _lname(e) in ('PrimaryPrelims',)), None)
    pre_txt = _text(prelims) if prelims is not None else ''
    lt = next((e for e in r.iter() if _lname(e) == 'LongTitle'), None)
    meta['long_title'] = _text(lt) if lt is not None else ''
    body = next((e for e in r.iter() if _lname(e) == 'Body'), None)
    sections = []
    if body is not None:
        # walk body: P1group (title) contains P1(s); bare P1 also possible
        def walk(e, group_title=None, ctx=()):
            for ch in e:
                n = _lname(ch)
                if n == 'P1group':
                    t = ch.find(LEG + 'Title'); gt = _text(t) if t is not None else ''
                    p1s = [c for c in ch if _lname(c) == 'P1']
                    if not p1s:
                        sections.append((None, gt, _text(ch), ctx))
                    for k, p in enumerate(p1s):
                        num = (p.findtext(LEG + 'Pnumber') or '').strip()
                        txt = _text(p)
                        if k == 0 and gt: txt = gt + '\n' + txt
                        sections.append((num, gt, txt, ctx))
                elif n == 'P1':
                    sections.append(((ch.findtext(LEG + 'Pnumber') or '').strip(), '', _text(ch), ctx))
                elif n in ('Part', 'Chapter', 'Pblock', 'PsubBlock'):
                    num = ch.findtext(LEG + 'Number') or ''; tt = ch.find(LEG + 'Title')
                    walk(ch, None, ctx + ((n, num.strip(), _text(tt) if tt is not None else ''),))
                elif n in ('Number', 'Title'):
                    continue
                else:
                    walk(ch, group_title, ctx)
        walk(body)
    schedules = []
    for s in (e for e in r.iter() if _lname(e) == 'Schedule'):
        num = (s.findtext(LEG + 'Number') or '').strip(); tb = s.find(LEG + 'TitleBlock')
        title = _text(tb.find(LEG + 'Title')) if tb is not None and tb.find(LEG + 'Title') is not None else ''
        schedules.append((num, title, _text(s)))
    full = '\n'.join(x for x in [pre_txt] + [s[2] for s in sections] + [s[2] for s in schedules] if x)
    if not sections and prim is not None:
        full = _text(prim)
    return {'meta': meta, 'prelims': pre_txt, 'sections': sections, 'schedules': schedules, 'full_text': full}

def pdf_text(pdf_bytes):
    p = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-q', '-', '-'], input=pdf_bytes, capture_output=True, timeout=300)
    t = p.stdout.decode('utf-8', 'replace')
    t = re.sub(r'[ \t]+', ' ', t); t = re.sub(r' *\n *', '\n', t); t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()

def pdf_pages(pdf_bytes):
    try:
        p = subprocess.run(['pdfinfo', '-'], input=pdf_bytes, capture_output=True, timeout=60)
        m = re.search(rb'Pages:\s+(\d+)', p.stdout); return int(m.group(1)) if m else 0
    except Exception: return 0

# ---------------------------------------------------------------- records
LAW_COLS = ['id', 'title', 'text', 'source_url', 'source_type', 'jurisdiction', 'country', 'language', 'eli', 'date',
            'date_issued', 'retrieved_at', 'license', 'law_status', 'identifier', 'official_identifier', 'article_count',
            'json_path', 'metadata_json']
ART_COLS = ['law_id', 'id', 'title', 'text', 'source_url', 'document_number', 'article_number', 'record_type', 'metadata_json']

LOCALITY_RE = re.compile(r'^(?:The\s+)?(.+?)\s+(?:\((?:[^)]*)\)\s+)?(?:Corporation|Borough|City|County|District|Council|Improvement|Harbour|Port|Water|Gas|Railway|Tramways?|Bridge|Dock|Docks|Canal|Navigation|Market|Markets|Act)\b')

def locality_guess(title):
    """Heuristic locality from the short title (e.g. 'Cheltenham Borough Council (Markets) Act 2026' -> 'Cheltenham').
    Stored as metadata only (locality_guess + method); jurisdiction stays 'GB-LOCAL'."""
    t = re.sub(r'\s+Act\s*,?\s*\d{4}.*$', '', title or '').strip()
    t = re.sub(r'\s*\([^)]*\)', '', t).strip()
    m = re.match(r'^(?:The\s+)?([A-Z][\w\'.-]*(?:\s+(?:upon|on|under|in|by|le|de|St\.?|and|&|[A-Z][\w\'.-]*))*?)\s+(?:Corporation|Borough|City|County|District|Metropolitan|Council|Improvement|Harbour|Port|Pier|Water|Waterworks|Gas|Railway|Tramways?|Bridge|Dock|Docks|Canal|Navigation|Market|Markets|Cemetery|Burial|Police|Drainage|Roads?|Light|Electric|Transport|Corporation)\b', t)
    return m.group(1).strip() if m else ''

def uri_path(e):
    # e.g. http://www.legislation.gov.uk/id/ukla/Vict/42-43/194 -> ukla/Vict/42-43/194 (regnal-year citations repeat numbers per calendar year)
    return re.sub(r'^https?://www\.legislation\.gov\.uk/(id/)?', '', e['uri']).strip('/')

def law_id(e): return re.sub(r'[^0-9A-Za-z]+', '-', uri_path(e)).strip('-').lower()

def build_record(e, kind, raw, src_url, cache_path, retrieved_at, extra_meta=None):
    lid = law_id(e)
    meta = {'schema_version': 'collection_record.v1', 'record_type': 'law', 'type': 'ukla',
            'legislation_uri': https(e['uri']), 'year': e['year'], 'number': e['number'], 'isbn': e.get('isbn') or None,
            'availability': e['availability'], 'content_kind': kind, 'feed_updated': e.get('updated'),
            'summary': e.get('summary') or None, 'xml_url': https(e.get('xml')) or None, 'pdf_url': https(e.get('pdf')) or None,
            'akn_url': https(e.get('akn')) or None, 'locality_guess': locality_guess(e['title']) or None,
            'locality_method': 'short-title heuristic', 'attribution': ATTRIBUTION, 'collector': 'gb_ukla_collect.py'}
    if extra_meta: meta.update(extra_meta)
    arts = []; text = ''; status = 'enacted'; date = ''; issued = ''
    if kind == 'xml':
        p = parse_clml(raw); m = p['meta']
        text = p['full_text']; issued = m.get('enactment_date') or ''; date = issued
        vm = re.search(r'/(\d{4}-\d{2}-\d{2})/data\.xml$', src_url or '')
        status = 'current' if vm else 'enacted'   # revised point-in-time version vs enacted text only
        meta['version'] = vm.group(1) if vm else 'enacted'
        if vm: date = vm.group(1)
        meta.update({'long_title': m.get('long_title') or None, 'dc_title': m.get('dc_title'), 'dc_modified': m.get('dc_modified'),
                     'enactment_date': m.get('enactment_date'), 'pdf_alternatives': m.get('pdf_alternatives'),
                     'n_sections': len(p['sections']), 'n_schedules': len(p['schedules']), 'text_source': 'clml_xml'})
        used = {}
        def add(kind_, num, title, txt, seq, ctx=()):
            slug = re.sub(r'[^0-9A-Za-z]+', '-', (num or '').strip()).strip('-') or f'u{seq}'
            base = f'{lid}-{kind_}-{slug}'; used[base] = used.get(base, 0) + 1
            aid = base if used[base] == 1 else f'{base}-{used[base]}'
            label = f"{'Section' if kind_ == 'section' else 'Schedule'} {num}".strip() if num else (title or kind_.title())
            arts.append({'law_id': lid, 'id': aid, 'title': f"{e['title']} — {label}" + (f": {title}" if title else ''),
                         'text': txt, 'source_url': src_url, 'document_number': label, 'article_number': num or '',
                         'record_type': 'article' if kind_ == 'section' else 'schedule',
                         'metadata_json': json.dumps({'law_identifier': lid, 'kind': kind_, 'heading': title or None, 'seq': seq,
                                                      'context': [list(c) for c in ctx] if ctx else None}, ensure_ascii=False)})
        for i, (num, title, txt, ctx) in enumerate(p['sections']):
            if txt.strip(): add('section', num, title, txt, i, ctx)
        for j, (num, title, txt) in enumerate(p['schedules']):
            if txt.strip(): add('schedule', num or str(j + 1), title, txt, len(p['sections']) + j)
    elif kind == 'pdf':
        t = pdf_text(raw); npg = pdf_pages(raw)
        words = len(re.findall(r'[A-Za-z]{3,}', t))
        has_layer = words >= max(30, 20 * max(npg, 1) // 4)
        meta.update({'pdf_pages': npg, 'pdf_text_words': words, 'pdf_text_layer': has_layer,
                     'text_source': 'pdf_text_layer' if has_layer else 'title_only'})
        if has_layer:
            text = t
        else:
            text = e['title']; meta['metadata_only'] = True; meta['metadata_only_reason'] = 'PDF scan without text layer (no OCR)'
            status = 'metadata_only'
        try: issued = e.get('creation_date') or ''
        except Exception: pass
    elif kind == 'pdf_skipped':
        text = e['title'] + (('\n' + e['summary']) if e.get('summary') else '')
        meta.update({'metadata_only': True, 'text_source': 'title_only',
                     'metadata_only_reason': 'PDF-only item (static print scan, no text layer in 9/9 sampled); PDF not downloaded, see pdf_url'})
        status = 'metadata_only'
    else:
        text = e['title'] + (('\n' + e['summary']) if e.get('summary') else '')
        meta['metadata_only'] = True; meta['metadata_only_reason'] = 'no XML or PDF on legislation.gov.uk'; meta['text_source'] = 'title_only'
        status = 'metadata_only'
    if kind != 'xml' and not date:
        date = f"{e['year']}" if e['year'] else ''
    meta.setdefault('metadata_only', False)
    law = {'id': lid, 'title': e['title'], 'text': text, 'source_url': src_url or https(e['uri']),
           'source_type': 'uk_local_act', 'jurisdiction': 'GB-LOCAL', 'country': 'United Kingdom', 'language': 'en',
           'eli': https(e['uri']), 'date': date, 'date_issued': issued, 'retrieved_at': retrieved_at, 'license': LICENSE,
           'law_status': status, 'identifier': uri_path(e),
           'official_identifier': f"{e['year']} c. {e['number']}" if e['number'] else '', 'article_count': len(arts),
           'json_path': cache_path or '', 'metadata_json': json.dumps(meta, ensure_ascii=False)}
    return law, arts

# ---------------------------------------------------------------- fetch with gz cache
def cache_file(e, kind):
    return f"{BASE}/cache/{kind}/{law_id(e)}.{kind}.gz"

def fetch_item(cli, e):
    """-> (kind, raw, url, cache_path). XML preferred; PDF-only -> static print PDF; metadata-only -> no request."""
    if e['availability'] == 'xml':
        kind, url = 'xml', https(e['xml'])
    elif e['availability'] == 'pdf':
        kind, url = 'pdf', https(e['pdf'])
        if url.endswith('/data.pdf'): return 'meta', None, https(e['uri']), ''   # robots: */data.pdf disallowed
        if not FETCH_PDF and not os.path.exists(cache_file(e, 'pdf')):
            return 'pdf_skipped', None, url, ''
    else:
        return 'meta', None, https(e['uri']), ''
    cp = cache_file(e, kind)
    if os.path.exists(cp):
        return kind, gzip.open(cp).read(), url, cp
    st, hdr, body = cli.get(url)
    if st == 200 and body:
        os.makedirs(os.path.dirname(cp), exist_ok=True)
        with gzip.open(cp + '.part', 'wb', compresslevel=6) as f: f.write(body)
        os.replace(cp + '.part', cp)
        return kind, body, url, cp
    return 'error', None, url, f'HTTP {st}'

def load_feed_entries(cli=None, refresh=False, log=print):
    d = f'{BASE}/cache/feed'; os.makedirs(d, exist_ok=True); entries = []; p = 1
    while True:
        fp = f'{d}/ukla_rc500_p{p:03d}.xml.gz'
        if os.path.exists(fp) and not refresh:
            b = gzip.open(fp).read()
        else:
            if cli is None: break
            st, h, b = cli.get(FEED.format(p=p))
            if st != 200: raise G.Stop(f'feed page {p} HTTP {st}')
            gzip.open(fp, 'wb').write(b)
        es, more = parse_feed(b); entries += es
        if not more or not es: break
        p += 1
    seen = set(); out = []
    for e in entries:
        k = e['uri']
        if k in seen: continue
        seen.add(k); out.append(e)
    return out

# ---------------------------------------------------------------- modes
def write_parquet(laws, arts, outdir):
    import pyarrow as pa, pyarrow.parquet as pq
    os.makedirs(outdir, exist_ok=True)
    ls = pa.schema([(c, pa.int32() if c == 'article_count' else pa.string()) for c in LAW_COLS])
    as_ = pa.schema([(c, pa.string()) for c in ART_COLS])
    pq.write_table(pa.Table.from_pylist(laws, schema=ls), f'{outdir}/laws.parquet', compression='zstd')
    pq.write_table(pa.Table.from_pylist(arts, schema=as_), f'{outdir}/articles.parquet', compression='zstd')

def mode_full(args):
    logp = os.environ.get('GBLA_LOG') or f"/workspace/logs/gb_ukla_collect_{dt.datetime.now():%Y%m%dT%H%M%S}.log"
    log = mk_logger(None if os.environ.get('GBLA_LOG') else logp)
    if memavail_mb() < 4608: log(f'REFUSING: MemAvailable {memavail_mb()}MB < 4.5G'); sys.exit(3)
    final = {'status': 'DONE'}; counted = False
    def on_term(sig, frm):
        final['status'] = 'MEMSHED' if guard.tripped else 'STOPPED_SIGTERM'; raise SystemExit(0)
    signal.signal(signal.SIGTERM, on_term)
    merge_state({'gbla_pid': os.getpid(), 'gbla_log': logp, 'gbla_status': 'COLLECTING',
                 'gbla_started_pt': dt.datetime.now().astimezone().isoformat(timespec='seconds')}, collectors_delta=+1)
    counted = True
    guard = Guard(log); cli = G.Client(log=log, status_file=f'{BASE}/out/http_status.log')
    os.makedirs(f'{BASE}/out', exist_ok=True)
    donep = f'{BASE}/out/done_ids.txt'
    done = set(l.strip() for l in open(donep)) if os.path.exists(donep) else set()
    n = {'ok': 0, 'meta': 0, 'err': 0}
    try:
        entries = load_feed_entries(cli, refresh=False, log=log)
        log(f'feed entries: {len(entries)}; already done: {len(done)}')
        order = {'xml': 0, 'pdf': 1, 'metadata_only': 2}
        entries.sort(key=lambda e: (order[e['availability']], -int(e['year'] or 0), int(re.sub(r'\D', '', e['number']) or 0)))
        for i, e in enumerate(entries):
            lid = law_id(e)
            if lid in done: continue
            kind, raw, url, cp = fetch_item(cli, e)
            if kind == 'error':
                n['err'] += 1; open(f'{BASE}/out/failed.jsonl', 'a').write(json.dumps({'id': lid, 'url': url, 'err': cp}) + '\n'); continue
            law, arts = build_record(e, kind, raw, url, cp, dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
            with gzip.open(f'{BASE}/out/records.jsonl.gz', 'at') as f:
                f.write(json.dumps({'law': law, 'articles': arts}, ensure_ascii=False) + '\n')
            open(donep, 'a').write(lid + '\n'); done.add(lid)
            n['meta' if law['law_status'] == 'metadata_only' else 'ok'] += 1; raw = None
            if (n['ok'] + n['meta']) % 50 == 0:
                log(f"progress {len(done)}/{len(entries)} ok={n['ok']} meta={n['meta']} err={n['err']} nreq={cli.nreq} memavail={memavail_mb()} rss={rss_tree_mb()}")
                merge_state({'gbla_progress': f"{len(done)}/{len(entries)} (full-text {n['ok']}, metadata-only {n['meta']}, err {n['err']}), nreq={cli.nreq}"})
        log(f"ALL DONE {len(done)}/{len(entries)} {n} nreq={cli.nreq}")
    except G.Stop as ex:
        final['status'] = 'STOPPED_3X'; log(f'STOP {ex}')
    except SystemExit:
        pass
    except Exception as ex:
        final['status'] = 'ERROR'; log(f'ERROR {ex!r}')
    finally:
        if counted:
            merge_state({'gbla_status': final['status'], 'gbla_pid': None,
                         'gbla_ended_pt': dt.datetime.now().astimezone().isoformat(timespec='seconds'),
                         'gbla_progress': f"{len(done)} done {n} nreq={cli.nreq}"}, collectors_delta=-1)
            log(f"exit gbla_status={final['status']}")

def mode_build(args):
    outdir = args[0] if args else f"{BASE}/out/build_{dt.datetime.now():%Y%m%dT%H%M%S}/data"
    laws, arts, seen = [], [], set()
    with gzip.open(f'{BASE}/out/records.jsonl.gz', 'rt') as f:
        for ln in f:
            r = json.loads(ln)
            if r['law']['id'] in seen: continue
            seen.add(r['law']['id']); laws.append(r['law']); arts += r['articles']
    write_parquet(laws, arts, outdir); print(outdir, len(laws), len(arts))

def mode_handcheck(args):
    import gb_ukla_handcheck as H
    H.run(args)

if __name__ == '__main__':
    m = sys.argv[1] if len(sys.argv) > 1 else ''
    {'full': mode_full, 'build': mode_build, 'handcheck': mode_handcheck}.get(m, lambda a: (print(__doc__), sys.exit(1)))(sys.argv[2:])

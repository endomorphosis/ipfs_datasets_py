#!/usr/bin/env python3
"""AT Gemeinderecht collector (RIS OGD API v2.6, applications Gr + GrA).

Modes:
  gate       - small gate requests: robots, per-Bundesland counts (writes probe/gate_raw.json)
  sample     - fetch content for a given list of IDs (hand-check sample), cached
  handcheck  - parse cached sample docs -> handcheck parquet + stats (no network unless cache miss)
  full       - enumerate all Gr/GrA pages + fetch main-document content; resume-safe; gz cache
  build      - convert out/records_*.jsonl.gz -> laws.parquet / articles.parquet (hub schema)

Source rules (RIS OGD FAQ "Technische Rahmenbedingungen", mandatory):
  <=0.5 req/s (we use >=2.5 s), no parallel connections, only outside office hours
  (Vienna 20:00-05:00, weekends, Austrian public holidays). 'full' additionally requires
  NOTIFY_SENT.json (prior "Ankuendigung eines geplanten Massendownloads (OGD)" to ris.it@bka.gv.at).
API endpoints + API-returned content URLs (ogd.ris.bka.gv.at/Dokumente/...) only. No HTML crawling.
Licence of RIS OGD data: CC BY 4.0, attribution "RIS - Rechtsinformationssystem des Bundes, Bundeskanzleramt".
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import datetime as dt, gzip, json, os, re, signal, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

BASE = '{_CORPORA}/at_municipal'
API = 'https://data.bka.gv.at/ris/api/v2.6/Gemeinden'
UA = ('legal-corpora-at-municipal/1.0 (research corpus of Austrian municipal law from RIS OGD, '
      'CC BY 4.0 attribution; <=0.4 req/s, single connection; contact via huggingface.co/endomorphosis)')
DELAY = 2.5
STATE = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'
MEMAVAIL_MIN_MB = 3700
RSS_MAX_MB = 300
VIENNA = ZoneInfo('Europe/Vienna')
NOTIFY_FILE = f'{BASE}/NOTIFY_SENT.json'
ATTRIBUTION = ('Quelle: RIS - Rechtsinformationssystem des Bundes, Bundeskanzleramt (https://www.ris.bka.gv.at), '
               'OGD-RIS API v2.6; Lizenz CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)')
# Bundesland values differ between applications (see OGD-RIS API Handbuch V2_6 p.37)
LAENDER = [  # (iso code, Gr value, GrA value, GKZ first digit)
    ('AT-1', 'Burgenland', 'Burgenland', '1'), ('AT-2', 'Kaernten', 'Kärnten', '2'),
    ('AT-3', 'Niederoesterreich', 'Niederösterreich', '3'), ('AT-4', 'Oberoesterreich', 'Oberösterreich', '4'),
    ('AT-5', 'Salzburg', 'Salzburg', '5'), ('AT-6', 'Steiermark', 'Steiermark', '6'),
    ('AT-7', 'Tirol', 'Tirol', '7'), ('AT-8', 'Vorarlberg', 'Vorarlberg', '8'), ('AT-9', 'Wien', 'Wien', '9')]
BL_NAME2ISO = {}
for iso, a, b, d in LAENDER:
    BL_NAME2ISO[a] = iso; BL_NAME2ISO[b] = iso
GKZ2ISO = {d: iso for iso, a, b, d in LAENDER}

class Stop(Exception):
    pass

class ApiError(Exception):
    pass

# ---------------------------------------------------------------- office-hours window
def _easter(y):
    a = y % 19; b = y // 100; c = y % 100; d = b // 4; e = b % 4; f = (b + 8) // 25; g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30; i = c // 4; k = c % 4; l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451; mo = (h + l - 7 * m + 114) // 31; da = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(y, mo, da)

def at_holidays(y):
    e = _easter(y)
    fixed = [(1, 1), (1, 6), (5, 1), (8, 15), (10, 26), (11, 1), (12, 8), (12, 25), (12, 26)]
    s = {dt.date(y, m, d) for m, d in fixed}
    s |= {e + dt.timedelta(days=1), e + dt.timedelta(days=39), e + dt.timedelta(days=50), e + dt.timedelta(days=60)}
    return s

def window_open(now=None):
    v = (now or dt.datetime.now(dt.timezone.utc)).astimezone(VIENNA)
    if v.weekday() >= 5 or v.date() in at_holidays(v.year):
        return True
    return v.hour >= 20 or v.hour < 5

def next_window_open(now=None):
    t = (now or dt.datetime.now(dt.timezone.utc)).replace(second=0, microsecond=0)
    for _ in range(60 * 24 * 4):
        if window_open(t):
            return t
        t += dt.timedelta(minutes=1)
    return t

# ---------------------------------------------------------------- memory guard + state
def meminfo_avail_mb():
    with open('/proc/meminfo') as f:
        for ln in f:
            if ln.startswith('MemAvailable:'):
                return int(ln.split()[1]) // 1024
    return 0

def rss_tree_mb(pid=None):
    pid = pid or os.getpid(); tot = 0; todo = [pid]; seen = set()
    while todo:
        p = todo.pop()
        if p in seen: continue
        seen.add(p)
        try:
            with open(f'/proc/{p}/status') as f:
                for ln in f:
                    if ln.startswith('VmRSS:'): tot += int(ln.split()[1])
            with open(f'/proc/{p}/task/{p}/children') as f:
                todo += [int(x) for x in f.read().split()]
        except Exception:
            pass
    return tot // 1024

def merge_state(upd, collectors_delta=0):
    """Re-read state file, merge only atm_* keys, adjust 'collectors'. Never touches nlm_* or mode."""
    assert all(k.startswith('atm_') for k in upd), upd
    for _ in range(5):
        try:
            with open(STATE) as f: st = json.load(f)
            st.update(upd)
            if collectors_delta:
                st['collectors'] = max(0, int(st.get('collectors') or 0) + collectors_delta)
            tmp = STATE + f'.tmp_atm_{os.getpid()}'
            with open(tmp, 'w') as f: json.dump(st, f, indent=2, ensure_ascii=False)
            os.replace(tmp, STATE); return st
        except json.JSONDecodeError:
            time.sleep(0.5)
    raise RuntimeError('state merge failed')

class Guard:
    def __init__(self, log):
        self.log = log; self.tripped = None
        threading.Thread(target=self._run, daemon=True).start()
    def _run(self):
        while True:
            ma = meminfo_avail_mb(); rs = rss_tree_mb()
            if ma <= MEMAVAIL_MIN_MB or rs > RSS_MAX_MB:
                self.tripped = f'MemAvailable={ma}MB RSS={rs}MB'
                self.log(f'MEMGUARD trip {self.tripped} -> SIGTERM self')
                os.kill(os.getpid(), signal.SIGTERM); return
            time.sleep(5)

# ---------------------------------------------------------------- HTTP client (single connection, global delay)
class Client:
    def __init__(self, log, delay=DELAY, enforce_window=True, status_file=None):
        self.log = log; self.delay = delay; self.last = 0.0; self.cbad = 0; self.nreq = 0
        self.enforce_window = enforce_window; self.status_file = status_file
    def _wait_window(self):
        while self.enforce_window and not window_open():
            nxt = next_window_open(); self.log(f'office hours (Vienna) -> paused until {nxt.astimezone(VIENNA).isoformat()}')
            while not window_open(): time.sleep(30)
    def get(self, url, params=None, accept=None, max_tries=6):
        if params: url = url + '?' + urllib.parse.urlencode(params)
        back = 10
        for attempt in range(max_tries):
            self._wait_window()
            w = self.last + self.delay - time.time()
            if w > 0: time.sleep(w)
            req = urllib.request.Request(url, headers={'User-Agent': UA, **({'Accept': accept} if accept else {})})
            st = None; body = b''; hdr = {}
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    st = r.status; body = r.read(); hdr = dict(r.headers)
            except urllib.error.HTTPError as e:
                st = e.code; hdr = dict(e.headers or {})
                try: body = e.read()
                except Exception: body = b''
            except Exception as e:
                st = -1; body = repr(e).encode()
            self.last = time.time(); self.nreq += 1
            if self.status_file:
                with open(self.status_file, 'a') as f:
                    f.write(f"{dt.datetime.now().isoformat(timespec='seconds')} PT\t{url}\tHTTP {st}\tbytes={len(body)}\tctype={hdr.get('Content-Type','')}\n")
            if st in (403, 429, 503):
                self.cbad += 1
                if self.cbad >= 3: raise Stop(f'3 consecutive {st} (last {url})')
            elif st != -1:
                self.cbad = 0
            if st == 200: return st, hdr, body
            if st == 404: return st, hdr, body
            if st == 500 and attempt >= 1:
                return st, hdr, body
            if st in (429, 500, 502, 503, 504, -1):
                ra = hdr.get('Retry-After'); s = int(ra) if (ra or '').isdigit() else back
                self.log(f'HTTP {st} {url} -> backoff {min(s,300)}s'); time.sleep(min(s, 300)); back = min(back * 2, 300); continue
            return st, hdr, body
        return st, hdr, body

def api_search(cli, app, page=1, size='OneHundred', **kw):
    p = {'Applikation': app, 'DokumenteProSeite': size, 'Seitennummer': str(page)}; p.update(kw)
    st, hdr, body = cli.get(API, p, accept='application/json')
    if st != 200: raise ApiError(f'API HTTP {st} for {p}: {body[:300]!r}')
    d = json.loads(body.decode('utf-8'))
    res = d['OgdSearchResult']
    if 'Error' in res: raise ApiError(f"API error {res['Error']}")
    r = res['OgdDocumentResults']; refs = r.get('OgdDocumentReference') or []
    if isinstance(refs, dict): refs = [refs]
    return int(r['Hits']['#text']), refs, body

# ---------------------------------------------------------------- metadata
def aslist(x):
    if x is None: return []
    return x if isinstance(x, list) else [x]

def items(x):
    if x is None: return []
    if isinstance(x, dict) and 'item' in x: return [str(i) for i in aslist(x['item'])]
    return [str(i) for i in aslist(x)]

def content_refs(ref):
    out = []
    for c in aslist(ref['Data'].get('Dokumentliste', {}).get('ContentReference')):
        urls = {u.get('DataType'): u.get('Url') for u in aslist(c.get('Urls', {}).get('ContentUrl'))}
        out.append({'type': c.get('ContentType'), 'name': c.get('Name'), 'urls': urls})
    return out

GKZ_RE = re.compile(r'^GEMREA?_[A-Z]{2}_(\d{5})')

def parse_meta(ref, bezirke=None):
    m = ref['Data']['Metadaten']; t = m['Technisch']; a = m.get('Allgemein', {}); g = m.get('Gemeinden', {})
    app = t['Applikation']; rid = t['ID']
    gm = GKZ_RE.match(rid); gkz = gm.group(1) if gm else ''
    bl = g.get('Bundesland') or ''
    bl_iso = BL_NAME2ISO.get(bl.strip()) or GKZ2ISO.get(gkz[:1], 'AT-0')
    sub = g.get(app, {}) or {}
    gemeinde = g.get('Gemeinde') or t.get('Organ') or ''
    bez_code = gkz[:3] if gkz else ''
    if gkz.startswith('9'):  # Wien: one Gemeinde (Statistik GKZ 90001); RIS IDs use 90101
        bez_code, bez_name = '900', 'Wien'
    else:
        bez_name = sub.get('Bezirk') or (bezirke or {}).get(bez_code, '')
    gem_stat = GEMLISTE.get('90001' if gkz.startswith('9') else gkz, '')
    cr = content_refs(ref)
    main = next((c for c in cr if c['type'] == 'MainDocument'), cr[0] if cr else {'urls': {}})
    md = {
        'application': app, 'ris_id': rid, 'gemeinde': gemeinde, 'organ': t.get('Organ'), 'einbringer': t.get('Einbringer'),
        'gkz': gkz, 'gemeinde_statistik_austria': gem_stat, 'bezirk': bez_name, 'bezirk_code': bez_code, 'bundesland': bl.strip(), 'bundesland_code': bl_iso,
        'gemeindeverband': sub.get('Gemeindeverband') or g.get('Gemeindeverband'),
        'typ': (g.get('Typ') or '').strip(), 'kurztitel': re.sub(r'\s+', ' ', g.get('Kurztitel') or '').strip(),
        'titel': re.sub(r'\s+', ' ', g.get('Titel') or '').strip(),
        'geschaeftszahl': items(g.get('Geschaeftszahl')), 'indizes': items(sub.get('Indizes')),
        'inkrafttretensdatum': sub.get('Inkrafttretensdatum'), 'ausserkrafttretensdatum': sub.get('Ausserkrafttretensdatum'),
        'kundmachungsorgan_nr': sub.get('KundmachungsorganNr'), 'kundmachungsdatum': sub.get('Kundmachungsdatum'),
        'planliche_darstellung': g.get('PlanlicheDarstellung'), 'anmerkung': g.get('Anmerkung'),
        'homepage_gemeinde': sub.get('HomepageDerGemeinde'), 'geaendert': a.get('Geaendert'),
        'dokument_url': a.get('DokumentUrl'), 'main_urls': main['urls'],
        'attachments': [{'name': c['name'], 'urls': c['urls']} for c in cr if c is not main],
    }
    return md

# ---------------------------------------------------------------- text extraction
def _norm_ws(s):
    s = s.replace('\xa0', ' ').replace('\u00ad', '')
    s = re.sub(r'[ \t\f\v]+', ' ', s)
    s = re.sub(r' *\n *', '\n', s)
    return re.sub(r'\n{3,}', '\n\n', s).strip()

def xml_to_blocks(xml_bytes):
    """RIS risdok XML -> list of (ct/typ, text) blocks from <nutzdaten>, skipping layout/meta."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_bytes)
    def lname(e): return e.tag.rsplit('}', 1)[-1]
    nutz = None
    for e in root.iter():
        if lname(e) == 'nutzdaten': nutz = e; break
    if nutz is None: nutz = root
    blocks = []
    SKIP = {'kzinhalt', 'fzinhalt', 'layoutdaten', 'metadaten', 'binary'}  # binary = embedded image (src path only)
    def txt(e):
        parts = []
        def rec(x):
            n = lname(x)
            if n in SKIP: return
            if n == 'br': parts.append('\n')
            if n in ('nbsp', 'tab'): parts.append(' ')
            if x.text: parts.append(x.text)
            for ch in x:
                rec(ch)
                if ch.tail: parts.append(ch.tail)
        rec(e); return ''.join(parts)
    def walk(e):
        for ch in e:
            n = lname(ch)
            if n in SKIP: continue
            if n in ('absatz', 'ueberschrift', 'table', 'liste', 'schlussteil', 'gldsym') or (n == 'abschnitt' and not len(ch)):
                if n == 'table':
                    rows = []
                    for tr in ch.iter():
                        if lname(tr) == 'tr':
                            cells = [_norm_ws(txt(td)).replace('\n', ' ') for td in tr if lname(td) in ('td', 'th')]
                            rows.append(' | '.join(c for c in cells))
                    t = '\n'.join(r for r in rows if r.strip())
                else:
                    t = _norm_ws(txt(ch))
                if t: blocks.append((ch.get('typ') or ch.get('ct') or n, t))
            else:
                walk(ch)
    walk(nutz)
    return blocks

PARA_RE = re.compile(r'^\s*(§\s*\d+\s?[a-z]?|Art(?:ikel|\.)\s*[IVXLC\d]+[a-z]?)\.?\s*(.*)$', re.S)
ANNEX_RE = re.compile(r'^\s*(Anlage|Beilage|Anhang)\s*([A-Z\d]+|[IVX]+)?\s*[:.]?\s*$', re.I)

def head_label(first):
    """Return normalized label if a block's first line is a section heading ('§ 3', '§ 3 Geltungsbereich', 'Artikel II')."""
    if len(first) > 120: return None
    m = PARA_RE.match(first)
    if not m: return None
    rest = m.group(2).strip()
    if rest:
        if len(rest) > 90 or rest[:1].islower() or re.search(r'[.;,]$', rest) or re.match(r'(Abs|Z|lit)\b', rest):
            return None
    return re.sub(r'\s+', ' ', m.group(1)).strip()

SECTION_RE = re.compile(r'^\s*((?:[IVXLC]+|\d+)\.\s*(?:Abschnitt|Hauptstück|Teil)|(?:Abschnitt|Hauptstück|Teil)\s+(?:[IVXLC]+|\d+)\.?)\s*[:.\-–]?\s*(.{0,80})$')

def _split_on_sections(blocks):
    secs = []; cur = None; pre = []
    for typ, t in blocks:
        first = t.split('\n', 1)[0].strip()
        m = SECTION_RE.match(first) if len(first) <= 100 else None
        if m:
            cur = {'label': re.sub(r'\s+', ' ', m.group(1)).strip(), 'rt': 'section', 'body': [t]}; secs.append(cur)
        elif cur is None: pre.append(t)
        else: cur['body'].append(t)
    return secs, pre

def split_sections(blocks):
    """Group blocks into (label, number, record_type, text). Preamble before first § kept as 'preamble'."""
    secs = []; cur = None; pre = []
    for typ, t in blocks:
        first = t.split('\n', 1)[0].strip()
        lab = head_label(first)
        if lab: lab = re.sub(r'^§\s*', '§ ', lab)
        if lab:
            if cur and cur['label'] == lab and len(cur['body']) == 1 and len(cur['body'][0]) < 120:
                cur['body'].append(t); continue
            cur = {'label': lab, 'rt': 'article', 'body': [t]}; secs.append(cur)
        elif cur is not None and ANNEX_RE.match(first):
            cur = {'label': re.sub(r'\s+', ' ', first).strip(' :.'), 'rt': 'annex', 'body': [t]}; secs.append(cur)
        elif cur is None:
            pre.append(t)
        else:
            cur['body'].append(t)
    if not secs:  # no § / Artikel structure -> fall back to Abschnitt/Hauptstueck/Teil headings
        secs, pre = _split_on_sections(blocks)
        if len(secs) < 2: secs, pre = [], [t for _, t in blocks]
    # fold a table of contents (short heading-only sections whose first label recurs later) into the preamble
    if len(secs) >= 4:
        j = next((i for i in range(1, len(secs)) if secs[i]['label'] == secs[0]['label']), 0)
        if j >= 2 and all(sum(len(b) for b in x['body']) < 300 for x in secs[:j]):
            for x in secs[:j]: pre += x['body']
            secs = secs[j:]
    out = []
    if pre and secs: out.append(('Präambel', '0', 'preamble', '\n'.join(pre)))
    for s in secs:
        if s['rt'] == 'section':
            num = re.sub(r'\s*(Abschnitt|Hauptstück|Teil)\s*', '', s['label']).strip(' .') or s['label']
        else:
            num = re.sub(r'^(§|Art(?:ikel|\.)?)\s*', '', s['label']).strip() or s['label']
        out.append((s['label'], num, s['rt'], '\n'.join(s['body'])))
    return out, pre

def pdf_to_text(pdf_bytes):
    p = subprocess.run(['pdftotext', '-enc', 'UTF-8', '-q', '-', '-'], input=pdf_bytes, capture_output=True, timeout=180)
    return p.stdout.decode('utf-8', 'replace')

SIG_RE = re.compile(r'(Dieses Dokument wurde amtssigniert|Signaturwert|Prüfinformation|Informationen zur Prüfung|Hinweis:\s*Dieses Dokument)', re.I)

def pdf_blocks(text):
    """Split pdftotext output into blocks (line breaks kept); section headings become their own blocks;
    drop page numbers ('1 von 3'), the RIS URL line and repeated page headers/footers."""
    pages = text.split('\f')
    cnt = {}
    for pg in pages:
        for ln in set(l.strip() for l in pg.split('\n') if l.strip()):
            cnt[ln] = cnt.get(ln, 0) + 1
    npages = sum(1 for p in pages if p.strip())
    rep = {l for l, c in cnt.items() if npages >= 2 and c >= 2 and c >= npages * 0.5 and len(l) < 160
           and not head_label(l) and not re.fullmatch(r'[\d.,\s€%]+', l)}
    blocks = []
    for pg in pages:
        buf = []
        def flush():
            if buf: blocks.append(('pdf', _norm_ws('\n'.join(buf)))); buf.clear()
        for ln in pg.split('\n'):
            st = ln.strip()
            if not st:
                flush(); continue
            if st in rep or st == 'www.ris.bka.gv.at' or re.fullmatch(r'(Seite\s*)?\d+\s*(von|/)\s*\d+', st):
                continue
            if head_label(st):
                flush(); blocks.append(('pdf_head', st)); continue
            buf.append(st)
        flush()
    return [(t, b) for t, b in blocks if b], sorted(rep)

def html_text(html_bytes):
    """Reference-only plain text of the API-returned HTML rendition (used in hand check)."""
    from html.parser import HTMLParser
    class P(HTMLParser):
        def __init__(s): super().__init__(); s.o = []; s.skip = 0
        def handle_starttag(s, t, a):
            cls = dict(a).get('class') or ''
            if s.skip: 
                if t not in ('br', 'img', 'hr', 'meta', 'link', 'input'): s.skip += 1
                return
            if t in ('script', 'style', 'head') or 'sr-only' in cls.split(): s.skip += 1; return
            if t in ('p', 'div', 'br', 'tr', 'h1', 'h2', 'h3', 'h4', 'li', 'td'): s.o.append('\n')
        def handle_endtag(s, t):
            if s.skip and t not in ('br', 'img', 'hr', 'meta', 'link', 'input'): s.skip -= 1
        def handle_data(s, d):
            if not s.skip: s.o.append(d)
    p = P(); p.feed(html_bytes.decode('utf-8', 'replace')); return _norm_ws(''.join(p.o))

# ---------------------------------------------------------------- record building (hub schema)
LAW_COLS = ['id', 'title', 'text', 'source_url', 'source_type', 'jurisdiction', 'country', 'language', 'eli', 'date',
            'date_issued', 'retrieved_at', 'license', 'law_status', 'identifier', 'official_identifier', 'article_count',
            'json_path', 'metadata_json']
ART_COLS = ['law_id', 'id', 'title', 'text', 'source_url', 'document_number', 'article_number', 'record_type', 'metadata_json']

def law_id_for(md):
    return f"at-{md['application'].lower()}-{md['ris_id']}"

def jurisdiction_for(md):
    if md['gkz']: return f"{md['bundesland_code']}-G{md['gkz']}"
    return f"{md['bundesland_code']}-G00000"

def build_record(md, raw, kind, src_url, cache_path, retrieved_at):
    if kind == 'xml':
        blocks = xml_to_blocks(raw); rep = []
    else:
        blocks, rep = pdf_blocks(pdf_to_text(raw))
        # drop trailing signature-block noise (Amtssignatur) from the law text only if clearly a signature box
    full = '\n'.join(b for _, b in blocks).strip()
    secs, pre = split_sections(blocks)
    lid = law_id_for(md)
    today = dt.date.today().isoformat()
    akd = md.get('ausserkrafttretensdatum')
    if md['application'] == 'Gr':
        status = 'repealed' if (akd and akd <= today) else 'current'
        date = md.get('inkrafttretensdatum') or ''
        issued = md.get('kundmachungsdatum') or ''
        off = '; '.join(md['geschaeftszahl'])
        stype = 'ris_gemeinderecht'
    else:
        status = 'promulgated'
        date = md.get('kundmachungsdatum') or ''
        issued = md.get('kundmachungsdatum') or ''
        off = md.get('kundmachungsorgan_nr') or ''
        stype = 'ris_gemeinderecht_authentisch'
    lmeta = dict(md); lmeta.update({'schema_version': 'collection_record.v1', 'record_type': 'law', 'content_kind': kind,
                  'attribution': ATTRIBUTION, 'license_url': 'https://creativecommons.org/licenses/by/4.0/',
                  'collector': 'at_municipal_collect.py', 'pdf_repeated_lines_removed': rep[:20] if rep else []})
    arts = []; used = {}
    for i, (lab, num, rt, t) in enumerate(secs):
        slug = re.sub(r'[^0-9A-Za-zäöüÄÖÜß]+', '-', num).strip('-') or str(i)
        base = f"{lid}-{'p' if lab.startswith('§') else ('art' if rt == 'article' else rt)}-{slug}"
        used[base] = used.get(base, 0) + 1
        aid = base if used[base] == 1 else f'{base}-{used[base]}'
        arts.append({'law_id': lid, 'id': aid, 'title': f"{md.get('kurztitel') or md.get('titel') or ''} — {lab}".strip(' —'),
                     'text': t, 'source_url': src_url, 'document_number': lab, 'article_number': num, 'record_type': rt,
                     'metadata_json': json.dumps({'law_identifier': md['ris_id'], 'application': md['application'], 'gkz': md['gkz'],
                                                  'gemeinde': md['gemeinde'], 'seq': i}, ensure_ascii=False)})
    law = {'id': lid, 'title': (md.get('titel') or md.get('kurztitel') or '').strip(), 'text': full, 'source_url': src_url,
           'source_type': stype, 'jurisdiction': jurisdiction_for(md), 'country': 'Austria', 'language': 'de', 'eli': '',
           'date': date, 'date_issued': issued, 'retrieved_at': retrieved_at, 'license': 'cc-by-4.0', 'law_status': status,
           'identifier': md['ris_id'], 'official_identifier': off, 'article_count': len(arts), 'json_path': cache_path,
           'metadata_json': json.dumps(lmeta, ensure_ascii=False)}
    return law, arts

# ---------------------------------------------------------------- content fetch with gz cache
def cache_path_for(md, kind):
    return f"{BASE}/cache/content/{md['application']}/{md['ris_id']}.{kind}.gz"

def fetch_main(cli, md, want_html=False):
    """Returns (kind, raw, url, cache_path). Gr: XML preferred, PDF fallback. GrA: authentic PDF."""
    u = md['main_urls']
    order = [('xml', u.get('Xml')), ('pdf', u.get('Pdf') or u.get('Authentisch'))]
    for kind, url in order:
        if not url: continue
        if not url.startswith('https://ogd.ris.bka.gv.at/Dokumente/'): continue  # API content URLs only
        cp = cache_path_for(md, kind)
        if os.path.exists(cp):
            with gzip.open(cp, 'rb') as f: return kind, f.read(), url, cp
        st, hdr, body = cli.get(url)
        if st == 200 and body:
            os.makedirs(os.path.dirname(cp), exist_ok=True)
            with gzip.open(cp + '.part', 'wb', compresslevel=6) as f: f.write(body)
            os.replace(cp + '.part', cp)
            return kind, body, url, cp
    return None, None, None, None

def fetch_html_ref(cli, md):
    url = md['main_urls'].get('Html')
    if not url or not url.startswith('https://ogd.ris.bka.gv.at/Dokumente/'): return None
    cp = cache_path_for(md, 'html')
    if os.path.exists(cp):
        with gzip.open(cp, 'rb') as f: return f.read()
    st, hdr, body = cli.get(url)
    if st == 200:
        os.makedirs(os.path.dirname(cp), exist_ok=True)
        with gzip.open(cp, 'wb') as f: f.write(body)
        return body
    return None

def _load_ref(name):
    p = f'{BASE}/ref/{name}.json'
    if os.path.exists(p):
        with open(p) as f: return json.load(f)
    return {}

GEMLISTE = _load_ref('gemliste')

def load_bezirke():
    p = f'{BASE}/ref/polbezirke.json'
    if os.path.exists(p):
        with open(p) as f: return json.load(f)
    return {}

# ---------------------------------------------------------------- modes
def mk_logger(path):
    def log(msg):
        line = f"{dt.datetime.now().isoformat(timespec='seconds')} PT {msg}"
        print(line, flush=True)
        if path:
            with open(path, 'a') as f: f.write(line + '\n')
    return log

def mode_full(args):
    ts = dt.datetime.now().strftime('%Y%m%dT%H%M%S')
    logp = os.environ.get('ATM_LOG') or f'/workspace/logs/at_municipal_collect_{ts}.log'
    log = mk_logger(None if os.environ.get('ATM_LOG') else logp)
    if not os.path.exists(NOTIFY_FILE) :
        log(f'REFUSING full run: {NOTIFY_FILE} missing (RIS OGD terms require prior mass-download notification)'); sys.exit(2)
    if meminfo_avail_mb() < 4608:
        log(f'REFUSING full run: MemAvailable {meminfo_avail_mb()}MB < 4.5G'); sys.exit(3)
    counted = {'v': False}; final = {'status': 'DONE'}
    def on_term(sig, frm):
        final['status'] = 'MEMSHED' if guard.tripped else 'STOPPED_SIGTERM'
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, on_term)
    merge_state({'atm_pid': os.getpid(), 'atm_log': logp, 'atm_status': 'COLLECTING',
                 'atm_started_pt': dt.datetime.now().astimezone().isoformat(timespec='seconds')}, collectors_delta=+1)
    counted['v'] = True
    guard = Guard(log)
    cli = Client(log, status_file=f'{BASE}/out/http_status.log')
    bez = load_bezirke()
    os.makedirs(f'{BASE}/out', exist_ok=True); os.makedirs(f'{BASE}/index', exist_ok=True)
    donep = f'{BASE}/out/done_ids.txt'
    done = set()
    if os.path.exists(donep):
        with open(donep) as f: done = set(l.strip() for l in f if l.strip())
    n_ok = n_fail = 0
    try:
        # Enumerate per application WITHOUT the Bundesland filter: the API returns HTTP 500 (Gr) / 0 hits (GrA)
        # for Bundesland=Oberoesterreich (probe 2026-10-04), so a per-Land loop would silently miss OOe.
        # Pass 2 (ImRisSeit=EinemMonat) picks up documents added while pass 1 was running.
        tally = {}
        for passno, extra in ((1, {}), (2, {'ImRisSeit': 'EinemMonat'})):
            for app in ('Gr', 'GrA'):
                page = 1; pages = None
                while True:
                    ip = f'{BASE}/index/{app}_pass{passno}_p{page:04d}.json.gz'
                    if os.path.exists(ip) and passno == 1:
                        with gzip.open(ip, 'rt') as f: pj = json.load(f)
                        hits, refs = pj['hits'], pj['refs']
                    else:
                        hits, refs, _ = api_search(cli, app, page=page, **extra)
                        with gzip.open(ip + '.part', 'wt') as f: json.dump({'hits': hits, 'refs': refs, 'page': page}, f)
                        os.replace(ip + '.part', ip)
                    pages = (hits + 99) // 100
                    for ref in refs:
                        md = parse_meta(ref, bez)
                        key = f"{app}:{md['ris_id']}"
                        tally[(app, md['bundesland_code'])] = tally.get((app, md['bundesland_code']), 0) + (passno == 1)
                        if key in done: continue
                        kind, raw, url, cp = fetch_main(cli, md)
                        if not raw:
                            n_fail += 1
                            with open(f'{BASE}/out/failed.jsonl', 'a') as f: f.write(json.dumps({'key': key, 'urls': md['main_urls']}) + '\n')
                            continue
                        law, arts = build_record(md, raw, kind, url, cp, dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
                        with gzip.open(f'{BASE}/out/records_{app}.jsonl.gz', 'at') as f:
                            f.write(json.dumps({'law': law, 'articles': arts}, ensure_ascii=False) + '\n')
                        with open(donep, 'a') as f: f.write(key + '\n')
                        done.add(key); n_ok += 1; del raw
                        if n_ok % 50 == 0:
                            log(f'progress ok={n_ok} fail={n_fail} done={len(done)} nreq={cli.nreq} pass{passno} {app} p{page}/{pages} memavail={meminfo_avail_mb()} rss={rss_tree_mb()}')
                            merge_state({'atm_progress': f'{len(done)}/~29810 docs, nreq={cli.nreq}, pass{passno} {app} p{page}/{pages}'})
                    if page >= pages or not refs: break
                    page += 1
        with open(f'{BASE}/out/tally_by_app_land.json', 'w') as f:
            json.dump({f'{k[0]}|{k[1]}': v for k, v in sorted(tally.items())}, f, indent=1)
        log(f'ALL DONE ok={n_ok} fail={n_fail} done={len(done)} nreq={cli.nreq}')
    except Stop as e:
        final['status'] = 'STOPPED_3X'; log(f'STOP: {e}')
    except SystemExit:
        pass
    except Exception as e:
        final['status'] = 'ERROR'; log(f'ERROR {e!r}')
    finally:
        if counted['v']:
            merge_state({'atm_status': final['status'], 'atm_pid': None,
                         'atm_ended_pt': dt.datetime.now().astimezone().isoformat(timespec='seconds'),
                         'atm_progress': f'{len(done)} docs, nreq={cli.nreq}'}, collectors_delta=-1)
            log(f"exit atm_status={final['status']}")

def write_parquet(laws, arts, outdir):
    import pyarrow as pa, pyarrow.parquet as pq
    os.makedirs(outdir, exist_ok=True)
    ls = pa.schema([(c, pa.int32() if c == 'article_count' else pa.string()) for c in LAW_COLS])
    as_ = pa.schema([(c, pa.string()) for c in ART_COLS])
    pq.write_table(pa.Table.from_pylist(laws, schema=ls), f'{outdir}/laws.parquet', compression='zstd')
    pq.write_table(pa.Table.from_pylist(arts, schema=as_), f'{outdir}/articles.parquet', compression='zstd')

def mode_build(args):
    outdir = args[0] if args else f"{BASE}/out/build_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}/data"
    laws, arts, seen = [], [], set()
    for app in ('Gr', 'GrA'):
        p = f'{BASE}/out/records_{app}.jsonl.gz'
        if not os.path.exists(p): continue
        with gzip.open(p, 'rt') as f:
            for ln in f:
                r = json.loads(ln)
                if r['law']['id'] in seen: continue
                seen.add(r['law']['id']); laws.append(r['law']); arts += r['articles']
    link_gr_gra(laws)
    write_parquet(laws, arts, outdir); print(outdir, len(laws), len(arts))

def _tok(s):
    import collections
    return collections.Counter(w for w in re.findall(r'[0-9a-zäöüß]+', s.lower()) if len(w) >= 2)

def link_gr_gra(laws, min_containment=0.9, max_days=60):
    """Gr (consolidated/selected texts) and GrA (authentic Kundmachungen) are both kept. Where the same
    municipality (GKZ) has a Gr and a GrA document whose texts overlap (token containment >= 0.9) and whose dates
    (Gr Inkrafttretensdatum vs GrA Kundmachungsdatum) are within 60 days, both rows get cross-links in metadata_json
    ('same_text_as' + 'dedup_role': GrA = authentic, Gr = consolidated). No rows are dropped."""
    by = {}
    for i, l in enumerate(laws):
        by.setdefault(l['jurisdiction'], {}).setdefault(l['source_type'], []).append(i)
    n = 0
    for j, d in by.items():
        gr, gra = d.get('ris_gemeinderecht', []), d.get('ris_gemeinderecht_authentisch', [])
        if not gr or not gra: continue
        tg = {i: _tok(laws[i]['text']) for i in gr}; ta = {i: _tok(laws[i]['text']) for i in gra}
        for i in gr:
            for k in gra:
                try:
                    dd = abs((dt.date.fromisoformat(laws[i]['date'][:10]) - dt.date.fromisoformat(laws[k]['date'][:10])).days)
                except Exception:
                    continue
                if dd > max_days: continue
                a, b = tg[i], ta[k]; inter = sum((a & b).values())
                c = inter / max(1, min(sum(a.values()), sum(b.values())))
                if c >= min_containment:
                    for x, y, role in ((i, k, 'consolidated_copy'), (k, i, 'authentic')):
                        m = json.loads(laws[x]['metadata_json'])
                        m.setdefault('same_text_as', []).append({'id': laws[y]['id'], 'containment': round(c, 3), 'date_delta_days': dd})
                        m['dedup_role'] = role
                        laws[x]['metadata_json'] = json.dumps(m, ensure_ascii=False)
                    n += 1
    print('gr/gra linked pairs:', n)
    return n

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'full': mode_full(sys.argv[2:])
    elif mode == 'build': mode_build(sys.argv[2:])
    elif mode in ('gate', 'sample', 'handcheck'):
        import at_municipal_handcheck as H  # helper module (gate/sample/handcheck drivers)
        getattr(H, 'mode_' + mode)(sys.argv[2:])
    else:
        print(__doc__); sys.exit(1)

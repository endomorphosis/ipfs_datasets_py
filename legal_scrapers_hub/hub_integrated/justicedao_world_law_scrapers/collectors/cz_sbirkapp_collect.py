#!/usr/bin/env python3
"""DRAFT - CZ municipal/regional legal acts collector for sbirkapp.gov.cz (Sbírka právních předpisů územních samosprávných celků a některých správních úřadů, SPP).
STATUS: draft written during the CoS-approved PROBE (2026-10-04). DO NOT RUN `full` WITHOUT A CoS GO.

Modes
  selftest                 offline: extract + split the cached probe documents (no network)
  full --cos-go TOKEN      full run; refuses unless TOKEN matches cz_sbirkapp/COS_GO_FULL (written by CoS/parent)
  build OUTDIR             offline: laws.parquet + articles.parquet (national hub schema copied from NL staging parquet)

Gate evidence (cz_sbirkapp/robots, cz_sbirkapp/terms): robots.txt = HTTP 404 (no rules); no terms-of-use page; statute: zákon 35/2021 Sb. § 1(3)
'Sbírka právních předpisů je bezplatně a neomezeně veřejně přístupná způsobem umožňujícím dálkový přístup'; copyright: zákon 121/2000 Sb. § 3 písm. a)
(úřední dílo - právní předpis - not protected). No public API for SPP (the e-Sbírka REST API is a different system and requires registration - not used).
Enumeration: /vyhledavani/vysledek?hlavni_typ=pp&kod_vusc=<VÚSC>&page=N (50 rows/page; per-region slicing gives the region for free) + hlavni_typ=oa.
  The CSV/XLSX export is an asynchronous server job (/export/<token>/prubeh) that stalled at 617/78,874 in the probe -> not used.
Per act: /detail/<SPPID> (metadata: publisher, IČO, ID DS, druh, číslo, zmocnění, oblast, dates, platnost, verze, návaznosti) + /detail/<SPPID>/text
  (ODT/DOCX/DOC/PDF original) + optional /detail/<SPPID>/prilohy/<n> (attachments; index only by default).
Guards: single process, >=2.0 s between request starts, honest UA, host-locked, no redirects off-host, RSS>300 MB stop, STRICT pause/resume/TERM guard (see CZ T2 section),
  3 consecutive 403/429/503 stop, backoff on 5xx/conn errors, SIGTERM clean exit, resume-safe ledger, state file: czp_* keys + collectors only.
Jurisdiction: CZ-<ISO 3166-2 kraj code> for kraje (CZ-10 Praha, CZ-20 Středočeský, ... CZ-80 Moravskoslezský);
  CZ-<kraj>-<ČSÚ/RÚIAN kód obce> for obce/města/městyse (e.g. CZ-20-539902 Zvole); CZ-10-<MČ IČO> for Prague districts; state bodies: CZ-<kraj> (KHS) or CZ.
  IČO -> kód obce/kraj via the official Czech POINT Seznam OVM file (cz_sbirkapp/ref/ico_map.json; 567/567 probe publishers mapped).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, re, json, gzip, time, signal, zipfile, subprocess, html, hashlib, datetime, tempfile, threading
import urllib.parse
CZ_USR = os.environ.get('CZ_USR_ROOT', '')  # user-space deb root (/workspace/usr); '' = system /usr, set for CZ collector only
sys.path.insert(0, '/workspace/scripts')
B = '{_CORPORA}/cz_sbirkapp'; HOST = 'sbirkapp.gov.cz'; BASE = f'https://{HOST}'
STATE = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'
UA = 'legal-corpora-cz-collector/1.0 (research corpus of official Czech municipal and regional legal acts; polite single-stream; contact via huggingface.co/endomorphosis)'
DELAY = 2.0; RSS_MB = 300; MEMAVAIL_MB = 3700
LICENSE = ('Not protected by copyright: zákon č. 121/2000 Sb. (autorský zákon) § 3 písm. a) - úřední dílo, zejména právní předpis. Source: Sbírka právních předpisů '
           'územních samosprávných celků a některých správních úřadů (sbirkapp.gov.cz, Ministerstvo vnitra), publicly accessible free of charge and without restriction '
           'per zákon č. 35/2021 Sb. § 1 odst. 3.')
LAW_COLS = ['id', 'title', 'text', 'source_url', 'source_type', 'jurisdiction', 'country', 'language', 'eli', 'date', 'date_issued', 'retrieved_at',
            'license', 'law_status', 'identifier', 'official_identifier', 'article_count', 'json_path', 'metadata_json']
ART_COLS = ['law_id', 'id', 'title', 'text', 'source_url', 'document_number', 'article_number', 'record_type', 'metadata_json']
VUSC = {'19': '10', '27': '20', '35': '31', '43': '32', '51': '41', '60': '42', '78': '51', '86': '52', '94': '53', '108': '63', '116': '64', '124': '71', '141': '72', '132': '80'}  # RÚIAN VÚSC -> ISO 3166-2:CZ
STOP = False
def _sig(*a):
    global STOP; STOP = True
signal.signal(signal.SIGTERM, _sig)
def log(*a): print(time.strftime('%H:%M:%S'), *a, flush=True)
def memavail(): return int(open('/proc/meminfo').read().split('MemAvailable:')[1].split()[0]) // 1024
def rss():
    for l in open('/proc/self/status'):
        if l.startswith('VmRSS'): return int(l.split()[1]) // 1024
    return 0
def state_merge(upd, collectors_delta=0):
    s = json.load(open(STATE))
    for k, v in upd.items():
        assert k.startswith('czp_'), k
        s[k] = v
    if collectors_delta: s['collectors'] = max(0, int(s.get('collectors', 0)) + collectors_delta)
    tmp = STATE + '.czp.tmp'; json.dump(s, open(tmp, 'w'), indent=1); os.replace(tmp, STATE)
# ---------------- text extraction ----------------
def _odt_text(data):
    from lxml import etree
    z = zipfile.ZipFile(data); root = etree.fromstring(z.read('content.xml'))
    T = 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'; TB = 'urn:oasis:names:tc:opendocument:xmlns:table:1.0'
    def run(el):
        out = [el.text or '']
        for c in el:
            tag = etree.QName(c).localname if isinstance(c.tag, str) else ''
            if tag == 's': out.append(' ' * int(c.get(f'{{{T}}}c', '1')))
            elif tag == 'tab': out.append('\t')
            elif tag == 'line-break': out.append('\n')
            elif tag in ('note', 'annotation'): pass
            else: out.append(run(c))
            out.append(c.tail or '')
        return ''.join(out)
    paras = []
    for el in root.iter(f'{{{T}}}p', f'{{{T}}}h'):
        if el.getparent() is not None and etree.QName(el.getparent()).localname in ('p', 'h'): continue
        paras.append(run(el))
    return '\n'.join(paras)
def _docx_text(data):
    """Transitional and Strict OOXML (namespace-agnostic: matches local names). Includes text boxes; automatic list numbering is not materialised."""
    from lxml import etree
    z = zipfile.ZipFile(data); root = etree.fromstring(z.read('word/document.xml')); paras = []
    for p in root.iter():
        if not isinstance(p.tag, str) or etree.QName(p).localname != 'p': continue
        if any(isinstance(a.tag, str) and etree.QName(a).localname == 'p' for a in p.iterancestors()): continue
        buf = []
        for el in p.iter():
            ln = etree.QName(el).localname if isinstance(el.tag, str) else ''
            if ln == 't': buf.append(el.text or '')
            elif ln == 'tab': buf.append('\t')
            elif ln in ('br', 'cr'): buf.append('\n')
        paras.append(''.join(buf))
    return '\n'.join(paras)
def _soffice_text(path):
    d = tempfile.mkdtemp(prefix='czso_', dir='/workspace/tmp')
    subprocess.run(['soffice', '--headless', '--norestore', f'-env:UserInstallation=file://{d}/profile', '--convert-to', 'txt:Text (encoded):UTF8', '--outdir', d, path],
                   capture_output=True, timeout=180)
    outs = [f for f in os.listdir(d) if f.endswith('.txt')]
    t = open(os.path.join(d, outs[0]), encoding='utf-8', errors='replace').read() if outs else ''
    subprocess.run(['rm', '-rf', d]); return t
_DIC = None; _EN = None; _QC = {}
def _word_ok(w):
    global _DIC, _EN
    if _DIC is None:
        from spylls.hunspell import Dictionary
        _DIC = Dictionary.from_files(CZ_USR+'/usr/share/hunspell/cs_CZ'); _EN = {x.strip().lower() for x in open(CZ_USR+'/usr/share/dict/american-english', errors='ignore')}
    lw = w.lower()
    if lw not in _QC:
        try: _QC[lw] = bool(_DIC.lookup(w) or _DIC.lookup(lw) or lw in _EN)
        except Exception: _QC[lw] = False
    return _QC[lw]
def _hun_ok(words):
    """batch verdicts with the hunspell binary: ok if w, w.lower() or w.lower().capitalize() is accepted by cs_CZ, or w.lower() is in the English list. None -> spylls fallback"""
    global _EN
    import shutil
    if not words: return {}
    if os.environ.get('CZ_QUALITY_ENGINE') == 'spylls' or not shutil.which('hunspell'): return None
    try:
        var = [v for w in words for v in (w, w.lower(), w.lower().capitalize())]
        r = subprocess.run(['hunspell', '-d', CZ_USR+'/usr/share/hunspell/cs_CZ', '-i', 'utf-8', '-l'], input='\n'.join(var) + '\n', capture_output=True, text=True, timeout=300)
        if r.returncode != 0: return None
        bad = set(r.stdout.split('\n'))
        if _EN is None: _EN = {x.strip().lower() for x in open(CZ_USR+'/usr/share/dict/american-english', errors='ignore')}
        return {w: (w not in bad) or (w.lower() not in bad) or (w.lower().capitalize() not in bad) or (w.lower() in _EN) for w in words}
    except Exception: return None
def text_quality(text, pages=None, max_unique=4000):
    """dict_ratio = share of alphabetic tokens (len>=2) found in hunspell cs_CZ (spylls) or the English wordlist; garbage_ratio = junk tokens."""
    toks = text.split(); alpha = [re.sub(r'^[\W_]+|[\W_]+$', '', t) for t in toks]
    alpha = [a for a in alpha if re.fullmatch(r'[^\W\d_]{2,}', a or '')]
    from collections import Counter
    c = Counter(alpha); top = c.most_common(max_unique); covered = sum(n for _, n in top)
    hv = _hun_ok([w for w, _ in top])   # CoS 02:58 PT: C hunspell (~31 MB child) instead of spylls (~250 MB); 0.05% token-weighted verdict diff on T2 sample
    good = sum(n for w, n in top if (hv[w] if hv is not None else _word_ok(w)))
    def junk(t):
        core = re.sub(r'^[\W_]+|[\W_]+$', '', t)
        if not core: return len(t) > 3
        if len(re.findall(r'[^\w.,;:()\'"/%§\-–]', core)) / len(core) > 0.3: return True
        if len(core) > 4 and any(a.islower() and b.isupper() and c.islower() for a, b, c in zip(core, core[1:], core[2:])): return True
        return False
    nonws = len(re.sub(r'\s', '', text))
    return dict(chars=nonws, chars_per_page=round(nonws / pages, 1) if pages else None, tokens=len(toks), alpha_tokens=len(alpha),
                dict_engine='hunspell' if hv is not None else 'spylls', dict_ratio=round(good / max(covered, 1), 4), garbage_ratio=round(sum(junk(t) for t in toks) / max(len(toks), 1), 4))
def pdf_pages(p):
    m = re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', p], capture_output=True, text=True).stdout); return int(m.group(1)) if m else 0
def ocr_pdf(p, workers=1):
    d = tempfile.mkdtemp(prefix='czocr_', dir='/workspace/tmp')
    subprocess.run(['pdftoppm', '-r', '300', '-scale-to', '3508', '-gray', '-png', p, f'{d}/pg'], check=True)
    texts = []
    for im in sorted(os.listdir(d)):
        texts.append(subprocess.run(['tesseract', os.path.join(d, im), '-', '-l', 'ces+eng'], capture_output=True, text=True, env=dict(os.environ, OMP_THREAD_LIMIT='1')).stdout)
    subprocess.run(['rm', '-rf', d]); return '\n\f'.join(texts)
def sniff(path):
    h = open(path, 'rb').read(8)
    if h.startswith(b'%PDF'): return 'pdf'
    if h.startswith(b'PK'):
        names = zipfile.ZipFile(path).namelist()
        if 'content.xml' in names: return 'odt'
        if 'word/document.xml' in names: return 'docx'
        return 'zip'
    if h.startswith(b'\xd0\xcf\x11\xe0'): return 'doc'
    if h.startswith(b'{\\rtf'): return 'rtf'
    return 'unknown'
def extract(path):
    """-> (text, method, pages_or_None)"""
    kind = sniff(path)
    if kind == 'odt': return _odt_text(path), 'odt_xml', None
    if kind == 'docx': return _docx_text(path), 'docx_xml', None
    if kind in ('doc', 'rtf'): return _soffice_text(path), f'{kind}_soffice', None
    if kind == 'pdf':
        n = pdf_pages(path); t = subprocess.run(['pdftotext', path, '-'], capture_output=True, text=True).stdout
        if len(re.sub(r'\s', '', t)) / max(n, 1) >= 200 and text_quality(t)['dict_ratio'] >= 0.80: return t, 'pdf_text_layer', n
        # scans, weak uploader OCR layers and broken font encodings (e.g. 'pohYebnictví', 'msta') -> OCR
        return ocr_pdf(path), 'pdf_ocr_tesseract_ces+eng', n
    return '', f'unsupported_{kind}', None
# ---------------- article split ----------------
ROMAN = {r: i + 1 for i, r in enumerate('I II III IV V VI VII VIII IX X XI XII XIII XIV XV XVI XVII XVIII XIX XX XXI XXII XXIII XXIV XXV'.split())}
H_CL = re.compile(r'^\s*(?:Čl\.|Čl|Článek|ČLÁNEK|Článek č\.|Cl\.|Clanek|čl\.)\s*([0-9]{1,3}|[IVX]{1,6})\s*[.:]?\s*(.{0,90})$')
H_PAR = re.compile(r'^\s*§\s*([0-9]{1,3})\s*([a-z](?![^\W\d_]))?\s*[.:]?\s*(.{0,90})$')
def _num(tok):
    return int(tok) if tok.isdigit() else ROMAN.get(tok)
_OCR_CL = re.compile(r'^(\s*)(?:Č|C|č|c)\s?[lI1|](?=[\s.:]|\d|[IVX])')
def _candidates(lines, rx):
    out = []
    for i, l in enumerate(lines):
        if rx is H_CL: l = _OCR_CL.sub(r'\1Čl', l)   # OCR variants: 'ČI. 1', 'Cl. 2', 'C13' (= Čl 3), 'Č1.2', 'ČI 1'
        m = rx.match(l)
        if not m: continue
        rest = m.group(m.lastindex).strip() if m.lastindex else ''
        if re.match(r'(odst|písm|zákona|zák\.|vyhlášky|této|bod|a\s|až\s)', rest, re.I): continue  # in-sentence cross-reference
        n = _num(m.group(1))
        if n: out.append((i, n, m.group(1), rest))
    return out
def _sequence(c):
    seq, last = [], 0
    for i, n, tok, rest in c:
        if last < n <= last + 3: seq.append((i, n, tok, rest)); last = n   # tolerate <=2 skipped numbers (source numbering errors / OCR loss)
    return seq
END = re.compile(r'^\s*(Příloha|PŘÍLOHA|P ř í l o h a)\b|^\s*(starost[a|ka]|místostarost[a|ka]|primátor(ka)?|hejtman(ka)?|náměstek|L\.\s?S\.)\s*$|^\s*\.{5,}|^\s*…{3,}', re.I)
def split_articles(text):
    """Split into články (Čl./Článek) or paragrafy (§) - whichever scheme gives the longer document-own sequence 1..n (arabic or Roman).
    Cross-references ('čl. 3 odst. 2', '§ 14 zákona') are not headings. Last article is cut at the signature block / Příloha.
    Returns (articles, info) with info = scheme, gaps, n_candidates."""
    lines = text.split('\n')
    best = None
    for scheme, rx in (('clanek', H_CL), ('paragraf', H_PAR)):
        seq = _sequence(_candidates(lines, rx))
        if best is None or len(seq) > len(best[1]): best = (scheme, seq)
    scheme, seq = best; arts = []; gaps = list(range(1, seq[0][1])) if seq and seq[0][1] > 1 else []   # leading headings lost
    for k, (i, n, tok, rest) in enumerate(seq):
        if k and n > seq[k - 1][1] + 1: gaps.extend(range(seq[k - 1][1] + 1, n))
        j = seq[k + 1][0] if k + 1 < len(seq) else len(lines)
        body = lines[i:j]
        if k + 1 == len(seq):
            for q, l in enumerate(body[1:], 1):
                if END.search(l): body = body[:q]; break
        title = rest if rest and not rest.endswith('.') else ''
        if not title and len(body) > 1 and 0 < len(body[1].strip()) <= 90 and not body[1].strip().startswith('('): title = body[1].strip()
        arts.append(dict(num=str(n) if tok.isdigit() else tok, title=title, record_type='article' if scheme == 'clanek' else 'paragraph',
                         text=re.sub(r'\n{3,}', '\n\n', '\n'.join(body)).strip()))
    return arts, dict(scheme=scheme if seq else None, gaps=gaps, amending_roman=bool(seq) and not seq[0][2].isdigit())
# ---------------- metadata / jurisdiction ----------------
FIELDS = ['Publikující', 'Datum a čas zveřejnění ve sbírce', 'Druh právního předpisu', 'Číslo právního předpisu', 'Zákonné zmocnění', 'Oblast právní úpravy',
          'Datum nabytí účinnosti', 'Datum vydání', 'Platnost', 'Verze', 'ID zprávy vyrozumění o vkladu', 'Druh aktu', 'Datum zrušení', 'Datum pozbytí platnosti']
def parse_detail(s, sppid):
    t = re.sub(r'<script.*?</script>|<style.*?</style>', '', s, flags=re.S)
    lines = [x.strip() for x in html.unescape(re.sub(r'<[^>]+>', '\n', t)).split('\n') if x.strip()]
    meta = {}
    try: meta['title'] = lines[lines.index('Notifikace') + 1]
    except ValueError: pass
    for k in FIELDS:
        if k in lines:
            j = lines.index(k); meta[k] = lines[j + 1]
    m = re.search(r'IČO:\s*(\d{8})', ' '.join(lines)); meta['ico'] = m.group(1) if m else None
    m = re.search(r'ID DS:\s*(\w+)', ' '.join(lines)); meta['id_ds'] = m.group(1) if m else None
    meta['has_text'] = f'/detail/{sppid}/text' in s
    meta['attachments'] = sorted(set(re.findall(rf'/detail/{sppid}/prilohy/(\d+)', s)), key=int)
    meta['related'] = sorted(set(re.findall(r'/detail/(SPP[A-Z0-9]+)', s)) - {sppid})
    return meta
_ICO = None
def jurisdiction(ico):
    global _ICO
    if _ICO is None: _ICO = json.load(open(f'{B}/ref/ico_map.json'))['map']
    v = _ICO.get(ico or '')
    if not v or not v.get('kraj_iso'): return 'CZ', v
    if v['pf'] == '804': return f"CZ-{v['kraj_iso']}", v                         # kraj (incl. Hlavní město Praha)
    if v['pf'] == '801': return (f"CZ-{v['kraj_iso']}-{v['obec_kod']}" if v.get('obec_kod') else f"CZ-{v['kraj_iso']}-ICO{ico}"), v   # obec / město / městys / statutární město
    if v['pf'] == '811': return f"CZ-{v['kraj_iso']}-MC{ico}", v                  # městská část / městský obvod
    return f"CZ-{v['kraj_iso']}", v                                                # state administrative body (KHS etc.)
def cz_date(s):
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', s or ''); return f'{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}' if m else None
def build_rows(sppid, meta, text, method, retrieved_at, fname=None):
    jur, reg = jurisdiction(meta.get('ico')); law_id = f'CZ-SPP-{sppid}'
    arts, info = split_articles(text)
    st = (meta.get('Platnost') or '').lower()
    pub = re.sub(r'\s*ID DS:.*$', '', meta.get('Publikující') or '').strip()
    law = dict(id=law_id, title=meta.get('title'), text=text, source_url=f'{BASE}/detail/{sppid}', source_type='municipal_legislation' if jur.count('-') == 2 else 'regional_legislation',
               jurisdiction=jur, country='Czechia', language='cs', eli=None, date=cz_date(meta.get('Datum nabytí účinnosti')),
               date_issued=cz_date(meta.get('Datum vydání')) or cz_date(meta.get('Datum a čas zveřejnění ve sbírce')), retrieved_at=retrieved_at, license=LICENSE,
               law_status='current' if st.startswith('platn') else ('repealed' if 'zruš' in st else st or None), identifier=law_id,
               official_identifier=f"{meta.get('Druh právního předpisu', '')} {pub} č. {meta.get('Číslo právního předpisu', '')}".strip(), article_count=len(arts), json_path=None,
               metadata_json=json.dumps(dict(source='SPP sbirkapp.gov.cz', spp_id=sppid, spp_metadata=meta, text_method=method, text_file=fname, split=info, publisher=reg,
                                             jurisdiction_scheme='CZ-<ISO kraj>[-<kód obce RÚIAN>]'), ensure_ascii=False))
    arows = [dict(law_id=law_id, id=f"{law_id}-{'cl' if a['record_type'] == 'article' else 'par'}-{a['num']}",
                  title=(f"Čl. {a['num']}" if a['record_type'] == 'article' else f"§ {a['num']}") + (f" {a['title']}" if a['title'] else ''),
                  text=a['text'], source_url=f'{BASE}/detail/{sppid}/text', document_number=(f"Čl. {a['num']}" if a['record_type'] == 'article' else f"§ {a['num']}"),
                  article_number=a['num'], record_type=a['record_type'], metadata_json=json.dumps(dict(law_identifier=law_id, ordinal=i + 1, text_method=method, gaps=info['gaps'])))
             for i, a in enumerate(arts)]
    return law, arows
# ---------------- network (full mode only) ----------------
class Net:
    """Legacy full-mode fetcher; same timeout policy as slot2_common.Net: connect 10 s, read 60 s, total 600 s, 2 retries with backoff,
    403/429/503 and timeouts are strikes, 3 consecutive -> stop."""
    def __init__(self):
        import requests
        self.s = requests.Session(); self.s.headers['User-Agent'] = UA; self.last = 0; self.bad = 0; self.n = 0
    def get(self, path):
        import slot2_common as _S
        url = path if path.startswith('http') else BASE + path
        assert url.startswith(BASE + '/'), 'off-host refused'
        back = 5
        for attempt in range(3):
            w = DELAY - (time.time() - self.last)
            if w > 0: time.sleep(w)
            self.last = time.time(); self.n += 1
            try: r = _S.fetch(self.s, url)
            except Exception as e:
                log('ERR', url, repr(e)[:120])
                if _S.is_timeout(e):
                    self.bad += 1
                    if self.bad >= 3: raise SystemExit('STOP 3 consecutive strikes (timeout)')
                time.sleep(back); back *= 2; continue
            if r.status_code in (403, 429, 503):
                self.bad += 1
                if self.bad >= 3: raise SystemExit(f'STOP 3 consecutive {r.status_code}')
                time.sleep(back); back *= 2; continue
            self.bad = 0
            if r.status_code >= 500 and attempt < 2: time.sleep(back); back *= 2; continue
            return r.status_code, r.content, r.headers
        return None, None, None
def enumerate_ids(net):
    """Listing pages per VÚSC (region known from the slice) + other acts. ~1,600 requests."""
    out = f'{B}/index/full_listing.jsonl'; seen = set()
    if os.path.exists(out): seen = {(json.loads(l)['vusc'], json.loads(l)['page']) for l in open(out)}
    f = open(out, 'a')
    for vusc in list(VUSC) + [None]:
        p = 1
        while True:
            if (vusc, p) in seen: p += 1; continue
            q = f'hlavni_typ=pp&kod_vusc={vusc}&page={p}' if vusc else f'hlavni_typ=oa&page={p}'
            st, body, _ = net.get(f'/vyhledavani/vysledek?{q}')
            ids = list(dict.fromkeys(re.findall(r'/detail/(SPP[A-Z0-9]+)', (body or b'').decode('utf-8', 'replace'))))
            f.write(json.dumps(dict(vusc=vusc, page=p, http=st, ids=ids)) + '\n'); f.flush()
            if not ids: break
            p += 1
def run_full():
    net = Net(); state_merge(dict(czp_status='COLLECTING_FULL', czp_pid=os.getpid()), collectors_delta=+1); end = 'DONE'; n = 0
    try:
        enumerate_ids(net)
        ids = []
        for l in open(f'{B}/index/full_listing.jsonl'):
            r = json.loads(l); ids += [(i, r['vusc']) for i in r['ids']]
        led = f'{B}/ledger_full.jsonl'; done = {json.loads(l)['id'] for l in open(led)} if os.path.exists(led) else set(); out = open(led, 'a')
        for sppid, vusc in dict(ids).items():
            if sppid in done: continue
            if STOP: end = 'TERMINATED_BY_SIGNAL'; break
            if memavail() <= MEMAVAIL_MB: end = 'MEMSHED'; break
            if rss() > RSS_MB: end = 'RSS_LIMIT'; break
            d = f'{B}/raw/{sppid[-2:]}'; os.makedirs(d, exist_ok=True)
            st, body, _ = net.get(f'/detail/{sppid}')
            rec = dict(id=sppid, vusc=vusc, detail_http=st, retrieved_at=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'))
            if st == 200:
                gzip.open(f'{d}/{sppid}.html.gz', 'wb').write(body); meta = parse_detail(body.decode('utf-8', 'replace'), sppid); rec['meta'] = meta
                if meta['has_text']:
                    st2, b2, h2 = net.get(f'/detail/{sppid}/text'); rec['text_http'] = st2
                    if st2 == 200:
                        open(f'{d}/{sppid}.bin', 'wb').write(b2); rec['filename'] = re.findall(r'filename=([^;]+)', h2.get('Content-Disposition', '') or '')[:1]
                        rec['sha256'] = hashlib.sha256(b2).hexdigest(); rec['bytes'] = len(b2)
            out.write(json.dumps(rec, ensure_ascii=False) + '\n'); out.flush(); n += 1
            if n % 100 == 0: state_merge(dict(czp_progress=n, czp_ts=time.strftime('%Y-%m-%dT%H:%M:%S%z')))
    except SystemExit as e: end = 'STOP_403_429_503'; log(e)
    finally: state_merge(dict(czp_status=f'HOLD_FULL_{end}', czp_pid=None, czp_progress=n), collectors_delta=-1)
def build(outdir):
    import pyarrow as pa, pyarrow.parquet as pq
    os.makedirs(f'{outdir}/data', exist_ok=True); laws, arts = [], []
    for l in open(f'{B}/ledger_full.jsonl'):
        r = json.loads(l)
        if r.get('text_http') != 200: continue
        p = f"{B}/raw/{r['id'][-2:]}/{r['id']}.bin"; text, method, _ = extract(p)
        a, b = build_rows(r['id'], r['meta'], text, method, r['retrieved_at'], r.get('filename')); laws.append(a); arts.extend(b)
    ls = pa.schema([(c, pa.int32() if c == 'article_count' else pa.string()) for c in LAW_COLS]); as_ = pa.schema([(c, pa.string()) for c in ART_COLS])
    pq.write_table(pa.Table.from_pylist(laws, schema=ls), f'{outdir}/data/laws.parquet'); pq.write_table(pa.Table.from_pylist(arts, schema=as_), f'{outdir}/data/articles.parquet')
    log('built', len(laws), 'laws', len(arts), 'articles')
    import pa_exit_guard; pa_exit_guard.release()  # exit guard (pa_exit_guard): Tables were temporaries; gc before returning
def selftest(limit=None):
    """Offline: probe cache (cz_sbirkapp/probe/detail_*.html + cz_sbirkapp/docs/<SPPID>) -> rows in memory + schema check; writes selftest_rows.json."""
    import pyarrow as pa
    recs = [json.loads(l) for l in open(f'{B}/index/sample.jsonl')]; laws, arts = [], []
    for r in recs[:limit]:
        s = open(f"{B}/probe/detail_{r['id']}.html", encoding='utf-8', errors='replace').read(); meta = parse_detail(s, r['id'])
        text, method, pages = extract(f"{B}/docs/{r['id']}")
        a, b = build_rows(r['id'], meta, text, method, '2026-10-04T23:50:00Z', r.get('filename')); laws.append(a); arts.extend(b)
        print(r['id'], a['jurisdiction'], method, len(text), 'articles', a['article_count'], json.loads(a['metadata_json'])['split']['scheme'], json.loads(a['metadata_json'])['split']['gaps'])
    ls = pa.schema([(c, pa.int32() if c == 'article_count' else pa.string()) for c in LAW_COLS]); as_ = pa.schema([(c, pa.string()) for c in ART_COLS])
    pa.Table.from_pylist(laws, schema=ls); pa.Table.from_pylist(arts, schema=as_)
    json.dump(dict(laws=[{k: (v[:300] if isinstance(v, str) else v) for k, v in l.items()} for l in laws], articles_n=len(arts)), open(f'{B}/selftest_rows.json', 'w'), ensure_ascii=False, indent=1)
    print('SELFTEST OK', len(laws), 'laws', len(arts), 'article rows; schema matches NL hub (19 / 9 cols)')
if __name__ == '__main__' and not (len(sys.argv) > 1 and sys.argv[1] in ('t1', 't1build', 'quality', 't2', 't2pack', 'guard_dryrun', 'extract')):
    a = sys.argv[1:]
    if not a: print(__doc__); sys.exit(1)
    if a[0] == 'selftest': selftest()
    elif a[0] == 'full':
        tok = a[a.index('--cos-go') + 1] if '--cos-go' in a else None; gf = f'{B}/COS_GO_FULL'
        sys.exit('REFUSED: legacy `full` (slot-2 MemAvail<=3700 TERM) is superseded; use `t2` (strict guard, STOP_CZ/PAUSE_CZ, persisted shards)')
    elif a[0] == 'build': import pa_exit_guard; pa_exit_guard.run_guarded(build, a[1])  # exit guard (pa_exit_guard): real exit code via os._exit
    else: print(__doc__); sys.exit(1)

# =====================================================================================================================
# CZ T1 DRIVER (CoS GO 2026-10-04 17:06 PT CZ T1 Karlovarský+Liberecký only). Index-only (attachments listed, never downloaded); text-only storage
# (original deleted after extraction/OCR; source URL + sha256 + filename kept in metadata). Verze: the detail page is the newest version of the act;
# for Verze>1 the /detail/<id>/verze page is fetched and the superseded versions are recorded. Junk filter from listing rows (counted by reason).
#   python3 cz_sbirkapp_collect.py t1 --cos-go TOKEN        (network + OCR, then automatic offline build/review = t1build)
#   python3 cz_sbirkapp_collect.py t1build [--ts TS]        (offline only)
# =====================================================================================================================
sys.path.insert(0, '/workspace/scripts')
import slot2_common as S2
T1 = f'{B}/t1'; T1_VUSC = {'51': ('CZ-41', 'Karlovarský kraj'), '78': ('CZ-51', 'Liberecký kraj')}
KEEP_DRUH = ('Obecně závazná vyhláška', 'Nařízení')
_CURS = {}
def _now(): return time.strftime('%Y-%m-%dT%H:%M:%S%z')
def _utc(): return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def _eta(rem): return time.strftime('%Y-%m-%d %H:%M %Z', time.localtime(time.time() + rem))
def _go_ok_t1(tok):
    gf = f'{B}/COS_GO_T1'
    return bool(tok) and os.path.exists(gf) and open(gf).readline().strip() == tok
def _rows(s):
    out = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S):
        m = re.search(r'/detail/(SPP[A-Z0-9]+)', row)
        if not m: continue
        cells = [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', c))).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
        out.append(dict(id=m.group(1), cells=cells))
    return out
def _total(s):
    m = re.search(r'Počet podání:\s*(?:<[^>]+>\s*)*([\d\s]+)', s); return int(re.sub(r'\s', '', m.group(1))) if m else None
def drop_reason(cells):
    if len(cells) != 7: return 'malformed_listing_row'
    druh = cells[2]; plat = cells[6]
    if 'VYŘAZEN' in druh.upper() or 'VYŘAZEN' in plat.upper(): return 'vyrazeno_removed_entry'
    if druh not in KEEP_DRUH: return f'other_untyped:{druh or "(empty)"}'
    return None
def t1_listing(net):
    os.makedirs(T1, exist_ok=True); lp = f'{T1}/listing.jsonl'; done = {}
    if os.path.exists(lp):
        for l in open(lp):
            r = json.loads(l); done[(r['vusc'], r['page'])] = r
    out = open(lp, 'a'); totals = {}
    for vusc in T1_VUSC:
        p = 1
        while True:
            if S2.STOP.is_set(): raise S2.Stopped()
            if (vusc, p) in done:
                r = done[(vusc, p)]; totals.setdefault(vusc, r.get('total'))
                if not r['rows']: break
                p += 1; continue
            st, body, _ = net.get(f'/vyhledavani/vysledek?hlavni_typ=pp&kod_vusc={vusc}&page={p}')
            s = (body or b'').decode('utf-8', 'replace'); rows = _rows(s) if st == 200 else []; tot = _total(s) if st == 200 else None
            if st != 200: log('listing HTTP', st, vusc, p)
            out.write(json.dumps(dict(vusc=vusc, page=p, http=st, total=tot, rows=rows, ts=_utc()), ensure_ascii=False) + '\n'); out.flush()
            totals.setdefault(vusc, tot)
            if p % 10 == 0: log(f'listing vusc {vusc} page {p} rows {len(rows)} total {tot}')
            if not rows: break
            p += 1
    return totals
def t1_targets():
    seen = {}; drops = {}; order = []
    for l in open(f'{T1}/listing.jsonl'):
        r = json.loads(l)
        for row in r['rows']:
            if row['id'] in seen: drops['duplicate_listing_row_same_id'] = drops.get('duplicate_listing_row_same_id', 0) + 1; continue
            seen[row['id']] = r['vusc']; why = drop_reason(row['cells'])
            if why:
                drops[why] = drops.get(why, 0) + 1
                open(f'{T1}/dropped.jsonl', 'a').write(json.dumps(dict(id=row['id'], vusc=r['vusc'], reason=why, cells=row['cells']), ensure_ascii=False) + '\n')
            else: order.append((row['id'], r['vusc'], row['cells']))
    return order, drops
def _parse_versions(s, sppid):
    """/detail/<id>/verze -> list of superseded versions (version no., dates, text file name/link) as rows of the version table."""
    out = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S):
        cells = [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', c))).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
        links = re.findall(r'href="([^"]+)"', row)
        if cells: out.append(dict(cells=cells, links=links))
    return out
HEAVY = threading.Condition(); _HV = dict(ocr=0, q=0, qwait=0)   # quality child (~250 MB spylls) never overlaps OCR children (tree cap 300 MB)
def heavy_ocr_enter():
    with HEAVY:
        while _HV['q'] or _HV['qwait']: HEAVY.wait(1)
        _HV['ocr'] += 1
def heavy_ocr_exit():
    with HEAVY: _HV['ocr'] -= 1; HEAVY.notify_all()
def t1_quality(path):
    """dict check in a short-lived subprocess (cs_CZ dictionary costs ~250 MB; keeps the driver under RSS 300 MB).
    Exclusive vs OCR page children: waits for in-flight pages (new pages wait), so the tree never holds quality + tesseract together."""
    with HEAVY:
        _HV['qwait'] += 1
        try:
            while _HV['q'] or _HV['ocr']: HEAVY.wait(1)
        finally: _HV['qwait'] -= 1
        _HV['q'] += 1
    try: return _t1_quality_run(path)
    finally:
        with HEAVY: _HV['q'] -= 1; HEAVY.notify_all()
def _t1_quality_run(path):
    r = subprocess.run([sys.executable, '/workspace/scripts/cz_sbirkapp_collect.py', 'quality', path], capture_output=True, text=True, timeout=600)
    try: return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception: return dict(error=r.stderr[-300:])
def t1_extract(tmp, sppid):
    """-> (method, info); writes t1/text/<id>.txt.gz; PDFs needing OCR are moved to t1/ocrq/<id>.pdf."""
    kind = sniff(tmp); info = dict(kind=kind)
    if kind == 'pdf':
        n = pdf_pages(tmp); info['pages'] = n
        t = subprocess.run(['pdftotext', tmp, '-'], capture_output=True, text=True, timeout=900).stdout
        tf = f'{T1}/work/{sppid}.layer.txt'; open(tf, 'w').write(t); q = t1_quality(tf); os.remove(tf); info['layer_quality'] = q
        cpp = len(re.sub(r'\s', '', t)) / max(n, 1)
        if n > 1000: method = 'pdf_skipped_over_1000_pages'
        elif cpp >= 200 and q.get('dict_ratio', 0) >= 0.80: method = 'pdf_text_layer'
        else: method = 'pdf_ocr_pending'
        with gzip.open(f'{T1}/text/{sppid}.txt.gz', 'wt') as f: f.write(t)
        if method == 'pdf_ocr_pending': os.replace(tmp, f'{T1}/ocrq/{sppid}.pdf')
        return method, info
    if kind == 'odt': t, method = _odt_text(tmp), 'odt_xml'
    elif kind == 'docx': t, method = _docx_text(tmp), 'docx_xml'
    elif kind in ('doc', 'rtf'): t, method = _soffice_text(tmp), f'{kind}_soffice'
    else: t, method = '', f'unsupported_{kind}'
    with gzip.open(f'{T1}/text/{sppid}.txt.gz', 'wt') as f: f.write(t)
    info['chars'] = len(re.sub(r'\s', '', t)); return method, info
def t1_fetch(net, order, ocr):
    curf = f'{T1}/cursor.json'; led = f'{T1}/docs.jsonl'
    cur = json.load(open(curf)) if os.path.exists(curf) else dict(next_idx=0, done=0); _CURS['t1'] = (curf, cur)
    done_ids = set()
    if os.path.exists(led):
        for l in open(led): done_ids.add(json.loads(l)['id'])
    out = open(led, 'a'); t0 = time.time(); n0 = cur['done']; total = len(order); req0 = net.n
    for idx, (sppid, vusc, cells) in enumerate(order):
        if idx < cur['next_idx']: continue
        if S2.STOP.is_set(): raise S2.Stopped()
        if sppid in done_ids: cur['next_idx'] = idx + 1; continue
        while S2.dir_gb(f'{T1}/ocrq') > 8.0:
            if S2.STOP.is_set(): raise S2.Stopped()
            S2.state_merge('czp_', dict(czp_status='T1_PAUSED_OCR_BACKLOG', czp_ts=_now())); time.sleep(60)
        rec = dict(id=sppid, vusc=vusc, kraj_iso=T1_VUSC[vusc][0], listing_cells=cells, source_url=f'{BASE}/detail/{sppid}', retrieved_at=_utc())
        st, body, _ = net.get(f'/detail/{sppid}'); rec['detail_http'] = st
        if st == 200:
            sdet = body.decode('utf-8', 'replace'); d = f'{T1}/raw/{sppid[-2:]}'; os.makedirs(d, exist_ok=True)
            gzip.open(f'{d}/{sppid}.html.gz', 'wb').write(body); meta = parse_detail(sdet, sppid)
            m = re.search(rf'href="/detail/{sppid}/text">([^<]+)</a>', sdet); meta['text_filename'] = html.unescape(m.group(1)).strip() if m else None
            meta['attachment_names'] = {a: html.unescape(n).strip() for a, n in re.findall(rf'href="/detail/{sppid}/prilohy/(\d+)">([^<]+)</a>', sdet)}
            rec['meta'] = meta
            try: ver = int(re.sub(r'\D', '', meta.get('Verze') or '1') or 1)
            except ValueError: ver = 1
            rec['verze'] = ver
            if ver > 1 and f'/detail/{sppid}/verze' in sdet:
                st3, b3, _ = net.get(f'/detail/{sppid}/verze'); rec['verze_http'] = st3
                if st3 == 200:
                    gzip.open(f'{d}/{sppid}.verze.html.gz', 'wb').write(b3); rec['superseded_versions'] = _parse_versions(b3.decode('utf-8', 'replace'), sppid)
            if meta['has_text']:
                st2, b2, h2 = net.get(f'/detail/{sppid}/text'); rec['text_http'] = st2; rec['text_source_url'] = f'{BASE}/detail/{sppid}/text'
                if st2 == 200 and b2:
                    tmp = f'{T1}/work/{sppid}.bin'; open(tmp, 'wb').write(b2)
                    cd = (h2 or {}).get('Content-Disposition', '') or ''; fm = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
                    rec.update(text_bytes=len(b2), text_sha256=hashlib.sha256(b2).hexdigest(), text_ctype=(h2 or {}).get('Content-Type'),
                               text_filename=urllib.parse.unquote(fm.group(1)) if fm else meta.get('text_filename')); b2 = None
                    try: method, info = t1_extract(tmp, sppid)
                    except Exception as e: method, info = 'extract_error', dict(error=repr(e)[:200])
                    rec['text_method'] = method; rec['extract'] = info
                    if os.path.exists(tmp): os.remove(tmp)
        out.write(json.dumps(rec, ensure_ascii=False) + '\n'); out.flush(); cur['next_idx'] = idx + 1; cur['done'] += 1
        if cur['done'] % 10 == 0: json.dump(cur, open(curf + '.tmp', 'w')); os.replace(curf + '.tmp', curf)
        if cur['done'] % 50 == 0:
            el = time.time() - t0; rate = (cur['done'] - n0) / max(el, 1); rem = (total - cur['done']) / max(rate, 1e-6)
            log(f"T1 {cur['done']}/{total} rate {rate:.3f} docs/s {(net.n - req0) / max(el, 1):.3f} req/s codes {net.codes} ocrq {S2.dir_gb(f'{T1}/ocrq'):.2f}GB ocr_done {ocr.done_n} rss {S2.rss_mb()}MB mem {S2.memavail()}MB eta {_eta(rem)}")
            S2.state_merge('czp_', dict(czp_status='T1_FETCH_LIVE', czp_t1_done=cur['done'], czp_t1_total=total, czp_t1_rate_docs_s=round(rate, 3), czp_t1_fetch_eta_pt=_eta(rem),
                                        czp_t1_ocr_done=ocr.done_n, czp_t1_ocr_queue_gb=round(S2.dir_gb(f'{T1}/ocrq'), 3), czp_http_codes={str(k): v for k, v in net.codes.items()}, czp_ts=_now()))
    cur['complete'] = True; json.dump(cur, open(curf + '.tmp', 'w')); os.replace(curf + '.tmp', curf)
def t1_drive(argv):
    tok = argv[argv.index('--cos-go') + 1] if '--cos-go' in argv else None
    if not _go_ok_t1(tok): sys.exit('REFUSED: t1 needs the CoS GO token (cz_sbirkapp/COS_GO_T1)')
    if S2.memavail() < S2.MEM_PAUSE: sys.exit(f'REFUSED: MemAvailable {S2.memavail()} MB < 4500 at launch')
    S2.install_signals()
    for d in ('', '/text', '/ocrq', '/ocr', '/work', '/raw'): os.makedirs(T1 + d, exist_ok=True)
    guard = StrictGuard(); threading.Thread(target=guard.watcher, daemon=True).start()   # T2 patch: strict NL-M guard replaces slot-2 TERM<=3700
    net = S2.Net(BASE, UA, guard, delay=DELAY)
    S2.state_merge('czp_', dict(czp_status='T1_LISTING', czp_pid=os.getpid(), czp_log=os.environ.get('CZP_LOG'), czp_t1_scope='CZ-41 Karlovarský (VÚSC 51) + CZ-51 Liberecký (VÚSC 78)',
                                czp_started_pt=time.strftime('%Y-%m-%d %H:%M %Z'), czp_ts=_now()), collectors_delta=+1)
    end = 'UNKNOWN'; ocr = S2.OCRWorker(f'{T1}/ocrq', f'{T1}/ocr', 'ces', guard, workers=2); ocr.start()
    try:
        totals = t1_listing(net); order, drops = t1_targets()
        json.dump(dict(listing_totals=totals, listed=len(order) + sum(drops.values()), kept=len(order), drops=drops, ts=_now()), open(f'{T1}/targets_summary.json', 'w'), indent=1, ensure_ascii=False)
        log('T1 targets', len(order), 'drops', drops, 'listing totals', totals)
        S2.state_merge('czp_', dict(czp_status='T1_FETCH_LIVE', czp_t1_listing_totals=totals, czp_t1_total=len(order), czp_t1_drops=drops, czp_ts=_now()))
        t1_fetch(net, order, ocr)
        log('T1 fetch complete; draining OCR'); ocr.finish.set()
        while ocr.is_alive() and (ocr.pending() or not ocr.idle.is_set()):
            if S2.STOP.is_set(): raise S2.Stopped()
            S2.state_merge('czp_', dict(czp_status='T1_OCR_DRAIN', czp_t1_ocr_done=ocr.done_n, czp_t1_ocr_pending=len(ocr.pending()), czp_ts=_now())); time.sleep(30)
        if ocr.pending(): raise RuntimeError(f'OCR worker ended with {len(ocr.pending())} pending: {ocr.err}')
        end = 'T1_NETWORK_OCR_DONE'
    except S2.HostBlocked as e: end = 'T1_STOP_3x403_429_503'; log(e)
    except S2.MemShed as e: end = 'T1_MEMSHED'; log(e)
    except S2.Stopped: end = 'T1_STOPPED_BY_SIGNAL'
    except Exception as e:
        import traceback; traceback.print_exc(); end = f'T1_ERROR_{type(e).__name__}'
    finally:
        S2.STOP.set()
        for k, (cf, c) in _CURS.items(): json.dump(c, open(cf + '.tmp', 'w')); os.replace(cf + '.tmp', cf)
        S2.state_merge('czp_', dict(czp_status=end, czp_pid=None, czp_requests_t1_run=net.n, czp_http_codes={str(k): v for k, v in net.codes.items()},
                                    czp_t1_ocr_done=ocr.done_n, czp_t1_ocr_pages=ocr.pages, czp_t1_ocr_cpu_wall_s=round(ocr.secs), czp_exit_pt=time.strftime('%Y-%m-%d %H:%M %Z'), czp_ts=_now()), collectors_delta=-1)
        log('T1 NETWORK/OCR EXIT', end, 'requests', net.n, net.codes)
    if end == 'T1_NETWORK_OCR_DONE':   # offline build in a fresh process (RSS isolation); no network
        blog = (os.environ.get('CZP_LOG') or f'/workspace/logs/cz_t1_{time.strftime("%Y%m%dT%H%M%S")}.log').replace('.log', '_build.log')
        bp = subprocess.Popen(['nice', '-n', '10', sys.executable, '-u', '/workspace/scripts/cz_sbirkapp_collect.py', 't1build'], stdout=open(blog, 'a'), stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, start_new_session=True)
        S2.state_merge('czp_', dict(czp_status='T1_BUILD_RUNNING', czp_build_pid=bp.pid, czp_build_log=blog, czp_ts=_now()))
        log('t1build launched detached pid', bp.pid, 'log', blog)
    sys.exit(0 if end == 'T1_NETWORK_OCR_DONE' else 2)
def _pubdt(meta):
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?', meta.get('Datum a čas zveřejnění ve sbírce') or '')
    return (int(m.group(3)), int(m.group(2)), int(m.group(1)), int(m.group(4) or 0), int(m.group(5) or 0)) if m else (0,)
def _own_max(text, scheme):
    rx = H_CL if scheme == 'clanek' else H_PAR; best = 0
    for i, n, tok, rest in _candidates(text.split('\n'), rx):
        if n <= 200 and tok.isdigit(): best = max(best, n)
    return best
def t1build(argv):
    import pyarrow as pa, pyarrow.parquet as pq, random, collections
    ts = argv[argv.index('--ts') + 1] if '--ts' in argv else time.strftime('%Y%m%dT%H%M%S')
    outdir = f"{os.environ.get('CZT1_OUT_ROOT', '{_CORPORA}/hf-staging')}/ipfs_czech_municipal_laws_tranche1_{ts}"; os.makedirs(f'{outdir}/data', exist_ok=True)
    S2.state_merge('czp_', dict(czp_status='T1_BUILD_RUNNING', czp_t1_stage=outdir, czp_ts=_now()))
    recs = {}
    for l in open(f'{T1}/docs.jsonl'):
        r = json.loads(l); recs[r['id']] = dict(i=len(recs), ico=(r.get('meta') or {}).get('ico'), druh=(r.get('meta') or {}).get('Druh právního předpisu') or r['listing_cells'][2],
                                                 cislo=((r.get('meta') or {}).get('Číslo právního předpisu') or r['listing_cells'][1] or '').strip(), pub=_pubdt(r.get('meta') or {}), http=r.get('detail_http'))
    tsum = json.load(open(f'{T1}/targets_summary.json'))
    drops = dict(tsum['drops']); groups = collections.defaultdict(list)
    for k, v in recs.items():
        if v['http'] != 200: drops['detail_not_200'] = drops.get('detail_not_200', 0) + 1; continue
        if v['ico'] and v['cislo']: groups[(v['ico'], v['druh'], v['cislo'])].append(k)
        else: groups[('_single', k)].append(k)
    keep = {}; superseded_entries = {}
    for g, ids in groups.items():
        ids = sorted(ids, key=lambda k: recs[k]['pub']); win = ids[-1]; keep[win] = True
        if len(ids) > 1:
            superseded_entries[win] = ids[:-1]; drops['duplicate_act_entry_same_ico_druh_cislo'] = drops.get('duplicate_act_entry_same_ico_druh_cislo', 0) + len(ids) - 1
    ls = pa.schema([(c, pa.int32() if c == 'article_count' else pa.string()) for c in LAW_COLS]); as_ = pa.schema([(c, pa.string()) for c in ART_COLS])
    lw = pq.ParquetWriter(f'{outdir}/data/laws.parquet', ls, compression='zstd'); aw = pq.ParquetWriter(f'{outdir}/data/articles.parquet', as_, compression='zstd')
    lb, ab = [], []; law_ids = set(); art_ids = set(); art_law_counts = collections.Counter(); law_counts = {}; dup_art_fixed = 0
    st = dict(kraj=collections.defaultdict(lambda: collections.Counter()), muni=collections.defaultdict(lambda: collections.Counter()), method=collections.Counter(),
              scheme=collections.Counter(), zero_art_with_text=0, with_gaps=0, arts=[], ocr_pages=0, pages_total=0, status=collections.Counter(), verze=collections.Counter(),
              superseded_versions_recorded=0, attachments_indexed=0)
    muni_name = {}; spot_pool = []
    def flush():
        if lb: lw.write_table(pa.Table.from_pylist(lb, schema=ls)); lb.clear()
        if ab: aw.write_table(pa.Table.from_pylist(ab, schema=as_)); ab.clear()
    seen = set()
    for l in open(f'{T1}/docs.jsonl'):
        r = json.loads(l)
        if r['id'] in seen or r['id'] not in keep: continue
        seen.add(r['id']); sppid = r['id']; meta = r.get('meta') or {}
        method = r.get('text_method') or ('no_text_link' if not meta.get('has_text') else f"text_http_{r.get('text_http')}")
        text = ''
        if os.path.exists(f'{T1}/ocr/{sppid}.txt'):
            text = open(f'{T1}/ocr/{sppid}.txt', encoding='utf-8', errors='replace').read(); method = 'pdf_ocr_tesseract_ces'
            st['ocr_pages'] += json.load(open(f'{T1}/ocr/{sppid}.json')).get('pages', 0)
        elif os.path.exists(f'{T1}/text/{sppid}.txt.gz') and method not in ('pdf_skipped_over_1000_pages',):
            text = gzip.open(f'{T1}/text/{sppid}.txt.gz', 'rt', encoding='utf-8', errors='replace').read()
        st['pages_total'] += (r.get('extract') or {}).get('pages') or 0
        law, arows = build_rows(sppid, meta, text, method, r['retrieved_at'], r.get('text_filename'))
        md = json.loads(law['metadata_json'])
        md.update(text_source_url=r.get('text_source_url'), text_original=dict(filename=r.get('text_filename'), sha256=r.get('text_sha256'), bytes=r.get('text_bytes'),
                  content_type=r.get('text_ctype'), retained=False), verze=r.get('verze'), superseded_versions=r.get('superseded_versions', []),
                  superseded_entries=[f'CZ-SPP-{x}' for x in superseded_entries.get(sppid, [])], listing_cells=r.get('listing_cells'), kraj_iso=r.get('kraj_iso'),
                  attachments_index=[dict(id=a, name=(meta.get('attachment_names') or {}).get(a), url=f'{BASE}/detail/{sppid}/prilohy/{a}') for a in meta.get('attachments', [])],
                  extract=r.get('extract'))
        law['metadata_json'] = json.dumps(md, ensure_ascii=False)
        fixed = []
        for a in arows:
            if a['id'] in art_ids:
                k = 2
                while f"{a['id']}-{k}" in art_ids: k += 1
                a['id'] = f"{a['id']}-{k}"; dup_art_fixed += 1
            art_ids.add(a['id']); art_law_counts[law['id']] += 1; fixed.append(a)
        law_ids.add(law['id']); law_counts[law['id']] = law['article_count']; lb.append(law); ab.extend(fixed)
        kraj = r.get('kraj_iso'); jur = law['jurisdiction']
        st['kraj'][kraj]['laws'] += 1; st['kraj'][kraj]['articles'] += len(fixed); st['kraj'][kraj]['with_text'] += bool(text.strip())
        st['kraj'][kraj]['ocr'] += method.startswith('pdf_ocr'); st['kraj'][kraj][f"druh:{meta.get('Druh právního předpisu')}"] += 1
        st['muni'][jur]['laws'] += 1; st['muni'][jur]['articles'] += len(fixed); muni_name[jur] = re.sub(r'\s*IČO:.*$', '', (r.get('listing_cells') or [''])[0]).strip()
        st['method'][method] += 1; st['status'][law['law_status'] or 'unknown'] += 1; st['verze'][str(r.get('verze'))] += 1
        st['superseded_versions_recorded'] += len(r.get('superseded_versions', [])); st['attachments_indexed'] += len(meta.get('attachments', []))
        if text.strip():
            st['scheme'][md['split']['scheme']] += 1; st['arts'].append(len(fixed))
            if not fixed and len(re.sub(r'\s', '', text)) > 1500: st['zero_art_with_text'] += 1
            if md['split']['gaps']: st['with_gaps'] += 1
            spot_pool.append(sppid)
        if len(lb) >= 200: flush()
    flush(); lw.close(); aw.close(); del lw, aw  # exit guard (pa_exit_guard): writers closed first, then dropped
    # ---- validation (re-read from parquet) ----
    L = pq.read_table(f'{outdir}/data/laws.parquet', columns=['id', 'article_count']).to_pylist(); A = pq.read_table(f'{outdir}/data/articles.parquet', columns=['law_id', 'id']).to_pylist()
    lid = [x['id'] for x in L]; aid = [x['id'] for x in A]; lset = set(lid); ac = collections.Counter(x['law_id'] for x in A)
    val = dict(laws=len(L), articles=len(A), duplicate_law_ids=len(lid) - len(lset), duplicate_article_ids=len(aid) - len(set(aid)),
               orphan_articles=sum(1 for x in A if x['law_id'] not in lset), article_count_mismatches=sum(1 for x in L if (x['article_count'] or 0) != ac.get(x['id'], 0)),
               duplicate_article_ids_suffixed_in_build=dup_art_fixed)
    val['ok'] = val['duplicate_law_ids'] == 0 and val['duplicate_article_ids'] == 0 and val['orphan_articles'] == 0 and val['article_count_mismatches'] == 0
    # ---- 20-doc spot check ----
    random.seed(20261004); spot = random.sample(sorted(spot_pool), min(20, len(spot_pool))); checks = []
    want = set(spot)
    for l in open(f'{T1}/docs.jsonl'):
        r = json.loads(l)
        if r['id'] not in want: continue
        want.discard(r['id']); sppid = r['id']
        p = f'{T1}/ocr/{sppid}.txt' if os.path.exists(f'{T1}/ocr/{sppid}.txt') else None
        text = open(p, encoding='utf-8', errors='replace').read() if p else gzip.open(f'{T1}/text/{sppid}.txt.gz', 'rt', encoding='utf-8', errors='replace').read()
        tf = f'{T1}/work/spot_{sppid}.txt'; open(tf, 'w').write(text); q = t1_quality(tf); os.remove(tf)
        arts, info = split_articles(text); own = _own_max(text, info['scheme']) if info['scheme'] else 0
        chars = len(re.sub(r'\s', '', text)); dr = q.get('dict_ratio', 0)
        flags = []
        if chars < 300: flags.append('too_short')
        if dr < 0.6: flags.append('dict<0.60')
        elif dr < 0.85: flags.append('dict<0.85')
        if not arts and chars > 1500: flags.append('no_articles')
        if info['gaps']: flags.append(f"gaps:{info['gaps'][:5]}")
        if own and arts and own > len(arts) + len(info['gaps']): flags.append(f'own_max {own} > split {len(arts)}')
        verdict = 'fail' if ('too_short' in flags or 'dict<0.60' in flags) else ('warn' if flags else 'pass')
        checks.append(dict(id=f'CZ-SPP-{sppid}', publisher=(r.get('listing_cells') or [''])[0], druh=(r.get('meta') or {}).get('Druh právního předpisu'), cislo=(r.get('meta') or {}).get('Číslo právního předpisu'),
                           method='pdf_ocr_tesseract_ces' if p else r.get('text_method'), chars=chars, dict_ratio=dr, garbage_ratio=q.get('garbage_ratio'), scheme=info['scheme'],
                           articles=len(arts), own_max_heading=own, gaps=info['gaps'], verdict=verdict, flags=flags, source_url=f'{BASE}/detail/{sppid}'))
    arts_n = st['arts']; n_text = len(arts_n)
    def med(x): x = sorted(x); return x[len(x) // 2] if x else 0
    ocr_docs = sum(v for k, v in st['method'].items() if k.startswith('pdf_ocr'))
    rep = dict(ts=ts, scope='CZ T1: CZ-41 Karlovarský kraj (VÚSC 51) + CZ-51 Liberecký kraj (VÚSC 78); CoS GO 2026-10-04 17:06 PT', staging_dir=outdir, published=False,
               hub_target='endomorphosis/ipfs_czech_municipal_laws (publish NOTHING without CoS)', validation=val,
               listing=dict(totals_reported=tsum.get('listing_totals'), listed_rows=tsum.get('listed'), kept_after_filter=tsum.get('kept')),
               drop_tallies=drops, dedupe=dict(rule='per SPP id the detail page is the newest Verze (superseded versions recorded from /verze); entries with identical (IČO, druh, číslo) -> newest zveřejnění kept, others recorded as superseded_entries',
                                               verze_distribution=dict(st['verze']), superseded_versions_recorded=st['superseded_versions_recorded'], duplicate_entries_dropped=drops.get('duplicate_act_entry_same_ico_druh_cislo', 0)),
               per_kraj={k: dict(v) for k, v in st['kraj'].items()}, per_municipality={k: dict(name=muni_name.get(k), **dict(v)) for k, v in sorted(st['muni'].items())},
               n_municipalities=len(st['muni']), text_methods=dict(st['method']), law_status=dict(st['status']),
               ocr=dict(docs=ocr_docs, share_of_docs_with_text=round(ocr_docs / max(n_text, 1), 4), pages_ocr=st['ocr_pages'], pdf_pages_total=st['pages_total']),
               article_split=dict(docs_with_text=n_text, schemes=dict(st['scheme']), articles_total=sum(arts_n), mean=round(sum(arts_n) / max(n_text, 1), 2), median=med(arts_n),
                                  zero_articles_docs_over_1500_chars=st['zero_art_with_text'], docs_with_gaps=st['with_gaps']),
               attachments_indexed_not_downloaded=st['attachments_indexed'],
               spot_check=dict(n=len(checks), verdicts=dict(collections.Counter(c['verdict'] for c in checks)), docs=checks))
    RD = os.environ.get('CZT1_REVIEW_DIR', '/workspace/country-law-triage'); os.makedirs(RD, exist_ok=True); rj = f'{RD}/cz_t1_review_{ts}.json'
    json.dump(rep, open(rj, 'w'), indent=1, ensure_ascii=False)
    md = [f'# CZ T1 review ({ts}) — Karlovarský (CZ-41) + Liberecký (CZ-51)', '', f'Staging: `{outdir}` (NOT published). Hub target: endomorphosis/ipfs_czech_municipal_laws.', '',
          f"## Validation: {'PASS' if val['ok'] else 'FAIL'}", '', '\n'.join(f'- {k}: {v}' for k, v in val.items()), '',
          '## Listing, filter and dedupe tallies', '', f"- listing totals reported (Počet podání): {tsum.get('listing_totals')}; rows listed {tsum.get('listed')}; kept after junk filter {tsum.get('kept')}",
          '\n'.join(f'- dropped {k}: {v}' for k, v in sorted(drops.items())), f"- Verze distribution: {dict(st['verze'])}; superseded versions recorded in metadata: {st['superseded_versions_recorded']}", '',
          '## Per kraj', '', '| kraj | laws | with text | OCR | articles | druh |', '|---|---|---|---|---|---|']
    for k, v in sorted(st['kraj'].items(), key=lambda x: str(x[0])):
        md.append(f"| {k} | {v['laws']} | {v['with_text']} | {v['ocr']} | {v['articles']} | " + ', '.join(f"{a[5:]} {b}" for a, b in v.items() if a.startswith('druh:')) + ' |')
    md += ['', f"## Per municipality ({len(st['muni'])} jurisdictions; top 40 by laws, full list in JSON)", '', '| jurisdiction | publisher | laws | articles |', '|---|---|---|---|']
    for k, v in sorted(st['muni'].items(), key=lambda x: -x[1]['laws'])[:40]: md.append(f"| {k} | {muni_name.get(k)} | {v['laws']} | {v['articles']} |")
    md += ['', '## Text methods / OCR', '', '\n'.join(f'- {k}: {v}' for k, v in st['method'].most_common()), f"- OCR share of docs with text: {rep['ocr']['share_of_docs_with_text']:.1%} ({ocr_docs} docs, {st['ocr_pages']} pages)", '',
           '## Article split', '', '\n'.join(f'- {k}: {v}' for k, v in rep['article_split'].items()), '',
           f"## 20-doc spot check: {rep['spot_check']['verdicts']}", '', '| id | publisher | druh č. | method | chars | dict | scheme | arts | own max | verdict | flags |', '|---|---|---|---|---|---|---|---|---|---|---|']
    for c in checks: md.append(f"| {c['id']} | {c['publisher'][:40]} | {c['druh']} {c['cislo']} | {c['method']} | {c['chars']} | {c['dict_ratio']} | {c['scheme']} | {c['articles']} | {c['own_max_heading']} | {c['verdict']} | {'; '.join(c['flags'])} |")
    open(rj.replace('.json', '.md'), 'w').write('\n'.join(md) + '\n')
    card = f"""---\nlicense: other\nlanguage: [cs]\npretty_name: Czech municipal and regional legal acts (SPP) - tranche 1\n---\n# ipfs_czech_municipal_laws - tranche 1 (staging, unpublished)\n\nKarlovarský (CZ-41) and Liberecký (CZ-51) kraje: obecně závazné vyhlášky and nařízení from the Sbírka právních předpisů územních samosprávných celků (https://sbirkapp.gov.cz), text only.\n\n{LICENSE}\n\nFiles: data/laws.parquet ({val['laws']} rows, NL hub law schema), data/articles.parquet ({val['articles']} rows, one per článek/§). Jurisdiction: CZ-<ISO 3166-2 kraj>[-<RÚIAN kód obce>]. Built {ts}.\n"""
    open(f'{outdir}/README.md', 'w').write(card); json.dump(dict(validation=val, review=rj, built=ts), open(f'{outdir}/manifest.json', 'w'), indent=1)
    S2.state_merge('czp_', dict(czp_status='T1_STAGED_AWAIT_REVIEW' if val['ok'] else 'T1_STAGED_VALIDATION_FAIL', czp_build_pid=None, czp_t1_stage=outdir, czp_t1_review=rj,
                                czp_t1_laws=val['laws'], czp_t1_articles=val['articles'], czp_ts=_now()))
    log('T1 BUILD DONE', val, rj)
    import pa_exit_guard; pa_exit_guard.release()  # exit guard (pa_exit_guard): read_table results were temporaries; gc before returning
if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] in ('t1', 't1build', 'quality'):
    if sys.argv[1] == 't1': t1_drive(sys.argv[2:])
    elif sys.argv[1] == 't1build': import pa_exit_guard; pa_exit_guard.run_guarded(t1build, sys.argv[2:])  # exit guard (pa_exit_guard)
    else: print(json.dumps(text_quality(open(sys.argv[2], encoding='utf-8', errors='replace').read())))

# =====================================================================================================================
# CZ T2 DRIVER (CoS contingent GO 2026-10-06 00:50 PT: remaining 12 kraje, launch only after Box Health Watchdog GO).
#   Launch (one command):  /workspace/scripts/cz_t2_launch.sh          (wraps: CZP_LOG=<log> setsid nohup python -u cz_sbirkapp_collect.py t2 --cos-go TOKEN)
#   Smoke (scratch, no PIN): python cz_sbirkapp_collect.py t2 --smoke --root /workspace/tmp/cz_t2_smoke --max-requests 10 --max-docs 3 --max-listing-pages 1
#   Offline pack/flush:     python cz_sbirkapp_collect.py t2pack [--final] [--root DIR]
#   Guard dry run:          python cz_sbirkapp_collect.py guard_dryrun
# Same request pattern/rate as T1: S2.Net (>=2.0 s between request starts, connect 10 s / read 60 s / total 600 s, 2 retries 5 s/10 s,
#   403/429/503+timeouts = strikes, 3 consecutive -> stop); per kraj: listing pages (50 rows), then per act /detail, /detail/<id>/verze if Verze>1,
#   /detail/<id>/text; attachments index-only; junk filter = T1 drop_reason; OCR (tesseract ces, 2 workers nice 19) in the background.
# STRICT MEMORY GUARD (ported from nl_municipal_collect.py; replaces slot-2 TERM<=3700 / PAUSE<4500 for CZ):
#   MemAvail < pause_memavail (3584) -> MEMPAUSE (main thread between requests; OCR threads wait too); MEMRESUME only after >= resume_memavail (4200)
#   continuously for resume_hold_s (30 s); MEMTERM (clean exit, checkpoint) if < hard_term_memavail (3000) for >= hard_term_sustain_s (5 s; watcher polls
#   every 2 s; any reading >= 3000 resets MEMLOW_STREAK), any reading < instant_term_memavail (2500), mem-paused > max_pause_s (900 s), or RSS > 300 MB.
#   Config live-reload every 60 s from cz_sbirkapp/czp_config.json (code floors: delay>=2.0, pause>=3300, resume>=3800, hold>=10, hard>=3000, instant>=2500).
# EXTERNAL CONTROL (Watchdog; CZ sheds first):
#   touch cz_sbirkapp/STOP_CZ  -> 'STOPFILE': in-flight request finishes (or is abandoned after 60 s), cursor checkpointed, clean exit (status T2_STOPPED_BY_STOPFILE).
#                                 The file is NOT removed by the collector; the launcher refuses while it exists (rm it to allow a relaunch).
#   touch cz_sbirkapp/PAUSE_CZ -> 'FILEPAUSE': pause (network + OCR) until the file is removed ('FILERESUME'); no 900 s limit while the file exists;
#                                 if MemAvail < pause on removal it continues as a normal MEMPAUSE.
# PERSISTENCE (box sync ignores out/ build/ dist/ venv/ target/ __pycache__/ .cache/ at any depth): everything durable is under cz_sbirkapp/t2/
#   listing/<ISO>.jsonl, docs/<ISO>.jsonl (ledger), raw/<xx>/<id>.html.gz (+.verze.html.gz), text/<xx>/<id>.txt.gz, ocr/<id>.txt|.json,
#   index/laws_shards/t2_<ISO>_<nnnn>.jsonl.gz (+ manifest.json: sha256, counts, ids per shard), cursor.json, plan.json; review packages in cz_sbirkapp/review/.
#   Transient only: t2/.cache/ocrq (PDFs awaiting OCR; refetched automatically if lost) and t2/.cache/work. T1 data (cz_sbirkapp/t1/) is never written.
# =====================================================================================================================
T2_ORDER_DEFAULT = [('19', 'CZ-10', 'Hlavní město Praha', 1484), ('141', 'CZ-72', 'Zlínský kraj', 3705), ('60', 'CZ-42', 'Ústecký kraj', 3867),
                    ('132', 'CZ-80', 'Moravskoslezský kraj', 4653), ('94', 'CZ-53', 'Pardubický kraj', 4696), ('86', 'CZ-52', 'Královéhradecký kraj', 4781),
                    ('124', 'CZ-71', 'Olomoucký kraj', 5428), ('108', 'CZ-63', 'Kraj Vysočina', 6016), ('43', 'CZ-32', 'Plzeňský kraj', 6021),
                    ('35', 'CZ-31', 'Jihočeský kraj', 6612), ('116', 'CZ-64', 'Jihomoravský kraj', 9351), ('27', 'CZ-20', 'Středočeský kraj', 14007)]
# counts = probe 2026-10-04 by_kraj (typed OZV+nařízení podání); order = smallest first. T1 kraje (VÚSC 51 Karlovarský, 78 Liberecký) are excluded.
CZCFG = f'{B}/czp_config.json'; STOP_CZ = f'{B}/STOP_CZ'; PAUSE_CZ = f'{B}/PAUSE_CZ'; SHARD_N = 1000; REVIEW_EVERY = 20000
_GCFG = dict(delay_s=2.0, rss_limit_mb=300, pause_memavail=3584, resume_memavail=4200, resume_hold_s=30, hard_term_memavail=1500, hard_term_sustain_s=10.0,
             hard_term_poll_s=2.0, instant_term_memavail=1000, max_pause_s=900, ocr_workers=2, ocrq_max_gb=2.0,
             rss_tree_grace_s=45, rss_stepup_below_mb=200, rss_stepup_hold_s=600,
             ocr_dpi=200, ocr_dpi_large=150, ocr_child_rss_mb=170, ocr_child_as_mb=1536)   # CoS 02:58 PT: OCR memory (page-by-page, 200 dpi, per-child ceiling)   # CoS 01:32 PT: 300 MB cap = whole process tree, step down OCR first
def _load_gcfg(quiet=True):
    try: c = json.load(open(CZCFG))
    except Exception: c = {}
    g = dict(_GCFG); g.update({k: c[k] for k in _GCFG if k in c})
    g['delay_s'] = max(2.0, float(g['delay_s'])); g['rss_limit_mb'] = min(300, int(g['rss_limit_mb']))
    g['pause_memavail'] = max(3300, int(g['pause_memavail'])); g['resume_memavail'] = max(3800, g['pause_memavail'] + 1, int(g['resume_memavail']))
    g['resume_hold_s'] = max(10, int(g['resume_hold_s'])); g['hard_term_memavail'] = min(g['pause_memavail'] - 1, max(1200, int(g['hard_term_memavail'])))
    g['hard_term_sustain_s'] = max(1.0, min(10.0, float(g['hard_term_sustain_s']))); g['hard_term_poll_s'] = max(0.5, min(2.0, float(g['hard_term_poll_s'])))
    g['instant_term_memavail'] = min(g['hard_term_memavail'] - 1, max(900, int(g['instant_term_memavail']))); g['max_pause_s'] = max(60, min(900, int(g['max_pause_s'])))
    g['ocr_workers'] = max(0, min(2, int(g['ocr_workers']))); g['ocrq_max_gb'] = max(0.2, min(8.0, float(g['ocrq_max_gb'])))
    g['rss_tree_grace_s'] = max(30, min(60, int(g['rss_tree_grace_s']))); g['rss_stepup_below_mb'] = max(50, min(200, int(g['rss_stepup_below_mb'])))
    g['rss_stepup_hold_s'] = max(600, int(g['rss_stepup_hold_s']))
    g['ocr_dpi'] = 300 if int(g['ocr_dpi']) >= 300 else (150 if int(g['ocr_dpi']) <= 150 else 200); g['ocr_dpi_large'] = max(100, min(g['ocr_dpi'], int(g['ocr_dpi_large'])))
    g['ocr_child_rss_mb'] = max(100, min(220, int(g['ocr_child_rss_mb']))); g['ocr_child_as_mb'] = max(768, min(4096, int(g['ocr_child_as_mb'])))
    return g
def _proc_rss_mb(pid):
    try:
        for l in open(f'/proc/{pid}/status'):
            if l.startswith('VmRSS'): return int(l.split()[1]) / 1024
    except Exception: pass
    return 0.0
_TREE_CACHE = [0.0, 0]
def tree_rss_mb(root=None):
    """RSS of this process + all descendants (OCR tesseract/pdftoppm, quality/spylls, soffice, pdftotext, review), cached 1 s"""
    if root is None and time.time() - _TREE_CACHE[0] < 1.0: return _TREE_CACHE[1]
    r = root or os.getpid(); kids = {}
    for d in os.listdir('/proc'):
        if d.isdigit():
            try: kids.setdefault(int(open(f'/proc/{d}/stat').read().rsplit(')', 1)[1].split()[1]), []).append(int(d))
            except Exception: pass
    tot = 0.0; st = [r]; seen = set()
    while st:
        p = st.pop()
        if p in seen: continue
        seen.add(p); tot += _proc_rss_mb(p); st += kids.get(p, [])
    if root is None: _TREE_CACHE[0] = time.time(); _TREE_CACHE[1] = int(tot)
    return int(tot)
def _ts(): return time.strftime('%Y-%m-%d %H:%M:%S')
def glog(*a): print(_ts(), *a, flush=True)
def _children(pid):
    kids = []
    for d in os.listdir('/proc'):
        if not d.isdigit(): continue
        try:
            st = open(f'/proc/{d}/stat').read(); ppid = int(st[st.rfind(')') + 2:].split()[1])
            if ppid == pid: kids.append(int(d))
        except Exception: pass
    out = []
    for k in kids: out += _children(k) + [k]
    return out
def kill_children():
    for k in _children(os.getpid()):
        try: os.kill(k, signal.SIGKILL)
        except Exception: pass
class StrictGuard:
    """Drop-in for S2.Guard (check(who) raises S2.MemShed / S2.Stopped). who='net' = main thread (logs MEMPAUSE/MEMRESUME); who='ocr' = OCR threads
    (wait silently while the main thread is paused / memory is low / PAUSE_CZ exists)."""
    def __init__(self, stop_file=STOP_CZ, pause_file=PAUSE_CZ, checkpoint=None):
        self.c = _load_gcfg(); self.stop_file = stop_file; self.pause_file = pause_file; self.checkpoint = checkpoint; self.lock = threading.Lock()
        self.G = dict(min_mem=10 ** 9, min_fetch=10 ** 9, min_paused=10 ** 9, n_pause=0, n_resume=0, n_filepause=0, pause_s_total=0.0, low_t0=None, low_n=0,
                      n_streaks=0, hard=None, hard_t=None, stopfile_t=None, termlogged=False)
        self.paused = False; self.net = None; self._rss_warned = False
        self.ocr_eff = 2; self.T = dict(over_t0=None, under_t0=None, n_stepdown=0, n_stepup=0, max_tree=0, last_tree=0); self.tlock = threading.Lock()
    def ocr_limit(self):
        """live OCR page concurrency: min(czp_config ocr_workers (live-reloaded), tree-RSS step-down level)"""
        return min(self.c['ocr_workers'], self.ocr_eff)
    def _tree(self, now, tree_fn=None):
        """CoS 01:32 PT: tree RSS > limit -> step OCR down to 1 worker (in-flight pages finish); TERM only if still over with 1 worker for rss_tree_grace_s"""
        c = self.c; t = (tree_fn or tree_rss_mb)(); lim = c['rss_limit_mb']
        with self.tlock:
            self.T['last_tree'] = t; self.T['max_tree'] = max(self.T['max_tree'], t)
            if t > lim:
                self.T['under_t0'] = None
                if self.ocr_limit() > 1:
                    self.ocr_eff = 1; self.T['n_stepdown'] += 1; self.T['over_t0'] = now
                    glog(f"RSS_STEPDOWN ocr_workers=1 tree_mb={t} limit_mb={lim} grace_s={c['rss_tree_grace_s']} (in-flight OCR pages finish; TERM only if still over with 1 worker)")
                    return None
                if self.T['over_t0'] is None:
                    self.T['over_t0'] = now; glog(f"RSS_TREE_OVER tree_mb={t} limit_mb={lim} ocr_workers={self.ocr_limit()} grace_s={c['rss_tree_grace_s']}")
                dur = now - self.T['over_t0']
                if dur >= c['rss_tree_grace_s']: return f"rss_tree tree_mb={t}>{lim}MB with ocr_workers={self.ocr_limit()} for {dur:.0f}s"
                return None
            if self.T['over_t0'] is not None: glog(f"RSS_TREE_OK tree_mb={t} after {now - self.T['over_t0']:.0f}s over (no TERM)"); self.T['over_t0'] = None
            if t < c['rss_stepup_below_mb'] and self.ocr_eff < 2:
                self.T['under_t0'] = self.T['under_t0'] or now
                if now - self.T['under_t0'] >= c['rss_stepup_hold_s']:
                    self.ocr_eff = 2; self.T['n_stepup'] += 1; self.T['under_t0'] = None
                    glog(f"RSS_STEPUP ocr_workers={self.ocr_limit()} tree_mb={t} (under {c['rss_stepup_below_mb']} MB for {c['rss_stepup_hold_s']}s)")
            elif t >= c['rss_stepup_below_mb']: self.T['under_t0'] = None
            return None
    def reload(self):
        new = _load_gcfg()
        if new != self.c: self.c = new; glog('CONFIG reloaded', new)
        if self.net is not None: self.net.delay = self.c['delay_s']
    def _low_streak(self, m, now):
        c = self.c
        with self.lock:
            if m < c['instant_term_memavail']: return f"lt{c['instant_term_memavail']} memavail={m}"
            if m >= c['hard_term_memavail']:
                if self.G['low_t0'] is not None: glog(f"MEMLOW_STREAK reset memavail={m} n={self.G['low_n']} dur_s={now - self.G['low_t0']:.1f} (no TERM)")
                self.G['low_t0'] = None; self.G['low_n'] = 0; return None
            if self.G['low_t0'] is None: self.G['low_t0'] = now; self.G['n_streaks'] += 1
            self.G['low_n'] += 1; dur = now - self.G['low_t0']
            glog(f"MEMLOW_STREAK memavail={m} n={self.G['low_n']} dur_s={dur:.1f} sustain_s={c['hard_term_sustain_s']:g}")
            if dur >= c['hard_term_sustain_s']: return f"sustained_lt{c['hard_term_memavail']} dur_s={dur:.1f} n={self.G['low_n']} memavail={m}"
            return None
    def _hard(self, m, now, rss_fn=None, tree_fn=None):
        self.G['min_mem'] = min(self.G['min_mem'], m); k = 'min_paused' if self.paused else 'min_fetch'; self.G[k] = min(self.G[k], m)
        why = self._low_streak(m, now)
        if why: return why
        r = (rss_fn or S2.rss_mb)()
        if r > self.c['rss_limit_mb']: return f"rss_self={r}MB>{self.c['rss_limit_mb']}MB"   # the collector process alone: immediate (OCR step-down cannot help)
        why = self._tree(now, tree_fn)
        if why: return why
        if self.T['last_tree'] > 0.8 * self.c['rss_limit_mb'] and not self._rss_warned: self._rss_warned = True; glog(f"RSS WARN tree_mb={self.T['last_tree']} (80% of limit)")
        return None
    def _term(self, m, why):
        if not self.G['termlogged']:
            self.G['termlogged'] = True
            glog(f"MEMTERM reason={why} memavail_now={m} min_memavail={self.G['min_mem']} pauses={self.G['n_pause']} resumes={self.G['n_resume']} ts={_now()}")
        raise S2.MemShed(why)
    def _stopcheck(self):
        if S2.STOP.is_set(): raise S2.Stopped()
        if os.path.exists(self.stop_file):
            if self.G['stopfile_t'] is None: self.G['stopfile_t'] = time.time(); glog(f'STOPFILE {self.stop_file} present -> clean exit')
            S2.STOP.set(); raise S2.Stopped()
    def check(self, who='net', _sleep=time.sleep, _mem=None, _clock=time.time, _rss=None, _tree=None):
        mem = _mem or S2.memavail
        self._stopcheck()
        m = mem(); now = _clock(); why = self._hard(m, now, _rss, _tree) or self.G['hard']
        if why: self._term(m, why)
        pf = os.path.exists(self.pause_file)
        if who != 'net':   # OCR thread: no logging, no hold logic of its own
            while self.paused or pf or m < self.c['pause_memavail']:
                _sleep(2); self._stopcheck(); m = mem(); pf = os.path.exists(self.pause_file)
                why = self._hard(m, _clock(), _rss, _tree) or self.G['hard']
                if why: self._term(m, why)
            return m
        if m >= self.c['pause_memavail'] and not pf: return m
        t0 = _clock(); self.paused = True; mode = 'file' if pf else 'mem'; mem_t0 = None if pf else t0; ok_since = None; last_log = t0
        if pf: self.G['n_filepause'] += 1; glog(f'FILEPAUSE {self.pause_file} present memavail={m} ts={_now()}')
        else: self.G['n_pause'] += 1; glog(f"MEMPAUSE memavail={m} pause_below={self.c['pause_memavail']} resume_at={self.c['resume_memavail']}x{self.c['resume_hold_s']}s ts={_now()} n={self.G['n_pause']}")
        try:
            while True:
                for _ in range(int(POLL_CZ if ok_since is None else 5)):
                    _sleep(1)
                    if self.G['hard'] or S2.STOP.is_set() or os.path.exists(self.stop_file): break
                self._stopcheck()
                m = mem(); now = _clock(); why = self._hard(m, now, _rss, _tree) or self.G['hard']
                if why: self._term(m, why)
                pf = os.path.exists(self.pause_file)
                if pf:
                    if mode != 'file': glog(f'FILEPAUSE {self.pause_file} appeared during MEMPAUSE memavail={m}')
                    mode = 'file'; mem_t0 = None; ok_since = None
                elif mode == 'file':
                    if m >= self.c['pause_memavail']: break
                    mode = 'mem'; mem_t0 = now; ok_since = None; self.G['n_pause'] += 1; glog(f'MEMPAUSE memavail={m} (after PAUSE_CZ removed) n={self.G["n_pause"]}')
                if mode == 'mem':
                    if now - mem_t0 > self.c['max_pause_s']: self._term(m, f"paused>{self.c['max_pause_s']}s (paused_s={now - mem_t0:.0f})")
                    if m >= self.c['resume_memavail']:
                        ok_since = ok_since or now
                        if now - ok_since >= self.c['resume_hold_s']: break
                    else: ok_since = None
                if now - last_log >= 60: last_log = now; glog(f"{'FILEPAUSE' if mode == 'file' else 'MEMPAUSE'} waiting memavail={m} paused_s={now - t0:.0f}")
        finally:
            self.paused = False
        ps = _clock() - t0; self.G['pause_s_total'] += ps
        if mode == 'file': glog(f'FILERESUME memavail={m} paused_s={ps:.0f} ts={_now()}')
        else: self.G['n_resume'] += 1; glog(f"MEMRESUME memavail={m} paused_s={ps:.0f} ts={_now()} n={self.G['n_resume']}")
        if self.net is not None:
            try: self.net.s.close()
            except Exception: pass
        return m
    def watch_tick(self, m, now, rss_fn=None, tree_fn=None):
        why = self._hard(m, now, rss_fn, tree_fn)
        if why and not self.G['hard']: self.G['hard'] = why; self.G['hard_t'] = now; glog(f'MEMGUARD hard condition flagged: {why}')
        return self.G['hard']
    def watcher(self):
        """daemon thread: 2 s polls feed the debounced streak; flags hard conditions for the main thread; STOP_CZ -> sets STOP; force exit
        (checkpoint + kill children) if the main thread has not exited 30 s after a hard flag / 60 s after STOP_CZ."""
        t_cfg = t_stat = time.time()
        while True:
            try:
                now = time.time(); m = S2.memavail(); self.watch_tick(m, now)
                if os.path.exists(self.stop_file):
                    if self.G['stopfile_t'] is None: self.G['stopfile_t'] = now; glog(f'STOPFILE {self.stop_file} present -> clean exit (watcher)')
                    S2.STOP.set()
                _hm = str(self.G['hard'] or ''); late = (self.G['hard'] and ((now - self.G['hard_t'] > 120 and m < 1500) if (_hm.startswith('sustained') or _hm.startswith('lt')) else now - self.G['hard_t'] > 30)) or (self.G['stopfile_t'] and now - self.G['stopfile_t'] > 60)
                if late:
                    why = self.G['hard'] or 'STOPFILE'
                    glog(f'MEMTERM reason={why} (watcher force exit: main thread did not reach a gate in time) memavail={m}')
                    try:
                        if self.checkpoint: self.checkpoint()
                    except Exception as e: glog('checkpoint failed', repr(e))
                    try: _t2_pin_end('T2_STOPPED_BY_STOPFILE' if why == 'STOPFILE' else 'T2_MEMSHED', why)
                    except Exception: pass
                    kill_children(); os._exit(4 if why == 'STOPFILE' else 3)
                if now - t_cfg >= 60: t_cfg = now; self.reload()
                if now - t_stat >= 300:
                    t_stat = now
                    glog(f"MEMSTAT memavail={m} min_memavail={self.G['min_mem']} min_fetch={self.G['min_fetch']} min_paused={self.G['min_paused']} rss={S2.rss_mb()} tree_mb={self.T['last_tree']} max_tree_mb={self.T['max_tree']} ocr_workers={self.ocr_limit()} stepdowns={self.T['n_stepdown']} stepups={self.T['n_stepup']} "
                         f"pauses={self.G['n_pause']} resumes={self.G['n_resume']} filepauses={self.G['n_filepause']} paused_total_s={self.G['pause_s_total']:.0f} low_streaks={self.G['n_streaks']}")
            except Exception as e: glog('memwatch error', repr(e)[:200])
            time.sleep(self.c['hard_term_poll_s'])
POLL_CZ = 10
def _png_dims(f):
    try:
        h = open(f, 'rb').read(24); return int.from_bytes(h[16:20], 'big'), int.from_bytes(h[20:24], 'big')
    except Exception: return 0, 0
def run_capped(cmd, rss_mb, as_mb, timeout=600):
    """child under prlimit --as (hard backstop) + RSS watchdog (kill at rss_mb); -> (rc, peak_mb, why). why in (None, 'rss_cap', 'timeout')"""
    env = dict(os.environ, OMP_THREAD_LIMIT='1')
    p = subprocess.Popen(['prlimit', f'--as={as_mb * 1048576}', '--', 'nice', '-n', '19'] + cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    t0 = time.time(); peak = 0; why = None
    while p.poll() is None:
        r = _proc_rss_mb(p.pid); peak = max(peak, r)
        if r > rss_mb: why = 'rss_cap'; p.kill(); break
        if time.time() - t0 > timeout: why = 'timeout'; p.kill(); break
        time.sleep(0.1)
    rc = p.wait(); return rc, peak, why
_OCRSTAT = dict(pages=0, peak_child_mb=0, rss_cap=0, retry150=0, failed=0)
def cz_ocr_page(pdf, pg, d, lang, c):
    """one page: pdftoppm -f N -l N (gray PNG, 200 dpi; ocr_dpi_large for oversized pages; long side capped) -> tesseract (OMP 1) -> delete image.
    Each child memory-capped; on failure retry once at 150 dpi; then page = '' and ocr_failed. -> (text, info)"""
    info = dict(page=pg)
    try:
        m = re.search(r'size:\s+([\d.]+) x ([\d.]+)', subprocess.run(['pdfinfo', '-f', str(pg), '-l', str(pg), pdf], capture_output=True, text=True, timeout=60).stdout)
        long_pt = max(float(m.group(1)), float(m.group(2))) if m else 842.0
    except Exception: long_pt = 842.0
    big = long_pt > 1191   # larger than A3
    tries = [c['ocr_dpi_large'] if big else c['ocr_dpi'], 150]
    for attempt, dpi in enumerate(tries):
        if attempt and tries[0] <= 150: break
        px = int(min(long_pt / 72.0 * dpi, {300: 3508, 200: 2339}.get(dpi, 1754) * (1.0 if not big else 1.25)))
        base = f'{d}/r{pg}_{dpi}'
        for f in os.listdir(d):
            if f.startswith(f'r{pg}_'): os.remove(os.path.join(d, f))
        rc, pk1, why = run_capped(['pdftoppm', '-f', str(pg), '-l', str(pg), '-r', str(dpi), '-scale-to', str(px), '-gray', '-png', pdf, base], c['ocr_child_rss_mb'], c['ocr_child_as_mb'])
        ims = [f for f in os.listdir(d) if f.startswith(f'r{pg}_{dpi}')]
        t = ''; pk2 = 0
        if not why and ims:
            rc2, pk2, why = run_capped(['tesseract', os.path.join(d, ims[0]), f'{base}_out', '-l', lang], c['ocr_child_rss_mb'], c['ocr_child_as_mb'])
            try: t = open(f'{base}_out.txt', encoding='utf-8', errors='replace').read()
            except OSError: t = ''
            if not why and rc2 != 0 and not t.strip(): why = f'tesseract_rc{rc2}'
        elif not why: why = f'pdftoppm_rc{rc}'
        for f in os.listdir(d):
            if f.startswith(f'r{pg}_'): os.remove(os.path.join(d, f))
        _OCRSTAT['peak_child_mb'] = max(_OCRSTAT['peak_child_mb'], pk1, pk2)
        info.update(dpi=dpi, px=px, peak_mb=max(pk1, pk2))
        if not why: break
        if why == 'rss_cap': _OCRSTAT['rss_cap'] += 1
        info.setdefault('fails', []).append(f'{dpi}:{why}'); glog(f'OCR page fail {os.path.basename(pdf)} p{pg} dpi {dpi} {why} peak {max(pk1, pk2)}MB' + ('; retry 150dpi' if attempt == 0 and tries[0] > 150 else ''))
        if attempt == 0 and tries[0] > 150: _OCRSTAT['retry150'] += 1
    else: why = why
    if why:
        info['ocr_failed'] = True; _OCRSTAT['failed'] += 1; return '', info
    if len(re.sub(r'\s', '', t)) < 80:   # phone-scanner PDFs with oversized page boxes: native embedded image, only if small enough for the child ceiling
        rc, pk, w2 = run_capped(['pdfimages', '-f', str(pg), '-l', str(pg), '-png', pdf, f'{d}/n{pg}'], c['ocr_child_rss_mb'], c['ocr_child_as_mb'])
        nat = sorted((os.path.join(d, f) for f in os.listdir(d) if f.startswith(f'n{pg}-')), key=os.path.getsize)
        if nat and max(_png_dims(nat[-1])) <= 2600:
            rc, pk, w2 = run_capped(['tesseract', nat[-1], f'{d}/n{pg}_out', '-l', lang], c['ocr_child_rss_mb'], c['ocr_child_as_mb'])
            try: t2 = open(f'{d}/n{pg}_out.txt', encoding='utf-8', errors='replace').read()
            except OSError: t2 = ''
            if len(t2.strip()) > len(t.strip()): t = t2; info['native'] = True
        elif nat: info['native_skipped_px'] = max(_png_dims(nat[-1]))
        for f in os.listdir(d):
            if f.startswith(f'n{pg}'): os.remove(os.path.join(d, f))
    _OCRSTAT['pages'] += 1
    return t, info
class CZOCRWorker(S2.OCRWorker):
    """S2.OCRWorker (unchanged in slot2_common) with live page concurrency = guard.ocr_limit(): pool of 2 threads, a page starts only while
    active pages < limit, so a step-down lets in-flight pages finish and takes effect at the next page (no mid-doc kill). limit 0 = OCR paused."""
    def __init__(self, *a, limit_fn=None, **k):
        super().__init__(*a, **k); self.limit_fn = limit_fn or (lambda: self.workers); self.cv = threading.Condition(); self.active = 0
    def _acq(self):
        with self.cv:
            while self.active >= self.limit_fn():
                if S2.STOP.is_set(): raise S2.Stopped()
                self.cv.wait(1)
            self.active += 1
    def _rel(self):
        with self.cv: self.active -= 1; self.cv.notify_all()
    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        try:
            while not S2.STOP.is_set():
                fs = self.pending()
                if not fs:
                    self.idle.set()
                    if self.finish.is_set(): return
                    time.sleep(5); continue
                self.idle.clear(); f = fs[0]; key = f[:-4]; pdf = os.path.join(self.q, f); n = S2.pdf_pages(pdf); t0 = time.time()
                d = tempfile.mkdtemp(prefix='czocr_', dir='/workspace/tmp'); texts = [None] * n; infos = [None] * n
                def one(pg):
                    self.guard.check('ocr'); self._acq()
                    try:
                        heavy_ocr_enter()
                        try: return cz_ocr_page(pdf, pg, d, self.lang, self.guard.c)
                        finally: heavy_ocr_exit()
                    finally: self._rel()
                try:
                    with ThreadPoolExecutor(2) as ex:
                        for i, (t, inf) in enumerate(ex.map(one, range(1, n + 1))): texts[i] = t; infos[i] = inf
                finally: subprocess.run(['rm', '-rf', d])
                failed = [x['page'] for x in infos if x.get('ocr_failed')]
                open(os.path.join(self.o, key + '.txt.tmp'), 'w').write('\n\f'.join(texts)); os.replace(os.path.join(self.o, key + '.txt.tmp'), os.path.join(self.o, key + '.txt'))
                json.dump(dict(pages=n, secs=round(time.time() - t0, 1), dpi=sorted({x.get('dpi') for x in infos if x.get('dpi')}), ocr_failed_pages=failed,
                               retried_150=[x['page'] for x in infos if x.get('fails') and not x.get('ocr_failed')], peak_child_mb=max([x.get('peak_mb', 0) for x in infos] or [0])),
                          open(os.path.join(self.o, key + '.json'), 'w'))
                if failed: glog(f'OCR doc {key} pages {n} ocr_failed pages {failed} (run continues)')
                if not self.keep: os.remove(pdf)
                self.done_n += 1; self.pages += n; self.secs += time.time() - t0
        except (S2.MemShed, S2.Stopped) as e: self.err = repr(e)
        except Exception as e: self.err = repr(e); glog('OCR worker error', repr(e))
# ---------------- T2 paths / helpers ----------------
def t2_paths(root):
    return dict(root=root, listing=f'{root}/listing', docs=f'{root}/docs', raw=f'{root}/raw', text=f'{root}/text', ocr=f'{root}/ocr', shards=f'{root}/index/laws_shards',
                ocrq=f'{root}/.cache/ocrq', work=f'{root}/.cache/work', cursor=f'{root}/cursor.json', plan=f'{root}/plan.json', review=f'{os.path.dirname(root)}/review')
def _atomic_json(p, obj):
    t = p + '.tmp'
    with open(t, 'w') as f: json.dump(obj, f, indent=1, ensure_ascii=False); f.flush(); os.fsync(f.fileno())
    os.replace(t, p)
def _atomic_gz_text(p, text):
    t = p + '.tmp'
    with gzip.open(t, 'wt', encoding='utf-8') as f: f.write(text)
    os.replace(t, p)
def _read_jsonl(p):
    out = []
    if not os.path.exists(p): return out
    for l in open(p, encoding='utf-8'):
        try: out.append(json.loads(l))
        except Exception: pass   # tolerate a torn last line after a forced exit (the act is redone from the cursor)
    return out
def _iter_jsonl(p):
    if not os.path.exists(p): return
    with open(p, encoding='utf-8') as f:
        for l in f:
            try: yield json.loads(l)
            except Exception: pass
def _ids_jsonl(p): return {r['id'] for r in _iter_jsonl(p)}
_T2 = {}
def _t2_pin(**u):
    if _T2.get('no_pin'): return
    S2.state_merge('czp_', dict(u, czp_ts=_now()))
def _t2_pin_end(status, why):
    if _T2.get('no_pin') or _T2.get('pin_ended'): return
    _T2['pin_ended'] = True
    S2.state_merge('czp_', dict(czp_status=status, czp_pid=None, czp_t2_end_reason=str(why)[:200], czp_exit_pt=time.strftime('%Y-%m-%d %H:%M %Z'), czp_ts=_now()),
                   collectors_delta=-1 if _T2.get('bumped') else 0)
def t2_listing(net, P, vusc, iso, max_pages=None):
    lp = f"{P['listing']}/{iso}.jsonl"; done = {r['page']: dict(total=r.get('total'), rows=bool(r['rows']), nrows=len(r['rows'])) for r in _iter_jsonl(lp)}; total = None; p = 1
    with open(lp, 'a', encoding='utf-8') as out:
        while True:
            if S2.STOP.is_set(): raise S2.Stopped()
            if p in done:
                total = total or done[p].get('total')
                if not done[p]['rows']: break
                p += 1; continue
            if max_pages and p > max_pages: break
            st, body, _ = net.get(f'/vyhledavani/vysledek?hlavni_typ=pp&kod_vusc={vusc}&page={p}')
            s = (body or b'').decode('utf-8', 'replace'); rows = _rows(s) if st == 200 else []; tot = _total(s) if st == 200 else None
            if st == 404:   # SPP answers 404 for the page after the last one: end only if earlier pages already cover the reported total / last page was short
                seen = sum(len(r['rows']) for r in _iter_jsonl(lp)); prev = done.get(p - 1) or {}
                prev_short = p > 1 and (prev.get('nrows', 50) < 50)
                if (total and seen >= total) or prev_short:
                    out.write(json.dumps(dict(vusc=vusc, iso=iso, page=p, http=404, total=total, rows=[], end='http404_after_last_page', ts=_utc()), ensure_ascii=False) + '\n')
                    out.flush(); os.fsync(out.fileno()); glog(f'T2 listing {iso} end at page {p} (HTTP 404 after last page; rows seen {seen}, total {total})'); break
            if st != 200:   # not recorded -> the page is re-requested on the next run (never mistaken for the end of the listing)
                glog('listing HTTP', st, iso, p); raise RuntimeError(f'listing page {iso} p{p} HTTP {st} after retries')
            out.write(json.dumps(dict(vusc=vusc, iso=iso, page=p, http=st, total=tot, rows=rows, ts=_utc()), ensure_ascii=False) + '\n'); out.flush(); os.fsync(out.fileno())
            total = total or tot; done[p] = dict(total=tot, rows=bool(rows), nrows=len(rows))
            if p % 10 == 0 or p == 1: glog(f'T2 listing {iso} page {p} rows {len(rows)} total {tot}')
            if not rows: break
            p += 1
    return total
def t2_targets(P, iso, exclude):
    seen = set(); drops = {}; order = []
    for r in _iter_jsonl(f"{P['listing']}/{iso}.jsonl"):
        for row in r['rows']:
            if row['id'] in seen: drops['duplicate_listing_row_same_id'] = drops.get('duplicate_listing_row_same_id', 0) + 1; continue
            seen.add(row['id'])
            if row['id'] in exclude: drops['already_in_t1_or_other_kraj'] = drops.get('already_in_t1_or_other_kraj', 0) + 1; continue
            why = drop_reason(row['cells'])
            if why: drops[why] = drops.get(why, 0) + 1
            else: order.append((row['id'], row['cells']))
    return order, drops
def t2_extract(P, tmp, sppid, guard):
    """T1 extraction policy; text -> text/<xx>/<id>.txt.gz (atomic); PDFs needing OCR -> .cache/ocrq/<id>.pdf"""
    kind = sniff(tmp); info = dict(kind=kind); td = f"{P['text']}/{sppid[-2:]}"; os.makedirs(td, exist_ok=True)
    if kind == 'pdf':
        n = pdf_pages(tmp); info['pages'] = n
        t = subprocess.run(['pdftotext', tmp, '-'], capture_output=True, text=True, timeout=900).stdout
        guard.check('net')   # the dictionary check spawns a ~210 MB subprocess: only while memory is OK
        tf = f"{P['work']}/{sppid}.layer.txt"; open(tf, 'w').write(t); q = t1_quality(tf); os.remove(tf); info['layer_quality'] = q
        cpp = len(re.sub(r'\s', '', t)) / max(n, 1)
        if n > 1000: method = 'pdf_skipped_over_1000_pages'
        elif cpp >= 200 and q.get('dict_ratio', 0) >= 0.80: method = 'pdf_text_layer'
        else: method = 'pdf_ocr_pending'
        _atomic_gz_text(f'{td}/{sppid}.txt.gz', t)
        if method == 'pdf_ocr_pending': os.replace(tmp, f"{P['ocrq']}/{sppid}.pdf")
        return method, info
    if kind in ('odt', 'docx'): guard.check('net'); t, method = _sub_extract(kind, tmp), f'{kind}_xml'   # child process: a big document.xml can need ~300 MB
    elif kind in ('doc', 'rtf'): t, method = _soffice_text(tmp), f'{kind}_soffice'
    else: t, method = '', f'unsupported_{kind}'
    _atomic_gz_text(f'{td}/{sppid}.txt.gz', t); info['chars'] = len(re.sub(r'\s', '', t)); return method, info
def _sub_extract(kind, path):
    """same _odt_text/_docx_text, run in a short-lived child so the collector's own RSS stays small (CoS 01:32 PT tree cap; child counts in the tree)"""
    out = path + '.txt'
    r = subprocess.run([sys.executable, '/workspace/scripts/cz_sbirkapp_collect.py', 'extract', kind, path, out], capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not os.path.exists(out): raise RuntimeError(f'extract child rc={r.returncode} {r.stderr[-200:]}')
    t = open(out, encoding='utf-8').read(); os.remove(out); return t
def _trim():
    try:
        import ctypes; ctypes.CDLL('libc.so.6').malloc_trim(0)
    except Exception: pass
def t2_fetch_one(net, P, guard, sppid, vusc, iso, cells):
    rec = dict(id=sppid, vusc=vusc, kraj_iso=iso, tranche='T2', listing_cells=cells, source_url=f'{BASE}/detail/{sppid}', retrieved_at=_utc())
    st, body, _ = net.get(f'/detail/{sppid}'); rec['detail_http'] = st
    if st != 200: return rec
    sdet = body.decode('utf-8', 'replace'); d = f"{P['raw']}/{sppid[-2:]}"; os.makedirs(d, exist_ok=True)
    with open(f'{d}/{sppid}.html.gz.tmp', 'wb') as f: f.write(gzip.compress(body))
    os.replace(f'{d}/{sppid}.html.gz.tmp', f'{d}/{sppid}.html.gz'); meta = parse_detail(sdet, sppid)
    m = re.search(rf'href="/detail/{sppid}/text">([^<]+)</a>', sdet); meta['text_filename'] = html.unescape(m.group(1)).strip() if m else None
    meta['attachment_names'] = {a: html.unescape(n).strip() for a, n in re.findall(rf'href="/detail/{sppid}/prilohy/(\d+)">([^<]+)</a>', sdet)}
    rec['meta'] = meta
    try: ver = int(re.sub(r'\D', '', meta.get('Verze') or '1') or 1)
    except ValueError: ver = 1
    rec['verze'] = ver
    if ver > 1 and f'/detail/{sppid}/verze' in sdet:
        st3, b3, _ = net.get(f'/detail/{sppid}/verze'); rec['verze_http'] = st3
        if st3 == 200:
            with open(f'{d}/{sppid}.verze.html.gz.tmp', 'wb') as f: f.write(gzip.compress(b3))
            os.replace(f'{d}/{sppid}.verze.html.gz.tmp', f'{d}/{sppid}.verze.html.gz'); rec['superseded_versions'] = _parse_versions(b3.decode('utf-8', 'replace'), sppid)
    if meta['has_text']:
        st2, b2, h2 = net.get(f'/detail/{sppid}/text'); rec['text_http'] = st2; rec['text_source_url'] = f'{BASE}/detail/{sppid}/text'
        if st2 == 200 and b2:
            tmp = f"{P['work']}/{sppid}.bin"; open(tmp, 'wb').write(b2)
            cd = (h2 or {}).get('Content-Disposition', '') or ''; fm = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
            rec.update(text_bytes=len(b2), text_sha256=hashlib.sha256(b2).hexdigest(), text_ctype=(h2 or {}).get('Content-Type'),
                       text_filename=urllib.parse.unquote(fm.group(1)) if fm else meta.get('text_filename')); b2 = None
            try: method, info = t2_extract(P, tmp, sppid, guard)
            except (S2.MemShed, S2.Stopped): raise
            except Exception as e: method, info = 'extract_error', dict(error=repr(e)[:200])
            rec['text_method'] = method; rec['extract'] = info
            if os.path.exists(tmp): os.remove(tmp)
    return rec
# ---------------- T2 packing (persisted per-law shards) ----------------
def t2_law_row(P, r):
    """ledger record -> (law, articles) with the T1 build metadata; text = OCR output if present, else extracted text"""
    sppid = r['id']; meta = r.get('meta') or {}
    method = r.get('text_method') or ('no_text_link' if not meta.get('has_text') else f"text_http_{r.get('text_http')}"); text = ''
    if os.path.exists(f"{P['ocr']}/{sppid}.txt"): text = open(f"{P['ocr']}/{sppid}.txt", encoding='utf-8', errors='replace').read(); method = 'pdf_ocr_tesseract_ces'
    elif os.path.exists(f"{P['text']}/{sppid[-2:]}/{sppid}.txt.gz") and method != 'pdf_skipped_over_1000_pages':
        text = gzip.open(f"{P['text']}/{sppid[-2:]}/{sppid}.txt.gz", 'rt', encoding='utf-8', errors='replace').read()
    law, arows = build_rows(sppid, meta, text, method, r['retrieved_at'], r.get('text_filename'))
    md = json.loads(law['metadata_json'])
    md.update(text_source_url=r.get('text_source_url'), text_original=dict(filename=r.get('text_filename'), sha256=r.get('text_sha256'), bytes=r.get('text_bytes'),
              content_type=r.get('text_ctype'), retained=False), verze=r.get('verze'), superseded_versions=r.get('superseded_versions', []), listing_cells=r.get('listing_cells'),
              kraj_iso=r.get('kraj_iso'), tranche='T2', extract=r.get('extract'),
              attachments_index=[dict(id=a, name=(meta.get('attachment_names') or {}).get(a), url=f'{BASE}/detail/{sppid}/prilohy/{a}') for a in meta.get('attachments', [])])
    law['metadata_json'] = json.dumps(md, ensure_ascii=False)
    return law, arows
def t2_ready(P, r):
    if r.get('detail_http') != 200: return False
    if r.get('text_method') == 'pdf_ocr_pending': return os.path.exists(f"{P['ocr']}/{r['id']}.txt")
    return True
def t2_pack(P, iso, final=False, guard=None):
    """pack ready, not-yet-packed acts of one kraj into new t2_<ISO>_<nnnn>.jsonl.gz shards of SHARD_N (a partial shard only if final); existing shards immutable."""
    os.makedirs(P['shards'], exist_ok=True); mp = f"{P['shards']}/manifest.json"
    man = json.load(open(mp)) if os.path.exists(mp) else dict(format='jsonl.gz: {"law": {19 NL-hub law cols}, "articles": [{9 cols}]} per line', shards={})
    packed = {i for s in man['shards'].values() for i in s['ids']}; led = f"{P['docs']}/{iso}.jsonl"
    last = {}   # pass 1 (streaming, small): id -> (line no. of its LAST record = redo after a forced exit wins, ready?)
    for n, r in enumerate(_iter_jsonl(led)): last[r['id']] = (n, t2_ready(P, r))
    ready = [i for i, (n, ok) in sorted(last.items(), key=lambda kv: kv[1][0]) if ok and i not in packed]
    k = sum(1 for n in man['shards'] if n.startswith(f't2_{iso}_')); made = 0
    while len(ready) >= SHARD_N or (final and ready):
        batch, ready = ready[:SHARD_N], ready[SHARD_N:]; want = {last[i][0] for i in batch}; written = []
        name = f't2_{iso}_{k:04d}.jsonl.gz'; p = f"{P['shards']}/{name}"; t = p + '.tmp'; na = 0; ne = 0
        with open(t, 'wb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=6, mtime=0) as g:
                for n, r in enumerate(_iter_jsonl(led)):   # pass 2: stream the ledger, build only this batch's rows
                    if n not in want: continue
                    law, arows = t2_law_row(P, r); na += len(arows); ne += not (law['text'] or '').strip(); written.append(r['id'])
                    g.write((json.dumps(dict(law=law, articles=arows), ensure_ascii=False) + '\n').encode())
            raw.flush(); os.fsync(raw.fileno())
        batch = written
        h = hashlib.sha256()
        with open(t, 'rb') as f:
            for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
        os.replace(t, p)
        man['shards'][name] = dict(kraj_iso=iso, n_laws=len(batch), n_articles=na, n_empty_text=ne, bytes=os.path.getsize(p), sha256=h.hexdigest(),
                                   packed_at=_now(), final_flush=bool(final and len(batch) < SHARD_N), ids=list(batch))
        man.update(n_shards=len(man['shards']), n_laws=sum(v['n_laws'] for v in man['shards'].values()), n_articles=sum(v['n_articles'] for v in man['shards'].values()), updated=_now())
        _atomic_json(mp, man); k += 1; made += 1
        glog(f'T2 SHARD {name} laws {len(batch)} articles {na} empty_text {ne} {os.path.getsize(p)/1e6:.1f}MB')
    return made, man.get('n_laws', 0)
# ---------------- T2 driver ----------------
class _CapNet(S2.Net):
    def __init__(self, *a, cap=None, **k):
        super().__init__(*a, **k); self.cap = cap
    def get(self, path, max_tries=1 + S2.RETRIES, stream_limit=None):
        if self.cap is not None and self.n >= self.cap: raise S2.Stopped(f'smoke request cap {self.cap} reached')
        return super().get(path, max_tries=max_tries if self.cap is None else 1, stream_limit=stream_limit)
def _go_ok_t2(tok):
    gf = f'{B}/COS_GO_T2'
    return bool(tok) and os.path.exists(gf) and open(gf).readline().strip() == tok
def _proc_running(pat):
    me = os.getpid(); out = []
    for d in os.listdir('/proc'):
        if not d.isdigit() or int(d) == me: continue
        try: cmd = open(f'/proc/{d}/cmdline', 'rb').read().replace(b'\0', b' ').decode('utf-8', 'replace')
        except Exception: continue
        if re.search(pat, cmd): out.append((int(d), cmd[:100]))
    return out
def t2_preflight(smoke=False):
    """-> list of refusal reasons (empty = OK)"""
    bad = []; g = _load_gcfg()
    if os.path.exists(STOP_CZ): bad.append(f'STOP_CZ present ({STOP_CZ}); remove it to allow a launch')
    if S2.memavail() < g['resume_memavail']: bad.append(f"MemAvailable {S2.memavail()} MB < {g['resume_memavail']} at launch")
    if not os.path.exists(CZ_USR+'/usr/share/tesseract-ocr/5/tessdata/ces.traineddata'): bad.append('tesseract ces traineddata missing (apt install tesseract-ocr tesseract-ocr-ces)')
    if not os.path.exists(CZ_USR+'/usr/share/hunspell/cs_CZ.dic'): bad.append('hunspell cs_CZ missing (apt install hunspell-cs)')
    if not os.path.exists(CZ_USR+'/usr/share/dict/american-english'): bad.append('wamerican missing (apt install wamerican)')
    import importlib.util
    if importlib.util.find_spec('spylls') is None: bad.append(f'spylls not importable by {sys.executable} (pip install spylls)')
    if not os.path.exists(f'{B}/ref/ico_map.json'): bad.append('ref/ico_map.json missing')
    if not smoke:
        others = _proc_running(r'cz_sbirkapp_collect\.py (t1|t2|full)( |$)')
        if others: bad.append(f'another CZ collector is running: {others}')
        idp = _proc_running(r'id_bpk_collect\.py')
        if idp: bad.append(f'ID bpk process running (no third collector): {idp}')
        try: col = int(json.load(open(STATE)).get('collectors') or 0)
        except Exception: col = 0
        if col >= 2: bad.append(f'PIN collectors={col} >= 2 already')
    return bad
OCR_GATE = f'{B}/t2/ocr_dpi_gate.json'
def ocr_gate_ok(c=None):
    """CoS 02:59 PT: before leaving CZ-10 (Praha) the 300 vs 200 dpi check on 3 scanned pages must pass for the configured ocr_dpi."""
    try: g = json.load(open(OCR_GATE))
    except Exception: return False, 'no gate file'
    c = c or _load_gcfg()
    if not g.get('pass'): return False, 'gate failed: ' + str(g.get('verdict'))
    if c['ocr_dpi'] < int(g.get('approved_dpi', 300)): return False, f"ocr_dpi {c['ocr_dpi']} < approved {g.get('approved_dpi')}"
    return True, f"pass approved_dpi {g.get('approved_dpi')} pages {g.get('pages')}"
def ocr_gate_wait(guard, iso):
    ok, why = ocr_gate_ok(guard.c); n = 0
    while not ok:
        if n % 30 == 0:
            glog(f'T2_HOLD_OCR_GATE before {iso}: {why} (needs {OCR_GATE})'); _t2_pin(czp_status='T2_HOLD_OCR_GATE', czp_t2_hold_before=iso)
        for _ in range(5):
            if S2.STOP.is_set() or os.path.exists(STOP_CZ): raise S2.Stopped('stop during OCR gate hold')
            time.sleep(2)
        n += 1; ok, why = ocr_gate_ok(_load_gcfg())
    glog(f'T2 OCR gate OK before {iso}: {why}')
def t2_drive(argv):
    smoke = '--smoke' in argv
    root = argv[argv.index('--root') + 1] if '--root' in argv else (None if not smoke else '/workspace/tmp/cz_t2_smoke')
    root = root or f'{B}/t2'
    if not smoke:
        tok = argv[argv.index('--cos-go') + 1] if '--cos-go' in argv else None
        if not _go_ok_t2(tok): sys.exit('REFUSED: t2 needs the CoS GO token (cz_sbirkapp/COS_GO_T2)')
        if os.path.realpath(root).startswith(os.path.realpath(f'{B}/t1')): sys.exit('REFUSED: T2 root inside T1')
    bad = t2_preflight(smoke)
    if bad:
        for b in bad: glog('REFUSED:', b)
        sys.exit(2)
    cap = int(argv[argv.index('--max-requests') + 1]) if '--max-requests' in argv else None
    max_docs = int(argv[argv.index('--max-docs') + 1]) if '--max-docs' in argv else None
    max_pages = int(argv[argv.index('--max-listing-pages') + 1]) if '--max-listing-pages' in argv else None
    if smoke and cap is None: cap = 10
    _T2['no_pin'] = smoke
    P = t2_paths(root)
    for k in ('listing', 'docs', 'raw', 'text', 'ocr', 'shards', 'ocrq', 'work', 'review'): os.makedirs(P[k], exist_ok=True)
    if os.path.exists(P['plan']): plan = json.load(open(P['plan']))
    else:
        plan = dict(created=_now(), order=[dict(vusc=v, iso=i, name=n, probe_count=c) for v, i, n, c in T2_ORDER_DEFAULT],
                    rule='remaining 12 kraje (excl. VÚSC 51 Karlovarský, 78 Liberecký = T1), smallest first by probe count')
        if '--kraje' in argv:
            want = argv[argv.index('--kraje') + 1].split(','); plan['order'] = [o for w in want for o in plan['order'] if o['iso'] == w]
        _atomic_json(P['plan'], plan)
    assert not any(o['vusc'] in ('51', '78') for o in plan['order']), 'T1 kraje in T2 plan'
    cur = json.load(open(P['cursor'])) if os.path.exists(P['cursor']) else dict(kraj_idx=0, kraje={}, done=0, created=_now())
    def checkpoint():
        cur['ts'] = _now(); _atomic_json(P['cursor'], cur)
    S2.install_signals()
    guard = StrictGuard(checkpoint=checkpoint); threading.Thread(target=guard.watcher, daemon=True).start()
    net = (_CapNet(BASE, UA, guard, delay=guard.c['delay_s'], cap=cap)); guard.net = net
    exclude = _ids_jsonl(f'{T1}/docs.jsonl')
    for o in plan['order']: exclude |= _ids_jsonl(f"{P['docs']}/{o['iso']}.jsonl")
    glog('T2 START', 'smoke' if smoke else 'live', 'pid', os.getpid(), 'root', root, 'mem', S2.memavail(), 'guard', guard.c, 'order', [o['iso'] for o in plan['order']],
         'cursor', {k: v for k, v in cur.items() if k != 'kraje'}, 'cap', cap)
    if not smoke:
        S2.state_merge('czp_', dict(czp_status='T2_LIVE', czp_pid=os.getpid(), czp_log=os.environ.get('CZP_LOG'), czp_t2_root=root, czp_started_pt=time.strftime('%Y-%m-%d %H:%M %Z'),
                                    czp_t2_kraj_order=[o['iso'] for o in plan['order']], czp_ts=_now()), collectors_delta=+1)
        _T2['bumped'] = True
    ocr = CZOCRWorker(P['ocrq'], P['ocr'], 'ces', guard, workers=2, limit_fn=guard.ocr_limit) if not smoke else None   # ocr_workers live (0 = OCR paused)
    if ocr: ocr.start()
    end = 'UNKNOWN'; total_docs = 0
    def kraj_pending_ocr(iso):
        last = {}
        for r in _iter_jsonl(f"{P['docs']}/{iso}.jsonl"): last[r['id']] = r.get('text_method') == 'pdf_ocr_pending'
        return [i for i, pend in last.items() if pend and not os.path.exists(f"{P['ocr']}/{i}.txt")]
    def requeue_lost_ocr(iso):
        """.cache/ocrq is not persisted: refetch originals of pending OCR acts whose PDF is gone (box restore)"""
        for sid in kraj_pending_ocr(iso):
            if not os.path.exists(f"{P['ocrq']}/{sid}.pdf"):
                st2, b2, _ = net.get(f'/detail/{sid}/text')
                if st2 == 200 and b2:
                    open(f"{P['ocrq']}/{sid}.pdf.tmp", 'wb').write(b2); os.replace(f"{P['ocrq']}/{sid}.pdf.tmp", f"{P['ocrq']}/{sid}.pdf"); glog('T2 OCR requeued', sid)
    def review_trigger(trigger):
        if smoke: return
        rl = os.environ.get('CZP_LOG', '/workspace/logs/cz_t2.log').replace('.log', '_review.log')
        subprocess.Popen(['nice', '-n', '19', sys.executable, '-u', '/workspace/scripts/cz_t2_review.py', '--auto', '--trigger', trigger, '--root', root],
                         stdout=open(rl, 'a'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        glog('T2 review package triggered:', trigger, 'log', rl)
    def housekeeping(final=False):
        nonlocal ocr
        if not final and not smoke and (cur['done'] // 50) % 10 != 0: return   # heavy part (ledger streaming) every ~500 docs
        if ocr is not None and not ocr.is_alive() and not S2.STOP.is_set():
            glog('T2 OCR worker ended (err=%s); restarting' % ocr.err); ocr = CZOCRWorker(P['ocrq'], P['ocr'], 'ces', guard, workers=2, limit_fn=guard.ocr_limit); ocr.start()
        for o in plan['order']:
            ks = cur['kraje'].get(o['iso'])
            if not ks: continue
            t2_pack(P, o['iso'], final=False)
            if ks.get('fetch_done') and not ks.get('final_flushed') and not kraj_pending_ocr(o['iso']):
                t2_pack(P, o['iso'], final=True); ks['final_flushed'] = _now(); checkpoint()
                glog(f"T2 KRAJ COMPLETE {o['iso']} ({o['name']})"); review_trigger(f"kraj_complete:{o['iso']}")
        mp = f"{P['shards']}/manifest.json"; nl = json.load(open(mp)).get('n_laws', 0) if os.path.exists(mp) else 0
        if nl // REVIEW_EVERY > cur.get('review_20k_n', 0):
            cur['review_20k_n'] = nl // REVIEW_EVERY; checkpoint(); review_trigger(f'every_20k:{nl}')
    try:
        for ki in range(cur['kraj_idx'], len(plan['order'])):
            o = plan['order'][ki]; vusc, iso = o['vusc'], o['iso']
            if not smoke and iso != 'CZ-10': ocr_gate_wait(guard, iso)
            ks = cur['kraje'].setdefault(iso, dict(listing_done=False, next_idx=0, done=0))
            cur['kraj_idx'] = ki; checkpoint()
            if not ks.get('listing_done'):
                ks['listing_total'] = t2_listing(net, P, vusc, iso, max_pages=max_pages); ks['listing_done'] = not bool(max_pages); checkpoint()
            order, drops = t2_targets(P, iso, exclude - _ids_jsonl(f"{P['docs']}/{iso}.jsonl"))
            ks.update(targets=len(order), drops=drops); checkpoint()
            glog(f"T2 KRAJ {iso} {o['name']} targets {len(order)} drops {drops} listing_total {ks.get('listing_total')} (probe {o['probe_count']})")
            _t2_pin(czp_status='T2_LIVE', czp_t2_kraj_current=iso, czp_t2_kraj_targets=len(order))
            requeue_lost_ocr(iso)
            have = _ids_jsonl(f"{P['docs']}/{iso}.jsonl"); t0 = time.time(); n0 = ks['done']; req0 = net.n
            with open(f"{P['docs']}/{iso}.jsonl", 'a', encoding='utf-8') as led:
                for idx, (sppid, cells) in enumerate(order):
                    if idx < ks['next_idx']: continue
                    if S2.STOP.is_set(): raise S2.Stopped()
                    if max_docs is not None and total_docs >= max_docs: raise S2.Stopped(f'smoke max docs {max_docs}')
                    if sppid in have: ks['next_idx'] = idx + 1; continue
                    while S2.dir_gb(P['ocrq']) > guard.c['ocrq_max_gb']:
                        guard.check('net'); _t2_pin(czp_status='T2_PAUSED_OCR_BACKLOG'); glog('T2 OCR backlog > %.1f GB; waiting' % guard.c['ocrq_max_gb'])
                        for _ in range(30):
                            if S2.STOP.is_set() or os.path.exists(STOP_CZ): raise S2.Stopped()
                            time.sleep(2)
                    rec = t2_fetch_one(net, P, guard, sppid, vusc, iso, cells)
                    led.write(json.dumps(rec, ensure_ascii=False) + '\n'); led.flush(); have.add(sppid); exclude.add(sppid)
                    ks['next_idx'] = idx + 1; ks['done'] += 1; cur['done'] += 1; total_docs += 1
                    if ks['done'] % 50 == 0 or smoke:   # chunk boundary: fsync ledger, atomic cursor, pack, triggers, progress
                        os.fsync(led.fileno()); checkpoint(); housekeeping(); _trim()
                        el = time.time() - t0; rate = (ks['done'] - n0) / max(el, 1); rem = (len(order) - ks['done']) / max(rate, 1e-6)
                        glog(f"T2 {iso} {ks['done']}/{len(order)} total {cur['done']} rate {rate:.3f} docs/s {(net.n - req0) / max(el, 1):.3f} req/s codes {net.codes} "
                             f"ocrq {S2.dir_gb(P['ocrq']):.2f}GB ocr_done {ocr.done_n if ocr else 0} rss {S2.rss_mb()}MB tree {tree_rss_mb()}MB ocr_w {guard.ocr_limit()} ocr_dpi {guard.c['ocr_dpi']} ocr_pages {_OCRSTAT['pages']} ocr_peak_child {_OCRSTAT['peak_child_mb']}MB ocr_capkill {_OCRSTAT['rss_cap']} ocr_failed {_OCRSTAT['failed']} mem {S2.memavail()}MB kraj_eta {_eta(rem)}")
                        _t2_pin(czp_status='T2_LIVE', czp_t2_kraj_current=iso, czp_t2_kraj_done=ks['done'], czp_t2_kraj_targets=len(order), czp_t2_done_total=cur['done'],
                                czp_t2_rate_docs_s=round(rate, 3), czp_http_codes={str(k): v for k, v in net.codes.items()})
                os.fsync(led.fileno())
            ks['fetch_done'] = _now() if not max_pages else False; checkpoint(); housekeeping(final=True)
            glog(f"T2 KRAJ FETCH DONE {iso} docs {ks['done']}")
        if smoke: end = 'T2_SMOKE_DONE'
        else:
            glog('T2 all kraje fetched; draining OCR')
            while ocr is not None and (ocr.pending() or not ocr.idle.is_set()):
                guard.check('net'); housekeeping(final=True); _t2_pin(czp_status='T2_OCR_DRAIN', czp_t2_ocr_pending=len(ocr.pending()))
                for _ in range(15):
                    if S2.STOP.is_set() or os.path.exists(STOP_CZ): raise S2.Stopped()
                    time.sleep(2)
            housekeeping(final=True); end = 'T2_DONE_AWAIT_REVIEW'
    except S2.HostBlocked as e: end = 'T2_STOP_3x403_429_503'; glog('STOP', e)
    except S2.MemShed as e: end = 'T2_MEMSHED'; glog('MEMSHED', e)
    except S2.Stopped as e: end = ('T2_STOPPED_BY_STOPFILE' if os.path.exists(STOP_CZ) else ('T2_SMOKE_CAP' if smoke else 'T2_STOPPED_BY_SIGNAL')); glog('STOPPED', e)
    except Exception as e:
        import traceback; traceback.print_exc(); end = f'T2_ERROR_{type(e).__name__}'
    finally:
        S2.STOP.set(); checkpoint(); kill_children()
        _t2_pin_end(end, end)
        glog('T2 EXIT', end, 'requests', net.n, net.codes, 'docs_this_run', total_docs, 'guard', {k: v for k, v in guard.G.items() if k not in ('termlogged',)})
    sys.exit(0 if end in ('T2_DONE_AWAIT_REVIEW', 'T2_SMOKE_DONE', 'T2_SMOKE_CAP') else 2)
def t2pack_cli(argv):
    root = argv[argv.index('--root') + 1] if '--root' in argv else f'{B}/t2'; P = t2_paths(root); plan = json.load(open(P['plan']))
    for o in plan['order']:
        if os.path.exists(f"{P['docs']}/{o['iso']}.jsonl"): print(o['iso'], t2_pack(P, o['iso'], final='--final' in argv))
def guard_dryrun():
    """simulated memory traces against StrictGuard (no network, no files written)"""
    g = StrictGuard(stop_file='/nonexistent/STOP', pause_file='/nonexistent/PAUSE'); g.c = dict(_load_gcfg())
    print('cfg', {k: g.c[k] for k in ('pause_memavail', 'resume_memavail', 'resume_hold_s', 'hard_term_memavail', 'hard_term_sustain_s', 'hard_term_poll_s', 'instant_term_memavail', 'max_pause_s', 'rss_limit_mb', 'delay_s')})
    class Sim:
        def __init__(s, f): s.f = f; s.t = 0.0; s.nw = g.c['hard_term_poll_s']
        def mem(s): return s.f(s.t)
        def clock(s): return s.t
        def sleep(s, d):
            end = s.t + d
            while s.nw <= end: s.t = s.nw; g.watch_tick(s.f(s.t), s.t, rss_fn=lambda: RSS[0]); s.nw += g.c['hard_term_poll_s']
            s.t = end
    RSS = [80]; ok_all = True
    def run(name, f, expect, pf=None):
        nonlocal ok_all
        g.G.update(min_mem=10 ** 9, n_pause=0, n_resume=0, n_filepause=0, low_t0=None, low_n=0, n_streaks=0, hard=None, hard_t=None, termlogged=False); g.paused = False
        g.pause_file = pf or '/nonexistent/PAUSE'; s = Sim(f)
        try: r = g.check('net', _sleep=s.sleep, _mem=s.mem, _clock=s.clock, _rss=lambda: RSS[0]); out = f'returned m={r}'
        except S2.MemShed as e: out = f'TERM {e}'
        except S2.Stopped: out = 'STOPPED'
        ok = out.startswith(expect); ok_all &= ok
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {out} | pauses={g.G['n_pause']} resumes={g.G['n_resume']} filepauses={g.G['n_filepause']} streaks={g.G['n_streaks']} sim_t={s.t:.0f}s")
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf) if False else contextlib.nullcontext():
        run('normal', lambda t: 5000, 'returned m=5000')
        run('dip 3450 -> recover 4300 (held 30s)', lambda t: 3450 if t < 25 else 4300, 'returned')
        run('flap 4300/4100 resets hold', lambda t: 3450 if t < 5 else (4100 if 10 <= t < 12 else 4300), 'returned')
        run('recover only to 4000 (<4200) -> stays paused >900s -> TERM', lambda t: 3450 if t < 1 else 4000, 'TERM paused>900')
        for d in (1, 2, 3, 4): run(f'{d}s dip <3000 inside a pause -> no TERM', lambda t, d=d: 3450 if t < 4 else (2900 if t < 4 + d else (3400 if t < 30 else 4400)), 'returned')
        run('sustained >=5s <3000 -> TERM', lambda t: 3450 if t < 4 else (2900 if t < 30 else 4400), 'TERM sustained_lt3000')
        run('single reading <2500 -> TERM', lambda t: 3450 if t < 6 else (2400 if t < 6.5 else 3450), 'TERM lt2500')
        run('single reading <2500 at gate -> TERM', lambda t: 2400, 'TERM lt2500')
        RSS[0] = 320; run('collector self rss 320MB -> TERM (immediate)', lambda t: 5000, 'TERM rss_self=320MB'); RSS[0] = 80
        import tempfile as _tf
        pfd = _tf.mkdtemp(prefix='czpf_'); pfile = f'{pfd}/PAUSE_CZ'; open(pfile, 'w').close()
        def f_pf(t):
            if t >= 40 and os.path.exists(pfile): os.remove(pfile)
            return 5000
        run('PAUSE_CZ for 40s (mem fine) -> FILEPAUSE then FILERESUME', f_pf, 'returned', pf=pfile)
        open(pfile, 'w').close()
        def f_pf2(t):
            if t >= 1200 and os.path.exists(pfile): os.remove(pfile)
            return 5000
        run('PAUSE_CZ 1200s -> no 900s TERM while file exists', f_pf2, 'returned', pf=pfile)
        os.rmdir(pfd)
        sfd = _tf.mkdtemp(prefix='czsf_'); g.stop_file = f'{sfd}/STOP_CZ'; open(g.stop_file, 'w').close()
        run('STOP_CZ present -> Stopped', lambda t: 5000, 'STOPPED'); os.remove(g.stop_file); os.rmdir(sfd); S2.STOP.clear(); g.stop_file = '/nonexistent/STOP'
    # ---- tree RSS step-down (CoS 01:32 PT): watcher ticks every 2 s with a simulated tree
    def trun(name, tf, expect, cfg_workers=2, dur=1500):
        nonlocal ok_all
        g.c['ocr_workers'] = cfg_workers; g.ocr_eff = 2; g.G.update(hard=None, hard_t=None, termlogged=False, low_t0=None, low_n=0)
        g.T.update(over_t0=None, under_t0=None, n_stepdown=0, n_stepup=0, max_tree=0, last_tree=0); out = 'no TERM'; trace = []
        for i in range(0, dur, 2):
            h = g.watch_tick(5000, float(i), rss_fn=lambda: 80, tree_fn=lambda: tf(i)); trace.append(g.ocr_limit())
            if h: out = f'TERM {h} at t={i}s'; break
        res = f"{out}; stepdowns={g.T['n_stepdown']} stepups={g.T['n_stepup']} ocr_workers_end={g.ocr_limit()} min_workers={min(trace)}"
        ok = all(e in res for e in expect); ok_all &= ok
        print(f"[{'OK' if ok else 'FAIL'}] tree: {name}: {res}")
    trun('320 MB for 20 s then 250 -> step down to 1, no TERM', lambda t: 320 if t < 20 else 250, ['no TERM', 'stepdowns=1', 'ocr_workers_end=1'])
    trun('320 MB sustained -> step down, TERM after 45 s grace with 1 worker', lambda t: 320, ['TERM rss_tree', 'with ocr_workers=1', 'at t=4', 'stepdowns=1'])
    trun('320 MB 30 s, then 150 MB 11 min -> RSS_STEPUP back to 2', lambda t: 320 if t < 30 else 150, ['no TERM', 'stepdowns=1', 'stepups=1', 'ocr_workers_end=2'])
    trun('320 MB 30 s, 150 MB 5 min, then 250 -> no step-up', lambda t: 320 if t < 30 else (150 if t < 330 else 250), ['no TERM', 'stepups=0', 'ocr_workers_end=1'])
    trun('at 1 worker: 320 for 30 s, 250 for 20 s, 320 for 30 s -> streak resets, no TERM', lambda t: 320 if t < 30 or 50 <= t < 80 else 250, ['no TERM', 'stepdowns=1'], dur=200)
    trun('config ocr_workers=1 + 320 sustained -> no step-down possible, TERM after grace', lambda t: 320, ['TERM rss_tree', 'stepdowns=0'], cfg_workers=1)
    g.c['ocr_workers'] = 2; g.ocr_eff = 2
    # ---- limiter: page concurrency follows the live limit (in-flight pages finish)
    import threading as _th
    lim = [2]; w = CZOCRWorker.__new__(CZOCRWorker); w.limit_fn = lambda: lim[0]; w.cv = _th.Condition(); w.active = 0
    w._acq(); w._acq(); lim[0] = 1; got = []
    th = _th.Thread(target=lambda: (w._acq(), got.append(time.time())), daemon=True); th.start(); time.sleep(0.3); blocked1 = not got
    w._rel(); time.sleep(0.3); blocked2 = not got      # active 1 >= limit 1 -> still blocked
    w._rel(); th.join(3); ok = blocked1 and blocked2 and bool(got) and w.active == 1; ok_all &= ok
    print(f"[{'OK' if ok else 'FAIL'}] limiter: limit 2->1 with 2 pages in flight: new page waits until both finish (blocked {blocked1},{blocked2}; started {bool(got)}; active {w.active})")
    print('GUARD DRYRUN', 'ALL OK' if ok_all else 'FAILURES')
    return ok_all
if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] in ('t2', 't2pack', 'guard_dryrun', 'extract'):
    if sys.argv[1] == 'extract':   # child: extract <odt|docx> <in> <out>
        _k, _i, _o = sys.argv[2:5]; _t = (_odt_text if _k == 'odt' else _docx_text)(_i)
        open(_o + '.tmp', 'w', encoding='utf-8').write(_t); os.replace(_o + '.tmp', _o); sys.exit(0)
    if sys.argv[1] == 't2': t2_drive(sys.argv[2:])
    elif sys.argv[1] == 't2pack': import pa_exit_guard; pa_exit_guard.run_guarded(t2pack_cli, sys.argv[2:])  # exit guard (pa_exit_guard)
    else: sys.exit(0 if guard_dryrun() else 1)

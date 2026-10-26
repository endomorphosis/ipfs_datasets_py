#!/usr/bin/env python3
"""NG national EXPAND collector (gov.ng hosts only). ONE process, sequential.
Targets: index/ng_targets.jsonl (NASS 'Acts & Publications' catalog acts not on hub 955aadec57e5 + justice.gov.ng rules PDF).
Rules: *.gov.ng only (no NigeriaLII / mirrors / Wayback); robots.txt obeyed (cached under robots/; 5xx => host disallowed);
>=2.5s between requests per host; 3 consecutive 403/429/503 on a host => host stopped; MemAvail <=3584MB => 'MEMGUARD TERM'.
Cache: cache/pdf/<law_id>.pdf.gz (+.meta.json); output out/<law_id>.json.gz (law record + article rows + quality). Resume-safe.
Text: pdftotext -layout (margin notes split off); OCR (pdftoppm 300dpi + tesseract TSV, margin blocks dropped) only when the
text layer is missing/poor; per-doc quality = dictionary-word ratio, garbage-char ratio, chars/page.
Usage: ng_collect.py handcheck | full"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, re, json, gzip, time, threading, subprocess, tempfile, shutil, urllib.robotparser
from urllib.parse import urlparse
import requests
B = '{_CORPORA}/ng_expand'; CP = f'{B}/cache/pdf'; OUT = f'{B}/out'; IDX = f'{B}/index'; RB = f'{B}/robots'
PIN = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'
UA = 'legal-corpora-ng-expand/1.0 (research corpus of official Nigerian federal legislation; polite; robots.txt obeyed; contact via huggingface.co/endomorphosis)'
TERM_MB = 3584; DELAY = 2.5; GOV = re.compile(r'(^|\.)gov\.ng$')
OCR_DPI = 300; OCR_MAX_PAGES = int(os.environ.get('NG_OCR_MAX_PAGES', '400'))
STRUCT_OCR_MAX_PAGES = int(os.environ.get('NG_STRUCT_OCR_MAX_PAGES', '120'))
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
    return 10 ** 9
def term(m):
    log(f'MEMGUARD TERM MemAvailable={m}MB')
    try: pin_update(mode='HOLD_0_NG_MEMSHED', collectors=0, pid=None, phase=f'NG collector self-TERM at MemAvail={m}MB; not restarted')
    except Exception as e: log('pin update failed', e)
    os._exit(3)
def mem_check():
    m = memavail()
    if m <= TERM_MB: term(m)
    return m
def _mg():
    while True: mem_check(); time.sleep(5)
def pin_update(**u):
    try: d = json.load(open(PIN))
    except Exception: d = {}
    d.update(u); d['ts'] = time.strftime('%Y-%m-%dT%H:%M:%S%z'); d['MemAvail_MB'] = memavail()
    open(PIN + '.tmp', 'w').write(json.dumps(d, indent=2)); os.replace(PIN + '.tmp', PIN)
class HostStop(Exception): pass
class Fetcher:
    def __init__(self):
        self.s = requests.Session(); self.s.headers['User-Agent'] = UA
        self.last = {}; self.bad = {}; self.stopped = set(); self.rp = {}; self.nreq = 0
    def robots(self, host):
        if host in self.rp: return self.rp[host]
        p = f'{RB}/{host}_robots.txt'; h = p + '.headers'
        st = None
        if os.path.exists(h):
            m = re.search(r'HTTP (\d+)', open(h).read()); st = int(m.group(1)) if m else None
        else:
            r = self.get(f'https://{host}/robots.txt', robots_check=False)
            st = None if r is None else r.status_code
            open(p, 'wb').write(b'' if r is None else r.content)
            open(h, 'w').write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} HTTP {st}\n")
        body = open(p, 'rb').read().decode('utf-8', 'replace')
        rp = urllib.robotparser.RobotFileParser()
        if st is None or st >= 500: rp.parse(['User-agent: *', 'Disallow: /']); mode = 'disallow_all(5xx/none)'
        elif st >= 400: rp.parse([]); mode = 'allow_all(4xx)'
        elif '<html' in body[:3000].lower() or '<!doctype' in body[:3000].lower() or body.lstrip().startswith('<!--'):
            rp.parse([]); mode = 'allow_all(200 html, no rules)'
        else: rp.parse(body.splitlines()); mode = 'parsed'
        self.rp[host] = (rp, mode); return self.rp[host]
    def get(self, url, robots_check=True, timeout=(20, 180)):
        host = urlparse(url).netloc.split(':')[0]
        if not GOV.search(host): raise ValueError('non-gov host refused: ' + url)
        if host in self.stopped: raise HostStop(host)
        if robots_check:
            rp, mode = self.robots(host)
            if not rp.can_fetch(UA, url): log('ROBOTS DISALLOW', url, mode); return 'robots'
        for att in range(2):
            mem_check()
            w = DELAY - (time.time() - self.last.get(host, 0))
            if w > 0: time.sleep(w)
            self.last[host] = time.time(); self.nreq += 1
            try: r = self.s.get(url, timeout=timeout, allow_redirects=False)
            except Exception as e: log('ERR', url, repr(e)[:200]); time.sleep(20); continue
            if r.status_code in (301, 302, 303, 307, 308):
                loc = requests.compat.urljoin(url, r.headers.get('location', ''))
                if not GOV.search(urlparse(loc).netloc.split(':')[0]): log('OFF-GOV redirect refused', url, loc); return None
                url = loc; continue
            if r.status_code in (403, 429, 503):
                self.bad[host] = self.bad.get(host, 0) + 1
                open(f'{B}/probe/http{r.status_code}_{host}_{int(time.time())}.txt', 'w').write(f'GET {url}\nHTTP {r.status_code}\n{dict(r.headers)}\n\n{r.text[:2000]}')
                log(f'HTTP {r.status_code} host={host} consecutive={self.bad[host]}', url)
                if self.bad[host] >= 3: self.stopped.add(host); log('HOST STOP', host); raise HostStop(host)
                time.sleep(30); continue
            self.bad[host] = 0
            return r
        return None
F = Fetcher()
# ---------------- text extraction + quality ----------------
_DICT = None
def dict_words():
    global _DICT
    if _DICT is None:
        w = set()
        for p in ('/usr/share/dict/words', '/usr/share/dict/american-english'):
            if os.path.exists(p): w |= {x.strip().lower() for x in open(p, encoding='utf-8', errors='ignore') if x.strip()}
        w |= set('''nigeria nigerian federation federal enacted gazette lfn cap act acts amendment amend amended amends commencement citation
        interpretation schedule schedules subsection subsections paragraph paragraphs thereof therein hereby hereunder thereunder whereof
        minister ministry commission commissioner council board tribunal agency authority naira kobo abuja lagos establishment
        functions offences offence penalty penalties appointment appointments regulations regulation provisions provision gazetted
        repeal repealed savings transitional chairman secretary pursuant notwithstanding hereinafter aforesaid preceding fct polytechnic
        senate representatives assembly bill explanatory memorandum signed president'''.split())
        _DICT = w
    return _DICT
GOOD_CH = re.compile(r"[A-Za-z0-9\s.,;:()'\"\-\u2013\u2014/&%$\[\]\u2018\u2019\u201c\u201d\u20a6*+=?!#@\u2026\u2022\u00a7\u00b0_<>|]")
def quality(text, pages):
    words = re.findall(r"[A-Za-z]+", text); D = dict_words()
    w3 = [w.lower() for w in words if len(w) >= 3]
    dr = sum(1 for w in w3 if w in D or w.rstrip('s') in D) / max(1, len(w3))
    ns = [c for c in text if not c.isspace()]
    gr = sum(1 for c in ns if not GOOD_CH.match(c)) / max(1, len(ns))
    # short-token noise: fraction of 1-2 letter alpha tokens that are not common words
    small_ok = {'a', 'i', 'an', 'as', 'at', 'be', 'by', 'do', 'if', 'in', 'is', 'it', 'no', 'of', 'on', 'or', 'so', 'to', 'up', 'we', 'he', 'me', 'my', 'us', 'am'}
    st = [w.lower() for w in words if len(w) <= 2]
    sn = sum(1 for w in st if w not in small_ok) / max(1, len(words))
    return dict(dict_word_ratio=round(dr, 4), garbage_char_ratio=round(gr, 4), short_token_noise=round(sn, 4),
                chars_per_page=round(len(ns) / max(1, pages)), words=len(words), pages=pages)
def grade(q):
    if q['pages'] and q['chars_per_page'] < 150: return 'empty'
    if q['dict_word_ratio'] >= 0.85 and q['garbage_char_ratio'] <= 0.02: return 'good'
    if q['dict_word_ratio'] >= 0.75 and q['garbage_char_ratio'] <= 0.05: return 'fair'
    return 'poor'
NUMTOK = re.compile(r'^\d{1,3}[A-Z]?[.,]?[-\u2013\u2014]*(\(\d+\))?$')
MNUM = re.compile(r'^\d{1,3}[A-Z]?\.$')
NUMSTART = re.compile(r'^\(?\d{1,3}')
def words_to_text(words, pw):
    """words: [(x0,y0,x1,y1,txt)] for one page. Groups into lines, finds the main text column and moves words lying
    wholly outside it (left/right marginal notes) to a margin stream. Returns (body, margin)."""
    if not words: return '', ''
    words = sorted(words, key=lambda w: (round(w[1]), w[0]))
    lines = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        yc = (w[1] + w[3]) / 2; h = max(1.0, w[3] - w[1])
        if lines and abs(lines[-1]['yc'] - yc) <= 0.45 * h: lines[-1]['w'].append(w)
        else: lines.append(dict(yc=yc, w=[w]))
    for l in lines: l['w'].sort(key=lambda w: w[0])
    gap = 0.025 * pw
    def main_seg(ws):
        segs, cur = [], [ws[0]]
        for a, b in zip(ws, ws[1:]):
            if b[0] - a[2] > gap: segs.append(cur); cur = [b]
            else: cur.append(b)
        segs.append(cur); return max(segs, key=len)
    longl = [main_seg(l['w']) for l in lines if len(l['w']) >= 6]
    longl = [m for m in longl if len(m) >= 5]
    if len(longl) >= 3:
        starts = sorted(m[0][0] for m in longl); ends = sorted(m[-1][2] for m in longl)
        bl = starts[int(0.10 * (len(starts) - 1))]; br = ends[int(0.90 * (len(ends) - 1))]
    else: bl, br = 0, pw
    tol = 0.012 * pw; unit = pw / 95.0
    body, margin = [], []
    for l in lines:
        bw = [w for w in l['w'] if not (w[2] <= bl - tol or w[0] >= br + tol)]
        # a section number printed left of the text column belongs to the body, not to the marginal note
        if bw and l['w'][0] not in bw and NUMTOK.match(l['w'][0][4]) and l['w'][0][0] < bl: bw = [l['w'][0]] + bw
        elif not bw and len(l['w']) == 1 and NUMTOK.match(l['w'][0][4]) and l['w'][0][0] < bl: bw = [l['w'][0]]
        mw = [w for w in l['w'] if w not in bw]
        if mw: margin.append(' '.join(w[4] for w in mw))
        # gazette layout: the section number is printed with the marginal heading ("13. Proof of Statute in court");
        # carry it into the body at the line where the heading starts, unless the body line is already numbered
        if len(mw) >= 2 and MNUM.match(mw[0][4]) and mw[1][4][:1].isupper() and not (bw and NUMSTART.match(bw[0][4])):
            bw = [mw[0]] + bw
        if bw:
            ind = int(max(0, bw[0][0] - bl) / unit)
            body.append(' ' * min(ind, 14) + ' '.join(w[4] for w in bw))
        else: body.append('')
    return '\n'.join(body), '\n'.join(margin)
def pdf_pages(path):
    out = subprocess.run(['pdfinfo', path], capture_output=True, text=True, timeout=120).stdout
    m = re.search(r'Pages:\s+(\d+)', out); return int(m.group(1)) if m else 0
import html as _html
def text_layer(path):
    """pdftotext -bbox word boxes -> per-page (body, margin)."""
    x = subprocess.run(['pdftotext', '-bbox', '-enc', 'UTF-8', path, '-'], capture_output=True, timeout=900).stdout.decode('utf-8', 'replace')
    bodies, margins = [], []
    for pm in re.finditer(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', x, re.S):
        pw = float(pm.group(1))
        ws = [(float(a), float(b), float(c), float(d), _html.unescape(t)) for a, b, c, d, t in
              re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', pm.group(3))]
        b_, m_ = words_to_text(ws, pw); bodies.append(b_); margins.append(m_)
    return bodies, margins
def ocr_page(path, i, tmp):
    base = f'{tmp}/p'
    subprocess.run(['pdftoppm', '-r', str(OCR_DPI), '-gray', '-f', str(i), '-l', str(i), '-png', path, base], check=True, timeout=300)
    png = [f for f in os.listdir(tmp) if f.endswith('.png')][0]
    tsv = subprocess.run(['tesseract', f'{tmp}/{png}', '-', '--psm', '3', '-l', 'eng', 'tsv'], capture_output=True, timeout=600).stdout.decode('utf-8', 'replace')
    os.remove(f'{tmp}/{png}')
    rows = [r.split('\t') for r in tsv.splitlines()[1:]]; rows = [r for r in rows if len(r) == 12]
    pw = max([int(r[6]) + int(r[8]) for r in rows if r[0] == '1'] + [1])
    ws = [(int(r[6]), int(r[7]), int(r[6]) + int(r[8]), int(r[7]) + int(r[9]), r[11]) for r in rows if r[0] == '5' and r[11].strip() and float(r[10]) >= 0]
    return words_to_text(ws, pw)
def ocr(path, npages, only=None):
    tmp = tempfile.mkdtemp(prefix='ngocr_'); out = {}
    try:
        for i in range(1, min(npages, OCR_MAX_PAGES) + 1):
            if only is not None and i not in only: continue
            mem_check(); out[i] = ocr_page(path, i, tmp)
    finally: shutil.rmtree(tmp, ignore_errors=True)
    return out
# ---------------- splitter ----------------
SEC = re.compile(r'^\s{0,14}(?:[\u2018\u2019\u201c\'"`_~|]{1,2}\s?)?(?:(\d{1,3})([A-Z]{0,2})|([lI]))\s?(?:\.{1,3}|,(?=\s*[A-Z\(])|(?=\s+\(\s?[1lI]\s?\)))\s*(?:[-\u2013\u2014]+\s*)?(?=[^\s\d.,;:]|$)')
SEC2 = re.compile(r'^\s{0,14}(?:[A-Za-z][\w,\'\u2019\-]*\s+){1,4}(\d{1,3})([A-Z]{0,2})\s?\.\s*[-\u2013\u2014]*\s*(?=\(\s?[1lI]\s?\)|[A-Z][a-z])')
SCHED = re.compile(r'^\s{0,40}((?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|THE)\s+)?SCHEDULE\b|^\s{0,40}(?:[FSTE]\s?[A-Z]+\s+)?S\s?CHEDULE\s*$', re.I)
EXPL = re.compile(r'^\s{0,40}EXPLANATORY\s+MEMORAND', re.I)
ENACT = re.compile(r'(?i)(be\s+it\s+)?e\s?nacted\s+by\s+the\s+n\s?ational\s+a\s?ssembly|enacted\s+by\s+the\s+(senate|national)|^\s*enacted\b', re.M)
ARR = re.compile(r'(?i)arrangement\s+of\s+sections')
def split_act(text, law_id, source_url, meta):
    lines = text.split('\n')
    # enactment start
    starts = [i for i, l in enumerate(lines) if ENACT.search(l)]
    arr = [i for i, l in enumerate(lines) if ARR.search(l)]
    start = starts[0] if starts else 0
    # arrangement count (lines between arrangement header and enactment)
    arr_nums = []
    if arr and starts and arr[0] < start:
        for l in lines[arr[0]:start]:
            for m in re.finditer(r'(?:^|\s)(\d{1,3})\s?\.\s+[A-Z]', l): arr_nums.append(int(m.group(1)))
    arr_count = max(arr_nums) if arr_nums else None
    secnum = {}
    for j, l in enumerate(lines):
        mm = SEC.match(l)
        if mm and mm.group(1): secnum[j] = int(mm.group(1))
    def run(i0, implicit1=False):
        secs, cur, last, annex, mode, ann_cur = [], None, 0, [], 'body', None
        i = i0
        if implicit1:
            # section 1 number lost (e.g. merged into a PART heading / margin): text from the enactment formula up to "2." is section 1
            cur = dict(nr='1', n=1, lines=lines[start + 1:i0]); secs.append(cur); last = 1
        while i < len(lines):
            l = lines[i]
            if mode == 'body' and secs and ((SCHED.match(l) and l.strip().upper() == l.strip()) or EXPL.match(l)): mode = 'annex'
            if mode == 'annex':
                if (SCHED.match(l) and l.strip().upper() == l.strip()) or EXPL.match(l):
                    ann_cur = dict(head=l.strip(), lines=[]); annex.append(ann_cur)
                elif ann_cur is not None: ann_cur['lines'].append(l)
                i += 1; continue
            m = SEC.match(l); pref = False
            if not m and last > 0:
                m2 = SEC2.match(l)
                if m2 and 1 <= int(m2.group(1)) - last <= 2: m = m2; pref = True
            if m:
                g1 = m.group(1) if pref else m.group(1)
                n = int(g1) if g1 else 1; suf = (m.group(2) or '')
                rest = l[m.end():].lstrip()
                strong = bool(rest) and (rest[0] == '(' or rest[0].isupper())
                big = g1 and last > 0 and 3 < n - last <= 8 and strong and (arr_count is None or n <= arr_count)
                if big and any(last < secnum.get(j, -1) < n for j in range(i + 1, min(len(lines), i + 400))): big = False
                ok = pref or (n == last + 1) or (g1 and 1 < n - last <= 3 and last > 0) or (g1 and n == last and suf) or big
                if not g1 and last != 0: ok = False
                if ok:
                    cur = dict(nr=f'{n}{suf}', n=n, lines=[l]); secs.append(cur); last = n; i += 1; continue
            if cur is not None: cur['lines'].append(l)
            elif annex == [] and EXPL.match(l) and not secs: pass
            i += 1
        return secs, annex
    ORD = re.compile(r'^\s{0,14}ORDER\s+(\d{1,3}|[IVXLC]{1,6})\b\s*[:.\-\u2013\u2014]?\s*(.*)$')
    oh = [(i, ORD.match(l)) for i, l in enumerate(lines) if ORD.match(l)]
    if len(oh) >= 3:
        # court rules: unit = Order (rules restart in each Order). Use the last run starting at Order 1 (skips the arrangement list)
        ones = [k for k, (i, m) in enumerate(oh) if m.group(1) in ('1', 'I')]
        k0 = ones[-1] if ones else 0
        sel = oh[k0:]; secs = []
        for k, (i, m) in enumerate(sel):
            j = sel[k + 1][0] if k + 1 < len(sel) else len(lines)
            secs.append(dict(nr=m.group(1), n=k + 1, lines=lines[i:j], unit='order'))
        annex = []
        if secs:
            tail = secs[-1]['lines']
            cut = next((x for x, l in enumerate(tail) if x > 0 and ((SCHED.match(l) and l.strip().upper() == l.strip()) or EXPL.match(l) or re.match(r'^\s{0,20}(FORMS?|APPENDIX)\s*$', l))), None)
            if cut: annex = [dict(head=tail[cut].strip(), lines=tail[cut + 1:])]; secs[-1]['lines'] = tail[:cut]
        cands = []
        best = (secs, annex, oh[k0][0], None)
    else:
        cands = [i for i, l in enumerate(lines) if (lambda m: m and (m.group(3) or int(m.group(1)) == 1))(SEC.match(l))]
        best = ([], [], -1, 0)
    if starts:
        after = [i for i in cands if i > start]
        cands = after or cands
    imp = []
    if starts and len(oh) < 3:
        imp = [i for i, l in enumerate(lines) if i > start and (lambda m: m and m.group(1) and int(m.group(1)) == 2)(SEC.match(l))][:5]
        imp = [i for i in imp if not any(start < c < i for c in cands)]
    for c, im in [(c, False) for c in cands[:40]] + [(c, True) for c in imp]:
        sc, an = run(c, im)
        if not sc: continue
        lens = sorted(len(' '.join(x['lines']).strip()) for x in sc); med = lens[len(lens) // 2]
        nn = [x['n'] for x in sc]; miss = len(set(range(1, max(nn) + 1)) - set(nn))
        key = (med >= 60 or len(sc) <= 2, len(sc) - 2 * miss, c)
        if best[2] < 0 or best[3] is None or key > best[3]: best = (sc, an, c, key)
    secs, annex = best[0], best[1]
    if arr_count is None and best[2] > 0:
        lo = arr[0] if (arr and arr[0] < best[2]) else 0
        nn = [int(m.group(1)) for l in lines[lo:best[2]] for m in [re.match(r'^\s*(\d{1,3})\s?\.\s+[A-Z]', l)] if m]
        arr_count = max(nn) if len(nn) >= 3 else None
    whole = False
    if not secs and text.strip():
        # no numbered sections recoverable (e.g. section numbers clipped off the scan): keep the enacted text as ONE
        # 'text' unit so nothing is lost; flagged split_fallback_whole_text and not counted as sections
        secs = [dict(nr='1', n=0, lines=lines[start:] if starts else lines, unit='text')]; whole = True
    rows = []
    def clean(ls):
        t = '\n'.join(x.rstrip() for x in ls); t = re.sub(r'\n{3,}', '\n\n', t); return re.sub(r'[ \t]{2,}', ' ', t).strip()
    seen = {}
    def uid(b):
        k = seen.get(b, 0) + 1; seen[b] = k; return b if k == 1 else f'{b}-{k}'
    for s in secs:
        body = clean(s['lines'])
        un = s.get('unit', 'section'); UN = un.capitalize()
        rows.append(dict(law_id=law_id, id=uid(f"{law_id}-{un}-{s['nr'].lower()}"), title=f"{UN} {s['nr']}", text=body, source_url=source_url,
                         document_number=f"{UN} {s['nr']}", article_number=s['nr'], record_type='article',
                         metadata_json=json.dumps(dict(law_identifier=law_id, unit=un, **meta, metadata=dict(text_extraction=dict(source='official', backend=meta.get('backend')))), ensure_ascii=False)))
    for k, a in enumerate(annex, 1):
        body = clean([a['head']] + a['lines'])
        if len(body) < 3: continue
        kind = 'explanatory-memorandum' if EXPL.match(a['head']) else 'schedule'
        rows.append(dict(law_id=law_id, id=uid(f'{law_id}-{kind}-{k}'), title=a['head'][:200], text=body, source_url=source_url,
                         document_number=a['head'][:120], article_number=None, record_type='annex',
                         metadata_json=json.dumps(dict(law_identifier=law_id, unit=kind, **meta, metadata=dict(text_extraction=dict(source='official', backend=meta.get('backend')))), ensure_ascii=False)))
    ss = [s for s in secs if s.get('unit') != 'text']
    nums = [s['n'] for s in ss]; mx = max(nums) if nums else 0
    st = dict(split_fallback_whole_text=whole, n_sections=len(ss), max_section=mx, missing_numbers=sorted(set(range(1, mx + 1)) - set(nums))[:50], n_missing=len(set(range(1, mx + 1)) - set(nums)),
              arrangement_count=arr_count, enactment_found=bool(starts), n_annex=sum(1 for r in rows if r['record_type'] == 'annex'),
              last_section_has_citation=bool(secs) and bool(re.search(r'(?i)cited\s+as', ' '.join(secs[-1]['lines']))),
              citation_in_any_section=any(re.search(r'(?i)may\s+be\s+cited\s+as', ' '.join(s['lines'])) for s in secs))
    return rows, st
# ---------------- per-doc pipeline ----------------
def process(t):
    lid = t['law_id']; op = f'{OUT}/{lid}.json.gz'
    if os.path.exists(op): return 'done_before'
    pp = f'{CP}/{lid}.pdf.gz'; mp = f'{CP}/{lid}.meta.json'
    if not os.path.exists(pp) and os.path.exists(f'{CP}/{lid}.doc.gz'): pp = f'{CP}/{lid}.doc.gz'
    if not os.path.exists(pp):
        r = F.get(t['url'])
        if r == 'robots': return 'robots_disallow'
        if r is None or r.status_code != 200: log('FAIL', lid, getattr(r, 'status_code', None), t['url']); return 'fetch_fail'
        is_doc = r.content[:8] == bytes.fromhex('D0CF11E0A1B11AE1') or 'msword' in (r.headers.get('content-type') or '') or r.content[:2] == b'PK'
        if not r.content.startswith(b'%PDF') and not is_doc:
            log('NOT_PDF', lid, r.headers.get('content-type'), len(r.content)); open(f'{B}/probe/notpdf_{lid}.bin', 'wb').write(r.content[:20000]); return 'not_pdf'
        if is_doc: pp = f'{CP}/{lid}.doc.gz'
        tmp = pp + '.tmp'; open(tmp, 'wb').write(gzip.compress(r.content, 6)); os.replace(tmp, pp)
        json.dump(dict(url=t['url'], final_url=r.url, bytes=len(r.content), content_type=r.headers.get('content-type'), last_modified=r.headers.get('last-modified'),
                       fetched_at=time.strftime('%Y-%m-%dT%H:%M:%S%z')), open(mp, 'w'))
    meta = json.load(open(mp))
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f: f.write(gzip.decompress(open(pp, 'rb').read())); path = f.name
    src_format = 'pdf'
    if pp.endswith('.doc.gz'):
        # MS Word original from the official host -> PDF via headless LibreOffice (local, no network)
        src_format = 'msword'; d = tempfile.mkdtemp(prefix='ngdoc_'); src = f'{d}/{lid}.doc'; os.replace(path, src)
        subprocess.run(['soffice', '--headless', '--convert-to', 'pdf', '--outdir', d, src], capture_output=True, timeout=300)
        conv = f'{d}/{lid}.pdf'
        if not os.path.exists(conv): shutil.rmtree(d, ignore_errors=True); log('DOC_CONVERT_FAIL', lid); return 'convert_fail'
        path = tempfile.mktemp(suffix='.pdf'); shutil.move(conv, path); shutil.rmtree(d, ignore_errors=True)
    try:
        npages = pdf_pages(path)
        tb, tm = text_layer(path); ttext = '\n'.join(tb)
        qt = quality(ttext, npages or len(tb)); gt = grade(qt); backend = 'pdftotext'; body, margins, q, g = list(tb), list(tm), qt, gt
        qo = go = None; ocr_s = None; ocr_pages = []
        t0 = time.time()
        if gt in ('empty', 'poor') or qt['dict_word_ratio'] < 0.88 or qt['garbage_char_ratio'] > 0.015 or qt['short_token_noise'] > 0.08:
            od = ocr(path, npages); ob = [od[i][0] if i in od else '' for i in range(1, npages + 1)]; om = [od[i][1] if i in od else '' for i in range(1, npages + 1)]
            qo = quality('\n'.join(ob), len(od) or 1); go = grade(qo)
            if (qo['dict_word_ratio'] > qt['dict_word_ratio'] + 0.02) or gt == 'empty':
                body, margins, q, g, backend = ob, om, qo, go, 'ocr_tesseract'; ocr_pages = sorted(od)
        if backend == 'pdftotext':
            # per-page fallback: pages whose text layer is (near) empty while the document otherwise has text
            pc = [len(re.sub(r'\s', '', x)) for x in tb]; med = sorted(pc)[len(pc) // 2] if pc else 0
            weak = [i + 1 for i, c in enumerate(pc) if c < 200 and med >= 600]
            if weak:
                od = ocr(path, npages, only=set(weak))
                for i, (b_, m_) in od.items():
                    if len(re.sub(r'\s', '', b_)) > pc[i - 1]: body[i - 1], margins[i - 1] = b_, m_; ocr_pages.append(i)
                if ocr_pages:
                    backend = 'pdftotext+ocr_pages'; q = quality('\n'.join(body), npages or len(body)); g = grade(q)
        ocr_s = round(time.time() - t0) if (qo is not None or ocr_pages) else None
        text = '\n\n'.join(body).strip()
        smeta = dict(title=t['title'], year=t.get('year'), backend=backend, source_host=t['host'], toc_source='document', catalog=t.get('catalog'))
        rows, st = split_act(text, lid, t['url'], smeta)
        # structural fallback: the text layer reads well but section numbers are missing from it (common in NASS gazette scans)
        ac = st.get('arrangement_count') or 0
        struct_bad = (ac >= 4 and st['n_sections'] < 0.6 * ac) or (st['n_sections'] == 0 and st['enactment_found']) or (st['max_section'] >= 8 and st['n_missing'] > 0.15 * st['max_section'])
        st['struct_ocr_tried'] = False
        if struct_bad and qo is None and backend.startswith('pdftotext') and npages <= STRUCT_OCR_MAX_PAGES:
            t1 = time.time(); od = ocr(path, npages); st['struct_ocr_tried'] = True
            ob = [od[i][0] if i in od else '' for i in range(1, npages + 1)]; om = [od[i][1] if i in od else '' for i in range(1, npages + 1)]
            qo = quality('\n'.join(ob), len(od) or 1); go = grade(qo)
            otext = '\n\n'.join(ob).strip()
            smeta2 = dict(smeta, backend='ocr_tesseract')
            rows2, st2 = split_act(otext, lid, t['url'], smeta2)
            ocr_s = (ocr_s or 0) + round(time.time() - t1)
            if (st2['n_sections'] - st2['n_missing']) > (st['n_sections'] - st['n_missing']) and go in ('good', 'fair'):
                st2['struct_ocr_tried'] = True; st2['struct_ocr_used'] = True
                rows, st, text, margins, q, g, backend, ocr_pages = rows2, st2, otext, om, qo, go, 'ocr_tesseract', sorted(od)
        rec = dict(law_id=lid, title=t['title'], year=t.get('year'), source_url=t['url'], host=t['host'], nass_download_id=t.get('nass_download_id'),
                   uploaded=t.get('uploaded'), catalog=t.get('catalog'), fetch=meta, source_format=src_format, pages=npages, backend=backend,
                   quality=q, grade=g, ocr_pages=ocr_pages, quality_text_layer=qt, grade_text_layer=gt, quality_ocr=qo, grade_ocr=go, ocr_seconds=ocr_s,
                   split=st, text=text, margin_notes='\n'.join(margins), rows=rows)
        tmp = op + '.tmp'
        with gzip.open(tmp, 'wt', encoding='utf-8') as f: json.dump(rec, f, ensure_ascii=False)
        os.replace(tmp, op)
        summ = dict(law_id=lid, title=t['title'][:100], year=t.get('year'), host=t['host'], pages=npages, backend=backend, grade=g, **{k: q[k] for k in ('dict_word_ratio', 'garbage_char_ratio', 'chars_per_page')},
                    grade_text_layer=gt, dict_text_layer=qt['dict_word_ratio'], grade_ocr=go, dict_ocr=qo['dict_word_ratio'] if qo else None, ocr_seconds=ocr_s, n_ocr_pages=len(ocr_pages), rows=len(rows), **st)
        with open(f'{IDX}/collect_summary.jsonl', 'a') as f: f.write(json.dumps(summ) + '\n')
        return 'ok'
    finally: os.remove(path)
HAND = None
def hand_targets(T):
    # spread over years/hosts/sizes; deterministic
    import random
    rnd = random.Random(20261003)
    bucket = {}
    for t in T: bucket.setdefault((t['host'], (int(t['year']) // 4 * 4) if t.get('year') else 0), []).append(t)
    out = [t for t in T if t['host'] != 'nass.gov.ng']
    keys = sorted(bucket)
    while len(out) < 20:
        for k in keys:
            c = [t for t in bucket[k] if t not in out]
            if c and len(out) < 20: out.append(rnd.choice(c))
    return out
def main():
    mode = sys.argv[1]; threading.Thread(target=_mg, daemon=True).start()
    for d in (CP, OUT, IDX): os.makedirs(d, exist_ok=True)
    T = [json.loads(l) for l in open(f'{IDX}/ng_targets.jsonl')]
    todo = hand_targets(T) if mode == 'handcheck' else T
    if mode == 'handcheck': open(f'{IDX}/handcheck_ids.json', 'w').write(json.dumps([t['law_id'] for t in todo]))
    log('START', mode, 'pid', os.getpid(), 'targets', len(todo), f'mem={memavail()}MB', 'delay', DELAY)
    res = {}; t0 = time.time()
    for n, t in enumerate(todo, 1):
        try: s = process(t)
        except HostStop as e: s = 'host_stopped'; log('HOST STOPPED', e, t['law_id'])
        except Exception as e: s = f'error_{type(e).__name__}'; log('ERROR', t['law_id'], repr(e)[:300])
        res[s] = res.get(s, 0) + 1
        if mode == 'handcheck' or n % 10 == 0:
            log('progress', n, '/', len(todo), res, 'nreq', F.nreq, f'{(time.time()-t0)/n:.1f}s/doc', f'mem={memavail()}MB')
        if mode == 'full' and n % 10 == 0:
            try: pin_update(progress=f'{n}/{len(todo)} {res}')
            except Exception: pass
        if mode == 'full' and n % 50 == 0: log('progress50', n, '/', len(todo), res, f'mem={memavail()}MB')
    json.dump(dict(mode=mode, res=res, nreq=F.nreq, stopped_hosts=sorted(F.stopped), seconds=round(time.time() - t0), ended=time.strftime('%Y-%m-%dT%H:%M:%S%z')), open(f'{B}/collect_result_{mode}.json', 'w'), indent=1)
    log('DONE', res)
    if mode == 'full':
        try: pin_update(mode='HOLD_0_NG_COLLECT_DONE', collectors=0, pid=None, phase=f'NG collect finished {res}')
        except Exception: pass
if __name__ == '__main__': main()

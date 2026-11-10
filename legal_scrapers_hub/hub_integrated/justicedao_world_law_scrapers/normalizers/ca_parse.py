"""Parsers for CA provincial/territorial legislation: ON (e-Laws JSON/HTML), MB (bilingual HTML, English column), NB (laws.gnb.ca HTML),
generic text splitter for NS (HTML) and SK/NT/NU (pdftotext)."""
import re, json, lxml.html
BLOCK = {'p', 'div', 'blockquote', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'br', 'section', 'ul', 'ol', 'dt', 'dd', 'dl'}
WS = re.compile(r'[ \t\u00a0\u2002\u2003\u2009\u202f\u200b]+')
def clean(t):
    t = WS.sub(' ', t); t = re.sub(r' *\n *', '\n', t); t = re.sub(r'\n{3,}', '\n\n', t); return t.strip()
CTRL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
def decode(b):
    return CTRL.sub(' ', _decode(b))
def _decode(b):
    try: return b.decode('utf-8')
    except UnicodeDecodeError:
        t = b.decode('utf-8', 'surrogateescape')
        return re.sub(r'[\udc80-\udcff]+', lambda m: bytes(ord(c) - 0xdc00 for c in m.group(0)).decode('cp1252', 'replace'), t)
def el_text(el):
    out = []
    def walk(e):
        if not isinstance(e.tag, str):
            if e.tail: out.append(e.tail)
            return
        tag = e.tag.lower()
        if tag in ('script', 'style'):
            if e.tail: out.append(e.tail)
            return
        if tag in BLOCK: out.append('\n')
        if e.text: out.append(e.text)
        for c in e: walk(c)
        if tag in BLOCK: out.append('\n')
        elif tag == 'span' and 'label' in (e.get('class') or ''): out.append(' ')
        if e.tail: out.append(e.tail)
    walk(el); return clean(''.join(out))
def first_line(t): return t.split('\n', 1)[0].strip()

# ---------- number keys / numbering check ----------
def _key1(p):
    m = re.match(r'(\d+)([A-Za-z]*)', p)
    return (int(m.group(1)), m.group(2).upper()) if m else (0, '')
def key(num):
    parts = [x for x in re.split(r'[.\-\u2011\u2013]', num or '') if x]
    return tuple(_key1(p) for p in parts) if parts else ((0, ''),)
def numbering_check(units):
    secs = [u['num'] for u in units if u['kind'] == 'section']
    ks = [key(n) for n in secs]
    ints = sorted(set(k[0][0] for k in ks))
    gaps = [i for i in range(ints[0], ints[-1] + 1) if i not in set(ints)] if ints else []
    return dict(n_sections=len(secs), n_schedules=sum(1 for u in units if u['kind'] == 'schedule'),
                nonmonotonic=sum(1 for a, b in zip(ks, ks[1:]) if b <= a), int_regress=sum(1 for a, b in zip(ks, ks[1:]) if b[0][0] < a[0][0]),
                duplicates=len(secs) - len(set(secs)), first=secs[0] if secs else None, last=secs[-1] if secs else None, int_gaps=len(gaps), gap_sample=gaps[:10])

# ---------- Ontario ----------
def parse_on(raw):
    d = json.loads(raw); doc = lxml.html.fromstring('<div>' + (d.get('content') or '') + '</div>')
    for t in doc.xpath('.//table[.//p[starts-with(@class,"TOC") or starts-with(@class,"YTOC")]]'): t.drop_tree()
    units = []; cur = None; head = []; body = []; nif_skipped = 0; last_key = None
    for p in doc.iter('p'):
        cls = (p.get('class') or '').strip(); c0 = cls.split(' ')[0] if cls else ''
        if c0.startswith(('footnote', 'Yfootnote', 'TOC', 'YTOC', 'toc', 'Pnote', 'YPnote')): continue
        if p.xpath('ancestor::p'): continue
        if c0[:1] == 'Y' and c0[1:2].islower():   # e-Laws 'Y' classes = amendments not yet in force; keep only current in-force text
            nif_skipped += 1; continue
        txt = el_text(p)
        if not txt: continue
        body.append(txt)
        base = c0[1:] if c0.startswith('Y') and c0[1:2].islower() else c0
        if base in ('headnote', 'headnoteitalic'):
            head.append(txt)
            if cur is not None: cur['lines'].append(txt)
            continue
        if base in ('section', 'sectionx'):
            m = re.match(r'^(\d+(?:\.\d+)*[A-Za-z]{0,3})\b\.?\s*(.*)$', txt, re.S)
            if m:
                k = key(m.group(1))
                if last_key is not None and k[0][0] < last_key[0][0]:   # integer numbering restarts: numbered paragraphs inside a schedule/form/agreement
                    if cur is None or cur['kind'] != 'schedule':
                        cur = dict(kind='schedule', num=str(sum(1 for u in units if u['kind'] == 'schedule') + 1), heading=' / '.join(head) or None, lines=[]); units.append(cur)
                    cur['lines'].append(txt); head = []; continue
                if cur is not None and head and cur['lines'][-len(head):] == head: del cur['lines'][-len(head):]
                cur = dict(kind='section', num=m.group(1), heading=' / '.join(head) or None, lines=[txt]); units.append(cur); head = []; last_key = k; continue
        if base in ('schedule', 'Schedule') and re.match(r'(?i)^(schedule|form)\b', txt):
            if cur is not None and head and cur['lines'][-len(head):] == head: del cur['lines'][-len(head):]
            m = re.match(r'(?i)^schedule[ \t]*([0-9]+[A-Z]?|[A-Z])?\b', txt)
            cur = dict(kind='schedule', num=(m.group(1) if m and m.group(1) else str(sum(1 for u in units if u['kind'] == 'schedule') + 1)), heading=' / '.join(head) or None, lines=[txt]); units.append(cur); head = []; continue
        head = []
        if base.startswith(('heading', 'partnum')):
            continue
        if cur is not None: cur['lines'].append(txt)
    out = []
    for u in units:
        t = clean('\n'.join(u['lines']))
        if t: out.append(dict(kind=u['kind'], num=u['num'], heading=u['heading'], text=t))
    meta = {k: d.get(k) for k in ('title', 'alias', 'state', 'updatedAt', 'docSource', 'dateFrom', 'tabMode')}
    meta['consolidation_period'] = re.sub(r'<[^>]+>', '', (d.get('comments') or {}).get('consolidationPeriod') or '') or None; meta['not_in_force_paragraphs_skipped'] = nif_skipped; cm = d.get('comments') or {}; meta['note'] = clean(lxml.html.fromstring('<div>' + cm['pnote'] + '</div>').text_content()) if cm.get('pnote') else None; meta['ynote'] = cm.get('ynote'); meta['description'] = d.get('description')
    meta['chapter'] = clean(lxml.html.fromstring('<div>' + d['chapter'] + '</div>').text_content()) if d.get('chapter') else None
    return clean('\n'.join(body)), out, meta

# ---------- Manitoba ----------
def parse_mb(raw):
    doc = lxml.html.fromstring(decode(raw))
    main = doc.get_element_by_id('mainContent', None)
    if main is None: main = doc.body
    for t in main.xpath('.//*[@id="mainTOCdiv"]|.//details[@id="mainTOC"]|.//*[contains(@class,"regcol-f")]|.//script|.//style'):
        if t.getparent() is not None: t.drop_tree()
    rows = main.xpath('.//div[contains(concat(" ",@class," ")," regrow ")]')
    if not rows: rows = [main]
    units = []; cur = None; body = []; last_key = None
    for r in rows:
        txt = el_text(r)
        if not txt: continue
        body.append(txt)
        sn = r.xpath('.//span[@class="secnum"]')
        if sn:
            num = clean(sn[0].text_content()).rstrip('.').strip()
            hd = r.xpath('.//h6[contains(@class,"secheading")]'); head = clean(hd[0].text_content()) if hd else None
            t2 = txt[len(head):].strip() if head and txt.startswith(head) else txt
            nn = re.sub(r'\(.*$', '', num.replace(' ', ''))
            if cur is not None and cur['kind'] == 'section' and nn == cur['num']:
                cur['lines'].append(txt); continue
            if re.match(r'^\d+(?:\.\d+)*[A-Za-z]{0,3}(?:\(\d+(?:\.\d+)?\))?$', num.replace(' ', '')):
                k = key(nn)
                if last_key is not None and k[0][0] < last_key[0][0]:   # integer numbering restarts -> numbered articles of a schedule (convention/agreement)
                    if cur is None or cur['kind'] != 'schedule':
                        cur = dict(kind='schedule', num=str(sum(1 for u in units if u['kind'] == 'schedule') + 1), heading=None, lines=[]); units.append(cur)
                    cur['lines'].append(txt); continue
                cur = dict(kind='section', num=re.sub(r'\(.*$', '', num.replace(' ', '')), heading=head, lines=[t2]); units.append(cur); last_key = k; continue
        cent = r.xpath('.//p[starts-with(@class,"centred") or starts-with(@class,"center")]')
        if cent and len(txt) < 200 and re.match(r'(?i)^(schedule|form)\b', txt):
            m = re.match(r'(?i)^schedule\s*([0-9A-Z.]+)?', txt)
            cur = dict(kind='schedule', num=(m.group(1) if m and m.group(1) else str(sum(1 for u in units if u['kind'] == 'schedule') + 1)), heading=None, lines=[txt]); units.append(cur); continue
        if cent and len(txt) < 200 and not r.xpath('.//p[not(starts-with(@class,"centred")) and not(starts-with(@class,"center"))]'):
            if cur is not None and cur['kind'] == 'section': cur = None
            continue
        if cur is not None: cur['lines'].append(txt)
    out = [dict(kind=u['kind'], num=u['num'], heading=u['heading'], text=clean('\n'.join(u['lines']))) for u in units]
    title = doc.xpath('//title'); return clean('\n'.join(body)), [u for u in out if u['text']], {'html_title': clean(title[0].text_content()) if title else None}

# ---------- New Brunswick ----------
def parse_nb(raw):
    doc = lxml.html.fromstring(decode(raw))
    secs = doc.xpath('//div[starts-with(@class,"Border")][@id]')
    top = [s for s in secs if re.match(r'^(se|sc|sch|ap|fo):[^-]+$', s.get('id') or '')]
    units = []
    for s in top:
        typ, num = s.get('id').split(':', 1); num = num.replace('_', '.')
        if s.xpath('ancestor::div[starts-with(@class,"Border")][@id][starts-with(@id,"se:") or starts-with(@id,"sc")]'): continue
        hd = s.xpath('.//*[@id="%s-sh"]' % s.get('id')); head = clean(hd[0].text_content()) if hd else None
        if hd: hd[0].drop_tree()
        for h in s.xpath('.//*[contains(@class,"history")]'): h.drop_tree()
        t = el_text(s)
        if not t: continue
        units.append(dict(kind='section' if typ == 'se' else 'schedule', num=num, heading=head, text=t))
    cont = doc.xpath('//div[contains(@class,"legislative-document") or @id="content" or contains(@class,"document-content")]')
    root = cont[0] if cont else doc.body
    for h in root.xpath('.//nav|.//script|.//style|.//*[contains(@class,"modal")]'):
        if h.getparent() is not None: h.drop_tree()
    full = el_text(root)
    ti = doc.xpath('//*[@id="id-lt"]') or doc.xpath('//title')
    return full, units, {'doc_title': clean(ti[0].text_content()) if ti else None, 'nif_sections': len(doc.xpath('//div[contains(@class,"legislative-document-nif")]'))}

# ---------- generic text splitter (NS html, SK/NT/NU pdf text) ----------
SEC = re.compile(r'^\s{0,60}(?:(?P<margin>[A-Za-z][^\d\n]{0,90}?)\s{2,})?(?P<num>\d{1,4}(?:[.\u2011\-]\d{1,4}){0,2}[A-Za-z]{0,3})(?P<dot>\.)?(?:\s+|(?=\(\d))(?P<rest>(?:\(\d+(?:\.\d+)?[a-z]?\)\s+[A-Z\u201c"\u2018\[]|[A-Z\u201c"\u2018\[]|\((?!\d)).*)$')
MONTHY = re.compile(r'^(Jan|Feb|Mar|Apr|May|June?|July?|Aug|Sept?|Oct|Nov|Dec|January|February|March|April|August|September|October|November|December)\.?,? \d{4}\b')
SCH = re.compile(r'^\s*(?:SCHEDULE|Schedule)(?:\s+([0-9]+[A-Z]?|[A-Z]))?\s*$')
def is_heading(s):
    s = s.strip()
    return 2 < len(s) < 90 and not re.search(r'[.;,:]$', s) and not s.isupper() and not re.match(r'^[\d(]', s) and not re.search(r'\s{3,}', s)
def split_text(txt, html_mode=False, max_jump=40):
    lines = [l.replace('\f', '').rstrip() for l in txt.replace('\r', '').split('\n')]
    units = []; cur = None; last = None; started = False; sch_n = 0
    for l in lines:
        s = l.strip()
        if not s: continue
        m = SEC.match(l.replace('\u2011', '-'))
        if m and not MONTHY.match(m.group('rest')) and not m.group('rest').isupper() and re.search(r'[a-z]{3}', m.group('rest')) and not re.match(r'^[A-Z ]{6,}$', m.group('rest').split('  ')[0]):
            num = m.group('num'); k = key(num)
            if started and units and k == key(units[0]['num']) and sum(len('\n'.join(u['lines'])) for u in units) / len(units) < 160:
                pending[:] = cur['lines'][-1:] if cur else []
                units.clear(); cur = None; last = None; started = False; sch_n = 0   # previous matches were a table of contents
            ok = (not started and k[0][0] <= 2) or (started and last is not None and k > last and k[0][0] - last[0][0] <= max_jump)   # also resumes after a (possibly spurious, e.g. wrapped 'Schedule A' line) schedule if main numbering continues
            if ok:
                head = clean(m.group('margin')) if m.group('margin') else None
                if head is None and cur is not None and cur['lines'] and is_heading(cur['lines'][-1]):
                    head = cur['lines'].pop().strip()
                elif head is None and pending and is_heading(pending[-1]): head = pending[-1].strip()
                cur = dict(kind='section', num=num, heading=head, lines=[f"{num}{m.group('dot') or ''} {m.group('rest').strip()}"]); units.append(cur)
                last = k; started = True; pending.clear(); continue
        ms = SCH.match(s)
        if ms and started:
            sch_n += 1; cur = dict(kind='schedule', num=ms.group(1) or str(sch_n), heading=None, lines=[s]); units.append(cur); continue
        if cur is not None: cur['lines'].append(re.sub(r'\s{2,}', ' ', s))
        else: pending.append(s)
    out = []
    for u in units:
        t = clean('\n'.join(u['lines']))
        if t: out.append(dict(kind=u['kind'], num=u['num'], heading=u['heading'], text=t))
    return out
pending = []
def parse_generic(text, max_jump=40):
    """Try the splitter from each candidate 'section 1' line (TOCs in PDFs/HTML otherwise poison the monotonic filter); keep the parse
    with the most sections (ties: more text)."""
    lines = text.replace('\r', '').split('\n')
    cands = [0]
    for i, l in enumerate(lines):
        m = SEC.match(l.replace('\f', '').replace('\u2011', '-'))
        if m and m.group('num') == '1' and re.search(r'[a-z]{3}', m.group('rest')): cands.append(max(0, i - 1))
    if len(cands) > 40: cands = cands[:40]
    best = None
    for c in dict.fromkeys(cands):
        pending.clear(); u = split_text('\n'.join(lines[c:]), max_jump=max_jump)
        sc = (sum(1 for x in u if x['kind'] == 'section'), sum(len(x['text']) for x in u))
        if best is None or sc > best[0]: best = (sc, u)
    return best[1] if best else []
def ns_html_text(raw):
    doc = lxml.html.fromstring(decode(raw))
    for f in doc.xpath('//font[@size="-2"]|//script|//style'):
        tail = f.tail; p = f.getparent()
        if p is None: continue
        f.drop_tree() if not tail else (f.drop_tree())
    body = doc.body if doc.body is not None else doc
    return el_text(body)
def pdf_text_clean(t):
    import collections
    raw = [l.replace('\f', '') for l in t.replace('\r', '').split('\n')]
    norm = lambda l: re.sub(r'\d+', '#', re.sub(r'\s+', ' ', re.sub(r'^(?:[ivxlc]{1,6}|\d{1,4})\s+|\s+(?:[ivxlc]{1,6}|\d{1,4})$', '', l.strip())))   # ignore page-number tokens
    cnt = collections.Counter(norm(l) for l in raw if l.strip())
    lines = []
    for s in raw:
        st = s.strip()
        if re.match(r'^(\d{1,4}|[ivxlc]{1,6})$', st): continue                      # bare page numbers
        if st and cnt[norm(s)] >= 4 and len(st) >= 6 and not st.startswith('(') and (not SEC.match(s) or not re.search(r'[a-z]{3}', st)): continue   # running headers/footers (incl. 'page# CITATION' footers)
        if st and len(st) < 90 and not re.search(r'[a-z]', st) and not re.match(r'^\(?[0-9]', st) and not SCH.match(st): continue  # all-caps headings / headers
        if re.match(r'^(©|PRINTED BY|Printed by|REGINA, SASKATCHEWAN|IMPRIMÉ PAR)', st): break
        lines.append(s)
    return '\n'.join(lines)

# ---------- bilingual two-column (EN left / FR right) pdftotext -layout text: keep the English (left) column ----------
FR_MARK = re.compile(r'CODIFICATION|MODIFIÉ PAR|\bLOI SUR\b|RÈGLEMENT|\bch\. ')
def left_column(t):
    import collections
    lines = t.replace('\r', '').split('\n')
    if not FR_MARK.search('\n'.join(lines[:60])): return t, False
    starts = collections.Counter()
    for l in lines:
        for m in re.finditer(r'\S {3,}(?=\S)', l):
            p = m.end()
            if p >= 40: starts[p] += 1; break
    if not starts: return t, False
    # mode over a +-3 window
    best = max(starts, key=lambda p: sum(starts.get(q, 0) for q in range(p - 3, p + 4)))
    nonempty = sum(1 for l in lines if l.strip())
    if sum(starts.get(q, 0) for q in range(best - 8, best + 19)) < 0.08 * nonempty: return t, False
    out = []
    for l in lines:
        s = len(l) - len(l.lstrip(' '))
        if l.strip() and s >= best - 3: continue                       # right column only (French) or centred page furniture
        cut = None
        for m in re.finditer(r' {2,}(?=\S)', l):
            if m.end() >= best - 8: cut = m.start(); break
        l2 = l[:cut] if cut is not None else l
        w = re.findall(r"[a-zà-ÿ']+", l2.lower())
        fr = sum(1 for x in w if x in FR_W or x.startswith(("l'", "d'", "qu'"))); en = sum(1 for x in w if x in EN_W)
        if fr >= 2 and fr > en: continue                                  # full-width French block (e.g. French schedules/forms)
        out.append(l2)
    return '\n'.join(out), True
FR_W = set('les des du une soit est aux dans pour par sur qui que au et la le ou en sont ne pas cette ces leur être selon lorsque article paragraphe alinéa loi règlement'.split())
EN_W = set('the of and to in shall or for by is be any a an may under this that with as on not section subsection act regulations'.split())

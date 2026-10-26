"""Parsers for AU state/territory legislation (NSW/QLD/TAS PCO html, WA Word-html, NT PDF text)."""
import re, lxml.html
from lxml import etree

BLOCK = {'p','div','blockquote','li','tr','h1','h2','h3','h4','h5','h6','table','br','section','ul','ol'}
WS = re.compile(r'[ \t\u00a0\u2002\u2003\u2009]+')

def clean(t):
    t = WS.sub(' ', t)
    t = re.sub(r' *\n *', '\n', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()

# ---------------- PCO (NSW / QLD / TAS) ----------------
UNIT_PCO = re.compile(r'^(?:sec|cl|rule|reg|art)\.([0-9]+[A-Za-z]*(?:\.[0-9]+[A-Za-z]*)*(?:-[0-9]+[A-Za-z]*(?:\.[0-9]+[A-Za-z]*)*)?)$')
SCH_PCO = re.compile(r'^sch\.([0-9A-Za-z]+)$')
BOUND_PCO = re.compile(r'^(?:pt|ch|div|sdiv)\.[0-9A-Za-z.]+(?:-(?:(?:pt|ch|div|sdiv)\.)?[0-9A-Za-z.]+)*$')
UNIT_TAS = re.compile(r'^GS([0-9]+[A-Za-z]*)@EN$')
SCH_TAS = re.compile(r'^JS([0-9A-Za-z]+)@EN$')
BOUND_TAS = re.compile(r'^H[A-Z]{1,2}[0-9]+[A-Za-z]*@EN$')
END_IDS = {'endnotes','hist','ednt','ed','push','footer','top-link-block'}

def _classify(aid, tas):
    if tas:
        m = UNIT_TAS.match(aid)
        if m: return ('section', m.group(1))
        m = SCH_TAS.match(aid)
        if m: return ('schedule', m.group(1))
        if BOUND_TAS.match(aid): return ('bound', None)
    else:
        m = UNIT_PCO.match(aid)
        if m: return ('section', m.group(1))
        m = SCH_PCO.match(aid)
        if m: return ('schedule', m.group(1))
        if BOUND_PCO.match(aid): return ('bound', None)
    if aid in END_IDS or aid.startswith('endnote'): return ('end', None)
    return None

def parse_pco(html, tas=False):
    doc = lxml.html.fromstring(html)
    fv = doc.get_element_by_id('fragview', None)
    if fv is None:
        return None, []
    title = ''
    t = doc.xpath('//h1[@class="title"]')
    if t: title = clean(t[0].text_content())
    for bad in fv.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," view-history-note ") or contains(@class,"history-note") or @class="frag-crest" or contains(@class,"nswcrest")]'):
        if bad.getparent() is not None:
            bad.drop_tree()
    out = []
    def walk(el):
        if not isinstance(el.tag, str):
            if el.tail: out.append(el.tail)
            return
        aid = el.get('id') or el.get('name')
        if aid:
            c = _classify(aid, tas)
            if c: out.append(('M', c[0], c[1], aid))
        tag = el.tag.lower()
        if tag in BLOCK: out.append('\n')
        if el.text: out.append(el.text)
        for ch in el: walk(ch)
        if tag in BLOCK: out.append('\n')
        elif (el.get('class') or '').split(' ')[0] in ('HeadingStyle','HeadingNumber','ListNumber','frag-no'): out.append(' ')
        if el.tail: out.append(el.tail)
    walk(fv)
    units = []; cur = None; buf = []; ended = False
    def flush():
        if cur is not None:
            txt = clean(''.join(buf))
            units.append(dict(kind=cur[0], num=cur[1], anchor=cur[2], text=txt))
    for x in out:
        if isinstance(x, tuple):
            kind, num = x[1], x[2]
            if cur is not None and x[3] == cur[2]:
                continue  # same anchor repeated (e.g. id + name / history wrapper)
            if kind == 'end':
                flush(); cur = None; buf = []; ended = True; break
            flush(); buf = []
            cur = (kind, num, x[3]) if kind in ('section','schedule') else None
        elif cur is not None:
            buf.append(x)
    if not ended: flush()
    # de-duplicate anchors appearing twice (e.g. inline name + id)
    seen = set(); res = []
    for u in units:
        k = (u['kind'], u['num'])
        if k in seen and not u['text']: continue
        seen.add(k); res.append(u)
    return title, [u for u in res if u['text']]

# ---------------- WA (Word-exported html) ----------------
def parse_wa(html):
    doc = lxml.html.fromstring(html)
    units = []; cur = None; buf = []; in_sch = False
    title = ''
    tt = doc.xpath('//title')
    if tt: title = clean(tt[0].text_content())
    def flush():
        if cur is not None:
            t = clean('\n'.join(buf)); t = re.sub(r'^(\[?\d+[A-Z]*(?:\.\d+[A-Z]*)*)\.(?=[^\d\s])', r'\1. ', t)
            units.append(dict(kind=cur[0], num=cur[1], anchor=None, text=t))
    for p in doc.iter('p'):
        cls = (p.get('class') or '')
        if cls.startswith('TOC'): continue
        txt = p.text_content()
        if cls.startswith('nHeading2') or (cls.startswith('NoteHeading') and txt.strip().startswith('Notes') and units):
            if units or cur: break
        sn = p.xpath('.//span[starts-with(@class,"CharSectno")]')
        sch = p.xpath('.//span[starts-with(@class,"CharSchNo")]')
        if sch and clean(sch[0].text_content()):
            flush(); buf = [txt]; in_sch = True
            num = re.sub(r'(?i)^schedule\s*', '', clean(sch[0].text_content())).strip() or '1'
            cur = ('schedule', num); continue
        is_head = cls.startswith('Heading5') or (cls.startswith('Enactment') and sn) or (cls.startswith('Ednotesection') and re.match(r'^\s*\[\s*\d+[A-Z]*\.', txt))
        if (sn or cls.startswith('Ednotesection')) and is_head and not in_sch:
            num = clean(sn[0].text_content()).rstrip('.') if sn else ''
            mt = re.match(r'^\s*(\d+[A-Z]*(?:\.\d+[A-Z]*)+)\.?\s*[^\d\s.]', txt)
            if num and mt and mt.group(1).startswith(num + '.'):
                num = mt.group(1)   # Part-prefixed numbering, e.g. Local Government Act 1995 s. 9.64
            mt2 = re.match(r'^\s*\[?\s*(\d+(?:[A-Z]{1,5}(?![a-z]))?(?:\.\d+(?:[A-Z]{1,5}(?![a-z]))?)*)', txt)
            if num and mt2 and mt2.group(1) != num and mt2.group(1).startswith(num) and not mt2.group(1).startswith(num + '.'):
                num = mt2.group(1)  # CharSectno span holds only a prefix of the number (e.g. '1' vs '149')
            if not re.match(r'^\d+[A-Z]*(?:\.\d+[A-Z]*)*$', num):
                mm = re.match(r'^\s*\[?\s*(\d+[A-Z]*(?:\.\d+[A-Z]*)*)(?:\.|-|\s|[A-Z][a-z])', txt); num = mm.group(1) if mm else ''
            if num:
                flush(); cur = ('section', num); buf = [txt]; continue
        if not in_sch and (cls.startswith('Heading2') or cls.startswith('Heading3') or cls.startswith('Heading4')):
            flush(); cur = None; buf = []; continue
        if cur is not None: buf.append(txt)
    if cur is not None and (not units or units[-1]['num'] != cur[1] or units[-1]['kind'] != cur[0]):
        flush()
    return title, [u for u in units if u['text']]

# ---------------- NT (PDF text, pdftotext -layout) ----------------
SEC_NT = re.compile(r'^(\d{1,4}[A-Z]{0,3})\s{2,}(\S.{0,250})$')
SCH_NT = re.compile(r'^Schedule\s+(\d+[A-Z]*)?\s{2,}(\S.*)$|^Schedule\s+(\d+[A-Z]*)\s*$|^Schedule\s*$')
HDR_NT = re.compile(r'^(Part|Division|Subdivision|Chapter)\s+\S+(\s{2,}.*)?$')

def _key1(p):
    m = re.match(r'(\d+)([A-Za-z]*)', p)
    if not m: return (0, '')
    suf = m.group(2).upper()
    # plain lexical suffix order (36D < 36DA < 36E); inserted 5AA-before-5A cases count as non-monotonic steps
    return (int(m.group(1)), suf)

def _key(num):
    parts = [x for x in (num or '').split('.') if x]
    return tuple(_key1(p) for p in parts) if parts else ((0, ''),)

def parse_nt_text(txt):
    lines = txt.replace('\r', '').split('\n')
    nonempty = [l.strip() for l in lines if l.strip()]
    title_line = None
    for l in nonempty[:6]:
        if l.upper() == l and re.search(r'(ACT|REGULATIONS|RULES|BY-LAWS|ORDER)\b', l) and 'TERRITORY' not in l:
            title_line = l; break
    start = 0
    if title_line:
        occ = [i for i, l in enumerate(lines) if l.strip() == title_line]
        if len(occ) >= 2: start = occ[1] + 1
    en = [i for i, l in enumerate(lines) if l.strip() == 'ENDNOTES']
    if en and en[0] < len(lines) * 0.5 and len(en) >= 2:
        start = max(start, en[0] + 1)
    else:
        lim = next((i for i, l in enumerate(lines) if l.strip().startswith('An Act ')), int(len(lines) * 0.3))
        toc = [i for i, l in enumerate(lines[:lim]) if re.search(r'\.{6,}\s*\d+\s*$', l)]
        if toc and toc[-1] + 1 > start:
            start = toc[-1] + 1
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].strip() == 'ENDNOTES':
            end = i; break
    body = lines[start:end]
    # remove page footers / running headers
    cleaned = []
    for i, l in enumerate(body):
        s = l.strip()
        if '\f' in l:
            s2 = l.replace('\f', '').strip()
            if HDR_NT.match(s2) or not s2: continue
            l = l.replace('\f', ''); s = s2
        if re.match(r'^.{3,120}\s{5,}(\d+|[ivxlc]+)$', s) and re.search(r'(Act|Regulations|Rules|By-laws|Order)\s+\d{4}', s):
            continue
        cleaned.append(l)
    units = []; cur = None; buf = []; last = ((0, ''),); last_sch = 0
    def flush():
        if cur is not None:
            units.append(dict(kind=cur[0], num=cur[1], anchor=None, text=clean('\n'.join(buf))))
    for l in cleaned:
        if l[:1] not in (' ', '') :
            m = SEC_NT.match(l.rstrip())
            if m and cur is not None and cur[0] == 'schedule':
                m = None
            if m and _key(m.group(1)) > last and _key(m.group(1))[0][0] - last[0][0] <= 60:
                flush(); cur = ('section', m.group(1)); buf = [f"{m.group(1)} {m.group(2).strip()}"]; last = _key(m.group(1)); continue
            ms = SCH_NT.match(l.rstrip())
            if ms:
                n = ms.group(1) or ms.group(3) or '1'
                if _key(n)[0][0] > last_sch or (not units and cur is None):
                    flush(); cur = ('schedule', n); buf = [l.strip()]; last_sch = _key(n)[0][0]; continue
                else:
                    continue
            if HDR_NT.match(l.strip()):
                continue
        if cur is not None: buf.append(l)
    flush()
    return title_line, [u for u in units if u['text']]

def numbering_check(units):
    secs = [u['num'] for u in units if u['kind'] == 'section']
    ks = [_key(n) for n in secs]
    nonmono = sum(1 for a, b in zip(ks, ks[1:]) if b <= a)
    int_regress = sum(1 for a, b in zip(ks, ks[1:]) if b[0][0] < a[0][0])
    dup = len(secs) - len(set(secs))
    ints = sorted(set(k[0][0] for k in ks))
    gaps = [i for i in range(ints[0], ints[-1] + 1) if i not in set(ints)] if ints else []
    return dict(n_sections=len(secs), n_schedules=sum(1 for u in units if u['kind']=='schedule'),
                nonmonotonic=nonmono, int_regress=int_regress, duplicates=dup, first=secs[0] if secs else None,
                last=secs[-1] if secs else None, int_gaps=len(gaps), gap_sample=gaps[:10])

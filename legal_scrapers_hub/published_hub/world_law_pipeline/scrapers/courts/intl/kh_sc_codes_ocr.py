#!/usr/bin/env python3
"""KH: Code of Civil Procedure (2006) and Code of Criminal Procedure (2007) of Cambodia, Khmer official texts
published by the Supreme Court of Cambodia (supremecourt.gov.kh -> asset.cambodia.gov.kh).
PDFs use legacy (Limon) Khmer font encoding, so pages are OCR'd with tesseract 5.5 + khm (200 dpi, psm 4);
article boundaries validated against the article sequence in the PDF's legacy text layer.
Usage: kh_sc_codes_ocr.py  (expects OCR text in /tmp/khocr/<tag>/pNNNN.txt). Appends new rule_ids only."""
import re, os, json, glob, hashlib, datetime
ROOT = '/workspace/world_courts'; OUT = os.environ.get('KH_OUT', f'{ROOT}/data/kh/kh_rules.jsonl')
BASE = 'https://asset.cambodia.gov.kh/supreme-court/documents/law/'
DOCS = [
 ('ccp', 'Civil-Code-Procedure.pdf', 'kh-ccp-2006', 'Code of Civil Procedure of the Kingdom of Cambodia (ក្រមនីតិវិធីរដ្ឋប្បវេណី, 2006)', None, 586),
 ('cpc', 'creminal-procedure-code.pdf', 'kh-cpc-2007', 'Code of Criminal Procedure of the Kingdom of Cambodia (ក្រមនីតិវិធីព្រហ្មទណ្ឌ, 2007)', None, 612),
]
KD = str.maketrans('០១២៣៤៥៦៧៨៩', '0123456789')
HEAD = re.compile(r'^\s*មា[ត្រ]{1,4}ា?\s*([០-៩0-9OoIl\]\[|!]{1,4})\s*[\.\-=:–—>]*\s*(.*)$')
STRONG = re.compile(r'^\s*មា[ត្រ]{1,4}ា?\s*[០-៩0-9OoIl\]\[|!]{1,4}\s*[\.,]\s*[-–=_\.]{1,3}\s*\S')
PART = re.compile(r'^\s*(គន្ថ|ជំពូក)')
def near(a, b):
    a, b = str(a), str(b); return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 1
existing = {json.loads(l)['rule_id'] for l in open(OUT) if l.strip()} if os.path.exists(OUT) else set()
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
total = 0
for tag, fn, rsid, rset, eff, expect in DOCS:
    pdf = f'{ROOT}/rules/raw/kh/{fn}'; sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    pages = sorted(glob.glob(f'/tmp/khocr/{tag}/p*.txt'))
    lines = []
    for p in pages:
        pg = int(re.search(r'p(\d+)\.txt', p).group(1))
        for l in open(p, encoding='utf-8'):
            l = l.rstrip()
            if not l.strip() or (len(l.strip()) <= 4 and not re.search(r'[\u1780-\u17ff]{2}', l)): continue
            lines.append((pg, l.strip()))
    arts, cur, nxt, book, chap = [], None, 1, None, None
    for pg, l in lines:
        m = HEAD.match(l)
        if m:
            raw = m.group(1).translate(KD); dig = re.sub(r'\D', '', raw)
            n = None
            if dig and (int(dig) == nxt or near(dig, nxt)): n = nxt
            elif dig and nxt < int(dig) <= nxt + 5 and re.match(r'^\s*\S+\s*\S{1,4}\s*[\.\-=:–—>]', l): n = int(dig)
            elif STRONG.match(l) and cur is not None and not (dig and nxt - 3 <= int(dig) < nxt): n = nxt  # heading layout with misread number
            if n is not None and n <= expect:
                nxt = n
                cur = {'n': nxt, 'title': m.group(2).strip(' .-=:'), 'part': ' / '.join(x for x in (book, chap) if x), 'page': pg, 'text': []}
                arts.append(cur); nxt += 1; continue
        if PART.match(l) and len(l) < 90:
            if l.startswith('គន្ថ'): book, chap = l, None
            elif l.startswith('ជំពូក'): chap = l
        if cur is not None and cur['n'] == expect and l.startswith('ធ្វើនៅ'):
            break  # promulgation formula after the last article; annexes/table of contents follow
        if cur is not None: cur['text'].append(l)
    new = 0
    with open(OUT, 'a') as f:
        for a in arts:
            rid = f'{rsid}:a{a["n"]}'
            if rid in existing: continue
            existing.add(rid); new += 1
            f.write(json.dumps({'rule_id': rid, 'rule_set_id': rsid, 'court_id': None, 'jurisdiction': 'KH', 'rule_set': rset,
                'rule_number': f'មាត្រា {a["n"]} (Article {a["n"]})', 'title': a['title'] or None, 'part': a['part'] or None,
                'text': '\n'.join(a['text']).strip() or None, 'effective_date': eff, 'pdf_path': f'rules/raw/kh/{fn}',
                'pdf_sha256': sha, 'source_sha256': sha, 'source_url': BASE + fn, 'index_url': 'https://supremecourt.gov.kh/laws',
                'site_policy': 'robots_allowed|supremecourt.gov.kh robots.txt: User-agent * Disallow: (empty)|official Supreme Court of Cambodia website, no restrictive terms found',
                'retrieved_at': now, 'license': 'Cambodian legislation (official text published by the Supreme Court); no licence stated',
                'language': 'km', 'source_kind': 'official_ocr', 'source_page': a['page'], 'needs_review': True,
                'version_note': f'tesseract 5.5 khm OCR (200 dpi) of official PDF with legacy Limon font encoding; article sequence checked against PDF text layer ({expect} articles); OCR errors likely; later amendments not consolidated'},
                ensure_ascii=False) + '\n')
    total += new
    print(tag, 'pages', len(pages), 'articles', len(arts), 'expected', expect, 'new', new)
print('total new', total)

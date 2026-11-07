#!/usr/bin/env python3
"""Split a KOOP BWB toestand XML into rows with the hub articles schema:
law_id, id, title, text, source_url, document_number, article_number, record_type, metadata_json.
- record_type 'article': top-level <artikel> (nested/quoted artikel inside an artikel is kept inside its parent's text)
- record_type 'annex'  : <bijlage> (whole annex as one row; artikel inside a bijlage stay in the annex text)
- record_type 'section': top-level <divisie> only when the regeling has NO artikel (circulaires/beleidsregels)
IDs: <law_id>-art-<nr-slug> | <law_id>-bijlage-<nr-slug|n> | <law_id>-div-<n>; duplicates get -2, -3 ... (document order).
Structure path (boek/deel/titeldeel/hoofdstuk/afdeling/paragraaf/...) and lid count go to metadata_json."""
import re, json, xml.etree.ElementTree as ET
SKIP = {'meta-data', 'brondata', 'jcis', 'bwb-inputbestand', 'bwb-wijzigingen', 'redactionele-correcties'}
BLOCK = {'al', 'lid', 'li', 'kop', 'tussenkop', 'row', 'p', 'considerans.al', 'wij', 'titel', 'definitie-item', 'aanhef', 'tgroup',
         'lijst', 'artikel', 'bijlage', 'divisie', 'paragraaf', 'afdeling', 'hoofdstuk', 'table', 'tabel', 'noot', 'tekst', 'plaatje', 'illustratie'}
CONTAINERS = {'boek', 'deel', 'titeldeel', 'hoofdstuk', 'afdeling', 'paragraaf', 'sub-paragraaf', 'subparagraaf', 'titel', 'circulaire.divisie'}
def norm(s): return re.sub(r'[ \t\u00a0]+', ' ', s)
def inline(e):
    parts = []
    def rec(x):
        if x.tag in SKIP: return
        if x.text: parts.append(x.text)
        for c in x:
            rec(c)
            if c.tail: parts.append(c.tail)
    rec(e)
    return re.sub(r'\s+', ' ', ''.join(parts)).strip()
def render(e):
    t = e.tag
    if t in SKIP: return []
    if t == 'kop':
        l, n, ti = kop_parts(e); h = ' '.join(x for x in (l, n) if x)
        return [(h + ('. ' + ti if ti else '')).strip()] if (h or ti) else []
    if t in ('al', 'considerans.al', 'wij', 'tussenkop', 'p', 'titel', 'naam', 'functie', 'plaats', 'datum', 'koning'):
        s = inline(e); return [s] if s else []
    if t == 'row':
        cells = [inline(c) for c in e if c.tag == 'entry']; s = ' | '.join(cells).strip(' |'); return [s] if s else []
    if t in ('lid', 'li'):
        nrtag = 'lidnr' if t == 'lid' else 'li.nr'; nr = e.find(nrtag); pre = (inline(nr) + (' ' if t == 'li' else '. ')) if nr is not None and inline(nr) else ''
        lines = []
        for c in e:
            if c.tag != nrtag: lines += render(c)
        if lines: lines[0] = pre + lines[0]
        elif pre: lines = [pre.strip()]
        return lines
    lines = []
    if e.text and e.text.strip(): lines.append(re.sub(r'\s+', ' ', e.text).strip())
    for c in e:
        lines += render(c)
        if c.tail and c.tail.strip(): lines.append(re.sub(r'\s+', ' ', c.tail).strip())
    return lines
def text_of(e): return '\n'.join(l for l in render(e) if l)
def kop_parts(k):
    g = lambda n: inline(k.find(n)) if k.find(n) is not None else ''
    return g('label'), g('nr'), g('titel')
def kop(e):
    k = e.find('kop')
    return kop_parts(k) if k is not None else ('', '', '')
def slug(s): return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')
def split_xml(raw, law_id, source_url, version=None):
    root = ET.fromstring(raw)
    w = root.find('wetgeving') if root.tag == 'toestand' else root
    if w is None: w = root
    rows, seen = [], {}
    used = set()
    def uid(base):
        n = seen.get(base, 0) + 1
        cand = base if n == 1 else f'{base}-{n}'
        while cand in used: n += 1; cand = f'{base}-{n}'
        seen[base] = n; used.add(cand); return cand
    EMITTED = set()
    def emit(e, rtype, path, idx):
        EMITTED.add(id(e))
        label, nr, titel = kop(e)
        if rtype == 'article':
            if e.tag == 'enig-artikel': label, nr = label or 'Enig artikel', nr or ''
            lab = label or 'Artikel'; base = f'{law_id}-art-{slug(nr) or ("enig" if e.tag == "enig-artikel" else "") or slug(lab) or idx}'
        elif rtype == 'annex':
            lab = label or 'Bijlage'; base = f'{law_id}-bijlage-{slug(nr) or idx}'
        else:
            lab = label or ''; base = f'{law_id}-div-{idx}'
            if not (lab or titel): titel = 'Tekst'
        head = ' '.join(x for x in (lab, nr) if x)
        title = ((head + (' ' if titel[:1] in ',:;(' else '. ') + titel) if (head and titel) else (head or titel or '')).strip()[:300]
        body = text_of(e)
        if not body.strip():  # image-only block (e.g. bijlage with only <plaatje>): reference the illustration(s) instead of an empty row
            ill = [i.get('naam') or i.get('id') or '' for i in e.iter('illustratie')]
            body = '\n'.join(f'[illustratie: {x}]' for x in ill) if ill else '[geen tekst in bron-XML]'
        rows.append(dict(law_id=law_id, id=uid(base), title=title, text=body, source_url=source_url,
                         document_number=head or None, article_number=nr or None, record_type=rtype,
                         metadata_json=json.dumps(dict(law_identifier=law_id, toestand=version, path=path,
                             status=e.get('status'), bwb_ng_variabel_deel=e.get('bwb-ng-variabel-deel'),
                             leden=len(e.findall('lid')),
                             metadata=dict(text_extraction=dict(source='official', backend='koop_bwb_toestand_xml'))), ensure_ascii=False)))
    counters = {'article': 0, 'annex': 0, 'section': 0}
    has_art = any(True for x in w.iter() if x.tag in ('artikel', 'enig-artikel'))
    has_div = any(True for x in w.iter() if x.tag in ('divisie', 'circulaire.divisie'))
    def walk(e, path):
        for c in e:
            if c.tag in SKIP: continue
            if c.tag in ('artikel', 'enig-artikel'):
                counters['article'] += 1; emit(c, 'article', path, counters['article'])
            elif c.tag == 'bijlage':
                counters['annex'] += 1; emit(c, 'annex', path, counters['annex'])
            elif c.tag in ('divisie', 'circulaire.divisie') and not has_art:
                counters['section'] += 1; emit(c, 'section', path, counters['section'])
            elif c.tag in ('tekst', 'regeling-tekst', 'circulaire-tekst') and not has_art and not has_div and e.tag in ('circulaire-tekst', 'circulaire', 'regeling', 'wet-besluit') and c.tag == 'tekst':
                counters['section'] += 1; emit(c, 'section', path, counters['section'])
            else:
                p = path
                if c.tag in CONTAINERS or c.tag == 'divisie':
                    l, n, t = kop(c); lab = ' '.join(x for x in (l, n) if x)
                    if lab or t: p = path + [(lab + (': ' + t if t else '')).strip()]
                walk(c, p)
    walk(w, [])
    # v2 gap fill (2026-10-03): operative text inside wettekst/regeling-tekst/circulaire-tekst not covered by any emitted
    # artikel/bijlage/divisie row (e.g. regeling-tekst/tekst, paragraaf-only beleidsregels, mixed artikel+tekst) becomes
    # 'section' rows, one per maximal uncovered subtree, so no operative text is lost. Headings (kop) are not emitted alone.
    def contains_emitted(e):
        return any(id(x) in EMITTED for x in e.iter())
    def gaps(e, path):
        for c in e:
            if c.tag in SKIP or c.tag in ('kop', 'meta-data') or id(c) in EMITTED: continue
            if contains_emitted(c):
                p = path
                if c.tag in CONTAINERS or c.tag == 'divisie':
                    l, n, t = kop(c); lab = ' '.join(x for x in (l, n) if x)
                    if lab or t: p = path + [(lab + (': ' + t if t else '')).strip()]
                gaps(c, p)
            elif text_of(c).strip():
                counters['section'] += 1; emit(c, 'section', path, counters['section'])
    for body in [x for x in w.iter() if x.tag in ('wettekst', 'regeling-tekst', 'circulaire-tekst')]:
        if id(body) in EMITTED: continue
        gaps(body, [])
    full = text_of(w)
    OPER = ('wettekst', 'regeling-tekst', 'circulaire-tekst', 'bijlage')
    def opsum(e):
        t = 0
        for c in e:
            if c.tag in SKIP: continue
            t += len(text_of(c)) if c.tag in OPER else opsum(c)
        return t
    oper = opsum(w)
    nota = sum(len(text_of(x)) for x in w.iter() if x.tag == 'nota-toelichting')
    return rows, dict(oper_chars=oper, nota_chars=nota, n_article=counters['article'], n_annex=counters['annex'], n_section=counters['section'],
                      full_chars=len(full), row_chars=sum(len(r['text']) for r in rows), soort=w.get('soort'))
def count_top_artikel(raw):
    """independent count: artikel elements with no artikel/bijlage ancestor"""
    root = ET.fromstring(raw); n = 0
    def rec(e, inside):
        nonlocal n
        for c in e:
            if c.tag in SKIP: continue
            if c.tag in ('artikel', 'enig-artikel') and not inside: n += 1; rec(c, True)
            else: rec(c, inside or c.tag in ('artikel', 'enig-artikel', 'bijlage'))
    rec(root, False); return n

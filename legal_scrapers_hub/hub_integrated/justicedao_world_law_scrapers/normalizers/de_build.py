#!/usr/bin/env python3
"""Build DE Landesrecht law/article rows from raw HTML (mirrors federal ipfs_germany_laws schema).
Usage: de_build.py [outdir] [LAND,...]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, re, json, gzip, time, datetime as dt
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString
import pyarrow as pa, pyarrow.parquet as pq
B = Path('{_CORPORA}/de_subnational'); RAW = B / 'raw'
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else B / 'build'; OUT.mkdir(parents=True, exist_ok=True)
LANDS = sys.argv[2].split(',') if len(sys.argv) > 2 else ['NW', 'SN', 'HB', 'BB']
TODAY = dt.date(2026, 10, 2)
LIC = {
 'NW': ('Ministerium des Innern des Landes Nordrhein-Westfalen', 'recht.nrw.de', 'https://recht.nrw.de/', 'recht_nrw'),
 'SN': ('Sächsische Staatskanzlei', 'revosax.sachsen.de (REVOSax)', 'https://www.revosax.sachsen.de/', 'revosax'),
 'HB': ('Freie Hansestadt Bremen', 'transparenz.bremen.de (Transparenzportal Bremen)', 'https://www.transparenz.bremen.de/vorschriften-72741', 'transparenzportal_bremen'),
 'BB': ('Land Brandenburg', 'bravors.brandenburg.de (BRAVORS)', 'https://bravors.brandenburg.de/', 'bravors'),
}
def license_str(land):
    pub, src, _, _ = LIC[land]
    s = f'Public domain (gemeinfrei): amtliche Werke i.S.d. § 5 Abs. 1 UrhG; {pub} / {src}'
    if land == 'HB': s += '; portal labels documents CC BY-NC-ND (see README Known limitations)'
    return s
SCHEMA_L = pa.schema([(n, pa.int64() if n == 'article_count' else pa.string()) for n in
    'id title text source_url source_type jurisdiction country language eli date date_issued retrieved_at license law_status identifier official_identifier article_count json_path metadata_json'.split()])
SCHEMA_A = pa.schema([(n, pa.string()) for n in 'law_id id title text source_url document_number article_number record_type metadata_json'.split()])
MON = {m: i + 1 for i, m in enumerate(['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'])}
MON['Jänner'] = 1
import html as _H
def norm(s): s = _H.unescape(s) if s and '&' in s else s; return re.sub(r'[ \t\u00a0\u2002\u2003\u2009\u202f]+', ' ', s or '').strip()
def ntext(s):
    s = _H.unescape(s) if s and '&' in s else s
    s = re.sub(r'[ \t\u00a0\u2002\u2003\u2009\u202f]+', ' ', s or ''); s = re.sub(r' *\n *', '\n', s); return re.sub(r'\n{3,}', '\n\n', s).strip()
def de_date(s):
    if not s: return None
    m = re.search(r'(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})', s)
    if m: return f'{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}'
    m = re.search(r'(\d{1,2})\.\s*(' + '|'.join(MON) + r')\s+(\d{4})', s)
    if m: return f'{int(m.group(3)):04d}-{MON[m.group(2)]:02d}-{int(m.group(1)):02d}'
    return None
def blocktext(el):
    """text of an element with paragraph breaks"""
    for br in el.find_all('br'): br.replace_with('\n')
    for b in el.find_all(['p', 'div', 'li', 'tr', 'dt', 'dd', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table']): b.insert_after('\n')
    return ntext(el.get_text(''))
ENBEZ = re.compile(r'^((?:§§?|Art\.?|Artikel|Anlage|Anhang|Nr\.)\s*[0-9IVXLC]+(?:\s?[a-z](?![a-zäöüß]))?(?:\s*(?:bis|und|-|–)\s*[0-9]+(?:\s?[a-z](?![a-zäöüß]))?)?|Anlage(?:\s+[0-9IVX]+[a-z]?)?|Anhang|Präambel|Eingangsformel|Schlussformel|Inhaltsübersicht|Inhaltsverzeichnis)\b')
def split_head(h):
    h = norm(h); m = ENBEZ.match(h)
    if not m: return None, h
    eb = re.sub(r'(\d)\s([a-z])\b', r'\1\2', norm(m.group(1)))
    return eb, norm(h[m.end():]).strip(' -–') or None
AMEND = re.compile(r'^(?:\S+\s+){0,3}(?:Gesetz|Verordnung|Landesverordnung|Ortsgesetz)\s+(?:zur|über die)\s+Änderung\b|^(?:\S+\s+)?(?:Änderungsgesetz|Änderungsverordnung)\b|^(?:\S+\s+){0,2}(?:Gesetz|Verordnung)\s+zur\s+Aufhebung\b', re.I)
def abbrev(title):
    m = re.search(r'\(([^()]{2,40})\)\s*$', title or '')
    if not m: return None
    a = m.group(1).split('–')[-1].split(' - ')[-1].strip()
    return a if len(a) <= 30 else None

class Law:
    def __init__(self, land, key, title, url, doctype, retrieved, raw_path):
        self.land, self.key, self.title, self.url, self.doctype, self.retrieved, self.raw_path = land, key, re.sub(r'\s+', ' ', title or '').strip(), url, doctype, retrieved, raw_path
        self.arts = []; self.seen = {}; self.date = None; self.identifier = key; self.abbr = abbrev(self.title); self.fundstelle = None; self.stand = []; self.extra = {}
    @property
    def id(self): return f'de-{self.land.lower()}-{self.key}'
    def add(self, enbez, title, text, doknr=None, gl=None, kind=None):
        text = ntext(text); base = kind or enbez or 'text'
        if kind == 'gl': base = 'gl:' + norm(title)[:120]
        n = self.seen.get(base, 0) + 1; self.seen[base] = n
        aid = f'{self.id}:{base}' + (f'#{n}' if n > 1 else '')
        ttl = norm(' '.join(x for x in [enbez, title] if x)) or (kind or None)
        self.arts.append(dict(law_id=self.id, id=aid, title=ttl, text=text, source_url=self.url, document_number=None, article_number=None, record_type='article',
            metadata_json=json.dumps({'doknr': doknr, 'enbez': enbez, 'titel': title if kind != 'gl' else None,
                                      'gliederungsbez': (gl or (None, None))[0], 'gliederungstitel': (gl or (None, None))[1]}, ensure_ascii=False)))
    def row(self):
        pub, src, home, stype = LIC[self.land]; lic = license_str(self.land)
        body = '\n\n'.join(a['text'] if not a['title'] or a['id'].endswith(':header') else f"{a['title']}\n{a['text']}".strip() for a in self.arts if a['text'] or a['title'])
        md = {'schema_version': 'collection_record.v1', 'record_type': 'law', 'law_identifier': self.abbr or self.identifier,
              'document_type': 'statute' if self.doctype == 'Gesetz' else 'regulation', 'is_current': True, 'canonical_law_url': self.url,
              'article_extraction_status': 'ok' if self.arts else 'empty',
              'metadata': {'license': lic, 'retrieved_at': self.retrieved, 'official_id': self.identifier, 'publisher': pub, 'source_name': src,
                           'abbreviation': self.abbr, 'amtliche_abkuerzung': self.abbr, 'slug': self.key, 'xml_url': None, 'builddate': None,
                           'fundstelle': self.fundstelle, 'standangabe': self.stand, 'toc_title': self.title, 'n_norms': len(self.arts),
                           'schema': 'collection_record.v1', 'collector': 'de_collect', 'parser': f'{stype}-html',
                           'rights': {'not_legal_advice': True, 'official_reuse_url': home, 'license': lic}}}
        return dict(id=self.id, title=self.title, text=(self.title + '\n' + body) if body else self.title, source_url=self.url, source_type=stype,
                    jurisdiction=f'DE-{self.land}', country='Germany', language='de', eli=None, date=self.date, date_issued=self.date,
                    retrieved_at=self.retrieved, license=lic, law_status='current', identifier=self.identifier, official_identifier=self.abbr,
                    article_count=len(self.arts), json_path=self.raw_path, metadata_json=json.dumps(md, ensure_ascii=False))

def load_index(land):
    idx = {}
    p = RAW / land / 'index.jsonl'
    if p.exists():
        for l in open(p):
            r = json.loads(l); idx[(r['kind'], r['key'])] = r
    return idx
def utc(ts):
    try: return dt.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S%z').astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception: return None

# ---------------- NW
def parse_nw(t, url):
    s = BeautifulSoup(t, 'lxml')
    info = {}
    for it in s.select('#block-rnrw-legal-document-info-box .info-box-item'):
        l = it.select_one('.field__label'); v = it.select_one('.field__item')
        if l and v: info[norm(l.get_text())] = norm(v.get_text())
    term = s.select_one('a[href*="/taxonomy/term/"]'); term = re.search(r'term/(\d+)', term['href']).group(1) if term else None
    h1 = s.select_one('h1'); title = norm(h1.get_text(' ')) if h1 else ''
    return s, info, term, title
def build_nw(emit, rep):
    idx = load_index('NW'); pages = {}
    for (kind, key), r in idx.items():
        if kind != 'law': continue
        f = RAW / 'NW' / 'law' / f'{key}.html.gz'
        if not f.exists(): continue
        t = gzip.decompress(f.read_bytes()).decode('utf-8', 'replace')
        s, info, term, title = parse_nw(t, r['final_url'])
        ab, bis = de_date(info.get('Gültig ab')), de_date(info.get('Gültig bis'))
        pages.setdefault(term or key, []).append((ab, bis, key, r, t))
    rep['NW_terms'] = len(pages)
    for term, lst in pages.items():
        cur = [p for p in lst if (p[0] is None or p[0] <= TODAY.isoformat()) and (p[1] is None or p[1] >= TODAY.isoformat())]
        if not cur:
            rep.setdefault('NW_excluded_not_in_force', 0); rep['NW_excluded_not_in_force'] += 1; continue
        ab, bis, key, r, t = sorted(cur, key=lambda p: p[0] or '')[-1]
        url = r['final_url'].rstrip('/'); typ = 'Gesetz' if '/lrgv/gesetz/' in url else 'Verordnung'
        s, info, tid, title = parse_nw(t, url)
        L = Law('NW', tid or key, title, url, typ, utc(r['ts']), str(RAW / 'NW' / 'law' / f'{key}.html.gz'))
        L.identifier = f'taxonomy/term/{tid}' if tid else key; L.date = de_date(info.get('Ausfertigungsdatum'))
        L.stand = [f"Fassung gültig ab {info.get('Gültig ab')}"] if info.get('Gültig ab') else []
        dl = s.select_one('a[href*="/system/files/BH/"]'); L.extra['bh'] = dl['href'] if dl else None
        gl = None; merge_to = None
        for i, sec in enumerate(s.select('section.legaldoc-article')):
            p = sec.select_one('div.paragraph'); doknr = p.get('id') if p else None
            num = sec.select_one('.field--field_num'); hl = sec.select_one('.field--field_headline')
            tx = sec.select_one('.field--field_text')
            trailing = []
            if tx:
                ps = tx.select('p')
                while ps and 'text-align-center' in (ps[-1].get('class') or []):
                    trailing.insert(0, blocktext(ps[-1])); ps[-1].decompose(); ps.pop()
                for fn in tx.select('.footnote-container'): fn.decompose()
            text = blocktext(tx) if tx else ''
            numt = norm(num.get_text(' ')) if num else None; hlt = norm(hl.get_text(' ')) if hl else None
            if not numt and not hlt:
                if i == 0: L.add(None, None, text, doknr, kind='header')
                elif merge_to is not None and text:  # recht.nrw.de sometimes splits a norm into a heading-only section + unlabelled text section(s)
                    L.arts[merge_to]['text'] = ntext((L.arts[merge_to]['text'] + '\n\n' + text).strip()); L.extra['merged_text_sections'] = L.extra.get('merged_text_sections', 0) + 1
                elif text: L.add(None, None, text, doknr, gl=gl, kind='text')
            else:
                eb, rest = split_head(numt or hlt)
                if numt and not eb: eb = numt
                L.add(eb, hlt if numt else rest, text, doknr, gl=gl); merge_to = len(L.arts) - 1 if not text else None
            if trailing: merge_to = None
            for tr in trailing:
                parts = tr.split('\n', 1); gl = (parts[0], parts[1] if len(parts) > 1 else None)
                L.add(None, tr.replace('\n', ' '), '', None, kind='gl')
        emit(L)

# ---------------- SN
def build_sn(emit, rep):
    idx = load_index('SN')
    for (kind, key), r in idx.items():
        if kind != 'law': continue
        f = RAW / 'SN' / 'law' / f'{key}.html.gz'
        t = gzip.decompress(f.read_bytes()).decode('utf-8', 'replace'); s = BeautifulSoup(t, 'lxml')
        desc = (s.find('meta', attrs={'name': 'description'}) or {}).get('content', '')
        m = re.match(r'Sächsisches Landesrecht ([^:]+):\s*(.*)$', desc or '', re.S); typ = m.group(1).strip() if m else '?'; full = re.sub(r'\s+', ' ', m.group(2)).strip() if m else ''
        if typ == 'Zustimmungsgesetz': typ = 'Gesetz'
        h1 = norm(s.select_one('h1').get_text(' ')) if s.select_one('h1') else full
        gz = s.find(string=re.compile(r'Fassung gültig')); gtxt = norm(gz.parent.get_text(' ')) if gz else ''
        if typ not in ('Gesetz', 'Verordnung'):
            rep.setdefault('SN_excluded_doctype', {}); rep['SN_excluded_doctype'][typ] = rep['SN_excluded_doctype'].get(typ, 0) + 1; continue
        if re.search(r'gültig bis', gtxt):
            bis = de_date(gtxt.split('bis', 1)[1])
            if bis and bis < TODAY.isoformat(): rep['SN_excluded_not_in_force'] = rep.get('SN_excluded_not_in_force', 0) + 1; continue
        title = full or h1
        if AMEND.search(h1) or AMEND.search(title):
            rep['SN_excluded_amending'] = rep.get('SN_excluded_amending', 0) + 1; continue
        url = r['final_url']
        L = Law('SN', key, title, url, typ, utc(r['ts']), str(f)); L.identifier = f'revosax:{key}'
        L.abbr = abbrev(norm((s.select_one('article#lesetext header') or s).get_text(' '))[:400].split(' Vom ')[0]) or (h1 if len(h1) <= 30 else None)
        fs = s.find('h3', string=re.compile('Fundstelle')); 
        if fs: L.fundstelle = {'typ': 'amtlich', 'periodikum': 'SächsGVBl', 'zitstelle': norm(fs.find_next('p').get_text(' '))}
        L.stand = [gtxt] if gtxt else []
        art = s.select_one('article#lesetext')
        if art is None: rep.setdefault('SN_no_lesetext', []).append(key); emit(L); continue
        for sup in art.select('sup.satzzahl'): sup.decompose()
        for a in art.select('a.fn, sup.fn, a[href^="#FNID"]'): a.decompose()
        hdr = art.find('header')
        if hdr:
            ht = blocktext(hdr); L.date = de_date((re.search(r'Vom\s+\d{1,2}\.\s*\S+\s+\d{4}', ht) or [None])[0]) if re.search(r'Vom\s+\d', ht) else None
            L.add(None, None, ht, None, kind='header')
        gl = None
        for sec in art.select('div.sections section'):
            for sub in sec.find_all('section'): sub.extract()
            st = norm(sec.get('title') or ''); hd = sec.find(['h3', 'h4', 'h5'])
            if st in ('Gesetz', 'Verordnung') and sec.get('data-level') == '1' and not sec.get('id', '').startswith('p'):
                rb = sec.select_one('.rechtsbereinigt'); L.stand.append(norm(rb.get_text(' ')) if rb else ''); continue
            if hd: hd.extract()
            body = blocktext(sec)
            eb, rest = split_head(st)
            if eb: L.add(eb, rest, body, sec.get('id'), gl=gl)
            elif not body.strip():
                gp = re.match(r'^((?:Teil|Kapitel|Abschnitt|Unterabschnitt|Titel|Buch)\s+\S+)\s*(.*)$', st); gl = (gp.group(1), gp.group(2) or None) if gp else (st, None)
                L.add(None, st, '', sec.get('id'), kind='gl')
            else: L.add(None, st or None, body, sec.get('id'), gl=gl, kind=None if st else 'text') if st else L.add(None, None, body, sec.get('id'), gl=gl, kind='text')
        emit(L)

# ---------------- HB
def build_hb(emit, rep):
    idx = load_index('HB')
    for (kind, key), r in idx.items():
        if kind != 'law': continue
        f = RAW / 'HB' / 'law' / f'{key}.html.gz'
        t = gzip.decompress(f.read_bytes()).decode('utf-8', 'replace'); s = BeautifulSoup(t, 'lxml')
        hd = {}
        for row in s.select('table.TableRahmenkpl tr'):
            tds = row.find_all('td', recursive=False)
            if len(tds) == 2 and tds[0].find('strong'): hd.setdefault(norm(tds[0].get_text(' ')).rstrip(':').strip(), norm(tds[1].get_text(' ')))
        dts = [norm(x.find_next_sibling('td').get_text(' ')) for x in s.select('td.TD30') if 'Dokumenttyp' in x.get_text() and x.find_next_sibling('td')]
        dtype = next((d for d in dts if d and d != 'Gesetze und Rechtsverordnungen'), '')
        if re.search(r'gesetz', dtype, re.I): typ = 'Gesetz'
        elif re.search(r'verordnung', dtype, re.I): typ = 'Verordnung'
        else: rep.setdefault('HB_excluded_doctype', {}); rep['HB_excluded_doctype'][dtype or '?'] = rep['HB_excluded_doctype'].get(dtype or '?', 0) + 1; continue
        if hd.get('Gültig bis') and (de_date(hd['Gültig bis']) or '9999') < TODAY.isoformat(): rep['HB_excluded_not_in_force'] = rep.get('HB_excluded_not_in_force', 0) + 1; continue
        tt = s.select_one('.docLayoutTitel'); title = norm(blocktext(tt).replace('\n', ' ')) if tt else norm(s.title.get_text())
        title = re.sub(r'\s+Vom\s+\d{1,2}\.\s*\S+\s+\d{4}\s*$', '', title)
        if AMEND.search(title): rep['HB_excluded_amending'] = rep.get('HB_excluded_amending', 0) + 1; continue
        first = s.select_one('div.jgwsAiZDoc'); doknr = re.sub(r'^jgwsAiZDoc-jlr-', '', first['id']) if first else None
        L = Law('HB', (doknr or key).lower(), title, r['final_url'], typ, utc(r['ts']), str(f)); L.identifier = doknr or key
        L.abbr = hd.get('juris-Abkürzung'); L.date = de_date(hd.get('Ausfertigungsdatum'))
        if hd.get('Fundstelle'): L.fundstelle = {'typ': 'amtlich', 'periodikum': hd['Fundstelle'].split(' ')[0], 'zitstelle': hd['Fundstelle']}
        L.extra['dokumenttyp'] = dtype
        gl = None
        for i, d in enumerate(s.select('div.jgwsAiZDoc')):
            did = re.sub(r'^jgwsAiZDoc-jlr-', '', d.get('id', ''))
            st = d.select_one('table.standangaben')
            if st:
                L.stand.append(norm(st.get_text(' '))); L.add(None, None, blocktext(st), did, kind='header'); continue
            h = d.find(['h2', 'h3', 'h4', 'h5'])
            head = blocktext(h) if h else ''
            if h: h.extract()
            body = blocktext(d)
            if head:
                first_line = head.split('\n')[0]; rest = norm(' '.join(head.split('\n')[1:])) or None
                eb, r2 = split_head(first_line)
                if eb: L.add(eb, rest or r2, body, did, gl=gl)
                elif not body: gl = (first_line, rest); L.add(None, head.replace('\n', ' '), '', did, kind='gl')
                else: L.add(None, head.replace('\n', ' '), body, did, gl=gl, kind='text')
            else: L.add(None, 'Eingangsformel' if i <= 1 else None, body, did, gl=gl, kind='Eingangsformel' if i <= 1 else 'text')
        emit(L)

# ---------------- BB
def build_bb(emit, rep):
    idx = load_index('BB')
    for (kind, key), r in idx.items():
        if kind != 'law': continue
        f = RAW / 'BB' / 'law' / f'{key}.html.gz'
        t = gzip.decompress(f.read_bytes()).decode('utf-8', 'replace'); s = BeautifulSoup(t, 'lxml')
        typ = 'Gesetz' if key.startswith('gesetze__') else 'Verordnung'
        kopf = s.select_one('.reiterbox_innen_kopf'); ktxt = blocktext(kopf) if kopf else ''
        h1 = s.find('h1'); title = norm(h1.get_text(' ')) if h1 else ''
        if not title or 'Vorschriftensystem' in title: title = ktxt.split('\n')[0] if ktxt else key
        if re.search(r'außer Kraft getreten|aufgehoben durch', ktxt[:600], re.I): rep['BB_excluded_not_in_force'] = rep.get('BB_excluded_not_in_force', 0) + 1; continue
        if AMEND.search(title): rep['BB_excluded_amending'] = rep.get('BB_excluded_amending', 0) + 1; continue
        slug = key.split('__', 1)[1]
        L = Law('BB', slug.lower().replace('_', '-'), title, r['final_url'], typ, utc(r['ts']), str(f)); L.identifier = f'bravors:{key.replace("__", "/")}'
        m = re.search(r'vom\s+(\d{1,2}\.\s*\S+\s+\d{4})', ktxt); L.date = de_date(m.group(1)) if m else None
        m = re.search(r'\(\s*(GVBl\.[^)]*)\)', ktxt)
        if m: L.fundstelle = {'typ': 'amtlich', 'periodikum': 'GVBl. Bbg', 'zitstelle': norm(m.group(1))}
        L.stand = [norm(x) for x in re.findall(r'zuletzt geändert durch[^\n]*', ktxt)][:1]
        box = s.select_one('.reiterbox_innen_text')
        if box is None: emit(L); continue
        nodes = [n for n in box.children if not (isinstance(n, NavigableString) and not n.strip())]
        heads = [n for n in nodes if getattr(n, 'name', None) in ('h2', 'h3', 'h4', 'h5', 'h6')]
        def is_norm(n):
            if 'Inhalts' in n.get_text()[:40]: return False
            return bool(n.find('a', attrs={'name': True}) or n.select_one('.paragraph_bez') or split_head(blocktext(__import__('copy').copy(n)).split('\n')[0])[0])
        anch = [n for n in heads if is_norm(n)]
        first_anch = nodes.index(anch[0]) if anch else len(nodes)
        pre = nodes[:first_anch]; last_toc = max([i for i, n in enumerate(pre) if getattr(n, 'name', None) == 'p' and n.find('a', href=re.compile('^#'))] or [-1])
        toc_start = next((i for i, n in enumerate(pre) if getattr(n, 'name', None) in ('h2', 'h3') and 'Inhalts' in n.get_text()), None)
        header_nodes = pre[:toc_start] if toc_start is not None else pre[:max(last_toc + 1, 0)] if last_toc >= 0 else []
        htxt = '\n'.join(x for x in [ktxt] + [blocktext(n) if hasattr(n, 'get_text') else ntext(str(n)) for n in header_nodes] if x)
        L.add(None, None, htxt, None, kind='header')
        if toc_start is not None and last_toc >= toc_start:
            L.add('Inhaltsübersicht', None, '\n'.join(blocktext(n) if hasattr(n, 'get_text') else ntext(str(n)) for n in pre[toc_start + 1:last_toc + 1]), None)
        gl = None; rest = pre[(last_toc + 1) if last_toc >= 0 else (len(header_nodes)):]
        cur = None; buf = []
        def flush():
            if cur is not None: L.add(cur[0], cur[1], '\n'.join(buf), cur[2], gl=cur[3])
        for n in rest + nodes[first_anch:]:
            nm = getattr(n, 'name', None)
            if nm in ('h2', 'h3', 'h4', 'h5', 'h6'):
                a = n.find('a', attrs={'name': True}); isn = is_norm(n); ht = blocktext(n)
                if isn:
                    flush(); buf = []; fl = ht.split('\n')[0]; eb, r2 = split_head(fl)
                    cur = (eb or fl, norm(' '.join(ht.split('\n')[1:])) or r2, a.get('name') if a else None, gl); continue
                if cur is not None and not ht.strip(): continue
                flush(); cur = None; buf = []; parts = ht.split('\n', 1); gl = (parts[0], norm(parts[1]) if len(parts) > 1 else None)
                L.add(None, ht.replace('\n', ' '), '', None, kind='gl'); continue
            txt = blocktext(n) if hasattr(n, 'get_text') else ntext(str(n))
            if not txt: continue
            if cur is None: L.add(None, None, txt, None, gl=gl, kind='text')
            else: buf.append(txt)
        flush()
        emit(L)

def main():
    laws, arts, rep = [], [], {'built_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    def emit(L):
        if not L.arts or not any(a['text'] for a in L.arts):
            rep.setdefault(f'{L.land}_excluded_no_text_on_portal', []).append({'id': L.id, 'title': L.title, 'url': L.url}); return
        laws.append(L.row()); arts.extend(L.arts)
    for land in LANDS:
        n0 = len(laws); {'NW': build_nw, 'SN': build_sn, 'HB': build_hb, 'BB': build_bb}[land](emit, rep)
        rep[f'{land}_laws'] = len(laws) - n0; print(land, 'laws', len(laws) - n0, flush=True)
    pq.write_table(pa.Table.from_pylist(laws, schema=SCHEMA_L), OUT / 'laws.parquet', compression='zstd')
    pq.write_table(pa.Table.from_pylist(arts, schema=SCHEMA_A), OUT / 'articles.parquet', compression='zstd')
    rep['laws'] = len(laws); rep['articles'] = len(arts)
    json.dump(rep, open(OUT / 'build_report.json', 'w'), indent=1, ensure_ascii=False); print(json.dumps(rep, ensure_ascii=False)[:3000])
if __name__ == '__main__': main()

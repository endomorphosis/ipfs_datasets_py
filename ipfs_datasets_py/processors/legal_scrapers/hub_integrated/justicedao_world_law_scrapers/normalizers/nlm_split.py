#!/usr/bin/env python3
"""Split a KOOP CVDR regeling XML (repository.officiele-overheidspublicaties.nl/cvdr/...) into hub article rows.
Reuses the NL national splitter (nl_split.split_xml v2 with gap fill) after normalising CVDR XML to the BWB tag dialect:
  - XML namespaces stripped (cvdr/terms, dcterms, overheid, overheidrg ...)
  - <meta> (owmskern/owmsmantel/cvdripm) removed from the text tree (parsed separately by parse_meta)
  - <li nr="1."> attributes become <li.nr>1.</li.nr> children so list numbering is rendered like BWB
Row schema: law_id, id, title, text, source_url, document_number, article_number, record_type, metadata_json.
IDs: <law_id>-art-<nr> | <law_id>-bijlage-<n> | <law_id>-div-<n> (duplicates -2, -3 in document order), law_id = CVDR work id (e.g. CVDR712517)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, json, re, xml.etree.ElementTree as ET
sys.path.insert(0, '/workspace/scripts'); import nl_split
from lxml import etree as LET
NS = {'c': 'http://standaarden.overheid.nl/cvdr/terms/', 'dcterms': 'http://purl.org/dc/terms/', 'overheid': 'http://standaarden.overheid.nl/owms/terms/',
      'overheidrg': 'http://standaarden.overheid.nl/cvdr/meta/'}
_LEAD = re.compile(r'(?m)^\. ')
def _local(t): return t.split('}', 1)[1] if isinstance(t, str) and '}' in t else t
def normalise(raw):
    root = ET.fromstring(raw)
    for e in root.iter():
        e.tag = _local(e.tag)
    for m in [x for x in root if x.tag == 'meta']: root.remove(m)
    # DROP besluit templates carry an empty placeholder <artikel> (no text apart from an empty kop); drop it
    def _txt(e, skip_kop_label=True):
        out = []
        for x in e.iter():
            if x.tag == 'label' and skip_kop_label: continue
            if x.text: out.append(x.text)
            if x.tail and x is not e: out.append(x.tail)
        return ''.join(out).strip()
    parent = {c: p for p in root.iter() for c in p}
    for a in [x for x in root.iter() if x.tag in ('artikel', 'enig-artikel', 'bijlage')]:  # empty placeholder artikel / bijlage (no text, no illustratie)
        if a in parent and not _txt(a) and not any(True for _ in a.iter('illustratie')): parent[a].remove(a)
    # operative text only in the aanhef (besluit: ...) and regeling-tekst empty -> aanhef becomes a section (divisie) of regeling-tekst
    for reg in root.iter('regeling'):
        rt, ah = reg.find('regeling-tekst'), reg.find('aanhef')
        if ah is not None and _txt(ah) and (rt is None or not _txt(rt)):
            if rt is None: rt = ET.SubElement(reg, 'regeling-tekst')
            for c in list(rt): rt.remove(c)
            d = ET.SubElement(rt, 'divisie'); k = ET.SubElement(d, 'kop'); t = ET.SubElement(k, 'titel'); t.text = 'Aanhef en besluit'
            for c in list(ah): d.append(c)
            reg.remove(ah)
    for li in root.iter('li'):
        nr = li.get('nr')
        if nr and li.find('li.nr') is None:
            n = ET.Element('li.nr'); n.text = nr; li.insert(0, n)
    return root
def parse_meta(raw):
    r = LET.fromstring(raw); m = r.find('c:meta', NS)
    def t(path):
        x = m.find(path, NS) if m is not None else None
        return (x.text or '').strip() if x is not None and x.text else None
    def ta(path, attr):
        x = m.find(path, NS) if m is not None else None
        return x.get(attr) if x is not None else None
    cr = m.find('.//dcterms:creator', NS) if m is not None else None
    types = {(x.get('scheme') or ''): (x.text or '').strip() for x in m.findall('.//dcterms:type', NS)} if m is not None else {}
    return dict(identifier=t('.//dcterms:identifier'), title=t('.//dcterms:title'), alternative=t('.//dcterms:alternative'),
                language=t('.//dcterms:language'), creator_scheme=(cr.get('scheme') or '').split(':')[-1] if cr is not None else None,
                creator=(cr.text or '').strip() if cr is not None and cr.text else None,
                informatietype=types.get('overheid:Informatietype'), rubriek=types.get('overheidop:Rubriek'),
                modified=t('.//dcterms:modified'), issued=t('.//dcterms:issued'), subject=t('.//dcterms:subject'),
                ratified_by=t('.//overheid:isRatifiedBy'), ratified_by_scheme=ta('.//overheid:isRatifiedBy', 'scheme'),
                is_format_of=t('.//dcterms:isFormatOf'), is_format_of_url=ta('.//dcterms:isFormatOf', 'resourceIdentifier'),
                rights=re.sub(r'\s+', ' ', t('.//dcterms:rights') or '') or None,
                inwerkingtreding=t('.//overheidrg:inwerkingtredingDatum'), uitwerkingtreding=t('.//overheidrg:uitwerkingtredingDatum'),
                terugwerkendekracht=t('.//overheidrg:terugwerkendekrachtDatum'), betreft=t('.//overheidrg:betreft'),
                kenmerk=t('.//overheidrg:kenmerk'), onderwerp=t('.//overheidrg:onderwerp'),
                externe_bijlagen=[dict(id=x.get('resourceIdentifier'), title=(x.text or '').strip()) for x in m.findall('.//overheidrg:externeBijlage', NS)] if m is not None else [])
def split_cvdr(raw, law_id, source_url, version):
    root = normalise(raw)
    rows, st = nl_split.split_xml(ET.tostring(root, encoding='utf-8'), law_id, source_url, version)
    for r in rows:
        r['text'] = _LEAD.sub('', r['text'])  # kop with titel but no label/nr renders as '. Titel' in nl_split -> 'Titel'
        md = json.loads(r['metadata_json']); md.pop('bwb_ng_variabel_deel', None); md['expression'] = md.pop('toestand', version)
        md['metadata'] = dict(text_extraction=dict(source='official', backend='koop_cvdr_xml'))
        r['metadata_json'] = json.dumps(md, ensure_ascii=False)
    body = root.find('body'); full = _LEAD.sub('', nl_split.text_of(body if body is not None else root))
    st['toelichting_chars'] = sum(len(nl_split.text_of(x)) for x in root.iter('toelichting'))
    return rows, st, full
def independent_counts(raw):
    """Independent (lxml XPath on the raw namespaced XML) counts:
    n_artikel = top-level artikel (no artikel/bijlage/meta ancestor) with some text besides the kop label (empty DROP placeholders excluded);
    n_bijlage = bijlage with no bijlage/artikel ancestor;
    oper_chars_nows = non-whitespace chars of regeling-tekst + those bijlagen, minus container headings (hoofdstuk/paragraaf/... kop, kept in
    metadata path); if regeling-tekst has no text, the aanhef counts as operative text."""
    r = LET.fromstring(raw); L = lambda n: f'local-name()="{n}"'
    def nows(nodes): return sum(len(re.sub(r'\s+', '', ''.join(x.itertext()))) for x in nodes)
    arts = r.xpath(f'//*[{L("artikel")} or {L("enig-artikel")}][not(ancestor::*[{L("artikel")} or {L("enig-artikel")} or {L("bijlage")} or {L("meta")}])]')
    art = [a for a in arts if re.sub(r'\s+', '', ''.join(t for t in a.xpath('.//text()[not(parent::*[' + L('label') + '])]'))) or a.xpath(f'.//*[{L("illustratie")}]')]
    bij = [b for b in r.xpath(f'//*[{L("bijlage")}][not(ancestor::*[{L("bijlage")} or {L("artikel")} or {L("meta")}])]')
           if re.sub(r'\s+', '', ''.join(b.xpath('.//text()[not(parent::*[' + L('label') + '])]'))) or b.xpath(f'.//*[{L("illustratie")}]')]
    rt = r.xpath(f'//*[{L("regeling-tekst")}]')
    heads = r.xpath(f'//*[{L("regeling-tekst")}]//*[{L("kop")}][not(parent::*[{L("artikel")} or {L("enig-artikel")} or {L("bijlage")}])]')
    op = nows(rt) - nows(heads)
    if op <= 0: op = nows(r.xpath(f'//*[{L("aanhef")}]'))
    # operative word bag (for a duplicate-proof coverage measure): regeling-tekst (or aanhef if regeling-tekst is empty) + bijlagen, minus container headings
    from collections import Counter
    W = lambda t: Counter(re.findall(r'\w+', t.lower()))
    bag = Counter()
    for x in (rt if nows(rt) - nows(heads) > 0 else r.xpath(f'//*[{L("aanhef")}]')) + bij: bag += W(' '.join(x.itertext()))
    for h in (heads if nows(rt) - nows(heads) > 0 else []): bag -= W(' '.join(h.itertext()))
    return dict(n_artikel=len(art), n_bijlage=len(bij), oper_chars_nows=max(0, op) + nows(bij), oper_words=bag)
def word_coverage(rows, ind):
    from collections import Counter
    rb = Counter()
    for x in rows: rb.update(re.findall(r'\w+', x['text'].lower()))
    tot = sum(ind['oper_words'].values())
    return (sum(min(c, rb[w]) for w, c in ind['oper_words'].items()) / tot) if tot else (1.0 if rows else 0.0)

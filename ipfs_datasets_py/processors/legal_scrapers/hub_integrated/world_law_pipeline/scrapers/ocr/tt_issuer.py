"""Issuer keying for pravo.tatarstan.ru docs: Republic acts -> iso:RU-TA; municipal acts -> wd:Q of the issuing
settlement/district/okrug, matched against the sasia_ru lane's Wikidata cache (_ru/wd_ru.jsonl, OKTMO 92* = Tatarstan)
using the lane matcher's rules (ru_gw_match.py: all name stems present, compatible level word, unique candidate)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, re, collections
D = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/')
LEVELS = [('rural_settlement', r'сельск\w*\s+поселени|сельсовет'), ('urban_settlement', r'городск\w*\s+поселени'),
          ('urban_okrug', r'городск\w*\s+округ'), ('district', r'муниципальн\w*\s+район|\bрайон\w*')]
GEN = {'городской','округ','город','поселение','сельское','городское','муниципальный','район','муниципальное','образование',
       'муниципального','образования','округа','района','поселения','сельский','совет','сельсовет','республики','республика','татарстан'}
def stem(w):
    w = w.lower().replace('ё', 'е')
    for suf in ('ского','скому','ский','ская','ское','ской','цкого','цкий','цкое','ого','ий','ая','ое','ой','ый','а','я','о','ы','и','ь'):
        if w.endswith(suf) and len(w) - len(suf) >= 4: return w[:-len(suf)]
    return w
def name_words(label):
    ws = [w.strip('«»"()., ') for w in re.split(r'\s+', label or '')]
    return [w for w in ws if w and w.lower() not in GEN and len(w) >= 3]
def level_of(s): return [k for k, p in LEVELS if re.search(p, s.lower())]
TT = [p for p in map(json.loads, open(D + 'wd_ru.jsonl')) if any(o.startswith('92') for o in p.get('oktmo') or [])]
IDX = collections.defaultdict(list)
for p in TT:
    for w in name_words(p.get('ru'))[:2]: IDX[stem(w)].append(p)
REPUBLIC = re.compile(r'кабинет\s+министров|президент\w*\s+республики|государственн\w*\s+совет\w*\s+республики|'
                      r'министерств\w*\s+[а-я ]{0,40}республики\s+татарстан|^\s*закон\s*$|закон\s+республики\s+татарстан|'
                      r'государственн\w*\s+комитет\w*\s+республики', re.I | re.M)
MUNI = re.compile(r'сельск\w*\s+поселени|городск\w*\s+поселени|муниципальн\w*\s+район|городск\w*\s+округ|исполнительн\w*\s+комитет|'
                  r'совет\w*\s+[а-яё\-]+ского|глав\w*\s+[а-яё\-]+ского', re.I)
REPUBLIC = re.compile(REPUBLIC.pattern + r'|раис\w*\s+республики|республики\s+татарстан\s+боерыг', re.I | re.M)
SETTLE = re.compile(r'([а-я\-]{4,})(?:ского|ского\W)?\W{0,40}?(?:\b[а-я\-]{4,}\b\W{0,5}){0,2}?(?:сельск\w*|городск\w*)\s+поселени', re.I)
PGT = re.compile(r'(?:поселок|посёлок)\s+городского\s+типа\W{0,3}([а-я\-]{4,})', re.I)
DISTRICT = re.compile(r'([а-я\-]{4,}ского)\W+муниципальн\w*\s+район', re.I)
SETTLE_LV = {'rural_settlement', 'urban_settlement'}
def _settle_by_stem(w):
    st = stem(w)
    return {p['qid']: p for p in IDX.get(st, []) if set(level_of(p['ru'])) & SETTLE_LV or 'поселение' in p['ru'].lower()}
DIST = {stem(d['ru'].split()[0]): d for d in json.load(open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/ocr/tt_districts.json')))}   # Wikidata: P31 Q2198484, OKTMO 926xx000
def issuer(text):
    """-> (place_id or None, reason). Settlement > (district: hold, not in codes) > Republic."""
    ls = [l for l in text.splitlines() if l.strip()][:30]
    cut = next((i for i, l in enumerate(ls) if re.search(r'^\W*(постановлени|решени|распоряжени|приказ|закон\b|карар|боерык)', l.strip(), re.I)), None)
    head = "\n".join(ls[:cut + 1] if cut is not None and cut >= 1 else ls[:8]).replace('ё', 'е').lower()   # issuer block only
    hits = []                                   # (pos, qid, name)
    for m in re.finditer(r'(?:сель\w*|городск\w*)\s+(?:[а-яэ]+\s+){0,4}?поселени', head):
        prev = re.findall(r'[а-я\-]{4,}', head[max(0, m.start() - 120):m.start()])[::-1][:8]
        for w in prev:
            c = _settle_by_stem(w)
            if len(c) == 1:
                q, p = next(iter(c.items())); hits.append((m.start(), q, p['ru'])); break
    for m in PGT.finditer(head):
        c = {p['qid']: p for p in TT if stem(m.group(1)) in p['ru'].lower().replace('ё', 'е') and 'поселени' in p['ru'].lower()}
        if len(c) == 1: q, p = next(iter(c.items())); hits.append((m.start(1), q, p['ru']))
    if hits:
        hits.sort(); return "wd:" + hits[0][1], "settlement:" + hits[0][2]
    for m in re.finditer(r'\bгород\w*\s+([а-я\-]{4,}(?:\s+[а-я\-]{4,})?)', head):     # city (urban okrug) bodies
        nm = m.group(1)
        c = {p['qid']: p for p in TT if 'округ' in p['ru'].lower() and all(stem(w) in p['ru'].lower().replace('ё', 'е') for w in nm.split())}
        if len(c) == 1: q, p = next(iter(c.items())); return "wd:" + q, "city:" + p['ru']
    for m in re.finditer(r'(?:муниципальн\w*\s+ра\w*|районн\w*\s+совет)', head):   # municipal district bodies
        if re.match(r'районн', m.group(0)):
            prev = re.findall(r'[а-я\-]{4,}', head[max(0, m.start() - 40):m.start()])[::-1][:1]
        else:
            prev = re.findall(r'[а-я\-]{4,}', head[max(0, m.start() - 80):m.start()])[::-1][:4]
        for w in prev:
            c = DIST.get(stem(w))
            if c: return "wd:" + c['qid'], "district:" + c['ru'] + " (муниципальный район)"
    if re.search(r'муниципальн\w*\s+ра\w*н|районн\w*\s+совет', head): return None, "district_unidentified"
    if re.search(r'исполнительн\w*\s+комитет|сельск\w*\s+поселени|городск\w*\s+поселени|городск\w*\s+округ', head): return None, "muni_unmatched"
    if REPUBLIC.search(head): return "iso:RU-TA", "republic"
    return None, "nomatch"

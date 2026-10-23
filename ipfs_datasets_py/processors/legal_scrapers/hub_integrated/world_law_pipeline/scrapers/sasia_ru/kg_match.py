"""Map cbd.minjust.gov.kg local organs (keneshes/mayoralties) to Wikidata places. Unique-match only."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, json, re, collections
D = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_kg')
def stem(w):
    w = w.lower().replace('ё', 'е').replace('аильн', 'айыльн').strip(' -"«»')
    w = re.sub(r'(ского|ский|ское|ской|ского|ского|ского|ского)$', '', w)
    w = re.sub(r'(инск|ынск|енск|овск|евск|ск|ого|ий|ая|ое|ый)$', '', w)
    return re.sub(r'[^а-яa-zөүң-]', '', w)
def wd_places():
    P = collections.defaultdict(lambda: {'d': set()})
    for r in csv.DictReader(open(D + '/kg_wd.csv')):
        q = 'wd:' + r['item'].rsplit('/', 1)[1]; t = r['type'].rsplit('/', 1)[1]
        kind = {'Q20733617': 'aimak', 'Q4389100': 'district', 'Q515': 'city'}.get(t, 'city')
        name = re.sub(r'\b(айыл(ный|ьный)? аймак|айылный округ|сельский округ|аильный округ|район|город)\b', '', (r['ru'] or ''), flags=re.I).strip()
        P[q].update(qid=q, kind=kind, ru=r['ru'], key=stem(name.split()[0]) if name else '')
        if r['dru']: P[q]['d'].add(stem(r['dru'].split()[0]))
    return list(P.values())
def parse(org):
    o = org.replace('ё', 'е')
    m = re.search(r'(\S+)\s+(?:айыл\w*|аил\w*)\s+аймак\w*(?:\s+(\S+)\s+район\w*)?', o, re.I)
    if m: return 'aimak', stem(m.group(1)), stem(m.group(2)) if m.group(2) else None
    m = re.search(r'(?:город\w*\s+кенеш\w*\s+(?:города\s+)?(\S+))|(?:(\S+)\s+город\w*\s+кенеш)|(?:Мэрия города\s+(\S+))', o, re.I)
    if m: return 'city', stem(next(g for g in m.groups() if g)), None
    m = re.search(r'(\S+)\s+район\w*\s+кенеш', o, re.I)
    if m: return 'district', stem(m.group(1)), None
    return None, None, None
if __name__ == '__main__':
    P = wd_places(); O = json.load(open(D + '/kg_local_organs.json'))
    out, stat = [], collections.Counter()
    for o in O:
        kind, k, d = parse(o['name'])
        if not kind: stat['unparsed'] += 1; continue
        c = [p for p in P if p['kind'] == kind and p['key'] and p['key'] == k]
        if kind == 'aimak' and d and len(c) > 1: c = [p for p in c if d in p['d']]
        if len(c) != 1: stat[f'{kind}_{"none" if not c else "multi"}'] += 1; continue
        stat[f'{kind}_ok'] += 1; out.append({'organ': o['name'], 'code': o['code'], 'qid': c[0]['qid'], 'place_ru': c[0]['ru'], 'kind': kind})
    by = collections.defaultdict(list)
    for x in out: by[x['qid']].append(x)
    with open(D + '/kg_organ_map.jsonl', 'w') as f:
        for x in out: f.write(json.dumps(x, ensure_ascii=False) + '\n')
    print(stat, 'places', len(by))

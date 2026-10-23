"""Parse cbd.minjust.gov.kg local organ names (aiyl keneshes) -> proposed aiyl aimak rows for the Normalizer.
Writes /workspace/world_law/codes/proposed/KG_aiyl_aimaks.csv. Never edits codes/place_additions.csv.
wikidata_id only when a UNIQUE aiyl-aimak item matches name stem (and district when given)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, json, re, sys, collections
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/sasia_ru'))
from kg_match import stem
D = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_kg'); OUT = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/codes/proposed/KG_aiyl_aimaks.csv')
AK = r'(?:айыл\w*|аил\w*|айыльн\w*)'
def parse(n):
    o = re.sub(r'\s+', ' ', n.replace('ё', 'е')).strip()
    pats = [  # (regex, lang)
        (rf'^(?P<a>[\w.\- ]+?)\s+{AK}\s+(?:К|к)енеш\w*(?:\s+имени\s+[\w. ]+?)?(?:\s+(?P<d>[\w\-]+)\s+район\w*)?$', 'ru'),
        (rf'^(?P<d>[\w\-]+)\s+район\w*\s+(?P<a>[\w.\- ]+?)\s+{AK}\s+кенеш\w*$', 'ru'),
        (r'^(?:(?P<d>[\w\-]+)\s+району(?:нун)?\s+)?(?P<a>[\w.\- ]+?)\s+айыл(?:\s+аймагынын)?\s+(?:айылдык\s+)?кенеши\w*$', 'ky'),
        (r'^(?P<a>[\w.\- ]+?)\s+айылдык\s+кенеши\w*(?:\s+(?P<d>[\w\-]+)\s+району\w*)?$', 'ky'),
        (rf'^(?:(?P<d>[\w\-]+)\s+район\w*\s+)?(?:местный\s+)?(?:{AK}\s+)?(?:К|к)е[нң]еш\w*\s+(?:айылного\s+аймака\s+)?(?P<a>[\w.\- ]+?)\s+(?:{AK}\s+аймак\w*)?(?:\s+(?P<d2>[\w\-]+)\s+район\w*)?$', 'ru'),
        (rf'^(?P<a>[\w.\- ]+?)\s+{AK}\s+(?:аймак\w*\s+)?(?:К|к)е[нң]е\w*(?:\s+[\w\-]+\s+{AK}\s+аймак\w*)?(?:\s+(?P<d>[\w\-]+)\s+район\w*)?$', 'ru'),
        (r'^(?P<d>[\w\-]+)\s+району\w*\s+(?P<a>[\w.\- ]+?)\s+айыл\w*\s+аймакты\w*\s+ке[нң]еши\w*$', 'ky'),
    ]
    for p, lang in pats:
        m = re.match(p, o, re.I)
        if m and m.group('a') and not re.match(r'(?i)^(айыл\w*|ке[нң]еш\w*|айылного|местный)( |$)', m.group('a')):
            a = m.group('a').strip(); d = m.group('d') or (m.groupdict().get('d2'))
            m2 = re.match(r'^([\w\-]+)\s+район\w*\s+(.+)$', a, re.I)
            if m2 and not d: d, a = m2.group(1), m2.group(2)
            if 'район' in a.lower() or 'област' in a.lower(): return None
            if lang == 'ru': a = re.sub(r'(?i)(ск|цк)ого$', r'\1ий', a)
            return lang, a, d
    return None
def main():
    W = list(csv.DictReader(open(D + '/wd2.csv')))
    aim = collections.defaultdict(dict)
    for r in W:
        if not r['t'].endswith('Q20733617'): continue
        q = r['i'].rsplit('/', 1)[1]
        nm = re.sub(r'(?i)\b(айыл(ный|ьный|дык)? айма\w*|аильный округ|айылный округ|сельский округ)\b', '', r['ru'] or r['ky'] or '').strip()
        a = aim[q]; a.update(q=q, ru=r['ru'], ky=r['ky'], osm=r['osm'] or a.get('osm', ''), key=stem(nm.split()[0]) if nm else '')
        a.setdefault('d', set()).add(stem((r['dru'] or 'x').split()[0]))
    DS = collections.defaultdict(lambda: {'iso': set()})
    for r in csv.DictReader(open(D + '/kg_districts.csv')):
        k = stem(r['dru'].split()[0]) if r['dru'] else None
        if k: DS[k].update(ru=r['dru'], ky=r['dky']); DS[k]['iso'].add(r['iso'])
    O = json.load(open(D + '/kg_local_organs.json')); rows = []; st = collections.Counter(); pend = []
    for o in O:
        if not re.search(r'(?i)айыл|аил', o['name']): st['not_aiyl_body'] += 1; continue
        p = parse(o['name'])
        if not p: st['unparsed'] += 1; pend.append(o['name']); continue
        lang, a, d = p; ak = stem(a.split()[-1] if a.lower().startswith('им') else a.split()[0]) if a else ''
        ak = stem(a)  # whole name stem (keeps hyphenated compounds)
        dk = stem(d) if d else None; dist = DS.get(dk) if dk else None
        c = [x for x in aim.values() if x['key'] == ak and (not dk or dk in x['d'])]
        wd = c[0] if len(c) == 1 else None
        st['wd_unique' if wd else ('wd_multi' if c else 'wd_none')] += 1
        iso = (dist['iso'] if dist else set())
        rows.append({'aiyl_aimak_ru': (a + ' айыл аймак') if lang == 'ru' else (wd['ru'] if wd else ''),
                     'aiyl_aimak_ky': (a + ' айыл аймагы') if lang == 'ky' else (wd['ky'] if wd else ''),
                     'parent_district_ru': dist['ru'] if dist else (d or ''), 'parent_district_ky': dist['ky'] if dist else '',
                     'district_matched': 'yes' if dist else ('no' if d else 'not_in_name'),
                     'region_code': next(iter(iso)) if len(iso) == 1 else '', 'region_note': 'multiple_iso_in_wd:' + '|'.join(sorted(iso)) if len(iso) > 1 else '',
                     'cbd_issuing_body_id': o['code'], 'cbd_issuing_body_name': o['name'], 'name_lang_in_cbd': lang,
                     'wikidata_id': wd['q'] if wd else '', 'osm_id': wd['osm'] if wd else '', 'wd_candidates': len(c)})
    with open(OUT, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    open(D + '/kg_unparsed_organs.txt', 'w').write('\n'.join(pend) + '\n')
    print(dict(st), 'rows', len(rows), 'district_matched', sum(r['district_matched'] == 'yes' for r in rows), 'region', sum(bool(r['region_code']) for r in rows))
if __name__ == "__main__": main()

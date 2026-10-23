"""Build verified NP palika -> site list. Tolerant Devanagari matching (vowel length, व/ब, nasal marks,
halant, spacing) + WD alt labels; unique-match only (district used only to break ties)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, json, re, sys, time, requests, html as H, unicodedata, collections, os
from concurrent.futures import ThreadPoolExecutor
D = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_np')
UA = {'User-Agent': 'world-law-research-bot/1.0 (municipal law archive research)'}
SUF = r'(उप-?महानगरपालिका|महानगरपालिका|गाउँ ?पालिका|गाउं ?पालिका|गाँउपालिका|नगर ?पालिका|Rural Municipality|Sub-?Metropolitan City|Metropolitan City|Municipality|Gaunpalika|Nagarpalika)'
def norm(s):
    s = unicodedata.normalize('NFC', s or '')
    s = re.sub(SUF, '', s, flags=re.I)
    for a, b in (('ी', 'ि'), ('ू', 'ु'), ('व', 'ब'), ('ँ', ''), ('ं', ''), ('ः', ''), ('्', ''), ('ङ', 'न'), ('ञ', 'न'), ('ण', 'न'), ('श', 'स'), ('ष', 'स'), ('ऋ', 'रि'), ('ृ', 'ि'), ('ई', 'इ'), ('ऊ', 'उ'), ('़', '')):
        s = s.replace(a, b)
    return re.sub(r'[^\u0900-\u097fa-z]', '', s.lower())
def load():
    R = {r['item'].rsplit('/', 1)[1]: r for r in csv.DictReader(open(D + '/np_wd.csv'))}
    for r in csv.DictReader(open(D + '/np_wd_d.csv')):
        q = r['item'].rsplit('/', 1)[1]
        if q in R and r['den'].endswith('District'): R[q]['district_ne'] = r['dne']; R[q]['district_en'] = r['den'][:-9]
    P = []
    for q, r in R.items():
        names = {n for n in [r['ne']] + [a for a in r['alts'].split('|') if re.search(r'[\u0900-\u097f]', a)] if n}
        keys = {norm(n) for n in names if len(norm(n)) >= 3}
        P.append({'qid': 'wd:' + q, 'en': r['en'], 'ne': r['ne'], 'alts': r['alts'], 'wd_site': r['site'], 'district_ne': r.get('district_ne', ''),
                  'district_en': r.get('district_en', ''), 'keys': sorted(keys), 'type': 'municipality' if r['type'].endswith('Q3492039') else 'rural_municipality'})
    return P
def match(title, P):
    t = norm(title.split('|')[0]) or norm(title)
    c = [p for p in P if any(k and k in t for k in p['keys'])]
    if len(c) > 1:  # prefer longest key, then district
        L = max(max(len(k) for k in p['keys'] if k in t) for p in c)
        c = [p for p in c if any(len(k) == L and k in t for k in p['keys'])]
    if len(c) > 1:
        tt = norm(title)
        c2 = [p for p in c if p['district_ne'] and norm(p['district_ne'].replace('जिल्ला', '')) in tt]
        if len(c2) == 1: c = c2
    return c
def fetch_title(host):
    import subprocess
    for sch in ('https', 'http'):
        r = subprocess.run(['curl', '-s', '-L', '--max-redirs', '3', '--noproxy', '*', '-m', '60', '--connect-timeout', '15', '-A', UA['User-Agent'],
                            '-r', '0-40000', '-w', '\n%{http_code}', f'{sch}://{host}/ne'], capture_output=True, text=True, errors='replace')
        if r.returncode == 28 and '<title>' in r.stdout: r = type('R', (), {'returncode': 0, 'stdout': r.stdout + '\n200'})()
        if r.returncode in (35, 51, 60) and sch == 'https': continue
        if r.returncode: return None, f'curl{r.returncode}', None
        body, _, code = r.stdout.rpartition('\n'); code = int(code or 0)
        m = re.search(r'<title>(.*?)</title>', body[:200000], re.S)
        if code < 500 and m: return f'{sch}://{host}', code, re.sub(r'\s+', ' ', H.unescape(m.group(1))).strip()
        return f'{sch}://{host}', code, None
    return None, None, None
def slug(en): return re.sub(r'[^a-z]', '', (en or '').lower())
if __name__ == '__main__':
    for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','all_proxy'): os.environ.pop(k, None)
    P = load(); byq = {p['qid']: p for p in P}
    cand = collections.defaultdict(set)
    for p in P:
        if p['wd_site'] and '.gov.np' in p['wd_site']:
            cand[re.sub(r'^https?://', '', p['wd_site']).split('/')[0].lower().removeprefix('www.')].add('wd')
        s = slug(p['en']); alt = [slug(a) for a in p['alts'].split('|') if a and not re.search(r'[\u0900-\u097f]', a)]
        for b in {s, *[re.sub(r'(ruralmunicipality|municipality|gaunpalika|nagarpalika|submetropolitancity|metropolitancity)$', '', a) for a in alt]}:
            if len(b) < 3: continue
            for pat in (f'{b}mun.gov.np', f'{b}mun{slug(p["district_en"])}.gov.np' if p['district_en'] else None, f'{b}.gov.np'):
                if pat: cand[pat].add('pattern')
    hosts = sorted(cand); print('candidate hosts', len(hosts), flush=True)
    import socket, threading
    CK = D + '/np_hostcheck.jsonl'; lk = threading.Lock()
    seen = {}
    if os.path.exists(CK):
        for l in open(CK):
            r = json.loads(l); seen[r['host']] = r
    RETRY = {'curl28', 500, 502, 503, 504}
    seen = {h: r for h, r in seen.items() if not (r.get('status') in RETRY and r.get('attempt', 1) < 2)}
    print('checkpointed', len(seen), flush=True)
    def chk0(h):
        site, st, title = fetch_title(h)
        if not title: return {'host': h, 'status': st, 'site': site}
        m = match(title, P)
        return {'host': h, 'status': st, 'site': site, 'title': title, 'matches': [x['qid'] for x in m]}
    def chk(h):
        if h in seen: return seen[h]
        r = chk0(h); r['attempt'] = 2
        with lk, open(CK, 'a') as f: f.write(json.dumps(r, ensure_ascii=False) + '\n')
        return r
    with ThreadPoolExecutor(6) as ex: res = list(ex.map(chk, hosts))
    for r in res:  # re-match with current matcher (checkpoint may predate matcher tweaks)
        if r.get('title'): r['matches'] = [x['qid'] for x in match(r['title'], P)]
    # unique-match: one place per host, one host per place
    per_place = collections.defaultdict(list)
    for r in res:
        if len(r.get('matches') or []) == 1: per_place[r['matches'][0]].append(r)
    out = []; amb = 0
    for q, rs in per_place.items():
        sites = {r['site'].replace('://www.', '://') for r in rs}
        if len(sites) > 1:
            # multiple hosts verified for one place: prefer the WD one, else ambiguous
            wd = [r for r in rs if 'wd' in cand[r['host']]]
            if len(wd) != 1: amb += 1; continue
            rs = wd
        r = rs[0]; p = byq[q]
        out.append({**{k: p[k] for k in ('qid', 'en', 'ne', 'type', 'district_en')}, 'host': r['host'], 'site': r['site'], 'site_title': r['title'], 'verified': 'title_unique_match', 'source': sorted(cand[r['host']])})
    with open(D + '/np_places_full.jsonl', 'w') as f:
        for o in out: f.write(json.dumps(o, ensure_ascii=False) + '\n')
    print('hosts with title', sum(1 for r in res if r.get('title')), 'unique-match hosts', sum(1 for r in res if len(r.get('matches') or []) == 1),
          'multi', sum(1 for r in res if len(r.get('matches') or []) > 1), 'nomatch', sum(1 for r in res if r.get('title') and not r.get('matches')),
          'places verified', len(out), 'ambiguous places', amb, 'from wd', sum(1 for o in out if 'wd' in o['source']), flush=True)

#!/usr/bin/env python3
"""CZ SPP probe loop (single process, sequential czp_get.py calls: >=2s spacing, 3x403/429/503 stop, MemAvail<=3700 TERM).
Phases: counts -> random listing pages -> sample detail+text -> (export polls interleaved every ~3 min)."""
import subprocess, sys, os, re, json, random, html, time
B = '/workspace/legal-corpora/cz_sbirkapp'; BASE = 'https://sbirkapp.gov.cz'
EXPORT = '/export/DDY74FFDC4HONCY2EYCHVCHAWDH7KPDTP726QGWV/prubeh'
def mem(): return int(open('/proc/meminfo').read().split('MemAvailable:')[1].split()[0]) // 1024
last_poll = [0]
def get(path, d, name):
    if mem() <= 3700: print('MEMGUARD TERM', mem(), flush=True); sys.exit(3)
    r = subprocess.run(['python3', '/workspace/scripts/czp_get.py', '--dir', d, '--name', name, BASE + path], capture_output=True, text=True)
    print(r.stdout.strip()[:220], r.stderr.strip()[-200:], flush=True)
    if r.returncode == 9: sys.exit(9)
    return r.stdout.split()[0] if r.stdout else None
def poll():
    if os.environ.get('CZP_NOPOLL') or time.time() - last_poll[0] < 180: return
    last_poll[0] = time.time()
    st = get(EXPORT, f'{B}/index', 'export_prubeh.html')
    s = open(f'{B}/index/export_prubeh.html', encoding='utf-8', errors='replace').read()
    m = re.search(r'\((\d+)/(\d+)\)', s); print('EXPORT', st, m.groups() if m else 'no-progress', time.strftime('%H:%M:%S'), flush=True)
def count(name):
    s = open(f'{B}/probe/{name}', encoding='utf-8', errors='replace').read()
    m = re.search(r'Počet podání:\s*(?:<[^>]+>\s*)*([\d\s]+)', s)
    return int(re.sub(r'\s', '', m.group(1))) if m else None
VUSC = {'19': 'Hlavní město Praha', '116': 'Jihomoravský kraj', '35': 'Jihočeský kraj', '51': 'Karlovarský kraj', '108': 'Kraj Vysočina', '86': 'Královéhradecký kraj', '78': 'Liberecký kraj',
        '132': 'Moravskoslezský kraj', '124': 'Olomoucký kraj', '94': 'Pardubický kraj', '43': 'Plzeňský kraj', '27': 'Středočeský kraj', '141': 'Zlínský kraj', '60': 'Ústecký kraj'}
phase = sys.argv[1]
if phase == 'counts':
    Q = {'pp_ozv': 'hlavni_typ=pp&typ=ozv', 'pp_narizeni': 'hlavni_typ=pp&typ=narizeni', 'pp_platne': 'hlavni_typ=pp&platnost=ano', 'pp_zruseno': 'hlavni_typ=pp&platnost=ne', 'oa_all': 'hlavni_typ=oa',
         'pp_transitional': 'hlavni_typ=pp&zpusob_zverejneni=TRANSITIONAL', 'pp_alternate': 'hlavni_typ=pp&zpusob_zverejneni=ALTERNATE'}
    for k, v in VUSC.items(): Q[f'pp_vusc_{k}'] = f'hlavni_typ=pp&kod_vusc={k}'
    res = {}
    for k, q in Q.items():
        poll(); get(f'/vyhledavani/vysledek?{q}', f'{B}/probe', f'count_{k}.html'); res[k] = count(f'count_{k}.html'); print('COUNT', k, res[k], flush=True)
    json.dump(dict(counts=res, vusc=VUSC, queries=Q, ts=time.strftime('%Y-%m-%dT%H:%M:%S%z')), open(f'{B}/index/counts.json', 'w'), indent=1, ensure_ascii=False)
elif phase == 'listing':
    random.seed(20261004); pages = sorted(random.sample(range(1, 1579), 12))
    ids = []
    for p in pages:
        poll(); get(f'/vyhledavani/vysledek?hlavni_typ=pp&page={p}', f'{B}/probe', f'list_p{p}.html')
        s = open(f'{B}/probe/list_p{p}.html', encoding='utf-8', errors='replace').read()
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S)
        for row in rows:
            m = re.search(r'/detail/(SPP[A-Z0-9]+)', row)
            if not m: continue
            cells = [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', c))).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
            ids.append(dict(id=m.group(1), page=p, cells=cells))
    json.dump(ids, open(f'{B}/index/listing_sample.json', 'w'), indent=1, ensure_ascii=False); print('IDS', len(ids))
elif phase == 'sample':
    L = json.load(open(f'{B}/index/listing_sample.json')); random.seed(7)
    pick = random.sample(L, min(int(sys.argv[2]), len(L)))
    os.makedirs(f'{B}/docs', exist_ok=True); out = open(f'{B}/index/sample.jsonl', 'a')
    done = {json.loads(l)['id'] for l in open(f'{B}/index/sample.jsonl')} if os.path.getsize(f'{B}/index/sample.jsonl') else set()
    for d in pick:
        if d['id'] in done: continue
        poll(); st = get(f"/detail/{d['id']}", f'{B}/probe', f"detail_{d['id']}.html"); rec = dict(id=d['id'], cells=d['cells'], detail_http=st)
        if st == '200':
            s = open(f"{B}/probe/detail_{d['id']}.html", encoding='utf-8', errors='replace').read()
            rec['has_text_link'] = f"/detail/{d['id']}/text" in s; rec['attachments'] = sorted(set(re.findall(rf"/detail/{d['id']}/prilohy/(\d+)", s)))
            if rec['has_text_link']:
                rec['text_http'] = get(f"/detail/{d['id']}/text", f'{B}/docs', d['id'])
                h = open(f"{B}/docs/{d['id']}.headers").read(); m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^"\n]+)', h); ct = re.search(r'"Content-Type": "([^"]+)"', h)
                rec['filename'] = m.group(1) if m else None; rec['ctype'] = ct.group(1) if ct else None; rec['bytes'] = os.path.getsize(f"{B}/docs/{d['id']}")
        out.write(json.dumps(rec, ensure_ascii=False) + '\n'); out.flush()
    print('SAMPLE DONE')
elif phase == 'poll':
    last_poll[0] = 0; poll()

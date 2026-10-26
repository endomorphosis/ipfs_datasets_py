#!/usr/bin/env python3
"""ES subnational collector: BOE legislacion-consolidada open-data API, ambito@codigo:2 (Autonomico).
Single process. robots.txt-checked per URL (Google-style * and $ matching, longest rule wins, Allow wins ties).
Stops after 3 consecutive 403s (BLOCKED_SOURCE). MemAvail pause <=4600MB, self-TERM <=3584MB.
Usage: es_collect.py handcheck ID,ID,...  |  es_collect.py full"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, re, json, gzip, time, threading, urllib3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
B = Path('{_CORPORA}/es_subnational'); RAW = B / 'raw'; PROBE = B / 'probe'; RAW.mkdir(parents=True, exist_ok=True)
API = 'https://www.boe.es/datosabiertos/api/legislacion-consolidada'
UA = 'legal-corpora-es-subnational/1.0 (research corpus of BOE open data; polite; https://www.boe.es/datosabiertos/)'
PIN = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'
WORKERS = 3; DELAY = 0.25
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
def set_pin(**u):
    kv = dict(l.rstrip('\n').split('=', 1) for l in open(PIN) if '=' in l); kv.update({k: str(v) for k, v in u.items()})
    open(PIN + '.tmp', 'w').write(''.join(f'{k}={v}\n' for k, v in kv.items())); os.replace(PIN + '.tmp', PIN)
STOP = threading.Event()
def mem_gate():
    while True:
        m = memavail()
        if m <= 3584:
            log(f'MEMGUARD TERM MemAvailable={m}MB'); STOP.set()
            set_pin(mode='HOLD_0_ES_MEMSHED', collectors=0, phase=f'ES collector self-TERM at MemAvail={m}MB; not restarted', ts=time.strftime('%Y-%m-%dT%H:%MPT'))
            os._exit(3)
        if m <= 4600:
            log(f'MEM PAUSE MemAvailable={m}MB'); time.sleep(30); continue
        return
def _mg():
    while True:
        if memavail() <= 3584: mem_gate()
        time.sleep(5)
threading.Thread(target=_mg, daemon=True).start()

# ---- robots
def load_robots(p=B / 'robots/boe.es_robots.txt'):
    rules = []; active = False
    for line in open(p, encoding='utf-8', errors='replace'):
        line = line.split('#', 1)[0].strip()
        if not line or ':' not in line: continue
        k, v = [x.strip() for x in line.split(':', 1)]; k = k.lower()
        if k == 'user-agent': active = (v == '*'); continue
        if not active or k not in ('allow', 'disallow') or not v: continue
        rx = re.escape(v).replace(r'\*', '.*'); rx = rx[:-2] + '$' if rx.endswith(r'\$') else rx
        rules.append((k == 'allow', len(v), re.compile(rx)))
    return rules
RULES = load_robots()
def robots_ok(url):
    path = re.sub(r'^https?://[^/]+', '', url) or '/'
    best = None
    for allow, n, rx in RULES:
        if rx.match(path) and (best is None or n > best[1] or (n == best[1] and allow)): best = (allow, n)
    return best is None or best[0]

http = urllib3.PoolManager(num_pools=2, maxsize=WORKERS + 1, timeout=urllib3.Timeout(connect=20, read=180), headers={'User-Agent': UA, 'Accept': 'application/xml'})
C403 = [0]; LOCK = threading.Lock(); STATS = dict(ok=0, cached=0, robots_skip=0, fail=0, http403=0)
def fetch(ident):
    if STOP.is_set(): return ident, 'stopped'
    dest = RAW / f'{ident}.xml.gz'
    if dest.exists(): return ident, 'cached'
    url = f'{API}/id/{ident}'
    if not robots_ok(url): return ident, 'robots_skip'
    mem_gate()
    for att in range(5):
        try:
            r = http.request('GET', url, preload_content=True, retries=False)
        except Exception as e:
            time.sleep(2 * (att + 1)); err = str(e); continue
        if r.status == 403:
            with LOCK:
                C403[0] += 1; STATS['http403'] += 1
                (PROBE / f'boe_403_{C403[0]}_{ident}.txt').write_bytes(f'GET {url}\nHTTP 403\n{dict(r.headers)}\n\n'.encode() + r.data[:4000])
                if C403[0] >= 3: STOP.set(); log('BLOCKED_SOURCE: 3 consecutive 403s')
            return ident, 'http403'
        if r.status in (429, 500, 502, 503, 504):
            time.sleep(5 * (att + 1)); err = f'HTTP {r.status}'; continue
        with LOCK: C403[0] = 0
        if r.status != 200 or not r.data.lstrip().startswith(b'<'): return ident, f'fail HTTP {r.status} {r.data[:80]!r}'
        tmp = dest.with_suffix('.tmp'); tmp.write_bytes(gzip.compress(r.data)); os.replace(tmp, dest)
        time.sleep(DELAY); return ident, 'ok'
    return ident, f'fail {err}'

def main():
    mode = sys.argv[1]
    cat = json.load(open(B / 'catalog_autonomico.json'))['data']
    ids = sys.argv[2].split(',') if mode == 'handcheck' else [x['identificador'] for x in cat]
    log('START', mode, 'n', len(ids), 'pid', os.getpid(), 'mem', memavail(), 'robots_rules', len(RULES))
    res = {}
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(fetch, i) for i in ids]
        for n, f in enumerate(as_completed(futs), 1):
            i, s = f.result(); res[i] = s; k = s.split()[0]; STATS[k] = STATS.get(k, 0) + 1
            if s.startswith('fail') or s in ('robots_skip', 'http403'): log(i, s)
            if n % 100 == 0: log('progress', n, len(ids), STATS, 'mem', memavail())
    json.dump(dict(mode=mode, stats=STATS, results=res, blocked_source=C403[0] >= 3, ts=time.strftime('%Y-%m-%dT%H:%M:%S%z')),
              open(B / f'collect_result_{mode}.json', 'w'), indent=1)
    log('DONE', STATS)
if __name__ == '__main__': main()

#!/usr/bin/env python3
"""NL ARTICLE_EXTRACT collector. ONE process, sequential. Source: ONLY repository.officiele-overheidspublicaties.nl (KOOP BWB, CC0).
NO requests to wetten.overheid.nl / zoekservice.overheid.nl. Fetches exactly the hub's toestand XML (hub articles.source_url);
on 404 falls back to the work manifest _latestItem. >=2.2s between requests; 3 consecutive 403/429/503 -> STOP.
MemAvail checked per request + 5s thread: <=3584MB -> 'MEMGUARD TERM MemAvailable=<n>MB', exit 3.
Raw XML cached gz per BWB id (raw/<id>.xml.gz); split rows per law (out/articles/<id>.jsonl.gz) -> resume-safe.
Usage: nl_collect.py handcheck | nl_collect.py full"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, re, json, gzip, time, threading
from pathlib import Path
import requests
sys.path.insert(0, '/workspace/scripts'); import nl_split
B = Path('{_CORPORA}/nl_extract'); RAW = B / 'raw'; OUT = B / 'out' / 'articles'; IDX = B / 'index'
PIN = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'; HOST = 'repository.officiele-overheidspublicaties.nl'
UA = 'legal-corpora-nl-extract/1.0 (research corpus of official Dutch legislation from the CC0 KOOP BWB repository; polite; contact via huggingface.co/endomorphosis)'
TERM_MB = 3584; DELAY = 2.2
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
    return 10 ** 9
def set_pin(**u):
    try: kv = dict(l.rstrip('\n').split('=', 1) for l in open(PIN) if '=' in l)
    except Exception: kv = {}
    kv.update({k: str(v) for k, v in u.items()}); open(PIN + '.tmp', 'w').write(''.join(f'{k}={v}\n' for k, v in kv.items())); os.replace(PIN + '.tmp', PIN)
def term(m):
    log(f'MEMGUARD TERM MemAvailable={m}MB')
    try: set_pin(mode='HOLD_0_NL_MEMSHED', collectors=0, pid='', phase=f'NL collector self-TERM at MemAvail={m}MB; not restarted', ts=time.strftime('%Y-%m-%dT%H:%MPT'), MemAvail_MB=m)
    except Exception as e: log('pin update failed', e)
    os._exit(3)
def mem_check():
    m = memavail()
    if m <= TERM_MB: term(m)
    return m
def _mg():
    while True: mem_check(); time.sleep(5)
class Stop(Exception): pass
class Fetcher:
    def __init__(self):
        self.s = requests.Session(); self.s.headers['User-Agent'] = UA; self.last = 0.0; self.cbad = 0; self.nreq = 0
        self.stats = dict(fetched=0, cached=0, http404=0, fallback_latest=0, fail=0, bad403_429_503=0)
    def get(self, url, timeout=(20, 180)):
        if not url.startswith(f'https://{HOST}/'): raise ValueError('off-host url refused: ' + url)
        for att in range(3):
            mem_check()
            w = DELAY - (time.time() - self.last)
            if w > 0: time.sleep(w)
            self.last = time.time(); self.nreq += 1
            try: r = self.s.get(url, timeout=timeout, allow_redirects=False)
            except Exception as e: log('ERR', url, repr(e)[:200]); time.sleep(15 * (att + 1)); continue
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get('location', '')
                if not loc.startswith(f'https://{HOST}/'): log('OFFHOST redirect refused', url, loc); return None
                url = loc; continue
            if r.status_code in (403, 429, 503):
                self.cbad += 1; self.stats['bad403_429_503'] += 1
                (B / 'probe' / f'http{r.status_code}_{self.cbad}_{int(time.time())}.txt').write_text(f'GET {url}\nHTTP {r.status_code}\n{dict(r.headers)}\n\n{r.text[:3000]}')
                log(f'HTTP {r.status_code} consecutive={self.cbad}', url)
                if self.cbad >= 3: raise Stop(f'3 consecutive 403/429/503 at {url}')
                time.sleep(60); continue
            self.cbad = 0
            if r.status_code >= 500: log('HTTP', r.status_code, url); time.sleep(30 * (att + 1)); continue
            return r
        return None
F = Fetcher()
def load_targets():
    return [json.loads(l) for l in open(IDX / 'hub_targets.jsonl')]
def fetch_xml(t):
    p = RAW / f"{t['law_id']}.xml.gz"
    if p.exists():
        F.stats['cached'] += 1; d = json.loads((RAW / f"{t['law_id']}.meta.json").read_text()) if (RAW / f"{t['law_id']}.meta.json").exists() else {}
        return gzip.decompress(p.read_bytes()), d.get('url', t['url']), d.get('version_note', 'hub_version')
    url, note = t['url'], 'hub_version'
    r = F.get(url)
    if r is not None and r.status_code == 404:
        F.stats['http404'] += 1; m = F.get(t['manifest'])
        if m is not None and m.status_code == 200:
            li = re.search(rb'_latestItem="([^"]+)"', m.content)
            if li:
                url = f"https://{HOST}/bwb/{t['law_id']}/{li.group(1).decode()}"; note = 'latest_item_fallback'; F.stats['fallback_latest'] += 1; r = F.get(url)
    if r is None or r.status_code != 200 or not r.content.lstrip().startswith(b'<?xml'):
        F.stats['fail'] += 1; log('FAIL', t['law_id'], getattr(r, 'status_code', None), url); return None, url, note
    tmp = p.with_suffix('.tmp'); tmp.write_bytes(gzip.compress(r.content, 6)); os.replace(tmp, p)
    (RAW / f"{t['law_id']}.meta.json").write_text(json.dumps(dict(url=url, version_note=note, bytes=len(r.content), fetched_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'))))
    F.stats['fetched'] += 1; return r.content, url, note
def version_of(url):
    m = re.search(r'/(\d{4}-\d{2}-\d{2}_\d+)/xml/', url); return m.group(1) if m else None
def process(t, summ):
    op = OUT / f"{t['law_id']}.jsonl.gz"
    if op.exists(): return 'done_before'
    raw, url, note = fetch_xml(t)
    if raw is None: summ.write(json.dumps(dict(law_id=t['law_id'], status='fetch_fail', url=url)) + '\n'); return 'fetch_fail'
    try: rows, st = nl_split.split_xml(raw, t['law_id'], url, version_of(url))
    except Exception as e:
        summ.write(json.dumps(dict(law_id=t['law_id'], status='parse_fail', error=repr(e)[:300])) + '\n'); return 'parse_fail'
    tmp = op.with_suffix('.tmp')
    with gzip.open(tmp, 'wt', encoding='utf-8') as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.replace(tmp, op)
    summ.write(json.dumps(dict(law_id=t['law_id'], status='ok', version=version_of(url), version_note=note, bwb_type=t.get('bwb_type'), rows=len(rows), **st)) + '\n'); summ.flush()
    return 'ok'
HAND = ['wet:4', 'AMvB:2', 'ministeriele-regeling:3', 'KB:1', 'zbo:1', 'beleidsregel:1', 'circulaire:1', 'ministeriele-regeling-archiefselectielijst:1',
        'rijkswet:1', 'wet-BES:1', 'pbo:1', 'reglement:1', 'AMvB-BES:1', 'ministeriele-regeling-BES:1']
def hand_targets(T):
    out = []
    for spec in HAND:
        ty, n = spec.split(':'); c = sorted([t for t in T if t['bwb_type'] == ty], key=lambda t: t['law_id'])
        if ty == 'wet':  # include one large wet (p99 size) and three spread
            big = sorted([t for t in c if (t['bytes'] or 0) < 3_000_000], key=lambda t: -(t['bytes'] or 0))[:1]; out += big; c = [t for t in c if t not in big]; n = int(n) - 1
        step = max(1, len(c) // (int(n) + 1)); out += [c[step * (i + 1)] for i in range(int(n))]
    return out
def main():
    mode = sys.argv[1]; threading.Thread(target=_mg, daemon=True).start()
    for d in (RAW, OUT, IDX): d.mkdir(parents=True, exist_ok=True)
    T = load_targets(); todo = hand_targets(T) if mode == 'handcheck' else T
    log('START', mode, 'pid', os.getpid(), 'targets', len(todo), f'mem={memavail()}MB', 'host', HOST, 'delay', DELAY)
    res = {}; t0 = time.time()
    with open(IDX / f'split_summary_{mode}.jsonl', 'a') as summ:
        for n, t in enumerate(todo, 1):
            try: s = process(t, summ)
            except Stop as e: log('STOP', e); res['STOPPED'] = str(e); break
            except Exception as e: s = f'error_{type(e).__name__}'; log('ERROR', t['law_id'], repr(e)[:300])
            res[s] = res.get(s, 0) + 1
            if n % 50 == 0 or mode == 'handcheck':
                log('progress', n, '/', len(todo), res, F.stats, 'nreq', F.nreq, f'{(time.time()-t0)/n:.2f}s/law', f'mem={memavail()}MB')
            if n % 500 == 0:
                try: set_pin(progress=f'{n}/{len(todo)} {res}', ts=time.strftime('%Y-%m-%dT%H:%MPT'), MemAvail_MB=memavail())
                except Exception: pass
    json.dump(dict(mode=mode, res=res, stats=F.stats, nreq=F.nreq, seconds=round(time.time() - t0), ended=time.strftime('%Y-%m-%dT%H:%M:%S%z')), open(B / f'collect_result_{mode}.json', 'w'), indent=1)
    log('DONE', res, F.stats)
    if mode == 'full':
        try: set_pin(mode='HOLD_0_NL_COLLECT_DONE', collectors=0, pid='', phase=f'NL collect finished {res}', ts=time.strftime('%Y-%m-%dT%H:%MPT'), MemAvail_MB=memavail())
        except Exception: pass
if __name__ == '__main__': main()

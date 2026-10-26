#!/usr/bin/env python3
"""NL MUNICIPAL (decentrale regelgeving, CVDR) collector. ONE process, sequential, polite.
Source: ONLY https://repository.officiele-overheidspublicaties.nl (KOOP repository, CVDR collection, CC0-1.0).
NO requests to wetten.overheid.nl / lokaleregelgeving.overheid.nl / zoekservice.overheid.nl / any SRU endpoint (host-locked).
Enumeration: CVDR work-ID range scan (no index/sitemap/events exist in the repository; SRU is off-limits):
  GET /cvdr/CVDR<id>/manifest.xml for id = TOP..1 (descending: newest/densest first), 404 = no such work.
  Hit -> manifest lists expressions (<expression label=n>, xml item CVDR<id>_<n>.xml); fetch the newest non-deleted xml
  expression; in force iff inwerkingtredingDatum <= today and (no uitwerkingtredingDatum or uitwerkingtredingDatum > today);
  if the newest expression starts in the future, step back to the previous expression (max 4).
  After the descending pass a tail pass scans upward from TOP+1 until 1500 consecutive 404s (works created during the run).
Scope: creator mapped (TOOI registers rwc_gemeenten/provincies/waterschappen_compleet, fetched from the same repository)
  to one of the 342 current gemeenten, 12 provincies, 21 waterschappen. Others are logged in the scan index only.
Politeness/safety: >=1.0s between requests (CoS 2026-10-04 14:16; nlm_config.json re-read every 60s); exponential backoff 5s..300s on 429/5xx/conn errors; 3 consecutive 403/429/503 -> STOP; RSS >300MB -> warn + TERM; SIGTERM -> clean exit after the current id; MemAvail checked before every request / id + 5s thread.
  PAUSE GUARD (CoS 2026-10-05 17:22 PT option c): MemAvail < pause_memavail (3584) -> 'MEMPAUSE' (in-flight request finishes, nothing
  written partially, sleep-poll every 10s); 'MEMRESUME' only after MemAvail >= resume_memavail (4200) continuously for resume_hold_s (30s);
  hard 'MEMTERM' (clean exit 3, PIN HOLD_0_NLM_MEMSHED) only if MemAvail < hard_term_memavail (3000) CONTINUOUSLY for >= hard_term_sustain_s (5s;
  watcher polls every hard_term_poll_s=2s, any reading >= 3000 resets the 'MEMLOW_STREAK'), any single reading < instant_term_memavail (2500),
  paused > max_pause_s (900), or RSS > 300MB (CoS 2026-10-05 17:48 PT debounce). A sub-3000 dip shorter than 5s is just a PAUSE.
  Test caps (full mode): NLM_MAX_CHUNKS / NLM_MAX_WALL_S stop at a chunk boundary and skip tail+retry passes; NLM_NO_PIN=1 never touches the PIN.
Resume-safe gz caches: index/scan/<hi>.jsonl.gz written atomically per 200-ID chunk (completed chunks are skipped);
  raw/manifest/*.xml.gz (hits), raw/xml/*.xml.gz (kept only for in-force in-scope), out/laws/<id>.json.gz, out/articles/<id>.jsonl.gz.
Usage: nl_municipal_collect.py handcheck | hcreport (offline re-check) | full | resplit (offline) | build <out_dir> (offline)"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, re, json, gzip, time, threading, datetime, unicodedata
from pathlib import Path
import xml.etree.ElementTree as ET
import requests
sys.path.insert(0, '/workspace/scripts'); import nlm_split, nl_split
B = Path('{_CORPORA}/nl_municipal'); RAWM = B / 'raw' / 'manifest'; RAWX = B / 'raw' / 'xml'
OUTA = B / 'out' / 'articles'; OUTL = B / 'out' / 'laws'; SCAN = B / 'index' / 'scan'; REF = B / 'ref'; PROBE = B / 'probe'
PIN = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'; HOST = 'repository.officiele-overheidspublicaties.nl'; BASE = f'https://{HOST}'
UA = 'legal-corpora-nl-municipal/1.0 (research corpus of official Dutch decentral regulations from the CC0 KOOP repository; polite; contact via huggingface.co/endomorphosis)'
TERM_MB = 3584; DELAY = 1.0; RSS_MB = 300; BACKOFF_BASE = 5; BACKOFF_CAP = 300; CHUNK = 200; TOP = int(os.environ.get('NLM_TOP', '767599')); TAIL_MISS = 1500
NAT = Path('{_CORPORA}/hf-staging/ipfs_netherlands_laws_extract_20261003T132323/data')
LICENSE = ("CC0-1.0 as stated by KOOP on data.overheid.nl dataset 'Lokale regelingen' (https://data.overheid.nl/dataset/lokale-regelingen): "
           "actuele en historische teksten van regelingen van gemeenten, provincies en waterschappen (bron: CVDR); license CC-0 (1.0). "
           "Each CVDR XML states dcterms:rights 'De tekst in dit document is vrij van auteursrecht en databankrecht'.")
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
    return 10 ** 9
def now_pt(): return datetime.datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')
CFG = B / 'nlm_config.json'  # re-read every 60s: delay_s (>=1.0), rss_limit_mb (<=300), pause_memavail (>=3300; legacy key term_memavail_mb), resume_memavail (>=3800),
#                               resume_hold_s (>=10), hard_term_memavail (>=3000), max_pause_s (<=900), backoff_base_s, backoff_cap_s
PAUSE_MB = 3584; RESUME_MB = 4200; RESUME_HOLD_S = 30; HARD_MB = 1500; MAX_PAUSE_S = 900; POLL_S = 10
HARD_SUSTAIN_S = 10.0; HARD_POLL_S = 2.0; INSTANT_MB = 1000
def load_cfg(quiet=False):
    global DELAY, RSS_MB, TERM_MB, BACKOFF_BASE, BACKOFF_CAP, PAUSE_MB, RESUME_MB, RESUME_HOLD_S, HARD_MB, MAX_PAUSE_S, HARD_SUSTAIN_S, HARD_POLL_S, INSTANT_MB
    try: c = json.load(open(CFG))
    except Exception: return
    pause = max(3300, int(c.get('pause_memavail', c.get('term_memavail_mb', PAUSE_MB))))  # floor 3300 (CoS 2026-10-05 18:03 PT; was 3584)
    new = (max(1.0, float(c.get('delay_s', DELAY))), min(300, int(c.get('rss_limit_mb', RSS_MB))), pause,
           float(c.get('backoff_base_s', BACKOFF_BASE)), float(c.get('backoff_cap_s', BACKOFF_CAP)),
           pause, max(3800, pause + 1, int(c.get('resume_memavail', RESUME_MB))), max(10, int(c.get('resume_hold_s', RESUME_HOLD_S))),  # floors 3800 / 10s (CoS 18:03; were 4200 / 30)
           min(pause - 1, max(1200, int(c.get('hard_term_memavail', HARD_MB)))), max(60, min(900, int(c.get('max_pause_s', MAX_PAUSE_S)))))
    hard = new[8]
    new += (max(1.0, min(10.0, float(c.get('hard_term_sustain_s', HARD_SUSTAIN_S)))), max(0.5, min(2.0, float(c.get('hard_term_poll_s', HARD_POLL_S)))),
            min(hard - 1, max(900, int(c.get('instant_term_memavail', INSTANT_MB)))))
    if new != (DELAY, RSS_MB, TERM_MB, BACKOFF_BASE, BACKOFF_CAP, PAUSE_MB, RESUME_MB, RESUME_HOLD_S, HARD_MB, MAX_PAUSE_S, HARD_SUSTAIN_S, HARD_POLL_S, INSTANT_MB):
        DELAY, RSS_MB, TERM_MB, BACKOFF_BASE, BACKOFF_CAP, PAUSE_MB, RESUME_MB, RESUME_HOLD_S, HARD_MB, MAX_PAUSE_S, HARD_SUSTAIN_S, HARD_POLL_S, INSTANT_MB = new
        if not quiet: log('CONFIG reloaded', cfg_dict())
def cfg_dict():
    return dict(delay_s=DELAY, rss_limit_mb=RSS_MB, pause_memavail=PAUSE_MB, resume_memavail=RESUME_MB, resume_hold_s=RESUME_HOLD_S,
                hard_term_memavail=HARD_MB, hard_term_sustain_s=HARD_SUSTAIN_S, hard_term_poll_s=HARD_POLL_S, instant_term_memavail=INSTANT_MB,
                max_pause_s=MAX_PAUSE_S, backoff_base_s=BACKOFF_BASE, backoff_cap_s=BACKOFF_CAP)
NO_PIN = os.environ.get('NLM_NO_PIN') == '1'
CRASH_TOL = os.environ.get('NLM_CRASH_TOLERANT') == '1'  # 2026-10-10 CoS: Watchdog auto-relaunch mode
PIN_MAIN = '/workspace/logs/HOLD_AT_PIN.state'
def set_pin(fn=None, **u):
    """JSON pin shared with other jobs: re-read immediately before writing, merge only our (nlm_*) keys (+fn for counters); atomic replace."""
    if NO_PIN: return
    try: d = json.load(open(PIN))
    except Exception: d = {}
    d.update(u)
    if fn: fn(d)
    d['nlm_ts'] = now_pt()
    tmp = PIN + '.nlm.tmp'; open(tmp, 'w').write(json.dumps(d, indent=1)); os.replace(tmp, PIN)
    if CRASH_TOL:  # mirror only nlm_* + collectors into the main PIN (re-read, atomic)
        try:
            m = json.load(open(PIN_MAIN)); m.update({k: v for k, v in d.items() if k.startswith('nlm_') or k == 'collectors'})
            t2 = PIN_MAIN + '.nlm.tmp'; open(t2, 'w').write(json.dumps(m, indent=2)); os.replace(t2, PIN_MAIN)
        except Exception as e: log('main PIN mirror failed', repr(e)[:200])
def pin_end(status, phase):
    """collector ending: nlm_status, decrement 'collectors' (reflect reality), take over 'mode' only if it is still ours"""
    def fn(d):
        try: d['collectors'] = max(0, int(d.get('collectors') or 0) - 1)
        except Exception: d['collectors'] = 0
    set_pin(fn, nlm_status=status, nlm_pid=None, nlm_phase=phase, nlm_memavail_mb=memavail(), nlm_ended_pt=now_pt())
MODE = None
_TERM_LOCK = threading.Lock()
def term(m, why='MEMGUARD'):
    if not _TERM_LOCK.acquire(blocking=False): time.sleep(60); os._exit(3)  # another thread is already terminating
    log(f'MEMTERM reason={why} memavail_now={m} rss={rss_mb()} min_memavail={G["min_mem"]} pauses={G["n_pause"]} resumes={G["n_resume"]} ts={now_pt()}')
    _drop_tmp()
    if MODE == 'full':
        try: pin_end('MEMTERM_crash_tolerant' if CRASH_TOL else 'HOLD_0_NLM_MEMSHED', f'NL municipal collector self-TERM ({why}) at MemAvail={m}MB rss={rss_mb()}MB; not restarted; resume-safe')
        except Exception as e: log('pin update failed', e)
    os._exit(3)
CUR_TMP = set()   # in-flight .tmp paths (write_chunk / retry pass / tail); removed on any exit path
def _drop_tmp():
    for t in list(CUR_TMP):
        try: os.unlink(t); log('TMP removed on exit', t)
        except FileNotFoundError: pass
        except Exception as e: log('TMP remove failed', t, repr(e)[:120])
        CUR_TMP.discard(t)
def rss_mb():
    for l in open('/proc/self/status'):
        if l.startswith('VmRSS:'): return int(l.split()[1]) // 1024
    return 0
_RSS_WARNED = [False]
G = dict(min_mem_fetch=10 ** 9, min_mem_paused=10 ** 9, min_mem=10 ** 9, n_pause=0, n_resume=0, paused=False, pause_s_total=0.0, hard=None, hard_t=None, low_t0=None, low_n=0, n_streaks=0)
_STREAK_LOCK = threading.Lock()
def _low_streak(m, now):
    """debounced hard floor: TERM reason only for a reading < INSTANT_MB, or MemAvail < HARD_MB on every reading for >= HARD_SUSTAIN_S
    (first to latest sub-HARD reading); any reading >= HARD_MB resets the streak. Fed by the 2s watcher and by the main-thread gate."""
    with _STREAK_LOCK:
        if m < INSTANT_MB: return f'lt{INSTANT_MB} memavail={m}'
        if m >= HARD_MB:
            if G['low_t0'] is not None: log(f'MEMLOW_STREAK reset memavail={m} n={G["low_n"]} dur_s={now - G["low_t0"]:.1f} (no TERM)')
            G['low_t0'] = None; G['low_n'] = 0; return None
        if G['low_t0'] is None: G['low_t0'] = now; G['n_streaks'] += 1
        G['low_n'] += 1; dur = now - G['low_t0']
        log(f'MEMLOW_STREAK memavail={m} n={G["low_n"]} dur_s={dur:.1f} sustain_s={HARD_SUSTAIN_S:g}')
        if dur >= HARD_SUSTAIN_S: return f'sustained_lt{HARD_MB} dur_s={dur:.1f} n={G["low_n"]} memavail={m}'
        return None
def _hard_checks(m, now=None):
    """conditions that end the run regardless of pause state; returns a reason or None"""
    G['min_mem'] = min(G['min_mem'], m)
    k = 'min_mem_paused' if G['paused'] else 'min_mem_fetch'; G[k] = min(G[k], m)
    why = _low_streak(m, time.time() if now is None else now)
    if why: return why
    r = rss_mb()
    if r > RSS_MB: return f'rss={r}MB>{RSS_MB}MB'
    if r > 0.8 * RSS_MB and not _RSS_WARNED[0]: _RSS_WARNED[0] = True; log(f'RSS WARN rss={r}MB (80% of {RSS_MB}MB limit)')
    return None
def mem_check(_sleep=time.sleep, _mem=None, _clock=time.time):
    """guard gate: called in the main thread between requests / ids (never during a file write). Pauses while MemAvail is low,
    resumes after RESUME_MB held for RESUME_HOLD_S, hard-TERMs (clean exit, nothing partial) on debounced <HARD_MB (sustained) / <INSTANT_MB, pause>MAX_PAUSE_S or RSS breach."""
    mem = _mem or memavail
    m = mem(); why = _hard_checks(m, _clock()) or G['hard']
    if why: term(m, why)
    if m >= PAUSE_MB: return m
    t0 = _clock(); G['paused'] = True; G['n_pause'] += 1
    log(f'MEMPAUSE memavail={m} pause_below={PAUSE_MB} resume_at={RESUME_MB}x{RESUME_HOLD_S}s ts={now_pt()} n={G["n_pause"]}')
    ok_since = None; last_log = t0
    while True:
        for _ in range(int(POLL_S if ok_since is None else min(POLL_S, 5))):  # 1s slices so a watcher-flagged TERM is acted on promptly
            _sleep(1)
            if G['hard'] or TERM_FLAG[0]: break
        m = mem(); now = _clock(); why = _hard_checks(m, now) or G['hard']
        if why: term(m, why)
        if now - t0 > MAX_PAUSE_S: term(m, f'paused>{MAX_PAUSE_S}s (paused_s={now - t0:.0f})')
        if TERM_FLAG[0]: log(f'MEMPAUSE interrupted by SIGTERM memavail={m}'); break
        if m >= RESUME_MB:
            if ok_since is None: ok_since = now
            if now - ok_since >= RESUME_HOLD_S: break
        else: ok_since = None
        if now - last_log >= 60: last_log = now; log(f'MEMPAUSE waiting memavail={m} paused_s={now - t0:.0f}')
    ps = _clock() - t0; G['paused'] = False; G['n_resume'] += 1; G['pause_s_total'] += ps
    log(f'MEMRESUME memavail={m} paused_s={ps:.0f} ts={now_pt()} n={G["n_resume"]}')
    try: F.s.close()  # drop pooled keep-alive sockets that may have gone stale while paused
    except Exception: pass
    return m
def _watch_tick(m, now):
    """one watcher reading: returns the flagged hard reason (also stored in G['hard'] for the main-thread gate) or None"""
    why = _hard_checks(m, now)
    if why and not G['hard']: G['hard'] = why; G['hard_t'] = now; log(f'MEMGUARD hard condition flagged: {why}')
    return G['hard']
def _mg():
    """watcher thread, polls every HARD_POLL_S (2s): feeds the debounced low-memory streak, tracks min MemAvail; on a hard condition flags
    it for the main-thread gate (which exits cleanly between requests), and force-exits after a 30s grace if the main thread does not
    reach a gate (e.g. stuck in a request). Never pauses or writes data itself."""
    t_cfg = t_stat = time.time()
    while True:
        try:
            m = memavail(); now = time.time(); _watch_tick(m, now)
            if G['hard'] and now - G['hard_t'] > 120 and memavail() < 1500: term(memavail(), G['hard'] + ' (watcher: main thread did not reach a gate within 120s, memavail<1500)')
            if now - t_cfg >= 60: t_cfg = now; load_cfg()
            if now - t_stat >= 300:
                t_stat = now; log(f'MEMSTAT memavail={m} min_memavail={G["min_mem"]} min_fetch={G["min_mem_fetch"]} min_paused={G["min_mem_paused"]} cfg=pause{PAUSE_MB}/resume{RESUME_MB}x{RESUME_HOLD_S}s rss={rss_mb()} pauses={G["n_pause"]} resumes={G["n_resume"]} paused_total_s={G["pause_s_total"]:.0f} low_streaks={G["n_streaks"]}')
        except Exception as e: log('memwatch error', repr(e)[:200])
        time.sleep(HARD_POLL_S)
TERM_FLAG = [False]
class Terminated(Exception): pass
def _on_sigterm(signum, frame):
    TERM_FLAG[0] = True; log('SIGTERM received: finishing the current CVDR id, then clean exit (resume-safe)')
class Stop(Exception): pass
# ---- HTTP timeouts (CoS 2026-10-04 20:13 PT): connect 10 s, read 60 s, total deadline 600 s (watchdog shuts a trickling socket);
#      up to 2 retries with backoff; a timeout counts as a strike toward the 3-consecutive stop (with 403/429/503).
CONNECT_S = 10; READ_S = 60; TOTAL_S = 600
class Deadline(Exception): pass
def is_timeout(e):
    return isinstance(e, (requests.exceptions.Timeout, Deadline, TimeoutError)) or 'timed out' in str(e).lower()
def fetch(session, url, connect=CONNECT_S, read=READ_S, total=TOTAL_S):
    import socket
    t0 = time.time(); r = session.get(url, timeout=(connect, read), allow_redirects=False, stream=True)
    fired = threading.Event()
    def _kill():
        fired.set()
        try:
            sock = None
            try: sock = r.raw._fp.fp.raw._sock
            except Exception: pass
            if sock is None: sock = getattr(getattr(r.raw, '_connection', None), 'sock', None)
            if sock is not None: sock.shutdown(socket.SHUT_RDWR)
        except Exception: pass
        try: r.raw.close()
        except Exception: pass
    wd = threading.Timer(max(0.1, total - (time.time() - t0)), _kill); wd.daemon = True; wd.start()
    try:
        buf = bytearray()
        try:
            for chunk in r.iter_content(65536):
                buf += chunk
                if time.time() - t0 > total: raise Deadline(f'total deadline {total}s exceeded ({len(buf)} bytes)')
        except Deadline: raise
        except Exception as e:
            if fired.is_set(): raise Deadline(f'total deadline {total}s exceeded ({len(buf)} bytes): {type(e).__name__}')
            raise
        if fired.is_set(): raise Deadline(f'total deadline {total}s exceeded ({len(buf)} bytes)')
        r._content = bytes(buf); r._content_consumed = True
    finally:
        wd.cancel(); r.close()
    return r
class Fetcher:
    def __init__(self):
        self.s = requests.Session(); self.s.headers['User-Agent'] = UA; self.last = 0.0; self.cbad = 0; self.nreq = 0; self.bk = 0
        self.stats = dict(http200=0, http404=0, fail=0, bad403_429_503=0, backoffs=0, timeouts=0)
    def backoff(self, why):
        w = min(BACKOFF_CAP, BACKOFF_BASE * (2 ** self.bk)); self.bk += 1; self.stats['backoffs'] += 1
        log(f'BACKOFF {w:.0f}s ({why}; step {self.bk})'); time.sleep(w)
    def get(self, path, timeout=(CONNECT_S, READ_S)):
        url = path if path.startswith('https://') else BASE + path
        if not url.startswith(BASE + '/'): raise ValueError('off-host url refused: ' + url)
        for att in range(3):
            mem_check()
            w = DELAY - (time.time() - self.last)
            if w > 0: time.sleep(w)
            self.last = time.time(); self.nreq += 1
            try: r = fetch(self.s, url, connect=timeout[0], read=timeout[1])
            except Exception as e:
                if is_timeout(e):
                    self.cbad += 1; self.stats['timeouts'] = self.stats.get('timeouts', 0) + 1
                    log(f'TIMEOUT strike consecutive={self.cbad}', url, repr(e)[:160])
                    if self.cbad >= 3: raise Stop(f'3 consecutive strikes (403/429/503/timeout) at {url}')
                    if att < 2: self.backoff('timeout')
                    continue
                log('ERR', url, repr(e)[:200])
                if att < 2: self.backoff('connection error')
                continue
            if r.status_code in (403, 429, 503):
                self.cbad += 1; self.stats['bad403_429_503'] += 1
                (PROBE / f'http{r.status_code}_{self.cbad}_{int(time.time())}.txt').write_text(f'GET {url}\nHTTP {r.status_code}\n{dict(r.headers)}\n\n{r.text[:3000]}')
                log(f'HTTP {r.status_code} consecutive={self.cbad}', url)
                if self.cbad >= 3: raise Stop(f'3 consecutive 403/429/503 at {url}')
                self.backoff(f'HTTP {r.status_code}'); continue
            self.cbad = 0
            if r.status_code in (301, 302, 303, 307, 308): log('REDIRECT (not followed)', url, r.headers.get('location')); return r
            if r.status_code >= 500: log('HTTP', r.status_code, url); self.backoff(f'HTTP {r.status_code}'); continue
            self.bk = 0
            if r.status_code == 200: self.stats['http200'] += 1
            elif r.status_code == 404: self.stats['http404'] += 1
            return r
        self.stats['fail'] += 1; return None
F = Fetcher()
# ---------------- authorities (TOOI registers from the KOOP repository) ----------------
T = 'https://identifier.overheid.nl/tooi/def/ont/'
def _v(x, k):
    return [y.get('@value', y.get('@id')) for y in (x.get(T + k) or []) if isinstance(y, dict)]
def norm_name(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\((gemeente|provincie|waterschap)\)', ' ', s)
    s = s.strip(); prev = None
    while prev != s: prev = s; s = re.sub(r'^(gemeente|provincie|waterschap|hoogheemraadschap|wetterskip|het|de|van)\s+', '', s).strip()
    return re.sub(r'[^a-z0-9]+', '', s)
class Authorities:
    def __init__(self):
        self.by_owms, self.by_name, self.orgs = {}, {}, {}
        today = datetime.date.today().isoformat()
        files = dict(Gemeente='rwc_gemeenten_compleet_5', Provincie='rwc_provincies_compleet_1', Waterschap='rwc_waterschappen_compleet_2')
        hist = []
        for typ, f in files.items():
            for x in json.load(open(REF / f'waardelijsten_{f}_json_{f}.json')):
                tps = [t.split('/')[-1] for t in x.get('@type', [])]
                if typ not in tps: continue
                code = (_v(x, 'organisatiecode') or [''])[0]
                if 'HistorischeVersie' in tps: hist.append((typ, code, x)); continue
                num = (_v(x, {'Gemeente': 'gemeentecode', 'Provincie': 'provinciecode', 'Waterschap': 'waterschapscode'}[typ]) or [code[2:]])[0]
                end = (_v(x, 'einddatum') or [None])[0]
                o = dict(type={'Gemeente': 'gemeente', 'Provincie': 'provincie', 'Waterschap': 'waterschap'}[typ], tooi_code=code, code=num,
                         jurisdiction={'Gemeente': 'NL-GM', 'Provincie': 'NL-PV', 'Waterschap': 'NL-WS'}[typ] + num,
                         name=(_v(x, 'officieleNaamInclSoort') or _v(x, 'label') or [''])[0], name_excl=(_v(x, 'officieleNaamExclSoort') or [''])[0],
                         tooi_uri=x.get('@id'), owms_uri=(_v(x, 'owmsId') or [None])[0], einddatum=end, current=(not end or end >= today))
                self.orgs[(typ, code)] = o
        for typ, code, x in hist:  # older names of an existing waterschap -> same entity
            if (typ, code) in self.orgs:
                o = self.orgs[(typ, code)]
                for k in ('owmsId',):
                    for u in _v(x, k): self.by_owms.setdefault(u, o)
                for n in _v(x, 'officieleNaamExclSoort') + _v(x, 'officieleNaamInclSoort'): self.by_name.setdefault((typ, norm_name(n)), o)
        # current orgs first so a reused name maps to the current entity
        for (typ, code), o in sorted(self.orgs.items(), key=lambda kv: not kv[1]['current']):
            if o['owms_uri']: self.by_owms.setdefault(o['owms_uri'], o)
            for n in (o['name'], o['name_excl'], (o['owms_uri'] or '').rsplit('/', 1)[-1].replace('_', ' ')):
                if n: self.by_name.setdefault((typ, norm_name(n)), o)
        self.n_current = {t: sum(1 for o in self.orgs.values() if o['type'] == t and o['current']) for t in ('gemeente', 'provincie', 'waterschap')}
    def match(self, owms_uri, scheme, creator):
        by_uri = self.by_owms.get(owms_uri) if owms_uri else None
        by_nm = self.by_name.get((scheme, norm_name(creator))) if scheme in ('Gemeente', 'Provincie', 'Waterschap') and creator else None
        o = by_uri or by_nm
        method = 'owms_uri+creator' if (by_uri and by_nm and by_uri is by_nm) else 'owms_uri' if by_uri else 'creator_name' if by_nm else None
        conflict = bool(by_uri and by_nm and by_uri is not by_nm)
        return o, method, conflict
AUTH = None
# ---------------- per-work processing ----------------
def gz_write(p, data):
    tmp = p.with_name(p.name + '.tmp'); tmp.write_bytes(gzip.compress(data, 6)); os.replace(tmp, p)
def get_manifest(i):
    p = RAWM / f'CVDR{i}.xml.gz'
    if p.exists(): return 200, gzip.decompress(p.read_bytes())
    r = F.get(f'/cvdr/CVDR{i}/manifest.xml')
    if r is None: return None, None
    if r.status_code == 200 and r.content.lstrip(b'\xef\xbb\xbf \t\r\n').startswith(b'<?xml'): gz_write(p, r.content); return 200, r.content  # strip UTF-8 BOM (fix 2026-10-14: BOM manifests were returned as None -> manifest_parse_fail)
    return r.status_code, None
def parse_manifest(raw):
    w = ET.fromstring(raw); md = w.find('metadata')
    g = lambda k: (md.find(k).text if md is not None and md.find(k) is not None else None)
    ex = []
    for e in w.findall('expression'):
        for m in e.findall('manifestation'):
            if m.get('label') != 'xml': continue
            for it in m.findall('item'):
                if (it.get('label') or '').endswith('.xml'): ex.append(dict(expr=e.get('label'), item=it.get('label'), deleted=it.get('_deleted') == 'true'))
    def k(x):
        try: return int(x['expr'])
        except Exception: return -1
    ex.sort(key=k, reverse=True)
    return dict(owms=g('organisatieOwmsURI'), latest=w.get('_latestItem'), generated=w.get('gegenereerd'), n_expr=len(w.findall('expression')),
                exprs=ex, creatiedatum=g('creatiedatum'))
def get_xml(i, e):
    p = RAWX / f"CVDR{i}_{e['expr']}.xml.gz"; url = f"{BASE}/cvdr/CVDR{i}/{e['expr']}/xml/{e['item']}"
    if p.exists(): return gzip.decompress(p.read_bytes()), url, True
    if (RAWX.parent / 'stop' / f"CVDR{i}_{e['expr']}.xml.gz").exists(): return None, url, 'stop'
    r = F.get(url)
    head = r.content.lstrip(b'\xef\xbb\xbf \t\r\n')[:200] if r is not None else b''
    if r is not None and r.status_code == 200 and head.startswith(b'<lvbbu:'):  # STOP/LVBB consolidation XML (Omgevingswet era): cache for a later STOP splitter
        gz_write(RAWX.parent / 'stop' / f"CVDR{i}_{e['expr']}.xml.gz", r.content); return None, url, 'stop'
    if r is None or r.status_code != 200 or not (head.startswith(b'<?xml') or head.startswith(b'<cvdr')):
        log('XMLFAIL', url, getattr(r, 'status_code', None), 'len', len(r.content) if r is not None else None, 'head', repr(head[:80]))
        if r is not None and r.status_code == 200: (PROBE / f"xmlfail_CVDR{i}_{e['expr']}.bin").write_bytes(r.content[:20000])
        return None, url, False
    gz_write(p, r.content); return r.content, url, False
TYPE_RE = [('apv', r'algemene plaatselijke verordening'), ('verordening', r'verordening|keur\b|keur '), ('beleidsregel', r'beleidsregel|beleidsregels|beleidslijn|beleidsnota|beleidskader'),
           ('reglement', r'reglement'), ('mandaat', r'mandaat|volmacht|machtiging'), ('subsidieregeling', r'subsidie'), ('besluit', r'besluit'), ('regeling', r'regeling')]
def reg_type(meta):
    rb = (meta.get('rubriek') or '').lower(); ti = ((meta.get('title') or '') + ' ' + (meta.get('alternative') or '')).lower()
    if 'verordening' in rb: base = 'verordening'
    elif 'beleidsregel' in rb: base = 'beleidsregel'
    elif rb: base = rb
    else: base = None
    for k, rx in TYPE_RE:
        if re.search(rx, ti): return (base or k) if k != 'apv' else 'apv'
    return base or 'overig'
def build_law(i, man, e, url, raw, meta, auth, method, rows, st, full, valid_on, fetched_at):
    law_id = f'CVDR{i}'
    md = dict(metadata=dict(license=LICENSE, retrieved_at=fetched_at, official_id=meta.get('identifier'), publisher='KOOP/overheid.nl',
              source_name='repository.officiele-overheidspublicaties.nl (CVDR)', collection='CVDR', cvdr_work=law_id, cvdr_expression=e['expr'],
              cvdr_n_expressions=man['n_expr'], manifest_url=f'{BASE}/cvdr/{law_id}/manifest.xml', manifest_generated=man['generated'],
              authority=auth['name'], authority_type=auth['type'], authority_code=auth['tooi_code'], authority_jurisdiction=auth['jurisdiction'],
              authority_tooi_uri=auth['tooi_uri'], authority_owms_uri=auth['owms_uri'], authority_match=method,
              creator_scheme=meta.get('creator_scheme'), creator=meta.get('creator'), manifest_organisatie_owms=man['owms'],
              regulation_type=reg_type(meta), rubriek=meta.get('rubriek'), informatietype=meta.get('informatietype'), ratified_by=meta.get('ratified_by'),
              subject=meta.get('subject'), alternative_title=meta.get('alternative'), modified=meta.get('modified'), issued=meta.get('issued'),
              geldig_van=meta.get('inwerkingtreding'), geldig_tot=meta.get('uitwerkingtreding'), terugwerkende_kracht=meta.get('terugwerkendekracht'),
              betreft=meta.get('betreft'), kenmerk=meta.get('kenmerk'), onderwerp=meta.get('onderwerp'), is_format_of=meta.get('is_format_of'),
              is_format_of_url=meta.get('is_format_of_url'), externe_bijlagen=meta.get('externe_bijlagen') or [], rights=meta.get('rights'), valid_on=valid_on, in_force=True,
              split=dict(n_article=st['n_article'], n_annex=st['n_annex'], n_section=st['n_section'], oper_chars=st['oper_chars'], row_chars=st['row_chars'],
                         toelichting_chars=st.get('toelichting_chars', 0))))
    return dict(id=law_id, title=meta.get('title') or meta.get('alternative') or law_id, text=full, source_url=url, source_type='decentral_regulation',
                jurisdiction=auth['jurisdiction'], country='Netherlands', language=meta.get('language') or 'nl', eli=None,
                date=meta.get('inwerkingtreding'), date_issued=meta.get('issued'), retrieved_at=fetched_at, license=LICENSE, law_status='current',
                identifier=law_id, official_identifier=meta.get('identifier'), article_count=len(rows), json_path=str(OUTL / f'{law_id}.json.gz'),
                metadata_json=json.dumps(md, ensure_ascii=False))
def process_id(i):
    st_, man_raw = get_manifest(i)
    if st_ is None: return dict(id=i, s='fetch_fail_manifest')
    if st_ == 404: return dict(id=i, s='absent')
    if st_ != 200: return dict(id=i, s=f'manifest_http{st_}')
    try: man = parse_manifest(man_raw)
    except Exception as e: return dict(id=i, s='manifest_parse_fail', err=repr(e)[:200])
    rec = dict(id=i, s=None, owms=man['owms'], n_expr=man['n_expr'])
    cands = [e for e in man['exprs'] if not e['deleted']]
    if not cands: rec['s'] = 'no_xml'; return rec
    today = datetime.date.today().isoformat(); chosen = None; tried = []
    for e in cands[:4]:
        raw, url, cached = get_xml(i, e)
        if raw is None and cached == 'stop': rec['s'] = 'stop_lvbb_xml_unsupported'; rec['expr'] = e['expr']; return rec
        if raw is None: rec['s'] = 'fetch_fail_xml'; rec['expr'] = e['expr']; return rec
        try: meta = nlm_split.parse_meta(raw)
        except Exception as ex: rec['s'] = 'xml_parse_fail'; rec['err'] = repr(ex)[:200]; return rec
        inw, uit = meta.get('inwerkingtreding'), meta.get('uitwerkingtreding'); tried.append(e['expr'])
        if inw and inw > today: rec.setdefault('future_exprs', []).append(e['expr']); continue
        chosen = (e, url, raw, meta); break
    if chosen is None: rec['s'] = 'future_only'; rec['tried'] = tried; return rec
    e, url, raw, meta = chosen
    inw, uit = meta.get('inwerkingtreding'), meta.get('uitwerkingtreding')
    rec.update(expr=e['expr'], inw=inw, uit=uit, scheme=meta.get('creator_scheme'), creator=meta.get('creator'), rubriek=meta.get('rubriek'), rtype=reg_type(meta))
    keep = False
    try:
        if uit and uit <= today: rec['s'] = 'expired'; return rec
        auth, method, conflict = AUTH.match(man['owms'], meta.get('creator_scheme'), meta.get('creator'))
        if conflict: rec['auth_conflict'] = True
        if auth is None: rec['s'] = 'in_force_out_of_scope'; rec['why'] = f"unmapped scheme={meta.get('creator_scheme')}"; return rec
        rec.update(auth=auth['tooi_code'], jur=auth['jurisdiction'], atype=auth['type'], amethod=method)
        if not auth['current']: rec['s'] = 'in_force_out_of_scope'; rec['why'] = 'former_authority'; return rec
        try: rows, st, full = nlm_split.split_cvdr(raw, f'CVDR{i}', url, e['expr'])
        except Exception as ex: rec['s'] = 'split_fail'; rec['err'] = repr(ex)[:200]; keep = True; return rec
        if not rows:  # in force + in scope, but the XML carries no operative text (content only in externe bijlagen, e.g. AGV peilbesluiten): index only
            rec['s'] = 'in_force_no_text_in_xml'; rec['externe_bijlagen'] = meta.get('externe_bijlagen'); rec['title'] = (meta.get('title') or '')[:200]; return rec
        fetched_at = datetime.datetime.fromtimestamp((RAWX / f"CVDR{i}_{e['expr']}.xml.gz").stat().st_mtime, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        law = build_law(i, man, e, url, raw, meta, auth, method, rows, st, full, today, fetched_at)
        tmp = OUTA / f'CVDR{i}.jsonl.gz.tmp'
        with gzip.open(tmp, 'wt', encoding='utf-8') as f:
            for r in rows: f.write(json.dumps(r, ensure_ascii=False) + '\n')
        os.replace(tmp, OUTA / f'CVDR{i}.jsonl.gz')
        gz_write(OUTL / f'CVDR{i}.json.gz', json.dumps(law, ensure_ascii=False).encode())
        keep = True
        rec.update(s='ok', rows=len(rows), n_article=st['n_article'], n_annex=st['n_annex'], n_section=st['n_section'], oper_chars=st['oper_chars'], row_chars=st['row_chars'])
        return rec
    finally:
        if not keep:  # keep raw xml only for in-force in-scope works (lean disk); manifests are kept
            for x in RAWX.glob(f'CVDR{i}_*.xml.gz'):
                try: x.unlink()
                except Exception: pass
# ---------------- scanning ----------------
def chunk_path(hi): return SCAN / f'{hi:06d}.jsonl.gz'
def run_chunk(hi, lo, res, t0, counter, total):
    recs = []
    for i in range(hi, lo - 1, -1) if hi >= lo else []:
        if TERM_FLAG[0]: raise Terminated(f'SIGTERM at id {i} (chunk {hi}-{lo} not written; caches kept)')
        mem_check()
        if TERM_FLAG[0]: raise Terminated(f'SIGTERM at id {i} (chunk {hi}-{lo} not written; caches kept)')
        try: rec = process_id(i)
        except (Stop, Terminated): raise
        except Exception as e: rec = dict(id=i, s=f'error_{type(e).__name__}', err=repr(e)[:200]); log('ERROR', i, repr(e)[:300])
        recs.append(rec); res[rec['s']] = res.get(rec['s'], 0) + 1; counter[0] += 1
        if counter[0] % 100 == 0:
            el = time.time() - t0; rate = el / max(1, counter[0]); left = (total - counter[0]) * rate if total else 0
            log('progress', counter[0], '/', total or '?', 'id', i, res, 'nreq', F.nreq, F.stats, f'{rate:.2f}s/id', f'eta_h={left/3600:.1f}', f'mem={memavail()}MB')
    return recs
def _fsync_dir(d):
    fd = os.open(str(d), os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)
def write_chunk(hi, recs):
    tmp = chunk_path(hi).with_name(chunk_path(hi).name + '.tmp')   # <hi>.jsonl.gz.tmp
    assert len(recs) == len({r['id'] for r in recs}), 'duplicate ids in chunk'
    CUR_TMP.add(str(tmp))
    try:
        with open(tmp, 'wb') as raw:
            with gzip.open(raw, 'wt') as f:
                for r in recs: f.write(json.dumps(r, ensure_ascii=False) + '\n')
            raw.flush(); os.fsync(raw.fileno())
        os.replace(tmp, chunk_path(hi)); _fsync_dir(SCAN)
    finally:
        CUR_TMP.discard(str(tmp))
        if tmp.exists():
            try: tmp.unlink()
            except Exception: pass
    log('CHUNK written', chunk_path(hi).name, 'ids', len(recs), f'{recs[0]["id"] if recs else None}..{recs[-1]["id"] if recs else None}')
def desc_chunks(top):
    hi = top
    while hi >= 1:
        lo = max(1, hi - CHUNK + 1); yield hi, lo; hi = lo - 1
def load_scan():
    out = []
    for p in sorted(SCAN.glob('*.jsonl.gz')):
        with gzip.open(p, 'rt') as f: out += [json.loads(l) for l in f]
    return out
def scan(mode, max_chunks=None, quota=None):
    res = {}; t0 = time.time(); counter = [0]; done_chunks = 0; capped = False
    if mode == 'full':
        max_chunks = int(os.environ.get('NLM_MAX_CHUNKS', '0')) or max_chunks
    max_wall = float(os.environ.get('NLM_MAX_WALL_S', '0') or 0)
    todo = [(hi, lo) for hi, lo in desc_chunks(TOP) if not chunk_path(hi).exists()]
    # 2026-10-12 CoS 10:59 PM PT: NLM_SKIP_HI='<top>:<bottom>' = chunk-hi range already held on other disks (disk_ranges.json); not re-scraped, nothing faked
    _sk = os.environ.get('NLM_SKIP_HI', '')
    if _sk:
        _a, _b = (int(x) for x in _sk.split(':')); assert _a >= _b and (TOP - _a) % CHUNK == 0 and (TOP - _b) % CHUNK == 0, _sk
        _n0 = len(todo); todo = [(hi, lo) for hi, lo in todo if not (_b <= hi <= _a)]
        log('SKIP_REMOTE chunk hi', _a, '..', _b, 'skipped', _n0 - len(todo), 'chunks (held on other disks per disk_ranges.json)')
    total = sum(hi - lo + 1 for hi, lo in todo)
    log('SCAN', mode, 'top', TOP, 'chunks_todo', len(todo), 'ids_todo', total, 'done_chunks', len(list(SCAN.glob('*.jsonl.gz'))))
    for hi, lo in todo:
        recs = run_chunk(hi, lo, res, t0, counter, total); write_chunk(hi, recs); done_chunks += 1
        if mode == 'full':
            try: set_pin(nlm_next_hi=lo - 1)   # 2026-10-10: PIN tracks the flushed resume hi on every chunk
            except Exception: pass
        if mode == 'full' and done_chunks % 5 == 0:
            try: set_pin(nlm_progress=f'ids {counter[0]}/{total} (cursor id {lo}) {res}', nlm_cursor_id=lo, nlm_memavail_mb=memavail(), nlm_rss_mb=rss_mb(), nlm_nreq=F.nreq)
            except Exception: pass
        if quota and quota(load_scan()): log('quota met after', done_chunks, 'chunks'); break
        if max_chunks and done_chunks >= max_chunks: log('max_chunks reached'); capped = True; break
        if max_wall and time.time() - t0 >= max_wall: log(f'CAP wall {max_wall:.0f}s reached after {done_chunks} chunks'); capped = True; break
    if capped and mode == 'full': log('CAPPED test run: tail + retry passes skipped'); return res, time.time() - t0
    if mode == 'full':  # tail: works created above TOP during the run
        miss, i, tail = 0, TOP + 1, []
        while miss < TAIL_MISS:
            rec = process_id(i); tail.append(rec); res[rec['s']] = res.get(rec['s'], 0) + 1
            miss = miss + 1 if rec['s'] == 'absent' else 0; i += 1
            if len(tail) % 100 == 0: log('tail progress', i, res, f'mem={memavail()}MB')
        tp = SCAN / f'tail_{TOP + 1:06d}_{i - 1:06d}.jsonl.gz'
        tpt = tp.with_name(tp.name + '.tmp'); CUR_TMP.add(str(tpt))
        try:
            with gzip.open(tpt, 'wt') as f:
                for r in tail: f.write(json.dumps(r, ensure_ascii=False) + '\n')
            os.replace(tpt, tp)
        finally:
            CUR_TMP.discard(str(tpt))
            if tpt.exists(): tpt.unlink()
        # retry pass: transient fetch failures / errors recorded in completed chunk files are retried once
        nretry = 0; _rsd = rescan_done_ids()  # 2026-10-14: ids already recovered in rescan_bom/ are not re-fetched / rewritten here
        for p in sorted(SCAN.glob('*.jsonl.gz')):
            with gzip.open(p, 'rt') as f: recs = [json.loads(l) for l in f]
            bad = [k for k, r in enumerate(recs) if (r['s'].startswith('fetch_fail') or r['s'].startswith('error_') or r['s'] == 'manifest_parse_fail') and r['id'] not in _rsd]  # 2026-10-14: re-try BOM-skipped manifests (ids 600600-640398)
            if not bad: continue
            for k in bad:
                r2 = process_id(recs[k]['id']); r2['retried'] = True; recs[k] = r2; nretry += 1
                res['retry_' + r2['s']] = res.get('retry_' + r2['s'], 0) + 1
            tmp = p.with_name(p.name + '.tmp'); CUR_TMP.add(str(tmp))
            try:
                with gzip.open(tmp, 'wt') as f:
                    for r in recs: f.write(json.dumps(r, ensure_ascii=False) + '\n')
                os.replace(tmp, p)
            finally:
                CUR_TMP.discard(str(tmp))
                if tmp.exists(): tmp.unlink()
        log('retry pass done', nretry, f'mem={memavail()}MB')
    return res, time.time() - t0
# ---------------- targeted id-list rescan (2026-10-14 CoS: BOM-skipped manifests) ----------------
# NLM_IDLIST=<file> (one CVDR id per line) with mode 'full': fetch ONLY listed ids, grouped by the fixed 200-id chunk grid from TOP; each
# group -> RESCAN/<hi>.jsonl.gz (atomic .tmp+fsync+os.replace+dir fsync; existing files = done, skipped on restart). Same guard/strikes/PIN.
# index/scan chunks are never touched. Progress in RESCAN/state.json (status pending|done). After done, the SAME process continues the main
# scan (scan('full')) so the single slot never idles and no relaunch is needed.
RESCAN = Path(os.environ.get('NLM_RESCAN_DIR', str(B / 'index' / 'rescan_bom'))); RESCAN_STATE = RESCAN / 'state.json'
def grid_hi(i): return TOP - ((TOP - i) // CHUNK) * CHUNK
def _rescan_state(**u):
    try: d = json.load(open(RESCAN_STATE))
    except Exception: d = {}
    d.update(u); d['updated_pt'] = now_pt(); t = RESCAN_STATE.with_name('state.json.tmp')
    with open(t, 'w') as f: json.dump(d, f, indent=1); f.flush(); os.fsync(f.fileno())
    os.replace(t, RESCAN_STATE); _fsync_dir(RESCAN); return d
def rescan_idlist(path):
    RESCAN.mkdir(parents=True, exist_ok=True)
    ids = sorted({int(x) for x in open(path).read().split() if x.strip().isdigit() and 1 <= int(x) <= TOP}, reverse=True)
    groups = {}
    for i in ids: groups.setdefault(grid_hi(i), []).append(i)
    todo = [(hi, g) for hi, g in sorted(groups.items(), reverse=True) if not (RESCAN / f'{hi:06d}.jsonl.gz').exists()]
    res = {}; t0 = time.time(); counter = [0]; total = sum(len(g) for _, g in todo)
    _rescan_state(status='pending', idlist=str(path), n_ids=len(ids), n_groups=len(groups), groups_todo_at_start=len(todo), pid=os.getpid())
    log('RESCAN idlist', path, 'ids', len(ids), 'groups', len(groups), 'groups_todo', len(todo), 'ids_todo', total, 'dir', RESCAN)
    for hi, g in todo:
        recs = []
        for i in g:
            if TERM_FLAG[0]: raise Terminated(f'SIGTERM at id {i} (rescan group {hi} not written; caches kept)')
            mem_check()
            if TERM_FLAG[0]: raise Terminated(f'SIGTERM at id {i} (rescan group {hi} not written; caches kept)')
            try: rec = process_id(i)
            except (Stop, Terminated): raise
            except Exception as e: rec = dict(id=i, s=f'error_{type(e).__name__}', err=repr(e)[:200]); log('ERROR', i, repr(e)[:300])
            rec['rescan'] = 'bom_20261014'; recs.append(rec); res[rec['s']] = res.get(rec['s'], 0) + 1; counter[0] += 1
            if counter[0] % 100 == 0:
                el = time.time() - t0; log('rescan progress', counter[0], '/', total, 'id', i, res, 'nreq', F.nreq, F.stats, f'{el / counter[0]:.2f}s/id', f'mem={memavail()}MB')
        p = RESCAN / f'{hi:06d}.jsonl.gz'; tmp = p.with_name(p.name + '.tmp'); CUR_TMP.add(str(tmp))
        try:
            with open(tmp, 'wb') as raw:
                with gzip.open(raw, 'wt') as f:
                    for r in recs: f.write(json.dumps(r, ensure_ascii=False) + '\n')
                raw.flush(); os.fsync(raw.fileno())
            os.replace(tmp, p); _fsync_dir(RESCAN)
        finally:
            CUR_TMP.discard(str(tmp))
            if tmp.exists():
                try: tmp.unlink()
                except Exception: pass
        log('CHUNK written rescan_bom/' + p.name, 'ids', len(recs), f'{recs[0]["id"]}..{recs[-1]["id"]}', 'run_res', res)
        try: set_pin(nlm_rescan=f'BOM rescan: group {hi} written; run {counter[0]}/{total} ids {res}')
        except Exception: pass
    # completion: all groups present -> done (counts over every rescan file)
    left = [hi for hi in groups if not (RESCAN / f'{hi:06d}.jsonl.gz').exists()]
    if not left:
        tot = {}
        for f in RESCAN.glob('*.jsonl.gz'):
            with gzip.open(f, 'rt') as fh:
                for l in fh: s_ = json.loads(l)['s']; tot[s_] = tot.get(s_, 0) + 1
        _rescan_state(status='done', done_pt=now_pt(), totals=tot, pid=None); log('RESCAN DONE totals', tot, 'run_res', res)
        try: set_pin(nlm_rescan=f'BOM rescan DONE {now_pt()} totals {tot}')
        except Exception: pass
    return res
def rescan_done_ids():
    """ids whose rescan record is no longer manifest_parse_fail (used to keep the end-of-scan retry pass off them)"""
    out = set()
    for f in RESCAN.glob('*.jsonl.gz') if RESCAN.exists() else []:
        with gzip.open(f, 'rt') as fh:
            for l in fh:
                r = json.loads(l)
                if r['s'] != 'manifest_parse_fail': out.add(r['id'])
    return out
# ---------------- hand check ----------------
def hc_quota(recs):
    ok = [r for r in recs if r.get('s') == 'ok']
    by = {t: [r for r in ok if r.get('atype') == t] for t in ('gemeente', 'provincie', 'waterschap')}
    types = {r.get('rtype') for r in ok}
    return len(by['gemeente']) >= 12 and len(by['provincie']) >= 4 and len(by['waterschap']) >= 4 and len(types) >= 4
def pick20(recs):
    ok = [r for r in recs if r.get('s') == 'ok']; sel = []
    for t, n in (('provincie', 4), ('waterschap', 4), ('gemeente', 12)):
        pool = sorted([r for r in ok if r.get('atype') == t], key=lambda r: r['id'], reverse=True); got = []
        while len(got) < n and pool:  # round-robin over regulation types, distinct authorities first
            seen_t = {g['rtype'] for g in got}; seen_a = {g['auth'] for g in got}
            best = sorted(pool, key=lambda r: ((r['rtype'] in seen_t), (r['auth'] in seen_a), -r['id']))[0]
            got.append(best); pool.remove(best)
        sel += got
    if len(sel) < 20:  # a type short of its quota -> fill from the remaining in-scope rows (flagged in the report)
        rest = sorted([r for r in ok if r not in sel], key=lambda r: -r['id']); sel += rest[:20 - len(sel)]
    return sel
def handcheck():
    res, secs = scan('handcheck', max_chunks=int(os.environ.get('NLM_HC_MAX_CHUNKS', '12')), quota=hc_quota)
    return hc_report(secs)
def check_one(r):
        lid = f"CVDR{r['id']}"; raw = gzip.decompress((RAWX / f"{lid}_{r['expr']}.xml.gz").read_bytes())
        rows = [json.loads(l) for l in gzip.open(OUTA / f'{lid}.jsonl.gz', 'rt', encoding='utf-8')]
        ind = nlm_split.independent_counts(raw)
        n_art = sum(1 for x in rows if x['record_type'] == 'article'); n_bij = sum(1 for x in rows if x['record_type'] == 'annex')
        empty = sum(1 for x in rows if not (x['text'] or '').strip() or x['text'].strip() == '[geen tekst in bron-XML]')
        rows_nows = sum(len(re.sub(r'\s+', '', x['text'])) for x in rows)
        cov = nlm_split.word_coverage(rows, ind)
        return dict(law_id=lid, art_ok=(n_art == ind['n_artikel'] and n_bij == ind['n_bijlage']), empty=empty, norows=not rows,
                    uniq=len({x['id'] for x in rows}) == len(rows), cov=round(cov, 4))
def _has_out(r): return (OUTL / f"CVDR{r['id']}.json.gz").exists() and (OUTA / f"CVDR{r['id']}.jsonl.gz").exists()
def hc_report(secs=0):
    # 2026-10-05: out/ was lost in the box restore (scan + raw came back); out was rebuilt offline from raw. Rows with s=ok but no out files
    # (e.g. expired since the scan, not rebuilt) are excluded from pick20 and the all-collected re-check and reported as ok_missing_out.
    recs = load_scan(); ok_missing_out = [r['id'] for r in recs if r.get('s') == 'ok' and not _has_out(r)]
    sel = pick20([r for r in recs if r.get('s') != 'ok' or _has_out(r)]); checks = []
    for r in sel:
        lid = f"CVDR{r['id']}"; raw = gzip.decompress((RAWX / f"{lid}_{r['expr']}.xml.gz").read_bytes())
        rows = [json.loads(l) for l in gzip.open(OUTA / f'{lid}.jsonl.gz', 'rt', encoding='utf-8')]
        law = json.loads(gzip.decompress((OUTL / f'{lid}.json.gz').read_bytes())); lm = json.loads(law['metadata_json'])['metadata']
        ind = nlm_split.independent_counts(raw); meta = nlm_split.parse_meta(raw)
        n_art = sum(1 for x in rows if x['record_type'] == 'article'); n_bij = sum(1 for x in rows if x['record_type'] == 'annex')
        ids = [x['id'] for x in rows]; empty = [x['id'] for x in rows if not (x['text'] or '').strip() or x['text'].strip() == '[geen tekst in bron-XML]']
        rows_nows = sum(len(re.sub(r'\s+', '', x['text'])) for x in rows)
        cov = nlm_split.word_coverage(rows, ind); char_ratio = round(rows_nows / ind['oper_chars_nows'], 4) if ind['oper_chars_nows'] else None
        # authority: independent recheck from raw sources (manifest owms URI and XML creator) vs TOOI register entry
        auth = AUTH.orgs[(lm['authority_type'].capitalize(), lm['authority_code'])]
        man = parse_manifest(gzip.decompress((RAWM / f'{lid}.xml.gz').read_bytes()))
        # manifest owms URI: equal to the register owmsId, or an alias unknown to the register (e.g. 'wsagv') = no conflict; mapping to ANOTHER org = conflict
        owms_ok = (man['owms'] == auth['owms_uri']) if man['owms'] else None
        owms_conflict = bool(man['owms'] and man['owms'] in AUTH.by_owms and AUTH.by_owms[man['owms']] is not auth)
        name_ok = norm_name(meta['creator']) in {norm_name(auth['name']), norm_name(auth['name_excl'])} and meta['creator_scheme'].lower() == auth['type']
        prefix = {'gemeente': 'NL-GM', 'provincie': 'NL-PV', 'waterschap': 'NL-WS'}[auth['type']]
        jur_ok = law['jurisdiction'] == prefix + auth['code'] and auth['current']
        art_ok = (n_art == ind['n_artikel']) and (n_bij == ind['n_bijlage'])
        c = dict(law_id=lid, expression=r['expr'], title=law['title'][:120], authority=auth['name'], authority_type=auth['type'], jurisdiction=law['jurisdiction'],
                 regulation_type=lm['regulation_type'], rubriek=lm['rubriek'], geldig_van=lm['geldig_van'], geldig_tot=lm['geldig_tot'],
                 rows=len(rows), rows_article=n_art, rows_annex=n_bij, rows_section=len(rows) - n_art - n_bij, xml_artikel=ind['n_artikel'], xml_bijlage=ind['n_bijlage'],
                 article_count_ok=art_ok, law_article_count_ok=law['article_count'] == len(rows), empty_rows=len(empty), ids_unique=len(set(ids)) == len(ids),
                 coverage=round(cov, 4), coverage_ok=cov >= 0.95, char_ratio_rows_vs_oper=char_ratio, owms_uri_match=owms_ok, creator_name_match=name_ok, jurisdiction_ok=jur_ok,
                 owms_conflict=owms_conflict, authority_ok=bool(jur_ok and name_ok and not owms_conflict), source_url=law['source_url'])
        c['pass'] = all([c['article_count_ok'], c['law_article_count_ok'], c['empty_rows'] == 0, c['ids_unique'], c['coverage_ok'], c['authority_ok']])
        checks.append(c)
    by_s = {}
    for r in recs: by_s[r['s']] = by_s.get(r['s'], 0) + 1
    ok = [r for r in recs if r['s'] == 'ok' and _has_out(r)]
    allc = [check_one(r) for r in ok]  # same checks over EVERY in-scope regulation collected so far (offline)
    all_ok = dict(n=len(allc), art_count_mismatch=[c['law_id'] for c in allc if not c['art_ok']], with_empty_rows=[c['law_id'] for c in allc if c['empty'] or c['norows']],
                  dup_ids=[c['law_id'] for c in allc if not c['uniq']], coverage_lt_095=[(c['law_id'], c['cov']) for c in allc if c['cov'] < 0.95],
                  coverage_min=min([c['cov'] for c in allc], default=None), coverage_mean=round(sum(c['cov'] for c in allc) / max(1, len(allc)), 4))
    summ = dict(generated=now_pt(), mode='handcheck', ids_scanned=len(recs), id_range=[min(r['id'] for r in recs), max(r['id'] for r in recs)] if recs else None,
                scan_status_counts=by_s, ok_by_authority_type={t: sum(1 for r in ok if r.get('atype') == t) for t in ('gemeente', 'provincie', 'waterschap')},
                nreq=F.nreq, http=F.stats, seconds=round(secs), n_checked=len(checks), n_pass=sum(c['pass'] for c in checks),
                all_pass=len(checks) == 20 and all(c['pass'] for c in checks), authorities_current=AUTH.n_current,
                selected_by_type={t: sum(1 for c in checks if c['authority_type'] == t) for t in ('gemeente', 'provincie', 'waterschap')},
                all_collected_offline_check=all_ok, ok_missing_out=dict(n=len(ok_missing_out), ids=ok_missing_out[:100]), checks=checks)
    json.dump(summ, open(B / 'handcheck_prerun.json', 'w'), indent=1, ensure_ascii=False)
    L = [f"# NL municipal (CVDR) hand check pre-run — {summ['generated']}", '',
         f"IDs scanned: {summ['ids_scanned']} (range {summ['id_range']}), requests {F.nreq}, {summ['seconds']}s. Scan status: {by_s}",
         f"In-force in-scope by authority type: {summ['ok_by_authority_type']}. Current authorities in TOOI registers: {AUTH.n_current}",
         f"**{summ['n_pass']}/{summ['n_checked']} pass** (all_pass={summ['all_pass']}); selected by type {summ['selected_by_type']}",
         f"Offline re-check of ALL {all_ok['n']} collected in-scope regulations: art-count mismatches {len(all_ok['art_count_mismatch'])}, with empty rows {len(all_ok['with_empty_rows'])}, dup ids {len(all_ok['dup_ids'])}, coverage<0.95 {len(all_ok['coverage_lt_095'])} (min {all_ok['coverage_min']}, mean {all_ok['coverage_mean']})", '',
         '| law_id | type | authority | jurisdiction | reg type | rows (art/bij/sec) | XML artikel/bijlage | art ok | empty | uniq | coverage | auth ok | pass |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for c in checks:
        L.append(f"| {c['law_id']}_{c['expression']} | {c['authority_type']} | {c['authority']} | {c['jurisdiction']} | {c['regulation_type']} | {c['rows']} ({c['rows_article']}/{c['rows_annex']}/{c['rows_section']}) | {c['xml_artikel']}/{c['xml_bijlage']} | {c['article_count_ok']} | {c['empty_rows']} | {c['ids_unique']} | {c['coverage']:.3f} | {c['authority_ok']} | {'PASS' if c['pass'] else 'FAIL'} |")
    L += ['', 'Titles:'] + [f"- {c['law_id']}: {c['title']} (geldig {c['geldig_van']} – {c['geldig_tot'] or 'onbepaald'}; {c['rubriek']})" for c in checks]
    open(B / 'handcheck_prerun.md', 'w').write('\n'.join(L) + '\n')
    log('HANDCHECK', summ['n_pass'], '/', summ['n_checked'], 'all_pass', summ['all_pass'])
    return summ
# ---------------- offline: resplit / build ----------------
def resplit():
    n = 0
    for p in sorted(OUTL.glob('*.json.gz')):
        mem_check(); law = json.loads(gzip.decompress(p.read_bytes())); lm = json.loads(law['metadata_json'])['metadata']
        raw = gzip.decompress((RAWX / f"{law['id']}_{lm['cvdr_expression']}.xml.gz").read_bytes())
        rows, st, full = nlm_split.split_cvdr(raw, law['id'], law['source_url'], lm['cvdr_expression'])
        tmp = OUTA / f"{law['id']}.jsonl.gz.tmp"
        with gzip.open(tmp, 'wt', encoding='utf-8') as f:
            for r in rows: f.write(json.dumps(r, ensure_ascii=False) + '\n')
        os.replace(tmp, OUTA / f"{law['id']}.jsonl.gz"); law['article_count'] = len(rows); law['text'] = full
        gz_write(p, json.dumps(law, ensure_ascii=False).encode()); n += 1
    log('RESPLIT done', n)
def build(out_dir):
    import pyarrow as pa, pyarrow.parquet as pq
    src_l, src_a = OUTL, OUTA  # build input = live out/ (laws/ + articles/)
    LS = pq.read_schema(NAT / 'laws.parquet'); AS = pq.read_schema(NAT / 'articles.parquet')
    os.makedirs(f'{out_dir}/data', exist_ok=True)
    lw = pq.ParquetWriter(f'{out_dir}/data/laws.parquet', LS, compression='zstd'); aw = pq.ParquetWriter(f'{out_dir}/data/articles.parquet', AS, compression='zstd')
    lb, ab, nl, na = [], [], 0, 0
    for p in sorted(src_l.glob('*.json.gz')):
        law = json.loads(gzip.decompress(p.read_bytes())); lb.append({k: law.get(k) for k in LS.names}); nl += 1
        with gzip.open(src_a / f"{law['id']}.jsonl.gz", 'rt', encoding='utf-8') as f:
            for l in f: r = json.loads(l); ab.append({k: r.get(k) for k in AS.names}); na += 1
        if len(ab) >= 20000: aw.write_table(pa.Table.from_pylist(ab, schema=AS)); ab = []; mem_check()
        if len(lb) >= 2000: lw.write_table(pa.Table.from_pylist(lb, schema=LS)); lb = []
    if ab: aw.write_table(pa.Table.from_pylist(ab, schema=AS))
    if lb: lw.write_table(pa.Table.from_pylist(lb, schema=LS))
    aw.close(); lw.close(); log('BUILD', out_dir, 'laws', nl, 'articles', na)
    del aw, lw; import pa_exit_guard; pa_exit_guard.release()  # exit guard (pa_exit_guard): writers closed first, then dropped + gc
def main():
    global MODE, AUTH
    MODE = sys.argv[1]
    for d in (RAWM, RAWX, RAWX.parent / 'stop', OUTA, OUTL, SCAN, PROBE): d.mkdir(parents=True, exist_ok=True)
    if MODE == 'build': return build(sys.argv[2])
    load_cfg(quiet=True); import signal; signal.signal(signal.SIGTERM, _on_sigterm)
    threading.Thread(target=_mg, daemon=True).start(); AUTH = Authorities()
    if MODE == 'resplit': return resplit()
    log('START', MODE, 'pid', os.getpid(), f'mem={memavail()}MB', 'host', HOST, 'delay', DELAY, 'rss_limit_mb', RSS_MB, 'guard', cfg_dict(), 'no_pin', NO_PIN, 'caps', dict(max_chunks=os.environ.get('NLM_MAX_CHUNKS'), max_wall_s=os.environ.get('NLM_MAX_WALL_S')), 'top', TOP, 'authorities_current', AUTH.n_current)
    if MODE == 'handcheck': handcheck(); return
    if MODE == 'hcreport': hc_report(); return
    if MODE != 'full': sys.exit('usage: handcheck | full | resplit | build <dir>')
    try:
        _il = os.environ.get('NLM_IDLIST')
        if _il:
            log('MODE rescan_idlist', _il); rescan_idlist(_il)
            try: done = json.load(open(RESCAN_STATE)).get('status') == 'done'
            except Exception: done = False
            if not done: raise Stop('rescan incomplete after a full pass (unexpected)')
            log('RESCAN complete -> continuing main scan in the same process')
        res, secs = scan('full'); stopped = None
    except Stop as e:
        log('STOP', e); res, secs, stopped = {}, 0, str(e)
    except Terminated as e:
        log('TERMINATED cleanly', e, F.stats, 'nreq', F.nreq)
        try: pin_end('NLM_TERMINATED_BY_SIGNAL', f'NL municipal collector stopped by SIGTERM ({e}); resume-safe')
        except Exception as ex: log('pin update failed', ex)
        return
    finally:
        _drop_tmp()   # 2026-10-10: no .tmp survives any exit path of the scan
    json.dump(dict(mode=MODE, res=res, stopped=stopped, nreq=F.nreq, http=F.stats, seconds=round(secs), ended=now_pt()), open(B / ('collect_result_full.json' if not (os.environ.get('NLM_MAX_CHUNKS') or os.environ.get('NLM_MAX_WALL_S')) else 'collect_result_capped_test.json'), 'w'), indent=1)
    log('DONE' if not stopped else 'STOPPED', res, F.stats, f'min_memavail={G["min_mem"]} pauses={G["n_pause"]} resumes={G["n_resume"]} paused_total_s={G["pause_s_total"]:.0f}')
    try: pin_end('HOLD_0_NLM_COLLECT_DONE', (f'NL municipal collect finished {res}' if not stopped else f'NL municipal collect STOPPED: {stopped}'))
    except Exception as e: log('pin update failed', e)
if __name__ == '__main__':
    if sys.argv[1:2] == ['build']: import pa_exit_guard; pa_exit_guard.run_guarded(main)  # exit guard (pa_exit_guard): only the offline parquet build
    else: main()

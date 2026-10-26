"""Shared guards for slot-2 collectors (ID BPK, CZ SPP). Single network stream per process; NL-M (pid 1123094) is never touched.
- Pacer/Net: >= DELAY s between request starts, honest UA, host-locked, no redirects off-host, 3 consecutive 403/429/503 -> HostBlocked,
  backoff 5..300 s on 5xx/520/connection errors (bounded retries).
- guard(): self-TERM at MemAvailable <= 3700 MB (raises MemShed); PAUSE while MemAvailable < 4500 MB or an IR build/encode job is running
  (state keys encode_alive/finish_alive/orch_pid/encode_pid/finish_pid, mode tokens IR/ENCODE/BUILD, or *_build.py / upload_ir / build_ir processes).
- OCRWorker: background thread, <=2 tesseract workers at nice 19, per-page render (long side capped 3508 px) + native-image fallback, pauses with guard.
- state_merge(prefix): re-read + merge only <prefix>* keys (+ collectors delta)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, re, json, time, threading, subprocess, tempfile, signal
STATE = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'
MEM_TERM = 3700; MEM_PAUSE = 4500; RSS_MB = 300
NLM_PID = 1123094
class MemShed(Exception): pass
class HostBlocked(Exception): pass
class Stopped(Exception): pass
STOP = threading.Event()
def _sig(*a): STOP.set()
def install_signals():
    signal.signal(signal.SIGTERM, _sig); signal.signal(signal.SIGINT, _sig)
def log(*a): print(time.strftime('%Y-%m-%d %H:%M:%S'), *a, flush=True)
def memavail(): return int(open('/proc/meminfo').read().split('MemAvailable:')[1].split()[0]) // 1024
def rss_mb():
    for l in open('/proc/self/status'):
        if l.startswith('VmRSS'): return int(l.split()[1]) // 1024
    return 0
def pid_alive(p):
    try: return bool(p) and os.path.exists(f'/proc/{int(p)}')
    except Exception: return False
IR_PROC = re.compile(r'(_build\.py|upload_ir|build_ir|ir_build|encode_ir|ir_encode|de_build_guarded|nl_build_stage|cleanup_ir)')
def ir_running():
    try: s = json.load(open(STATE))
    except Exception: s = {}
    if s.get('encode_alive') or s.get('finish_alive'): return 'state:encode/finish_alive'
    for k in ('orch_pid', 'encode_pid', 'finish_pid'):
        if pid_alive(s.get(k)): return f'state:{k}'
    if re.search(r'(^|_)(IR|ENCODE|BUILD)(_|$)', str(s.get('mode', ''))): return f"state:mode={s.get('mode')}"
    me = os.getpid()
    for d in os.listdir('/proc'):
        if not d.isdigit() or int(d) in (me, NLM_PID): continue
        try: cmd = open(f'/proc/{d}/cmdline', 'rb').read().replace(b'\0', b' ').decode('utf-8', 'replace')
        except Exception: continue
        if 'python' in cmd and IR_PROC.search(cmd) and 'slot2' not in cmd: return f'proc:{d}:{cmd[:80]}'
    return None
def state_merge(prefix, upd, collectors_delta=0):
    s = json.load(open(STATE))
    for k, v in upd.items():
        assert k.startswith(prefix), k
        s[k] = v
    if collectors_delta: s['collectors'] = max(0, int(s.get('collectors', 0)) + collectors_delta)
    tmp = f'{STATE}.{prefix}tmp'; json.dump(s, open(tmp, 'w'), indent=1); os.replace(tmp, STATE)
class Guard:
    """Call guard.check() before every request / OCR page. Blocks while paused; raises MemShed / Stopped."""
    def __init__(self, prefix, status_cb=None):
        self.prefix = prefix; self.paused = None; self.status_cb = status_cb; self.last_ir = 0; self.ir = None; self.lock = threading.Lock()
    def reason(self):
        m = memavail()
        if m <= MEM_TERM: raise MemShed(f'MemAvailable {m} MB <= {MEM_TERM}')
        if m < MEM_PAUSE: return f'mem {m} MB < {MEM_PAUSE}'
        if time.time() - self.last_ir > 30: self.ir = ir_running(); self.last_ir = time.time()
        return f'IR build: {self.ir}' if self.ir else None
    def check(self, who='net'):
        while True:
            if STOP.is_set(): raise Stopped()
            r = self.reason()
            if not r:
                if self.paused and who == 'net':
                    log('RESUME after pause:', self.paused); self.paused = None
                    if self.status_cb: self.status_cb('resumed')
                return
            if who == 'net' and self.paused != r:
                log('PAUSE:', r); self.paused = r
                if self.status_cb: self.status_cb(f'paused: {r}')
            for _ in range(30):
                if STOP.is_set(): raise Stopped()
                time.sleep(2)
            self.last_ir = 0
CONNECT_S = 10; READ_S = 60; TOTAL_S = 600; RETRIES = 2
class Deadline(Exception): pass
def is_timeout(e):
    import requests
    return isinstance(e, (requests.exceptions.Timeout, Deadline, TimeoutError)) or 'timed out' in str(e).lower() or 'timeout' in type(e).__name__.lower()
def fetch(session, url, connect=CONNECT_S, read=READ_S, total=TOTAL_S):
    """GET with explicit connect/read timeouts AND a total wall-clock deadline (a trickling server cannot hold the socket forever).
    Body is streamed in chunks; returns a normal Response with .content filled."""
    import socket
    t0 = time.time(); r = session.get(url, timeout=(connect, read), allow_redirects=False, stream=True)
    fired = threading.Event()
    def _kill():   # a trickling body never trips the per-recv read timeout -> shut the socket down at the deadline
        fired.set()
        try:
            sock = None
            try: sock = r.raw._fp.fp.raw._sock            # urllib3 2.x: socket detached into the http.client response
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
class Net:
    """Every request: connect 10 s, read 60 s, total 600 s; up to 2 retries with backoff (5 s, 10 s);
    403/429/503 AND timeouts are strikes; 3 consecutive strikes -> HostBlocked."""
    def __init__(self, base, ua, guard, delay=2.0):
        import requests
        self.base = base; self.s = requests.Session(); self.s.headers['User-Agent'] = ua; self.guard = guard; self.delay = delay
        self.last = 0.0; self.bad = 0; self.n = 0; self.codes = {}; self.t0 = time.time()
    def _strike(self, why, url):
        self.bad += 1; log('STRIKE', why, url[:120], f'consecutive_strikes={self.bad}')
        if self.bad >= 3: raise HostBlocked(f'3 consecutive strikes (403/429/503/timeout); last: {why}')
    def get(self, path, max_tries=1 + RETRIES, stream_limit=None):
        url = path if path.startswith('http') else self.base + path
        assert url.startswith(self.base + '/'), 'off-host refused'
        back = 5
        for attempt in range(max_tries):
            self.guard.check('net')
            if rss_mb() > RSS_MB: raise MemShed(f'RSS {rss_mb()} MB > {RSS_MB}')
            w = self.delay - (time.time() - self.last)
            if w > 0: time.sleep(w)
            self.last = time.time(); self.n += 1
            try:
                r = fetch(self.s, url)
            except Exception as e:
                if is_timeout(e):
                    self.codes['TIMEOUT'] = self.codes.get('TIMEOUT', 0) + 1; self._strike(f'timeout {repr(e)[:100]}', url)
                else:
                    self.codes['ERR'] = self.codes.get('ERR', 0) + 1; log('ERR', url[:120], repr(e)[:120])
                if attempt + 1 < max_tries: time.sleep(back); back *= 2
                continue
            self.codes[r.status_code] = self.codes.get(r.status_code, 0) + 1
            if r.status_code in (403, 429, 503):
                self._strike(f'HTTP {r.status_code}', url)
                if attempt + 1 < max_tries: time.sleep(back); back *= 2
                continue
            self.bad = 0
            if r.status_code >= 500 and attempt + 1 < max_tries:
                log('HTTP', r.status_code, url[:120], f'retry in {back}s'); time.sleep(back); back *= 2; continue
            return r.status_code, r.content, r.headers
        log('GIVE UP after', max_tries, 'attempts', url[:120]); return None, None, None
    def rate(self): return self.n / max(time.time() - self.t0, 1)
# ---------------- OCR ----------------
def _tess(im, lang):
    return subprocess.run(['nice', '-n', '19', 'tesseract', im, '-', '-l', lang], capture_output=True, text=True, env=dict(os.environ, OMP_THREAD_LIMIT='1')).stdout
def ocr_page(pdf, pg, d, lang):
    subprocess.run(['nice', '-n', '19', 'pdftoppm', '-f', str(pg), '-l', str(pg), '-r', '300', '-scale-to', '3508', '-gray', '-png', pdf, f'{d}/r{pg}'], capture_output=True)
    ims = [f for f in os.listdir(d) if f.startswith(f'r{pg}-') or f == f'r{pg}.png']
    t = _tess(os.path.join(d, ims[0]), lang) if ims else ''
    for f in ims: os.remove(os.path.join(d, f))
    if len(re.sub(r'\s', '', t)) < 80:   # phone-scanner PDFs with oversized page boxes: OCR the embedded native image instead
        subprocess.run(['nice', '-n', '19', 'pdfimages', '-f', str(pg), '-l', str(pg), '-png', pdf, f'{d}/n{pg}'], capture_output=True)
        nat = sorted((os.path.join(d, f) for f in os.listdir(d) if f.startswith(f'n{pg}-')), key=os.path.getsize)
        if nat:
            t2 = _tess(nat[-1], lang)
            if len(t2.strip()) > len(t.strip()): t = t2
        for f in nat: os.remove(f)
    return t
def pdf_pages(p):
    m = re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', p], capture_output=True, text=True).stdout); return int(m.group(1)) if m else 0
def dir_gb(d):
    tot = 0
    for root, _, fs in os.walk(d):
        for f in fs:
            try: tot += os.path.getsize(os.path.join(root, f))
            except OSError: pass
    return tot / 1e9
class OCRWorker(threading.Thread):
    """Processes every <queue_dir>/<key>.pdf (oldest first) -> <out_dir>/<key>.txt (+ .json stats), then deletes the PDF. Pauses with the guard."""
    def __init__(self, queue_dir, out_dir, lang, guard, workers=2, keep_pdf=False):
        super().__init__(daemon=True); self.q = queue_dir; self.o = out_dir; self.lang = lang; self.guard = guard; self.workers = workers
        self.keep = keep_pdf; self.idle = threading.Event(); self.done_n = 0; self.pages = 0; self.secs = 0.0; self.err = None; self.finish = threading.Event()
        os.makedirs(queue_dir, exist_ok=True); os.makedirs(out_dir, exist_ok=True)
    def pending(self):
        fs = [f for f in os.listdir(self.q) if f.endswith('.pdf')]
        return sorted(fs, key=lambda f: os.path.getmtime(os.path.join(self.q, f)))
    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        try:
            while not STOP.is_set():
                fs = self.pending()
                if not fs:
                    self.idle.set()
                    if self.finish.is_set(): return
                    time.sleep(5); continue
                self.idle.clear(); f = fs[0]; key = f[:-4]; pdf = os.path.join(self.q, f); n = pdf_pages(pdf); t0 = time.time()
                d = tempfile.mkdtemp(prefix='s2ocr_', dir='/workspace/tmp'); texts = [None] * n
                def one(pg):
                    self.guard.check('ocr'); return ocr_page(pdf, pg, d, self.lang)
                with ThreadPoolExecutor(self.workers) as ex:
                    for i, t in enumerate(ex.map(one, range(1, n + 1))): texts[i] = t
                subprocess.run(['rm', '-rf', d])
                open(os.path.join(self.o, key + '.txt.tmp'), 'w').write('\n\f'.join(texts)); os.replace(os.path.join(self.o, key + '.txt.tmp'), os.path.join(self.o, key + '.txt'))
                json.dump(dict(pages=n, secs=round(time.time() - t0, 1)), open(os.path.join(self.o, key + '.json'), 'w'))
                if not self.keep: os.remove(pdf)
                self.done_n += 1; self.pages += n; self.secs += time.time() - t0
        except (MemShed, Stopped) as e:
            self.err = repr(e)
        except Exception as e:
            self.err = repr(e); log('OCR worker error', repr(e))

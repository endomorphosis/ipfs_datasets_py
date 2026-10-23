#!/usr/bin/env python3
"""EE municipal tranche 1: Riigi Teataja avaandmed xml.2024.zip -> RT IV KOV acts -> jsonl.gz shards. Bounded offline job (ONE HTTP download), not a crawl.
CoS contingent GO 2026-10-06 01:05 PT. Licence basis: Autoriõiguse seadus § 5 p 3 (legal acts and administrative documents are not protected).
NOT counted as a collector (CoS 01:03 PT steering): never touches `collectors` or any key in HOLD_AT_PIN.state; EE state lives in ee_municipal/state.json.
Shed order on memory trouble: EE first, then CZ, then NL-M.

Modes
  run --cos-go TOKEN [--allow-redownload]       full job: preflight -> download (once) -> sha256 -> parse -> pack -> verify -> review -> verify -> delete zip
                                                (use /workspace/scripts/ee_t1_launch.sh; resumes from state.json/manifest after a stop)
  offline --zip PATH --root DIR [--no-sha] [--shard-n N] [--keep-zip]   parse/pack/verify/review a local zip (tests; never downloads)
  verify [--root DIR]                           recompute shard sha256 vs manifest
  guard_dryrun                                  simulated memory traces against the guard (no files, no network)
  status [--root DIR]                           print state.json
Download: exactly one GET of URL (curl, --limit-rate <=5M, connect 10 s, max-time 900 s, abort if <50 KB/s for 120 s; no --retry, no ranges, no -C,
  no redirects). Repeated ONLY after curl exit 28 (timeout) or a dropped connection (18/52/55/56/92/16), at most twice. A download aborted by the guard or
  STOP_EE is never re-fetched automatically; a later run refuses unless --allow-redownload (CoS decision). File: <root>/build/xml.2024.zip (build/ is
  sync-ignored). Verified against the official SHA256SUMS (evidence/SHA256SUMS_20261006.txt) and the HEAD size before parsing.
Guard (strict, same as NL-M / CZ T2; ee_config.json re-read every 60 s, floors enforced in code):
  PAUSE MemAvail < 3584 (download: curl SIGSTOP), RESUME >= 4200 held 30 s; hard TERM < 3000 sustained >= 5 s (2 s poll), instant < 2500, paused > 900 s, RSS > 300 MB;
  EE_SHED_BASELINE: MemAvail < 4200 for >= 60 s continuously (any reading >= 4200 resets) -> clean stop + checkpoint (EE sheds first).
  Tokens: MEMPAUSE / MEMRESUME / MEMLOW_STREAK / MEMTERM / EE_SHED_BASELINE / STOPFILE / FILEPAUSE / FILERESUME / MEMSTAT.
  touch ee_municipal/STOP_EE  -> abandon the in-flight GET (partial file deleted) or finish the current zip member, checkpoint, clean exit (T1_STOPPED_BY_STOPFILE).
  touch ee_municipal/PAUSE_EE -> pause (curl SIGSTOP during download) until the file is removed; hard memory rules still apply. Watcher force-exits 30 s (hard) /
  60 s (STOP_EE, baseline shed) after the flag if the main thread has not reached a gate (checkpoint, kill curl, os._exit).
Layout (<root> = {_CORPORA}/ee_municipal): build/ (zip, staging, transient; sync-ignored) | index/laws_shards/ee_t1_kov_<nnnn>.jsonl.gz + manifest.json |
  review/ | ref/ehak_2026v1_stat_ee.csv | evidence/ | state.json | ee_config.json | COS_GO_EE_T1 | STOP_EE | PAUSE_EE"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, re, json, gzip, time, html, signal, hashlib, zipfile, threading, subprocess, csv, collections, datetime
sys.path.insert(0, '/workspace/scripts')
import slot2_common as S2   # memavail / rss_mb / ir_running (read-only use; not modified)
B = '{_CORPORA}/ee_municipal'
URL = 'https://www.riigiteataja.ee/avaandmed/ERT/xml.2024.zip'
ZIP_SIZE = 344174073; ZIP_LASTMOD = 'Sun, 04 Oct 2026 08:12:25 GMT'
FORBIDDEN = ('xml.2026', 'xml.2025')
DUMP_AS_OF = '2026-10-04'   # LOEMIND: "Riigi Teataja avaandmed on genereeritud 2026-10-04 seisuga"
UA = 'Mozilla/5.0 (compatible; legal-corpus-build/1.0; one-time bulk download of RT avaandmed)'
LICENSE = 'Not protected by copyright: Autoriõiguse seadus § 5 p 3 (õigusaktid ja haldusdokumendid)'
RETRY_EXIT = {28: 'timeout', 18: 'partial_file', 52: 'empty_reply', 55: 'send_error', 56: 'recv_error', 92: 'http2_stream', 16: 'http2'}
_CFG = dict(pause_memavail=3584, resume_memavail=4200, resume_hold_s=30, hard_term_memavail=3000, hard_term_sustain_s=5, hard_term_poll_s=2,
            instant_term_memavail=2500, max_pause_s=900, rss_limit_mb=300, baseline_shed_memavail=4200, baseline_shed_sustain_s=60,
            launch_min_memavail=4200, limit_rate_kb=5120, shard_n=1000, shard_max_mb=64)
STOP = threading.Event()
class MemShed(Exception): pass
class Shed(Exception): pass
class Stopped(Exception): pass
def _ts(): return time.strftime('%Y-%m-%d %H:%M:%S')
def _now(): return time.strftime('%Y-%m-%dT%H:%M:%S%z')
def glog(*a): print(_ts(), *a, flush=True)
def paths(root):
    return dict(root=root, build=f'{root}/build', zip=f'{root}/build/xml.2024.zip', part=f'{root}/build/xml.2024.zip.part', staging=f'{root}/build/acts_staging.jsonl',
                shards=f'{root}/index/laws_shards', manifest=f'{root}/index/laws_shards/manifest.json', review=f'{root}/review', state=f'{root}/state.json',
                cfg=f'{root}/ee_config.json', stop=f'{root}/STOP_EE', pause=f'{root}/PAUSE_EE', token=f'{root}/COS_GO_EE_T1',
                ehak=f'{B}/ref/ehak_2026v1_stat_ee.csv', sums=f'{B}/evidence/SHA256SUMS_20261006.txt')
def atomic_json(p, obj):
    t = p + '.tmp'
    with open(t, 'w') as f: json.dump(obj, f, indent=1, ensure_ascii=False); f.flush(); os.fsync(f.fileno())
    os.replace(t, p)
def load_cfg(p):
    try: c = json.load(open(p))
    except Exception: c = {}
    g = dict(_CFG); g.update({k: c[k] for k in _CFG if k in c})
    g['pause_memavail'] = max(3300, int(g['pause_memavail'])); g['resume_memavail'] = max(3800, g['pause_memavail'] + 1, int(g['resume_memavail']))
    g['resume_hold_s'] = max(10, int(g['resume_hold_s'])); g['hard_term_memavail'] = min(g['pause_memavail'] - 1, max(3000, int(g['hard_term_memavail'])))
    g['hard_term_sustain_s'] = max(1.0, min(10.0, float(g['hard_term_sustain_s']))); g['hard_term_poll_s'] = max(0.5, min(2.0, float(g['hard_term_poll_s'])))
    g['instant_term_memavail'] = min(g['hard_term_memavail'] - 1, max(2500, int(g['instant_term_memavail']))); g['max_pause_s'] = max(60, min(900, int(g['max_pause_s'])))
    g['rss_limit_mb'] = min(300, int(g['rss_limit_mb'])); g['baseline_shed_memavail'] = max(4200, int(g['baseline_shed_memavail']))
    g['baseline_shed_sustain_s'] = max(30, min(120, int(g['baseline_shed_sustain_s']))); g['launch_min_memavail'] = max(4200, int(g['launch_min_memavail']))
    g['limit_rate_kb'] = max(256, min(5120, int(g['limit_rate_kb']))); g['shard_n'] = max(1, min(1000, int(g['shard_n']))); g['shard_max_mb'] = max(1, min(128, int(g['shard_max_mb'])))
    return g
class State:
    def __init__(self, p): self.p = p; self.s = json.load(open(p)) if os.path.exists(p) else dict(created=_now())
    def set(self, **u): self.s.update(u); self.s['ts'] = _now(); atomic_json(self.p, self.s)
    def __getitem__(self, k): return self.s.get(k)
def _children(pid):
    kids = []
    for d in os.listdir('/proc'):
        if not d.isdigit(): continue
        try:
            if int(open(f'/proc/{d}/stat').read().rsplit(')', 1)[1].split()[1]) == pid: kids.append(int(d)); kids += _children(int(d))
        except Exception: pass
    return kids
def kill_children():
    for k in _children(os.getpid()):
        try: os.kill(k, signal.SIGKILL)
        except Exception: pass
# ---------------- guard ----------------
class Guard:
    def __init__(self, P, checkpoint=None, on_exit=None):
        self.P = P; self.c = load_cfg(P['cfg']); self.checkpoint = checkpoint; self.watch_checkpoint = None; self.on_exit = on_exit; self.lock = threading.Lock(); self.paused = False
        self.G = dict(min_mem=10 ** 9, n_pause=0, n_resume=0, n_filepause=0, pause_s_total=0.0, low_t0=None, low_n=0, n_streaks=0, hard=None, hard_t=None,
                      stopfile_t=None, termlogged=False, base_t0=None, shed=None, shed_t=None)
    def reload(self):
        n = load_cfg(self.P['cfg'])
        if n != self.c: self.c = n; glog('CONFIG reloaded', n)
    def _baseline(self, m, now):
        c = self.c
        with self.lock:
            if m >= c['baseline_shed_memavail']: self.G['base_t0'] = None; return None
            if self.G['base_t0'] is None: self.G['base_t0'] = now
            dur = now - self.G['base_t0']
            if dur >= c['baseline_shed_sustain_s']:
                if not self.G['shed']:
                    self.G['shed'] = f"memavail<{c['baseline_shed_memavail']} for {dur:.0f}s (now {m})"; self.G['shed_t'] = now
                    glog(f"EE_SHED_BASELINE memavail={m} below={c['baseline_shed_memavail']} dur_s={dur:.0f} sustain_s={c['baseline_shed_sustain_s']} -> clean stop (EE sheds first)")
                return self.G['shed']
            return None
    def _low_streak(self, m, now):
        c = self.c
        with self.lock:
            if m < c['instant_term_memavail']: return f"lt{c['instant_term_memavail']} memavail={m}"
            if m >= c['hard_term_memavail']:
                if self.G['low_t0'] is not None: glog(f"MEMLOW_STREAK reset memavail={m} n={self.G['low_n']} dur_s={now - self.G['low_t0']:.1f} (no TERM)")
                self.G['low_t0'] = None; self.G['low_n'] = 0; return None
            if self.G['low_t0'] is None: self.G['low_t0'] = now; self.G['n_streaks'] += 1
            self.G['low_n'] += 1; dur = now - self.G['low_t0']
            glog(f"MEMLOW_STREAK memavail={m} n={self.G['low_n']} dur_s={dur:.1f} sustain_s={c['hard_term_sustain_s']:g}")
            if dur >= c['hard_term_sustain_s']: return f"sustained_lt{c['hard_term_memavail']} dur_s={dur:.1f} n={self.G['low_n']} memavail={m}"
            return None
    def _hard(self, m, now, rss_fn=None):
        self.G['min_mem'] = min(self.G['min_mem'], m)
        why = self._low_streak(m, now)
        if why: return why
        r = (rss_fn or S2.rss_mb)()
        if r > self.c['rss_limit_mb']: return f"rss={r}MB>{self.c['rss_limit_mb']}MB"
        return None
    def _term(self, m, why):
        if not self.G['termlogged']:
            self.G['termlogged'] = True; glog(f"MEMTERM reason={why} memavail_now={m} min_memavail={self.G['min_mem']} pauses={self.G['n_pause']} ts={_now()}")
        raise MemShed(why)
    def _stopcheck(self):
        if STOP.is_set() and not os.path.exists(self.P['stop']): raise Stopped('signal')
        if os.path.exists(self.P['stop']):
            if self.G['stopfile_t'] is None: self.G['stopfile_t'] = time.time(); glog(f"STOPFILE {self.P['stop']} present -> clean exit")
            STOP.set(); raise Stopped('stopfile')
    def _shedcheck(self, m, now):
        why = self._baseline(m, now) or self.G['shed']
        if why: raise Shed(why)
    def check(self, _sleep=time.sleep, _mem=None, _clock=time.time, _rss=None):
        """gate (main thread): before each zip member / shard / during the download loop. Blocks while paused; raises MemShed / Shed / Stopped."""
        mem = _mem or S2.memavail
        self._stopcheck(); m = mem(); now = _clock()
        why = self._hard(m, now, _rss) or self.G['hard']
        if why: self._term(m, why)
        self._shedcheck(m, now)
        pf = os.path.exists(self.P['pause'])
        if m >= self.c['pause_memavail'] and not pf: return m
        t0 = _clock(); self.paused = True; mode = 'file' if pf else 'mem'; mem_t0 = None if pf else t0; ok_since = None; last_log = t0
        if pf: self.G['n_filepause'] += 1; glog(f"FILEPAUSE {self.P['pause']} present memavail={m}")
        else: self.G['n_pause'] += 1; glog(f"MEMPAUSE memavail={m} pause_below={self.c['pause_memavail']} resume_at={self.c['resume_memavail']}x{self.c['resume_hold_s']}s n={self.G['n_pause']}")
        try:
            while True:
                for _ in range(2 if ok_since is None else 1):
                    _sleep(1)
                self._stopcheck(); m = mem(); now = _clock()
                why = self._hard(m, now, _rss) or self.G['hard']
                if why: self._term(m, why)
                if mode == 'mem': self._shedcheck(m, now)
                pf = os.path.exists(self.P['pause'])
                if pf: mode = 'file'; mem_t0 = None; ok_since = None
                elif mode == 'file':
                    if m >= self.c['pause_memavail']: break
                    mode = 'mem'; mem_t0 = now; ok_since = None; self.G['n_pause'] += 1; glog(f'MEMPAUSE memavail={m} (after PAUSE_EE removed)')
                if mode == 'mem':
                    if now - mem_t0 > self.c['max_pause_s']: self._term(m, f"paused>{self.c['max_pause_s']}s (paused_s={now - mem_t0:.0f})")
                    if m >= self.c['resume_memavail']:
                        ok_since = ok_since or now
                        if now - ok_since >= self.c['resume_hold_s']: break
                    else: ok_since = None
                if now - last_log >= 60: last_log = now; glog(f"{'FILEPAUSE' if mode == 'file' else 'MEMPAUSE'} waiting memavail={m} paused_s={now - t0:.0f}")
        finally: self.paused = False
        ps = _clock() - t0; self.G['pause_s_total'] += ps
        if mode == 'file': glog(f'FILERESUME memavail={m} paused_s={ps:.0f}')
        else: self.G['n_resume'] += 1; glog(f"MEMRESUME memavail={m} paused_s={ps:.0f} n={self.G['n_resume']}")
        return m
    def watch_tick(self, m, now, rss_fn=None):
        why = self._hard(m, now, rss_fn)
        if why and not self.G['hard']: self.G['hard'] = why; self.G['hard_t'] = now; glog(f'MEMGUARD hard condition flagged: {why}')
        self._baseline(m, now)
        return self.G['hard'] or self.G['shed']
    def watcher(self):
        t_cfg = t_stat = time.time()
        while True:
            try:
                now = time.time(); m = S2.memavail(); self.watch_tick(m, now)
                if os.path.exists(self.P['stop']):
                    if self.G['stopfile_t'] is None: self.G['stopfile_t'] = now; glog(f"STOPFILE {self.P['stop']} present -> clean exit (watcher)")
                    STOP.set()
                late = ((self.G['hard'] and now - self.G['hard_t'] > 30) and 'MEMTERM') or ((self.G['shed'] and now - self.G['shed_t'] > 60) and 'EE_SHED_BASELINE') \
                       or ((self.G['stopfile_t'] and now - self.G['stopfile_t'] > 60) and 'STOPFILE')
                if late:
                    glog(f'{late} watcher force exit: main thread did not reach a gate in time; memavail={m}')
                    try:   # parse resume point = last consistent main-thread checkpoint (<= 10 members old); download: mark the GET aborted
                        if self.watch_checkpoint: self.watch_checkpoint()
                    except Exception as e: glog('checkpoint failed', repr(e))
                    try:
                        if self.on_exit: self.on_exit({'MEMTERM': 'T1_MEMSHED', 'EE_SHED_BASELINE': 'T1_SHED_BASELINE', 'STOPFILE': 'T1_STOPPED_BY_STOPFILE'}[late], late)
                    except Exception: pass
                    kill_children(); os._exit(3)
                if now - t_cfg >= 60: t_cfg = now; self.reload()
                if now - t_stat >= 300:
                    t_stat = now; glog(f"MEMSTAT memavail={m} min_memavail={self.G['min_mem']} rss={S2.rss_mb()} pauses={self.G['n_pause']} resumes={self.G['n_resume']} low_streaks={self.G['n_streaks']}")
            except Exception as e: glog('memwatch error', repr(e)[:200])
            time.sleep(self.c['hard_term_poll_s'])
# ---------------- EHAK / issuer ----------------
ISSUER = re.compile(r'^(?P<g>.+?)\s+(?P<kind>Linna|Valla|Alevi)?\s*(?P<organ>volikogu|valitsus|vanem|pea)$', re.I)
def load_ehak(p):
    m = {}; rows = []
    for x in csv.DictReader(open(p, encoding='utf-8-sig')):
        if x['Level'] != '2' or x['Label-et-EE'].endswith('linnaosa'): continue
        name = x['Label-et-EE']; rows.append((x['Value'], name, x['Parent']))
        if name == 'Tallinn': keys = [('tallinna', 'linn'), ('tallinn', 'linn')]
        else:
            base, kind = name.rsplit(' ', 1); keys = [(base.lower(), kind)]
        for k in keys: m[k] = dict(code=x['Value'], name=name, county_code=x['Parent'])
    return m, rows
def issuer_lg(issuer, ehak):
    """'Narva Linnavolikogu' -> (lg_name, organ, ehak dict|None); None if not a KOV issuer"""
    s = re.sub(r'\s+', ' ', (issuer or '').strip())
    mo = ISSUER.match(s)
    if not mo: return None
    g, kind, organ = mo.group('g'), (mo.group('kind') or '').lower(), mo.group('organ').lower()
    if not kind and organ in ('volikogu', 'valitsus', 'vanem', 'pea'):
        if re.search(r'(maa|riigi|vabariigi)$', g.lower()) and organ == 'valitsus': return None   # Vabariigi Valitsus / maavalitsus-like
        if organ in ('vanem', 'pea') and not g.lower().endswith(('valla', 'linna')): return None
    if organ == 'vanem' and not kind: return None
    k = {'linna': 'linn', 'valla': 'vald', 'alevi': 'alev'}.get(kind)
    e = ehak.get((g.lower(), k)) if k else (ehak.get((g.lower(), 'vald')) or ehak.get((g.lower(), 'linn')))
    if not e and not k and g.lower().startswith('tallinna ') and organ == 'valitsus':   # Tallinn district government (linnaosa valitsus) -> Tallinn
        e = ehak.get(('tallinna', 'linn')); organ = 'linnaosa valitsus'
    lg = e['name'] if e else (f"{g} {k}" if k else g)
    return lg, f"{kind}{organ}" if kind else organ, e
# ---------------- XML -> act ----------------
CONTAINERS = {'sisu', 'peatykk', 'jagu', 'osa', 'alljaotis', 'jaotis'}
BLOCK = {'loige', 'punkt', 'alampunkt', 'taane', 'preambul', 'HTMLKonteiner', 'tabel', 'lisa', 'kommentaar'}
SUP = str.maketrans('0123456789', '⁰¹²³⁴⁵⁶⁷⁸⁹')
def L(t): return t.rsplit('}', 1)[-1] if isinstance(t, str) else ''
def html_text(s):
    s = re.sub(r'(?is)<(script|style).*?</\1>', ' ', s or '')
    s = re.sub(r'(?i)</t[dh]\s*>', ' | ', s); s = re.sub(r'(?i)<br\s*/?>|</(p|tr|div|li|h\d|table)\s*>', '\n', s)
    return html.unescape(re.sub(r'<[^>]+>', ' ', s))
def render(e):
    out = []
    def walk(x):
        t = L(x.tag)
        if not t: out.append(x.tail or ''); return
        if t.endswith('Nr') and t != 'kuvatavNr': out.append(x.tail or ''); return
        if t in BLOCK: out.append('\n')
        if t == 'HTMLKonteiner': out.append('\n' + html_text(''.join(x.itertext())) + '\n')
        elif t in ('sup', 'ylaIndeks', 'ylaindeks'): out.append(''.join(x.itertext()).strip().translate(SUP))
        else:
            out.append(x.text or '')
            for c in x: walk(c)
        if t == 'kuvatavNr': out.append(' ')
        if t in ('paragrahvPealkiri', 'peatykkPealkiri', 'jaguPealkiri', 'osaPealkiri'): out.append('\n')
        out.append(x.tail or '')
    walk(e); e_tail = e.tail; out[-1:] = [out[-1][:len(out[-1]) - len(e_tail or '')]] if out and e_tail and out[-1].endswith(e_tail) else out[-1:]
    lines = [re.sub(r'[ \t\r\f\v\u00a0]+', ' ', l).strip() for l in ''.join(out).split('\n')]
    return '\n'.join(l for l in lines if l)
def _t(e, *names):
    for n in names:
        for x in e.iter():
            if L(x.tag) == n and (x.text or '').strip(): return x.text.strip()
    return None
def parse_meta(e):
    m = dict(issuer=_t(e, 'valjaandja'), doc_type=_t(e, 'dokumentLiik'), text_kind=_t(e, 'tekstiliik'), stage=_t(e, 'dokumentEtapp'), doc_status=_t(e, 'dokumentStaatus'),
             global_id=_t(e, 'globaalID'), group_id=_t(e, 'terviktekstiGrupiID'), schema=_t(e, 'skeemiNimi'), meta_version=_t(e, 'metaandmedVersioon'),
             meta_version_date=_t(e, 'metaandmedVersioonKuupaev'))
    for x in e:
        t = L(x.tag)
        if t == 'vastuvoetud': m.update(adopted=_t(x, 'aktikuupaev'), act_no=_t(x, 'aktiNr'), adopted_note=_t(x, 'tavatekst'))
        elif t == 'avaldamismarge' and 'rt_part' not in m:
            m.update(rt_part=_t(x, 'RTosa'), rt_year=_t(x, 'RTaasta'), rt_article=_t(x, 'RTartikkel'), rt_ref_id=_t(x, 'aktViide'), published=_t(x, 'avaldamineKuupaev'))
        elif t == 'kehtivus': m.update(valid_from=_t(x, 'kehtivuseAlgus'), valid_to=_t(x, 'kehtivuseLopp'))
        elif t == 'versioon': m.update(version=_t(x, 'dokumentVersioon'), version_date=_t(x, 'dokumentVersioonKuupaev'))
        elif t == 'joustumine' and 'in_force_date' not in m: m['in_force_date'] = _t(x, 'joustumiseKuupaev') or (x.text or '').strip() or None
    ex = {L(x.tag): (x.text or '').strip() for x in e.iter() if 'ehak' in L(x.tag).lower() and (x.text or '').strip()}
    if ex: m['ehak_in_xml'] = ex
    for k in ('valid_from', 'valid_to', 'adopted', 'published', 'in_force_date'):
        if m.get(k): m[k] = m[k][:10]
    return m
def law_status(m, ref=DUMP_AS_OF):
    a, b = m.get('valid_from'), m.get('valid_to')
    if not a: return 'unknown'
    if a > ref: return 'future_version'
    if b and b < ref: return 'historical_version'
    return 'current'
def parse_act(fobj, member, ehak, retrieved):
    """streaming iterparse of one act XML (elements cleared as processed) -> (record | None, drop_reason | None)"""
    from lxml import etree
    stack = []; meta = None; title = None; lines = []; arts = []; pts = []; ctx = {}; heads = {}; sign = None; attach = set()
    for ev, el in etree.iterparse(fobj, events=('start', 'end'), resolve_entities=False, no_network=True, huge_tree=True, remove_comments=True):
        t = L(el.tag)
        if ev == 'start':
            stack.append(t)
            if t in CONTAINERS and t != 'sisu':
                for k in ('osa', 'peatykk', 'jagu', 'jaotis', 'alljaotis')[('osa', 'peatykk', 'jagu', 'jaotis', 'alljaotis').index(t) if t in ('osa', 'peatykk', 'jagu', 'jaotis', 'alljaotis') else 0:]: ctx.pop(k, None)
                heads[t] = ''
            continue
        stack.pop(); parent = stack[-1] if stack else None
        for v in el.attrib.values():
            if re.search(r'(?i)(aktilisa|\.pdf$|\.asice$|\.bdoc$|\.ddoc$)', v): attach.add(v)
        done = False
        if t == 'metaandmed' and parent == 'oigusakt':
            meta = parse_meta(el); done = True
            if meta.get('rt_part') and meta['rt_part'] != 'RT IV': return None, f"not_rt_iv:{meta['rt_part']}"
        elif t == 'aktinimi' and parent == 'oigusakt': title = re.sub(r'\s+', ' ', ' '.join(el.itertext())).strip() or None; done = True
        elif t == 'allkiri' and parent == 'oigusakt': sign = re.sub(r'\s+', ' ', ' '.join(el.itertext())).strip() or None; done = True
        elif parent in CONTAINERS and t not in CONTAINERS:
            if parent != 'sisu' and (t == 'kuvatavNr' or t.endswith('Pealkiri') or t.endswith('Nr')):
                if t == 'kuvatavNr': heads[parent] = (''.join(el.itertext())).strip()
                elif t.endswith('Pealkiri'):
                    h = re.sub(r'\s+', ' ', (heads.get(parent, '') + ' ' + ''.join(el.itertext())).strip()); ctx[parent] = h; lines.append(h)
            else:
                txt = render(el)
                if txt: lines.append(txt)
                if t == 'punkt' and txt:   # fallback split for acts without paragrahv (top-level numbered points)
                    nr = next(((c.text or '').strip() for c in el if L(c.tag) == 'punktNr'), None) or str(len(pts) + 1)
                    pts.append(dict(num=nr, display=None, title='', text=txt, chapter=ctx.get('peatykk'), section=ctx.get('jagu'), part=ctx.get('osa'), xml_id=el.get('id'), rt='point'))
                if t == 'paragrahv':
                    nr = None
                    for c in el:
                        if L(c.tag) == 'paragrahvNr':
                            nr = (c.text or '').strip()
                            for s in c:
                                if L(s.tag).lower() in ('ylaindeks', 'sup'): nr += '^' + ''.join(s.itertext()).strip()
                    disp = next((''.join(c.itertext()).strip() for c in el if L(c.tag) == 'kuvatavNr'), None)
                    ttl = next((re.sub(r'\s+', ' ', ''.join(c.itertext())).strip() for c in el if L(c.tag) == 'paragrahvPealkiri'), None)
                    arts.append(dict(num=nr or (disp or '').strip('§. ') or str(len(arts) + 1), display=disp, title=ttl or '', text=txt,
                                     chapter=ctx.get('peatykk'), section=ctx.get('jagu'), part=ctx.get('osa'), xml_id=el.get('id')))
            done = True
        elif parent == 'oigusakt' and t not in ('metaandmed', 'aktinimi', 'sisu', 'allkiri'):
            txt = render(el)
            if txt: lines.append(txt)
            done = True
        if done:
            el.clear()
            while el.getprevious() is not None: del el.getparent()[0]
    if meta is None: return None, 'no_metaandmed'
    if not arts and pts: arts = pts
    k = issuer_lg(meta.get('issuer'), ehak)
    if not k: return None, f"not_kov_issuer:{meta.get('issuer')}"
    lg, organ, e = k
    gid = meta.get('global_id') or member.rsplit('.', 1)[0]; law_id = f'EE-RT-{gid}'; text = '\n'.join(lines)
    rt_ref = None
    if meta.get('rt_part') and meta.get('published'):
        d = meta['published']; rt_ref = f"{meta['rt_part']}, {d[8:10]}.{d[5:7]}.{d[:4]}, {meta.get('rt_article')}"
    adopted = meta.get('adopted'); ad = f"{adopted[8:10]}.{adopted[5:7]}.{adopted[:4]}" if adopted else '?'
    official = f"{meta.get('issuer')} {meta.get('doc_type') or ''} {ad} nr {meta.get('act_no') or '?'}".replace('  ', ' ') + (f' ({rt_ref})' if rt_ref else '')
    src = f'https://www.riigiteataja.ee/akt/{gid}'; st = law_status(meta)
    md = dict(source='Riigi Teataja avaandmed xml.2024.zip', zip_member=member, rt_reference=rt_ref, issuer=meta.get('issuer'), issuer_organ=organ, lg_name=lg,
              ehak_code=e['code'] if e else None, ehak_version='EHAK2026v1' if e else None, county_ehak=e['county_code'] if e else None, ehak_in_xml=meta.get('ehak_in_xml'),
              status_ref_date=DUMP_AS_OF, signatory=sign, attachments=sorted(attach)[:50], **{k2: v for k2, v in meta.items() if k2 not in ('issuer', 'ehak_in_xml')})
    law = dict(id=law_id, title=title, text=text, source_url=src, source_type='municipal_legislation', jurisdiction=f"EE-{e['code']}" if e else 'EE', country='Estonia',
               language='et', eli=None, date=meta.get('valid_from') or meta.get('published') or adopted, date_issued=adopted, retrieved_at=retrieved, license=LICENSE,
               law_status=st, identifier=law_id, official_identifier=official, article_count=len(arts), json_path=None, metadata_json=json.dumps(md, ensure_ascii=False))
    arows = [dict(law_id=law_id, id=f"{law_id}-{'pt' if a.get('rt') == 'point' else 'par'}{a['num']}", title=a['title'], text=a['text'], source_url=src, document_number=meta.get('act_no'),
                  article_number=a['num'], record_type=a.get('rt', 'paragraph'), metadata_json=json.dumps(dict(ordinal=i + 1, display=a['display'], chapter=a['chapter'], section=a['section'],
                                                                                                     part=a['part'], xml_id=a['xml_id']), ensure_ascii=False)) for i, a in enumerate(arts)]
    return dict(law=law, articles=arows), None
# ---------------- download ----------------
def expected_sha(P):
    for l in open(P['sums']):
        p = l.split()
        if len(p) == 2 and p[1] == 'xml.2024.zip': return p[0]
    raise RuntimeError('xml.2024.zip not in SHA256SUMS evidence')
def sha256_file(p, guard=None):
    h = hashlib.sha256(); n = 0
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b); n += 1
            if guard and n % 64 == 0: guard.check()
    return h.hexdigest()
def download(P, st, guard, allow_redownload=False):
    assert not any(x in URL for x in FORBIDDEN) and URL.endswith('/xml.2024.zip')
    dl = st['download'] or dict(gets_started=0, history=[])
    if dl.get('aborted_by_guard_or_stop') and not allow_redownload:
        raise RuntimeError('REFUSED_REDOWNLOAD: an earlier GET was aborted by the guard/STOP_EE; a new GET needs CoS approval (--allow-redownload)')
    if dl['gets_started'] >= 3 and not allow_redownload: raise RuntimeError(f"REFUSED_REDOWNLOAD: {dl['gets_started']} GETs already started (cap 3)")
    run_gets = 0
    while True:
        if run_gets >= 3: raise RuntimeError('download failed: 3 GETs (1 + 2 repeats) used')
        guard.check()
        if os.path.exists(P['part']): os.remove(P['part'])
        cmd = ['curl', '-sS', '--fail', '--proto', '=https', '--limit-rate', f"{guard.c['limit_rate_kb']}k", '--connect-timeout', '10', '--max-time', '900',
               '--speed-limit', '51200', '--speed-time', '120', '-A', UA, '-o', P['part'], '-w', '%{http_code} %{size_download} %{speed_download} %{time_total}', URL]
        assert '--retry' not in cmd and '-C' not in cmd and '-r' not in cmd and '--range' not in cmd
        run_gets += 1; dl['gets_started'] += 1; dl['history'].append(dict(start=_now(), get_no=dl['gets_started'])); st.set(status='T1_DOWNLOADING', download=dl)
        glog(f"DOWNLOAD GET #{dl['gets_started']} (run attempt {run_gets}/3) {URL} limit {guard.c['limit_rate_kb']}k/s -> {P['part']}")
        def mark_aborted():
            dl['history'][-1].update(end=_now(), result='aborted:watcher_force_exit'); dl['aborted_by_guard_or_stop'] = True; st.set(download=dl)
        guard.watch_checkpoint = mark_aborted
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL); t0 = time.time(); last = t0
        try:
            while proc.poll() is None:
                time.sleep(1)
                m = S2.memavail(); need_pause = m < guard.c['pause_memavail'] or os.path.exists(P['pause'])
                if need_pause: proc.send_signal(signal.SIGSTOP); glog('DOWNLOAD curl SIGSTOP (pause)')
                try: guard.check()
                finally:
                    if need_pause and proc.poll() is None: proc.send_signal(signal.SIGCONT); glog('DOWNLOAD curl SIGCONT (resume)')
                if time.time() - last >= 15:
                    last = time.time(); sz = os.path.getsize(P['part']) if os.path.exists(P['part']) else 0
                    glog(f'DOWNLOAD progress {sz / 1e6:.1f}/{ZIP_SIZE / 1e6:.1f} MB {sz / max(time.time() - t0, 1) / 1e6:.2f} MB/s mem {m} rss {S2.rss_mb()}')
        except BaseException as e:
            if proc.poll() is None: proc.send_signal(signal.SIGCONT); proc.kill(); proc.wait()
            if os.path.exists(P['part']): os.remove(P['part'])
            dl['history'][-1].update(end=_now(), result=f'aborted:{type(e).__name__}:{e}'[:200]); dl['aborted_by_guard_or_stop'] = True; st.set(download=dl)
            glog('DOWNLOAD aborted (partial file deleted; no automatic re-fetch):', type(e).__name__, e); raise
        guard.watch_checkpoint = None
        out, err = proc.communicate(); rc = proc.returncode; info = out.decode(errors='replace').strip()
        dl['history'][-1].update(end=_now(), curl_exit=rc, info=info, stderr=err.decode(errors='replace').strip()[:200]); st.set(download=dl)
        glog(f'DOWNLOAD curl exit {rc} [{info}] {err.decode(errors="replace").strip()[:200]}')
        if rc == 0: break
        if rc in RETRY_EXIT and run_gets < 3:
            w = 30 * run_gets; glog(f'DOWNLOAD {RETRY_EXIT[rc]} (exit {rc}) -> repeat once more after {w}s'); 
            for _ in range(w): guard.check(); time.sleep(1)
            continue
        if os.path.exists(P['part']): os.remove(P['part'])
        raise RuntimeError(f'download failed: curl exit {rc} ({RETRY_EXIT.get(rc, "not retryable")}) {info}')
    sz = os.path.getsize(P['part'])
    if sz != ZIP_SIZE: os.remove(P['part']); raise RuntimeError(f'size {sz} != HEAD {ZIP_SIZE}')
    st.set(status='T1_VERIFYING_ZIP'); h = sha256_file(P['part'], guard)
    if h != expected_sha(P):
        dl['sha256'] = h; dl['sha_ok'] = False; st.set(download=dl, status='T1_DOWNLOAD_SHA_MISMATCH'); raise RuntimeError(f'sha256 mismatch {h}')
    os.replace(P['part'], P['zip']); dl.update(sha256=h, sha_ok=True, bytes=sz, done=_now()); st.set(download=dl, status='T1_DOWNLOADED')
    glog('DOWNLOAD OK sha256 verified', h)
# ---------------- parse / pack / verify ----------------
def parse_zip(P, st, guard, zpath):
    ehak, _ = load_ehak(P['ehak']); ps = st['parse'] or dict(next_idx=0, staging_bytes=0, kept=0, dropped={}, errors=0, members_total=None)
    zf = zipfile.ZipFile(zpath)
    members = sorted((i for i in zf.infolist() if not i.is_dir()), key=lambda i: i.filename)
    rtiv = [i for i in members if os.path.basename(i.filename).startswith('4') and i.filename.endswith('.xml')]
    ps.update(members_total=len(members), rtiv_total=len(rtiv), non_rtiv_skipped=len(members) - len(rtiv))
    os.makedirs(P['build'], exist_ok=True)
    if os.path.exists(P['staging']) and os.path.getsize(P['staging']) < ps['staging_bytes']:
        raise RuntimeError(f"staging shorter ({os.path.getsize(P['staging'])}) than checkpoint ({ps['staging_bytes']}); refusing to resume")
    with open(P['staging'], 'ab') as f: f.truncate(ps['staging_bytes'])   # drop records written after the last consistent checkpoint (re-parsed)
    retrieved = (st['download'] or {}).get('done') or _now()
    glog(f"PARSE {zpath} members {len(members)} RT IV {len(rtiv)} resume at {ps['next_idx']} staging {ps['staging_bytes']} B")
    holder = dict(out=None)
    def ckpt():   # main thread only: (next_idx, staging_bytes, tallies) always consistent
        o = holder['out']
        if o is not None and not o.closed: o.flush(); os.fsync(o.fileno()); ps['staging_bytes'] = o.tell()
        else:
            with open(P['staging'], 'ab') as f: os.fsync(f.fileno()); ps['staging_bytes'] = f.seek(0, 2)
        st.set(parse=ps)
    guard.checkpoint = ckpt
    t0 = time.time(); n0 = ps['next_idx']
    with open(P['staging'], 'ab') as out:
        holder['out'] = out
        for idx in range(ps['next_idx'], len(rtiv)):
            guard.check(); zi = rtiv[idx]
            try:
                with zf.open(zi) as fobj: rec, why = parse_act(fobj, zi.filename, ehak, retrieved)
            except Exception as e: rec, why = None, f'xml_error:{type(e).__name__}'; ps['errors'] += 1; glog('PARSE error', zi.filename, repr(e)[:200])
            if rec:
                out.write((json.dumps(rec, ensure_ascii=False) + '\n').encode()); ps['kept'] += 1
            else:
                key = why.split(':')[0]; ps['dropped'][key] = ps['dropped'].get(key, 0) + 1
                ps.setdefault('drop_examples', {}).setdefault(key, [])
                if len(ps['drop_examples'][key]) < 10: ps['drop_examples'][key].append(f'{zi.filename}:{why}'[:160])
            ps['next_idx'] = idx + 1
            if ps['next_idx'] % 10 == 0 or ps['next_idx'] == len(rtiv): ckpt()
            if ps['next_idx'] % 100 == 0:
                glog(f"PARSE {ps['next_idx']}/{len(rtiv)} kept {ps['kept']} dropped {ps['dropped']} errors {ps['errors']} rate {(ps['next_idx'] - n0) / max(time.time() - t0, 1):.1f}/s rss {S2.rss_mb()}MB mem {S2.memavail()}")
        out.flush(); os.fsync(out.fileno()); ps['staging_bytes'] = out.tell()
    ps['done'] = _now(); ckpt(); guard.checkpoint = None; glog(f"PARSE DONE kept {ps['kept']} dropped {ps['dropped']} errors {ps['errors']} rss {S2.rss_mb()}MB")
def pack(P, st, guard):
    os.makedirs(P['shards'], exist_ok=True)
    man = json.load(open(P['manifest'])) if os.path.exists(P['manifest']) else dict(
        format='jsonl.gz: one line per act {"law": {19 hub law cols}, "articles": [{9 cols}]}', source=dict(url=URL, bytes=ZIP_SIZE, last_modified=ZIP_LASTMOD,
        sha256=(st['download'] or {}).get('sha256')), shards={}, staging_offset=0, complete=False)
    if man.get('complete'): return man
    shard_n, cap = guard.c['shard_n'], guard.c['shard_max_mb'] * 1e6; k = len(man['shards'])
    with open(P['staging'], 'rb') as f:
        f.seek(man['staging_offset'])
        while True:
            guard.check(); batch = []; size = 0; start = f.tell()
            while len(batch) < shard_n and size < cap:
                l = f.readline()
                if not l: break
                batch.append(l); size += len(l)
            if not batch: break
            name = f'ee_t1_kov_{k:04d}.jsonl.gz'; p = f"{P['shards']}/{name}"; t = p + '.tmp'; ids = []; na = ne = 0; lgs = collections.Counter()
            with open(t, 'wb') as raw:
                with gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=6, mtime=0) as g:
                    for l in batch:
                        r = json.loads(l); law = r['law']; ids.append(law['id']); na += len(r['articles']); ne += not (law['text'] or '').strip()
                        lgs[json.loads(law['metadata_json']).get('lg_name')] += 1; g.write(l)
                raw.flush(); os.fsync(raw.fileno())
            h = sha256_file(t); os.replace(t, p)
            man['shards'][name] = dict(n_laws=len(batch), n_articles=na, n_empty_text=ne, bytes=os.path.getsize(p), sha256=h, staging_range=[start, f.tell()],
                                       lg_counts=dict(lgs), ids=ids, packed_at=_now())
            man.update(staging_offset=f.tell(), n_shards=len(man['shards']), n_laws=sum(s['n_laws'] for s in man['shards'].values()),
                       n_articles=sum(s['n_articles'] for s in man['shards'].values()), updated=_now())
            atomic_json(P['manifest'], man); k += 1; batch = None
            glog(f"SHARD {name} laws {man['shards'][name]['n_laws']} articles {na} empty {ne} {os.path.getsize(p) / 1e6:.1f} MB")
    man['complete'] = True; man['parse'] = dict(st['parse'] or {}); atomic_json(P['manifest'], man)
    return man
def verify(P, expect_laws=None):
    man = json.load(open(P['manifest'])); bad = []; n = 0
    for name, s in sorted(man['shards'].items()):
        p = f"{P['shards']}/{name}"
        if not os.path.exists(p): bad.append(f'{name}: missing'); continue
        if sha256_file(p) != s['sha256']: bad.append(f'{name}: sha256 mismatch'); continue
        c = 0
        with gzip.open(p, 'rt', encoding='utf-8') as g:
            for l in g: json.loads(l); c += 1
        if c != s['n_laws']: bad.append(f"{name}: {c} lines != {s['n_laws']}")
        n += c
    if not man.get('complete'): bad.append('manifest not complete')
    if expect_laws is not None and n != expect_laws: bad.append(f'laws in shards {n} != parsed kept {expect_laws}')
    return dict(ok=not bad, laws=n, shards=len(man['shards']), problems=bad)
# ---------------- preflight / driver ----------------
HF = re.compile(r'(huggingface-cli|hf upload|hf_upload|upload_folder|upload_large_folder|upload_ir|push_to_hub)')
def ir_busy():
    r = S2.ir_running()
    if r: return r
    me = os.getpid()
    for d in os.listdir('/proc'):
        if not d.isdigit() or int(d) == me: continue
        try: argv = open(f'/proc/{d}/cmdline', 'rb').read().decode('utf-8', 'replace').split('\0')
        except Exception: continue
        exe = os.path.basename(argv[0]) if argv else ''; cmd = ' '.join(argv)
        if exe in ('huggingface-cli', 'hf') and 'upload' in argv: return f'proc:{d}:{cmd[:80]}'
        if 'python' in exe and HF.search(' '.join(argv[1:])) and 'ee_municipal_t1' not in cmd: return f'proc:{d}:{cmd[:80]}'
    return None
def other_ee():
    me = os.getpid(); out = []
    for d in os.listdir('/proc'):
        if not d.isdigit() or int(d) in (me, os.getppid()): continue
        try: argv = open(f'/proc/{d}/cmdline', 'rb').read().decode('utf-8', 'replace').split('\0')
        except Exception: continue
        if argv and 'python' in os.path.basename(argv[0]) and any(x.endswith('ee_municipal_t1.py') for x in argv[1:3]) and ('run' in argv or 'offline' in argv): out.append(int(d))
    return out
def preflight(P, c):
    bad = []
    if os.path.exists(P['stop']): bad.append(f"STOP_EE present ({P['stop']}); remove it to allow a launch")
    m = S2.memavail()
    if m < c['launch_min_memavail']: bad.append(f"MemAvailable {m} MB < {c['launch_min_memavail']} at launch")
    ir = ir_busy()
    if ir: bad.append(f'IR encode/build/HF upload running: {ir}')
    o = other_ee()
    if o: bad.append(f'another EE job is running: {o}')
    if not os.path.exists(P['ehak']): bad.append('ref/ehak_2026v1_stat_ee.csv missing')
    if not os.path.exists(P['sums']): bad.append('evidence/SHA256SUMS_20261006.txt missing')
    try: import lxml  # noqa
    except Exception: bad.append('lxml missing in venv')
    return bad
def drive(argv):
    offline = argv[0] == 'offline'
    root = argv[argv.index('--root') + 1] if '--root' in argv else B
    P = paths(root); os.makedirs(P['build'], exist_ok=True); st = State(P['state']); c = load_cfg(P['cfg'])
    if not offline:
        tok = argv[argv.index('--cos-go') + 1] if '--cos-go' in argv else None
        if not (tok and os.path.exists(P['token']) and open(P['token']).readline().strip() == tok): sys.exit('REFUSED: needs the CoS GO token (ee_municipal/COS_GO_EE_T1)')
    if (st['status'] or '').startswith('T1_DONE'): glog('already done:', st['status']); sys.exit(0)
    bad = preflight(P, c)
    if bad:
        for b in bad: glog('REFUSED:', b)
        st.set(last_refusal=dict(ts=_now(), reasons=bad)); sys.exit(2)
    if '--shard-n' in argv:
        cf = json.load(open(P['cfg'])) if os.path.exists(P['cfg']) else {}; cf['shard_n'] = int(argv[argv.index('--shard-n') + 1]); atomic_json(P['cfg'], cf)
    signal.signal(signal.SIGTERM, lambda *a: STOP.set()); signal.signal(signal.SIGINT, lambda *a: STOP.set())
    def on_exit(status, why): st.set(status=status, end_reason=str(why)[:200], pid=None, exit_pt=time.strftime('%Y-%m-%d %H:%M %Z'))
    guard = Guard(P, on_exit=on_exit); threading.Thread(target=guard.watcher, daemon=True).start()
    st.set(status='T1_RUNNING', pid=os.getpid(), log=os.environ.get('EE_LOG'), started_pt=time.strftime('%Y-%m-%d %H:%M %Z'), mode='offline' if offline else 'run')
    glog('EE T1 START', 'offline' if offline else 'run', 'pid', os.getpid(), 'root', root, 'mem', S2.memavail(), 'guard', guard.c)
    end = 'UNKNOWN'
    try:
        if offline:
            zpath = argv[argv.index('--zip') + 1]
            if '--no-sha' not in argv and sha256_file(zpath, guard) != expected_sha(P): raise RuntimeError('offline zip sha256 != official')
        else:
            zpath = P['zip']
            if not ((st['download'] or {}).get('sha_ok') and os.path.exists(zpath)): download(P, st, guard, allow_redownload='--allow-redownload' in argv)
        if not (st['parse'] or {}).get('done'): st.set(status='T1_PARSING'); parse_zip(P, st, guard, zpath)
        st.set(status='T1_PACKING'); man = pack(P, st, guard)
        v = verify(P, expect_laws=st['parse']['kept']); st.set(verify1=v); glog('VERIFY', v)
        if not v['ok']: raise RuntimeError(f'verify failed: {v["problems"][:5]}')
        st.set(status='T1_REVIEW'); guard.check()
        r = subprocess.run(['nice', '-n', '19', sys.executable, '-u', '/workspace/scripts/ee_t1_review.py', '--root', root], capture_output=True, text=True, timeout=3600)
        sys.stdout.write(r.stdout[-3000:]); sys.stderr.write(r.stderr[-2000:])
        rv = json.load(open(f"{P['review']}/index.json")) if os.path.exists(f"{P['review']}/index.json") else {}
        last = (rv.get('packages') or [{}])[-1]
        if r.returncode != 0 or last.get('manifest_sha256') != sha256_file(P['manifest']): raise RuntimeError(f'review package not built for this manifest (rc {r.returncode})')
        v2 = verify(P, expect_laws=st['parse']['kept']); st.set(verify2=v2, review=last)
        if not v2['ok']: raise RuntimeError(f'verify (post-review) failed: {v2["problems"][:5]}')
        zabs = os.path.realpath(zpath)
        if '--keep-zip' in argv: glog('zip kept (--keep-zip)')
        elif zabs.startswith(os.path.realpath(P['build']) + '/') and os.path.exists(zabs):
            os.remove(zabs); glog('ZIP DELETED after verified shards + manifest + review:', zabs)
        else: glog('zip not deleted (outside <root>/build):', zabs)
        if os.path.exists(P['staging']) and '--keep-staging' not in argv: os.remove(P['staging']); glog('staging deleted (shards verified)')
        st.set(zip_deleted=not os.path.exists(zabs)); end = 'T1_DONE_AWAIT_COS_REVIEW'
    except Shed as e: end = 'T1_SHED_BASELINE'; glog('EE_SHED_BASELINE stop:', e)
    except MemShed as e: end = 'T1_MEMSHED'; glog('MEMSHED', e)
    except Stopped as e: end = 'T1_STOPPED_BY_STOPFILE' if os.path.exists(P['stop']) else 'T1_STOPPED_BY_SIGNAL'; glog('STOPPED', e)
    except Exception as e:
        import traceback; traceback.print_exc(); end = 'T1_REFUSED_REDOWNLOAD' if 'REFUSED_REDOWNLOAD' in str(e) else f'T1_ERROR_{type(e).__name__}'
        st.set(error=str(e)[:300])
    finally:
        STOP.set(); kill_children()
        if guard.checkpoint:
            try: guard.checkpoint()
            except Exception: pass
        on_exit(end, end); glog('EE T1 EXIT', end, 'guard', {k: v for k, v in guard.G.items() if k != 'termlogged'})
    sys.exit(0 if end.startswith('T1_DONE') else 2)
def guard_dryrun():
    import tempfile
    d = tempfile.mkdtemp(prefix='eeg_'); P = paths(d); g = Guard(P); ok_all = True; RSS = [80]
    print('cfg', {k: g.c[k] for k in ('pause_memavail', 'resume_memavail', 'resume_hold_s', 'hard_term_memavail', 'hard_term_sustain_s', 'instant_term_memavail',
                                      'max_pause_s', 'rss_limit_mb', 'baseline_shed_memavail', 'baseline_shed_sustain_s', 'launch_min_memavail')})
    class Sim:
        def __init__(s, f): s.f = f; s.t = 0.0; s.nw = g.c['hard_term_poll_s']
        def mem(s): return s.f(s.t)
        def clock(s): return s.t
        def sleep(s, dt):
            end = s.t + dt
            while s.nw <= end: s.t = s.nw; g.watch_tick(s.f(s.t), s.t, rss_fn=lambda: RSS[0]); s.nw += g.c['hard_term_poll_s']
            s.t = end
    def run(name, f, expect, pre=None):
        nonlocal ok_all
        g.G.update(min_mem=10 ** 9, n_pause=0, n_resume=0, n_filepause=0, low_t0=None, low_n=0, n_streaks=0, hard=None, hard_t=None, termlogged=False, base_t0=None, shed=None, shed_t=None)
        g.paused = False; STOP.clear(); s = Sim(f)
        if pre: pre(s)
        try: r = g.check(_sleep=s.sleep, _mem=s.mem, _clock=s.clock, _rss=lambda: RSS[0]); out = f'returned m={r}'
        except MemShed as e: out = f'TERM {e}'
        except Shed as e: out = f'SHED {e}'
        except Stopped: out = 'STOPPED'
        ok = out.startswith(expect); ok_all &= ok
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {out} | pauses={g.G['n_pause']} resumes={g.G['n_resume']} streaks={g.G['n_streaks']} sim_t={s.t:.0f}s")
    run('normal 5000', lambda t: 5000, 'returned m=5000')
    run('sync dip 3450 for 20s -> recover 4300 held 30s', lambda t: 3450 if t < 20 else 4300, 'returned')
    run('dip 3450 for 50s (<60s below 4200) -> resume', lambda t: 3450 if t < 50 else 4300, 'returned')
    run('3450 for 70s -> EE_SHED_BASELINE', lambda t: 3450 if t < 70 else 4300, 'SHED')
    run('4100 baseline at gate (no pause) after 60s below 4200 -> SHED',
        lambda t: 4100, 'SHED', pre=lambda s: (g._baseline(4100, -61.0)))
    run('4100 flapping to 4250 every 40s -> no SHED (gate passes, no pause)', lambda t: 4100, 'returned', pre=lambda s: (g._baseline(4100, -40.0), g._baseline(4250, -1.0)))
    for dd in (2, 4): run(f"{dd}s dip <3000 inside a pause -> no TERM", lambda t, dd=dd: 3450 if t < 4 else (2900 if t < 4 + dd else (3400 if t < 10 else 4400)), "returned")
    run('sustained >=5s <3000 -> TERM', lambda t: 3450 if t < 4 else 2900, 'TERM sustained_lt3000')
    run('single reading <2500 -> TERM', lambda t: 2400, 'TERM lt2500')
    RSS[0] = 320; run('rss 320MB -> TERM', lambda t: 5000, 'TERM rss=320MB'); RSS[0] = 80
    open(P['pause'], 'w').close()
    def fpf(t):
        if t >= 1000 and os.path.exists(P['pause']): os.remove(P['pause'])
        return 5000
    run('PAUSE_EE 1000s (mem fine) -> no 900s TERM, FILERESUME', fpf, 'returned')
    open(P['stop'], 'w').close(); run('STOP_EE present -> Stopped', lambda t: 5000, 'STOPPED'); os.remove(P['stop']); STOP.clear()
    os.rmdir(d)
    print('GUARD DRYRUN', 'ALL OK' if ok_all else 'FAILURES'); return ok_all
if __name__ == '__main__':
    a = sys.argv[1:]
    if not a: print(__doc__); sys.exit(1)
    if a[0] in ('run', 'offline'): drive(a)
    elif a[0] == 'verify':
        P = paths(a[a.index('--root') + 1] if '--root' in a else B); print(json.dumps(verify(P), indent=1))
    elif a[0] == 'status':
        P = paths(a[a.index('--root') + 1] if '--root' in a else B); print(json.dumps(State(P['state']).s, indent=1, ensure_ascii=False))
    elif a[0] == 'guard_dryrun': sys.exit(0 if guard_dryrun() else 1)
    else: print(__doc__); sys.exit(1)

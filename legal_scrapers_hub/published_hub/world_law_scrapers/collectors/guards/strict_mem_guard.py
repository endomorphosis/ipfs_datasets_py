#!/usr/bin/env python3
"""Shared STRICT memory guard matching NL-M thresholds (CoS 2026-10-05/06).
pause 3584 / resume 4200 held 30s / hard 3000 sustained 5s / instant 2500 /
RSS cap 300MB / max pause 900s. Offline-only helpers + guard_dryrun.
No network. Import from collector skeletons.
"""
from __future__ import annotations
import os, sys, time, json, threading, tempfile

DEFAULTS = dict(
    pause_memavail=3584, resume_memavail=4200, resume_hold_s=30,
    hard_term_memavail=1500, hard_term_sustain_s=10.0, hard_term_poll_s=2.0,
    instant_term_memavail=1000, max_pause_s=900, rss_limit_mb=300,
    delay_s=1.0,
)

class MemShed(Exception):
    pass

class Stopped(Exception):
    pass

def memavail():
    with open('/proc/meminfo') as f:
        for l in f:
            if l.startswith('MemAvailable:'):
                return int(l.split()[1]) // 1024
    return 0

def rss_mb(key='VmRSS'):
    with open('/proc/self/status') as f:
        for l in f:
            if l.startswith(key + ':'):
                return int(l.split()[1]) // 1024
    return 0

def load_cfg(path=None, overrides=None, delay_floor=0.5):
    c = dict(DEFAULTS)
    raw = {}
    if path and os.path.exists(path):
        try:
            raw = json.load(open(path))
        except Exception:
            raw = {}
        c.update({k: raw[k] for k in DEFAULTS if k in raw})
    if overrides:
        c.update({k: overrides[k] for k in DEFAULTS if k in overrides})
    c['pause_memavail'] = max(3300, int(c['pause_memavail']))
    c['resume_memavail'] = max(3800, c['pause_memavail'] + 1, int(c['resume_memavail']))
    c['resume_hold_s'] = max(10, int(c['resume_hold_s']))
    c['hard_term_memavail'] = min(c['pause_memavail'] - 1, max(1200, int(c['hard_term_memavail'])))
    c['hard_term_sustain_s'] = max(1.0, min(10.0, float(c['hard_term_sustain_s'])))
    c['hard_term_poll_s'] = max(0.5, min(2.0, float(c['hard_term_poll_s'])))
    c['instant_term_memavail'] = min(c['hard_term_memavail'] - 1, max(900, int(c['instant_term_memavail'])))
    c['max_pause_s'] = max(60, min(900, int(c['max_pause_s'])))
    c['rss_limit_mb'] = min(300, int(c['rss_limit_mb']))
    c['delay_s'] = max(float(delay_floor), float(c['delay_s']))
    return c

def atomic_json(p, obj):
    t = p + '.tmp'
    with open(t, 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.flush(); os.fsync(f.fileno())
    os.replace(t, p)

class StrictGuard:
    """NL-M-matching pause/resume/TERM gate. Main thread calls check() between units of work.
    Watcher thread flags hard conditions; check() raises MemShed / Stopped."""

    def __init__(self, cfg=None, stop_file=None, pause_file=None, log=print):
        self.c = dict(DEFAULTS if cfg is None else cfg)
        self.stop_file = stop_file
        self.pause_file = pause_file
        self.log = log
        self.lock = threading.Lock()
        self.paused = False
        self.alive = True
        self.G = dict(min_mem=10 ** 9, n_pause=0, n_resume=0, n_filepause=0, pause_s_total=0.0,
                      low_t0=None, low_n=0, n_streaks=0, hard=None, hard_t=None, termlogged=False)
        self._watcher = None

    def start_watcher(self):
        if self._watcher and self._watcher.is_alive():
            return
        self.alive = True
        self._watcher = threading.Thread(target=self._watch, daemon=True)
        self._watcher.start()

    def stop_watcher(self):
        self.alive = False

    def _watch(self):
        while self.alive:
            try:
                now = time.time()
                m = memavail()
                self.watch_tick(m, now)
            except Exception as e:
                try:
                    self.log(f'guard watcher error {e!r}')
                except Exception:
                    pass
            time.sleep(self.c['hard_term_poll_s'])

    def _low_streak(self, m, now):
        c = self.c
        with self.lock:
            if m < c['instant_term_memavail']:
                return f"lt{c['instant_term_memavail']} memavail={m}"
            if m >= c['hard_term_memavail']:
                if self.G['low_t0'] is not None:
                    self.log(f"MEMLOW_STREAK reset memavail={m} n={self.G['low_n']} dur_s={now - self.G['low_t0']:.1f} (no TERM)")
                self.G['low_t0'] = None
                self.G['low_n'] = 0
                return None
            if self.G['low_t0'] is None:
                self.G['low_t0'] = now
                self.G['n_streaks'] += 1
            self.G['low_n'] += 1
            dur = now - self.G['low_t0']
            self.log(f"MEMLOW_STREAK memavail={m} n={self.G['low_n']} dur_s={dur:.1f} sustain_s={c['hard_term_sustain_s']:g}")
            if dur >= c['hard_term_sustain_s']:
                return f"sustained_lt{c['hard_term_memavail']} dur_s={dur:.1f} n={self.G['low_n']} memavail={m}"
            return None

    def _hard(self, m, now, rss_fn=None):
        self.G['min_mem'] = min(self.G['min_mem'], m)
        why = self._low_streak(m, now)
        if why:
            return why
        r = (rss_fn or rss_mb)()
        if r > self.c['rss_limit_mb']:
            return f"rss={r}MB>{self.c['rss_limit_mb']}MB"
        return None

    def watch_tick(self, m, now, rss_fn=None):
        why = self._hard(m, now, rss_fn)
        if why and not self.G['hard']:
            self.G['hard'] = why
            self.G['hard_t'] = now
            self.log(f'MEMGUARD hard condition flagged: {why}')
        return self.G['hard']

    def _term(self, m, why):
        if not self.G['termlogged']:
            self.G['termlogged'] = True
            self.log(f"MEMTERM reason={why} memavail_now={m} min_memavail={self.G['min_mem']} pauses={self.G['n_pause']}")
        raise MemShed(why)

    def _stopcheck(self):
        if self.stop_file and os.path.exists(self.stop_file):
            raise Stopped('stopfile')

    def check(self, _sleep=time.sleep, _mem=None, _clock=time.time, _rss=None):
        mem = _mem or memavail
        self._stopcheck()
        m = mem(); now = _clock()
        why = self._hard(m, now, _rss) or self.G['hard']
        if why:
            self._term(m, why)
        pf = bool(self.pause_file and os.path.exists(self.pause_file))
        if m >= self.c['pause_memavail'] and not pf:
            return m
        t0 = _clock(); self.paused = True
        mode = 'file' if pf else 'mem'
        mem_t0 = None if pf else t0
        ok_since = None
        last_log = t0
        if pf:
            self.G['n_filepause'] += 1
            self.log(f'FILEPAUSE {self.pause_file} present memavail={m}')
        else:
            self.G['n_pause'] += 1
            self.log(f"MEMPAUSE memavail={m} pause_below={self.c['pause_memavail']} resume_at={self.c['resume_memavail']}x{self.c['resume_hold_s']}s n={self.G['n_pause']}")
        try:
            while True:
                _sleep(1)
                self._stopcheck()
                m = mem(); now = _clock()
                why = self._hard(m, now, _rss) or self.G['hard']
                if why:
                    self._term(m, why)
                pf = bool(self.pause_file and os.path.exists(self.pause_file))
                if pf:
                    mode = 'file'; mem_t0 = None; ok_since = None
                elif mode == 'file':
                    if m >= self.c['pause_memavail']:
                        break
                    mode = 'mem'; mem_t0 = now; ok_since = None
                    self.G['n_pause'] += 1
                    self.log(f'MEMPAUSE memavail={m} (after PAUSE file removed)')
                if mode == 'mem':
                    if now - mem_t0 > self.c['max_pause_s']:
                        self._term(m, f"paused>{self.c['max_pause_s']}s (paused_s={now - mem_t0:.0f})")
                    if m >= self.c['resume_memavail']:
                        ok_since = ok_since or now
                        if now - ok_since >= self.c['resume_hold_s']:
                            break
                    else:
                        ok_since = None
                if now - last_log >= 60:
                    last_log = now
                    self.log(f"{'FILEPAUSE' if mode == 'file' else 'MEMPAUSE'} waiting memavail={m} paused_s={now - t0:.0f}")
        finally:
            self.paused = False
        ps = _clock() - t0
        self.G['pause_s_total'] += ps
        if mode == 'file':
            self.log(f'FILERESUME memavail={m} paused_s={ps:.0f}')
        else:
            self.G['n_resume'] += 1
            self.log(f"MEMRESUME memavail={m} paused_s={ps:.0f} n={self.G['n_resume']}")
        return m

    def stats(self):
        return dict(min_memavail_mb=self.G['min_mem'], n_pause=self.G['n_pause'],
                    n_resume=self.G['n_resume'], pause_s_total=round(self.G['pause_s_total'], 1),
                    hard=self.G['hard'], rss_mb=rss_mb())


def guard_dryrun(cfg=None, label='STRICT'):
    """Simulated memory traces against StrictGuard. No network, no durable files. Returns True iff all cases pass."""
    c = dict(DEFAULTS if cfg is None else cfg)
    g = StrictGuard(c, stop_file='/nonexistent/STOP', pause_file='/nonexistent/PAUSE', log=lambda *a: None)
    print(f'cfg[{label}]', {k: c[k] for k in ('pause_memavail', 'resume_memavail', 'resume_hold_s',
          'hard_term_memavail', 'hard_term_sustain_s', 'hard_term_poll_s', 'instant_term_memavail',
          'max_pause_s', 'rss_limit_mb', 'delay_s')})
    RSS = [80]
    ok_all = True

    class Sim:
        def __init__(s, f):
            s.f = f; s.t = 0.0; s.nw = c['hard_term_poll_s']
        def mem(s): return s.f(s.t)
        def clock(s): return s.t
        def sleep(s, d):
            end = s.t + d
            while s.nw <= end:
                s.t = s.nw
                g.watch_tick(s.f(s.t), s.t, rss_fn=lambda: RSS[0])
                s.nw += c['hard_term_poll_s']
            s.t = end

    def run(name, f, expect, pf=None):
        nonlocal ok_all
        g.G.update(min_mem=10 ** 9, n_pause=0, n_resume=0, n_filepause=0, low_t0=None, low_n=0,
                   n_streaks=0, hard=None, hard_t=None, termlogged=False)
        g.paused = False
        g.pause_file = pf or '/nonexistent/PAUSE'
        s = Sim(f)
        try:
            r = g.check(_sleep=s.sleep, _mem=s.mem, _clock=s.clock, _rss=lambda: RSS[0])
            out = f'returned m={r}'
        except MemShed as e:
            out = f'TERM {e}'
        except Stopped:
            out = 'STOPPED'
        ok = out.startswith(expect)
        ok_all &= ok
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {out} | pauses={g.G['n_pause']} resumes={g.G['n_resume']} streaks={g.G['n_streaks']} sim_t={s.t:.0f}s")

    run('normal', lambda t: 5000, 'returned m=5000')
    run('dip 3450 -> recover 4300 (held 30s)', lambda t: 3450 if t < 25 else 4300, 'returned')
    run('flap 4300/4100 resets hold', lambda t: 3450 if t < 5 else (4100 if 10 <= t < 12 else 4300), 'returned')
    run('recover only to 4000 (<4200) -> stays paused >900s -> TERM', lambda t: 3450 if t < 1 else 4000, 'TERM paused>900')
    for d in (1, 2, 3, 4):
        run(f'{d}s dip <3000 inside a pause -> no TERM',
            lambda t, d=d: 3450 if t < 4 else (2900 if t < 4 + d else (3400 if t < 30 else 4400)), 'returned')
    run('sustained >=5s <3000 -> TERM', lambda t: 3450 if t < 4 else (2900 if t < 30 else 4400), 'TERM sustained_lt3000')
    run('single reading <2500 -> TERM', lambda t: 3450 if t < 6 else (2400 if t < 6.5 else 3450), 'TERM lt2500')
    run('single reading <2500 at gate -> TERM', lambda t: 2400, 'TERM lt2500')
    RSS[0] = 320
    run('collector self rss 320MB -> TERM (immediate)', lambda t: 5000, 'TERM rss=320MB')
    RSS[0] = 80
    pfd = tempfile.mkdtemp(prefix='sgpf_')
    pfile = f'{pfd}/PAUSE'
    open(pfile, 'w').close()
    def f_pf(t):
        if t >= 40 and os.path.exists(pfile):
            os.remove(pfile)
        return 5000
    run('PAUSE file for 40s (mem fine) -> FILEPAUSE then FILERESUME', f_pf, 'returned', pf=pfile)
    open(pfile, 'w').close()
    def f_pf2(t):
        if t >= 1200 and os.path.exists(pfile):
            os.remove(pfile)
        return 5000
    run('PAUSE file 1200s -> no 900s TERM while file exists', f_pf2, 'returned', pf=pfile)
    try:
        os.rmdir(pfd)
    except OSError:
        pass
    sfd = tempfile.mkdtemp(prefix='sgsf_')
    g.stop_file = f'{sfd}/STOP'
    open(g.stop_file, 'w').close()
    run('STOP file present -> Stopped', lambda t: 5000, 'STOPPED')
    os.remove(g.stop_file)
    try:
        os.rmdir(sfd)
    except OSError:
        pass
    g.stop_file = '/nonexistent/STOP'
    print('GUARD DRYRUN', 'ALL OK' if ok_all else 'FAILURES')
    return ok_all


if __name__ == '__main__':
    sys.exit(0 if guard_dryrun() else 1)

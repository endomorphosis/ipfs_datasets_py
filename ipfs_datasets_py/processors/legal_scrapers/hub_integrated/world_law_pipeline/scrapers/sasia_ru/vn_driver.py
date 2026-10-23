"""Resumable driver: runs vn_vbpl_archive.py one province at a time and records done provinces in _ru/vn_done.txt
(respects rate limits; never bypasses the breaker).

2026-10-18 throttle deferral (shared ArchiveFetcher raises ArchiveDeferred on 429/5xx / host cool-down):
* A province whose child run reports status deferred/transient (some item or the CDX listing was deferred) is NOT
  marked done (the child did not stage it either). Its deferred items are persisted in _ru/vn_deferred.jsonl
  (one line per item: slug, item, url, not_before, reason) and the driver moves on to the next province. A deferred
  province is re-run once its not_before has passed (due revisits go before fresh provinces); the re-run is cheap
  (CDX + bodies come from the archive disk cache). An empty result caused by deferrals is never 'province empty'.
* While web.archive.org is cooling down box-wide (archive.deferral.host_cooldown) no child is started (every
  request would be deferred at once); the driver waits for the cool-down to end, it does not retry anything early.
* Real Wayback breaker: unchanged behaviour, wait in place (300 s checks) and then run the interrupted province again.
* CDX error (non-throttle, e.g. non-JSON / 403): retried after CDX_ERROR_RETRY_S, parked after MAX_CHILD_ERRORS,
  never marked done (12:10 follow-up; it used to be marked done).
* Child crash / missing stats: deferred CHILD_ERROR_RETRY_S, never marked done; after MAX_CHILD_ERRORS it is parked
  (status 'parked' in vn_deferred.jsonl, not done) for a manual look.
* Single instance (flock _ru/vn_driver.lock). SIGTERM/SIGINT: the running child is killed (it stages only at the end
  of a complete province, atomically), so stop/restart at any time is a clean boundary.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, re, os, time, json, subprocess, signal, fcntl

sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline'))
D = os.environ.get('VN_DRIVER_DIR', '/workspace/world_law/staging/sasia_ru/_ru/')
P = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/sasia_ru/vn_vbpl_archive.py')
WB_HOST = 'web.archive.org'
BREAKER_WAIT_S = 300
CHILD_ERROR_RETRY_S = 600
CDX_ERROR_RETRY_S = 1800
MAX_CHILD_ERRORS = 5
MAX_IDLE_SLEEP_S = 300
RETRYABLE = ('deferred', 'transient', 'breaker')


def log(*a):
    print(time.strftime('%T'), *a, flush=True)


def province_order():
    sl = re.findall(r"^ \('([a-z]+)', '(?:iso|wd):", open(P).read(), re.M)
    return ['nghean'] + [s for s in sl if s != 'nghean']


def load_done(d=None):
    d = d or D
    return set(open(d + 'vn_done.txt').read().split()) if os.path.exists(d + 'vn_done.txt') else set()


def mark_done(s, d=None):
    with open((d or D) + 'vn_done.txt', 'a') as f:
        f.write(s + '\n')


def load_deferred(d=None):
    """-> {slug: {'not_before', 'status', 'attempts', 'items': [...]}} from vn_deferred.jsonl."""
    p = (d or D) + 'vn_deferred.jsonl'
    q = {}
    if not os.path.exists(p):
        return q
    for line in open(p):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        e = q.setdefault(r['slug'], {'not_before': 0.0, 'status': r.get('status', 'deferred'),
                                     'attempts': int(r.get('attempts', 0) or 0), 'items': []})
        e['not_before'] = max(e['not_before'], float(r.get('not_before', 0) or 0))
        e['attempts'] = max(e['attempts'], int(r.get('attempts', 0) or 0))
        e['items'].append(r)
    return q


def save_deferred(q, d=None):
    p = (d or D) + 'vn_deferred.jsonl'
    tmp = p + f'.{os.getpid()}.tmp'
    with open(tmp, 'w') as f:
        for slug, e in q.items():
            items = e['items'] or [{'slug': slug, 'item': '__province__', 'url': ''}]
            for it in items:
                r = dict(it, slug=slug, status=e['status'], attempts=e['attempts'],
                         not_before=round(e['not_before'], 1),
                         not_before_pt=time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(e['not_before'])),
                         updated=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)


def run_child(s, d=None):
    """Run one province in a child; returns (returncode, stat dict or None, stdout)."""
    d = d or D
    stats_p = d + 'vn_vbpl_stats.json'
    if os.path.exists(stats_p):
        os.replace(stats_p, stats_p + '.prev')        # never read a stale result
    r = subprocess.run([sys.executable, P, '--only', s, '--per-place', '40', '--stage', '--out', d + '_vnout_' + s,
                        '--stats', stats_p], env={**os.environ, 'ARCHIVE_LANE': 'sasia_ru'},
                       capture_output=True, text=True)
    st = None
    try:
        st = json.load(open(stats_p)).get(s)
    except (OSError, ValueError):
        pass
    if r.returncode != 0:
        log(s, 'child rc', r.returncode, (r.stderr or '')[-800:].replace('\n', ' | '))
    return r.returncode, st, r.stdout


def apply_result(s, rc, st, q, now=None):
    """Update queue/done for one child result. Returns 'done' | 'requeued' | 'breaker' | 'parked'."""
    now = time.time() if now is None else now
    prev = q.get(s, {})
    if rc != 0 or not isinstance(st, dict) or 'status' not in st:
        att = int(prev.get('attempts', 0)) + 1
        q[s] = {'not_before': now + CHILD_ERROR_RETRY_S, 'attempts': att, 'items': prev.get('items', []),
                'status': 'parked' if att >= MAX_CHILD_ERRORS else 'child_error'}
        return 'parked' if att >= MAX_CHILD_ERRORS else 'requeued'
    status = st['status']
    if status == 'complete':                           # only a province with zero deferred items is done
        q.pop(s, None)
        return 'done'
    if status == 'cdx_error':                          # 12:10 follow-up: no longer 'done' (was); retry, park after N
        att = int(prev.get('attempts', 0)) + 1
        q[s] = {'not_before': now + CDX_ERROR_RETRY_S, 'attempts': att,
                'items': [{'slug': s, 'item': '__cdx__', 'url': '', 'reason': 'cdx_error', 'error': str(st.get('error', ''))[:200]}],
                'status': 'parked' if att >= MAX_CHILD_ERRORS else 'cdx_error'}
        return 'parked' if att >= MAX_CHILD_ERRORS else 'requeued'
    if status in RETRYABLE:
        items = [dict(it, slug=s) for it in st.get('deferred', [])]
        nb = max([float(st.get('not_before', 0) or 0)] + [float(it.get('not_before', 0) or 0) for it in items])
        if status == 'breaker':
            nb = now                                   # rerun as soon as the breaker is closed again
        q[s] = {'not_before': max(nb, now if status == 'breaker' else nb), 'attempts': int(prev.get('attempts', 0)) + 1,
                'items': items, 'status': status}
        return 'breaker' if status == 'breaker' else 'requeued'
    att = int(prev.get('attempts', 0)) + 1             # unknown status: never 'done'
    q[s] = {'not_before': now + CHILD_ERROR_RETRY_S, 'attempts': att, 'items': [],
            'status': 'parked' if att >= MAX_CHILD_ERRORS else 'unknown_status:' + str(status)}
    return 'requeued'


def pick_next(todo, q, now):
    """Due deferred province (earliest not_before) first, then the next fresh one; None if nothing is due."""
    due = sorted((q[s]['not_before'], s) for s in todo if s in q and q[s]['status'] != 'parked' and q[s]['not_before'] <= now)
    if due:
        return due[0][1]
    for s in todo:
        if s not in q:
            return s
    return None


def drive(order, *, d=None, runner=run_child, wb_available=None, host_cooldown=None, sleep=time.sleep, clock=time.time,
          max_loops=None):
    d = d or D
    if wb_available is None or host_cooldown is None:
        from archive import ratelimit, deferral
        wb_available = wb_available or ratelimit.wayback_available
        host_cooldown = host_cooldown or (lambda: deferral.host_cooldown(WB_HOST))
    done = load_done(d)
    q = load_deferred(d)
    for s in list(q):
        if s in done:                                  # stale entry (done elsewhere): drop
            q.pop(s)
    save_deferred(q, d)
    loops = 0
    while True:
        loops += 1
        if max_loops and loops > max_loops:
            return 'max_loops'
        todo = [s for s in order if s not in done]
        live = [s for s in todo if q.get(s, {}).get('status') != 'parked']
        if not live:
            log('driver finished;', len(done), 'done,', len(todo), 'parked:', todo)
            return 'finished'
        if not wb_available():
            log('breaker open; waiting'); sleep(BREAKER_WAIT_S); continue
        cool = host_cooldown()
        if cool > 0:
            log(f'{WB_HOST} cooling down {cool:.0f}s (box-wide); {len(q)} province(s) deferred; waiting for cool-down')
            sleep(min(cool + 1, MAX_IDLE_SLEEP_S)); continue
        now = clock()
        s = pick_next(live, q, now)
        if s is None:
            nb = min(q[x]['not_before'] for x in live if x in q)
            w = max(1.0, min(nb - now, MAX_IDLE_SLEEP_S))
            log(f'all {len(live)} remaining province(s) deferred; next due in {nb - now:.0f}s'); sleep(w); continue
        tag = f'(revisit #{q[s]["attempts"]}, was {q[s]["status"]})' if s in q else ''
        log('start', s, tag)
        rc, st, out = runner(s, d)
        staged = [l for l in (out or '').splitlines() if l.startswith('staged')]
        res = apply_result(s, rc, st, q, clock())
        brief = {k: v for k, v in (st or {}).items() if k != 'deferred'} if isinstance(st, dict) else st
        ndef = len((st or {}).get('deferred', [])) if isinstance(st, dict) else 0
        log(s, brief, f'deferred_items={ndef}', staged, '->', res)
        if res == 'done':
            mark_done(s, d); done.add(s)
        save_deferred(q, d)


def main():
    lock = open(D + 'vn_driver.lock', 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log('another vn_driver holds', D + 'vn_driver.lock', '; exiting'); sys.exit(1)

    def _stop(sig, frm):
        log('signal', sig, '-> stopping (child killed, nothing marked done)')
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log('vn_driver start pid', os.getpid(), '(deferral-aware)')
    drive(province_order())


if __name__ == '__main__':
    main()

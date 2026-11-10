#!/usr/bin/env python3
"""Pack NL-M out/ (laws/*.json.gz + articles/*.jsonl.gz) into persisted shards under index/out_packed/ (out/ itself is excluded by the
box sync's default ignore list: unanchored 'out/'). Streaming, one regulation at a time; loose out/ files are never modified or deleted.

INCREMENTAL REPACK POLICY (CoS 2026-10-05 17:48 PT). Usage (always low priority):
  nice -n 19 ionice -c3 /workspace/venv/bin/python -u /workspace/scripts/nlm_pack_out.py --dry-run          # report counts + guard state only
  nice -n 19 ionice -c3 /workspace/venv/bin/python -u /workspace/scripts/nlm_pack_out.py --wait-window-s 1800   # normal incremental run
  ... --force-min 1000      # override the >=5000-new-regulations threshold (N = new minimum)
  ... --final               # also flush a partial (<1000) tail shard (end of collection only)
  Options: --collector-log/--collector-pid (default: nlm_log/nlm_pid from the PIN), --start-mb 4200, --abort-mb 3600, --max-shards 0 (=all),
           --dst DIR (testing only).
What it packs: ok rows of COMPLETED scan chunks (index/scan, source of truth) that have both out files and are NOT yet in any shard of
  out_packed/plan.json / manifest.json, sorted by id DESC, into NEW ~1000-regulation shards appended to plan + manifest (sha256, counts,
  id range). Existing shards are never rewritten. Shard line = {"id","law":{...},"articles":[...]}; written to .tmp, fsynced, os.replace'd.
GUARD (refuses / aborts; never bursts while the collector is fetching):
  (a) >= 5000 unpacked new regulations (or --force-min N); only full 1000-shards unless --final.
  (b) collector window: the collector log's latest guard event is MEMPAUSE (no later MEMRESUME) with the pid alive ('paused'), OR the
      collector process is not running and its log ends at a chunk boundary (CHUNK written / TERMINATED / MEMTERM / RESTART / DONE)
      ('stopped_at_boundary'). An alive collector right after 'CHUNK written' is already fetching the next chunk -> not eligible.
      Each shard also needs MemAvail >= --start-mb (4200; i.e. the collector's 30s resume-hold window after a dip).
  Mid-shard abort (tmp removed, nothing partial): any new collector log line other than MEMPAUSE waiting / MEMSTAT / MEMLOW_STREAK
  (e.g. MEMRESUME, progress, ERR, BACKOFF, CHUNK, START), any new file in raw/{manifest,xml,stop} or out/{laws,articles} (= a fetch started),
  MemAvail < 3600 (--abort-mb), or own RSS > 200MB. Hard exit if MemAvail < 3000. With --wait-window-s the packer waits for the next
  eligible window and redoes the aborted shard, else it exits 4. Exit codes: 0 done / nothing to do, 3 guard (a) not met, 4 no window/aborted."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, gzip, json, time, hashlib, argparse, re
B = '{_CORPORA}/nl_municipal'; SCAN = f'{B}/index/scan'; OUTL = f'{B}/out/laws'; OUTA = f'{B}/out/articles'
DST = f'{B}/index/out_packed'; PIN = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'
WATCH_DIRS = [f'{B}/raw/manifest', f'{B}/raw/xml', f'{B}/raw/stop', OUTL, OUTA]
ap = argparse.ArgumentParser()
ap.add_argument('--shard-n', type=int, default=1000); ap.add_argument('--final', action='store_true')
ap.add_argument('--force-min', type=int, default=None); ap.add_argument('--dry-run', action='store_true')
ap.add_argument('--wait-window-s', type=int, default=0); ap.add_argument('--max-shards', type=int, default=0)
ap.add_argument('--collector-log', default=None); ap.add_argument('--collector-pid', type=int, default=None)
ap.add_argument('--start-mb', type=int, default=4200); ap.add_argument('--abort-mb', type=int, default=3600)
ap.add_argument('--sleep-per-file', type=float, default=0.004)
ap.add_argument('--dst', default=DST, help='testing only: alternate shard dir')
a = ap.parse_args(); DST = a.dst; MIN_NEW = a.force_min if a.force_min is not None else 5000
def log(*x): print(time.strftime('%Y-%m-%d %H:%M:%S'), *x, flush=True)
def memavail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
def rss():
    for l in open('/proc/self/status'):
        if l.startswith('VmRSS:'): return int(l.split()[1]) // 1024
MIN = [10 ** 9]
class Abort(Exception): pass
def atomic_json(p, obj):
    t = p + '.tmp'
    with open(t, 'w') as f: json.dump(obj, f, indent=1); f.flush(); os.fsync(f.fileno())
    os.replace(t, p)
# ---------------- collector state ----------------
try: pin = json.load(open(PIN))
except Exception: pin = {}
CLOG = a.collector_log or pin.get('nlm_log'); CPID = a.collector_pid or pin.get('nlm_pid')
def collector_pids():
    out = []
    for d in os.listdir('/proc'):
        if d.isdigit():
            try:
                c = open(f'/proc/{d}/cmdline', 'rb').read().split(b'\0')
                if any(x.endswith(b'nl_municipal_collect.py') for x in c) and b'full' in c and int(d) != os.getpid(): out.append(int(d))
            except Exception: pass
    return out
QUIET = re.compile(r' (MEMPAUSE waiting|MEMSTAT|MEMLOW_STREAK|MEMGUARD hard condition flagged|CONFIG reloaded|RSS WARN)')
BOUNDARY = re.compile(r' (CHUNK written|TERMINATED cleanly|MEMTERM|RESTART |DONE|STOPPED|STOP )')
def collector_state():
    """returns (state, detail): paused | stopped_at_boundary | fetching | stopped_mid | no_log"""
    if not CLOG or not os.path.exists(CLOG): return ('no_log', CLOG)
    with open(CLOG, 'rb') as f:
        f.seek(max(0, os.path.getsize(CLOG) - 65536)); lines = f.read().decode('utf-8', 'replace').splitlines()
    pids = collector_pids(); meaningful = [l for l in lines if l.strip() and not QUIET.search(l)]
    last = meaningful[-1] if meaningful else ''
    if pids:
        if ' MEMPAUSE memavail=' in last: return ('paused', f'pids={pids} last={last[:120]}')
        return ('fetching', f'pids={pids} last={last[:120]}')
    if BOUNDARY.search(last): return ('stopped_at_boundary', f'no collector process; last={last[:120]}')
    return ('stopped_mid', f'no collector process; last={last[:120]}')
def dir_sig(): return tuple(os.stat(d).st_mtime_ns for d in WATCH_DIRS if os.path.exists(d))
class Watch:
    """mid-shard abort detector: collector log growth with non-quiet lines, new files in raw/out dirs, MemAvail"""
    def __init__(s):
        s.off = os.path.getsize(CLOG) if CLOG and os.path.exists(CLOG) else 0; s.sig = dir_sig(); s.n = 0
    def check(s):
        s.n += 1; m = memavail(); MIN[0] = min(MIN[0], m)
        if m < 3000: log(f'PACK HARDEXIT memavail={m}'); sys.exit(5)
        if m < a.abort_mb: raise Abort(f'memavail={m}<{a.abort_mb}')
        if rss() > 200: log(f'PACK HARDEXIT rss={rss()}MB'); sys.exit(6)
        if CLOG and os.path.exists(CLOG) and os.path.getsize(CLOG) > s.off:
            with open(CLOG, 'rb') as f: f.seek(s.off); new = f.read().decode('utf-8', 'replace'); s.off += len(new.encode())
            bad = [l for l in new.splitlines() if l.strip() and not QUIET.search(l)]
            if bad: raise Abort(f'collector log: {bad[0][:120]}')
        if dir_sig() != s.sig: raise Abort('new file in raw/ or out/ (collector fetch started)')
def eligible_now():
    st, det = collector_state(); m = memavail()
    return (st in ('paused', 'stopped_at_boundary') and m >= a.start_mb), st, det, m
def wait_window(deadline):
    last = 0
    while True:
        ok, st, det, m = eligible_now()
        if ok: log(f'PACK WINDOW state={st} memavail={m} ({det})'); return True
        if time.time() > deadline: log(f'PACK no eligible window (state={st} memavail={m})'); return False
        if time.time() - last > 60: last = time.time(); log(f'PACK waiting for window: state={st} memavail={m}')
        time.sleep(1)
# ---------------- plan ----------------
os.makedirs(DST, exist_ok=True)
plan_p, man_p = f'{DST}/plan.json', f'{DST}/manifest.json'
plan = json.load(open(plan_p)) if os.path.exists(plan_p) else dict(shard_n=a.shard_n, order='id_desc', shards=[])
man = json.load(open(man_p)) if os.path.exists(man_p) else dict(shards={})
for n, v in man['shards'].items():  # existing shards are immutable: sanity-check size only (cheap)
    if not os.path.exists(f'{DST}/{n}') or os.path.getsize(f'{DST}/{n}') != v['bytes']: sys.exit(f'existing shard {n} missing or size mismatch; refusing')
planned = {i for s in plan['shards'] for i in s['ids']}
pending = [s for s in plan['shards'] if s['name'] not in man['shards']]  # planned earlier, not yet packed (e.g. aborted)
cand = set()  # 2026-10-14: ok rows from index/scan UNION index/rescan_bom (BOM rescan records), deduped by id
RESCAN = f'{B}/index/rescan_bom'; n_rescan_ok = 0
for d in (SCAN, RESCAN):
    if not os.path.isdir(d): continue
    for fn in sorted(os.listdir(d)):
        if not re.fullmatch(r'\d{6}\.jsonl\.gz', fn): continue
        with gzip.open(f'{d}/{fn}', 'rt') as f:
            for l in f:
                r = json.loads(l)
                if r.get('s') == 'ok' and r['id'] not in planned:
                    if d == RESCAN and r['id'] not in cand: n_rescan_ok += 1
                    cand.add(r['id'])
cand = sorted(cand, reverse=True)
log(f'PACK SOURCES rescan_bom ok (new, not in scan ok) = {n_rescan_ok}')
have = [i for i in cand if os.path.exists(f'{OUTL}/CVDR{i}.json.gz') and os.path.exists(f'{OUTA}/CVDR{i}.jsonl.gz')]
n_new = len(have) + sum(len(s['ids']) for s in pending)
st, det = collector_state()
log(f'PACK STATUS packed_shards={len(man["shards"])} packed_regs={man.get("n_regulations", 0)} unpacked_new={n_new} (unplanned {len(have)}, '
    f'planned-pending {sum(len(s["ids"]) for s in pending)}; ok rows lacking out files {len(cand) - len(have)}) min_new={MIN_NEW} '
    f'collector_state={st} memavail={memavail()} ({det})')
if n_new < MIN_NEW: log(f'PACK GUARD(a) not met: {n_new} < {MIN_NEW} new regulations; nothing packed'); sys.exit(0 if a.dry_run else 3)
if a.dry_run:
    log(f'PACK DRY-RUN: would plan {len(have) // a.shard_n + (1 if a.final and len(have) % a.shard_n else 0)} new shard(s) + {len(pending)} pending; '
        f'window eligible now={eligible_now()[0]}'); sys.exit(0)
k = len(plan['shards'])
while len(have) >= plan['shard_n'] or (a.final and have):
    ids, have = have[:plan['shard_n']], have[plan['shard_n']:]
    plan['shards'].append(dict(name=f'nlm_out_{k:05d}.jsonl.gz', ids=ids)); k += 1
atomic_json(plan_p, plan)
todo = [s for s in plan['shards'] if s['name'] not in man['shards']]
if a.max_shards: todo = todo[:a.max_shards]
log('PACK PLAN todo_shards', len(todo), 'unplanned_tail', len(have))
# ---------------- pack ----------------
def write_shard(s):
    p = f"{DST}/{s['name']}"; t = p + '.tmp'; h = hashlib.sha256(); na = 0; w = Watch()
    try:
        with open(t, 'wb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=6, mtime=0) as g:
                for i in s['ids']:
                    w.check()
                    law = json.loads(gzip.decompress(open(f'{OUTL}/CVDR{i}.json.gz', 'rb').read()))
                    with gzip.open(f'{OUTA}/CVDR{i}.jsonl.gz', 'rt', encoding='utf-8') as f: arts = [json.loads(l) for l in f]
                    na += len(arts)
                    g.write((json.dumps(dict(id=f'CVDR{i}', law=law, articles=arts), ensure_ascii=False) + '\n').encode())
                    del law, arts
                    if a.sleep_per_file: time.sleep(a.sleep_per_file)
            raw.flush(); os.fsync(raw.fileno())
        w.check()
    except BaseException:
        try: os.remove(t)
        except OSError: pass
        raise
    with open(t, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    os.replace(t, p)
    return dict(n_regulations=len(s['ids']), n_articles=na, id_hi=s['ids'][0], id_lo=s['ids'][-1], bytes=os.path.getsize(p),
                sha256=h.hexdigest(), packed_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
t0 = time.time(); deadline = t0 + a.wait_window_s; nnew = 0
for s in todo:
    while True:
        ok, st, det, m = eligible_now()
        if not ok:
            log(f'PACK not in window before {s["name"]}: state={st} memavail={m}')
            if not a.wait_window_s or not wait_window(deadline): log('PACK EXIT (no window); packed', nnew); sys.exit(4)
        try:
            man['shards'][s['name']] = write_shard(s); nnew += 1
            man.update(n_shards=len(man['shards']), n_regulations=sum(v['n_regulations'] for v in man['shards'].values()),
                       n_articles=sum(v['n_articles'] for v in man['shards'].values()), source='index/scan ok rows x out/{laws,articles}',
                       format='jsonl.gz: {"id","law","articles"} per line', updated=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
            atomic_json(man_p, man); v = man['shards'][s['name']]
            log('SHARD', s['name'], v['n_regulations'], 'regs', v['n_articles'], 'arts', f"{v['bytes']/1e6:.1f}MB", f'mem={memavail()}MB rss={rss()}MB')
            break
        except Abort as e:
            log(f'PACK ABORT shard {s["name"]}: {e.args[0]}; tmp removed')
            if not a.wait_window_s: log('PACK EXIT (aborted); packed', nnew); sys.exit(4)
            time.sleep(2)
log('PACK DONE new_shards', nnew, 'total_shards', len(man['shards']), 'regs', man.get('n_regulations'), 'arts', man.get('n_articles'),
    f'min_memavail={MIN[0]} elapsed_s={time.time() - t0:.0f} rss={rss()}MB')

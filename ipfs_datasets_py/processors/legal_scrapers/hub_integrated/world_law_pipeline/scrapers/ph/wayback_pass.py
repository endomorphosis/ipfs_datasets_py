"""Wayback pass for dead PH LGU sites (staging/ph/_state/wayback_deferred.jsonl).
Shared archive module (box-wide limiter, breaker, per-host cool-down), ARCHIVE_LANE=ph, Wayback only, 1 worker.
Per host: CDX domain listing of archived PDFs + HTML naming an ordinance/resolution/EO -> fetch -> stage via
archive.StagedWriter (staging/ph/PH/<pk>.archive<UTC>pNNNN.jsonl + _archive_provenance sidecar).

Deferral (2026-10-18; fetch_best raises ArchiveDeferred when throttled, None = genuine miss; listings checked for
.truncated/.deferred): ArchiveDeferred (429/5xx/host cool-down) and other ArchiveTransient (breaker open) are never
retried in place. The item (cdx listing or doc) is requeued with not_before (persisted in
_state/wayback_deferred_items.jsonl, append-only: 'deferred' and 'resolved' events) and the scheduler moves on to the
next ready item/place. It sleeps only when every remaining item is deferred, until the earliest not_before.
A place is marked done (wayback_done[_pass2].jsonl) only when its listing is done and no doc is pending or deferred.
Checkpoints: wayback_done.jsonl, wayback_docs.jsonl (per doc URL, written after the writer flushes),
wayback_cand/<pk>.json (CDX candidate list, so a listing is never redone), wayback_capped.jsonl.
Pass 1: first PH_WB_MAXDOCS (25) docs per place. --second-pass: only capped places, remaining docs (skips URLs in
wayback_docs and doc_ids in _archive_provenance/PH). SIGTERM: flush, exit 143. Disk < 35 GB free: flush, exit 75."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, re, json, time, shutil, hashlib, subprocess, tempfile, datetime, resource, logging, glob, signal, dataclasses
os.environ.setdefault('ARCHIVE_LANE', 'ph')
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline')); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))   # hard guard; RSS target < 500 MB
from archive import ArchiveFetcher, StagedWriter, provenance_fields
from archive.core import ArchiveTransient, ArchiveError, ArchiveDeferred, Capture, good_doc
from archive import ratelimit
from urllib.parse import urlparse, unquote
import ph_crawl as C
logging.basicConfig(level=logging.WARNING)
ST = os.environ.get('PH_WB_ST', '/workspace/world_law/staging/ph/_state')
STAGE = os.environ.get('PH_WB_STAGE', '/workspace/world_law/staging/ph')
MAXDOCS = int(os.environ.get('PH_WB_MAXDOCS', '25'))
BREAKER_WAIT = 300; TRANSIENT_WAIT = 600
SECOND = '--second-pass' in sys.argv
CAPPED = ST + '/wayback_capped.jsonl'; DEFQ = ST + '/wayback_deferred_items.jsonl'; CANDDIR = ST + '/wayback_cand'
DONE = ST + ('/wayback_done_pass2.jsonl' if SECOND else '/wayback_done.jsonl'); DOCS = ST + '/wayback_docs.jsonl'
STOP = {'flag': False}
signal.signal(signal.SIGTERM, lambda *a: STOP.update(flag=True))
now = lambda: datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def log(*a): print(now(), *a, flush=True)
def disk_ok(): return shutil.disk_usage(STAGE).free >= 35 * 2**30
def rss_mb(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
def clean(v): return None if v is None or (isinstance(v, float) and v != v) else v
def jl(path): return [json.loads(l) for l in open(path)] if os.path.exists(path) else []
def did(url): return 'u' + hashlib.sha1(url.encode()).hexdigest()[:16]
HTMLKW = r'.*(ordinance|resolution|executive-order|executive_order|kautusan|sangguniang|legislative).*'
PROC = re.compile(r'\b(bac|bids?|awards?|procurement|notice[\s_-]*of[\s_-]*award|noa|ntp|philgeps)\b', re.I)
fx = None

def pdf_to_text(body):
    with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
        f.write(body); f.flush()
        try: return subprocess.run(['pdftotext', '-layout', '-l', '60', f.name, '-'], capture_output=True, timeout=120).stdout.decode('utf-8', 'replace')
        except Exception: return ''

class Defer(Exception):
    def __init__(self, nb, why): super().__init__(why); self.nb, self.why = nb, why

def call(fn, *a, **kw):
    """Run one archive call; ArchiveDeferred/ArchiveTransient -> Defer(not_before). No retry here."""
    if not ratelimit.wayback_available(): raise Defer(time.time() + BREAKER_WAIT, 'breaker_open')
    try: return fn(*a, **kw)
    except ArchiveDeferred as e: raise Defer(max(float(e.not_before or 0), time.time() + 1), f'deferred:{e.status}:{str(e)[:120]}')
    except ArchiveTransient as e: raise Defer(time.time() + TRANSIENT_WAIT, f'transient:{str(e)[:120]}')

class DefQ:
    """Persistent deferred-item queue (append-only events)."""
    def __init__(s):
        s.items = {}
        for e in jl(DEFQ):
            k = (e['place_id'], e['kind'], e['url'])
            if e.get('event') == 'resolved': s.items.pop(k, None)
            else: s.items[k] = e
        s.f = open(DEFQ, 'a')
    def defer(s, pid, kind, url, nb, why):
        e = dict(event='deferred', place_id=pid, kind=kind, url=url, not_before=nb, not_before_iso=datetime.datetime.fromtimestamp(nb, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), why=why, at=now(), **{'pass': 2 if SECOND else 1})
        s.items[(pid, kind, url)] = e; s.f.write(json.dumps(e) + '\n'); s.f.flush()
    def resolve(s, pid, kind, url):
        if (pid, kind, url) in s.items:
            s.items.pop((pid, kind, url)); s.f.write(json.dumps(dict(event='resolved', place_id=pid, kind=kind, url=url, at=now())) + '\n'); s.f.flush()
    def nb(s, pid, kind, url):
        e = s.items.get((pid, kind, url)); return e['not_before'] if e else 0
    def place_nb(s, pid): return max([e['not_before'] for (p, _, _), e in s.items.items() if p == pid] or [0])
    def count(s, pid=None): return sum(1 for (p, _, _) in s.items if pid is None or p == pid)

class Task:
    def __init__(t, q, ctx):
        t.q, t.ctx = q, ctx; t.p = {k: clean(v) for k, v in P[q['place_id']].items()}; t.pid = t.p['place_id']
        t.host = re.sub(r'^www\.', '', q['host'].split(':')[0])
        t.candf = f"{CANDDIR}/{C.place_key(t.pid) if hasattr(C, 'place_key') else t.pid.replace(':', '_')}.json"
        t.cand = None; t.listing = {}; t.w = None; t.pending_ck = []
        t.st = dict(staged=0, with_text=0, miss=0, rejected=0, not_doc=0, deferrals=0); t.files = []
        if os.path.exists(t.candf):
            d = json.load(open(t.candf)); t.cand = [Capture(**c) for c in d['cand']]; t.cand_total = d['cand_total']; t.cdx_counts = d.get('cdx', {})
    def ready_at(t, g): return max(g, ctx.defq.place_nb(t.pid))
    # -- listing
    def ensure_listing(t):
        if t.cand is not None: return
        for kind, flt in (('cdx_pdf', ['mimetype:application/pdf']), ('cdx_html', ['mimetype:text/html', 'original:' + HTMLKW])):
            if kind in t.listing: continue
            if ctx.defq.nb(t.pid, kind, t.host) > time.time(): raise Defer(ctx.defq.nb(t.pid, kind, t.host), 'still deferred')
            try:
                caps = call(fx.wb_captures, t.host, 'domain', collapse='urlkey', filters=flt, max_rows=20000)
                if getattr(caps, 'truncated', False) or getattr(caps, 'deferred', False):   # listing incomplete -> requeue discovery
                    dfr = getattr(caps, 'deferral', None)
                    raise Defer(float(getattr(dfr, 'not_before', 0) or 0) or time.time() + TRANSIENT_WAIT, 'listing truncated/deferred')
                t.listing[kind] = caps
            except Defer as d: t.st['deferrals'] += 1; ctx.defq.defer(t.pid, kind, t.host, d.nb, d.why); raise
            ctx.defq.resolve(t.pid, kind, t.host)
        cand = []
        for c in t.listing['cdx_pdf']:
            u = unquote(c.original_url); name = unquote(os.path.basename(urlparse(c.original_url).path)).replace('_', ' ').replace('-', ' ')
            if PROC.search(u.replace('-', ' ').replace('_', ' ')): continue
            if C.DOCKW.search(name) or C.DOCKW.search(u): cand.append(c)
        cand += [c for c in t.listing['cdx_html'] if C.NUM.search(unquote(c.original_url).replace('-', ' ')) and not C.BAD.search(c.original_url)]
        seen_u = set(); cand = [c for c in cand if not (c.original_url in seen_u or seen_u.add(c.original_url))]
        t.cand, t.cand_total = cand, len(cand); t.cdx_counts = {k: len(v) for k, v in t.listing.items()}
        os.makedirs(CANDDIR, exist_ok=True)
        with open(t.candf + '.tmp', 'w') as f: json.dump(dict(place_id=t.pid, host=t.host, cand_total=len(cand), cdx=t.cdx_counts, cand=[dataclasses.asdict(c) for c in cand]), f)
        os.rename(t.candf + '.tmp', t.candf)
        if not SECOND and len(cand) > MAXDOCS and t.pid not in ctx.capped:
            with open(CAPPED, 'a') as cf: cf.write(json.dumps(dict(place_id=t.pid, name=t.p.get('place_name'), host=t.host, cap=MAXDOCS, docs_taken=MAXDOCS, cand_total=len(cand), at=now())) + '\n')
            ctx.capped.add(t.pid)
        t.listing = {}
    def todo_docs(t):
        sel = t.cand if SECOND else t.cand[:MAXDOCS]
        return [c for c in sel if c.original_url not in ctx.seen_docs and not (SECOND and did(c.original_url) in ctx.staged_ids.get(t.pid, ()))]
    # -- docs
    def flush(t):
        if t.w is not None: t.w.flush(); t.files = [os.path.basename(x) for x in t.w.written]
        for x in t.pending_ck: ctx.dl.write(json.dumps(x) + '\n')
        ctx.dl.flush(); t.pending_ck.clear()
    def mark(t, url, status, durable=True):
        x = dict(url=url, place_id=t.pid, status=status)
        if durable: ctx.dl.write(json.dumps(x) + '\n'); ctx.dl.flush()
        else: t.pending_ck.append(x)
        ctx.seen_docs.add(url)
    def step(t):
        """Process ready items of this place. Returns True if the place is complete. Raises Defer (place requeued)."""
        t.ensure_listing()
        nb_min = None
        for c in t.todo_docs():
            if STOP['flag']: return False
            if not disk_ok(): t.flush(); ctx.close(); log('DISK < 35GB free: stopping'); sys.exit(75)
            nb = ctx.defq.nb(t.pid, 'doc', c.original_url)
            if nb > time.time(): nb_min = min(nb_min or nb, nb); continue      # this doc still deferred: move on
            try:
                doc = call(fx.fetch_best, [c], max_tries=1)      # raises ArchiveDeferred when throttled; None = genuine miss
                if doc is None and getattr(fx, 'last_wb_deferred', 0):   # breaker-open skip / transient: not a miss
                    raise Defer(time.time() + (BREAKER_WAIT if not ratelimit.wayback_available() else TRANSIENT_WAIT), 'wb skipped (breaker/transient)')
            except Defer as d:
                t.st['deferrals'] += 1; ctx.defq.defer(t.pid, 'doc', c.original_url, d.nb, d.why); t.flush(); raise
            except ArchiveError as e:
                ctx.defq.resolve(t.pid, 'doc', c.original_url); t.st['miss'] += 1; t.mark(c.original_url, 'miss'); continue
            ctx.defq.resolve(t.pid, 'doc', c.original_url)
            if doc is None: t.st['miss'] += 1; t.mark(c.original_url, 'miss'); continue
            t.add_doc(c, doc)
        t.flush()
        if nb_min: raise Defer(nb_min, 'docs still deferred')
        return not t.todo_docs() and ctx.defq.count(t.pid) == 0
    def add_doc(t, c, doc):
        if t.w is None: t.w = StagedWriter(STAGE, 'PH', t.pid, batch_prefix='archive', chunk=100)
        is_pdf = doc.body[:4] == b'%PDF'
        name = unquote(os.path.basename(urlparse(c.original_url).path))
        mq = re.search(r'download=\d+:([^&]+)', unquote(urlparse(c.original_url).query))
        if mq: name = mq.group(1)
        if is_pdf:
            txt = pdf_to_text(doc.body); title = re.sub(r'\.pdf$', '', name, flags=re.I).replace('_', ' ').replace('-', ' ').strip(); fmt = 'pdf_text'
        else:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(doc.text()[:2_000_000], 'html.parser')
            h = soup.find(['h1', 'h2']); title = (h.get_text(' ', strip=True) if h else (soup.title.get_text(strip=True) if soup.title else name))[:300]
            txt = C.page_text(soup); fmt = 'html'
            if not (C.DOCKW.search(title) or C.DOCKW.search(txt[:2000])): t.st['not_doc'] += 1; t.mark(c.original_url, 'not_doc'); return
        p = t.p; num = C.parse_num(title) or C.parse_num((txt or '')[:3000])
        rec = dict(place_id=t.pid, country_code='PH', language='en', consolidated=False, place_name=p.get('place_name'), qid=p.get('qid'),
                   admin_level=p.get('admin_level'), platform='ph_lgu_archive', platform_place_id=t.host, source_official=True, source_org=t.host,
                   doc_id=did(c.original_url), source_url=c.original_url, source_platform='ph_lgu_archive', doc_type=C.doctype(num or title),
                   title_native=title or name, number=num, ph_doc_kind=C.kind(num or title), content_format=fmt, retrieved_at=now(),
                   **provenance_fields(doc, 'live_unreachable_archive_fallback', f"live site unreachable from box ({t.q.get('block_reason')})"))
        d = C.parse_date((txt or '')[:4000]) or C.year_from(num or title)
        if d: rec['adopted_date'] = d
        if txt and len(txt.strip()) > 200: rec['text'] = txt; t.st['with_text'] += 1
        else: rec['content_complete'] = False; rec['text_note'] = 'scanned_pdf_no_ocr' if is_pdf else 'short_page'
        err = t.w.add(rec)
        t.st['rejected' if err else 'staged'] += 1
        t.mark(c.original_url, 'staged' if not err else 'rejected:' + err, durable=False)
        if not t.w.buf: t.flush()
    def result(t):
        return dict(place_id=t.pid, name=t.p.get('place_name'), host=t.host, cdx_pdf=t.cdx_counts.get('cdx_pdf'), cdx_html=t.cdx_counts.get('cdx_html'),
                    cand=len(t.cand if SECOND else t.cand[:MAXDOCS]), cand_total=t.cand_total, **{'pass': 2 if SECOND else 1}, **t.st,
                    files=t.files, rss_mb=round(rss_mb()), status='ok')

class Ctx:
    def __init__(s):
        s.defq = DefQ(); s.seen_docs = {x['url'] for x in jl(DOCS)}; s.capped = {x['place_id'] for x in jl(CAPPED)}
        s.done = {x['place_id'] for x in jl(DONE)}; s.dl = open(DOCS, 'a'); s.df = open(DONE, 'a'); s.staged_ids = {}
        for f in glob.glob(STAGE + '/_archive_provenance/PH/*.jsonl'):
            for l in open(f):
                try: x = json.loads(l); s.staged_ids.setdefault(x['place_id'], set()).add(x['doc_id'])
                except Exception: pass
    def close(s):
        for t in getattr(s, 'tasks', []): t.flush()
        s.dl.flush(); s.df.flush()

def run(Q):
    global ctx
    ctx = Ctx()
    if SECOND: todo = [q for q in Q if q['place_id'] in ctx.capped and q['place_id'] not in ctx.done and q['place_id'] in P]
    else: todo = [q for q in Q if q['place_id'] not in ctx.done and q['place_id'] in P]
    tasks = [Task(q, ctx) for q in todo]; ctx.tasks = tasks
    log('pass', 2 if SECOND else 1, 'todo', len(tasks), 'done', len(ctx.done), 'deferred items (persisted)', ctx.defq.count(), 'lane', fx.lane, 'cap', MAXDOCS)
    g_nb = 0.0   # all Wayback items share web.archive.org -> a deferral on one defers every item until then
    while tasks and not STOP['flag']:
        t_now = time.time()
        ready = [t for t in tasks if t.ready_at(g_nb) <= t_now]
        if not ready:
            wake = min(t.ready_at(g_nb) for t in tasks)
            log(f'all {len(tasks)} remaining places deferred ({ctx.defq.count()} items); sleeping {wake - t_now:.0f}s until {datetime.datetime.fromtimestamp(wake, datetime.timezone.utc):%H:%M:%SZ}')
            while time.time() < wake and not STOP['flag']: time.sleep(min(5, max(0.1, wake - time.time())))
            continue
        t = ready[0]
        try:
            complete = t.step()
        except Defer as d:
            g_nb = d.nb
            tasks.remove(t); tasks.append(t)   # rotate: a repeatedly failing place must not head-of-line block the rest
            log(f'DEFER {t.pid} {t.host}: {d.why} -> requeued until {datetime.datetime.fromtimestamp(d.nb, datetime.timezone.utc):%H:%M:%SZ}; moving on')
            continue
        if complete:
            r = t.result(); ctx.df.write(json.dumps(r, ensure_ascii=False) + '\n'); ctx.df.flush(); log(json.dumps(r, ensure_ascii=False)[:300])
            tasks.remove(t)
    ctx.close()
    if STOP['flag']: log('STOPPED (SIGTERM), resumable'); sys.exit(143)
    log('FINISHED', 'pass', 2 if SECOND else 1)

P = {}
if __name__ == '__main__':
    for f in ('places.jsonl', 'cities.jsonl'):
        for l in open(f'{ST}/{f}'):
            p = json.loads(l); P[p['place_id']] = p
    fx = ArchiveFetcher(use_cc=False, lane='ph')
    run(jl(ST + '/wayback_deferred.jsonl'))

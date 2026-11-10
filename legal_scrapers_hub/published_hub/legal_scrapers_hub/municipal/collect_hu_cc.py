"""Hungarian local-government decrees (önkormányzati rendeletek) from Common Crawl captures of the Önkormányzati Rendeletek Tára
(or.njt.hu ELI pages /eli/v01/<issuer id>/r/<year>/<number> and /eli/<issuer id>/r/<year>/<number>, both forms or.njt.hu serves). Common Crawl only: CDX pointers (cluster.idx -> ranged index blocks, via
common_crawl_helper.find_pointers) then one ranged WARC read per record (fetch_records). No request goes to njt.hu itself.
  python collect_hu_cc.py pointers   # HU_BUILD/ptr_eli.parquet (all collections since 2019)
  python collect_hu_cc.py fetch      # HU_BUILD/pages.jsonl.gz: ≤3 pages per decree (latest undated, alaprendelet, newest dated state), decree parts only
  python collect_hu_cc.py alt KEYS.json   # other captures of the decrees listed (heading recovery)
  python collect_hu_cc.py secondary NEED.json   # instead of the full plan: the second pages only for the decrees that need them
  python collect_hu_cc.py pointers_ornjt   # HU_BUILD/ptr_ornjt.parquet: the other or.njt.hu decree URL forms, /onkormanyzati-rendelet/<year>-<no>-SP-<code>
                                          # and /onkormanyzati-rendelet/<numeric id> (all or.njt.hu cluster blocks of each collection, filtered)
  python collect_hu_cc.py ornjt [workers]  # HU_BUILD/pages_ornjt.jsonl.gz: latest capture of each SP-form decree not in the ELI collection (or newer
                                          # than its ELI capture by > 90 days), and of each numeric-id page; a second capture where the first is not a decree page
  (env CC_MIN_DISK_GIB / CC_MIN_MEM_GIB set the resource guard; this build used 30 / 4.5)
/ri/ URLs are the decrees' explanatory memoranda (indokolás): their pointers are recorded, the pages are not fetched.
Stops when free disk < 30 GiB or MemAvailable is low (common_crawl_helper.resource_guard)."""
import os, sys, json, gzip, re, time, collections, concurrent.futures as cf
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import common_crawl_helper as CC
B = os.environ.get("HU_BUILD", "hu_build")
ELI = r"/eli/(?:v01/)?\d+/ri?/\d{4}/\d+"          # /r/ decree pages (fetched); /ri/ pointers are kept for the record, not fetched
DECREE = re.compile(r"/eli/(?:v01/)?\d+/r/\d{4}/\d+")
def pointers():
    import pyarrow as pa, pyarrow.parquet as pq
    for k in range(4):                         # index.commoncrawl.org/collinfo.json drops connections now and then
        try: cols = [c for c in CC.list_collections() if c >= "CC-MAIN-2019"]; break
        except Exception as e: print("collinfo retry", k, type(e).__name__, flush=True); time.sleep(30 * (k + 1))
    else: raise SystemExit("collinfo.json unreachable")
    allp = []
    for c in cols:
        ps = CC.find_pointers("or.njt.hu", collections=[c], url_regex=ELI, status="200", path_prefix="/eli/",
                              max_records=100_000, max_blocks_per_collection=400)
        if not ps and c == "CC-MAIN-2022-05":      # its cluster.idx read failed once; one retry
            time.sleep(20); ps = CC.find_pointers("or.njt.hu", collections=[c], url_regex=ELI, status="200", path_prefix="/eli/", max_records=100_000, max_blocks_per_collection=400)
        print(c, len(ps), sum(bool(DECREE.search(x["url"])) for x in ps), flush=True); allp += ps
    pq.write_table(pa.Table.from_pylist(allp), f"{B}/ptr_eli.parquet", compression="zstd")
ORNJT = re.compile(r"^https?://or\.njt\.hu/onkormanyzati-rendelet/(?:(?P<y>\d{4})-(?P<n>\d+)-SP-(?P<sp>\d+)|(?P<num>\d+))/?$")
def pointers_ornjt(cols=None, dump=None):
    """CDX lines of or.njt.hu /onkormanyzati-rendelet/ pages. dump: an existing listing of all or.njt.hu cluster-block lines ('<collection> <cdx line>'
    per line, gz), e.g. the one the re-verification wrote from the same cluster.idx blocks; otherwise the blocks are read here."""
    import pyarrow as pa, pyarrow.parquet as pq
    out = []
    def take(c, ln):
        surt, ts, js = ln.split(" ", 2); j = json.loads(js)
        if ORNJT.match(j.get("url", "")) and j.get("status") == "200":
            out.append(dict(url=j["url"], timestamp=ts, collection=c, filename=j["filename"], offset=j["offset"], length=j["length"], digest=j.get("digest"), status="200"))
    if dump:
        for l in gzip.open(dump, "rt", encoding="utf-8"):
            c, ln = l.rstrip("\n").split(" ", 1)
            try: take(c, ln)
            except Exception: pass
    else:
        pref = CC.host_to_surt_prefix("or.njt.hu")
        for c in cols or [c for c in CC.list_collections() if c >= "CC-MAIN-2021"]:
            for b in CC.cluster_blocks(c, pref):
                for ln in CC._read_cdx_block(c, b):
                    ln = ln.decode("utf-8", "replace")
                    if ln.startswith(pref):
                        try: take(c, ln)
                        except Exception: pass
    pq.write_table(pa.Table.from_pylist(out), f"{B}/ptr_ornjt.parquet", compression="zstd"); print("ornjt pointers", len(out), flush=True)
def sp_map(out_p=None):
    """SP code (the or.njt.hu / njt.jog.gov.hu publisher code in '<year>-<no>-SP-<code>' and /download/<code>/resources links) -> ELI issuer id,
    learned from the fetched ELI pages: a code is mapped when >= 80 % of the pages that mention it belong to one issuer id"""
    m = collections.defaultdict(collections.Counter)
    for r in read_jsonl_gz(f"{B}/pages.jsonl.gz"):
        k = vkey(r["url"])
        if not k or r.get("error"): continue
        h = (r.get("content_html") or "") + (r.get("footnotes_html") or "")
        for x in re.findall(r"/download/(\d+)/resources", h) + re.findall(r"SP-(?:5Y)?(\d+)", h): m[x][k[0]] += 1
    sp = {c: n.most_common(1)[0][0] for c, n in m.items() if n.most_common(1)[0][1] >= 0.8 * sum(n.values())}
    json.dump(sp, open(out_p or f"{B}/sp2iss.json", "w")); print("sp codes mapped", len(sp), flush=True); return sp
def ornjt_plan(rows, eli_rows, sp2iss, done):
    """latest capture per SP decree key and per numeric page; SP keys already collected through ELI are skipped unless the SP capture is > 90 days newer"""
    import datetime as _d
    eli_ts = {}
    for r in eli_rows:
        k = vkey(r["url"])
        if k and k[3] == "": eli_ts[k[:3]] = max(eli_ts.get(k[:3], ""), r["timestamp"])
    by = collections.defaultdict(list)
    for r in rows:
        m = ORNJT.match(r["url"])
        if m: by[("sp", m["sp"], m["y"], str(int(m["n"]))) if m["sp"] else ("num", m["num"])].append(r)
    first, second, skipped = [], [], 0
    for k, rs in by.items():
        rs.sort(key=lambda r: r["timestamp"], reverse=True)
        if k[0] == "sp" and k[1] in sp2iss:
            e = eli_ts.get((sp2iss[k[1]], k[2], k[3]))
            if e and (_d.datetime.strptime(rs[0]["timestamp"][:8], "%Y%m%d") - _d.datetime.strptime(e[:8], "%Y%m%d")).days <= 90: skipped += 1; continue
        if rs[0]["url"] + rs[0]["timestamp"] in done: 
            if done[rs[0]["url"] + rs[0]["timestamp"]] and len(rs) > 1: second.append(rs[1])      # the first capture was not a decree page
            continue
        first.append(rs[0])
    second = [r for r in second if r["url"] + r["timestamp"] not in done]
    first.sort(key=lambda r: "-SP-" not in r["url"])
    return first + second, dict(keys=len(by), skipped_in_eli=skipped, first=len(first), second=len(second))
def parts(html):
    """The decree parts of an or.njt.hu page. Layout 'orr' (older): h1.orr-c1 issuer + number, h2.orr-c2 subject, h3.orr-valthat[data-hatba]
    in force from, div.orr-content text, div.orr-ftn footnotes. Layout 'njt' (2023-): div.jogszabaly with h1.jogszabalyMainTitle,
    h2.jogszabalySubtitle, .hatalyText ('Hatályos: 2024. 01. 01- …'), div.preambulum, div.szakasz (§) … marked by span.jhId."""
    from bs4 import BeautifulSoup
    s = BeautifulSoup(html, "html.parser")
    g = lambda sel: s.select_one(sel)
    h1, h2, hv, ct, fn = g("h1.orr-c1"), g("h2.orr-c2"), g("h3.orr-valthat"), g("div.orr-content"), g("div.orr-ftn")
    if h1 and ct:
        return dict(layout="orr", h1=h1.get_text(" ", strip=True), h2=h2.get_text(" ", strip=True) if h2 else None,
                    in_force_from=hv.get("data-hatba") if hv else None, in_force_text=hv.get_text(" ", strip=True) if hv else None,
                    content_html=str(ct), footnotes_html=str(fn) if fn and fn.get_text(strip=True) else None)
    j = g("div.jogszabaly") or g(".jogszabaly")
    if j:
        t1 = j.select_one("h1.mainTitle") or j.select_one("h1.jogszabalyMainTitle"); t2 = j.select_one("h2.jogszabalySubtitle")
        hv = j.select_one(".hatalyText")
        if t1:
            return dict(layout="njt", h1=t1.get_text(" ", strip=True), h2=t2.get_text(" ", strip=True) if t2 else None, in_force_from=None,
                        in_force_text=hv.get_text(" ", strip=True) if hv else None, content_html=str(j), footnotes_html=None)
    return None
VKEY = re.compile(r"^https?://or\.njt\.hu/eli/(?:v01/)?(\d+)/r/(\d{4})/(\d+)(?:/(\d{4}-\d{2}-\d{2}|alaprendelet))?/?$")
def vkey(url):
    """(issuer, year, number, state) of a decree page in either URL form (/eli/v01/… or /eli/…); state '' = the undated current page"""
    m = VKEY.match(url); return (m.group(1), m.group(2), str(int(m.group(3))), m.group(4) or "") if m else None
def read_jsonl_gz(path, stats=None):
    """JSON lines from an appended multi-member .gz, tolerant of a member cut off by a stopped run: the complete lines of a truncated member
    are kept and reading resumes at the next gzip member header."""
    import zlib
    data = open(path, "rb").read(); pos = 0; MAGIC = b"\x1f\x8b\x08"; C = 1 << 20
    while pos < len(data):
        d = zlib.decompressobj(31); buf = b""; q = pos; nxt = None
        while q < len(data):
            chunk = data[q:q + C]
            try: buf += d.decompress(chunk)
            except zlib.error: break
            *ls, buf = buf.split(b"\n")
            for l in ls:
                if l.strip(): yield json.loads(l)
            if d.eof: nxt = q + len(chunk) - len(d.unused_data); break
            q += len(chunk)
        if nxt is not None:                                   # a complete member
            if buf.strip(): yield json.loads(buf)
            pos = nxt; continue
        if q >= len(data): break                              # the last member is cut off at the end of the file: its complete lines are kept
        if stats is not None: stats["truncated_gzip_members"] += 1
        f = data.find(MAGIC, pos + 10)
        if f < 0: break
        pos = f
def _done_pages(out_p):
    done = {}
    if os.path.exists(out_p):
        try:
            for r in read_jsonl_gz(out_p):
                if not r.get("error") or r["error"] == "no decree parts in page":       # failed reads (503 …) are retried
                    k = vkey(r["url"])
                    if k: done.setdefault(k, set()).add(r.get("timestamp") or r.get("ptr", {}).get("timestamp") or "")
        except EOFError: pass                                         # a cut-off tail from a stopped run: the rest is kept
    return done
def plan(rows, done, primary_only=False):
    """At most 3 pages per decree: the latest capture of the undated page (state at crawl time), the original text (/alaprendelet) and
    the newest dated state; for each the latest capture over both URL forms. A version already fetched is kept unless the undated page
    has a capture more than 90 days newer."""
    best = {}
    for r in rows:
        k = vkey(r["url"])
        if k and r["status"] == "200" and (k not in best or r["timestamp"] > best[k]["timestamp"]): best[k] = r
    dec = collections.defaultdict(dict)
    for k, r in best.items(): dec[k[:3]][k[3]] = r
    todo, second = [], []
    for d, vs in dec.items():
        dated = sorted(v for v in vs if v not in ("", "alaprendelet"))
        order = [""] + dated[-1:] + ["alaprendelet"]
        primary = next(v for v in order if v in vs)               # fetched first: one page per decree, then the others
        for v in order:
            if v not in vs: continue
            k = d + (v,); r = vs[v]
            if k in done:
                if v != "" or max(done[k]) >= r["timestamp"]: continue
                import datetime as _d
                if (_d.datetime.strptime(r["timestamp"][:8], "%Y%m%d") - _d.datetime.strptime(max(done[k])[:8] or "19700101", "%Y%m%d")).days <= 90: continue
            (todo if v == primary else second).append(r)
    return (todo if primary_only else todo + second), len(dec)
def alt_plan(rows, done, keys):
    """other captures (any URL form, newest first, up to 3) of the decrees in keys: for headings that did not parse on the kept capture"""
    keys = set(keys); out = collections.defaultdict(list)
    for r in sorted(rows, key=lambda r: r["timestamp"], reverse=True):
        k = vkey(r["url"])
        if k and k[:3] in keys and r["status"] == "200" and r["timestamp"] not in done.get(k, set()) and len(out[k[:3]]) < 3: out[k[:3]].append(r)
    return [r for v in out.values() for r in v]
def secondary_plan(rows, done, out_p, keys):
    """the second pages of selected decrees only: the decrees in keys (the build's need list: hollow § left, heading not parsed) and the
    decrees whose index has a dated state newer than the hatály start of the fetched current page (ranking)"""
    keys = {tuple(k) for k in keys}; start = {}
    for r in read_jsonl_gz(out_p):
        k = vkey(r["url"])
        if k and k[3] == "" and not r.get("error"):
            m = re.search(r"(\d{4})\s*[.-]\s*(\d{2})\s*[.-]\s*(\d{2})", r.get("in_force_text") or "")
            if m: start[k[:3]] = "-".join(m.groups())
    full, _ = plan(rows, done)
    newest = collections.defaultdict(str)
    for r in rows:
        k = vkey(r["url"])
        if k and k[3] not in ("", "alaprendelet"): newest[k[:3]] = max(newest[k[:3]], k[3])
    rank_keys = {d for d, s in start.items() if newest.get(d, "") > s}
    sel = keys | rank_keys
    return [r for r in full if vkey(r["url"])[:3] in sel], dict(need=len(keys), ranking=len(rank_keys))
def fetch(workers=4, mode="plan", keys_file=None):
    import pyarrow.parquet as pq
    rows = [r for r in pq.read_table(f"{B}/ptr_eli.parquet").to_pylist() if DECREE.search(r["url"])]
    out_p = f"{B}/pages.jsonl.gz"; done = _done_pages(out_p)
    if mode == "ornjt":
        out_p = f"{B}/pages_ornjt.jsonl.gz"; dn = {}
        if os.path.exists(out_p):
            for r in read_jsonl_gz(out_p):
                if not r.get("error") or r["error"] == "no decree parts in page": dn[r["url"] + (r.get("timestamp") or r["ptr"]["timestamp"])] = bool(r.get("error"))
        sp2iss = json.load(open(keys_file))
        todo, ndec = ornjt_plan(pq.read_table(f"{B}/ptr_ornjt.parquet").to_pylist(), rows, sp2iss, dn)
    elif mode == "alt": todo = alt_plan(rows, done, [tuple(x) for x in json.load(open(keys_file))]); ndec = None
    elif mode == "secondary": todo, ndec = secondary_plan(rows, done, out_p, json.load(open(keys_file)))
    else: todo, ndec = plan(rows, done, primary_only=(mode == "primary"))
    print("decrees", ndec, "versions done", len(done), "todo", len(todo), flush=True)
    st = collections.Counter(); t0 = time.time()
    # Graceful stop: SIGINT / SIGTERM set a flag; no new page is submitted, the few in flight (at most 4 x workers) are finished and
    # written, and the gzip member is closed cleanly. Pages are submitted in a bounded window, so nothing is left queued in the pool.
    import signal, threading
    stop = threading.Event()
    def _stop(sig, frame): print(f"signal {sig}: stopping after the pages in flight", flush=True); stop.set()
    for sg in (signal.SIGINT, signal.SIGTERM): signal.signal(sg, _stop)
    def one(p):
        # checked here without waiting: the helper's own guard in fetch_records waits up to 30 min, which kept a stop request waiting
        if stop.is_set() or not CC.resource_guard(wait=False): return None
        r = CC.fetch_records([p])[0]
        if r.get("error") or r.get("http_status") != 200: return dict(url=p["url"], error=r.get("error") or f"http {r.get('http_status')}", ptr=p)
        body = r["body"]
        try: html = body.decode("utf-8")
        except UnicodeDecodeError: html = body.decode("utf-8", "replace")
        pt = parts(html)
        if not pt: return dict(url=p["url"], error="no decree parts in page", ptr=p)
        return dict(url=p["url"], timestamp=p["timestamp"], collection=p["collection"], warc=p["filename"], offset=p["offset"], length=p["length"],
                    digest=p.get("digest"), fetch_mode=mode, **pt)
    it = iter(todo); pending = set(); k = 0
    with gzip.open(out_p, "at", encoding="utf-8") as out, cf.ThreadPoolExecutor(workers) as ex:
        def fill():
            while not stop.is_set() and len(pending) < 4 * workers:
                p = next(it, None)
                if p is None: return
                pending.add(ex.submit(one, p))
        fill()
        while pending:
            fin, _ = cf.wait(pending, timeout=5, return_when=cf.FIRST_COMPLETED)
            for f in fin:
                pending.discard(f)
                try: rec = f.result()
                except Exception as e: st["exception"] += 1; continue
                if rec is None: st["skipped_stop_or_guard"] += 1; continue
                out.write(json.dumps(rec, ensure_ascii=False) + "\n"); st["error" if rec.get("error") else "ok"] += 1; k += 1
                if k % 50 == 0: out.flush()
                if k % 500 == 0: print(k, dict(st), f"{time.time() - t0:.0f}s", flush=True)
            if not stop.is_set() and not CC.resource_guard(wait=False):
                print("resource guard: below the disk / memory floor, stopping", flush=True); stop.set()
            fill()
        out.flush()
    print("done", dict(st), flush=True)
if __name__ == "__main__":
    os.makedirs(B, exist_ok=True)
    if sys.argv[1] == "fetch": fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 4, mode="primary" if sys.argv[3:4] == ["primary"] else "plan")
    elif sys.argv[1] == "alt": fetch(int(sys.argv[3]) if len(sys.argv) > 3 else 4, mode="alt", keys_file=sys.argv[2])
    elif sys.argv[1] == "pointers_ornjt": pointers_ornjt(dump=sys.argv[2] if len(sys.argv) > 2 else None)
    elif sys.argv[1] == "sp_map": sp_map()
    elif sys.argv[1] == "ornjt": fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 4, mode="ornjt", keys_file=f"{B}/sp2iss.json")
    elif sys.argv[1] == "secondary": fetch(int(sys.argv[3]) if len(sys.argv) > 3 else 4, mode="secondary", keys_file=sys.argv[2])
    else: pointers()

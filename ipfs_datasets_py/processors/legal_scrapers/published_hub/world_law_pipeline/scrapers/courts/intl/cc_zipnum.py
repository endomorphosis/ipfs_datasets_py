"""Common Crawl lookup WITHOUT index.commoncrawl.org (which TLS-fails / 504s from the box): uses the public zipnum
cluster.idx (cached in /workspace/cc_idx) + HTTP range requests to data.commoncrawl.org cdx-*.gz shards, and
WARC record range fetches. Usage: cc_zipnum.py <crawl> <domain> [path_prefix]  -> prints CDX JSON lines.
fetch_warc(rec) returns (http_status, headers, body bytes)."""
import bisect, gzip, io, json, os, sys, time, zlib, requests
IDX = "/workspace/cc_idx"; D = "https://data.commoncrawl.org/"; UA = "WorldCourtsResearchBot/1.0 (public court data research)"
_cache = {}
def surt(domain, path=""):
    parts = domain.lower().split(".")
    if parts[0] == "www": parts = parts[1:]
    return ",".join(reversed(parts)) + ")/" + path.lstrip("/")
def _load(crawl):
    if crawl not in _cache:
        p = f"{IDX}/{crawl}.idx"
        if not os.path.exists(p):
            open(p, "wb").write(requests.get(f"{D}cc-index/collections/{crawl}/indexes/cluster.idx", timeout=600).content)
        keys, meta = [], []
        for l in open(p, encoding="utf-8", errors="replace"):
            a = l.rstrip("\n").split("\t"); keys.append(a[0].split(" ")[0]); meta.append((a[1], int(a[2]), int(a[3])))
        _cache[crawl] = (keys, meta)
    return _cache[crawl]
def lookup(crawl, domain, path="", limit=100000):
    keys, meta = _load(crawl); pre = surt(domain, path)
    i = max(0, bisect.bisect_left(keys, pre) - 1); out = []
    while i < len(keys) and (keys[i] <= pre or keys[i].startswith(pre)) :
        f, off, ln = meta[i]
        r = requests.get(f"{D}cc-index/collections/{crawl}/indexes/{f}", headers={"Range": f"bytes={off}-{off+ln-1}", "User-Agent": UA}, timeout=120)
        time.sleep(1)
        for l in zlib.decompress(r.content, 16 + zlib.MAX_WBITS).decode("utf-8", "replace").splitlines():
            k, ts, js = l.split(" ", 2)
            if k.startswith(pre): out.append(json.loads(js) | {"timestamp": ts, "urlkey": k})
            elif k > pre and not k.startswith(pre) and out: return out[:limit]
        i += 1
        if len(out) >= limit: break
    return out[:limit]
def fetch_warc(rec):
    off, ln = int(rec["offset"]), int(rec["length"])
    r = requests.get(D + rec["filename"], headers={"Range": f"bytes={off}-{off+ln-1}", "User-Agent": UA}, timeout=180); time.sleep(1)
    raw = gzip.decompress(r.content)
    _, http = raw.split(b"\r\n\r\n", 1); hdr, body = http.split(b"\r\n\r\n", 1)
    st = int(hdr.split(b" ", 2)[1]); h = {}
    for line in hdr.split(b"\r\n")[1:]:
        if b":" in line: k, v = line.split(b":", 1); h[k.decode().strip().lower()] = v.decode("latin-1").strip()
    if "chunked" in h.get("transfer-encoding", "").lower():
        b2, rest = b"", body
        while rest:
            n, rest = rest.split(b"\r\n", 1); n = int(n.split(b";")[0], 16)
            if n == 0: break
            b2 += rest[:n]; rest = rest[n + 2:]
        body = b2
    return st, h, body
if __name__ == "__main__":
    for r in lookup(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""):
        print(json.dumps(r))

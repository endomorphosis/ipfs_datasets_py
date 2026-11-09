"""Fetch single Common Crawl WARC records by (filename, offset, length) from data.commoncrawl.org with polite pacing + backoff.
Usage as module: fetch(rec, out_path) -> (http_status, html_bytes). rec = CDX JSON record."""
import gzip, time, urllib.request, os
UA = "WorldCourtsResearchBot/1.0 (+public court directory research; polite crawl)"
def fetch(rec, out_path=None, tries=4, pause=6):
    if out_path and os.path.exists(out_path):
        raw = open(out_path, "rb").read()
    else:
        o, n = int(rec["offset"]), int(rec["length"]); d = pause; raw = None
        for _ in range(tries):
            try:
                req = urllib.request.Request("https://data.commoncrawl.org/" + rec["filename"], headers={"User-Agent": UA, "Range": f"bytes={o}-{o+n-1}"})
                raw = gzip.decompress(urllib.request.urlopen(req, timeout=120).read()); time.sleep(pause); break
            except Exception as e:
                time.sleep(d); d *= 2; last = e
        if raw is None: return 0, str(last).encode()
        if out_path: open(out_path, "wb").write(raw)
    # WARC record: headers \r\n\r\n HTTP headers \r\n\r\n body
    parts = raw.split(b"\r\n\r\n", 2)
    if len(parts) < 3: return 0, b""
    st = parts[1].split(b"\r\n", 1)[0].split(b" ")
    return int(st[1]) if len(st) > 1 and st[1].isdigit() else 0, parts[2]

#!~/.ipfs_datasets/world_law/.venv_afme/bin/python
"""afme generic live crawler, configured per country by out/afme_config/<CC>.json.

Config:
{"cc": "KE", "source_platform": "ke_kenyalaw", "language": "en", "doc_type": "ordinance",
 "consolidated": false, "content_format": "html", "source_official": true, "source_org": "...",
 "host_min_interval": 5.0,
 "places": [{"place_id": "wd:Q3870", "place_name": "Nairobi", "admin_level": "county",
             "docs": [{"url": "https://...", "doc_id": "...", "title_native": "...", "number": "..."}],
             "index_url": "https://...", "link_regex": "href=\"([^\"]+\\.pdf)\""}]}
Docs can be listed, or discovered from index_url with link_regex (doc_id = URL path unless given).
Output: out/afme/raw/<CC>/<place_key>.<cc>_live_<UTC>.jsonl ; afme_stage.py validates and stages it.
robots.txt is NOT enforced (2026-11-01); rows carry source_policy=robots_not_checked.
Never bypasses Cloudflare/WAF/captcha: a challenge is logged and the URL is skipped. No proxies.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import argparse, hashlib, re, sys, time
from urllib.parse import urljoin, urlparse
import afme_common as C
import requests
from schema import place_key, validate_record

MAX_BODY = 25 * 1024 * 1024


class Live:
    def __init__(self, min_interval=5.0, timeout=(10, 40)):
        self.s = requests.Session()
        self.s.trust_env = False          # no proxies from env
        self.s.proxies = {}
        self.s.headers.update({"User-Agent": C.UA, "Accept-Language": "en,fr;q=0.8,ar;q=0.6"})
        self.min_interval = min_interval
        self.timeout = timeout
        self.last = {}                    # host -> last request end
        self.cool = {}                    # host -> not_before
        self.skip_hosts = set()           # hosts that served a challenge (skip for this run)

    def get(self, url):
        host = urlparse(url).hostname or ""
        if any(f in host for f in C.FORBIDDEN_FRAGMENTS):
            return None, "forbidden_host"
        if host in self.skip_hosts:
            return None, "host_challenged_earlier"
        if self.cool.get(host, 0) > time.time():
            return None, "host_cooling_down"
        wait = self.last.get(host, 0) + self.min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            r = self.s.get(url, timeout=self.timeout, stream=True, allow_redirects=True)
            body = b""
            for chunk in r.iter_content(65536):
                body += chunk
                if len(body) > MAX_BODY:
                    r.close(); return None, "too_large"
        except requests.RequestException as e:
            self.last[host] = time.time()
            return None, f"neterr:{type(e).__name__}"
        self.last[host] = time.time()
        ch = C.is_challenge(r.status_code, r.headers, body)
        if ch:
            self.skip_hosts.add(host)
            return None, f"skip_challenge:{ch}"
        if r.status_code == 429 or r.status_code >= 500:
            ra = r.headers.get("Retry-After", "")
            self.cool[host] = time.time() + (int(ra) if ra.isdigit() else 300)
            return None, f"deferred:{r.status_code}"
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        return r, body


def doc_record(cfg, place, d, resp, body):
    ctype = resp.headers.get("Content-Type", "").lower()
    is_pdf = "pdf" in ctype or body[:5] == b"%PDF-"
    rec = {
        "place_id": place["place_id"], "country_code": cfg["cc"],
        "doc_id": d.get("doc_id") or urlparse(resp.url).path.strip("/") or hashlib.sha1(resp.url.encode()).hexdigest()[:16],
        "source_platform": cfg["source_platform"], "source_url": d["url"],
        "doc_type": d.get("doc_type", cfg.get("doc_type", "ordinance")),
        "language": d.get("language", cfg.get("language", "en")),
        "consolidated": bool(d.get("consolidated", cfg.get("consolidated", False))),
        "content_format": "pdf_text" if is_pdf else cfg.get("content_format", "html"),
        "retrieved_at": C.utc_iso(), "source_policy": C.LIVE_POLICY,
        "source_official": cfg.get("source_official", True),
    }
    for k in ("title_native", "number", "adopted_date", "published_date", "effective_date", "in_force"):
        if d.get(k) is not None:
            rec[k] = d[k]
    for k in ("place_name", "admin_level", "qid", "iso_3166_2"):
        if place.get(k):
            rec[k] = place[k]
    if cfg.get("source_org"):
        rec["source_org"] = cfg["source_org"]
    rec["platform"] = cfg["source_platform"]
    if is_pdf:
        txt = pdf_text(body)
        rec["text"] = txt
        if not txt.strip():
            rec["content_complete"] = False   # scanned PDF: metadata-only row, OCR later
    else:
        enc = resp.encoding or "utf-8"
        html = body.decode(enc, errors="replace")
        rec["html"] = html
        if "title_native" not in rec:
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            rec["title_native"] = re.sub(r"\s+", " ", m.group(1)).strip() if m else rec["doc_id"]
    if "title_native" not in rec and "number" not in rec:
        rec["title_native"] = rec["doc_id"]
    return rec


def pdf_text(body):
    import subprocess
    try:
        p = subprocess.run(["pdftotext", "-layout", "-", "-"], input=body, capture_output=True, timeout=120)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""


def discover(live, place):
    if not place.get("index_url"):
        return []
    r, body = live.get(place["index_url"])
    if r is None:
        C.log(f"index {place['index_url']}: {body}")
        return []
    html = body.decode(r.encoding or "utf-8", errors="replace")
    rx = re.compile(place.get("link_regex", r'href="([^"]+\.pdf)"'), re.I)
    seen, out = set(), []
    for m in rx.finditer(html):
        u = urljoin(r.url, m.group(1))
        if u not in seen:
            seen.add(u); out.append({"url": u})
    return out


def run(cc, max_urls=None, places_filter=None, dry=False):
    C.cap_address_space()
    cfg = C.load_config(cc); cc = cfg["cc"] = cfg["cc"].upper()
    live = Live(cfg.get("host_min_interval", 5.0))
    done = C.load_done("live", cc)
    n_urls = 0
    for place in cfg["places"]:
        if places_filter and place["place_id"] not in places_filter:
            continue
        pk = place_key(place["place_id"])
        C.disk_check(); C.mem_check()
        docs = list(place.get("docs", [])) + discover(live, place)
        rows, deferred = [], 0
        for d in docs:
            if d["url"] in done:
                continue
            if max_urls is not None and n_urls >= max_urls:
                break
            n_urls += 1
            r, info = live.get(d["url"])
            if r is None:
                C.log(f"{cc} {pk} {d['url']}: {info}")
                if info.startswith(("deferred", "neterr", "host_cooling")):
                    deferred += 1            # not done: retry next run
                elif not dry:
                    C.mark_done("live", cc, d["url"], "skip_challenge" if "challenge" in info else "miss", info)
                continue
            rec = doc_record(cfg, place, d, r, info)
            errs = validate_record(rec)
            if errs:
                C.log(f"{cc} {pk} invalid {d['url']}: {errs}")
                continue
            rows.append(rec)
            C.mem_check()
        if rows and not dry:
            p = C.write_raw(cc, pk, f"{cc.lower()}_live_", rows)
            for rr in rows:
                C.mark_done("live", cc, rr["source_url"], "ok", p.name)
            C.log(f"{cc} {pk}: {len(rows)} rows -> {p}")
        if max_urls is not None and n_urls >= max_urls:
            break
    C.log(f"{cc} done: {n_urls} URLs tried, RSS {C.rss_mb():.0f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cc")
    ap.add_argument("--max-urls", type=int)
    ap.add_argument("--place", action="append")
    ap.add_argument("--dry-run", action="store_true", help="fetch but write nothing")
    a = ap.parse_args()
    run(a.cc, a.max_urls, a.place, a.dry_run)

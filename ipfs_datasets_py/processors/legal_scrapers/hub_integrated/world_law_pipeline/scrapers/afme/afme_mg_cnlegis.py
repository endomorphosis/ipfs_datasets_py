#!~/.ipfs_datasets/world_law/.venv_afme/bin/python
"""afme wave 13: Madagascar CNLégis (Centre National LEGIS, Primature; references the JORM) adapter.
The site is a POST search (session) + JSON listing (page_data_result_direct_mots_texte, var_pg_limit="offset,limit")
whose rows carry the full French/Malagasy HTML text. Keeps rows whose objet names a commune / collectivité.
Config: afme_config/MG.json ("search_terms", "objet_regex", "page_size"). Output/done/guards as afme_live.py.

Transient net errors (RemoteDisconnected/reset/timeout) and 5xx/429 use bounded exponential backoff.
A challenge is never retried or bypassed. One host failure after retries defers that search term and
continues other terms rather than aborting the whole country.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import argparse, html as H, os, re, sys, time
import requests
import afme_common as C
from afme_live import Live
from schema import place_key, validate_record


# DNS via Cloudflare DoH (box resolver returns fake 198.18.x). TLS SNI/Host stay real. No proxies.
import json as _json, socket as _socket, urllib.request as _urlreq
_orig_gai = _socket.getaddrinfo
_doh_cache = {}
def _doh_a(host):
    if host not in _doh_cache:
        ip = None
        try:
            req = _urlreq.Request(
                f"https://cloudflare-dns.com/dns-query?name={host}&type=A",
                headers={"accept": "application/dns-json"},
            )
            ans = _json.load(_urlreq.build_opener(_urlreq.ProxyHandler({})).open(req, timeout=10)).get("Answer", [])
            ips = [a["data"] for a in ans if a.get("type") == 1]
            ip = ips[0] if ips else None
        except Exception:
            ip = None
        _doh_cache[host] = ip
    return _doh_cache[host]
def _gai(host, port, family=0, type=0, proto=0, flags=0):
    if isinstance(host, str) and host not in ("cloudflare-dns.com", "localhost") and not host.replace(".", "").isdigit():
        ip = _doh_a(host)
        if ip:
            return _orig_gai(ip, port, _socket.AF_INET, type, proto, flags)
        raise _socket.gaierror(_socket.EAI_NONAME, f"DoH: no A record for {host}")
    return _orig_gai(host, port, family, type, proto, flags)
_socket.getaddrinfo = _gai

BASE = "https://www.cnlegis.gov.mg/"
HOST = "www.cnlegis.gov.mg"
# Bounded exponential backoff for transient live failures (env-overridable for tests).
POST_MAX_TRIES = max(1, int(os.environ.get("AFME_MG_POST_MAX_TRIES", "5")))
POST_BACKOFF_BASE = float(os.environ.get("AFME_MG_POST_BACKOFF_BASE", "5"))
POST_BACKOFF_CAP = float(os.environ.get("AFME_MG_POST_BACKOFF_CAP", "120"))


class TransientHostError(Exception):
    """Live host unreachable after bounded retries; caller may continue other work / archive."""


def iso(d):
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})$", d or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _retryable_net(exc):
    """True for disconnect/reset/timeout-class request failures (not SSL MITM, not challenge)."""
    if isinstance(exc, (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError)):
        return True
    # Some stacks wrap ProtocolError/RemoteDisconnected inside RequestException
    name = type(exc).__name__
    if name in ("ProtocolError", "RemoteDisconnected", "BrokenPipeError"):
        return True
    msg = str(exc).lower()
    return any(s in msg for s in (
        "remotedisconnected", "connection aborted", "connection reset",
        "read timed out", "connect timeout", "broken pipe",
    ))


def post(live, url, data, max_tries=None, expect_json=False):
    """POST with polite host delay + bounded exponential backoff on transient errors / 5xx / 429.
    Never retries or bypasses Cloudflare/WAF/captcha. No proxies (Live.trust_env=False).
    expect_json: empty body or non-JSON is treated as a transient retry (cnlegis listing).
    """
    max_tries = POST_MAX_TRIES if max_tries is None else max(1, int(max_tries))
    delay = POST_BACKOFF_BASE
    last_err = None
    for attempt in range(1, max_tries + 1):
        wait = live.last.get(HOST, 0) + live.min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            r = live.s.post(url, data=data, timeout=(15, 120))
        except requests.RequestException as e:
            live.last[HOST] = time.time()
            last_err = e
            if not _retryable_net(e) or attempt >= max_tries:
                raise TransientHostError(
                    f"neterr after {attempt}/{max_tries}: {type(e).__name__}: {e}"
                ) from e
            sleep_for = min(delay, POST_BACKOFF_CAP)
            C.log(f"MG post retry {attempt}/{max_tries} {type(e).__name__}; sleep {sleep_for:.0f}s")
            time.sleep(sleep_for)
            delay = min(delay * 2, POST_BACKOFF_CAP)
            continue
        live.last[HOST] = time.time()
        ch = C.is_challenge(r.status_code, r.headers, r.content)
        if ch:
            raise SystemExit(f"skip_challenge {ch}: not bypassing")
        if r.status_code == 429 or r.status_code >= 500:
            last_err = f"http {r.status_code}"
            if attempt >= max_tries:
                raise TransientHostError(f"deferred http {r.status_code} after {max_tries}")
            ra = r.headers.get("Retry-After", "")
            sleep_for = int(ra) if ra.isdigit() else delay
            sleep_for = min(max(float(sleep_for), delay), max(POST_BACKOFF_CAP, 300))
            C.log(f"MG post retry {attempt}/{max_tries} http {r.status_code}; sleep {sleep_for:.0f}s")
            time.sleep(sleep_for)
            delay = min(delay * 2, POST_BACKOFF_CAP)
            continue
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            raise TransientHostError(f"http {r.status_code}: {e}") from e
        if expect_json:
            raw = r.content or b""
            if not raw.strip():
                last_err = "empty_body"
                if attempt >= max_tries:
                    raise TransientHostError(f"empty_body after {max_tries}")
                sleep_for = min(delay, POST_BACKOFF_CAP)
                C.log(f"MG post retry {attempt}/{max_tries} empty_body; sleep {sleep_for:.0f}s")
                time.sleep(sleep_for)
                delay = min(delay * 2, POST_BACKOFF_CAP)
                continue
            try:
                r.json()  # validate; caller may call .json() again (cached by requests)
            except ValueError as e:
                last_err = f"bad_json:{e}"
                if attempt >= max_tries:
                    raise TransientHostError(f"bad_json after {max_tries}: {e}") from e
                sleep_for = min(delay, POST_BACKOFF_CAP)
                C.log(f"MG post retry {attempt}/{max_tries} bad_json; sleep {sleep_for:.0f}s")
                time.sleep(sleep_for)
                delay = min(delay * 2, POST_BACKOFF_CAP)
                continue
        return r
    raise TransientHostError(f"exhausted retries: {last_err}")


def run(max_items=None, dry=False):
    C.cap_address_space()
    cfg = C.load_config("MG"); cc = "MG"
    place = cfg["places"][0]; pk = place_key(place["place_id"])
    live = Live(cfg.get("host_min_interval", 5.0))
    done = C.load_done("live", cc)
    rx = re.compile(cfg["objet_regex"], re.I)
    ps = int(cfg.get("page_size", 20)); n = 0
    terms_ok, terms_deferred = 0, 0
    for term in cfg["search_terms"]:
        C.disk_check(); C.mem_check()
        try:
            post(live, BASE + "page_find_direct_mots_texte/", {"txt_recherche": term})
        except TransientHostError as e:
            C.log(f"MG term '{term}' search deferred: {e}")
            terms_deferred += 1
            continue  # try the next search term / reachable page
        off = 0
        term_got_page = False
        while True:
            C.disk_check(); C.mem_check()
            try:
                js = post(live, BASE + "page_data_result_direct_mots_texte",
                          {"var_pg_limit": f"{off},{ps}"}, expect_json=True).json()
            except TransientHostError as e:
                C.log(f"MG term '{term}' off={off} deferred: {e}")
                terms_deferred += 1
                break  # leave this term; continue other terms
            items = js.get("aaData") or []
            if not items:
                break
            term_got_page = True
            rows = []
            for it in items:
                key = f"{BASE}#texte-{it['id']}"
                if key in done:
                    continue
                obj = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", it.get("objet_txt") or ""))).strip()
                if not rx.search(obj):
                    continue          # not a local-government act: not counted, not marked
                if max_items is not None and n >= max_items:
                    break
                n += 1; done.add(key)
                body = it.get("html_fichier_fr") or it.get("html_fichier_mg") or ""
                if not body.strip():
                    if not dry:
                        C.mark_done("live", cc, key, "miss", "no_html")
                    continue
                rec = {"place_id": place["place_id"], "country_code": cc,
                       "doc_id": it.get("int_name") or f"cnlegis-{it['id']}",
                       "source_platform": cfg["source_platform"], "source_url": key,
                       "doc_type": cfg["doc_type"],
                       "language": "fr" if it.get("html_fichier_fr") else "mg",
                       "consolidated": False, "content_format": "html", "html": body,
                       "retrieved_at": C.utc_iso(), "source_policy": C.LIVE_POLICY,
                       "source_official": True, "source_org": cfg["source_org"],
                       "platform": cfg["source_platform"], "platform_place_id": str(it["id"]),
                       "title_native": f"{it.get('type_txt','')} n° {it.get('num_txt','')} {obj}".strip()[:1000],
                       "number": it.get("num_txt") or None,
                       "place_name": place["place_name"], "admin_level": place["admin_level"],
                       "qid": place.get("qid")}
                for k, v in (("adopted_date", iso(it.get("date_txt"))),
                             ("published_date", iso(it.get("date_jo")))):
                    if v:
                        rec[k] = v
                rec = {k: v for k, v in rec.items() if v is not None}
                errs = validate_record(rec)
                if errs:
                    C.log(f"MG invalid {key}: {errs}"); continue
                rows.append(rec)
            if rows and not dry:
                p = C.write_raw(cc, pk, "mg_live_", rows)
                for rr in rows:
                    C.mark_done("live", cc, rr["source_url"], "ok", p.name)
                C.log(f"MG {term} off={off}: {len(rows)} rows -> {p.name}")
            if max_items is not None and n >= max_items:
                break
            off += ps
        if term_got_page:
            terms_ok += 1
        if max_items is not None and n >= max_items:
            break
    C.log(f"MG done: {n} matching items, terms_ok={terms_ok} terms_deferred={terms_deferred}, "
          f"RSS {C.rss_mb():.0f} MB")
    # Exit 2 when the live host stayed unreachable so the resume wrapper can try archive fallback.
    if terms_ok == 0 and terms_deferred > 0 and n == 0:
        raise SystemExit(2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-items", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(a.max_items, a.dry_run)

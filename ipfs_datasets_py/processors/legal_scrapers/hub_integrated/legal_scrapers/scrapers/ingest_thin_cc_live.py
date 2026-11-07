#!/usr/bin/env python3
"""Live-ingest official PDFs discovered via S3 CC harvest (*_cc_urls.jsonl).

Prefer live fetch (wayback=False first, then wayback fallback). No WARC Range.
OMP_THREAD_LIMIT=1. Logs also mirrored by shell to logs/cc_parallel_<cc>.log
Usage: ingest_thin_cc_live.py <cc>
Env: MAX_NEW (40), MAX_SECONDS (3600), TARGET_LAWS (hub+40-ish), ALLOW_OCR (0)
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import importlib, json, logging, os, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(_SCRAPERS) + "/scrapers")
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import fetch_official, save_instrument, setup_log, slug_id

LOGS = Path(str(_SCRAPERS) + "/logs")
MIN_TEXT = 120

# Fallback meta when collect_<cc> import fails
FALLBACK = {
    "iq": ("Iraq", "ar", "moj_iraq", "Ministry of Justice of Iraq (moj.gov.iq).", ["moj.gov.iq"]),
    "la": ("Laos", "lo", "lao_official_gazette", "Lao Official Gazette.", ["laoofficialgazette.gov.la"]),
    "lk": ("Sri Lanka", "en", "documents_gov_lk", "documents.gov.lk / parliament.lk.", ["documents.gov.lk", "parliament.lk"]),
    "ge": ("Georgia", "ka", "georgia_official_pdf", "matsne.gov.ge / parliament.ge.", ["matsne.gov.ge", "parliament.ge"]),
    "gh": ("Ghana", "en", "ghana_official", "Parliament of Ghana.", ["parliament.gh", "judicial.gov.gh"]),
    "ba": ("Bosnia and Herzegovina", "bs", "sluzbeni_list_bih", "Sluzbeni list BiH.", ["sluzbenilist.ba"]),
    "sv": ("El Salvador", "es", "asamblea_diario_oficial_sv", "Diario Oficial SV.", ["diariooficial.gob.sv", "asamblea.gob.sv", "imprentanacional.gob.sv"]),
    "et": ("Ethiopia", "am", "negarit_gazette", "Federal Negarit Gazette.", ["justice.gov.et", "hopr.gov.et"]),
    "na": ("Namibia", "en", "namibia_parliament", "Parliament of Namibia.", ["parliament.na", "laws.parliament.na", "bon.com.na"]),
    "cu": ("Cuba", "es", "gaceta_oficial_cu", "Gaceta Oficial de Cuba.", ["gacetaoficial.gob.cu"]),
    "gt": ("Guatemala", "es", "congreso_gt", "Congreso de Guatemala.", ["congreso.gob.gt"]),
    "kh": ("Cambodia", "km", "moj_kh", "Ministry of Justice Cambodia.", ["moj.gov.kh"]),
    "ni": ("Nicaragua", "es", "asamblea_ni", "Asamblea Nacional Nicaragua.", ["asamblea.gob.ni"]),
    "fj": ("Fiji", "en", "laws_gov_fj", "laws.gov.fj.", ["laws.gov.fj"]),
    "me": ("Montenegro", "sr", "sluzbeni_list_cg", "Sluzbeni list CG.", ["sluzbenilist.me"]),
    "bn": ("Brunei", "en", "agc_brunei_laws", "AGC Laws of Brunei.", ["agc.gov.bn"]),
    "pa": ("Panama", "es", "gaceta_oficial_pa", "Gaceta Oficial de Panama.", ["gacetaoficial.gob.pa"]),
    "do": ("Dominican Republic", "es", "consultoria_congreso_do", "Consultoria / Biblioteca Congreso DO.", ["consultoria.gov.do", "bibliotecadelcongreso.gob.do"]),
}

JUNK = re.compile(
    r"(?i)(logo|banner|brochure|formulario|hansard|order.?paper|budget.?statement|"
    r"discurso|comunicado|robots\.txt|\.css|\.js)"
)


def load_mod(cc: str):
    try:
        return importlib.import_module(f"collect_{cc}")
    except Exception:
        return None


def meta(cc: str, mod):
    fb = FALLBACK[cc]
    country = getattr(mod, "COUNTRY", fb[0]) if mod else fb[0]
    lang = getattr(mod, "LANG", fb[1]) if mod else fb[1]
    st = getattr(mod, "SOURCE_TYPE", fb[2]) if mod else fb[2]
    lic = getattr(mod, "LICENSE", fb[3] + " Authentic official text prevails. Not legal advice.") if mod else (fb[3] + " Authentic official text prevails. Not legal advice.")
    art = getattr(mod, "ART", None) if mod else None
    if art is None and mod:
        art = getattr(mod, "ART_GH", None) or getattr(mod, "ART_RE", None)
    hosts = fb[4]
    ua = getattr(mod, "UA", f"legal-corpora-collector/1.0 (research; cc={cc})") if mod else f"legal-corpora-collector/1.0 (research; cc={cc})"
    return country, lang, st, lic, art, hosts, ua


def host_ok(url: str, hosts: list[str]) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return any(host == h or host.endswith("." + h) or h in host for h in hosts)


def url_stem(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    if not name:
        parts = [p for p in path.strip("/").split("/") if p]
        name = parts[-1] if parts else "document"
    return re.sub(r"[^\w.\-]+", "-", name).strip("-")[:160] or "document"


def existing_stems(cc: str) -> set[str]:
    stems: set[str] = set()
    d = Path(f"{_CORPORA}/{cc}/instruments")
    if not d.exists():
        return stems
    for p in d.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for k in ("source_url", "url"):
            su = rec.get(k) or ""
            if su:
                stems.add(Path(unquote(urlparse(su).path)).name.lower())
                stems.add(url_stem(su).lower())
        stems.add((rec.get("id") or p.stem).lower())
    return stems


def load_records(cc: str) -> list[dict]:
    path = LOGS / f"{cc}_cc_urls.jsonl"
    seen, out = set(), []
    if not path.exists():
        return out
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        u = r.get("url") or ""
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(r)
    # Prefer parliament / uploads / actos over bill spam when mixed
    def rank(r: dict) -> tuple:
        u = (r.get("url") or "").lower()
        score = 0
        if "parliament" in u: score -= 3
        if "/act/" in u or "/acts/" in u: score -= 2
        if "/uploads/" in u or "/actos/" in u or "proclamation" in u: score -= 2
        if "/bill/" in u: score += 2
        return (score, u)
    out.sort(key=rank)
    return out


def title_from(text: str, ident: str) -> str:
    for line in (text or "").splitlines():
        s = line.strip()
        if 12 <= len(s) <= 240 and not s.startswith("%"):
            return s[:240]
    return ident.replace("-", " ")[:240]


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: ingest_thin_cc_live.py <cc>", file=sys.stderr)
        sys.exit(2)
    cc = sys.argv[1].lower()
    if cc not in FALLBACK:
        print(f"unsupported cc {cc}", file=sys.stderr)
        sys.exit(2)
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    setup_log(cc)
    log = logging.getLogger(f"cc_live_{cc}")
    mod = load_mod(cc)
    country, lang, source_type, license_text, art, hosts, ua = meta(cc, mod)
    t0 = utcnow()
    max_new = int(os.environ.get("MAX_NEW", "40") or 40)
    target = int(os.environ.get("TARGET_LAWS", "0") or 0)
    max_seconds = int(os.environ.get("MAX_SECONDS", "3600") or 3600)
    allow_ocr = os.environ.get("ALLOW_OCR", "0") in ("1", "true", "True")
    done = existing_ids(cc)
    stems = existing_stems(cc)
    records = load_records(cc)
    from common import ROOT
    corpus = lambda: sum(1 for _ in (ROOT / cc / "instruments").glob("*.json"))
    laws0 = corpus()
    log.info("start urls=%s ids=%s stems=%s target=%s allow_ocr=%s", len(records), len(done), len(stems), target, allow_ocr)
    ok = skip = fail = 0
    t_start = time.time()

    for rec in records:
        url = rec.get("url") or ""
        if ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        if target and corpus() >= target and ok >= 1:
            log.info("target reached %s", corpus())
            break
        if not host_ok(url, hosts):
            skip += 1
            continue
        if JUNK.search(url):
            skip += 1
            continue
        bare = url_stem(url).lower()
        stem_name = Path(unquote(urlparse(url).path)).name.lower() or (bare + ".pdf")
        if stem_name in stems or bare in stems or bare + ".pdf" in stems:
            skip += 1
            continue
        ident = bare[:160]
        rid = slug_id(cc, ident)
        if rid in done:
            skip += 1
            continue

        # LIVE first
        got = fetch_official(url, ua=ua, verify=False, wayback=False, min_text=MIN_TEXT)
        text = got.get("text") or ""
        method = got.get("method") or ""
        # selective wayback fallback if live fails
        if len(text) < MIN_TEXT:
            got2 = fetch_official(url, ua=ua, verify=False, wayback=True, min_text=MIN_TEXT)
            if len(got2.get("text") or "") > len(text):
                got, text, method = got2, got2.get("text") or "", got2.get("method") or method

        # Common Crawl WARC range fallback when live+wayback miss (use harvest pointers)
        if len(text) < MIN_TEXT and rec.get("filename") and rec.get("offset"):
            try:
                import archive_fallbacks as af
                from pdf_extract_lib import extract_pdf_text
                warc = af.fetch_common_crawl_warc(rec, max_bytes=8_000_000)
                body = warc.get("content") if warc.get("status") == "success" else b""
                if body and body[:4] == b"%PDF":
                    t2, how, _ = extract_pdf_text(body, enable_ocr=allow_ocr,
                        ocr_lang=("lao+eng" if cc == "la" else "eng"),
                        ocr_max_pages=int(os.environ.get("OCR_MAX_PAGES", "25") or 25))
                    if len(t2 or "") > len(text):
                        text, method = t2, "common_crawl_warc+" + (how or "pdf")
                        got = {**got, "content": body, "text": text, "method": method, "status": "success"}
                elif warc.get("status") != "success":
                    log.info("warc miss %s: %s", ident[:40], warc.get("error"))
            except Exception as exc:
                log.info("warc fail %s: %s", ident[:40], exc)

        # optional OCR via collect module helpers or pdf_extract_lib
        if len(text) < MIN_TEXT and allow_ocr and got.get("content"):
            pdf = got["content"] if isinstance(got["content"], (bytes, bytearray)) else b""
            if pdf[:4] == b"%PDF":
                try:
                    if mod and hasattr(mod, "pdf_ocr_text"):
                        ocr = mod.pdf_ocr_text(bytes(pdf))
                    else:
                        from pdf_extract_lib import extract_ocr
                        lang = "lao+eng" if cc == "la" else ("sin+eng" if cc == "lk" else "eng")
                        ocr, _ = extract_ocr(bytes(pdf), lang=lang,
                            max_pages=int(os.environ.get("OCR_MAX_PAGES", "25") or 25))
                    if len(ocr or "") >= MIN_TEXT:
                        text, method = ocr, (method or "live") + "+ocr"
                except Exception as exc:
                    log.info("ocr fail %s: %s", ident[:40], exc)

        # IQ/ET garbage recovery
        if mod and hasattr(mod, "recover_text") and (len(text) < MIN_TEXT or allow_ocr):
            try:
                text2, method2 = mod.recover_text(got)
                if len(text2 or "") > len(text):
                    text, method = text2, method2
            except Exception:
                pass

        if len(text) < MIN_TEXT:
            fail += 1
            log_failure(cc, {"identifier": ident, "source_url": url, "reason": got.get("error") or "short", "portal": "cc_live"})
            log.info("fail %s err=%s", url[:100], got.get("error"))
            continue

        title = title_from(text, ident)
        if save_instrument(
            cc=cc, country=country, language=lang, ident=ident,
            title=title, text=text, source_url=url,
            source_type=source_type, license_text=license_text,
            collector="ingest_thin_cc_live.py", article_re=art,
            extra_meta={"fetch_method": method or "http_live", "discovery": "common_crawl_s3_cdxj_live"},
        ):
            ok += 1
            done.add(rid)
            stems.add(stem_name); stems.add(bare); stems.add(bare + ".pdf")
            log.info("ok %s method=%s corpus=%s", ident[:70], method, corpus())
        else:
            fail += 1
        time.sleep(0.35)

    laws = corpus()
    write_summary(
        cc, country=country,
        source=f"{source_type} + CC S3-discovered live PDFs",
        source_urls=[f"https://{h}/" for h in hosts[:4]],
        license_text=license_text, discovered=len(records), fetched=ok, skipped=skip, failed=fail,
        coverage="official-live-pdfs from CC S3 URL harvest",
        notes=f"ingest_thin_cc_live.py. Before {laws0} after {laws}. Started {t0}.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s corpus=%s->%s", ok, skip, fail, laws0, laws)
    print(json.dumps({"cc": cc, "ok": ok, "skip": skip, "fail": fail, "laws0": laws0, "laws": laws}, indent=2))


if __name__ == "__main__":
    main()

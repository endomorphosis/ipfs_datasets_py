#!/usr/bin/env python3
"""Vietnam: Luật + Hiến pháp from official CSDLVBPL / Công báo / chinhphu.vn.

Official only (not Thư viện pháp luật commercial):
  https://vbpl.vn                 CSDL quốc gia về pháp luật (Bộ Tư pháp)
  https://congbao.chinhphu.vn     Công báo điện tử
  https://vanban.chinhphu.vn      Hệ thống văn bản Cổng TTĐT Chính phủ
  https://chinhphu.vn

Luật + Hiến pháp first, then nghị định if tractable.
Honours vbpl.vn robots.txt: Disallow /api/ and /Pages/ (not used).
Live 429/403 uses archive_fallbacks. No WAF bypass.
Công báo/VBPL authentic text prevails. Not legal advice.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, unquote, quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "vn"
COUNTRY = "Vietnam"
SOURCE_TYPE = "vbpl_congbao"
LICENSE = (
    "Official Socialist Republic of Vietnam legislative texts from CSDL quốc gia "
    "về pháp luật (vbpl.vn, Bộ Tư pháp / Chính phủ), Công báo điện tử "
    "(congbao.chinhphu.vn) and Cổng TTĐT Chính phủ (vanban.chinhphu.vn). "
    "Công báo / VBPL authentic text prevails. Not Thư viện pháp luật. Not legal advice."
)
UA = DEFAULT_UA + " source=https://vbpl.vn/"
VBPL = "https://vbpl.vn/"
CONGBAO = "https://congbao.chinhphu.vn/"
VANBAN = "https://vanban.chinhphu.vn/"
SITEMAP_INDEX = "https://vbpl.vn/sitemap.xml"
WORKERS = 3
SLEEP = 0.35
MIN_TEXT = 400
log = logging.getLogger("vn")

CHI_TIET = re.compile(r"https://vbpl\.vn/van-ban/chi-tiet/([^/?#]+)", re.I)
ART_VN = re.compile(
    r"(?im)^\s*((?:Điều|ĐIỀU|Dieu|Điều)\s+\d+[A-Za-z]?)\b"
)
SOKYHIEU = re.compile(r"(?:so-|số-)?(\d{1,4})[-/](\d{4})[-/](qh\d+|ttg|nd-cp|nđ-cp|pl\d+)", re.I)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def pdf_to_text(raw: bytes) -> str:
    if not raw or raw[:4] != b"%PDF":
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                check=False, capture_output=True, timeout=240,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext failed: %s", exc)
    return ""


def split_vn(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_VN.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 8:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            doc_id = f"{doc_id}-{len(out)+1}"[:180]
        seen.add(doc_id)
        out.append({
            "id": doc_id,
            "title": chunk.split("\n", 1)[0][:200],
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "vn_collector"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def live_get(url: str, *, accept: str = "text/html, application/xml, */*", timeout=(20, 90), retries: int = 3):
    try:
        return http_get(
            url, ua=UA, sleep=SLEEP, timeout=timeout, retries=retries,
            headers={"Accept": accept, "Accept-Language": "vi,en;q=0.8", "Referer": VBPL},
        )
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        return None


def get_html(url: str) -> tuple[str, str]:
    r = live_get(url)
    if r is not None and r.status_code == 200 and r.text and not af.is_challenge(r.text, r.status_code):
        return r.text, "live"
    if r is not None and r.status_code in (403, 429, 503):
        log.info("live HTTP %s %s — archive fallback", r.status_code, url)
        res = af.fetch_with_fallbacks(url, try_archive_is=True, try_http=False, try_cc=True)
        if res.get("status") == "success":
            text = res.get("text") or ""
            if not text and res.get("content"):
                text = res["content"].decode("utf-8", "replace")
            return text, res.get("method") or "archive"
    return (r.text if r is not None and r.status_code == 200 else ""), ("live" if r is not None and r.status_code == 200 else "failed")


def get_bytes(url: str) -> tuple[bytes, str]:
    r = live_get(url, accept="application/pdf, application/octet-stream, */*", timeout=(20, 180), retries=2)
    if r is not None and r.status_code == 200 and r.content:
        if r.content[:4] == b"%PDF" or len(r.content) > 1000:
            return r.content, "live_pdf"
    if r is not None and r.status_code in (403, 429):
        res = af.fetch_with_fallbacks(url, try_archive_is=False, try_http=False, try_cc=True)
        if res.get("status") == "success" and res.get("content"):
            return res["content"], res.get("method") or "archive"
    return b"", "failed"


def is_priority_slug(slug: str) -> str:
    s = (slug or "").lower()
    if s.startswith("hien-phap") or "hien-phap" in s[:20]:
        return "constitution"
    if s.startswith("luat-") or s.startswith("luat-phap-lenh") or s.startswith("phap-lenh"):
        return "law"
    if s.startswith("nghi-dinh"):
        return "decree"
    return ""


def parse_sitemap_locs(xml: str) -> list[str]:
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml or "")


def discover_vbpl(include_decree: bool = False) -> list[dict]:
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    items: list[dict] = []
    if cat.exists() and cat.stat().st_size > 500:
        with cat.open(encoding="utf-8") as f:
            for line in f:
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        if len(items) > 20:
            log.info("resume catalog %s", len(items))
            return items
    html, method = get_html(SITEMAP_INDEX)
    smaps = parse_sitemap_locs(html)
    # trung uong sitemaps 1-12; 0 is static
    if not smaps:
        smaps = [f"https://vbpl.vn/sitemap/{i}.xml" for i in range(0, 13)]
    log.info("sitemaps %s method=%s", len(smaps), method)
    seen = set()
    for sm in smaps:
        if "/sitemap/" not in sm:
            continue
        # skip dia phuong (13+)
        mnum = re.search(r"/sitemap/(\d+)\.xml", sm)
        if mnum and int(mnum.group(1)) >= 13:
            continue
        xml, smethod = get_html(sm)
        locs = parse_sitemap_locs(xml)
        log.info("sitemap %s locs=%s", sm, len(locs))
        for loc in locs:
            m = CHI_TIET.search(loc)
            if not m:
                continue
            tail = m.group(1)
            if "--" in tail:
                slug, iid = tail.rsplit("--", 1)
            else:
                slug, iid = tail, tail
            kind = is_priority_slug(slug)
            if not kind:
                continue
            if kind == "decree" and not include_decree:
                continue
            if iid in seen:
                continue
            seen.add(iid)
            row = {
                "kind": kind,
                "slug": slug,
                "item_id": iid,
                "url": loc.split("?")[0],
                "source": "vbpl_sitemap",
            }
            items.append(row)
            append_catalog(CC, row)
    # vanban.chinhphu.vn Hiến pháp + Luật listings
    items.extend(discover_vanban(seen))
    log.info("catalog discovered %s", len(items))
    return items


def discover_vanban(seen: set) -> list[dict]:
    extra = []
    # typegroupid empirically: try 1..6 and keep Hiến pháp / Luật rows
    for tg in (1, 2, 3, 4, 5, 6):
        start = 0
        empty_pages = 0
        for page in range(0, 80):
            url = (
                f"https://vanban.chinhphu.vn/he-thong-van-ban?classid=1&mode=1"
                f"&typegroupid={tg}&maxresults=50"
            )
            if page:
                url += f"&currentpage={page}&start={page*50}"
            html, method = get_html(url)
            if not html:
                empty_pages += 1
                if empty_pages >= 2:
                    break
                continue
            docids = list(dict.fromkeys(re.findall(r"docid=(\d+)", html)))
            # titles near docid
            pairs = re.findall(
                r'docid=(\d+)[^>]*>\s*([^<]{3,200})',
                html,
            )
            title_map = {}
            for did, title in pairs:
                title_map.setdefault(did, re.sub(r"\s+", " ", title).strip())
            newc = 0
            for did in docids:
                title = title_map.get(did, "")
                low = title.lower()
                kind = ""
                if "hiến pháp" in low or "hien phap" in low:
                    kind = "constitution"
                elif low.startswith("luật") or "luật " in low[:40] or low.startswith("pháp lệnh"):
                    kind = "law"
                elif "nghị định" in low or low.startswith("nghi dinh"):
                    kind = "decree"
                if not kind:
                    continue
                key = f"vanban-{did}"
                if key in seen:
                    continue
                seen.add(key)
                row = {
                    "kind": kind,
                    "slug": f"vanban-{did}",
                    "item_id": did,
                    "url": f"https://vanban.chinhphu.vn/?pageid=27160&docid={did}",
                    "title_hint": title,
                    "source": "vanban_chinhphu",
                    "typegroupid": tg,
                }
                extra.append(row)
                append_catalog(CC, row)
                newc += 1
            log.info("vanban tg=%s page=%s new=%s docids=%s", tg, page, newc, len(docids))
            if newc == 0 and page > 0:
                empty_pages += 1
                if empty_pages >= 2:
                    break
            else:
                empty_pages = 0
            if not docids:
                break
            # Hiến pháp is tiny; Luật listing: keep going while new
            if tg in (1, 6) and page >= 3 and newc == 0:
                break
        if extra and tg in (1, 4, 6):
            pass
    return extra


def rsc_text(html: str) -> str:
    if not html:
        return ""
    parts = []
    # unescape next_f string payloads
    for m in re.finditer(r'self\.__next_f\.push\(\[1,"((?:\\.|[^"\\])*)"\]\)', html):
        raw = m.group(1)
        try:
            raw = bytes(raw, "utf-8").decode("unicode_escape")
        except Exception:
            raw = raw.replace("\\n", "\n").replace('\\"', '"')
        if "Điều" in raw or "HIẾN PHÁP" in raw or "Luật" in raw:
            parts.append(raw)
    blob = "\n".join(parts)
    # strip leftover JSON noise a bit
    blob = re.sub(r"\$[A-Za-z0-9]+", " ", blob)
    return html_to_text(blob) if blob else ""


def extract_toanvan_text(html: str) -> str:
    if not html:
        return ""
    low = html.lower()
    idx = low.find('id="toanvancontent"')
    if idx < 0:
        idx = low.find("class=\"toanvancontent\"")
    if idx >= 0:
        chunk = html[idx: idx + 450000]
        text = html_to_text(chunk)
    else:
        text = html_to_text(html)
    # drop portal chrome; keep from first Điều / LUẬT / HIẾN PHÁP
    for marker in ("HIẾN PHÁP", "Hiến pháp", "BỘ LUẬT", "Bộ luật", "LUẬT\n", "Luật\n", "Điều 1", "ĐIỀU 1"):
        i = text.find(marker)
        if i >= 0 and i < len(text) * 0.7:
            text = text[i:]
            break
    return text.strip()


def parse_vbpl_page(html: str, url: str) -> dict:
    title = ""
    m = re.search(r"<title>\s*([^<]+)", html or "", re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).split("|")[0].strip()
    if title.strip() in ("Trung ương", "VBPL", "CSDL quốc gia về VBPL"):
        title = ""
    tm = re.search(r"(?:LUẬT|BỘ LUẬT|HIẾN PHÁP)[^\n]{0,180}", extract_toanvan_text(html)[:2500] or "")
    if tm and (not title or len(title) < 12):
        title = re.sub(r"\s+", " ", tm.group(0)).strip()
    date = None
    dm = re.search(r'"legislationDate"\s*:\s*"(\d{4}-\d{2}-\d{2})', html or "")
    if dm:
        date = dm.group(1)
    else:
        dm = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", html or "")
        if dm:
            date = f"{dm.group(3)}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}"
    ident = ""
    im = re.search(r'"legislationIdentifier"\s*:\s*"([^"]+)"', html or "")
    if im:
        ident = im.group(1)
    pdfs = re.findall(r'href="([^"]+\.pdf)"', html or "", re.I)
    pdfs += re.findall(r"https://congbaocdn.chinhphu.vn/\S+?\.pdf", html or "", re.I)
    pdfs = [urljoin(url, p) for p in pdfs]
    text = extract_toanvan_text(html)
    rsc = rsc_text(html)
    if rsc.count("Điều") > text.count("Điều") and len(rsc) > 800:
        text = rsc
    if text.count("Điều") < 2 and "Đang tải dữ liệu" in (html or ""):
        text = ""
    return {"title": title, "date": date, "identifier": ident, "pdfs": list(dict.fromkeys(pdfs)), "text": text}


def parse_vanban_page(html: str, url: str) -> dict:
    title = ""
    m = re.search(r"<title>\s*([^<]+)", html or "", re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
    pdfs = []
    for href in re.findall(r'href="(https?://datafiles\.chinhphu\.vn/[^"]+)"', html or "", re.I):
        if href.lower().endswith((".pdf", ".doc", ".docx")):
            pdfs.append(href)
    for href in re.findall(r'href="([^"]+\.pdf)"', html or "", re.I):
        pdfs.append(urljoin(url, href))
    date = None
    dm = re.search(r"(\d{2})[-/](\d{2})[-/](\d{4})", html or "")
    if dm:
        date = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
    text = html_to_text(html)
    return {"title": title, "date": date, "pdfs": list(dict.fromkeys(pdfs)), "text": text}


def discover_congbao(seen: set) -> list[dict]:
    extra = []
    seeds = [
        ("https://congbao.chinhphu.vn/van-ban-dang-cong-bao/luat-l13.htm", "law"),
        ("https://congbao.chinhphu.vn/van-ban-dang-cong-bao/hien-phap-l26.htm", "constitution"),
        ("https://congbao.chinhphu.vn/van-ban-dang-cong-bao/bo-luat-l12.htm", "law"),
    ]
    href_re = re.compile(r'href="(/(?:van-ban)/(?:luat|hien-phap|bo-luat)[^"#?]+\.htm)"', re.I)
    for seed, kind in seeds:
        html, method = get_html(seed)
        if not html:
            continue
        urls = []
        for rel in href_re.findall(html):
            urls.append(urljoin(CONGBAO, rel))
        # light pagination guesses
        for n in range(2, 8):
            for cand in (f"{seed}?page={n}", f"{seed}?p={n}", seed.replace(".htm", f"-p{n}.htm")):
                h2, _ = get_html(cand)
                if not h2:
                    continue
                found = href_re.findall(h2)
                if not found:
                    break
                urls.extend(urljoin(CONGBAO, rel) for rel in found)
        for u in dict.fromkeys(urls):
            key = u.rstrip("/").rsplit("/", 1)[-1]
            if key in seen:
                continue
            seen.add(key)
            slug = key.replace(".htm", "")
            row = {
                "kind": kind,
                "slug": slug,
                "item_id": slug,
                "url": u,
                "source": "congbao",
            }
            extra.append(row)
            append_catalog(CC, row)
        log.info("congbao seed=%s new=%s method=%s", seed, len(extra), method)
    return extra


def fetch_toanvan(item_id: str) -> tuple[str, str, str]:
    """HTTP Wayback of official old CSDLVBPL toàn văn (HTTPS Wayback SSL-fails here)."""
    if not item_id or not str(item_id).isdigit():
        return "", "", ""
    orig = f"https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID={item_id}"
    wb = f"http://web.archive.org/web/2id_/{orig}"
    try:
        r = __import__("requests").get(
            wb, timeout=(20, 90), allow_redirects=True,
            headers={"User-Agent": UA, "Accept": "text/html, */*"},
        )
    except Exception as exc:
        log.info("http wayback fail ItemID=%s: %s", item_id, exc)
        return "", orig, "failed"
    html = r.text or ""
    if r.status_code == 200 and html.count("Điều") >= 2:
        return html, orig, "wayback_toanvan"
    log.info("http wayback HTTP %s ItemID=%s dieu=%s", r.status_code, item_id, html.count("Điều"))
    return "", orig, "failed"



def fetch_one(it: dict, done: set[str], include_decree: bool) -> str:
    kind = it.get("kind") or "law"
    if kind == "decree" and not include_decree:
        return "skip"
    slug = it.get("slug") or it.get("item_id") or "unknown"
    url = it.get("url") or ""
    ident = slug
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    html, method = "", "failed"
    is_congbao = "congbao.chinhphu.vn" in url or it.get("source") == "congbao"
    if is_congbao:
        html, method = get_html(url)
    else:
        tv_html, tv_url, tv_method = fetch_toanvan(str(it.get("item_id") or ""))
        if tv_html:
            html, url, method = tv_html, tv_url, tv_method
        else:
            log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "no_official_fulltext"})
            return "fail"
    if not html:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "empty_page"})
        return "fail"
    if "Đang tải dữ liệu" in html and html.count("Điều") < 2:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "spa_shell"})
        return "fail"
    if "congbao.chinhphu.vn" in url:
        meta = parse_vanban_page(html, url)
        # Công báo signed PDFs (Word-origin) extract; prefer over listing chrome
        cdn = re.findall(r"https://congbaocdn.chinhphu.vn/\S+?\.pdf", html or "", re.I)
        meta["pdfs"] = list(dict.fromkeys((meta.get("pdfs") or []) + cdn))
    elif "vanban.chinhphu.vn" in url:
        meta = parse_vanban_page(html, url)
    else:
        meta = parse_vbpl_page(html, url)
    text = meta.get("text") or ""
    pdf_url = None
    pdfs = meta.get("pdfs") or []
    if pdfs and (text.count("Điều") < 8 or any("congbaocdn" in (p or "") for p in pdfs) or len(text) < 1200):
        for p in pdfs[:3]:
            if "g7.cdnchinhphu.vn" in (p or ""):
                continue  # signed stream often TLS-fails from this host
            raw, pm = get_bytes(p)
            pt = pdf_to_text(raw) if raw and raw[:4] == b"%PDF" else ""
            if len(pt) > len(text) and pt.count("Điều") >= text.count("Điều"):
                text, method, pdf_url = pt, pm, p
    # chrome-only pages
    if len(text) < MIN_TEXT or (text.count("Điều") < 2 and "Hiến pháp" not in text and "HIẾN PHÁP" not in text):
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "empty_text"})
        return "fail"
    title = it.get("title_hint") or meta.get("title") or ident
    official = meta.get("identifier") or ident
    date = iso_date(meta.get("date")) if meta.get("date") else None
    dtype = "constitution" if kind == "constitution" else ("decree" if kind == "decree" else "statute")
    docs = split_vn(text, rid, url, date)
    rec = base_record(
        cc=CC, country=COUNTRY, language="vi", ident=ident,
        title=title, text=text, source_url=url, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="vn-vbpl-congbao",
        date=date, official_identifier=official, document_type=dtype,
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {
                "method": it.get("source") or "vbpl_sitemap",
                "retrieval": method,
                "pdf_url": pdf_url,
            },
            "official_metadata": {
                "slug": slug, "item_id": it.get("item_id"), "kind": kind,
            },
        },
        extra_fields={
            "canonical_title": title,
            "citation": official,
            "canonical_document_url": pdf_url or url,
            "status_source": "vbpl_congbao",
            "status_note": "Công báo / VBPL authentic text prevails. Not Thư viện pháp luật.",
        },
    )
    rec["id"] = rid
    rec["languages"] = ["vi"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover_vbpl(include_decree=False)
    seen_keys = {str(x.get("slug") or x.get("item_id") or x.get("url")) for x in items}
    items.extend(discover_congbao(seen_keys))
    n_law = sum(1 for x in items if x.get("kind") in ("law", "constitution"))
    include_decree = n_law < 40  # nghị định only if luật not tractable / tiny
    if include_decree:
        log.info("luat/hienphap catalog small (%s) — adding nghị định from sitemaps", n_law)
        items = discover_from_sitemaps_fresh(include_decree=True)
    done = existing_ids(CC)
    ok = skip = fail = 0
    queue = [x for x in items if include_decree or x.get("kind") != "decree"]
    queue.sort(key=lambda x: 0 if (x.get("source") == "congbao" or "congbao.chinhphu.vn" in (x.get("url") or "")) else 1)
    log.info("queue %s already_done=%s include_decree=%s congbao=%s",
             len(queue), len(done), include_decree,
             sum(1 for x in queue if x.get("source")=="congbao"))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, it, done, include_decree) for it in queue]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"
            skip += st == "skip"
            fail += st == "fail"
            if n % 30 == 0 or n == len(queue):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(queue), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY,
                    source="CSDLVBPL / Công báo / vanban.chinhphu.vn",
                    source_urls=[VBPL, CONGBAO, VANBAN, "https://chinhphu.vn/"],
                    license_text=LICENSE, discovered=len(queue), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="Luật + Hiến pháp first. Not Thư viện pháp luật.",
                    last_run=utcnow(),
                )
    coverage = "full" if fail == 0 and ok + skip >= len(queue) and queue else "catalog-backed incomplete"
    notes = (
        f"Luật + Hiến pháp from vbpl.vn sitemaps and vanban.chinhphu.vn "
        f"(catalog {len(queue)}; include_decree={include_decree}). "
        "vbpl.vn /api/ and /Pages/ not used (robots Disallow). "
        "Not Thư viện pháp luật. Công báo/VBPL prevails. "
        f"Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="CSDLVBPL / Công báo / vanban.chinhphu.vn",
        source_urls=[VBPL, CONGBAO, VANBAN, "https://chinhphu.vn/"],
        license_text=LICENSE, discovered=len(queue), fetched=ok,
        skipped=skip, failed=fail, coverage=coverage, notes=notes,
        last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(queue),
        "coverage": coverage, "include_decree": include_decree,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


def discover_from_sitemaps_fresh(include_decree: bool) -> list[dict]:
    """Re-walk sitemaps when luật catalog is too small."""
    # wipe in-memory; keep file and merge
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    existing = []
    seen = set()
    if cat.exists():
        with cat.open(encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                existing.append(row)
                seen.add(str(row.get("item_id") or row.get("slug")))
    html, _ = get_html(SITEMAP_INDEX)
    smaps = parse_sitemap_locs(html) or [f"https://vbpl.vn/sitemap/{i}.xml" for i in range(1, 13)]
    for sm in smaps:
        mnum = re.search(r"/sitemap/(\d+)\.xml", sm)
        if mnum and int(mnum.group(1)) >= 13:
            continue
        if "/sitemap/" not in sm:
            continue
        xml, _ = get_html(sm)
        for loc in parse_sitemap_locs(xml):
            m = CHI_TIET.search(loc)
            if not m:
                continue
            tail = m.group(1)
            if "--" in tail:
                slug, iid = tail.rsplit("--", 1)
            else:
                slug, iid = tail, tail
            kind = is_priority_slug(slug)
            if not kind or (kind == "decree" and not include_decree):
                continue
            if iid in seen:
                continue
            seen.add(iid)
            row = {"kind": kind, "slug": slug, "item_id": iid, "url": loc.split("?")[0], "source": "vbpl_sitemap"}
            existing.append(row)
            append_catalog(CC, row)
    existing.extend(discover_vanban(seen))
    log.info("fresh catalog %s", len(existing))
    return existing


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Malaysia: in-force principal Acts from AGC Federal Legislation Portal.

Official only:
  https://lom.agc.gov.my/  (Portal Perundangan Persekutuan)
  Catalog: GET json-updated-2024.php (AES-GCM envelope; key published in page JS)
  Bodies: official PDF consolidations under /ilims/upload/portal/akta/outputaktap/

Does not use LawNet / PNMB / commercial databases.
Bilingual ms/en when both PDFs exist.
Not presented as the printed Gazette for s.61 Interpretation Acts.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urljoin

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC = "my"
COUNTRY = "Malaysia"
SOURCE_TYPE = "lom_agc_pdf"
LICENSE = (
    "Malaysian official texts from the Attorney-General's Chambers Federal "
    "Legislation Portal (lom.agc.gov.my). AGC portal terms / copyright AGC "
    "Malaysia. Online texts are not the printed Gazette for s.61 of the "
    "Interpretation Acts 1948 and 1967; the printed Gazette and authentic "
    "Laws of Malaysia reprint prevail. Recorded as a research snapshot with "
    "provenance. Not legal advice."
)
UA = DEFAULT_UA + " source=https://lom.agc.gov.my/"
PORTAL = "https://lom.agc.gov.my/"
CATALOG_URL = "https://lom.agc.gov.my/json-updated-2024.php"
UPDATED_PAGE = "https://lom.agc.gov.my/principal.php?type=updated"
TNC_URL = "https://lom.agc.gov.my/tnc.php"
FAQ_URL = "https://lom.agc.gov.my/faq.php"
WORKERS = 10
SLEEP = 0.25
FALLBACK_KEY = "ecdf7a016e103d01314ce0e3be4ac00bd6b1b931a276cb1a000abdad1b89bfff"
log = logging.getLogger("my")

ART_EN = re.compile(
    r"(?im)^\s*((?:Section|SECTION|s\.)\s+\d+[A-Za-z]?)\b"
)
ART_MS = re.compile(
    r"(?im)^\s*((?:Seksyen|SEKSYEN|seksyen)\s+\d+[A-Za-z]?)\b"
)


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
                check=False, capture_output=True, timeout=180,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext failed: %s", exc)
    return ""


def split_my_articles(text: str, law_id: str, source_url: str, date: Optional[str], lang: str) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    pat = ART_MS if lang == "ms" else ART_EN
    matches = list(pat.finditer(text or ""))
    if len(matches) < 2:
        return []
    out = []
    seen = set()
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            doc_id = f"{doc_id}-{len(out)+1}"[:180]
        seen.add(doc_id)
        heading = chunk.split("\n", 1)[0][:200]
        out.append({
            "id": doc_id,
            "title": heading,
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "lom_agc_pdf"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def page_aes_key() -> str:
    try:
        r = http_get(UPDATED_PAGE, ua=UA, sleep=0.2, timeout=(20, 60), retries=3)
        if r.status_code == 200 and r.text:
            m = re.search(r"SEARCH_RESPONSE_KEY\s*=\s*'([0-9a-fA-F]{64})'", r.text)
            if m:
                return m.group(1)
    except Exception as exc:
        log.warning("key from page: %s", exc)
    return FALLBACK_KEY


def decrypt_envelope(payload: dict, key_hex: str) -> dict:
    if not isinstance(payload, dict) or not payload.get("encrypted"):
        return payload
    blob = base64.b64decode(payload["data"])
    iv, tag, ct = blob[:12], blob[12:28], blob[28:]
    pt = AESGCM(bytes.fromhex(key_hex)).decrypt(iv, ct + tag, None)
    return json.loads(pt.decode("utf-8"))


def strip_tags(raw: str) -> str:
    if not raw:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_to_text(f"<p>{s}</p>") if "<" in raw else s
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_titles(title_html: str) -> dict:
    out = {"en": "", "ms": "", "date": None, "detail_en": None, "detail_ms": None}
    if not title_html:
        return out
    for m in re.finditer(
        r'href="(act-detail\.php\?[^"]+)"[^>]*>([^<]+)', title_html, re.I
    ):
        href, label = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        lang = "en" if "lang=BI" in href or "language=BI" in href else "ms"
        out[lang] = label
        out[f"detail_{lang}"] = urljoin(PORTAL, href.replace("#timeline", ""))
        dm = re.search(r"date=(\d{2}-\d{2}-\d{4})", href)
        if dm and not out["date"]:
            d, mo, y = dm.group(1).split("-")
            out["date"] = f"{y}-{mo}-{d}"
    if not out["en"] and not out["ms"]:
        out["en"] = strip_tags(title_html)
    return out


def parse_pdfs(rec: dict) -> list[dict]:
    docs = []
    raw = rec.get("doc2downloadgeneratepdf") or "[]"
    try:
        arr = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        arr = []
    for d in arr:
        path = (d.get("path") or "").strip()
        name = (d.get("docName") or "").strip()
        icon = (d.get("icon") or "")
        if not path or not name:
            continue
        if path.startswith("/upload/"):
            url_path = "/ilims" + path + name
        elif path.startswith("/ilims/"):
            url_path = path + name
        else:
            url_path = "/ilims/upload/portal/akta" + path + name
        url = "https://lom.agc.gov.my" + quote(url_path, safe="/:")
        if "_BM" in path or "ms" in icon or name.lower().startswith("akta"):
            lang = "ms"
        else:
            lang = "en"
        docs.append({"url": url, "name": name, "lang": lang, "path": path})
    # processFile tokens as fallback
    html = rec.get("doc2download_link") or rec.get("doc2download") or ""
    tokens = re.findall(r"processFile\.php\?token=([^\"'&]+)", html)
    for tok in tokens:
        try:
            decoded = base64.b64decode(unquote(tok)).decode("utf-8", "replace")
            pdf_url = decoded.split("|", 1)[0]
            if not pdf_url.startswith("http"):
                continue
            lang = "ms" if "_BM" in pdf_url or "/Akta" in pdf_url else "en"
            if not any(x["url"] == pdf_url or x.get("token") == tok for x in docs):
                # attach token to matching lang if url differs only by encoding
                matched = False
                for x in docs:
                    if x["lang"] == lang and "token" not in x:
                        x["token"] = tok
                        x["process_url"] = PORTAL + "processFile.php?token=" + tok
                        matched = True
                        break
                if not matched:
                    docs.append({
                        "url": pdf_url, "name": Path(pdf_url).name, "lang": lang,
                        "token": tok, "process_url": PORTAL + "processFile.php?token=" + tok,
                    })
        except Exception:
            continue
    return docs


def discover() -> list[dict]:
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    items: list[dict] = []
    if cat.exists() and cat.stat().st_size > 1000:
        with cat.open(encoding="utf-8") as f:
            for line in f:
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        if items:
            log.info("resume catalog %s", len(items))
            return items
    key = page_aes_key()
    log.info("fetching catalog %s", CATALOG_URL)
    r = http_get(CATALOG_URL, ua=UA, sleep=0.2, timeout=(20, 180), retries=5,
                 headers={"Accept": "application/json, */*", "Referer": UPDATED_PAGE})
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"catalog HTTP {r.status_code}")
    try:
        payload = r.json()
    except Exception:
        raise RuntimeError("catalog not json")
    data = decrypt_envelope(payload, key)
    recs = data.get("records") or []
    dest = ROOT / CC / "raw" / "updated_catalog.json"
    atomic_write(dest, json.dumps({"recordsTotal": data.get("recordsTotal"), "n": len(recs)}, ensure_ascii=False, indent=2))
    seen = set()
    for rec in recs:
        act_no = str(rec.get("lgt_act_no") or rec.get("lgt_act_id") or "").strip()
        if not act_no or act_no in seen:
            continue
        seen.add(act_no)
        titles = parse_titles(rec.get("title") or "")
        pdfs = parse_pdfs(rec)
        row = {
            "act_no": act_no,
            "act_id": str(rec.get("lgt_act_id") or act_no).strip(),
            "log_type": rec.get("lgt_log_type") or "UPDATED",
            "title_en": titles["en"],
            "title_ms": titles["ms"],
            "date": titles["date"],
            "detail_en": titles["detail_en"] or f"{PORTAL}act-detail.php?act={act_no}&lang=BI",
            "detail_ms": titles["detail_ms"] or f"{PORTAL}act-detail.php?act={act_no}&lang=BM",
            "pdfs": pdfs,
        }
        items.append(row)
        append_catalog(CC, row)
    log.info("catalog discovered %s (recordsTotal=%s)", len(items), data.get("recordsTotal"))
    return items


def fetch_pdf(spec: dict) -> bytes:
    urls = [spec.get("url")]
    if spec.get("process_url"):
        urls.append(spec["process_url"])
    for url in urls:
        if not url:
            continue
        try:
            r = http_get(
                url, ua=UA, sleep=SLEEP, timeout=(20, 180), retries=3,
                headers={"Accept": "application/pdf, */*", "Referer": UPDATED_PAGE},
            )
        except Exception as exc:
            log.warning("pdf get %s: %s", url, exc)
            continue
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
        log.info("pdf miss status=%s bytes=%s url=%s", r.status_code, len(r.content or b""), url[:120])
    return b""


def record_id(act_no: str, lang: str) -> str:
    return slug_id(CC, f"act-{act_no}-{lang}")


def fetch_lang(it: dict, lang: str, spec: dict, done: set[str]) -> str:
    act_no = it["act_no"]
    rid = record_id(act_no, lang)
    if rid in done:
        return "skip"
    raw = fetch_pdf(spec)
    if not raw:
        log_failure(CC, {
            "identifier": f"act-{act_no}-{lang}",
            "source_url": spec.get("url"),
            "status": "failed",
            "reason": "missing_pdf",
        })
        return "fail"
    text = pdf_to_text(raw)
    if not text or len(text) < 40:
        log_failure(CC, {
            "identifier": f"act-{act_no}-{lang}",
            "source_url": spec.get("url"),
            "status": "failed",
            "reason": "empty_text",
        })
        return "fail"
    title = (it.get("title_en") if lang == "en" else it.get("title_ms")) or spec.get("name") or f"Act {act_no}"
    source_url = it.get("detail_en") if lang == "en" else it.get("detail_ms")
    date = it.get("date")
    docs = split_my_articles(text, rid, source_url, date, lang)
    rec = base_record(
        cc=CC, country=COUNTRY, language=lang, ident=f"act-{act_no}-{lang}",
        title=title, text=text, source_url=source_url, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="my-lom-agc",
        eli=None, date=date, official_identifier=f"Act {act_no}",
        document_type="statute", law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": "json_updated_2024_aes_gcm",
                "catalog_identifier": act_no,
                "seed_url": CATALOG_URL,
                "pdf_url": spec.get("url"),
                "pdf_name": spec.get("name"),
            },
            "official_metadata": {
                "act_no": act_no,
                "act_id": it.get("act_id"),
                "log_type": it.get("log_type"),
                "title_en": it.get("title_en"),
                "title_ms": it.get("title_ms"),
                "language": lang,
            },
        },
        extra_fields={
            "canonical_title": title,
            "languages": ["en", "ms"] if (it.get("title_en") and it.get("title_ms")) else [lang],
            "citation": f"Act {act_no} ({title})",
            "canonical_document_url": spec.get("url"),
            "status_source": "lom_agc_updated_principal",
            "status_confidence": "high",
            "status_note": (
                "Updated reprint from AGC portal. Not the printed Gazette for "
                "s.61 Interpretation Acts; authentic LOM reprint / Gazette prevails."
            ),
        },
    )
    rec["id"] = rid
    rec["languages"] = rec.get("languages") or [lang]
    write_instrument(CC, rec)
    return "ok"


def fetch_one(it: dict, done: set[str]) -> dict:
    counts = {"ok": 0, "skip": 0, "fail": 0}
    pdfs = it.get("pdfs") or []
    by_lang = {}
    for spec in pdfs:
        by_lang.setdefault(spec.get("lang") or "en", spec)
    if not by_lang:
        log_failure(CC, {"identifier": it.get("act_no"), "status": "failed", "reason": "no_pdfs"})
        return {"ok": 0, "skip": 0, "fail": 1}
    for lang, spec in by_lang.items():
        try:
            st = fetch_lang(it, lang, spec, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"identifier": f"act-{it.get('act_no')}-{lang}", "status": "failed", "reason": repr(exc)})
        counts[st] = counts.get(st, 0) + 1
    return counts


def main():
    setup()
    t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    log.info("queue acts=%s already_done=%s", len(items), len(done))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, it, done) for it in items]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                c = fut.result()
            except Exception as exc:
                c = {"ok": 0, "skip": 0, "fail": 1}
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += c.get("ok", 0)
            skip += c.get("skip", 0)
            fail += c.get("fail", 0)
            if n % 50 == 0 or n == len(items):
                log.info("progress acts=%s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY,
                    source="AGC Federal Legislation Portal (lom.agc.gov.my) updated principal Acts",
                    source_urls=[PORTAL, UPDATED_PAGE, CATALOG_URL, TNC_URL],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="Updated principal Acts. Bilingual ms/en when both PDFs exist.",
                    last_run=utcnow(),
                )
    coverage = "full" if fail == 0 and ok + skip > 0 else "catalog-backed incomplete"
    notes = (
        f"Updated principal Acts from json-updated-2024.php ({len(items)} act numbers). "
        "Bilingual English (BI) and Malay (BM) PDFs when both exist (separate rows). "
        "Not P.U.(A)/P.U.(B), not amendment Acts, not ordinances. "
        "Not LawNet/PNMB. Online text is not the printed Gazette for s.61 Interpretation Acts. "
        f"Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="AGC Federal Legislation Portal (lom.agc.gov.my) updated principal Acts",
        source_urls=[PORTAL, UPDATED_PAGE, CATALOG_URL, TNC_URL, FAQ_URL],
        license_text=LICENSE, discovered=len(items), fetched=ok,
        skipped=skip, failed=fail, coverage=coverage, notes=notes,
        last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items), "coverage": coverage,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()

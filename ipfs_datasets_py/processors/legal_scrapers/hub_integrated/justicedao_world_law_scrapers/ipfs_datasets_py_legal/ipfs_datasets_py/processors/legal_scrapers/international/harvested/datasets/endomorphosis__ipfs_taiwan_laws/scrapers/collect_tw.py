#!/usr/bin/env python3
"""Taiwan: national 法律 / 憲法 / 命令 from 全國法規資料庫 Open API (MOJ).

Official only:
  https://law.moj.gov.tw
  Open API (swagger): https://law.moj.gov.tw/api/swagger/index.html
    GET /api/ch/law/json   GET /api/en/law/json
    GET /api/ch/order/json GET /api/en/order/json
  Authentic gazette (總統府公報 / 行政院公報) prevails over the database.

robots.txt Disallow:/ for generic crawlers — this collector does not scrape
HTML. It uses the Ministry of Justice Open API bulk ZIP/JSON only.

English rows are official MOJ translations (not machine translation).
No Lawbank / 北大法宝 / Westlaw. No git clone. No HF upload.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import zipfile
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "tw"
COUNTRY = "Taiwan"
SOURCE_TYPE = "moj_law_json"
LICENSE = (
    "Taiwan official texts from 全國法規資料庫 (Ministry of Justice). "
    "Laws, orders and official documents are excepted from copyright under "
    "著作權法. Authentic 總統府公報 / 行政院公報 prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://law.moj.gov.tw/"
PORTAL = "https://law.moj.gov.tw/"
SWAGGER = "https://law.moj.gov.tw/api/swagger/index.html"
API = {
    ("ch", "law"): "https://law.moj.gov.tw/api/ch/law/json",
    ("en", "law"): "https://law.moj.gov.tw/api/en/law/json",
    ("ch", "order"): "https://law.moj.gov.tw/api/ch/order/json",
    ("en", "order"): "https://law.moj.gov.tw/api/en/order/json",
}
ZIP_NAME = {
    ("ch", "law"): "ChLaw.json.zip",
    ("en", "law"): "EnLaw.json.zip",
    ("ch", "order"): "ChOrder.json.zip",
    ("en", "order"): "EnOrder.json.zip",
}
PCODE_RE = re.compile(r"pcode=([A-Za-z0-9]+)", re.I)
log = logging.getLogger("tw")
STATS = {"live": 0, "archive": 0, "fail": 0}


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def pcode_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    m = PCODE_RE.search(url)
    return m.group(1).upper() if m else None


def roc_date(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    val = str(val).strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", val)
    if m and m.group(2) != "00" and m.group(3) != "00":
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return iso_date(val)


def download_zip(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and zipfile.is_zipfile(dest) and dest.stat().st_size > 1000:
        log.info("zip present %s bytes=%s", dest.name, dest.stat().st_size)
        return True
    tmp = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(1, 6):
        try:
            log.info("GET %s attempt=%s", url, attempt)
            r = get_session(UA).get(url, timeout=(30, 180), stream=True)
            if r.status_code in (403, 429) or af.is_challenge(r.text if r.headers.get("content-type", "").startswith("text") else "", r.status_code):
                log.info("live HTTP %s %s — archive fallback", r.status_code, url)
                res = af.fetch_with_fallbacks(url, try_archive_is=True, try_http=False, try_cc=True)
                if res.get("status") == "success" and res.get("content"):
                    body = res["content"]
                    if body[:2] == b"PK":
                        dest.write_bytes(body)
                        STATS["archive"] += 1
                        log.info("archive zip %s bytes=%s via %s", dest.name, dest.stat().st_size, res.get("method"))
                        return True
                last = f"http_{r.status_code}"
                continue
            if r.status_code != 200:
                last = f"http_{r.status_code}"
                continue
            n = 0
            with tmp.open("wb") as handle:
                for chunk in r.iter_content(1 << 16):
                    if chunk:
                        handle.write(chunk)
                        n += len(chunk)
            cl = r.headers.get("Content-Length")
            if cl and int(cl) != n:
                last = f"size {n} vs {cl}"
                log.warning("size mismatch %s", last)
                continue
            if n < 1000 or tmp.read_bytes()[:2] != b"PK":
                last = "not_zip"
                continue
            tmp.replace(dest)
            STATS["live"] += 1
            log.info("downloaded %s bytes=%s", dest.name, dest.stat().st_size)
            return True
        except Exception as exc:
            last = repr(exc)
            log.warning("download fail %s: %s", url, exc)
    log.error("failed download %s last=%s", url, last)
    STATS["fail"] += 1
    return False


def load_zip_json(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        jn = [n for n in z.namelist() if n.lower().endswith(".json")]
        if not jn:
            raise RuntimeError(f"no json in {path}")
        raw = z.read(jn[0]).decode("utf-8-sig", "replace")
    return json.loads(raw)


def art_slug(no: str, i: int) -> str:
    m = re.search(r"(\d+[A-Za-z]?)", no or "")
    if m:
        return f"art-{m.group(1).lower()}"
    s = re.sub(r"[^a-z0-9]+", "-", (no or "").lower()).strip("-")
    return s or f"a{i}"


def articles_from_list(rows, *, law_id: str, source_url: str, date: Optional[str],
                       type_key: str, no_key: str, content_key: str) -> tuple[str, list[dict]]:
    parts: list[str] = []
    docs: list[dict] = []
    seen: set[str] = set()
    heading_path: list[str] = []
    i = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        typ = (row.get(type_key) or "").strip().upper()
        no = (row.get(no_key) or "").strip()
        content = (row.get(content_key) or "").strip()
        if not content:
            continue
        content = content.replace("\xa0", " ")
        content = re.sub(r"[ \t]+\n", "\n", content).strip()
        if typ == "C":
            heading_path = [re.sub(r"\s+", " ", content).strip()]
            parts.append(content)
            continue
        i += 1
        body = content
        if no and no not in body[:80]:
            body = f"{no}\n{content}"
        if heading_path:
            parts.append(heading_path[-1])
        parts.append(body)
        slug = art_slug(no, i)
        doc_id = f"{law_id}-{slug}"[:180]
        if doc_id in seen:
            doc_id = f"{doc_id}-{i}"[:180]
        seen.add(doc_id)
        heading = (no or body.split("\n", 1)[0])[:200]
        docs.append({
            "id": doc_id,
            "title": heading,
            "text": body,
            "date_filed": date,
            "document_number": no or str(i),
            "source_url": source_url,
            "record_type": "article",
            "article_number": no or str(i),
            "law_identifier": law_id,
            "hierarchy_path_text": " / ".join(heading_path) if heading_path else "",
            "metadata": {
                "text_extraction": {"source": "official", "backend": "moj_law_json_article"},
                "article_type": typ or "A",
            },
        })
        if len(docs) >= 8000:
            break
    text = "\n\n".join(p for p in parts if p)
    return text, docs


def record_one(law: dict, *, lang: str, kind: str, done: set[str]) -> str:
    if lang == "en":
        url = law.get("EngLawURL") or ""
        title = (law.get("EngLawName") or law.get("LawName") or "").strip()
        zh_title = (law.get("LawName") or "").strip()
        foreword = (law.get("EngLawForeword") or "").strip()
        histories = (law.get("EngLawHistories") or "").strip()
        abandon = (law.get("EngLawAbandonNote") or "").strip()
        date = roc_date(law.get("EngLawModifiedDate"))
        arts = law.get("EngLawArticles")
        type_key, no_key, content_key = "EngArticleType", "EngArticleNo", "EngArticleContent"
        ident_suffix = "-en"
        language = "en"
    else:
        url = law.get("LawURL") or ""
        title = (law.get("LawName") or "").strip()
        zh_title = title
        eng_name = (law.get("EngLawName") or "").strip()
        foreword = (law.get("LawForeword") or "").strip()
        histories = (law.get("LawHistories") or "").strip()
        abandon = (law.get("LawAbandonNote") or "").strip()
        date = roc_date(law.get("LawModifiedDate") or law.get("LawEffectiveDate"))
        arts = law.get("LawArticles")
        type_key, no_key, content_key = "ArticleType", "ArticleNo", "ArticleContent"
        ident_suffix = ""
        language = "zh-Hant"
        if not url:
            url = ""
    pcode = pcode_from_url(url)
    if not pcode:
        log_failure(CC, {"identifier": title, "source_url": url, "status": "failed", "reason": "no_pcode"})
        return "fail"
    ident = pcode + ident_suffix
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    if not url:
        url = f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"
        if lang == "en":
            url = f"https://law.moj.gov.tw/Eng/LawClass/LawAll.aspx?pcode={pcode}"
    body, docs = articles_from_list(
        arts, law_id=rid, source_url=url, date=date,
        type_key=type_key, no_key=no_key, content_key=content_key,
    )
    chunks = []
    if title:
        chunks.append(title)
    if foreword:
        chunks.append(foreword)
    if body:
        chunks.append(body)
    text = "\n\n".join(chunks)
    if not text or len(text) < 8:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "empty_text"})
        return "fail"
    level = (law.get("LawLevel") or "").strip()
    if level == "憲法":
        doc_type = "constitution"
    elif level == "命令":
        doc_type = "regulation"
    else:
        doc_type = "statute"
    repealed = bool(abandon) or (law.get("LawCategory") or "").startswith("廢止")
    law_status = "repealed" if repealed else "current"
    aliases = []
    if lang == "en" and zh_title and zh_title != title:
        aliases.append(zh_title)
    if lang != "en":
        eng_name = (law.get("EngLawName") or "").strip()
        if eng_name:
            aliases.append(eng_name)
    rec = base_record(
        cc=CC, country=COUNTRY, language=language, ident=ident,
        title=title or pcode, text=text, source_url=url, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="tw-moj-open-api",
        eli=None, date=date, official_identifier=pcode,
        document_type=doc_type, law_status=law_status, is_current=not repealed,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": "moj_open_api_zip_json",
                "catalog_identifier": pcode,
                "seed_url": API[(lang if lang == "en" else "ch", kind)],
                "retrieval": "live",
                "dump": ZIP_NAME[(lang if lang == "en" else "ch", kind)],
            },
            "official_metadata": {
                "pcode": pcode,
                "law_level": level,
                "law_category": law.get("LawCategory"),
                "law_has_eng_version": law.get("LawHasEngVersion"),
                "abandon_note": abandon or None,
                "effective_note": law.get("LawEffectiveNote") or None,
                "histories": histories[:2000] if histories else None,
            },
            "text_extraction": {"source": "official", "backend": "moj_law_json"},
        },
        extra_fields={
            "canonical_title": title,
            "aliases": aliases,
            "citation": f"{title}（{pcode}）" if language != "en" else f"{title} ({pcode})",
            "effective_date": roc_date(law.get("LawEffectiveDate")),
            "publication_date": date,
            "status_source": "moj_lawabandonnote",
            "status_confidence": "high",
            "status_note": abandon or None,
        },
    )
    rec["id"] = rid
    rec["languages"] = [language]
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def ingest_dump(lang: str, kind: str, done: set[str]) -> tuple[int, int, int, int]:
    key = (lang, kind)
    dest = ROOT / CC / "raw" / ZIP_NAME[key]
    if not download_zip(API[key], dest):
        return 0, 0, 0, 0
    data = load_zip_json(dest)
    laws = data.get("Laws") or []
    log.info("dump %s/%s laws=%s update=%s", lang, kind, len(laws), data.get("UpdateDate"))
    ok = skip = fail = 0
    for i, law in enumerate(laws, 1):
        try:
            st = record_one(law, lang=lang, kind=kind, done=done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"status": "failed", "reason": repr(exc), "kind": kind, "lang": lang})
        ok += st == "ok"
        skip += st == "skip"
        fail += st == "fail"
        if i % 500 == 0 or i == len(laws):
            log.info("progress %s/%s %s/%s ok=%s skip=%s fail=%s", i, len(laws), lang, kind, ok, skip, fail)
    return len(laws), ok, skip, fail


def main():
    setup()
    t0 = utcnow()
    done = existing_ids(CC)
    totals = {"discovered": 0, "ok": 0, "skip": 0, "fail": 0}
    # 法律 first (incl. 憲法 in the law dump), then 命令. Chinese then official English rows.
    order = [("ch", "law"), ("en", "law"), ("ch", "order"), ("en", "order")]
    for lang, kind in order:
        n, ok, skip, fail = ingest_dump(lang, kind, done)
        totals["discovered"] += n
        totals["ok"] += ok
        totals["skip"] += skip
        totals["fail"] += fail
        write_summary(
            CC, country=COUNTRY,
            source="全國法規資料庫 Open API (Ministry of Justice)",
            source_urls=[PORTAL, SWAGGER, API[("ch", "law")], API[("en", "law")],
                         API[("ch", "order")], API[("en", "order")]],
            license_text=LICENSE, discovered=totals["discovered"], fetched=totals["ok"],
            skipped=totals["skip"], failed=totals["fail"],
            coverage="catalog-backed incomplete",
            notes="法律 then 命令; official English extra rows. Live Open API ZIP/JSON.",
            last_run=utcnow(),
        )
    coverage = "full" if totals["fail"] == 0 and totals["discovered"] else "catalog-backed incomplete"
    notes = (
        "Official MOJ Open API ZIP/JSON (Ch/En Law then Ch/En Order). "
        "憲法+法律 first, then 命令. English rows are official MOJ translations "
        f"(extra language rows, id suffix -en). Live vs archive mix: live={STATS['live']} "
        f"archive={STATS['archive']} fail={STATS['fail']}. robots.txt Disallow:/ honoured "
        f"(no HTML scrape). Authentic 總統府公報 / 行政院公報 prevails. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="全國法規資料庫 Open API (Ministry of Justice)",
        source_urls=[PORTAL, SWAGGER, API[("ch", "law")], API[("en", "law")],
                     API[("ch", "order")], API[("en", "order")]],
        license_text=LICENSE, discovered=totals["discovered"], fetched=totals["ok"],
        skipped=totals["skip"], failed=totals["fail"], coverage=coverage, notes=notes,
        last_run=utcnow(), extra=f"started {t0} live={STATS['live']} archive={STATS['archive']}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        **totals, "coverage": coverage, "live": STATS["live"], "archive": STATS["archive"],
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done %s coverage=%s", totals, coverage)


if __name__ == "__main__":
    main()

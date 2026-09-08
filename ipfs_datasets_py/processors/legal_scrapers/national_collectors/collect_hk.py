#!/usr/bin/env python3
"""Hong Kong: in-force Ordinances from Hong Kong e-Legislation (Department of Justice).

Official only:
  https://www.elegislation.gov.hk
  PSI list JSON: https://resource.data.one.gov.hk/doj/data/hkel_list_c_all_{en,zh-Hant}.json
  PSI XML zips (DoJ / data.gov.hk current legislation):
    https://resource.data.one.gov.hk/doj/data/hkel_c_leg_cap_*_{en,zh-Hant}.zip
  FAQ: machine-readable XML via data.gov.hk PSI portal.

Ordinances (LegislationType=O) only — not every subsidiary cap.
Bilingual EN / zh-Hant official extra language rows.
Does not scrape e-legislation HTML (robots.txt Disallow:/ for generic UA;
site uses checkconfig). Does not use BLIS unofficial mirrors.
No Westlaw/Lexis. No Cloudflare browser rendering. No HF upload.
"""
from __future__ import annotations

import hashlib
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

CC = "hk"
COUNTRY = "Hong Kong"
SOURCE_TYPE = "hkel_xml"
LICENSE = (
    "HKSAR official texts from Hong Kong e-Legislation (Department of Justice) "
    "/ data.gov.hk PSI. DoJ terms apply. Authentic e-Legislation (verified copy "
    "under Cap. 614) prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.elegislation.gov.hk/"
PORTAL = "https://www.elegislation.gov.hk/"
LIST_EN = "https://resource.data.one.gov.hk/doj/data/hkel_list_c_all_en.json"
LIST_ZH = "https://resource.data.one.gov.hk/doj/data/hkel_list_c_all_zh-Hant.json"
NS = "http://www.xml.gov.hk/schemas/hklm/1.0"
SKIP_TAGS = {"meta"}
BLOCK_TAGS = {
    "section", "subsection", "paragraph", "subparagraph", "part", "division",
    "subdivision", "chapter", "schedule", "longtitle", "enactingformula",
    "commencementnote", "heading", "subheading", "crossheading", "content",
    "def", "text", "leadin",
}
log = logging.getLogger("hk")
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


def zip_base(name: str) -> str:
    return name.replace("\\", "/").split("/")[-1]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: Path, expect_sha: Optional[str] = None, min_bytes: int = 1000) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size >= min_bytes:
        if dest.suffix == ".zip" and not zipfile.is_zipfile(dest):
            log.warning("removing bad zip %s", dest)
            dest.unlink()
        else:
            if expect_sha:
                got = sha256_file(dest).upper()
                if got != expect_sha.upper():
                    log.warning("sha mismatch %s got=%s expect=%s — redownload", dest.name, got, expect_sha)
                    dest.unlink()
                else:
                    log.info("present %s bytes=%s sha_ok", dest.name, dest.stat().st_size)
                    return True
            else:
                log.info("present %s bytes=%s", dest.name, dest.stat().st_size)
                return True
    tmp = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(1, 6):
        try:
            log.info("GET %s attempt=%s -> %s", url, attempt, dest.name)
            r = get_session(UA).get(url, timeout=(30, 600), stream=True)
            if r.status_code in (403, 429) or (
                r.status_code == 200 and af.is_challenge((r.text[:2000] if "text" in (r.headers.get("content-type") or "") else ""), r.status_code)
            ):
                log.info("live HTTP %s %s — archive fallback of official URL", r.status_code, url)
                res = af.fetch_with_fallbacks(url, try_archive_is=True, try_http=False, try_cc=True)
                if res.get("status") == "success" and res.get("content"):
                    tmp.write_bytes(res["content"])
                    if tmp.stat().st_size >= min_bytes:
                        tmp.replace(dest)
                        STATS["archive"] += 1
                        log.info("archive %s bytes=%s via %s", dest.name, dest.stat().st_size, res.get("method"))
                        return True
                last = f"http_{r.status_code}"
                continue
            if r.status_code != 200:
                last = f"http_{r.status_code}"
                log.warning("HTTP %s %s", r.status_code, url)
                continue
            n = 0
            with tmp.open("wb") as handle:
                for chunk in r.iter_content(1 << 16):
                    if chunk:
                        handle.write(chunk)
                        n += len(chunk)
                        if n % (50 << 20) == 0:
                            log.info("  %s MiB", n // (1 << 20))
            cl = r.headers.get("Content-Length")
            if cl and int(cl) != n:
                last = f"size {n} vs {cl}"
                log.warning("size mismatch %s", last)
                continue
            if n < min_bytes:
                last = f"too_small {n}"
                continue
            if dest.suffix == ".zip" and tmp.read_bytes()[:2] != b"PK":
                last = "not_zip"
                continue
            tmp.replace(dest)
            if expect_sha:
                got = sha256_file(dest).upper()
                if got != expect_sha.upper():
                    last = f"sha {got} vs {expect_sha}"
                    log.warning("sha mismatch after download %s", last)
                    dest.unlink()
                    continue
            STATS["live"] += 1
            log.info("downloaded %s bytes=%s", dest.name, dest.stat().st_size)
            return True
        except Exception as exc:
            last = repr(exc)
            log.warning("download fail %s: %s", url, exc)
    log.error("failed %s last=%s", url, last)
    STATS["fail"] += 1
    return False


def version_info(ch: dict) -> dict:
    vers = ch.get("Version") or []
    if isinstance(vers, dict):
        vers = [vers]
    v = vers[0] if vers else {}
    vd = v.get("VersionDate") or {}
    if not isinstance(vd, dict):
        vd = {"value": vd}
    return {
        "web": v.get("Web") or "",
        "file": v.get("FileName") or "",
        "loc": v.get("FileLocation") or "",
        "zip": v.get("DataResourceUrl") or "",
        "date": (vd.get("value") or "")[:10] or None,
        "status": vd.get("statusCategory") or "",
        "is_current": vd.get("isCurrentVersion"),
        "status_code": vd.get("statusCode"),
    }


def load_list(path: Path, lang: str) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    title_key = "ChapterTitleEnglish" if lang == "en" else "ChapterTitleTraditionalChinese"
    items = []
    for ch in data.get("Chapter") or []:
        if (ch.get("LegislationType") or "").strip() != "O":
            continue
        cap = str(ch.get("CapNo") or "").strip()
        if not cap:
            continue
        vi = version_info(ch)
        items.append({
            "cap": cap,
            "title": (ch.get(title_key) or "").strip(),
            "display": ch.get("CapNoDisplay"),
            "lang": lang,
            **vi,
        })
    return items


def extract_from_zip(zpath: Path, wanted: dict[str, dict], lang: str) -> int:
    """Extract ordinance XMLs whose basename is in wanted (keyed by FileName)."""
    out_dir = ROOT / CC / "raw" / "xml" / lang
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(zpath) as z:
        for member in z.namelist():
            bn = zip_base(member)
            if bn not in wanted:
                continue
            dest = out_dir / bn
            if dest.exists() and dest.stat().st_size > 40:
                n += 1
                continue
            try:
                dest.write_bytes(z.read(member))
                n += 1
            except Exception as exc:
                log.warning("extract %s: %s", member, exc)
    log.info("extracted %s ordinance xml from %s", n, zpath.name)
    return n


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(el: ET.Element, tagname: str) -> str:
    for child in list(el):
        if local(child.tag) == tagname:
            return "".join(child.itertext()).strip()
    return ""


def element_text(el: ET.Element) -> str:
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        tag = local(node.tag)
        if tag in SKIP_TAGS:
            return
        if node.text and node.text.strip():
            parts.append(node.text.strip())
        for child in list(node):
            walk(child)
            if child.tail and child.tail.strip():
                parts.append(child.tail.strip())
        if tag in BLOCK_TAGS:
            parts.append("\n")

    walk(el)
    text = " ".join(parts)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_root(raw: str) -> Optional[ET.Element]:
    raw = re.sub(r"<!DOCTYPE[^>]*>", "", raw, count=1)
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        try:
            return ET.fromstring(raw.encode("utf-8"))
        except Exception:
            return None


def find_main(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if local(el.tag) == "main":
            return el
    return root


def extract_sections(root: ET.Element, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs: list[dict] = []
    seen: set[str] = set()
    path: list[str] = []

    def emit(el: ET.Element, zone: str) -> None:
        num = child_text(el, "num") or el.attrib.get("name") or ""
        heading = child_text(el, "heading")
        text = element_text(el)
        if not text or len(text) < 4:
            return
        display = " ".join(x for x in (num, heading) if x).strip() or num or zone
        num_m = re.search(r"(\d+[A-Za-z]?)", num or "")
        slug_src = num_m.group(1) if num_m else (num or f"a{len(docs)+1}")
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug_src).strip("-").lower() or f"a{len(docs)+1}"
        prefix = "sch-" if zone == "schedule" else "s"
        doc_id = f"{law_id}-{prefix}{slug}"[:180]
        if doc_id in seen:
            doc_id = f"{doc_id}-{len(docs)+1}"[:180]
        seen.add(doc_id)
        docs.append({
            "id": doc_id,
            "title": display[:500],
            "text": text,
            "date_filed": date,
            "document_number": num or None,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num or None,
            "article_heading": heading or display,
            "law_identifier": law_id,
            "hierarchy_path_text": " / ".join(path),
            "metadata": {
                "text_extraction": {"source": "official", "backend": "hkel_xml_section"},
                "unit": local(el.tag),
                "zone": zone,
            },
        })

    def walk(el: ET.Element, zone: str) -> None:
        tag = local(el.tag)
        if tag == "meta":
            return
        pushed = False
        if tag in {"part", "division", "subdivision", "chapter", "subpart"}:
            label = " ".join(x for x in (child_text(el, "num"), child_text(el, "heading")) if x).strip()
            if label:
                path.append(label)
                pushed = True
        nxt_zone = zone
        if tag == "schedule":
            nxt_zone = "schedule"
            emit(el, "schedule")
            # still walk nested sections
        if tag == "section":
            emit(el, nxt_zone)
            if pushed:
                path.pop()
            return
        for child in list(el):
            if len(docs) >= 8000:
                break
            walk(child, nxt_zone)
        if pushed:
            path.pop()

    walk(root, "main")
    return docs


def status_from(cat: str) -> tuple[str, bool]:
    cat = (cat or "").strip()
    if cat in {"NoLongerInEffect", "Repealed"}:
        return "repealed", False
    if cat in {"NotYetInEffect"}:
        return "current", False
    return "current", True


def record_one(it: dict, xml_path: Path, done: set[str]) -> str:
    cap = it["cap"]
    lang = it["lang"]
    ident = f"cap{cap}-{lang}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    raw = xml_path.read_text(encoding="utf-8", errors="replace")
    root = parse_root(raw)
    if root is None:
        log_failure(CC, {"identifier": ident, "source_url": it.get("web"), "status": "failed", "reason": "xml_parse"})
        return "fail"
    main = find_main(root)
    title = it.get("title") or ""
    for el in root.iter():
        if local(el.tag) == "docname" and not title:
            title = "".join(el.itertext()).strip()
        if local(el.tag) == "shorttitle" and not title:
            title = "".join(el.itertext()).strip()
    if not title:
        title = f"Cap. {cap}"
    date = it.get("date")
    if date and len(date) >= 10:
        date = date[:10]
    else:
        date = iso_date(date)
    source_url = it.get("web") or f"https://www.elegislation.gov.hk/hk/cap{cap}!{'en' if lang=='en' else 'zh-Hant-HK'}"
    language = "en" if lang == "en" else "zh-Hant"
    text = element_text(main)
    if not text or len(text) < 8:
        text = element_text(root)
    if not text or len(text) < 8:
        log_failure(CC, {"identifier": ident, "source_url": source_url, "status": "failed", "reason": "empty_text"})
        return "fail"
    docs = extract_sections(root, rid, source_url, date)
    law_status, is_current = status_from(it.get("status") or "")
    rec = base_record(
        cc=CC, country=COUNTRY, language=language, ident=ident,
        title=title, text=text, source_url=source_url, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="hk-hkel-xml",
        eli=None, date=date, official_identifier=f"Cap. {cap}",
        document_type="ordinance", law_status=law_status, is_current=is_current,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": "hkel_psi_list_json_plus_xml_zip",
                "catalog_identifier": cap,
                "seed_url": LIST_EN if lang == "en" else LIST_ZH,
                "retrieval": "live",
                "xml_file": xml_path.name,
                "zip_url": it.get("zip"),
            },
            "official_metadata": {
                "cap_no": cap,
                "cap_display": it.get("display"),
                "legislation_type": "O",
                "status_category": it.get("status"),
                "file_name": it.get("file"),
                "file_location": it.get("loc"),
            },
            "text_extraction": {"source": "official", "backend": "hkel_xml"},
        },
        extra_fields={
            "canonical_title": title,
            "citation": f"{title} (Cap. {cap})" if language == "en" else f"{title}（第{cap}章）",
            "status_source": "hkel_list_statusCategory",
            "status_confidence": "high",
            "canonical_document_url": source_url,
        },
    )
    rec["id"] = rid
    rec["languages"] = [language]
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def process_lang(lang: str, list_url: str, list_name: str, done: set[str]) -> tuple[int, int, int, int]:
    list_path = ROOT / CC / "raw" / list_name
    if not download_file(list_url, list_path, min_bytes=10_000):
        log.error("cannot fetch list %s", list_url)
        return 0, 0, 0, 0
    items = load_list(list_path, lang)
    log.info("%s ordinances in list=%s", lang, len(items))
    by_zip: dict[str, list[dict]] = {}
    for it in items:
        zurl = it.get("zip") or ""
        if not zurl:
            continue
        by_zip.setdefault(zurl, []).append(it)
    xml_dir = ROOT / CC / "raw" / "xml" / lang
    xml_dir.mkdir(parents=True, exist_ok=True)
    for zurl, group in by_zip.items():
        zname = zurl.rstrip("/").split("/")[-1]
        zpath = ROOT / CC / "raw" / zname
        wanted = {it["file"]: it for it in group if it.get("file")}
        missing = [fn for fn in wanted if not (xml_dir / fn).exists() or (xml_dir / fn).stat().st_size < 40]
        if not missing:
            log.info("xml already extracted for %s (%s files)", zname, len(wanted))
            continue
        if not download_file(zurl, zpath, min_bytes=1_000_000):
            log.error("zip failed %s", zurl)
            continue
        extract_from_zip(zpath, wanted, lang)
        try:
            zpath.unlink()
            log.info("removed zip %s after extract", zname)
        except OSError:
            pass
    ok = skip = fail = 0
    for i, it in enumerate(items, 1):
        xml_path = xml_dir / (it.get("file") or "")
        if not xml_path.exists() or xml_path.stat().st_size < 40:
            log_failure(CC, {
                "identifier": f"cap{it['cap']}-{lang}",
                "source_url": it.get("web"),
                "status": "failed",
                "reason": "missing_xml",
            })
            fail += 1
            continue
        try:
            st = record_one(it, xml_path, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"status": "failed", "reason": repr(exc), "cap": it.get("cap")})
        ok += st == "ok"
        skip += st == "skip"
        fail += st == "fail"
        if i % 100 == 0 or i == len(items):
            log.info("progress %s/%s %s ok=%s skip=%s fail=%s", i, len(items), lang, ok, skip, fail)
    return len(items), ok, skip, fail


def main():
    setup()
    t0 = utcnow()
    done = existing_ids(CC)
    totals = {"discovered": 0, "ok": 0, "skip": 0, "fail": 0}
    for lang, url, name in (
        ("en", LIST_EN, "hkel_list_c_all_en.json"),
        ("zh-Hant", LIST_ZH, "hkel_list_c_all_zh-Hant.json"),
    ):
        n, ok, skip, fail = process_lang(lang, url, name, done)
        totals["discovered"] += n
        totals["ok"] += ok
        totals["skip"] += skip
        totals["fail"] += fail
        write_summary(
            CC, country=COUNTRY,
            source="Hong Kong e-Legislation (Department of Justice) PSI XML",
            source_urls=[PORTAL, LIST_EN, LIST_ZH,
                         "https://data.gov.hk/en-data/dataset/hk-doj-hkel-legislation-current"],
            license_text=LICENSE, discovered=totals["discovered"], fetched=totals["ok"],
            skipped=totals["skip"], failed=totals["fail"],
            coverage="catalog-backed incomplete",
            notes="Ordinances only. EN then zh-Hant. Official PSI XML zips.",
            last_run=utcnow(),
        )
    coverage = "full" if totals["fail"] == 0 and totals["discovered"] else "catalog-backed incomplete"
    notes = (
        "Current-version Ordinances (LegislationType=O) from official HKeL PSI "
        "list JSON + XML zips on resource.data.one.gov.hk (DoJ / data.gov.hk). "
        "Subsidiary legislation and instruments excluded. Bilingual EN/zh-Hant "
        "as extra language rows. No BLIS, no e-Legislation HTML scrape "
        f"(robots.txt Disallow:/). Live vs archive mix: live={STATS['live']} "
        f"archive={STATS['archive']} fail={STATS['fail']}. Authentic e-Legislation "
        f"verified copy (Cap. 614) prevails. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Hong Kong e-Legislation (Department of Justice) PSI XML",
        source_urls=[PORTAL, LIST_EN, LIST_ZH,
                     "https://data.gov.hk/en-data/dataset/hk-doj-hkel-legislation-current"],
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

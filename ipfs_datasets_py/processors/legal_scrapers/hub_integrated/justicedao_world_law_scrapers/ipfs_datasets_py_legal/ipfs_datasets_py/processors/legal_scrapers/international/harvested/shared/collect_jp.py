#!/usr/bin/env python3
"""Japan: in-force national Acts (法律) from e-Gov 法令検索 (Digital Agency).

Primary sources (official only):
  - Portal: https://laws.e-gov.go.jp/
  - XML bulk dump (preferred): https://laws.e-gov.go.jp/bulkdownload/
    GET /bulkdownload?file_section=1&only_xml_flag=true  -> all_xml.zip
  - API v2 catalog / fallback body: https://laws.e-gov.go.jp/api/2/
    GET /laws  GET /law_data/{id}  swagger-ui

Does not use commercial Japanese law databases (Westlaw Japan, D1-Law,
Lexis, etc.). Does not git-clone any repository. Does not machine-translate.
English rows are added only if the official dump itself is Lang=en (it is not).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC = "jp"
COUNTRY = "Japan"
SOURCE_TYPE = "egov_laws_xml"
LICENSE = (
    "Official Japanese legislative texts are not copyright-protected "
    "(Copyright Act of Japan art. 13: 憲法その他の法令). e-Gov 法令検索 help Q6 "
    "(https://laws.e-gov.go.jp/help/): reuse of the provided law data is "
    "unrestricted (二次利用していただいて構いません / 特に制限を設けておりません). "
    "Site chrome may be 公共データ利用規約 PDL 1.0. Not legal advice; 官報 and "
    "e-Gov authentic text prevail."
)
UA = DEFAULT_UA + " source=https://laws.e-gov.go.jp/"
WORKERS = 6
SLEEP = 0.35
ASOF = "2026-09-02"
BULK_URL = "https://laws.e-gov.go.jp/bulkdownload?file_section=1&only_xml_flag=true"
API_LAWS = "https://laws.e-gov.go.jp/api/2/laws"
API_LAW_DATA = "https://laws.e-gov.go.jp/api/2/law_data/"
PORTAL = "https://laws.e-gov.go.jp/"
HELP_URL = "https://laws.e-gov.go.jp/help/"
SWAGGER = "https://laws.e-gov.go.jp/api/2/swagger-ui/"
log = logging.getLogger("jp")

SKIP_TEXT_TAGS = {
    "toc", "tocchapter", "tocsection", "tocsubsection", "tocdivision",
    "tocarticle", "tocsupplprovision", "tocappdx", "tocappdxtable",
    "toclabel", "tocitem",
    "fig", "rt",  # skip furigana readings; keep Ruby base text
}
BLOCK_TAGS = {
    "article", "paragraph", "item", "subitem1", "subitem2", "subitem3",
    "chapter", "section", "subsection", "division", "part",
    "supplprovision", "appdxtable", "appdxstyle", "appdxnote", "appdxfig",
    "appdxformat", "preamble", "enactstatement", "lawtitle", "articletitle",
    "articlecaption", "chaptertitle", "sectiontitle", "parttitle",
    "subsectiontitle", "divisiontitle", "paragraphtitle",
}


def setup():
    ensure_dirs(CC)
    (ROOT / CC / "raw").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def law_url(law_id: str, revision_id: Optional[str] = None) -> str:
    if revision_id and "_" in revision_id:
        # revision_id is {law_id}_{YYYYMMDD}_{amendment_id}
        parts = revision_id.split("_", 1)
        if len(parts) == 2 and parts[0] == law_id:
            return f"https://laws.e-gov.go.jp/law/{law_id}/{parts[1]}"
    return f"https://laws.e-gov.go.jp/law/{law_id}"


def zip_ok(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1_000_000:
        return False
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
        return any(n.endswith(".xml") for n in names[:200]) or any(
            n.endswith(".xml") for n in names
        )
    except zipfile.BadZipFile:
        return False


def download_bulk(dest: Path) -> Optional[Path]:
    if zip_ok(dest):
        log.info("bulk zip present %s bytes=%s", dest, dest.stat().st_size)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        log.warning("removing incomplete zip %s bytes=%s", dest, dest.stat().st_size)
        dest.unlink()
    log.info("downloading bulk XML %s -> %s", BULK_URL, dest)
    try:
        subprocess.run(
            [
                "curl", "-L", "--fail", "--retry", "5", "--retry-delay", "8",
                "--retry-all-errors", "-A", UA, "-o", str(dest), BULK_URL,
            ],
            check=True, timeout=1800,
        )
        if zip_ok(dest):
            log.info("bulk zip downloaded bytes=%s", dest.stat().st_size)
            return dest
        log.warning("curl finished but zip invalid bytes=%s", dest.stat().st_size if dest.exists() else 0)
    except Exception as exc:
        log.warning("curl bulk download failed: %s", exc)
    # requests fallback
    try:
        r = get_session(UA).get(BULK_URL, timeout=(30, 600), stream=True)
        if r.status_code != 200:
            log.warning("bulk GET status=%s", r.status_code)
            return None
        n = 0
        with dest.open("wb") as handle:
            for chunk in r.iter_content(1 << 16):
                if chunk:
                    handle.write(chunk)
                    n += len(chunk)
                    if n % (20 << 20) == 0:
                        log.info("bulk downloaded %s MiB", n // (1 << 20))
        if zip_ok(dest):
            log.info("bulk zip via requests bytes=%s", dest.stat().st_size)
            return dest
    except Exception as exc:
        log.warning("requests bulk download failed: %s", exc)
    return dest if zip_ok(dest) else None


def category_zips() -> list[Path]:
    """Fallback: download XML-only per 法令分類 if the all-in-one zip fails."""
    out: list[Path] = []
    raw = ROOT / CC / "raw" / "categories"
    raw.mkdir(parents=True, exist_ok=True)
    for cd in range(1, 51):
        dest = raw / f"{cd}_xml.zip"
        if zip_ok(dest):
            out.append(dest)
            continue
        url = f"https://laws.e-gov.go.jp/bulkdownload?file_section=2&category_cd={cd}&only_xml_flag=true"
        log.info("category zip cd=%s", cd)
        try:
            r = http_get(url, ua=UA, sleep=0.4, timeout=(20, 300), retries=4,
                         headers={"Accept": "application/octet-stream, */*"})
            if r.status_code == 200 and r.content[:2] == b"PK":
                dest.write_bytes(r.content)
                if zip_ok(dest):
                    out.append(dest)
                    continue
            log.warning("category %s status=%s bytes=%s", cd, r.status_code, len(r.content or b""))
        except Exception as exc:
            log.warning("category %s failed: %s", cd, exc)
    return out


def index_zip(path: Path) -> dict[str, tuple[Path, str]]:
    """Map law_revision_id / file stem -> (zip_path, member_name)."""
    idx: dict[str, tuple[Path, str]] = {}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.endswith(".xml"):
                continue
            stem = Path(name).stem
            idx[stem] = (path, name)
    return idx


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

    seen: set[str] = set()
    offset = 0
    limit = 500
    total = None
    while True:
        params = {
            "law_type": "Act",
            "repeal_status": "None",
            "asof": ASOF,
            "limit": limit,
            "offset": offset,
            "response_format": "json",
        }
        r = http_get(API_LAWS, ua=UA, sleep=SLEEP, params=params, timeout=(20, 90), retries=5)
        if r.status_code != 200:
            log.warning("API /laws status=%s offset=%s body=%s", r.status_code, offset, r.text[:300])
            break
        data = r.json()
        if total is None:
            total = data.get("total_count")
            log.info("API /laws total_count=%s", total)
        laws = data.get("laws") or []
        if not laws:
            break
        newc = 0
        for row in laws:
            info = row.get("law_info") or {}
            rev = row.get("revision_info") or {}
            cur = row.get("current_revision_info") or {}
            law_id = (info.get("law_id") or "").strip()
            if not law_id or law_id in seen:
                continue
            # Prefer the as-of revision; fall back to current enforced.
            use = rev or cur
            status = (use.get("current_revision_status") or "").strip()
            if status and status not in ("CurrentEnforced", "Current"):
                # Still in-force as of ASOF if repeal_status is None; keep unless
                # explicitly repealed. Future-only revisions are not CurrentEnforced.
                if status not in ("CurrentEnforced",):
                    # Keep CurrentNotEnforced only if asof revision is the one returned.
                    pass
            seen.add(law_id)
            rec = {
                "law_id": law_id,
                "law_type": info.get("law_type") or use.get("law_type") or "Act",
                "law_num": info.get("law_num"),
                "promulgation_date": iso_date(info.get("promulgation_date")),
                "law_revision_id": use.get("law_revision_id") or cur.get("law_revision_id"),
                "law_title": use.get("law_title") or cur.get("law_title"),
                "law_title_kana": use.get("law_title_kana"),
                "abbrev": use.get("abbrev"),
                "category": use.get("category"),
                "amendment_enforcement_date": iso_date(use.get("amendment_enforcement_date")),
                "amendment_promulgate_date": iso_date(use.get("amendment_promulgate_date")),
                "repeal_status": use.get("repeal_status") or "None",
                "current_revision_status": use.get("current_revision_status"),
                "updated": use.get("updated"),
            }
            items.append(rec)
            append_catalog(CC, rec)
            newc += 1
        log.info("catalog offset=%s new=%s total_items=%s page=%s", offset, newc, len(items), len(laws))
        nxt = data.get("next_offset")
        if nxt is None or nxt == offset or not laws:
            offset += len(laws)
        else:
            offset = nxt
        if total is not None and len(items) >= int(total):
            break
        if len(laws) < limit:
            break
        if offset > 20000:
            break
    log.info("catalog discovered %s (api total_count=%s)", len(items), total)
    return items


def parse_root(raw: str) -> Optional[ET.Element]:
    raw = re.sub(r"<!DOCTYPE[^>]*>", "", raw, count=1)
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        try:
            return ET.fromstring(raw.encode("utf-8"))
        except Exception:
            return None


def find_law_element(root: ET.Element) -> ET.Element:
    tag = localtag(root.tag)
    if tag == "Law":
        return root
    for el in root.iter():
        if localtag(el.tag) == "Law":
            return el
    return root


def element_text(el: ET.Element) -> str:
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        tag = localtag(node.tag).lower()
        if tag in SKIP_TEXT_TAGS:
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


def child_text(el: ET.Element, tagname: str) -> str:
    for child in list(el):
        if localtag(child.tag) == tagname:
            return "".join(child.itertext()).strip()
    return ""


def law_full_text(law_el: ET.Element) -> str:
    chunks: list[str] = []
    for child in list(law_el):
        tag = localtag(child.tag)
        if tag == "LawNum":
            t = "".join(child.itertext()).strip()
            if t:
                chunks.append(t)
        elif tag == "LawBody":
            for part in list(child):
                ptag = localtag(part.tag)
                if ptag in {"TOC"}:
                    continue
                t = element_text(part)
                if t:
                    chunks.append(t)
        elif tag not in {"TOC"}:
            t = element_text(child)
            if t:
                chunks.append(t)
    text = "\n\n".join(c for c in chunks if c)
    if not text:
        text = element_text(law_el)
    return text


def extract_articles(law_el: ET.Element, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs: list[dict] = []
    seen: set[str] = set()

    def walk(el: ET.Element, path: list[dict], zone: str) -> None:
        tag = localtag(el.tag)
        if tag == "TOC":
            return
        nxt_zone = zone
        nxt_path = path
        if tag == "SupplProvision":
            nxt_zone = "suppl"
            label = child_text(el, "SupplProvisionLabel") or "附則"
            nxt_path = path + [{"kind": "suppl_provision", "label": label}]
        elif tag in {"Part", "Chapter", "Section", "Subsection", "Division"}:
            title = (
                child_text(el, tag + "Title")
                or child_text(el, "ChapterTitle")
                or ""
            )
            nxt_path = path + [{"kind": tag.lower(), "label": title or tag, "number": el.attrib.get("Num")}]
        elif tag.startswith("Appdx"):
            nxt_zone = "appdx"
            title = child_text(el, tag + "Title") or tag
            nxt_path = path + [{"kind": tag.lower(), "label": title}]
        if tag == "Article":
            num = (el.attrib.get("Num") or "").strip()
            title_el = child_text(el, "ArticleTitle")
            caption = child_text(el, "ArticleCaption")
            text = element_text(el)
            if not text or len(text) < 4:
                return
            display_num = title_el or (f"第{num}条" if num else "")
            heading = " ".join(x for x in (display_num, caption) if x).strip() or display_num or "条"
            slug_src = num or display_num or f"a{len(docs)+1}"
            slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug_src).strip("-").lower() or f"a{len(docs)+1}"
            prefix = "suppl-" if nxt_zone == "suppl" else ("appdx-" if nxt_zone == "appdx" else "")
            doc_id = f"{law_id}-{prefix}art-{slug}"[:180]
            if doc_id in seen:
                doc_id = f"{doc_id}-{len(docs)+1}"[:180]
            seen.add(doc_id)
            docs.append({
                "id": doc_id,
                "title": heading[:500],
                "text": text,
                "date_filed": date,
                "document_number": display_num or num or None,
                "source_url": source_url,
                "record_type": "article",
                "article_number": display_num or num or None,
                "article_heading": caption or heading,
                "law_identifier": law_id,
                "hierarchy_path": nxt_path,
                "hierarchy_path_text": " / ".join(p.get("label") or "" for p in nxt_path if p.get("label")),
                "metadata": {
                    "text_extraction": {"source": "official", "backend": "egov_law_xml_article"},
                    "unit": "article",
                    "zone": nxt_zone,
                    "num": num or None,
                    "article_caption": caption or None,
                },
            })
            if len(docs) >= 8000:
                return
            return  # do not recurse into Article children for nested Article
        for child in list(el):
            if len(docs) >= 8000:
                return
            walk(child, nxt_path, nxt_zone)

    walk(law_el, [], "main")
    return docs


_xml_cache = ROOT / CC / "raw" / "xml"


def extract_needed(items: list[dict], xml_index: dict[str, tuple[Path, str]]) -> int:
    """Extract catalog revision XML out of the bulk zip once (thread-safe later)."""
    _xml_cache.mkdir(parents=True, exist_ok=True)
    n = 0
    missing = 0
    # group members by zip path
    by_zip: dict[Path, list[tuple[str, str]]] = {}
    for it in items:
        rev = (it.get("law_revision_id") or "").strip()
        law_id = (it.get("law_id") or "").strip()
        key = rev if rev in xml_index else (law_id if law_id in xml_index else None)
        if not key:
            missing += 1
            continue
        dest = _xml_cache / f"{key}.xml"
        if dest.exists() and dest.stat().st_size > 40:
            n += 1
            continue
        zpath, member = xml_index[key]
        by_zip.setdefault(zpath, []).append((key, member))
    for zpath, pairs in by_zip.items():
        log.info("extracting %s members from %s", len(pairs), zpath.name)
        with zipfile.ZipFile(zpath) as z:
            for key, member in pairs:
                dest = _xml_cache / f"{key}.xml"
                try:
                    dest.write_bytes(z.read(member))
                    n += 1
                except Exception as exc:
                    log.warning("extract %s: %s", member, exc)
                    missing += 1
    log.info("extracted xml cache=%s missing_from_zip=%s", n, missing)
    return n


def read_zip_member(zpath: Path, member: str) -> Optional[str]:
    try:
        with zipfile.ZipFile(zpath) as z:
            raw = z.read(member)
        return raw.decode("utf-8", errors="replace")
    except Exception as exc:
        log.warning("zip read %s %s: %s", zpath, member, exc)
        return None


def read_xml_cache(rev: str, law_id: str) -> Optional[tuple[str, str]]:
    for key in (rev, law_id):
        if not key:
            continue
        p = _xml_cache / f"{key}.xml"
        if p.exists() and p.stat().st_size > 40:
            return p.read_text(encoding="utf-8", errors="replace"), str(p)
    return None


def fetch_api_xml(law_id: str) -> Optional[str]:
    url = API_LAW_DATA + law_id
    r = http_get(
        url, ua=UA, sleep=SLEEP, timeout=(20, 180), retries=4,
        params={"response_format": "xml"},
        headers={"Accept": "application/xml, text/xml, */*"},
    )
    if r.status_code != 200 or not r.content or len(r.content) < 40:
        return None
    return r.content.decode("utf-8", errors="replace")


def record_id(law_id: str) -> str:
    return slug_id(CC, law_id)


def fetch_one(it: dict, done: set[str], xml_index: dict[str, tuple[Path, str]]) -> str:
    law_id = (it.get("law_id") or "").strip()
    if not law_id:
        return "fail"
    rid = record_id(law_id)
    if rid in done:
        return "skip"
    rev = (it.get("law_revision_id") or "").strip()
    raw = None
    src_path = None
    cached = read_xml_cache(rev, law_id)
    if cached:
        raw, src_path = cached
    if not raw and rev and rev in xml_index:
        zpath, member = xml_index[rev]
        raw = read_zip_member(zpath, member)
        src_path = f"{zpath.name}:{member}"
    if not raw and law_id in xml_index:
        zpath, member = xml_index[law_id]
        raw = read_zip_member(zpath, member)
        src_path = f"{zpath.name}:{member}"
    if not raw:
        raw = fetch_api_xml(law_id)
        if raw:
            src_path = API_LAW_DATA + law_id
    if not raw:
        log_failure(CC, {
            "identifier": law_id,
            "source_url": law_url(law_id, rev),
            "status": "failed",
            "reason": "missing_xml",
            "law_revision_id": rev,
        })
        return "fail"
    root = parse_root(raw)
    if root is None:
        log_failure(CC, {
            "identifier": law_id,
            "source_url": law_url(law_id, rev),
            "status": "failed",
            "reason": "xml_parse_error",
        })
        return "fail"
    law_el = find_law_element(root)
    lang = (law_el.attrib.get("Lang") or "ja").strip().lower()
    if lang not in {"ja", "en"}:
        lang = "ja"
    title = (
        it.get("law_title")
        or child_text(next((c for c in law_el.iter() if localtag(c.tag) == "LawBody"), law_el), "LawTitle")
        or it.get("law_num")
        or law_id
    )
    # LawTitle is nested in LawBody
    for el in law_el.iter():
        if localtag(el.tag) == "LawTitle":
            t = "".join(el.itertext()).strip()
            if t:
                title = t
            break
    text = law_full_text(law_el)
    if not text or len(text) < 8:
        text = element_text(law_el)
    if not text or len(text) < 8:
        log_failure(CC, {
            "identifier": law_id,
            "source_url": law_url(law_id, rev),
            "status": "failed",
            "reason": "empty_text",
        })
        return "fail"
    official = it.get("law_num") or law_id
    date = it.get("amendment_enforcement_date") or it.get("promulgation_date")
    source_url = law_url(law_id, rev)
    docs = extract_articles(law_el, rid, source_url, date)
    aliases = []
    if it.get("abbrev"):
        aliases.append(it["abbrev"])
    rec = base_record(
        cc=CC, country=COUNTRY, language=lang, ident=law_id,
        title=title, text=text, source_url=source_url, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="jp-egov-laws-xml",
        eli=None, date=date, official_identifier=official,
        document_type="statute", law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": "egov_api_v2_laws_plus_bulk_xml",
                "catalog_identifier": law_id,
                "seed_url": API_LAWS,
                "bulk_member": src_path,
                "asof": ASOF,
            },
            "official_metadata": {
                "law_id": law_id,
                "law_type": it.get("law_type"),
                "law_num": it.get("law_num"),
                "law_revision_id": rev,
                "law_title_kana": it.get("law_title_kana"),
                "abbrev": it.get("abbrev"),
                "category": it.get("category"),
                "promulgation_date": it.get("promulgation_date"),
                "amendment_enforcement_date": it.get("amendment_enforcement_date"),
                "current_revision_status": it.get("current_revision_status"),
                "xml_lang": lang,
            },
        },
        extra_fields={
            "canonical_title": title,
            "aliases": aliases,
            "citation": f"{title}（{official}）" if official and official not in (title or "") else title,
            "publication_date": it.get("promulgation_date"),
            "effective_date": it.get("amendment_enforcement_date") or date,
            "valid_from": it.get("amendment_enforcement_date"),
            "last_modified_date": iso_date((it.get("updated") or "")[:10]) if it.get("updated") else None,
            "version_specific_identifier": rev or None,
            "law_version_identifier": rev or None,
            "canonical_document_url": source_url,
            "status_source": "egov_api_v2_repeal_status_None_asof",
            "status_confidence": "high",
        },
    )
    rec["id"] = rid
    rec["languages"] = [lang]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    dest = ROOT / CC / "raw" / "all_xml.zip"
    bulk = download_bulk(dest)
    xml_index: dict[str, tuple[Path, str]] = {}
    if bulk:
        xml_index.update(index_zip(bulk))
        log.info("bulk xml members indexed=%s", len(xml_index))
    else:
        log.warning("all_xml.zip unavailable; trying per-category zips")
        for cz in category_zips():
            xml_index.update(index_zip(cz))
        log.info("category xml members indexed=%s", len(xml_index))
    if xml_index:
        extract_needed(items, xml_index)
    else:
        log.warning("no bulk XML; will fetch each Act via API v2 /law_data")

    done = existing_ids(CC)
    ok = skip = fail = 0
    log.info("queue acts=%s already_done=%s indexed_xml=%s", len(items), len(done), len(xml_index))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, it, done, xml_index) for it in items]
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
            if n % 200 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY,
                    source="e-Gov 法令検索 (Digital Agency) XML bulk + API v2",
                    source_urls=[PORTAL, BULK_URL, API_LAWS, HELP_URL, SWAGGER],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail,
                    coverage="catalog-backed incomplete",
                    notes="In-force national 法律 (Act) as of ASOF. Bulk XML preferred.",
                    last_run=utcnow(),
                )
    coverage = "full" if fail == 0 and ok + skip >= len(items) and items else "catalog-backed incomplete"
    notes = (
        f"In-force national Acts (法律, law_type=Act, repeal_status=None, asof={ASOF}). "
        f"Bodies from official XML bulk dump (file_section=1, only_xml_flag=true) keyed by "
        f"law_revision_id; API v2 /law_data used only for misses. Japanese only "
        f"(Lang=ja in 法令標準XML); no machine translation. Constitution, Cabinet Orders, "
        f"Imperial Orders, Ministerial Ordinances, and Rules are in the bulk dump but "
        f"out of scope for this 法律-first snapshot. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="e-Gov 法令検索 (Digital Agency) XML bulk + API v2",
        source_urls=[PORTAL, BULK_URL, "https://laws.e-gov.go.jp/bulkdownload/", API_LAWS, HELP_URL, SWAGGER],
        license_text=LICENSE, discovered=len(items), fetched=ok,
        skipped=skip, failed=fail, coverage=coverage, notes=notes,
        last_run=utcnow(), extra=f"started {t0}",
    )
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()

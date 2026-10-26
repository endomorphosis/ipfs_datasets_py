#!/usr/bin/env python3
"""Canada: Justice Laws Website consolidated Acts and Regulations (official XML).

Primary sources (Department of Justice Canada, official only):
  - Catalog: https://laws-lois.justice.gc.ca/eng/XML/Legis.xml
  - Per-instrument XML: https://laws-lois.justice.gc.ca/eng/XML/{id}.xml
    and French https://laws-lois.justice.gc.ca/fra/XML/{id}.xml
  - Bulk dump (preferred): https://github.com/justicecanada/laws-lois-xml
    (Justice Canada official repository of the same consolidations)

Does not use CanLII, Westlaw, Lexis, Quicklaw, or other commercial databases.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC = "ca"
COUNTRY = "Canada"
SOURCE_TYPE = "justice_laws_xml"
LICENSE = (
    "Crown copyright (Canada). Reproduction of federal enactments and consolidations "
    "is permitted without charge or request for permission under the Reproduction of "
    "Federal Law Order (SI/97-5), provided due diligence is exercised in ensuring the "
    "accuracy of the materials reproduced and the reproduction is not represented as an "
    "official version. See https://laws-lois.justice.gc.ca/eng/regulations/SI-97-5/FullText.html "
    "and https://laws-lois.justice.gc.ca/eng/FAQ/. The official Justice Laws Website text "
    "prevails. Not legal advice. GitHub bulk XML dump is also published under the Open "
    "Government Licence – Canada: https://open.canada.ca/en/open-government-licence-canada"
)
UA = DEFAULT_UA + " source=https://laws-lois.justice.gc.ca/"
WORKERS = 6
SLEEP = 0.3
CATALOG_URL = "https://laws-lois.justice.gc.ca/eng/XML/Legis.xml"
GITHUB_REPO = "https://github.com/justicecanada/laws-lois-xml.git"
GITHUB_PAGE = "https://github.com/justicecanada/laws-lois-xml"
log = logging.getLogger("ca")

SKIP_TEXT_TAGS = {
    "historicalnote", "historicalnotesubitem", "recentamendments", "amendment",
    "billhistory", "stages", "footnote", "footnoteref", "amendmentcitation",
    "amendmentdate",
}
BLOCK_TAGS = {
    "section", "subsection", "paragraph", "subparagraph", "clause", "subclause",
    "heading", "schedule", "text", "provision", "definition", "titletext",
    "marginalnote", "longtitle", "shorttitle", "order", "formulagroup",
}
LIMS = "http://justice.gc.ca/lims"


def setup():
    ensure_dirs(CC)
    (ROOT / CC / "raw" / "xml").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def https(url: str) -> str:
    if not url:
        return url
    if url.startswith("http://"):
        return "https://" + url[7:]
    return url


def lang_code(raw: Optional[str]) -> str:
    v = (raw or "").strip().lower()
    if v.startswith("fr") or v == "fra":
        return "fr"
    return "en"


def xml_filename(url: str) -> str:
    path = unquote(urlparse(url).path)
    return path.rsplit("/", 1)[-1]


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

    dest = ROOT / CC / "raw" / "Legis.xml"
    if not dest.exists() or dest.stat().st_size < 100_000:
        log.info("fetching catalog %s", CATALOG_URL)
        r = http_get(CATALOG_URL, ua=UA, sleep=0.2, timeout=(20, 180), retries=5)
        r.raise_for_status()
        dest.write_bytes(r.content)
    log.info("parsing catalog %s bytes=%s", dest, dest.stat().st_size)
    tree = ET.parse(dest)
    root = tree.getroot()
    seen = set()
    for kind, wrapper, child in (
        ("act", "Acts", "Act"),
        ("regulation", "Regulations", "Regulation"),
    ):
        wrap = root.find(wrapper)
        if wrap is None:
            continue
        for el in wrap:
            if localtag(el.tag) != child:
                continue
            uid = (el.findtext("UniqueId") or "").strip()
            language = (el.findtext("Language") or "").strip()
            xml_url = https((el.findtext("LinkToXML") or "").strip())
            html_url = https((el.findtext("LinkToHTMLToC") or "").strip())
            title = (el.findtext("Title") or "").strip()
            current_to = iso_date(el.findtext("CurrentToDate"))
            official = (el.findtext("OfficialNumber") or uid).strip()
            key = (kind, language, uid, xml_url)
            if not uid or not xml_url or key in seen:
                continue
            seen.add(key)
            row = {
                "kind": kind,
                "unique_id": uid,
                "language": language,
                "title": title,
                "official_number": official,
                "current_to": current_to,
                "xml_url": xml_url,
                "html_url": html_url,
                "xml_filename": xml_filename(xml_url),
                "reg_id": el.attrib.get("id"),
                "olid": el.attrib.get("olid"),
            }
            items.append(row)
            append_catalog(CC, row)
    log.info("catalog discovered %s", len(items))
    return items


def bulk_dir() -> Path:
    return ROOT / CC / "raw" / "laws-lois-xml"


def ensure_bulk_dump() -> Optional[Path]:
    """Prefer the official Justice Canada GitHub bulk XML dump over per-page fetches."""
    dest = bulk_dir()
    marker = dest / ".complete"
    if marker.exists() and (dest / "eng").is_dir() and (dest / "fra").is_dir():
        log.info("bulk dump present %s", dest)
        return dest
    log.info("cloning official bulk dump %s (sparse eng+fra, depth 1)", GITHUB_REPO)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not (dest / ".git").exists():
        # incomplete leftover
        import shutil
        shutil.rmtree(dest, ignore_errors=True)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        if not (dest / ".git").exists():
            subprocess.run(
                [
                    "git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                    GITHUB_REPO, str(dest),
                ],
                check=True, env=env, timeout=600,
            )
        subprocess.run(
            ["git", "-C", str(dest), "sparse-checkout", "set", "eng", "fra"],
            check=True, env=env, timeout=900,
        )
        marker.write_text("ok\n", encoding="utf-8")
        n_xml = sum(1 for _ in dest.rglob("*.xml"))
        log.info("bulk dump ready xml_files=%s", n_xml)
        return dest
    except Exception as exc:
        log.warning("bulk dump clone failed (%s); will fetch per-instrument XML", exc)
        return dest if (dest / "eng").is_dir() else None


def lookup_bulk(dump: Optional[Path], it: dict) -> Optional[Path]:
    if dump is None:
        return None
    lang = (it.get("language") or "eng").lower()
    if lang.startswith("fr"):
        lang_dirs = ["fra"]
        if it.get("kind") == "act":
            kind_dirs = ["lois", "acts"]
        else:
            kind_dirs = ["reglements", "regulations"]
    else:
        lang_dirs = ["eng"]
        if it.get("kind") == "act":
            kind_dirs = ["acts", "lois"]
        else:
            kind_dirs = ["regulations", "reglements"]
    fn = it.get("xml_filename") or ""
    names = [fn]
    if fn:
        names.extend([unquote(fn), fn.replace("_", " "), fn.replace(" ", "_")])
    # de-dupe while preserving order
    seen = set()
    names = [n for n in names if n and not (n in seen or seen.add(n))]
    for lang_dir in lang_dirs:
        for kind_dir in kind_dirs:
            for name in names:
                p = dump / lang_dir / kind_dir / name
                if p.is_file() and p.stat().st_size > 40:
                    return p
    return None


def fetch_xml_http(it: dict) -> Optional[str]:
    url = it["xml_url"]
    cache = ROOT / CC / "raw" / "xml" / it["language"] / it["xml_filename"]
    if cache.exists() and cache.stat().st_size > 40:
        return cache.read_text(encoding="utf-8", errors="replace")
    r = http_get(
        url, ua=UA, sleep=SLEEP, timeout=(20, 180), retries=4,
        headers={"Accept": "application/xml, text/xml, */*"},
    )
    if r.status_code != 200 or not r.content or len(r.content) < 40:
        log_failure(CC, {
            "identifier": it.get("unique_id"),
            "source_url": url,
            "status": r.status_code if hasattr(r, "status_code") else "failed",
            "reason": "empty_or_bad_status",
        })
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(r.content)
    return r.content.decode("utf-8", errors="replace")


def parse_root(raw: str) -> Optional[ET.Element]:
    raw = re.sub(r"<!DOCTYPE[^>]*>", "", raw, count=1)
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        try:
            return ET.fromstring(raw.encode("utf-8"))
        except Exception:
            return None


def lims_attr(el: ET.Element, name: str) -> Optional[str]:
    return el.attrib.get(f"{{{LIMS}}}{name}") or el.attrib.get(name)


def element_text(el: ET.Element, skip: Optional[set[str]] = None) -> str:
    skip = skip or SKIP_TEXT_TAGS
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        tag = localtag(node.tag).lower()
        if tag in skip:
            return
        if tag == "label":
            lab = "".join(node.itertext()).strip()
            if lab:
                parts.append(lab)
            if node.tail and node.tail.strip():
                parts.append(node.tail.strip())
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


def extract_identification(root: ET.Element) -> dict:
    ident = None
    for el in root:
        if localtag(el.tag) == "Identification":
            ident = el
            break
    out = {
        "long_title": None,
        "short_title": None,
        "instrument_number": None,
        "consolidated_number": None,
        "chapter": None,
    }
    if ident is None:
        return out
    for el in ident.iter():
        tag = localtag(el.tag)
        if tag == "LongTitle" and out["long_title"] is None:
            out["long_title"] = "".join(el.itertext()).strip() or None
        elif tag == "ShortTitle" and out["short_title"] is None:
            out["short_title"] = "".join(el.itertext()).strip() or None
        elif tag == "InstrumentNumber" and out["instrument_number"] is None:
            out["instrument_number"] = "".join(el.itertext()).strip() or None
        elif tag == "ConsolidatedNumber" and out["consolidated_number"] is None:
            out["consolidated_number"] = "".join(el.itertext()).strip() or None
        elif tag == "Chapter" and out["chapter"] is None:
            out["chapter"] = "".join(el.itertext()).strip() or None
    return out


def law_full_text(root: ET.Element, ident_meta: dict) -> str:
    chunks: list[str] = []
    if ident_meta.get("long_title"):
        chunks.append(ident_meta["long_title"])
    if ident_meta.get("short_title") and ident_meta["short_title"] != ident_meta.get("long_title"):
        chunks.append(ident_meta["short_title"])
    for el in root:
        tag = localtag(el.tag).lower()
        if tag in {"body", "order", "schedule", "scheduleform"}:
            chunks.append(element_text(el))
    text = "\n\n".join(c for c in chunks if c)
    if not text:
        text = element_text(root)
    return text


def extract_sections(root: ET.Element, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs: list[dict] = []
    seen_ids: set[str] = set()
    for sec in root.iter():
        if localtag(sec.tag) != "Section":
            continue
        label = ""
        heading = ""
        for child in list(sec):
            t = localtag(child.tag)
            if t == "Label" and not label:
                label = "".join(child.itertext()).strip()
            elif t == "MarginalNote" and not heading:
                heading = "".join(child.itertext()).strip()
        text = element_text(sec)
        if not text or len(text) < 8:
            continue
        num = label or ""
        aid_src = num or heading or f"s{len(docs)+1}"
        aid = re.sub(r"[^a-z0-9]+", "-", aid_src.lower()).strip("-") or f"s{len(docs)+1}"
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen_ids:
            doc_id = f"{law_id}-{aid}-{len(docs)+1}"[:180]
        seen_ids.add(doc_id)
        title = " ".join(x for x in (num, heading) if x).strip() or num or "Section"
        docs.append({
            "id": doc_id,
            "title": title[:500],
            "text": text,
            "date_filed": date,
            "document_number": num or None,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num or None,
            "article_heading": heading or None,
            "law_identifier": law_id,
            "metadata": {
                "text_extraction": {"source": "official", "backend": "justice_laws_xml_section"},
                "unit": "section",
            },
        })
        if len(docs) >= 12000:
            break
    return docs


def record_id(it: dict) -> str:
    lang = lang_code(it.get("language"))
    uid = it.get("unique_id") or it.get("xml_filename") or "unknown"
    return slug_id(CC, f"{lang}-{uid}")


def fetch_one(it: dict, done: set[str], dump: Optional[Path]) -> str:
    rid = record_id(it)
    if rid in done:
        return "skip"
    raw = None
    local = lookup_bulk(dump, it)
    src_path = None
    if local is not None:
        raw = local.read_text(encoding="utf-8", errors="replace")
        src_path = str(local)
    if not raw:
        raw = fetch_xml_http(it)
        if raw:
            src_path = it["xml_url"]
    if not raw:
        return "fail"
    root = parse_root(raw)
    if root is None:
        log_failure(CC, {
            "identifier": it.get("unique_id"),
            "source_url": it.get("xml_url"),
            "status": "failed",
            "reason": "xml_parse_error",
        })
        return "fail"
    ident_meta = extract_identification(root)
    title = (
        it.get("title")
        or ident_meta.get("short_title")
        or ident_meta.get("long_title")
        or it.get("unique_id")
    )
    text = law_full_text(root, ident_meta)
    if not text or len(text) < 20:
        # last resort: xml_to_text
        text = xml_to_text(raw, skip_tags={
            "historicalnote", "recentamendments", "billhistory", "identification",
        })
    if not text or len(text) < 12:
        log_failure(CC, {
            "identifier": it.get("unique_id"),
            "source_url": it.get("xml_url"),
            "status": "failed",
            "reason": "empty_text",
        })
        return "fail"

    language = lang_code(it.get("language") or lims_attr(root, "lang") or root.attrib.get("{http://www.w3.org/XML/1998/namespace}lang"))
    kind = it.get("kind") or ("statute" if localtag(root.tag) == "Statute" else "regulation")
    document_type = "statute" if kind == "act" else "regulation"
    date = it.get("current_to") or iso_date(lims_attr(root, "current-date") or lims_attr(root, "pit-date"))
    last_amended = iso_date(lims_attr(root, "lastAmendedDate"))
    in_force_start = iso_date(lims_attr(root, "inforce-start-date"))
    official = (
        ident_meta.get("instrument_number")
        or ident_meta.get("consolidated_number")
        or it.get("official_number")
        or it.get("unique_id")
    )
    html_url = it.get("html_url") or it.get("xml_url")
    source_url = https(html_url)
    docs = extract_sections(root, rid, source_url, date)
    in_force_attr = (root.attrib.get("in-force") or "").lower()
    if in_force_attr in ("no", "false"):
        law_status, is_cur = "historical", False
    else:
        law_status, is_cur = "current", True

    rec = base_record(
        cc=CC, country=COUNTRY, language=language, ident=f"{language}-{it.get('unique_id')}",
        title=title, text=text, source_url=source_url, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="ca-justice-laws-xml",
        eli=None, date=date, official_identifier=official,
        document_type=document_type, law_status=law_status, is_current=is_cur,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": "legis_xml_catalog",
                "catalog_identifier": it.get("unique_id"),
                "seed_url": CATALOG_URL,
                "xml_url": it.get("xml_url"),
                "bulk_path": src_path,
            },
            "official_metadata": {
                "kind": kind,
                "unique_id": it.get("unique_id"),
                "official_number": it.get("official_number"),
                "current_to": it.get("current_to"),
                "last_amended": last_amended,
                "in_force_start": in_force_start,
                "long_title": ident_meta.get("long_title"),
                "short_title": ident_meta.get("short_title"),
                "instrument_number": ident_meta.get("instrument_number"),
                "consolidated_number": ident_meta.get("consolidated_number"),
                "xml_lang": language,
                "olid": it.get("olid"),
            },
        },
        extra_fields={
            "canonical_title": ident_meta.get("long_title") or title,
            "citation": official,
            "last_modified_date": last_amended,
            "effective_date": in_force_start or date,
            "valid_from": in_force_start,
            "languages": ["en", "fr"],
            "canonical_document_url": https(it.get("xml_url")),
        },
    )
    # keep id stable even if slug_id of ident already includes language
    rec["id"] = rid
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    dump = ensure_bulk_dump()
    done = existing_ids(CC)
    ok = skip = fail = 0
    # Prefer acts first so a timeout still yields a coherent Acts dump.
    items = sorted(items, key=lambda x: (0 if x.get("kind") == "act" else 1, x.get("language") or "", x.get("unique_id") or ""))
    n_acts = sum(1 for x in items if x.get("kind") == "act")
    n_regs = len(items) - n_acts
    log.info("queue acts=%s regulations=%s already_done=%s bulk=%s", n_acts, n_regs, len(done), bool(dump))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, it, done, dump) for it in items]
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
                    source="Justice Laws Website XML (Department of Justice Canada)",
                    source_urls=[
                        CATALOG_URL,
                        "https://laws-lois.justice.gc.ca/eng/XML/",
                        "https://laws-lois.justice.gc.ca/fra/XML/",
                        GITHUB_PAGE,
                    ],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail,
                    coverage="catalog-backed incomplete",
                    notes="In-force federal Acts and Regulations, bilingual EN+FR.",
                    last_run=utcnow(),
                )
    coverage = "full" if fail == 0 and ok + skip >= len(items) else "catalog-backed incomplete"
    notes = (
        f"Consolidated in-force federal Acts ({n_acts} language versions) and "
        f"Regulations ({n_regs} language versions) from Justice Laws XML. "
        f"Bilingual EN+FR as separate rows. Bulk dump: {GITHUB_PAGE}. "
        f"Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Justice Laws Website XML (Department of Justice Canada)",
        source_urls=[
            CATALOG_URL,
            "https://laws-lois.justice.gc.ca/eng/XML/",
            "https://laws-lois.justice.gc.ca/fra/XML/",
            GITHUB_PAGE,
            "https://open.canada.ca/data/en/dataset/ff56de85-f8b9-4719-8dff-ecf362adf0af",
        ],
        license_text=LICENSE, discovered=len(items), fetched=ok,
        skipped=skip, failed=fail, coverage=coverage, notes=notes,
        last_run=utcnow(), extra=f"started {t0}",
    )
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()

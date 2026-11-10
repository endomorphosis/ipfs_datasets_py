#!/usr/bin/env python3
"""Australian external territories CX / CC / HM via Federal Register of Legislation API.

Official keyless API: https://api.prod.legislation.gov.au/v1/
Portal robots.txt Crawl-delay: 10 — mirrored here as delay=10.
Does not HTML-crawl the SPA. No captcha/WAF bypass.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

os.environ.setdefault("MALLOC_ARENA_MAX", "2")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wave2b_common import (  # noqa: E402
    LAW_COLS,
    RAW,
    ROOT,
    StrikeStop,
    polite_get,
    require_mem,
    session,
    utcnow,
    verify_load_dataset,
    write_json,
    write_parquet,
)

API = "https://api.prod.legislation.gov.au/v1"
PORTAL = "https://www.legislation.gov.au"
LICENSE = (
    "Creative Commons Attribution 4.0 International (CC BY 4.0), as stated by the "
    "Federal Register of Legislation at https://www.legislation.gov.au/terms-of-use "
    "(exception: Commonwealth Coat of Arms and content otherwise noted). "
    "Attribute the Federal Register of Legislation. Not legal advice."
)
DELAY = 10.0
TERRITORIES = {
    "CX": {
        "name": "Christmas Island",
        "country": "Christmas Island",
        "repo": "endomorphosis/ipfs_christmasisland_laws",
        "terms": ["Christmas Island"],
    },
    "CC": {
        "name": "Cocos (Keeling) Islands",
        "country": "Cocos (Keeling) Islands",
        "repo": "endomorphosis/ipfs_cocoskeelingislands_laws",
        "terms": ["Cocos (Keeling) Islands", "Cocos Islands"],
    },
    "HM": {
        "name": "Heard Island and McDonald Islands",
        "country": "Heard Island and McDonald Islands",
        "repo": "endomorphosis/ipfs_heardislandandmcdonaldislands_laws",
        "terms": ["Heard Island", "McDonald Islands", "Heard Island and McDonald Islands"],
    },
}


def catalog_titles(sess, code: str, terms: list[str], strikes: list[int]) -> list[dict]:
    rows: dict[str, dict] = {}
    for term in terms:
        skip = 0
        while True:
            require_mem()
            # OData: avoid invalid $select fields; request full objects then trim
            params = {
                "$filter": f"contains(Name,'{term}')",
                "$top": "100",
                "$skip": str(skip),
                "$count": "true",
            }
            r = polite_get(sess, f"{API}/Titles", params=params, delay=DELAY, strikes=strikes)
            if r.status_code != 200:
                raise RuntimeError(f"Titles HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            vals = data.get("value") or []
            for v in vals:
                rows[v["id"]] = v
            total = data.get("@odata.count")
            print(code, term, "skip", skip, "got", len(vals), "unique", len(rows), "total", total)
            if not vals or (total is not None and skip + len(vals) >= int(total)):
                break
            skip += len(vals)
            if skip > 2000:
                break
    write_json(RAW / f"au_{code}_titles.json", {"count": len(rows), "titles": list(rows.values())})
    return list(rows.values())


def epub_to_text(content: bytes) -> str:
    parts = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
        names.sort()
        for n in names:
            raw = zf.read(n).decode("utf-8", errors="ignore")
            raw = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
            raw = re.sub(r"(?is)<style.*?>.*?</style>", " ", raw)
            raw = re.sub(r"(?is)<[^>]+>", " ", raw)
            raw = re.sub(r"&nbsp;", " ", raw)
            raw = re.sub(r"&amp;", "&", raw)
            raw = re.sub(r"\s+", " ", raw).strip()
            if raw:
                parts.append(raw)
    return "\n\n".join(parts).strip()


def docx_to_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    texts = []
    for e in root.iter():
        if e.tag.endswith("}t") and e.text:
            texts.append(e.text)
        if e.tag.endswith("}p"):
            texts.append("\n")
    return re.sub(r"\n{3,}", "\n\n", "".join(texts)).strip()


def fetch_document_text(sess, title_id: str, strikes: list[int]) -> tuple[str, str]:
    """Try Epub then Word compilations via API."""
    # Versions endpoint
    r = polite_get(sess, f"{API}/Titles('{title_id}')/Versions", delay=DELAY, strikes=strikes)
    if r.status_code != 200:
        return "", f"{PORTAL}/{title_id}"
    versions = (r.json() or {}).get("value") or []
    # Prefer Latest/Current
    versions_sorted = sorted(
        versions,
        key=lambda v: (
            0 if str(v.get("asAt") or v.get("name") or "").lower() in ("latest", "current") else 1,
            str(v.get("start") or v.get("registeredAt") or ""),
        ),
    )
    for ver in versions_sorted[:3]:
        ver_id = ver.get("id") or ver.get("Id")
        if not ver_id:
            continue
        for fmt in ("Epub", "Word", "Pdf"):
            url = f"{API}/Titles('{title_id}')/Versions('{ver_id}')/Formats('{fmt}')/$value"
            try:
                rr = polite_get(sess, url, delay=DELAY, strikes=strikes, timeout=(20, 180))
            except StrikeStop:
                raise
            except Exception:
                continue
            if rr.status_code != 200 or not rr.content or len(rr.content) < 100:
                continue
            try:
                if fmt == "Epub":
                    text = epub_to_text(rr.content)
                elif fmt == "Word":
                    text = docx_to_text(rr.content)
                else:
                    # skip PDF OCR in this pass (RSS budget)
                    continue
            except Exception:
                continue
            if len(text) >= 50:
                return text, f"{PORTAL}/{title_id}"
    return "", f"{PORTAL}/{title_id}"


def build_one(code: str, meta: dict, titles: list[dict], strikes: list[int]) -> dict:
    sess = session()
    laws = []
    errors = []
    # Prefer Acts + Ordinances + Legislative Instruments in force; cap to keep RSS polite
    preferred = []
    for t in titles:
        coll = str(t.get("collection") or "")
        status = str(t.get("status") or "")
        name = str(t.get("name") or "")
        score = 0
        if coll in ("Act", "LegislativeInstrument", "NotifiableInstrument"):
            score += 2
        if "Ordinance" in name or "Act" in name:
            score += 2
        if status.lower() in ("inforce", "in force"):
            score += 1
        preferred.append((score, t))
    preferred.sort(key=lambda x: -x[0])
    # Cap fetches: Acts/Ordinances first up to 40, else top 25
    selected = [t for _, t in preferred[:40]]
    for t in selected:
        tid = t["id"]
        title = t.get("name") or tid
        try:
            text, url = fetch_document_text(sess, tid, strikes)
        except StrikeStop:
            raise
        except Exception as e:
            errors.append({"id": tid, "error": str(e)})
            continue
        if len(text) < 50:
            # keep metadata-only? No — require text>=50 per task for substantive rows.
            # Still record thin miss.
            errors.append({"id": tid, "error": "text_lt_50", "title": title})
            continue
        laws.append(
            {
                "id": f"{code.lower()}-{tid.lower()}",
                "title": title,
                "text": text,
                "source_url": url,
                "source_type": "au_federal_register_legislation",
                "jurisdiction": code,
                "country": meta["country"],
                "language": "en",
                "eli": None,
                "date": (t.get("makingDate") or [None])[0] if isinstance(t.get("makingDate"), list) else t.get("makingDate"),
                "date_issued": t.get("asMadeRegisteredAt"),
                "retrieved_at": utcnow(),
                "license": LICENSE,
                "law_status": t.get("status"),
                "identifier": tid,
                "official_identifier": tid,
                "article_count": 0,
                "json_path": None,
                "metadata_json": json.dumps(
                    {"collection": t.get("collection"), "year": t.get("year"), "number": t.get("number")},
                    ensure_ascii=False,
                ),
            }
        )
    out = ROOT / code / "upload_ready"
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    scrapers = out / "scrapers_and_normalizers"
    scrapers.mkdir(parents=True, exist_ok=True)
    for name in ("collect_au_external_territories.py", "wave2b_common.py"):
        src = Path(__file__).resolve().parent / name
        (scrapers / name).write_bytes(src.read_bytes())
    validation = {
        "jurisdiction": code,
        "target_hf_repo": meta["repo"],
        "catalog_titles": len(titles),
        "laws": 0,
        "articles": 0,
        "errors": errors[:80],
        "error_count": len(errors),
        "push": "NOT_PUSHED",
        "delay_seconds": DELAY,
    }
    if laws:
        n = write_parquet(data / "laws.parquet", laws, LAW_COLS)
        validation["laws"] = n
        validation["load_dataset_verify"] = verify_load_dataset(out)
        (out / "README.md").write_text(
            f"""# {meta['name']} laws

Official instruments from the Australian Federal Register of Legislation API
(`api.prod.legislation.gov.au`) whose titles mention {meta['name']}.

License: {LICENSE}

Laws: {n}
Retrieved: {utcnow()}
Push: NOT_PUSHED (Chief of Staff HF HOLD)
""",
            encoding="utf-8",
        )
    else:
        (out / "README.md").write_text(
            f"# {meta['name']} — code-only / thin\n\nCatalogued {len(titles)} titles; no text>=50 instrument bodies fetched in this pass.\n",
            encoding="utf-8",
        )
        # do not write 0-row parquet
    write_json(out / "validation.json", validation)
    return validation


def main() -> int:
    require_mem()
    # local corpora check note
    write_json(
        RAW / "au_local_corpora_check.json",
        {
            "checked": [
                "/workspace/legal-corpora/au_sa",
                "/workspace/legal-corpora/au_subnational",
                "/workspace/legal-corpora/world_admin_regs_eos_20261105/AU",
            ],
            "christmas_cocos_heard_content_hits": 0,
            "note": "No on-disk AU federal instruments for CX/CC/HM; using Register API.",
        },
    )
    sess = session()
    strikes: list[int] = []
    summary = {}
    for code, meta in TERRITORIES.items():
        print("===", code)
        titles = catalog_titles(sess, code, meta["terms"], strikes)
        summary[code] = build_one(code, meta, titles, strikes)
    write_json(RAW / "au_external_summary.json", summary)
    print(json.dumps({k: {"laws": v.get("laws"), "catalog": v.get("catalog_titles")} for k, v in summary.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

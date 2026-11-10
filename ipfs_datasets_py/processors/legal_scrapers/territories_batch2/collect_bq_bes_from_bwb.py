#!/usr/bin/env python3
"""Caribbean Netherlands (BQ / BES) collector — robots-aware BWB path.

zoekservice.overheid.nl robots.txt is `User-agent: * / Disallow: /`, so this
collector does NOT call the SRU Search endpoint. Discovery uses:
  1) title/id filter of already-published endomorphosis/ipfs_netherlands_laws
  2) official repository.officiele-overheidspublicaties.nl BWB XML for those IDs
     (no robots.txt present; TLS verified; polite delay)
  3) wetten.overheid.nl HTML only on Allow paths (not /zoeken/zoekresultaat,
     not /*/informatie/xml)

License: CC0-1.0 as stated by KOOP for Basis Wetten Bestand.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

os.environ.setdefault("MALLOC_ARENA_MAX", "2")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wave2b_common import (  # noqa: E402
    ART_COLS,
    LAW_COLS,
    RAW,
    ROOT,
    StrikeStop,
    UA,
    extract_articles_from_bwb_text,
    polite_get,
    require_mem,
    session,
    utcnow,
    verify_load_dataset,
    write_json,
    write_parquet,
)

BES_RE = re.compile(
    r"\bBES\b|Bonaire|Sint[\s\-]?Eustatius|\bSaba\b|Caribisch Nederland|"
    r"openbare lichamen Bonaire|Wetboek BES|WolBES|FinBES",
    re.I,
)
LICENSE = (
    "CC0-1.0 as stated by KOOP on data.overheid.nl dataset "
    "'Basis Wetten Bestand' (Basiswettenbestand). Not legal advice; "
    "authorised wetten.overheid.nl / BWB text prevails."
)
REPO = "https://repository.officiele-overheidspublicaties.nl/bwb"


def localtag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def text_of(elem: ET.Element) -> str:
    skip = {
        "meta-data", "brondata", "oorspronkelijk", "inwerkingtreding", "jcis", "jci",
        "bwb-inputbestand", "bwb-wijzigingen", "redactionele-correcties", "publicatie",
        "extref",
    }
    block = {
        "artikel", "lid", "hoofdstuk", "titeldeel", "afdeling", "paragraaf",
        "subparagraaf", "wet-besluit", "regeling", "bijlage", "intitule",
        "citeertitel", "aanhef", "al", "kop", "divisie",
    }
    parts: list[str] = []

    def rec(e: ET.Element) -> None:
        tag = localtag(e.tag)
        if tag in skip:
            return
        if tag in block:
            parts.append("\n")
        if e.text and e.text.strip():
            parts.append(e.text.strip())
        for c in list(e):
            rec(c)
            if c.tail and c.tail.strip():
                parts.append(c.tail.strip())
        if tag in block:
            parts.append("\n")

    rec(elem)
    raw = " ".join(parts)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n[ \t]+", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def discover_from_hf_nl() -> list[dict]:
    require_mem()
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq

    path = hf_hub_download(
        repo_id="endomorphosis/ipfs_netherlands_laws",
        filename="data/laws.parquet",
        repo_type="dataset",
        local_dir=str(RAW / "hf_nl"),
        local_dir_use_symlinks=False,
    )
    # column projection
    cols = [c for c in ("id", "title", "text", "source_url", "identifier", "official_identifier",
                        "eli", "date", "date_issued", "license", "law_status", "language",
                        "metadata_json", "article_count") if True]
    # read only needed cols that exist
    pf = pq.ParquetFile(path)
    names = pf.schema_arrow.names
    want = [c for c in cols if c in names]
    table = pf.read(columns=want)
    hits = []
    for i in range(table.num_rows):
        row = {c: table.column(c)[i].as_py() for c in want}
        title = str(row.get("title") or "")
        ident = str(row.get("identifier") or row.get("id") or "")
        if BES_RE.search(title) or BES_RE.search(ident):
            hits.append(row)
    write_json(RAW / "bq_bes_hf_hits.json", {"count": len(hits), "ids": [h.get("id") for h in hits]})
    return hits


def bwb_id_of(row: dict) -> str | None:
    for key in ("official_identifier", "identifier", "id", "source_url"):
        val = str(row.get(key) or "")
        m = re.search(r"(BWBR\d{7})", val.upper())
        if m:
            return m.group(1)
    return None


def fetch_repo_xml(sess, bwb_id: str, strikes: list[int]) -> tuple[str, str]:
    """Return (xml_text, xml_url) for latest toestand."""
    man_url = f"{REPO}/{bwb_id}/"
    r = polite_get(sess, man_url, strikes=strikes, delay=2.0)
    if r.status_code != 200 or not r.content:
        return "", man_url
    root = ET.fromstring(r.content)
    latest = root.attrib.get("_latestItem")
    if not latest:
        # fallback: first item label path
        for e in root.iter():
            if localtag(e.tag) == "item" and e.attrib.get("label"):
                # need expression/manifestation path — use parent structure
                pass
        return "", man_url
    xml_url = f"{REPO}/{bwb_id}/{latest}"
    r2 = polite_get(sess, xml_url, strikes=strikes, delay=2.0)
    if r2.status_code != 200:
        return "", xml_url
    return r2.text, xml_url


def citeertitel(root: ET.Element) -> str:
    for e in root.iter():
        if localtag(e.tag) == "citeertitel" and (e.text or "").strip():
            return e.text.strip()
    for e in root.iter():
        if localtag(e.tag) == "intitule" and (e.text or "").strip():
            return e.text.strip()
    return ""


def build_package(hits: list[dict]) -> dict:
    require_mem()
    sess = session()
    strikes: list[int] = []
    laws = []
    articles = []
    errors = []
    seen = set()
    for row in hits:
        bid = bwb_id_of(row)
        if not bid or bid in seen:
            continue
        seen.add(bid)
        text = ""
        xml_url = ""
        title = str(row.get("title") or "")
        try:
            xml, xml_url = fetch_repo_xml(sess, bid, strikes)
            if xml:
                root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
                title = citeertitel(root) or title
                text = text_of(root)
        except StrikeStop:
            raise
        except Exception as e:
            errors.append({"bwb_id": bid, "error": str(e)})
        if not text:
            text = str(row.get("text") or "")
        if len(text) < 50:
            errors.append({"bwb_id": bid, "error": "text_lt_50"})
            continue
        law_id = f"bq-{bid.lower()}"
        source_url = xml_url or str(row.get("source_url") or f"https://wetten.overheid.nl/{bid}")
        arts = extract_articles_from_bwb_text(law_id, text, source_url)
        laws.append(
            {
                "id": law_id,
                "title": title or bid,
                "text": text,
                "source_url": source_url,
                "source_type": "bwb_repository_bes",
                "jurisdiction": "BQ",
                "country": "Bonaire, Sint Eustatius and Saba",
                "language": "nl",
                "eli": None,
                "date": row.get("date"),
                "date_issued": row.get("date_issued"),
                "retrieved_at": utcnow(),
                "license": LICENSE,
                "law_status": row.get("law_status") or "unknown",
                "identifier": bid,
                "official_identifier": bid,
                "article_count": len(arts),
                "json_path": None,
                "metadata_json": json.dumps(
                    {
                        "bwb_id": bid,
                        "discovery": "hf_netherlands_laws_title_filter+repository_xml",
                        "sru_skipped_reason": "zoekservice.overheid.nl robots.txt Disallow:/",
                        "hf_source_id": row.get("id"),
                    },
                    ensure_ascii=False,
                ),
            }
        )
        articles.extend(arts)
    out = ROOT / "BQ" / "upload_ready"
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    n_laws = write_parquet(data / "laws.parquet", laws, LAW_COLS)
    n_arts = 0
    if articles:
        n_arts = write_parquet(data / "articles.parquet", articles, ART_COLS)
    readme = f"""# Bonaire, Sint Eustatius and Saba (Caribbean Netherlands) laws

Jurisdiction: BQ (BES islands) — Dutch public-body legislation.

Source: KOOP Basis Wetten Bestand (BWB) via official repository XML.
SRU at zoekservice.overheid.nl was **not** queried because robots.txt
disallows all paths for User-agent *.

Discovery: title filter on `endomorphosis/ipfs_netherlands_laws` for BES /
Bonaire / Sint Eustatius / Saba / Caribisch Nederland, then refresh from
`repository.officiele-overheidspublicaties.nl/bwb/{{BWBR}}/`.

License: {LICENSE}

Rows: laws={n_laws}, articles={n_arts}
Retrieved: {utcnow()}
Push: NOT_PUSHED (Chief of Staff HF HOLD)
"""
    (out / "README.md").write_text(readme, encoding="utf-8")
    validation = {
        "jurisdiction": "BQ",
        "target_hf_repo": "endomorphosis/ipfs_bonairesinteustatiusandsaba_laws",
        "laws": n_laws,
        "articles": n_arts,
        "errors": errors[:50],
        "error_count": len(errors),
        "sru_used": False,
        "sru_skip_reason": "robots.txt User-agent:* Disallow:/ on zoekservice.overheid.nl",
        "discovery": "hf_netherlands_title_filter + repository XML",
        "strikes": strikes,
        "push": "NOT_PUSHED",
        "load_dataset_verify": None,
    }
    try:
        validation["load_dataset_verify"] = verify_load_dataset(out)
    except Exception as e:
        validation["load_dataset_verify_error"] = str(e)
    write_json(out / "validation.json", validation)
    # bundle scrapers
    scrapers = out / "scrapers_and_normalizers"
    scrapers.mkdir(parents=True, exist_ok=True)
    for name in ("collect_bq_bes_from_bwb.py", "wave2b_common.py"):
        src = Path(__file__).resolve().parent / name
        dst = scrapers / name
        if src.exists() and not dst.exists():
            dst.write_bytes(src.read_bytes())
        elif src.exists():
            # additive overwrite of our own staged copy is OK (same content path)
            dst.write_bytes(src.read_bytes())
    return validation


def main() -> int:
    require_mem()
    hits = discover_from_hf_nl()
    print(f"BES HF hits: {len(hits)}")
    if not hits:
        # stage code-only package note
        out = ROOT / "BQ" / "upload_ready"
        scrapers = out / "scrapers_and_normalizers"
        scrapers.mkdir(parents=True, exist_ok=True)
        for name in ("collect_bq_bes_from_bwb.py", "wave2b_common.py"):
            src = Path(__file__).resolve().parent / name
            (scrapers / name).write_bytes(src.read_bytes())
        write_json(
            out / "validation.json",
            {
                "jurisdiction": "BQ",
                "laws": 0,
                "articles": 0,
                "note": "No BES title hits in live HF NL; scraper bundled only (no 0-row parquet).",
                "push": "NOT_PUSHED",
            },
        )
        (out / "README.md").write_text(
            "# BQ BES — code-only staging\n\nNo BES title matches in live Netherlands HF corpus yet.\n",
            encoding="utf-8",
        )
        print("code-only staging")
        return 0
    val = build_package(hits)
    print(json.dumps({k: val[k] for k in ("laws", "articles", "error_count", "sru_used")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

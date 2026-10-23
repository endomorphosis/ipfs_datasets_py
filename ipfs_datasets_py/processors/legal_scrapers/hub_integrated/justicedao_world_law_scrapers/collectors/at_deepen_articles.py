#!/usr/bin/env python3
"""Austria: deepen Hub tip arts from RIS BrKons per Gesetzesnummer.
Never thins laws below Hub floor 21959 (tip d79a0d6f8c02). Soft never-thin.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import json
import logging
import re
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import requests

ROOT = _CORPORA / "at"
REL = Path("{_CORPORA}-releases/austria")
LAWS_PQ = REL / "data" / "laws.parquet"
ARTS_PQ = REL / "data" / "articles.parquet"
ARTS_JSONL = ROOT / "deepen" / "articles.jsonl"
DONE_PATH = ROOT / "deepen" / "done_law_ids.txt"
STATE_PATH = ROOT / "deepen" / "state.json"
LOG_PATH = _CORPORA / "_wave_logs" / "at_deepen_articles.md"
API = "https://data.bka.gv.at/ris/api/v2.6/Bundesrecht"
UA = "CountryLawScraper/at-deepen (+https://huggingface.co/endomorphosis)"
FLOOR_LAWS = 21959
MAX_ARTS_PER_LAW = 80
FETCH_SLEEP = 0.08

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("at_deepen")


def ensure():
    (ROOT / "deepen").mkdir(parents=True, exist_ok=True)
    REL.joinpath("data").mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_done() -> set[str]:
    if not DONE_PATH.exists():
        return set()
    return {ln.strip() for ln in DONE_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()}


def mark_done(law_id: str) -> None:
    with DONE_PATH.open("a", encoding="utf-8") as f:
        f.write(law_id + "\n")


def xml_or_html_to_text(body: str) -> str:
    # light strip tags
    body = re.sub(r"(?is)<script.*?>.*?</script>", " ", body)
    body = re.sub(r"(?is)<style.*?>.*?</style>", " ", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    body = re.sub(r"&nbsp;", " ", body)
    body = re.sub(r"&amp;", "&", body)
    body = re.sub(r"&lt;", "<", body)
    body = re.sub(r"&gt;", ">", body)
    body = re.sub(r"\s+", " ", body).strip()
    return body


def fetch_url(url: str) -> str:
    if not url:
        return ""
    try:
        r = requests.get(url, timeout=(20, 90), headers={"User-Agent": UA})
        if r.status_code == 200 and r.text:
            return xml_or_html_to_text(r.text)
    except Exception as exc:
        log.info("fetch err %s %s", url, exc)
    return ""


def refs_for_gn(session: requests.Session, gn: str) -> list[dict]:
    out = []
    page = 1
    while page <= 50:
        try:
            time.sleep(0.12)
            r = session.post(
                API,
                data={
                    "Applikation": "BrKons",
                    "Gesetzesnummer": str(gn),
                    "DokumenteProSeite": "OneHundred",
                    "Seitennummer": str(page),
                },
                headers={"Accept": "application/json", "User-Agent": UA},
                timeout=(20, 90),
            )
        except Exception as exc:
            log.info("api gn=%s page=%s err %s", gn, page, exc)
            break
        if r.status_code != 200:
            break
        try:
            data = r.json()
        except Exception:
            break
        res = ((data or {}).get("OgdSearchResult") or {}).get("OgdDocumentResults") or {}
        hits = res.get("Hits") or {}
        total = int(hits.get("#text") or 0)
        refs = res.get("OgdDocumentReference") or []
        if isinstance(refs, dict):
            refs = [refs]
        if not refs:
            break
        for ref in refs:
            meta = ((ref.get("Data") or {}).get("Metadaten") or {})
            br = meta.get("Bundesrecht") or {}
            kons = br.get("BrKons") or {}
            urls = []
            dl = (ref.get("Data") or {}).get("Dokumentliste") or {}
            cr = dl.get("ContentReference") or {}
            if isinstance(cr, dict):
                cr = [cr]
            for c in cr or []:
                for u in (((c.get("Urls") or {}).get("ContentUrl")) or []):
                    if isinstance(u, dict):
                        urls.append(u)
            out.append(
                {
                    "para": (kons.get("ArtikelParagraphAnlage") or "").strip(),
                    "eli": br.get("Eli"),
                    "gesamt_url": kons.get("GesamteRechtsvorschriftUrl"),
                    "dokument_url": (meta.get("Allgemein") or {}).get("DokumentUrl"),
                    "urls": urls,
                    "kurztitel": (br.get("Kurztitel") or "").strip(),
                }
            )
        if total and page * 100 >= total:
            break
        page += 1
    return out


def pick_url(ref: dict) -> str:
    for u in ref.get("urls") or []:
        dt = (u.get("DataType") or u.get("dataType") or "").lower()
        url = u.get("#text") or u.get("Url") or u.get("url")
        if url and (dt == "xml" or str(url).endswith(".xml")):
            return url
    for u in ref.get("urls") or []:
        url = u.get("#text") or u.get("Url") or u.get("url")
        if url:
            return url
    return ref.get("gesamt_url") or ref.get("dokument_url") or ""


def para_slug(para: str) -> str:
    s = re.sub(r"\s+", " ", para or "").strip().lower()
    s = re.sub(r"[^a-z0-9§]+", "-", s).strip("-")
    return s or "para"


def append_articles(rows: list[dict]) -> None:
    if not rows:
        return
    with ARTS_JSONL.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def rebuild_articles_parquet() -> int:
    if not ARTS_JSONL.exists():
        # keep empty schema parquet
        table = pa.table(
            {
                "law_id": pa.array([], type=pa.string()),
                "id": pa.array([], type=pa.string()),
                "title": pa.array([], type=pa.string()),
                "text": pa.array([], type=pa.string()),
                "source_url": pa.array([], type=pa.string()),
                "document_number": pa.array([], type=pa.string()),
                "article_number": pa.array([], type=pa.string()),
                "record_type": pa.array([], type=pa.string()),
                "metadata_json": pa.array([], type=pa.string()),
            }
        )
        pq.write_table(table, ARTS_PQ)
        return 0
    # dedupe by id keeping last
    by_id = {}
    with ARTS_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            by_id[row["id"]] = row
    rows = list(by_id.values())
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, ARTS_PQ)
    return len(rows)


def update_law_article_counts(counts: dict[str, int]) -> None:
    """Update article_count in working laws parquet; never drop rows."""
    t = pq.read_table(LAWS_PQ)
    d = t.to_pandas()
    if len(d) < FLOOR_LAWS:
        raise RuntimeError(f"laws rows {len(d)} < floor {FLOOR_LAWS} — abort")
    d["article_count"] = d.apply(
        lambda r: max(int(r.get("article_count") or 0), int(counts.get(r["id"], r.get("article_count") or 0))),
        axis=1,
    )
    pq.write_table(pa.Table.from_pandas(d, preserve_index=False), LAWS_PQ)


def main():
    ensure()
    if not LAWS_PQ.exists():
        log.error("missing %s", LAWS_PQ)
        sys.exit(1)
    laws = pq.read_table(LAWS_PQ).to_pandas()
    if len(laws) < FLOOR_LAWS:
        log.error("laws %s < floor %s — refuse", len(laws), FLOOR_LAWS)
        sys.exit(2)
    done = load_done()
    session = requests.Session()
    counts: dict[str, int] = {}
    processed = 0
    arts_added = 0
    t0 = time.time()
    log.info("start laws=%s done=%s floor=%s", len(laws), len(done), FLOOR_LAWS)

    for idx, row in laws.iterrows():
        law_id = str(row["id"])
        if law_id in done:
            continue
        gn = str(row.get("official_identifier") or row.get("identifier") or "")
        if not gn:
            mark_done(law_id)
            continue
        refs = refs_for_gn(session, gn)
        # prefer concrete paragraphs; keep §0 only if alone
        concrete = [r for r in refs if (r.get("para") or "") not in ("", "§ 0", "§0", "0")]
        use = concrete or refs
        # dedupe by para (RIS returns historical duplicates)
        by_para = {}
        for r in use:
            by_para.setdefault((r.get("para") or "").strip(), r)
        use = list(by_para.values())[:MAX_ARTS_PER_LAW]
        log.info("law %s gn=%s refs=%s unique_para=%s fetching=%s", law_id, gn, len(refs), len(by_para), len(use))
        art_rows = []
        for ref in use:
            para = ref.get("para") or "§?"
            url = pick_url(ref)
            text = fetch_url(url)
            if not text or len(text) < 40:
                continue
            slug = para_slug(para)
            aid = f"{law_id}-{slug}"[:180]
            art_rows.append(
                {
                    "law_id": law_id,
                    "id": aid,
                    "title": f"{row.get('title') or gn} — {para}",
                    "text": text,
                    "source_url": url or (row.get("source_url") or ""),
                    "document_number": para,
                    "article_number": para,
                    "record_type": "article",
                    "metadata_json": json.dumps(
                        {
                            "collector": "at_deepen_articles",
                            "gesetzesnummer": gn,
                            "eli": ref.get("eli"),
                            "hub_tip_floor_laws": FLOOR_LAWS,
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            time.sleep(FETCH_SLEEP)
        if art_rows:
            append_articles(art_rows)
            counts[law_id] = len(art_rows)
            arts_added += len(art_rows)
        mark_done(law_id)
        processed += 1
        if processed % 25 == 0:
            n = rebuild_articles_parquet()
            update_law_article_counts(counts)
            counts.clear()
            STATE_PATH.write_text(
                json.dumps(
                    {
                        "processed": processed,
                        "arts_jsonl_estimate": arts_added,
                        "articles_parquet_rows": n,
                        "laws_rows": int(len(laws)),
                        "elapsed_s": int(time.time() - t0),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            log.info(
                "checkpoint processed=%s arts_added~=%s parquet_arts=%s elapsed=%ss",
                processed,
                arts_added,
                n,
                int(time.time() - t0),
            )

    n = rebuild_articles_parquet()
    if counts:
        update_law_article_counts(counts)
    log.info("DONE processed=%s arts_parquet=%s laws=%s", processed, n, len(laws))


if __name__ == "__main__":
    main()

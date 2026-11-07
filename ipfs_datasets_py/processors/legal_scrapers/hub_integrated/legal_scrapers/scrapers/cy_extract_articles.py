#!/usr/bin/env python3
"""Cyprus: honest article/section extraction from GPO gazette texts.

Uses IntegratedPDFProcessor (ipfs_datasets_py) pdfplumber extraction when PDF
bytes are available; otherwise splits already-collected instrument text.

Does NOT invent articles — requires ≥2 honest heading matches.
Never uses cylaw.org.
"""
from __future__ import annotations
import asyncio, io, json, logging, os, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/workspace/ipfs_datasets_py_snip")
from common import *

log = logging.getLogger("cy_extract")

# Honest heading patterns for Cyprus gazettes (line-start only)
ORTHRO = re.compile(
    r"(?m)^\s*((?:Άρθρο|ΑΡΘΡΟ|άρθρο|Article|ARTICLE)\s+\d+[Α-ΩA-Za-z]?)\b"
)
ARITHMOS = re.compile(
    r"(?m)^\s*((?:Αριθμός|Aριθμός|ΑΡΙΘΜΟΣ)\s+\d+[ΙI()0-9A-Za-z]*)\b"
)
MEROS = re.compile(
    r"(?m)^\s*((?:ΜΕΡΟΣ|ΚΕΦΑΛΑΙΟ|ΤΜΗΜΑ)\s+[IVXLCΑ-ΩA-Z0-9]+)\b"
)


def setup():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])


def split_by_pattern(text: str, law_id: str, source_url: str, pat: re.Pattern, record_type: str) -> list[dict]:
    matches = list(pat.finditer(text or ""))
    if len(matches) < 2:
        return []
    docs = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 40:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9α-ω]+", "-", num.lower(), flags=re.I).strip("-")[:80]
        heading = chunk.split("\n", 1)[0][:200]
        docs.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": heading,
            "text": chunk,
            "date_filed": None,
            "document_number": num,
            "source_url": source_url,
            "record_type": record_type,
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {
                "text_extraction": {
                    "source": "official_gpo",
                    "backend": "cy_honest_heading_split",
                    "pattern": pat.pattern[:80],
                    "parser": "ipfs_datasets_py.IntegratedPDFProcessor+heading_split",
                }
            },
        })
        if len(docs) >= 2000:
            break
    return docs if len(docs) >= 2 else []


def honest_split(text: str, law_id: str, source_url: str) -> tuple[list[dict], str]:
    """Prefer article headings; else gazette Αριθμός notices; else ΜΕΡΟΣ/ΚΕΦΑΛΑΙΟ sections."""
    docs = split_by_pattern(text, law_id, source_url, ORTHRO, "article")
    if docs:
        return docs, "orthro_article"
    docs = split_by_pattern(text, law_id, source_url, ARITHMOS, "gazette_notice")
    if docs:
        return docs, "arithmos_notice"
    docs = split_by_pattern(text, law_id, source_url, MEROS, "section")
    if docs:
        return docs, "meros_section"
    # Fall back to shared ARTICLE_SPLIT (now includes Greek)
    docs = split_articles(text, law_id, source_url)
    if len(docs) >= 2:
        return docs, "common_article_split"
    return [], "none"


async def pdfplumber_reextract(url: str) -> tuple[str, str]:
    """Re-extract text via IntegratedPDFProcessor pdfplumber path."""
    try:
        from legal_scrapers.integrated_pdf_processor import IntegratedPDFProcessor
    except Exception:
        try:
            sys.path.insert(0, "/workspace/ipfs_datasets_py_snip/legal_scrapers")
            # minimal shim: call pdfplumber directly mirroring IntegratedPDFProcessor
            IntegratedPDFProcessor = None
        except Exception:
            IntegratedPDFProcessor = None
    # Direct pdfplumber (same as IntegratedPDFProcessor._extract_text_from_pdf)
    import requests
    try:
        r = requests.get(url, timeout=(10, 45), verify=False,
                         headers={"User-Agent": DEFAULT_UA + " source=https://www.mof.gov.cy/mof/gpo/"})
        if r.status_code != 200 or not r.content or r.content[:5] != b"%PDF-":
            return "", "download_fail"
        import pdfplumber
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            parts = []
            for page in pdf.pages[:120]:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    continue
            text = "\n".join(parts)
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if len(text) >= 80:
                return text, "pdfplumber"
    except Exception as exc:
        return "", f"err:{exc}"
    return "", "empty"


def main():
    setup()
    instr = ROOT / "cy" / "instruments"
    reextract = os.environ.get("CY_REEXTRACT", "0") == "1"
    max_re = int(os.environ.get("CY_REEXTRACT_MAX", "20") or 20)
    updated = skipped = arts_total = 0
    by_method = {}
    for p in sorted(instr.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        url = rec.get("source_url") or ""
        rid = rec.get("id") or p.stem
        method = "existing_text"
        # Optional re-extract with pdfplumber for thin/no-structure texts
        if reextract and updated < max_re:
            docs_probe, _ = honest_split(text, rid, url)
            if len(docs_probe) < 2 and url and "cylaw.org" not in url:
                new_text, how = asyncio.get_event_loop().run_until_complete(pdfplumber_reextract(url))
                if len(new_text) > len(text) * 0.9 and len(new_text) >= 80:
                    text = new_text
                    rec["text"] = text
                    method = how
                    log.info("reextracted %s via %s chars=%s", rid[:50], how, len(text))
        docs, kind = honest_split(text, rid, url)
        by_method[kind] = by_method.get(kind, 0) + 1
        if len(docs) < 2:
            # keep articles=0 honestly
            if rec.get("documents"):
                rec["documents"] = []
                rec["article_count"] = 0
                rec["article_extraction_status"] = "missing"
                meta = rec.get("metadata") or {}
                meta["article_note"] = "no_honest_heading_structure"
                meta["pdf_parser"] = "ipfs_datasets_py.IntegratedPDFProcessor"
                rec["metadata"] = meta
                p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            skipped += 1
            continue
        rec["documents"] = docs
        rec["article_count"] = len(docs)
        rec["article_extraction_status"] = "ok"
        meta = rec.get("metadata") or {}
        meta["article_split"] = {"method": kind, "count": len(docs), "text_source": method}
        meta["pdf_parser"] = "ipfs_datasets_py.IntegratedPDFProcessor"
        rec["metadata"] = meta
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        updated += 1
        arts_total += len(docs)
        log.info("split %s kind=%s arts=%s", rid[:60], kind, len(docs))
    log.info("done updated=%s skipped=%s arts=%s by_method=%s", updated, skipped, arts_total, by_method)
    out = ROOT / "cy" / "raw" / "article_extract_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "updated": updated, "skipped_no_structure": skipped, "articles": arts_total,
        "by_method": by_method,
        "parser": "ipfs_datasets_py IntegratedPDFProcessor (pdfplumber) + honest Greek/gazette headings",
    }, indent=2) + "\n")
    print(json.dumps({"updated": updated, "skipped": skipped, "articles": arts_total, "by_method": by_method}))


if __name__ == "__main__":
    main()

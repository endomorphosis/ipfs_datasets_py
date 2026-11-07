#!/usr/bin/env python3
"""Italy deepen: fill thin bodies via dettaglio-atto + honest Art. articleization.

Official API only (Normattiva BFF). Prefer existing IDs over catalog expansion.
Bounds: MAX_NEW (body fills), MAX_SPLIT, MAX_SECONDS.
Does NOT upload to HF.
"""
from __future__ import annotations
import json, logging, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_it import api_post, UA, LICENSE, fetch_text
from common import html_to_text, split_articles, write_instrument, utcnow, ROOT

log = logging.getLogger("it_deepen")
INST = ROOT / "it" / "instruments"
ABROG = re.compile(r"PROVVEDIMENTO ABROGATO|DECRETO DECADUTO", re.I)
QUOTE_BLOCK = re.compile(r"[«\u201c\"].{0,3000}?[»\u201d\"]", re.S)
# Honest article heads after quote stripping: line-start Art. N
ART_LINE = re.compile(
    r"(?im)^[ \t]*((?:Art\.|Articolo)\s+\d+[a-zA-Z]?(?:\s*(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies))?)\b"
)
# Art. N (rubrica). - N.  (common Normattiva flattened form after <br>)
ART_FLAT = re.compile(
    r"(?m)(?<![\w«\"])((?:Art\.|Articolo)\s+\d+[a-zA-Z]?(?:\s*(?:bis|ter|quater))?)"
    r"(?:\s*\([^)]{0,160}\))?\s*(?:\.|-|–)\s+\d+\."
)


def parse_ids_from_record(rec: dict) -> tuple[str, str]:
    """Return (dataGU, codiceRedazionale) from instrument record."""
    ident = str(rec.get("official_identifier") or rec.get("identifier") or "")
    # forms: 2002-05-04-002G0112 or similar
    m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)$", ident)
    if m:
        return m.group(1), m.group(2)
    url = str(rec.get("source_url") or "")
    m = re.search(r"dataGU=([^&]+).*codiceRedazionale=([^&]+)", url)
    if m:
        return m.group(1), m.group(2)
    meta = rec.get("metadata") or {}
    disc = meta.get("discovery") or {}
    if disc.get("codiceRedazionale") and rec.get("date"):
        return str(rec.get("date")), str(disc.get("codiceRedazionale"))
    return "", ""


def strip_quotes(text: str) -> str:
    return QUOTE_BLOCK.sub(" ", text or "")


def split_it_articles(text: str, law_id: str, source_url: str, date: str | None = None) -> list[dict]:
    """Honest Italian article split; requires >=2 heads; strips quoted amendment refs."""
    if not text or len(text) < 80:
        return []
    # Prefer common split_articles first
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    cleaned = strip_quotes(text)
    matches = list(ART_LINE.finditer(cleaned))
    if len(matches) < 2:
        matches = list(ART_FLAT.finditer(cleaned))
    if len(matches) < 2:
        return []
    # Enforce roughly ascending article numbers (tolerance for bis)
    nums = []
    for m in matches:
        nm = re.search(r"(\d+)", m.group(1))
        nums.append(int(nm.group(1)) if nm else 0)
    # keep sequence where numbers don't wildly jump backwards more than once
    out = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
        chunk = cleaned[start:end].strip()
        if len(chunk) < 50:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        heading = chunk.split("\n", 1)[0][:200]
        out.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": heading,
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {
                "text_extraction": {
                    "source": "official_normattiva",
                    "backend": "it_honest_art_split",
                    "parser": "quote_strip+Art_line_or_flat",
                }
            },
        })
        if len(out) >= 2000:
            break
    return out if len(out) >= 2 else []


def fetch_body_and_articles(data_gu: str, codice: str) -> tuple[str, str, list[dict], str]:
    """Fetch via dettaglio-atto; try idArticolo walk when single Art. in blob.

    Returns (text, source_url, docs_from_api, title).
    """
    src = f"https://www.normattiva.it/atto/caricaDettaglioAtto?dataGU={data_gu}&codiceRedazionale={codice}"
    title = ""
    # First: whole-atto fetch
    r = api_post("/api/v1/atto/dettaglio-atto", {
        "dataGU": data_gu, "codiceRedazionale": codice, "formatoRichiesta": "V",
    })
    html = ""
    if r.status_code == 200 and r.content:
        try:
            data = r.json()
        except Exception:
            data = {}
        atto = ((data.get("data") or {}).get("atto")) or {}
        html = atto.get("articoloHtml") or ""
        title = (atto.get("titolo") or "").strip()
    text = html_to_text(html) if html else ""
    docs: list[dict] = []

    # Per-article walk with idArticolo (official filter field)
    art_htmls = []
    if html:
        # Always try walking a few articles when line-split is weak
        for i in range(1, 81):
            rr = api_post("/api/v1/atto/dettaglio-atto", {
                "dataGU": data_gu, "codiceRedazionale": codice,
                "formatoRichiesta": "V", "idArticolo": i,
            })
            if rr.status_code != 200:
                break
            try:
                atto = ((rr.json().get("data") or {}).get("atto")) or {}
            except Exception:
                break
            h = atto.get("articoloHtml") or ""
            if not h or len(h) < 40:
                break
            t = html_to_text(h)
            # Detect if still same Art.1 blob (API ignoring idArticolo)
            heads = re.findall(r'(?m)^(?:Art\.|Articolo)\s+\d+', t)
            art_nums = re.findall(r'<h2 class="article-num-akn"[^>]*>([^<]+)</h2>', h)
            label = art_nums[0] if art_nums else (heads[0] if heads else f"Art. {i}")
            # Stop if duplicate of first and i>1
            if i > 1 and art_htmls and h == art_htmls[0][1]:
                break
            if i > 1 and art_htmls and t == art_htmls[0][2]:
                break
            art_htmls.append((label, h, t))
            # Bound: if first response clearly contains many arts already, stop walk early
            if i == 1 and len(re.findall(r'article-num-akn', h)) >= 2:
                break
            if i == 1 and len(heads) >= 2:
                # whole blob already multi-article; no need to walk
                break
        if len(art_htmls) >= 2:
            parts = []
            for label, h, t in art_htmls:
                parts.append(t)
                aid = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
                docs.append({
                    "id": f"art-{aid}"[:120],
                    "title": label,
                    "text": t,
                    "date_filed": data_gu,
                    "document_number": label,
                    "source_url": src,
                    "record_type": "article",
                    "article_number": label,
                    "law_identifier": "",
                    "metadata": {
                        "text_extraction": {
                            "source": "official_normattiva_bff",
                            "backend": "dettaglio-atto:idArticolo",
                            "idArticolo_walk": True,
                        }
                    },
                })
            text = "\n\n".join(parts)
    return text, src, docs, title


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    max_new = int(os.environ.get("MAX_NEW", "300") or 300)
    max_split = int(os.environ.get("MAX_SPLIT", "2000") or 2000)
    max_seconds = int(os.environ.get("MAX_SECONDS", "3600") or 3600)
    t0 = time.time()
    files = sorted(INST.glob("*.json"))
    log.info("instruments=%s MAX_NEW=%s MAX_SPLIT=%s MAX_SECONDS=%s", len(files), max_new, max_split, max_seconds)

    filled = 0
    split_ok = 0
    arts_added = 0
    skipped = 0
    failed = 0
    refill_candidates = []
    split_candidates = []

    for p in files:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = str(rec.get("text") or "")
        docs = rec.get("documents") or []
        tl = len(text.strip())
        if ABROG.search(text[:300]) and tl < 200:
            skipped += 1
            continue
        # Prefer split if already has body and <2 docs
        if tl >= 120 and len(docs) < 2:
            split_candidates.append(p)
        # Body fill if short/non-abrog
        if tl < 120 and not ABROG.search(text[:300]):
            refill_candidates.append(p)
        elif tl < 80:
            skipped += 1

    log.info("split_candidates=%s refill_candidates=%s", len(split_candidates), len(refill_candidates))

    # Pass 1: offline articleization (no API)
    for p in split_candidates[:max_split]:
        if max_seconds and (time.time() - t0) > max_seconds:
            log.info("MAX_SECONDS during split"); break
        rec = json.loads(p.read_text(encoding="utf-8"))
        text = str(rec.get("text") or "")
        old_docs = rec.get("documents") or []
        law_id = rec.get("id") or p.stem
        new_docs = split_it_articles(text, law_id, rec.get("source_url") or "", rec.get("date"))
        if len(new_docs) >= 2 and len(new_docs) > len(old_docs):
            # fix ids to include law_id prefix properly
            for d in new_docs:
                if not str(d.get("id", "")).startswith(law_id):
                    d["id"] = f"{law_id}-{d.get('id')}"[:180]
                d["law_identifier"] = law_id
            rec["documents"] = new_docs
            rec["article_count"] = len(new_docs)
            rec["article_extraction_status"] = "ok"
            meta = rec.get("metadata") or {}
            meta["deepen"] = {"method": "it_honest_art_split", "at": utcnow()}
            rec["metadata"] = meta
            p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            split_ok += 1
            arts_added += len(new_docs) - len(old_docs)
            if split_ok % 50 == 0:
                log.info("split progress %s arts_added=%s", split_ok, arts_added)

    log.info("pass1 done split_ok=%s arts_added=%s", split_ok, arts_added)

    # Pass 2: API body-fill + idArticolo walk for thin / unsplit laws
    # Prefer laws with medium text that failed offline split (likely need idArticolo)
    need_api = []
    for p in split_candidates:
        if max_seconds and (time.time() - t0) > max_seconds * 0.95:
            break
        rec = json.loads(p.read_text(encoding="utf-8"))
        docs = rec.get("documents") or []
        if len(docs) >= 2:
            continue
        text = str(rec.get("text") or "")
        if len(text) < 200:
            continue
        # long text but couldn't split — candidate for idArticolo walk
        need_api.append(p)
    need_api = refill_candidates + need_api
    log.info("api_candidates=%s (capped %s)", len(need_api), max_new)

    for p in need_api[:max_new]:
        if max_seconds and (time.time() - t0) > max_seconds:
            log.info("MAX_SECONDS during fill"); break
        rec = json.loads(p.read_text(encoding="utf-8"))
        data_gu, codice = parse_ids_from_record(rec)
        if not data_gu or not codice:
            failed += 1
            continue
        try:
            text, src, api_docs, title = fetch_body_and_articles(data_gu, codice)
        except Exception as exc:
            log.info("fetch fail %s %s: %s", data_gu, codice, exc)
            failed += 1
            continue
        if not text or len(text) < 40:
            failed += 1
            continue
        law_id = rec.get("id") or p.stem
        old_text = str(rec.get("text") or "")
        old_docs = rec.get("documents") or []
        improved = False
        if len(text) > len(old_text) + 50:
            rec["text"] = text
            improved = True
            filled += 1
        docs = api_docs
        if len(docs) < 2:
            docs = split_it_articles(rec.get("text") or text, law_id, src or rec.get("source_url") or "", rec.get("date"))
        if len(docs) >= 2 and len(docs) > len(old_docs):
            for d in docs:
                if not str(d.get("id", "")).startswith(law_id):
                    d["id"] = f"{law_id}-{d.get('id')}"[:180]
                d["law_identifier"] = law_id
                d["source_url"] = d.get("source_url") or src
            rec["documents"] = docs
            rec["article_count"] = len(docs)
            rec["article_extraction_status"] = "ok"
            arts_added += len(docs) - len(old_docs)
            split_ok += 1
            improved = True
        if title and (not rec.get("title") or len(title) > 10):
            rec["title"] = title
        if improved:
            meta = rec.get("metadata") or {}
            meta["deepen"] = {
                "method": "dettaglio-atto+idArticolo+split",
                "at": utcnow(),
                "source": src,
            }
            rec["metadata"] = meta
            if src:
                rec["source_url"] = rec.get("source_url") or src
            p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if (filled + split_ok) % 20 == 0:
            log.info("api progress filled=%s split_ok=%s arts_added=%s fail=%s", filled, split_ok, arts_added, failed)

    elapsed = int(time.time() - t0)
    summary = {
        "filled_bodies": filled,
        "laws_articleized": split_ok,
        "arts_added": arts_added,
        "failed": failed,
        "skipped_abrog_or_short": skipped,
        "elapsed_seconds": elapsed,
        "max_new": max_new,
        "max_split": max_split,
    }
    out = ROOT / "it" / "logs" / "deepen_articles.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    log.info("DONE %s", summary)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Italy deepen: Normattiva dettaglio-atto idArticolo walk for multi-article acts."""
from __future__ import annotations
import json, logging, os, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_it import api_post
from common import html_to_text, split_articles, utcnow, ROOT
log = logging.getLogger("it_deepen")
INST = ROOT / "it" / "instruments"
ABROG = re.compile(r"PROVVEDIMENTO ABROGATO|DECRETO DECADUTO", re.I)
ART_LINE = re.compile(r"(?im)^[ \t]*((?:Art\.|Articolo)\s+\d+[a-zA-Z]?)\b")

def parse_ids(rec):
    ident = str(rec.get("official_identifier") or rec.get("identifier") or "")
    m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)$", ident)
    if m: return m.group(1), m.group(2)
    url = str(rec.get("source_url") or "")
    m = re.search(r"dataGU=([^&]+).*codiceRedazionale=([^&]+)", url)
    if m: return m.group(1), m.group(2)
    rid = str(rec.get("id") or "")
    m = re.match(r"it-(\d{4}-\d{2}-\d{2})-(.+)$", rid, re.I)
    if m: return m.group(1), m.group(2).upper()
    return "", ""

def split_offline(text, law_id, source_url, date=None):
    docs = split_articles(text or "", law_id, source_url, date)
    if len(docs) >= 2: return docs
    matches = list(ART_LINE.finditer(text or ""))
    if len(matches) < 2: return []
    out = []
    for i, m in enumerate(matches):
        start = m.start(); end = matches[i+1].start() if i+1 < len(matches) else len(text)
        chunk = (text or "")[start:end].strip()
        if len(chunk) < 50: continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        out.append({"id": f"{law_id}-{aid}"[:180], "title": chunk.split("\n",1)[0][:200], "text": chunk, "date_filed": date, "document_number": num, "source_url": source_url, "record_type": "article", "article_number": num, "law_identifier": law_id, "metadata": {"text_extraction": {"source": "official_normattiva", "backend": "offline_art_line"}}})
        if len(out) >= 2000: break
    return out if len(out) >= 2 else []

def fetch_one(data_gu, codice, id_articolo):
    payload = {"dataGU": data_gu, "codiceRedazionale": codice, "formatoRichiesta": "V", "idArticolo": int(id_articolo)}
    r = api_post("/api/v1/atto/dettaglio-atto", payload)
    if r.status_code == 404: return "miss"
    if r.status_code != 200 or not r.content: return "err"
    try: data = r.json()
    except Exception: return "err"
    if data.get("success") is False and not ((data.get("data") or {}).get("atto") or {}).get("articoloHtml"):
        # message often encodes missing article
        return "miss"
    atto = ((data.get("data") or {}).get("atto")) or {}
    html = atto.get("articoloHtml") or ""
    if not html: return "miss"
    text = html_to_text(html)
    labels = re.findall(r'<h2 class="article-num-akn"[^>]*>([^<]+)</h2>', html)
    label = labels[0] if labels else f"Art. {id_articolo}"
    title = (atto.get("titolo") or "").strip()
    return {"text": text, "label": label, "title": title, "html_len": len(html)}

def walk(data_gu, codice, max_arts=100):
    src = f"https://www.normattiva.it/atto/caricaDettaglioAtto?dataGU={data_gu}&codiceRedazionale={codice}"
    # Probe art2 first: cheap filter for multi-article acts
    a1 = fetch_one(data_gu, codice, 1)
    if not isinstance(a1, dict):
        return "", [], "", src, "no_art1"
    a2 = fetch_one(data_gu, codice, 2)
    title = a1.get("title") or ""
    if not isinstance(a2, dict):
        # single-article (or flattened blob): try offline split of art1/full text
        docs = split_offline(a1["text"], "tmp", src, data_gu)
        if len(docs) >= 2:
            return a1["text"], docs, title, src, "offline_from_art1"
        return a1["text"], [{"id":"tmp-art-1","title":a1["label"],"text":a1["text"],"date_filed":data_gu,"document_number":a1["label"],"source_url":src,"record_type":"article","article_number":a1["label"],"law_identifier":"","metadata":{"text_extraction":{"source":"official_normattiva_bff","backend":"dettaglio-atto:idArticolo","idArticolo":1}}}], title, src, "single"
    # multi-article walk
    docs = []; parts = []; miss = 0
    for i, got in [(1, a1), (2, a2)]:
        label = got["label"]; aid = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or f"art-{i}"
        docs.append({"id": f"tmp-{aid}", "title": label, "text": got["text"], "date_filed": data_gu, "document_number": label, "source_url": src, "record_type": "article", "article_number": label, "law_identifier": "", "metadata": {"text_extraction": {"source": "official_normattiva_bff", "backend": "dettaglio-atto:idArticolo", "idArticolo": i}}})
        parts.append(got["text"])
        if got.get("title"): title = got["title"]
    for i in range(3, max_arts+1):
        got = fetch_one(data_gu, codice, i)
        if not isinstance(got, dict):
            miss += 1
            if miss >= 2: break
            continue
        miss = 0
        label = got["label"]; aid = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or f"art-{i}"
        docs.append({"id": f"tmp-{aid}", "title": label, "text": got["text"], "date_filed": data_gu, "document_number": label, "source_url": src, "record_type": "article", "article_number": label, "law_identifier": "", "metadata": {"text_extraction": {"source": "official_normattiva_bff", "backend": "dettaglio-atto:idArticolo", "idArticolo": i}}})
        parts.append(got["text"])
    return "\n\n".join(parts), docs, title, src, "walked"

def legge_boost(rec, tl):
    title = (rec.get("title") or "").lower()
    dtype = (rec.get("document_type") or "").lower()
    boost = 0
    if "legge" in title or dtype == "legge": boost += 50000
    if "decreto legislativo" in title or "d.lgs" in dtype: boost += 20000
    # prefer medium-long (multi-art likely) over mega single blobs
    if 3000 <= tl <= 80000: boost += 10000
    return boost + min(tl, 20000)

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
    max_new = int(os.environ.get("MAX_NEW", "300") or 300)
    max_seconds = int(os.environ.get("MAX_SECONDS", "3600") or 3600)
    max_arts = int(os.environ.get("MAX_ARTS_PER_LAW", "80") or 80)
    t0 = time.time()
    files = list(INST.glob("*.json"))
    log.info("instruments=%s MAX_NEW=%s MAX_SECONDS=%s", len(files), max_new, max_seconds)
    cands = []
    for p in files:
        try: rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception: continue
        text = str(rec.get("text") or ""); docs = rec.get("documents") or []; tl = len(text.strip())
        if len(docs) >= 2: continue
        if ABROG.search(text[:300]) and tl < 250: continue
        if tl < 80: continue
        cands.append((legge_boost(rec, tl), tl, p))
    cands.sort(key=lambda x: -x[0])
    log.info("candidates=%s top=%s", len(cands), [(c[1], c[2].name) for c in cands[:5]])
    offline = 0; arts_added = 0
    for score, tl, p in cands:
        rec = json.loads(p.read_text(encoding="utf-8"))
        if len(rec.get("documents") or []) >= 2: continue
        law_id = rec.get("id") or p.stem
        docs = split_offline(rec.get("text") or "", law_id, rec.get("source_url") or "", rec.get("date"))
        if len(docs) >= 2:
            rec["documents"] = docs; rec["article_count"] = len(docs); rec["article_extraction_status"] = "ok"
            meta = rec.get("metadata") or {}; meta["deepen"] = {"method": "offline_art_split", "at": utcnow()}; rec["metadata"] = meta
            p.write_text(json.dumps(rec, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            offline += 1; arts_added += len(docs)
    log.info("offline_split=%s arts_added=%s", offline, arts_added)
    remain = []
    for score, tl, p in cands:
        rec = json.loads(p.read_text(encoding="utf-8"))
        if len(rec.get("documents") or []) >= 2: continue
        remain.append((score, tl, p))
    log.info("api remain=%s cap=%s", len(remain), max_new)
    filled = 0; articleized = 0; failed = 0; singles = 0
    for n, (score, tl, p) in enumerate(remain[:max_new], 1):
        if time.time() - t0 > max_seconds:
            log.info("MAX_SECONDS at %s", n); break
        rec = json.loads(p.read_text(encoding="utf-8"))
        data_gu, codice = parse_ids(rec)
        if not data_gu or not codice:
            failed += 1; continue
        try:
            full, docs, title, src, mode = walk(data_gu, codice, max_arts=max_arts)
        except Exception as exc:
            log.info("err %s %s %s", data_gu, codice, exc); failed += 1; continue
        law_id = rec.get("id") or p.stem
        old_text = str(rec.get("text") or ""); old_docs = rec.get("documents") or []; improved = False
        if mode == "single":
            singles += 1
            # still refresh body if longer
            if full and len(full) > len(old_text) + 100:
                rec["text"] = full; filled += 1; improved = True
                if title: rec["title"] = title
                meta = rec.get("metadata") or {}; meta["deepen"] = {"method": "dettaglio-atto:single", "at": utcnow()}; rec["metadata"] = meta
                p.write_text(json.dumps(rec, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            if n % 10 == 0:
                log.info("api %s/%s filled=%s arts_laws=%s arts_added=%s single=%s fail=%s mode_last=%s t=%.0fs", n, max_new, filled, articleized, arts_added, singles, failed, mode, time.time()-t0)
            continue
        if full and (len(full) > len(old_text) + 40 or (len(old_text) < 120 and len(full) >= 120)):
            rec["text"] = full; filled += 1; improved = True
        if len(docs) >= 2 and len(docs) > len(old_docs):
            for d in docs:
                if not str(d.get("id","")).startswith(law_id):
                    d["id"] = f"{law_id}-{d.get('id')}"[:180]
                d["law_identifier"] = law_id
            rec["documents"] = docs; rec["article_count"] = len(docs); rec["article_extraction_status"] = "ok"
            arts_added += len(docs) - len(old_docs); articleized += 1; improved = True
        if title: rec["title"] = title
        if improved:
            meta = rec.get("metadata") or {}
            meta["deepen"] = {"method": f"dettaglio-atto:{mode}", "at": utcnow(), "n_docs": len(rec.get("documents") or [])}
            rec["metadata"] = meta; rec["source_url"] = rec.get("source_url") or src
            p.write_text(json.dumps(rec, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        else:
            failed += 1
        if n % 5 == 0:
            log.info("api %s/%s filled=%s arts_laws=%s arts_added=%s single=%s fail=%s t=%.0fs", n, max_new, filled, articleized, arts_added, singles, failed, time.time()-t0)
    summary = {"offline_split_laws": offline, "filled_bodies": filled, "api_articleized_laws": articleized, "arts_added": arts_added, "singles_skipped": singles, "failed_or_unchanged": failed, "elapsed_seconds": int(time.time()-t0), "max_new": max_new, "source": "Normattiva BFF dettaglio-atto idArticolo"}
    outp = ROOT / "it" / "logs" / "deepen_articles.json"; outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    log.info("DONE %s", summary)

if __name__ == "__main__":
    main()

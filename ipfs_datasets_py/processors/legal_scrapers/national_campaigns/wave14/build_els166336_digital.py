#!/usr/bin/env python3
"""Wave-14 tail: recover sv els166336 via DIGITAL extraction.

The banked capture (wave11/ocr_pdfs/sv/els166336.pdf) was exactly
5,242,880 B / 0 pages. The CDX fresh-capture check (watchdog
2026-10-15) found every Wayback capture (7 rows, one payload digest
FQ7PVIPUQBEBDCO3KSVKRXH6I4GYDTYF, timestamps 2023-06-27 ->
2025-11-07) serves byte-identical truncated bytes (sha256
5e32a237..., Content-Length 5242880, wayback redirects all
timestamps to 20251107155154) -- the CDX route cannot repair it.
The LIVE FAOLEX origin does: Content-Length 49,174,554,
Accept-Ranges bytes, Range GET past 5 MiB returns real PDF bytes.
Full live download verified: 49,174,554 B, sha256 279adcb8...,
53 pages, 192,449 clean digital chars (Plan Estrategico
Institucional 2014-2019, Ministerio de Agricultura, El Salvador).
The truncated copy is preserved at
wave14/stats/els166336_truncated_5242880.pdf.bak and the live
capture is banked at the original wave11 path.

Like geo200876, tesseract OCR of already-digital pages is the
wrong route; this driver rebuilds the instrument with
faolex_cdx_harvest13's own extract / derive_title /
count_articles logic and record shape, guarded by a fresh
dedupe (id + normalized-title checks), for the standard
stage->publish pipeline. Title: derive_title returns the cover
slogan "AGRICULTURA PARA EL BUEN VIVIR"; corrected to the
document title per the geo200876 / RPPL-10-47 precedent.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, re, sys

SCRIPTS13 = os.path.expanduser(
    "~/workspace/goals/global-law-scraping-coverage/hidden_files/wave13/scripts")
sys.path.insert(0, SCRIPTS13)
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from common13 import build_dedupe, norm, WAVE13  # noqa: E402
import faolex_cdx_harvest13 as H  # noqa: E402

CC = "sv"
FN = "els166336.pdf"
PDF = os.path.expanduser(
    "~/workspace/goals/global-law-scraping-coverage/hidden_files/"
    "wave11/ocr_pdfs/sv/els166336.pdf")
INST_DIR = os.path.expanduser("~/.ipfs_datasets/legal-corpora/sv/instruments")
TITLE = "PLAN ESTRATÉGICO INSTITUCIONAL 2014-2019"

def main():
    info = build_dedupe(CC)
    print("dedupe:", json.dumps(info))
    dedupe = json.load(open(os.path.join(WAVE13, "dedupe", "sv_dedupe.json")))
    hf_ids = {r["id"] for r in dedupe}
    hf_titles = {r["norm_title"] for r in dedupe if r["norm_title"]}
    code = FN[:-4]
    iid = f"{CC}-faolex-{code}"
    local_ids = {f[:-5] for f in os.listdir(INST_DIR) if f.endswith(".json")}
    assert iid not in hf_ids, f"{iid} already remote"
    assert iid not in local_ids, f"{iid} already local"
    got = H.extract(PDF)
    assert got is not None, "extract child died"
    text, pages, meta_title = got
    text = text.strip()
    print(f"extract: pages={pages} chars={len(text)} meta_title={meta_title!r}")
    assert len(text) >= 300, "short_text"
    derived = H.derive_title(text, meta_title)
    print("derived title:", derived)
    print("title (corrected):", TITLE)
    assert norm(TITLE) not in hf_titles, "dup_title guard would hold it"
    ym = re.search(r"\b(19|20)\d{2}\b", text[:1500])
    num = re.search(r"\d+", code).group(0)
    rec = {
        "id": iid, "title": TITLE, "text": text,
        "source_url": f"https://faolex.fao.org/docs/pdf/{FN}",
        "source_type": "faolex-cdx",
        "jurisdiction": "El Salvador", "country": CC,
        "language": "es", "eli": None,
        "date": ym.group(0) if ym else None,
        "retrieved_at": H.TODAY + "T00:00:00Z",
        "license": "public-domain", "law_status": "unknown",
        "identifier": iid, "official_identifier": f"LEX-FAOC{num}",
        "article_count": H.count_articles(text),
    }
    out = os.path.join(INST_DIR, iid + ".json")
    with open(out, "w") as f:
        json.dump(rec, f, ensure_ascii=False)
    print("WROTE", out, "articles:", rec["article_count"], "date:", rec["date"])
    print("sample:", text[:300].replace("\n", " "))

if __name__ == "__main__":
    main()

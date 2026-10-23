#!/usr/bin/env python3
"""Wave-14 tail: recover ge geo200876 via DIGITAL extraction.

The repaired CDX capture (wave12/ocr_pdfs/ge/geo200876.pdf, 2,329,166 B,
49 pp) carries 121,532 clean digital chars (Kakheti Regional
Development Strategy 2014-2021, English). The bank12 OCR rerun
quality-rejected it (126,518 OCR chars, alpha 0.539, script_share
0.478) because tesseract garbled already-digital pages. This driver
rebuilds the instrument with faolex_cdx_harvest13's own extract /
derive_title / count_articles logic and record shape, guarded by a
fresh dedupe (id + normalized-title checks), and writes it to the
local ge instruments dir for the standard stage->publish pipeline.
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

CC = "ge"
FN = "geo200876.pdf"
PDF = os.path.expanduser(
    "~/workspace/goals/global-law-scraping-coverage/hidden_files/"
    "wave12/ocr_pdfs/ge/geo200876.pdf")
INST_DIR = os.path.expanduser("~/.ipfs_datasets/legal-corpora/ge/instruments")

def main():
    info = build_dedupe(CC)
    print("dedupe:", json.dumps(info))
    dedupe = json.load(open(os.path.join(WAVE13, "dedupe", "ge_dedupe.json")))
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
    title = H.derive_title(text, meta_title)
    print("title:", title)
    assert norm(title) not in hf_titles, "dup_title guard would hold it"
    lang = "en"
    sample5k = text[:5000]
    if len(re.findall(r"[\u10A0-\u10FF]", sample5k)) > 200:
        lang = "ka"
    ym = re.search(r"\b(19|20)\d{2}\b", text[:1500])
    num = re.search(r"\d+", code).group(0)
    rec = {
        "id": iid, "title": title, "text": text,
        "source_url": f"https://faolex.fao.org/docs/pdf/{FN}",
        "source_type": "faolex-cdx",
        "jurisdiction": "Georgia", "country": CC,
        "language": lang, "eli": None,
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

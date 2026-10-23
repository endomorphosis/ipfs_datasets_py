"""Small helpers shared by the states-lane archive adapters (in_state, at_ris, id_bpk_prov)."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import fcntl, json, os, re, subprocess, tempfile

import logging
_log = logging.getLogger("arch_common")
from common import OCR_MANIFEST, STAGING, LANE, check_guards, utcnow
from schema import place_key
from archive import provenance_fields

# html_extract / pdf_text / guess_date are imported read-only from the national lane's archive runner
import sys
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/archive"))
from run_archive import html_extract, guess_date  # noqa: E402,F401


def pdf_text(body: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(body); f.flush()
        try:
            out = subprocess.run(["pdftotext", "-q", "-layout", "-enc", "UTF-8", f.name, "-"], capture_output=True, timeout=180)
            return out.stdout.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            return ""


def has_text(t: str, min_chars=200) -> bool:
    return len("".join((t or "").split())) >= min_chars


def clean(t: str) -> str:
    t = re.sub(r"[ \t\u00a0]+", " ", t or "")
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def queue_scanned_pdf_archived(doc_id, place_id, cc, original_url, archive_url, source_policy, archive_timestamp=None,
                               sha256=None, archive_source=None, archive_crawl_id=None, content_type=None):
    """Append an image-only archived PDF to staging/states/_scanned_pdfs_manifest.jsonl, the World Law OCR input
    (keyed on place_key + doc_id; asia_latam/eap format). Every row carries place_key, the PDF's own source_url, and an
    archive link in archive_url (+ wayback_url for Wayback id_ links, + extra_metadata.archive), because the live host is
    blocked from the box and OCR must fetch the archived copy. Rows missing any of these are refused. Dedup by (place_key, doc_id)."""
    check_guards()
    pk = place_key(place_id)
    if not (pk and original_url and archive_url):
        _log.warning("OCR manifest row refused (needs place_key, source_url, archive link): %s", doc_id)
        return False
    is_pdf = bool(re.search(r"\.pdf(?:$|[?#])", original_url, re.I)) or "pdf" in (content_type or "").lower()
    if not is_pdf:
        _log.warning("OCR manifest row refused (source_url not a PDF): %s %s", doc_id, original_url)
        return False
    if not archive_source:
        archive_source = ("wayback" if "web.archive.org/" in archive_url else
                          "commoncrawl" if "commoncrawl.org/" in archive_url else None)
    wb = archive_url if (archive_source == "wayback" and "id_/" in archive_url) else None
    arch = {k: v for k, v in {"archive_source": archive_source, "archive_crawl_id": archive_crawl_id,
                              "archive_timestamp": archive_timestamp, "archive_url": archive_url,
                              "original_url": original_url}.items() if v}
    rec = {"doc_id": doc_id, "place_key": pk, "place_id": place_id, "country_code": cc, "source_url": original_url,
           "local_path": None, "ocr_done": False, "source_policy": source_policy, "lane": LANE,
           "law_file": f"hf://endomorphosis/world_national_law/world_law/data/{cc}/{pk}_html.parquet",
           "fetch_url": archive_url, "archive_url": archive_url, "archive_source": archive_source,
           "archive_timestamp": archive_timestamp, "sha256": sha256, "content_type": content_type or "application/pdf",
           "extra_metadata": {"archive": arch}, "queued_at": utcnow()}
    if wb:
        rec["wayback_url"] = wb
    STAGING.mkdir(parents=True, exist_ok=True)
    with open(OCR_MANIFEST.with_suffix(".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if OCR_MANIFEST.exists():
            for line in OCR_MANIFEST.open(encoding="utf-8"):
                try:
                    o = json.loads(line)
                    if (o["place_key"], o["doc_id"]) == (pk, doc_id):
                        return False
                except Exception:
                    pass
        with OCR_MANIFEST.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
            os.fsync(f.fileno())
    return True


def archived_rec(doc, policy, basis, **extra_meta):
    """Provenance fields for an archived doc + extra_metadata (archive + adapter extras)."""
    p = provenance_fields(doc, policy, basis)
    em = p.pop("extra_metadata")
    em.update({k: v for k, v in extra_meta.items() if v not in (None, "", [], {})})
    p["extra_metadata"] = em
    return p

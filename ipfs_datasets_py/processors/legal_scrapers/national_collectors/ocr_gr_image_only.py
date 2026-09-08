#!/usr/bin/env python3
"""Greece: OCR remaining image-only FEK A PDFs via official Azure blobs + tesseract ell+eng."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    DEFAULT_UA,
    ROOT,
    base_record,
    existing_ids,
    get_session,
    log_failure,
    slug_id,
    utcnow,
    write_instrument,
    write_summary,
    ensure_dirs,
)

CC, COUNTRY, SOURCE_TYPE = "gr", "Greece", "et_gr"
LICENSE = (
    "National Printing Office (Ethniko Typografeio) search.et.gr / et.gr official gazette FEK."
)
UA = DEFAULT_UA + " source=https://search.et.gr/"
BLOB_HOST = "ia37rg02wpsa01.blob.core.windows.net"
CORS = {"Origin": "https://search.et.gr", "Referer": "https://search.et.gr/"}
PDF_DIR = ROOT / CC / "raw" / "pdfs"
UNIQUE_PATH = ROOT / CC / "raw" / "image_only_unique.jsonl"
PROGRESS_PATH = ROOT / CC / "logs" / "ocr_progress.jsonl"
MAX_PAGES = 40
DPI = 200
OCR_LANG = "ell+eng"
MIN_CHARS = 400
WORKERS = 4
CATALOG_N = 6937

GREEK_RE = re.compile(r"[\u0370-\u03FF\u1F00-\u1FFF]")
log = logging.getLogger("gr-ocr")


def setup() -> None:
    ensure_dirs(CC)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "ocr.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_unique() -> list[dict]:
    rows = []
    seen = set()
    src = UNIQUE_PATH if UNIQUE_PATH.exists() else ROOT / CC / "failures.jsonl"
    for line in src.open(encoding="utf-8"):
        try:
            row = json.loads(line)
        except Exception:
            continue
        ident = row.get("identifier") or ""
        if not ident.startswith("FEK-"):
            continue
        if UNIQUE_PATH.exists():
            pass
        else:
            if row.get("reason") != "image_only_pdf_no_text_layer":
                continue
        if ident in seen:
            continue
        seen.add(ident)
        rows.append(row)
    rows.sort(key=lambda r: int(r.get("pages") or 10**9))
    return rows


def catalog_idx() -> dict:
    idx = {}
    p = ROOT / CC / "raw" / "catalog_fek.jsonl"
    if not p.exists():
        return idx
    for line in p.open(encoding="utf-8"):
        try:
            row = json.loads(line)
        except Exception:
            continue
        nid = row.get("norm_id")
        if nid:
            idx[nid] = row
    return idx


def is_statute_quality(text: str) -> bool:
    if not text or len(text) < MIN_CHARS:
        return False
    greek = len(GREEK_RE.findall(text))
    if greek < 80:
        return False
    letters = sum(1 for c in text if c.isalpha())
    if letters and (greek / letters) < 0.20:
        return False
    return True


def allowed_blob(url: str) -> bool:
    if not url:
        return False
    return url.startswith("https://ia37rg02wpsa01.blob.core.windows.net/fek/") and url.lower().endswith(".pdf")


def pdf_path_for(nid: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", nid)
    return PDF_DIR / f"{safe}.pdf"


def download_pdf(nid: str, url: str) -> tuple[str, str]:
    dest = pdf_path_for(nid)
    if dest.exists() and dest.stat().st_size > 1000:
        with dest.open("rb") as fh:
            magic = fh.read(5)
        if magic.startswith(b"%PDF"):
            return "ok_cached", str(dest)
    if not allowed_blob(url):
        return "bad_url", url
    last_err = ""
    for attempt in range(1, 5):
        try:
            time.sleep(0.25)
            r = get_session(UA).get(
                url,
                timeout=(20, 300),
                headers={**CORS, "User-Agent": UA},
                stream=True,
            )
            if r.status_code != 200:
                last_err = f"http_{r.status_code}"
                r.close()
                if r.status_code in (404, 410):
                    return last_err, url
                time.sleep(min(20, 2 ** attempt))
                continue
            tmp = dest.with_suffix(".part")
            size = 0
            with tmp.open("wb") as fh:
                for chunk in r.iter_content(1024 * 256):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    size += len(chunk)
                    if size > 400_000_000:
                        break
            r.close()
            if size < 1000:
                tmp.unlink(missing_ok=True)
                last_err = f"too_small_{size}"
                continue
            with tmp.open("rb") as fh:
                magic = fh.read(5)
            if not magic.startswith(b"%PDF"):
                tmp.unlink(missing_ok=True)
                last_err = "not_pdf"
                continue
            tmp.replace(dest)
            return "ok", str(dest)
        except Exception as exc:
            last_err = f"download:{exc}"
            time.sleep(min(20, 1.5 * attempt))
    return last_err or "download_fail", url


def _ocr_pdf_text(
    path: Path,
    *,
    max_pages: Optional[int] = None,
    dpi: int = 200,
    lang: str = "eng",
) -> Dict[str, Any]:
    """Copied from ipfs_datasets_py workspace_dataset._ocr_pdf_text with frombytes + timeout."""
    errors: list[str] = []
    page_texts: list[str] = []
    page_count = 0
    rendered = 0
    try:
        import fitz  # type: ignore
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore

        document = fitz.open(str(path))
        page_count = len(document)
        rendered_page_count = page_count
        if max_pages is not None:
            rendered_page_count = min(page_count, max(0, int(max_pages)))
        scale = max(72, int(dpi or 200)) / 72
        matrix = fitz.Matrix(scale, scale)
        for page_index in range(rendered_page_count):
            try:
                pixmap = document[page_index].get_pixmap(matrix=matrix, alpha=False)
                try:
                    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                except Exception:
                    image = Image.open(BytesIO(pixmap.tobytes("png")))
                page_texts.append(
                    str(
                        pytesseract.image_to_string(
                            image, lang=str(lang or "eng"), timeout=90
                        )
                        or ""
                    )
                )
                rendered += 1
            except Exception as exc:
                errors.append(f"tesseract_ocr_page_error:{exc}")
        try:
            document.close()
        except Exception:
            pass
    except Exception as exc:
        errors.append(f"tesseract_ocr:{exc}")
    return {
        "text": "\n\n".join(text.strip() for text in page_texts if text and text.strip()).strip(),
        "page_count": page_count,
        "rendered_pages": rendered,
        "backend": "tesseract_ocr",
        "errors": errors,
        "error": "; ".join(errors[-3:]),
    }


def ocr_worker(payload: dict) -> dict:
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    nid = payload["identifier"]
    pdf = Path(payload["pdf_path"])
    t0 = time.time()
    result = _ocr_pdf_text(pdf, max_pages=MAX_PAGES, dpi=DPI, lang=OCR_LANG)
    result["identifier"] = nid
    result["elapsed_s"] = round(time.time() - t0, 2)
    result["dpi"] = DPI
    result["lang"] = OCR_LANG
    result["pdf_path"] = str(pdf)
    return result


def append_progress(row: dict) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROGRESS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_done_ocr() -> set[str]:
    done = set()
    if not PROGRESS_PATH.exists():
        return done
    for line in PROGRESS_PATH.open(encoding="utf-8"):
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("status") in {"ok", "skip_existing"} and row.get("identifier"):
            done.add(row["identifier"])
    return done


def parse_date(idate: str) -> Optional[str]:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", idate or "")
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def write_one(nid: str, text: str, meta: dict, ocr: dict, url: str) -> None:
    title = meta.get("label") or nid
    rec = base_record(
        cc=CC,
        country=COUNTRY,
        language="el",
        ident=nid,
        title=title,
        text=text,
        source_url=url,
        source_type=SOURCE_TYPE,
        license_text=LICENSE,
        collector="gr-et-tesseract-ocr",
        eli=None,
        date=parse_date(meta.get("issue_date") or ""),
        official_identifier=title,
        document_type="gazette_act",
        law_status="unknown",
        is_current=None,
        extra_meta={
            "method_used": "tesseract_ocr",
            "ocr_lang": OCR_LANG,
            "text_extraction": {
                "source": "official",
                "backend": "tesseract_ocr",
                "lang": OCR_LANG,
                "dpi": DPI,
                "max_pages": MAX_PAGES,
                "page_count": ocr.get("page_count"),
                "rendered_pages": ocr.get("rendered_pages"),
                "ocr_chars": len(text),
            },
            "discovery": {
                "method": "image_only_tesseract_ocr",
                "search_id": meta.get("search_id"),
                "pages": meta.get("pages"),
            },
        },
    )
    write_instrument(CC, rec)


def maybe_summary(ok: int, skip: int, fail: int, notes: str) -> None:
    n_now = len(list((ROOT / CC / "instruments").glob("*.json")))
    write_summary(
        CC,
        country=COUNTRY,
        source="Ethniko Typografeio FEK A (search.et.gr / Azure blob) + tesseract OCR",
        source_urls=[
            "https://search.et.gr/",
            "https://www.et.gr/",
            "https://searchetv99.azurewebsites.net/api",
            "https://ia37rg02wpsa01.blob.core.windows.net/fek/",
        ],
        license_text=LICENSE,
        discovered=CATALOG_N,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete",
        notes=notes,
        last_run=utcnow(),
        extra=f"instruments_json_after={n_now}",
    )


def main() -> None:
    import multiprocessing as mp
    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        pass
    setup()
    t0 = utcnow()
    items = load_unique()
    cat = catalog_idx()
    existing = existing_ids(CC)
    progress_done = load_done_ocr()
    log.info(
        "unique_image_only=%s catalog=%s existing_instruments=%s progress_done=%s dpi=%s max_pages=%s workers=%s",
        len(items),
        len(cat),
        len(existing),
        len(progress_done),
        DPI,
        MAX_PAGES,
        WORKERS,
    )

    ok = skip = fail = downloaded = cached = ocr_garbage = 0
    to_ocr: list[dict] = []

    for n, row in enumerate(items, 1):
        nid = row["identifier"]
        rid = slug_id(CC, nid)
        inst = ROOT / CC / "instruments" / f"{rid}.json"
        if rid in existing and inst.exists():
            try:
                rec = json.loads(inst.read_text(encoding="utf-8"))
                if is_statute_quality(rec.get("text") or ""):
                    skip += 1
                    append_progress({"identifier": nid, "status": "skip_existing"})
                    continue
            except Exception:
                pass
        if nid in progress_done and inst.exists():
            skip += 1
            continue
        url = row.get("source_url") or ""
        meta = cat.get(nid) or {}
        if not url and meta:
            year = int(meta["year"])
            ig = int(meta.get("issue_group") or 1)
            num = int(meta["doc_number"])
            url = f"https://{BLOB_HOST}/fek/{ig:02d}/{year}/{year}{ig:02d}{num:05d}.pdf"
        st, path_or_err = download_pdf(nid, url)
        if st in {"ok", "ok_cached"}:
            if st == "ok":
                downloaded += 1
            else:
                cached += 1
            to_ocr.append(
                {
                    "identifier": nid,
                    "pdf_path": path_or_err,
                    "source_url": url,
                    "meta": {
                        "label": row.get("label") or meta.get("label"),
                        "issue_date": row.get("issue_date") or meta.get("issue_date"),
                        "search_id": row.get("search_id") or meta.get("search_id"),
                        "pages": row.get("pages") or meta.get("pages"),
                    },
                }
            )
        else:
            fail += 1
            log_failure(
                CC,
                {
                    "identifier": nid,
                    "source_url": url,
                    "status": "failed",
                    "reason": f"ocr_download_{st}",
                },
            )
            append_progress({"identifier": nid, "status": "download_fail", "reason": st})
        if n == 1 or n % 20 == 0:
            log.info(
                "download progress %s/%s new=%s cached=%s fail=%s queued_ocr=%s",
                n,
                len(items),
                downloaded,
                cached,
                fail,
                len(to_ocr),
            )

    log.info("downloads done new=%s cached=%s queued=%s fail=%s", downloaded, cached, len(to_ocr), fail)
    notes_mid = (
        f"OCR pass in progress. unique_image_only={len(items)} downloaded_new={downloaded} "
        f"cached={cached} queued={len(to_ocr)}. dpi={DPI} lang={OCR_LANG} max_pages={MAX_PAGES}."
    )
    maybe_summary(ok, skip, fail, notes_mid)

    meta_by_id = {x["identifier"]: x for x in to_ocr}
    if to_ocr:
        with ProcessPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(ocr_worker, {"identifier": x["identifier"], "pdf_path": x["pdf_path"]}): x["identifier"] for x in to_ocr}
            n_done = 0
            for fut in as_completed(futs):
                nid = futs[fut]
                n_done += 1
                item = meta_by_id[nid]
                try:
                    ocr = fut.result()
                except Exception as exc:
                    fail += 1
                    log_failure(
                        CC,
                        {
                            "identifier": nid,
                            "source_url": item["source_url"],
                            "status": "failed",
                            "reason": f"ocr_exc:{exc}",
                        },
                    )
                    append_progress({"identifier": nid, "status": "ocr_exc", "reason": repr(exc)})
                    log.info("ocr fail %s/%s %s exc=%s", n_done, len(to_ocr), nid, exc)
                    continue
                text = ocr.get("text") or ""
                quality = is_statute_quality(text)
                if quality:
                    write_one(nid, text, item["meta"], ocr, item["source_url"])
                    ok += 1
                    append_progress(
                        {
                            "identifier": nid,
                            "status": "ok",
                            "chars": len(text),
                            "pages": ocr.get("page_count"),
                            "rendered": ocr.get("rendered_pages"),
                            "elapsed_s": ocr.get("elapsed_s"),
                        }
                    )
                    log.info(
                        "ocr ok %s/%s %s chars=%s pages=%s/%s %.1fs",
                        n_done,
                        len(to_ocr),
                        nid,
                        len(text),
                        ocr.get("rendered_pages"),
                        ocr.get("page_count"),
                        ocr.get("elapsed_s") or 0,
                    )
                else:
                    fail += 1
                    ocr_garbage += 1
                    reason = "ocr_empty" if len(text) < MIN_CHARS else "ocr_garbage"
                    log_failure(
                        CC,
                        {
                            "identifier": nid,
                            "source_url": item["source_url"],
                            "status": "failed",
                            "reason": reason,
                            "ocr_chars": len(text),
                            "ocr_error": ocr.get("error") or "",
                        },
                    )
                    append_progress(
                        {
                            "identifier": nid,
                            "status": reason,
                            "chars": len(text),
                            "pages": ocr.get("page_count"),
                            "rendered": ocr.get("rendered_pages"),
                            "elapsed_s": ocr.get("elapsed_s"),
                            "error": ocr.get("error") or "",
                        }
                    )
                    log.info(
                        "ocr %s %s/%s %s chars=%s err=%s",
                        reason,
                        n_done,
                        len(to_ocr),
                        nid,
                        len(text),
                        (ocr.get("error") or "")[:120],
                    )
                if n_done == 1 or n_done % 10 == 0:
                    maybe_summary(
                        ok,
                        skip,
                        fail,
                        f"OCR in progress {n_done}/{len(to_ocr)} ok={ok} garbage={ocr_garbage} fail={fail} skip={skip}. "
                        f"dpi={DPI} lang={OCR_LANG} max_pages={MAX_PAGES}. started {t0}",
                    )

    n_now = len(list((ROOT / CC / "instruments").glob("*.json")))
    remaining = max(0, CATALOG_N - n_now)
    notes = (
        f"BEFORE instruments=6824 catalog=6937 remaining_image_only=164. "
        f"AFTER instruments={n_now} unique_image_only=164 downloaded_new={downloaded} cached={cached} "
        f"ocr_ok={ok} ocr_empty_or_garbage={ocr_garbage} skip_existing={skip} fail={fail}. "
        f"method_used=tesseract_ocr ocr_lang={OCR_LANG} dpi={DPI} max_pages={MAX_PAGES}. "
        f"Official Azure FEK blobs only; no cylaw; no HF upload. "
        f"REMAINING BLOCKER: {ocr_garbage + (fail - ocr_garbage)} image-only/OCR-fail FEKs; "
        f"catalog leftover ~{remaining}."
    )
    maybe_summary(ok, skip, fail, notes)
    log.info(
        "done unique=%s downloaded=%s cached=%s ocr_ok=%s garbage=%s skip=%s fail=%s instruments=%s",
        len(items),
        downloaded,
        cached,
        ok,
        ocr_garbage,
        skip,
        fail,
        n_now,
    )


if __name__ == "__main__":
    main()

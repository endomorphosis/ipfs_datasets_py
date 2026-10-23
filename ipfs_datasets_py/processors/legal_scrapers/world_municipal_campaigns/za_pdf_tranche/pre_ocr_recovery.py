"""OCR recovery driver for the 8 scanned-image works.

Identical OCR settings to za_pdf_tranche_build._ocr_one (300 dpi render,
tesseract -l <lang> --psm 6, OMP_THREAD_LIMIT=2, per-page checkpoint
files under texts/_ocr_pages/<pdf-sha16>/), with two operational fixes
for this VM's ~9% CPU duty cycle:

1. Per-page subprocess timeout raised from the builder's 1200 s to
   10800 s. At ~9% duty a dense page accumulates only ~110 CPU-s in
   1200 s wall — short of what the page needs — so the builder's
   timeout kills every page just before completion and the checkpoint
   never advances (observed 2026-10-13: all 8 workers timed out at
   exactly 1200 s, zero pages written).
2. Jobs are ordered smallest-PDF-first and results are consumed as
   completed, so whole works finish early and often.

Resumable: pages whose checkpoint file exists are skipped.
Expects the workspace tesseract root on PATH (see report).
"""
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
import za_pdf_tranche_build as B

TARGETS = [
    ("CPT", "sub-council-further-amendment"),
    ("WC023", "rules-of-order"),
    ("ETH", "mn/1999/7"),
    ("ETH", "mn/2012/20"),
    ("ETH", "mn/1998/50"),
    ("ETH", "water-supply"),
]
TIMEOUT = 10800


def ocr_one_long(job):
    pdf, i, lang, page_file = job
    import fitz
    doc = fitz.open(pdf)
    pix = doc[i].get_pixmap(dpi=300)
    png = B.OUT / f"_ocr_rec_{os.getpid()}.png"
    pix.save(png)
    doc.close()
    env = dict(os.environ, OMP_THREAD_LIMIT="2")
    t0 = time.time()
    try:
        out = subprocess.run(["tesseract", str(png), "stdout", "-l", lang,
                              "--psm", "6"],
                             capture_output=True, timeout=TIMEOUT, env=env)
        txt = out.stdout.decode("utf-8", errors="replace")
        if out.returncode != 0:
            return i, page_file, f"rc={out.returncode}", time.time() - t0
    finally:
        png.unlink(missing_ok=True)
    Path(page_file).write_text(txt)
    return i, page_file, f"{len(txt)} chars", time.time() - t0


def main():
    works = B.load_excluded()
    jobs = []
    import fitz
    for mdb, frag in TARGETS:
        w = [x for x in works if x["mdb"] == mdb and frag in x["work"]][0]
        p = B.pdf_path(w)
        doc = fitz.open(p)
        n = doc.page_count
        doc.close()
        sha = hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]
        pdir = B.TEXTS / "_ocr_pages" / sha
        pdir.mkdir(parents=True, exist_ok=True)
        todo = [i for i in range(n) if not (pdir / f"p{i:04d}.txt").exists()]
        print(f"{mdb} {frag}: {n} pages, {len(todo)} to OCR", flush=True)
        jobs += [(str(p), i, "eng", str(pdir / f"p{i:04d}.txt")) for i in todo]
    print(f"TOTAL jobs: {len(jobs)}", flush=True)
    if not jobs:
        print("PRE-OCR RECOVERY DONE (nothing to do)", flush=True)
        return
    import concurrent.futures
    done = 0
    with concurrent.futures.ProcessPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(ocr_one_long, j): j for j in jobs}
        for fut in concurrent.futures.as_completed(futs):
            j = futs[fut]
            try:
                i, pf, res, secs = fut.result()
                done += 1
                print(f"  [{done}/{len(jobs)}] {Path(pf).parent.name}/p{i:04d} "
                      f"{res} in {secs:.0f}s", flush=True)
            except Exception as exc:  # noqa: BLE001
                done += 1
                print(f"  [{done}/{len(jobs)}] FAILED {j[3]}: "
                      f"{type(exc).__name__} {str(exc)[:120]}", flush=True)
    print("PRE-OCR RECOVERY DONE", flush=True)


if __name__ == "__main__":
    main()

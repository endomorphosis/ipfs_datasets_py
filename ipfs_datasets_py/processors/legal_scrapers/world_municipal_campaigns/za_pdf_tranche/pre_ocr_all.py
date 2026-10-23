"""Union pre-OCR: fill per-page checkpoints for every OCR-dependent
work with a wide worker pool (the builder's own pool is 4-wide)."""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, ".")
import za_pdf_tranche_build as B

TARGETS = [
    ("CPT", "sub-council-further-amendment"),
    ("WC023", "rules-of-order"),
    ("ETH", "water-supply"),
    ("ETH", "mn/1998/50"),
    ("ETH", "mn/1999/7"),
    ("ETH", "mn/2012/20"),
]

works = B.load_excluded()
jobs = []
seen = set()
for mdb, frag in TARGETS:
    w = [x for x in works if x["mdb"] == mdb and frag in x["work"]][0]
    p = B.pdf_path(w)
    import fitz
    doc = fitz.open(p)
    n = doc.page_count
    doc.close()
    sha = hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]
    pdir = B.TEXTS / "_ocr_pages" / sha
    pdir.mkdir(parents=True, exist_ok=True)
    todo = 0
    for i in range(n):
        pf = pdir / f"p{i:04d}.txt"
        if not pf.exists() and (sha, i) not in seen:
            seen.add((sha, i))
            jobs.append((str(p), i, "eng", str(pf)))
            todo += 1
    print(f"{mdb} {frag}: {n} pages, {todo} to OCR", flush=True)

print(f"TOTAL jobs: {len(jobs)}", flush=True)
if jobs:
    import concurrent.futures
    done = 0
    with concurrent.futures.ProcessPoolExecutor(max_workers=8) as ex:
        for i, txt in ex.map(B._ocr_one, jobs):
            done += 1
            if done % 10 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)} pages done", flush=True)
print("PRE-OCR ALL DONE", flush=True)

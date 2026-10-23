"""Wave 14 near-blank render-reject probe: fitz pixmap rendering route.

Wave 13's OCR engine renders with pdftoppm; a small set of files OCR'd
to 0-85 chars that way (near-blank render rejects, wave-13 report
queue #5). Untried route: render each page with fitz (PyMuPDF) pixmap
at 300 dpi instead, OCR with the same workspace tesseract + env.

Probe semantics: renders every page to wave13/ocr_work/<job>/pNNNN.png
(overwriting any pdftoppm PNG) and OCRs in-memory for a verdict. It
does NOT write pNNNN.txt checkpoints. If the total clears 300 chars,
it zeroes any existing pNNNN.txt files so the standard lane (after a
stats scrub + rerun) re-OCRs from the fitz PNGs through its own save
path — one code path for instrument creation.

Usage: fitz_probe.py <pdf_path> <job_name> <lang>
Result: wave14/stats/fitz_probe_<job_name sanitized>.json
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, subprocess, sys
sys.path.insert(0, os.path.expanduser(
    '~/workspace/goals/global-law-scraping-coverage/hidden_files/wave13/scripts'))
from ocr13_engine import TESS_BIN, TESS_ENV, OCR_WORK

WAVE14_STATS = os.path.expanduser(
    '~/workspace/goals/global-law-scraping-coverage/hidden_files/wave14/stats')

def main():
    pdf_path, job_name, lang = sys.argv[1], sys.argv[2], sys.argv[3]
    import fitz
    work = os.path.join(OCR_WORK, job_name)
    os.makedirs(work, exist_ok=True)
    doc = fitz.open(pdf_path)
    n = len(doc)
    zoom = 300 / 72.0
    per_page = []
    total = 0
    for i in range(1, n + 1):
        page = doc[i - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        png = os.path.join(work, f'p{i:04d}.png')
        pix.save(png)
        del pix
        out = subprocess.run([TESS_BIN, png, 'stdout', '-l', lang],
                             capture_output=True, timeout=900, env=TESS_ENV)
        text = out.stdout.decode('utf-8', 'replace')
        per_page.append({'page': i, 'chars': len(text)})
        total += len(text)
        print(f'page {i}/{n}: {len(text)} chars', flush=True)
    doc.close()
    promising = total >= 300
    zeroed = 0
    if promising:
        for i in range(1, n + 1):
            tp = os.path.join(work, f'p{i:04d}.txt')
            if os.path.isfile(tp) and os.path.getsize(tp) > 0:
                with open(tp, 'w') as f:
                    f.write('')
                zeroed += 1
    res = {'pdf': pdf_path, 'job': job_name, 'lang': lang, 'pages': n,
           'total_chars': total, 'per_page': per_page,
           'promising': promising, 'txt_zeroed_for_rerun': zeroed}
    os.makedirs(WAVE14_STATS, exist_ok=True)
    safe = ''.join(c if c.isalnum() else '_' for c in job_name)[:80]
    json.dump(res, open(os.path.join(WAVE14_STATS, f'fitz_probe_{safe}.json'), 'w'), indent=1)
    print(json.dumps(res))

if __name__ == '__main__':
    main()

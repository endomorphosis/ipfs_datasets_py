"""Wave 13 page-checkpointed OCR engine (shared by the FAOLEX-bank and
CI douanes passes).

Wave <=12 OCR rendered a whole PDF to PNGs in a temp dir and OCR'd it
in one shot — an interruption lost everything. Here every page is
rendered once into a persistent work dir (wave13/ocr_work/<job>/) and
its OCR text checkpointed as pNNNN.txt; re-runs skip finished pages.

Tesseract: workspace-persisted binary (~/workspace/tools/tessroot) with
wave13/tessdata (wave-10 set + rus/kat/hrv/bos fetched from
tessdata_fast at wave start). System tesseract is never used (VM
replacements wipe apt installs).

Quality bar (a file is staged only if ALL hold):
 - total OCR chars >= 300
 - alphabetic ratio of the text >= 0.45
 - script check: for rus/kat jobs, >=50% of alphabetic chars in the
   expected script block; for Latin-script jobs, >=3 hits from a small
   per-language stopword list in the text.
Per-file metrics are recorded either way; failures stay excluded and
documented, per the wave brief.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, re, subprocess, sys

TESSROOT = os.path.expanduser('~/workspace/tools/tessroot/usr')
TESS_BIN = os.path.join(TESSROOT, 'bin', 'tesseract')
TESSDATA = os.path.expanduser('~/workspace/goals/global-law-scraping-coverage/hidden_files/wave13/tessdata')
TESS_ENV = dict(os.environ,
                LD_LIBRARY_PATH=os.path.join(TESSROOT, 'lib', 'x86_64-linux-gnu'),
                TESSDATA_PREFIX=TESSDATA)
OCR_WORK = os.path.expanduser('~/workspace/goals/global-law-scraping-coverage/hidden_files/wave13/ocr_work')

STOPWORDS = {
    'spa': ['el', 'la', 'de', 'que', 'en', 'los', 'del', 'se', 'las', 'un', 'una', 'por', 'con', 'no', 'es'],
    'fra': ['le', 'la', 'de', 'des', 'et', 'les', 'du', 'en', 'au', 'aux', 'est', 'une', 'dans', 'pour', 'qui'],
    'eng': ['the', 'of', 'and', 'to', 'in', 'is', 'for', 'on', 'as', 'by', 'an', 'be', 'or', 'with', 'this'],
    'por': ['de', 'a', 'o', 'que', 'e', 'do', 'da', 'em', 'um', 'para', 'com', 'os', 'no', 'se', 'na'],
    'hrv': ['i', 'u', 'je', 'se', 'na', 'da', 'za', 'od', 'o', 'su', 'sa', 'iz', 'po', 'koji', 'kao'],
    'bos': ['i', 'u', 'je', 'se', 'na', 'da', 'za', 'od', 'o', 'su', 'sa', 'iz', 'po', 'koji', 'kao'],
}
SCRIPT_RANGES = {'rus': 'Ѐ-ӿ', 'kat': 'Ⴀ-ჿ'}

def page_count(pdf_path):
    import fitz
    doc = fitz.open(pdf_path)
    n = len(doc)
    doc.close()
    return n

def ocr_pdf_pages(pdf_path, job_name, lang, dpi=300, max_pages=None):
    """OCR pdf page-wise with checkpoints. Returns (text, npages, done_pages)."""
    work = os.path.join(OCR_WORK, job_name)
    os.makedirs(work, exist_ok=True)
    n = page_count(pdf_path)
    if max_pages:
        n = min(n, max_pages)
    for i in range(1, n + 1):
        txt_path = os.path.join(work, f'p{i:04d}.txt')
        if os.path.isfile(txt_path) and os.path.getsize(txt_path) > 0:
            continue
        png_base = os.path.join(work, f'p{i:04d}')
        if not os.path.isfile(png_base + '.png'):
            # -singlefile: output is exactly <prefix>.png (without it
            # pdftoppm appends -<page>, which the checkpoint logic misses)
            try:
                r = subprocess.run(['pdftoppm', '-r', str(dpi), '-png', '-singlefile',
                                    '-f', str(i), '-l', str(i),
                                    pdf_path, png_base], capture_output=True, timeout=600)
                render_ok = r.returncode == 0
            except Exception:
                render_ok = False
            if not render_ok or not os.path.isfile(png_base + '.png'):
                with open(txt_path, 'w') as f: f.write('')
                continue
        try:
            out = subprocess.run([TESS_BIN, png_base + '.png', 'stdout', '-l', lang],
                                 capture_output=True, timeout=900, env=TESS_ENV)
            page_text = out.stdout.decode('utf-8', 'replace')
        except Exception:
            # Includes TimeoutExpired: a pathological page must not kill
            # the run — bank it as attempted-with-no-text and continue.
            # Its PNG is NOT unlinked below, so a future retry can
            # re-render/re-OCR it (empty txts are re-attempted on rerun).
            page_text = ''
        with open(txt_path, 'w') as f:
            f.write(page_text)
        if page_text.strip():
            try: os.unlink(png_base + '.png')
            except Exception: pass
    parts, done, attempted = [], 0, 0
    for i in range(1, n + 1):
        p = os.path.join(work, f'p{i:04d}.txt')
        if os.path.isfile(p):
            attempted += 1
            t = open(p, encoding='utf-8', errors='replace').read()
            parts.append(t)
            if t.strip():
                done += 1
    return '\n'.join(parts).strip(), n, attempted

def quality(text, lang_key):
    """Returns (ok, metrics). lang_key: tesseract lang used (spa/fra/eng/rus/kat/hrv/bos/por)."""
    chars = len(text)
    alpha = sum(1 for c in text if c.isalpha())
    alpha_ratio = (alpha / chars) if chars else 0.0
    m = {'chars': chars, 'alpha_ratio': round(alpha_ratio, 3)}
    ok = chars >= 300 and alpha_ratio >= 0.45
    if lang_key in SCRIPT_RANGES:
        lo, hi = SCRIPT_RANGES[lang_key][0], SCRIPT_RANGES[lang_key][-1]
        in_script = sum(1 for c in text if c.isalpha() and lo <= c <= hi)
        share = (in_script / alpha) if alpha else 0.0
        m['script_share'] = round(share, 3)
        ok = ok and share >= 0.5
    else:
        words = STOPWORDS.get(lang_key, STOPWORDS['eng'])
        low = ' ' + re.sub(r'[^a-zà-ÿ]+', ' ', text.lower()) + ' '
        hits = sum(low.count(f' {w} ') for w in words)
        m['stopword_hits'] = hits
        ok = ok and hits >= 3
    m['ok'] = bool(ok)
    return bool(ok), m

#!/usr/bin/env python3
"""Wave 11 El Salvador 'els' verification: enumerate the 'els' FAOLEX
prefix via Wayback CDX, fetch up to 2 sample PDFs (archive-first),
digital-extract (expected ~0 chars: scanned), OCR the first pages
(tesseract spa, 300 dpi, workspace-persisted binary — same setup as
wave10 ocr_wave10.py), and save the text to wave11/stats/els_verify.txt
for a human read. Only after this verifies as Salvadoran law may the
'els' harvest run.

Usage: ocr_verify_els.py [pages_per_doc=3]
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import importlib.util, json, os, re, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common11 import WAVE11

spec = importlib.util.spec_from_file_location('h11', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faolex_cdx_harvest11.py'))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)

_TESSROOT = os.path.expanduser('~/workspace/tools/tessroot/usr')
TESS_BIN = os.path.join(_TESSROOT, 'bin', 'tesseract')
WAVE10DIR = os.path.expanduser('~/workspace/goals/global-law-scraping-coverage/hidden_files/wave10')
TESS_ENV = dict(os.environ,
                LD_LIBRARY_PATH=os.path.join(_TESSROOT, 'lib', 'x86_64-linux-gnu'),
                TESSDATA_PREFIX=os.path.join(WAVE10DIR, 'tessdata'))

def ocr_first_pages(pdf_bytes, lang, max_pages):
    with tempfile.TemporaryDirectory(dir=WAVE11) as td:
        path = os.path.join(td, 'doc.pdf')
        open(path, 'wb').write(pdf_bytes)
        pref = os.path.join(td, 'pg')
        subprocess.run(['pdftoppm', '-r', '300', '-png', '-f', '1', '-l', str(max_pages), path, pref],
                       capture_output=True, timeout=1200)
        texts = []
        for fn in sorted(os.listdir(td)):
            if fn.endswith('.png'):
                out = subprocess.run([TESS_BIN, os.path.join(td, fn), 'stdout', '-l', lang],
                                     capture_output=True, timeout=900, env=TESS_ENV)
                texts.append(out.stdout.decode('utf-8', 'replace'))
    return '\n'.join(texts).strip()

def main():
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    files = h.cdx_files('els', 'sv')
    print(f'els enumerated_unique_files={len(files)}', flush=True)
    lines = [f"els enumeration: {len(files)} unique files (Wayback CDX, both FAO hosts)"]
    tried = 0
    for fn, (orig, ts) in sorted(files.items()):
        if tried >= 2:
            break
        data = h.get_binary(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=150)
        via = 'archive'
        if not (data and data[:4] == b'%PDF'):
            data = None
            for cand in (f"https://extwprlegs1.fao.org/docs/pdf/{fn}", f"https://faolex.fao.org/docs/pdf/{fn}"):
                data = h.get_binary(cand, timeout=30)
                if data and data[:4] == b'%PDF':
                    via = 'live'; break
                data = None
        if data is None:
            lines.append(f"\n===== {fn}: FETCH FAILED =====")
            continue
        tried += 1
        text, pages, meta = h.pdf_to_text_and_pages(data)
        lines.append(f"\n===== {fn} via={via} pages={pages} digital_chars={len(text.strip())} =====")
        print(f'{fn}: pages={pages} digital_chars={len(text.strip())}', flush=True)
        if len(text.strip()) >= 300:
            lines.append('[digital text present]\n' + text.strip()[:3000])
            continue
        print(f'{fn}: OCR first {max_pages} pages (spa)...', flush=True)
        t0 = time.time()
        ocr = ocr_first_pages(data, 'spa', max_pages)
        lines.append(f'[OCR spa, first {max_pages} pages, {time.time()-t0:.0f}s, {len(ocr)} chars]\n' + ocr[:4000])
        print(f'{fn}: ocr_chars={len(ocr)} in {time.time()-t0:.0f}s', flush=True)
    out = '\n'.join(lines)
    open(os.path.join(WAVE11, 'stats', 'els_verify.txt'), 'w').write(out)
    print('saved els_verify.txt')

if __name__ == '__main__':
    main()

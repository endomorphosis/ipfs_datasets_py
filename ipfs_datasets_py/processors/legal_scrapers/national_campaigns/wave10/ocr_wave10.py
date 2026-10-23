"""Wave 10 OCR pass: OCR saved no-text PDFs in wave9/ocr_pdfs/{cc}/ plus
re-download Vanuatu no-text candidates from its CDX cache (order = enumerated
sorted order). Recovered texts >=300 chars are written as instruments with
source_type faolex-ecolex-ocr (wave7 precedent for bi-faolex-bur112094).

Usage: ocr_wave10.py <cc> <lang> [--max N] [--from-cache]
 --from-cache: enumerate CDX cache for cc, skip HF/local ids, download PDFs,
   digital-extract first; only OCR those still <300 chars (counts them).
Without --from-cache: OCR the PDFs already saved in ocr_pdfs/{cc}/.
Counts are written to ../stats/ocr_{cc}.json
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import argparse, io, json, os, re, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common10 import TARGETS, WAVE10, PREFIX, norm

INST_BASE = os.path.expanduser('~/.ipfs_datasets/legal-corpora')
TODAY = time.strftime('%Y-%m-%d', time.gmtime())
# PREFIX comes from common10 (stats/targets.json)
# Tesseract: the apt binary vanished with a VM replacement on 2026-10-13;
# use the workspace-persisted binary with wave-10 tessdata (fra/spa/por/khm
# downloaded from tessdata_fast; eng/osd copied from the tools tessroot).
_TESSROOT = os.path.expanduser('~/workspace/tools/tessroot/usr')
TESS_BIN = os.path.join(_TESSROOT, 'bin', 'tesseract')
TESS_ENV = dict(os.environ,
                LD_LIBRARY_PATH=os.path.join(_TESSROOT, 'lib', 'x86_64-linux-gnu'),
                TESSDATA_PREFIX=os.path.join(WAVE10, 'tessdata'))

def count_articles(text):
    pats = [r'(?m)^\s*Article\s+\d+', r'(?m)^\s*ARTICLE\s+\d+',
            r'(?m)^\s*Art\.\s*\d+', r'(?m)^\s*Section\s+\d+']
    return max((len(re.findall(p, text)) for p in pats), default=0)

def ocr_pdf(path, lang):
    with tempfile.TemporaryDirectory(dir=os.path.expanduser('~/workspace/goals/global-law-scraping-coverage/hidden_files/wave10')) as td:
        pref = os.path.join(td, 'pg')
        subprocess.run(['pdftoppm', '-r', '300', '-png', path, pref],
                       capture_output=True, timeout=1200)
        texts = []
        for fn in sorted(os.listdir(td)):
            if fn.endswith('.png'):
                out = subprocess.run([TESS_BIN, os.path.join(td, fn), 'stdout',
                                      '-l', lang], capture_output=True, timeout=600,
                                     env=TESS_ENV)
                texts.append(out.stdout.decode('utf-8', 'replace'))
    return '\n'.join(texts).strip()

def derive_title(text):
    for line in text.splitlines():
        line = re.sub(r'\s+', ' ', line).strip()
        if len(line) >= 18 and not re.fullmatch(r'[\d\s\.\-_/]+', line):
            return line[:240]
    return 'Untitled FAOLEX document (OCR)'

def save(cc, iid, fn, text, orig_url):
    repo, display, _e, jurisdiction, default_lang = TARGETS[cc]
    num = re.search(r'\d+', fn[:-4]).group(0) if re.search(r'\d+', fn[:-4]) else iid
    ym = re.search(r'\b(19|20)\d{2}\b', text[:1500])
    rec = {'id': iid, 'title': derive_title(text), 'text': text,
           'source_url': f"https://faolex.fao.org/docs/pdf/{fn}",
           'source_type': 'faolex-ecolex-ocr',
           'jurisdiction': jurisdiction, 'country': cc,
           'language': default_lang, 'eli': None,
           'date': ym.group(0) if ym else None,
           'retrieved_at': TODAY + 'T00:00:00Z',
           'license': 'public-domain', 'law_status': 'unknown',
           'identifier': iid, 'official_identifier': f'LEX-FAOC{num}',
           'article_count': count_articles(text)}
    d = os.path.join(INST_BASE, cc, 'instruments'); os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, iid + '.json'), 'w') as f:
        json.dump(rec, f, ensure_ascii=False)
    return rec

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('cc'); ap.add_argument('lang')
    ap.add_argument('--max', type=int, default=1000)
    ap.add_argument('--from-cache', action='store_true')
    args = ap.parse_args(); cc = args.cc
    dedupe = json.load(open(os.path.join(WAVE10, 'dedupe', f'{cc}_dedupe.json')))
    hf_ids = {r['id'] for r in dedupe}; hf_titles = {r['norm_title'] for r in dedupe if r['norm_title']}
    inst_dir = os.path.join(INST_BASE, cc, 'instruments')
    local_ids = {f[:-5] for f in os.listdir(inst_dir)} if os.path.isdir(inst_dir) else set()
    stats = {'cc': cc, 'lang': args.lang, 'encountered_no_text': 0, 'ocr_done': 0,
             'recovered_ge300': 0, 'still_short': 0, 'dup': 0, 'items': []}
    jobs = []  # (fn, pdf_path_or_None, orig, ts)
    if args.from_cache:
        # wave9 cache first, else wave7 cache
        cache = os.path.join(WAVE10, 'stats', f'cdx_cache_{cc}.json')
        if not os.path.isfile(cache):
            cache = os.path.expanduser(f'~/workspace/goals/global-law-scraping-coverage/hidden_files/wave7/stats/cdx_cache_{cc}.json')
        files = {k: tuple(v) for k, v in json.load(open(cache)).items()}
        # need harvest module helpers for download/digital extract
        import importlib.util
        spec = importlib.util.spec_from_file_location('h8', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faolex_cdx_harvest10.py'))
        h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
        for fn, (orig, ts) in sorted(files.items()):
            if stats['ocr_done'] >= args.max: break
            iid = f"{cc}-faolex-{fn[:-4]}"
            if iid in hf_ids or iid in local_ids: continue
            data = None
            for cand in (f"https://extwprlegs1.fao.org/docs/pdf/{fn}", f"https://faolex.fao.org/docs/pdf/{fn}"):
                data = h.get_binary(cand)
                if data and data[:4] == b'%PDF': break
                data = None
            if data is None:
                data = h.get_binary(f"https://web.archive.org/web/{ts}id_/{orig}")
                if not (data and data[:4] == b'%PDF'): continue
            text, pages, _mt = h.pdf_to_text_and_pages(data)
            if len(text.strip()) >= 300: continue  # digital, harvester's job (already handled or dup-title)
            stats['encountered_no_text'] += 1
            ocr_dir = os.path.join(WAVE10, 'ocr_pdfs', cc); os.makedirs(ocr_dir, exist_ok=True)
            path = os.path.join(ocr_dir, fn)
            with open(path, 'wb') as f: f.write(data)
            jobs.append((fn, path, orig))
    else:
        ocr_dir = os.path.join(WAVE10, 'ocr_pdfs', cc)
        if os.path.isdir(ocr_dir):
            for fn in sorted(os.listdir(ocr_dir)):
                if fn.endswith('.pdf'):
                    iid = f"{cc}-faolex-{fn[:-4]}"
                    if iid in hf_ids or iid in local_ids:
                        stats['dup'] += 1; continue
                    stats['encountered_no_text'] += 1
                    jobs.append((fn, os.path.join(ocr_dir, fn), f"https://faolex.fao.org/docs/pdf/{fn}"))
    for fn, path, orig in jobs[:args.max]:
        iid = f"{cc}-faolex-{fn[:-4]}"
        try:
            text = ocr_pdf(path, args.lang)
        except Exception as e:
            stats['items'].append({'file': fn, 'error': str(e)[:200]}); continue
        stats['ocr_done'] += 1
        if len(text) >= 300:
            if norm(derive_title(text)) in hf_titles:
                stats['items'].append({'file': fn, 'ocr_chars': len(text), 'dup_title': True}); continue
            save(cc, iid, fn, text, orig); local_ids.add(iid)
            stats['recovered_ge300'] += 1
            stats['items'].append({'file': fn, 'ocr_chars': len(text), 'recovered': True})
        else:
            stats['still_short'] += 1
            stats['items'].append({'file': fn, 'ocr_chars': len(text), 'recovered': False})
        print(cc, fn, stats['ocr_done'], stats['recovered_ge300'], flush=True)
        json.dump(stats, open(os.path.join(WAVE10, 'stats', f'ocr_{cc}.json'), 'w'), indent=1)
    stats['deferred'] = max(0, stats['encountered_no_text'] - stats['ocr_done']) if not args.from_cache else 'see report: from-cache pass capped by --max / enumerated order'
    json.dump(stats, open(os.path.join(WAVE10, 'stats', f'ocr_{cc}.json'), 'w'), indent=1)
    print(json.dumps({k: v for k, v in stats.items() if k != 'items'}))

if __name__ == '__main__':
    main()

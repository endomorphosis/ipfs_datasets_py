"""Wave 13 FAOLEX harvester — wave-12 semantics, memory-hardened.

Enumeration: Wayback CDX over the two FAO legislation PDF hosts (the
robots-compliant route from waves 6/7/9-12; ECOLEX /result/ is NOT
used — robots-disallowed). Fetch: archive snapshot first, live FAO
hosts as fallback, streamed to disk under wave13/pdf_cache/.

Wave-13 change: extraction runs in a per-file child process
(extract_child.py, RLIMIT_AS-capped). Wave 12 lost the ba and sz
walks to single scanned PDFs whose in-process fitz/pdfplumber
extraction exhausted the VM's RAM; here a hostile file produces the
ledger disposition `blocker_extract_fail` (terminal for this wave,
documented in the report) and the walk continues.

State: walk ledger wave13/stats/walk_{cc}.jsonl (seeded from wave 12),
guarded prefix-skip wave13/stats/walk_prefix_{cc}.json (same rule as
wave 12: honored only when the reused CDX cache reproduces the exact
prior enumeration count). short_text PDFs are banked to
wave13/ocr_pdfs/{cc}/ for the OCR passes.

Usage: faolex_cdx_harvest13.py <cc> [--max-seconds N] [--max-new N]
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import argparse, json, os, re, subprocess, sys, time
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common13 import TARGETS, WAVE13, WAVE12, WAVE11, WAVE10, PREFIX, norm

INST_BASE = os.path.expanduser('~/.ipfs_datasets/legal-corpora')
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) legal-data-research/1.0'}
S = requests.Session(); S.headers.update(UA)
TODAY = time.strftime('%Y-%m-%d', time.gmtime())
CHILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'extract_child.py')
MAX_BYTES = 160_000_000  # streamed-download abort cap

def count_articles(text):
    pats = [r'(?m)^\s*Article\s+\d+', r'(?m)^\s*ARTICLE\s+\d+',
            r'(?m)^\s*Art\.\s*\d+', r'(?m)^\s*Secci[oó]n\s+\d+',
            r'(?m)^\s*المادة\s+\d+', r'(?m)^\s*Neni\s+\d+',
            r'(?m)^\s*Section\s+\d+']
    return max((len(re.findall(p, text)) for p in pats), default=0)

def stream_download(url, dest, timeout=240):
    """Stream url to dest; return bytes written or None. Aborts > MAX_BYTES."""
    try:
        with S.get(url, timeout=timeout, stream=True) as r:
            if r.status_code != 200:
                return None
            n = 0
            with open(dest, 'wb') as f:
                for ch in r.iter_content(1 << 16):
                    n += len(ch)
                    if n > MAX_BYTES:
                        f.close(); os.unlink(dest)
                        return None
                    f.write(ch)
            return n
    except Exception:
        try: os.unlink(dest)
        except Exception: pass
        return None

def is_pdf(path):
    try:
        with open(path, 'rb') as f:
            return f.read(4) == b'%PDF'
    except Exception:
        return False

def extract(path):
    """Run the capped child. Returns (text, pages, meta_title) or None on child death."""
    out = path + '.extract.json'
    try:
        r = subprocess.run([sys.executable, CHILD, path, out],
                           capture_output=True, timeout=600)
        if r.returncode != 0 or not os.path.isfile(out):
            return None
        d = json.load(open(out))
        os.unlink(out)
        return d['text'], d['pages'], d.get('meta_title') or ''
    except Exception:
        return None

def cdx_files(prefix, cc):
    """filename(lower) -> (original_url, timestamp) from both FAO hosts. Cached."""
    cache = os.path.join(WAVE13, 'stats', f'cdx_cache_{cc}.json')
    if not os.path.isfile(cache):
        for alt in (os.path.join(WAVE12, 'stats', f'cdx_cache_{cc}.json'),
                    os.path.join(WAVE11, 'stats', f'cdx_cache_{cc}.json'),
                    os.path.join(WAVE10, 'stats', f'cdx_cache_{cc}.json'),
                    os.path.expanduser(f'~/workspace/goals/global-law-scraping-coverage/hidden_files/wave7/stats/cdx_cache_{cc}.json')):
            if os.path.isfile(alt):
                cache = alt; break
    if os.path.isfile(cache):
        try:
            return {k: tuple(v) for k, v in json.load(open(cache)).items()}
        except Exception:
            pass
    found = {}
    for host in ('faolex.fao.org', 'extwprlegs1.fao.org'):
        url = (f"https://web.archive.org/cdx/search/cdx?url={host}/docs/pdf/{prefix}*"
               f"&output=json&limit=5000"
               f"&collapse=urlkey&fl=original,timestamp")
        for attempt in range(2):
            try:
                r = S.get(url, timeout=100)
                if r.status_code == 200 and r.text.strip().startswith('['):
                    rows = r.json()
                    for orig, ts in rows[1:]:
                        fn = orig.split('/')[-1].split('?')[0]
                        if re.fullmatch(rf"{prefix}\d+[a-z0-9]*\.pdf", fn.lower()):
                            found.setdefault(fn.lower(), (orig, ts))
                    break
            except Exception:
                time.sleep(3 * (attempt + 1))
    if found:
        try:
            json.dump(found, open(os.path.join(WAVE13, 'stats', f'cdx_cache_{cc}.json'), 'w'))
        except Exception:
            pass
    return found

def derive_title(text, meta_title):
    if meta_title and len(meta_title.strip()) >= 15 and 'untitled' not in meta_title.lower():
        return re.sub(r'\s+', ' ', meta_title).strip()[:240]
    for line in text.splitlines():
        line = re.sub(r'\s+', ' ', line).strip()
        if len(line) >= 18 and not re.fullmatch(r'[\d\s\.\-_/]+', line):
            return line[:240]
    for line in text.splitlines():
        line = re.sub(r'\s+', ' ', line).strip()
        if len(line) >= 8:
            return line[:240]
    return 'Untitled FAOLEX document'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cc')
    ap.add_argument('--max-seconds', type=int, default=1500)
    ap.add_argument('--max-new', type=int, default=100000)
    args = ap.parse_args()
    cc = args.cc
    repo, display, _eco, jurisdiction, default_lang = TARGETS[cc]
    prefix = PREFIX[cc]
    dedupe = json.load(open(os.path.join(WAVE13, 'dedupe', f'{cc}_dedupe.json')))
    hf_ids = {r['id'] for r in dedupe}
    hf_titles = {r['norm_title'] for r in dedupe if r['norm_title']}
    inst_dir = os.path.join(INST_BASE, cc, 'instruments')
    os.makedirs(inst_dir, exist_ok=True)
    local_ids = {f[:-5] for f in os.listdir(inst_dir) if f.endswith('.json')}
    cache_dir = os.path.join(WAVE13, 'pdf_cache', cc)
    os.makedirs(cache_dir, exist_ok=True)
    stats = {'cc': cc, 'enumerated': 0, 'written': 0, 'dup_id': 0, 'dup_title': 0,
             'short_text': 0, 'fetch_fail': 0, 'blocker_extract_fail': 0,
             'live': 0, 'archive': 0,
             'prior_prefix_skipped': 0, 'ledger_skipped': 0}
    ocr_inventory = []
    t0 = time.time()
    files = cdx_files(prefix, cc)
    stats['enumerated'] = len(files)
    ordered = sorted(files.items())
    pfx_path = os.path.join(WAVE13, 'stats', f'walk_prefix_{cc}.json')
    if os.path.isfile(pfx_path):
        try:
            pfx = json.load(open(pfx_path))
            if int(pfx.get('enumerated', -1)) == len(files) and int(pfx.get('skip', 0)) > 0:
                stats['prior_prefix_skipped'] = int(pfx['skip'])
                ordered = ordered[int(pfx['skip']):]
        except Exception:
            pass
    ledger_path = os.path.join(WAVE13, 'stats', f'walk_{cc}.jsonl')
    ledger = {}
    if os.path.isfile(ledger_path):
        for line in open(ledger_path):
            try:
                e = json.loads(line); ledger[e['fn']] = e['disp']
            except Exception:
                pass
    TERMINAL = {'written', 'dup_title', 'short_text', 'blocker_extract_fail'}
    ledger_f = open(ledger_path, 'a')
    def mark(fn_, disp):
        ledger[fn_] = disp
        ledger_f.write(json.dumps({'fn': fn_, 'disp': disp}) + '\n'); ledger_f.flush()
    for fn, (orig, ts) in ordered:
        if fn in ledger and ledger[fn] in TERMINAL:
            stats['ledger_skipped'] += 1
            continue
        if stats['written'] >= args.max_new or time.time() - t0 > args.max_seconds:
            stats['stopped_early'] = True
            break
        code = fn[:-4]
        iid = f"{cc}-faolex-{code}"
        if iid in hf_ids or iid in local_ids:
            stats['dup_id'] += 1
            continue
        dest = os.path.join(cache_dir, fn)
        via = None
        if not (os.path.isfile(dest) and is_pdf(dest)):
            n = stream_download(f"https://web.archive.org/web/{ts}id_/{orig}", dest, timeout=240)
            if n and is_pdf(dest):
                via = 'archive'
            else:
                for cand in (f"https://extwprlegs1.fao.org/docs/pdf/{fn}",
                             f"https://faolex.fao.org/docs/pdf/{fn}"):
                    n = stream_download(cand, dest, timeout=60)
                    if n and is_pdf(dest):
                        via = 'live'; break
                    via = None
        else:
            via = 'cache'
        if via is None:
            stats['fetch_fail'] += 1
            mark(fn, 'fetch_fail')
            continue
        stats[via if via in ('archive', 'live') else 'archive'] += 1
        got = extract(dest)
        if got is None:
            stats['blocker_extract_fail'] += 1
            mark(fn, 'blocker_extract_fail')
            print(f'{cc} {fn}: EXTRACT CHILD DIED (blocker)', flush=True)
            continue  # cache file kept for forensics / OCR attempt
        text, pages, meta_title = got
        text = text.strip()
        if len(text) < 300:
            stats['short_text'] += 1
            ocr_dir = os.path.join(WAVE13, 'ocr_pdfs', cc)
            os.makedirs(ocr_dir, exist_ok=True)
            try:
                os.replace(dest, os.path.join(ocr_dir, fn))
            except Exception:
                pass
            ocr_inventory.append({'file': fn, 'id': iid, 'pages': pages,
                                  'extracted_chars': len(text),
                                  'source_url': orig,
                                  'pdf_path': os.path.join(ocr_dir, fn)})
            mark(fn, 'short_text')
            continue
        title = derive_title(text, meta_title)
        if norm(title) and norm(title) in hf_titles:
            stats['dup_title'] += 1
            mark(fn, 'dup_title')
            try: os.unlink(dest)
            except Exception: pass
            continue
        lang = default_lang
        sample5k = text[:5000]
        if len(re.findall(r'[\u0600-\u06FF]', sample5k)) > 200:
            lang = 'fa' if cc == 'af' else 'ar'
        elif len(re.findall(r'[\u10A0-\u10FF]', sample5k)) > 200:
            lang = 'ka'
        elif len(re.findall(r'[\u0400-\u04FF]', sample5k)) > 200:
            lang = {'by': 'ru', 'ba': 'sr'}.get(cc, 'ru')
        elif len(re.findall(r'[\u1780-\u17FF]', sample5k)) > 100:
            lang = 'km'
        ym = re.search(r'\b(19|20)\d{2}\b', text[:1500])
        num = re.search(r'\d+', code).group(0)
        rec = {
            'id': iid, 'title': title, 'text': text,
            'source_url': f"https://faolex.fao.org/docs/pdf/{fn}",
            'source_type': 'faolex-cdx',
            'jurisdiction': jurisdiction, 'country': cc,
            'language': lang, 'eli': None,
            'date': ym.group(0) if ym else None,
            'retrieved_at': TODAY + 'T00:00:00Z',
            'license': 'public-domain', 'law_status': 'unknown',
            'identifier': iid, 'official_identifier': f'LEX-FAOC{num}',
            'article_count': count_articles(text),
        }
        with open(os.path.join(inst_dir, iid + '.json'), 'w') as f:
            json.dump(rec, f, ensure_ascii=False)
        local_ids.add(iid)
        stats['written'] += 1
        mark(fn, 'written')
        try: os.unlink(dest)
        except Exception: pass
        time.sleep(0.4)
    stats['ocr_inventory'] = ocr_inventory
    out = os.path.join(WAVE13, 'stats', f'faolex_{cc}_stats.json')
    json.dump(stats, open(out, 'w'), indent=1)
    print(json.dumps({k: v for k, v in stats.items() if k != 'ocr_inventory'}))

if __name__ == '__main__':
    main()

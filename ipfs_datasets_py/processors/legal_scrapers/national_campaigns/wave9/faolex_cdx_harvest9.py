"""Wave 9 FAOLEX harvester — robots-compliant ECOLEX-tail alternative.

ECOLEX's /result/ search path is robots-disallowed for User-agent: * in the
robots.txt served to this egress on 2026-10-12 (Disallow: /result/,
Crawl-delay: 30), so the wave-6/7 ECOLEX enumeration route is NOT used.

Enumeration instead uses the Wayback CDX API (web.archive.org) over the two
FAO legislation PDF hosts — the same discovery route as the repo's own
collect_er.py — and PDFs are fetched live from extwprlegs1.fao.org /
faolex.fao.org (falling back to the archived snapshot). Instrument IDs use
the wave-5/6 FAOLEX scheme ({cc}-faolex-{code}); LEX-FAOC number == the
numeric part of the PDF filename, so dedupe against live-HF ids is exact.
Digital-only extraction (fitz -> pdfplumber -> pdftotext), NO OCR, same as
wave 6: PDFs under 300 extracted chars are counted as OCR-deferred and, for
Burundi, inventoried with page counts (Lane C).

Usage: faolex_cdx_harvest.py <cc> [--max-seconds N] [--max-new N]
Reads dedupe from ../dedupe/{cc}_dedupe.json (relative to this script's
wave9 dir). Writes instrument JSONs to ~/.ipfs_datasets/legal-corpora/{cc}/instruments/
and stats to ../stats/faolex_{cc}_stats.json.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import argparse, io, json, os, re, subprocess, sys, tempfile, time, unicodedata
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common9 import TARGETS, WAVE9, norm

INST_BASE = os.path.expanduser('~/.ipfs_datasets/legal-corpora')
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) legal-data-research/1.0'}
S = requests.Session(); S.headers.update(UA)
PREFIX = {'vu': 'van', 'bi': 'bur', 'af': 'afg', 'gm': 'gam', 'gq': 'eqg',
          'so': 'som', 'ss': 'ssd', 'sr': 'sur', 'nu': 'niu', 'er': 'eri',
          'sd': 'sud', 'ls': 'les', 'pg': 'png'}
TODAY = time.strftime('%Y-%m-%d', time.gmtime())

def pdf_to_text_and_pages(data):
    text, pages = '', 0
    try:
        import fitz
        doc = fitz.open(stream=data, filetype='pdf')
        pages = len(doc)
        text = '\n'.join(pg.get_text() for pg in doc)
        meta_title = (doc.metadata or {}).get('title') or ''
        doc.close()
    except Exception:
        meta_title = ''
    if len(text.strip()) >= 300:
        return text, pages, meta_title
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = pages or len(pdf.pages)
            t = '\n'.join((pg.extract_text() or '') for pg in pdf.pages)
        if len(t.strip()) > len(text.strip()):
            text = t
    except Exception:
        pass
    if len(text.strip()) >= 300:
        return text, pages, meta_title
    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tf:
            tf.write(data); path = tf.name
        out = subprocess.run(['pdftotext', '-layout', path, '-'],
                             capture_output=True, timeout=180)
        os.unlink(path)
        t2 = out.stdout.decode('utf-8', 'replace')
        if len(t2) > len(text):
            text = t2
    except Exception:
        pass
    return text, pages, meta_title

def count_articles(text):
    pats = [r'(?m)^\s*Article\s+\d+', r'(?m)^\s*ARTICLE\s+\d+',
            r'(?m)^\s*Art\.\s*\d+', r'(?m)^\s*Secci[oó]n\s+\d+',
            r'(?m)^\s*المادة\s+\d+', r'(?m)^\s*Neni\s+\d+',
            r'(?m)^\s*Section\s+\d+']
    return max((len(re.findall(p, text)) for p in pats), default=0)

def get_binary(url, timeout=45):
    try:
        r = S.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.content
    except Exception:
        pass
    return None

def cdx_files(prefix, cc):
    """filename(lower) -> (original_url, timestamp) from both FAO hosts. Cached."""
    cache = os.path.join(WAVE9, 'stats', f'cdx_cache_{cc}.json')
    if not os.path.isfile(cache):
        alt = os.path.expanduser(f'~/workspace/goals/global-law-scraping-coverage/hidden_files/wave7/stats/cdx_cache_{cc}.json')
        if os.path.isfile(alt): cache = alt
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
            json.dump(found, open(os.path.join(WAVE9, 'stats', f'cdx_cache_{cc}.json'), 'w'))
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
    dedupe = json.load(open(os.path.join(WAVE9, 'dedupe', f'{cc}_dedupe.json')))
    hf_ids = {r['id'] for r in dedupe}
    hf_titles = {r['norm_title'] for r in dedupe if r['norm_title']}
    inst_dir = os.path.join(INST_BASE, cc, 'instruments')
    os.makedirs(inst_dir, exist_ok=True)
    local_ids = {f[:-5] for f in os.listdir(inst_dir) if f.endswith('.json')}
    stats = {'cc': cc, 'enumerated': 0, 'written': 0, 'dup_id': 0, 'dup_title': 0,
             'short_text': 0, 'fetch_fail': 0, 'live': 0, 'archive': 0}
    ocr_inventory = []
    t0 = time.time()
    files = cdx_files(prefix, cc)
    stats['enumerated'] = len(files)
    for fn, (orig, ts) in sorted(files.items()):
        if stats['written'] >= args.max_new or time.time() - t0 > args.max_seconds:
            stats['stopped_early'] = True
            break
        code = fn[:-4]
        iid = f"{cc}-faolex-{code}"
        if iid in hf_ids or iid in local_ids:
            stats['dup_id'] += 1
            continue
        data, via = None, None
        for cand in (f"https://extwprlegs1.fao.org/docs/pdf/{fn}",
                     f"https://faolex.fao.org/docs/pdf/{fn}"):
            data = get_binary(cand)
            if data and data[:4] == b'%PDF':
                via = 'live'; break
            data = None
        if data is None:
            data = get_binary(f"https://web.archive.org/web/{ts}id_/{orig}")
            if data and data[:4] == b'%PDF':
                via = 'archive'
            else:
                data = None
        if data is None:
            stats['fetch_fail'] += 1
            continue
        stats[via] += 1
        text, pages, meta_title = pdf_to_text_and_pages(data)
        text = text.strip()
        if len(text) < 300:
            stats['short_text'] += 1
            ocr_dir = os.path.join(WAVE9, 'ocr_pdfs', cc)
            os.makedirs(ocr_dir, exist_ok=True)
            try:
                with open(os.path.join(ocr_dir, fn), 'wb') as _f: _f.write(data)
            except Exception: pass
            ocr_inventory.append({'file': fn, 'id': iid, 'pages': pages,
                                  'extracted_chars': len(text),
                                  'source_url': orig, 'pdf_path': os.path.join(ocr_dir, fn)})
            continue
        title = derive_title(text, meta_title)
        if norm(title) and norm(title) in hf_titles:
            stats['dup_title'] += 1
            continue
        lang = default_lang
        if cc == 'af':
            arab = len(re.findall(r'[\u0600-\u06FF]', text[:5000]))
            if arab > 200:
                lang = 'fa'
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
        time.sleep(0.4)
    stats['ocr_inventory'] = ocr_inventory
    out = os.path.join(WAVE9, 'stats', f'faolex_{cc}_stats.json')
    json.dump(stats, open(out, 'w'), indent=1)
    print(json.dumps({k: v for k, v in stats.items() if k != 'ocr_inventory'}))

if __name__ == '__main__':
    main()

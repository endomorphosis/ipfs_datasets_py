"""Wave 13 Palau harvest — palaugov.pw ONLY (PacLII is robots-excluded;
wave-12 report §3). palaugov.pw robots.txt (fetched 2026-10-13) allows
public crawling (only /wp-admin/ disallowed).

Enumeration: Wayback CDX *index* queries over
www.palaugov.pw/wp-content/uploads/ (queries against archive.org's
index, not fetches of archived pages). Candidates are PDFs whose
filenames match legal-instrument patterns (Executive Order / RPPL /
Public Law / Proclamation / regulation) and whose normalized URL is
not already in the live repo. Fetches go to the LIVE site first
(robots-allowed), Wayback snapshot as fallback.

Discipline: a 4-file content sample is verified (Palau legal-instrument
text) before the full pass runs; the pass itself re-checks a Palau
marker in every extracted text. Records mimic the repo's existing
convention exactly (jurisdiction 'PW', country 'Palau', source_type
'palaugov_pw', identifier = original filename stem).

Usage: pw_harvest13.py [--sample-only] [--max-seconds N]
Ledger: wave13/stats/walk_pw.jsonl. Stats: wave13/stats/pw_harvest.json.
"""
import argparse, json, os, re, subprocess, sys, time, urllib.parse
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common13 import WAVE13, norm

INST_DIR = os.path.expanduser('~/.ipfs_datasets/legal-corpora/pw/instruments')
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) legal-data-research/1.0'}
S = requests.Session(); S.headers.update(UA)
TODAY = time.strftime('%Y-%m-%d', time.gmtime())
CHILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'extract_child.py')
LICENSE = ('Official Republic of Palau Public Laws (RPPL) and presidential '
           'legislations as published on palaugov.pw. The authentic official '
           'text prevails. Not legal advice.')
PATTERNS = [
    ('executive_order', re.compile(r'executive[-_ ]order', re.I)),
    ('rppl', re.compile(r'rppl', re.I)),
    ('public_law', re.compile(r'public[-_ ]law', re.I)),
    ('proclamation', re.compile(r'proclamation', re.I)),
    ('regulation', re.compile(r'regulation', re.I)),
    ('eo', re.compile(r'(^|[-_])eo[-_ ]?no', re.I)),
]
MARKER = re.compile(r'(Republic of Palau|Executive Order|RPPL|Public Law|Proclamation|WHEREAS)', re.I)

def norm_url(u):
    p = urllib.parse.urlparse(u)
    path = urllib.parse.unquote(p.path)
    return f"www.palaugov.pw{path}"

def slug_id(stem):
    s = re.sub(r'[^a-z0-9.]+', '-', stem.lower()).strip('-')
    return f'pw-{s}'

def enumerate_uploads():
    cache = os.path.join(WAVE13, 'stats', 'pw_cdx.json')
    if os.path.isfile(cache):
        return {k: tuple(v) for k, v in json.load(open(cache)).items()}
    found = {}
    prefixes = ['www.palaugov.pw/wp-content/uploads/'] + \
               [f'www.palaugov.pw/wp-content/uploads/{y}/' for y in range(2014, 2028)]
    for pref in prefixes:
        url = (f"https://web.archive.org/cdx/search/cdx?url={pref}"
               f"&matchType=prefix&output=json&fl=original,timestamp,statuscode"
               f"&collapse=urlkey&limit=4000")
        try:
            r = S.get(url, timeout=120)
            if r.status_code == 200 and r.text.strip().startswith('['):
                for orig, ts, sc in r.json()[1:]:
                    if sc != '200':
                        continue
                    fn = urllib.parse.unquote(orig.split('/')[-1].split('?')[0])
                    if fn.lower().endswith('.pdf'):
                        found.setdefault(norm_url(orig), (orig, ts))
        except Exception as e:
            print('cdx fail', pref, type(e).__name__, flush=True)
        time.sleep(1)
    json.dump(found, open(cache, 'w'))
    return found

def stream_download(url, dest, timeout=180):
    try:
        with S.get(url, timeout=timeout, stream=True) as r:
            if r.status_code != 200:
                return None
            n = 0
            with open(dest, 'wb') as f:
                for ch in r.iter_content(1 << 16):
                    n += len(ch)
                    if n > 80_000_000:
                        f.close(); os.unlink(dest); return None
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
    out = path + '.extract.json'
    try:
        r = subprocess.run([sys.executable, CHILD, path, out], capture_output=True, timeout=600)
        if r.returncode != 0 or not os.path.isfile(out):
            return None
        d = json.load(open(out)); os.unlink(out)
        return d['text'], d['pages'], d.get('meta_title') or ''
    except Exception:
        return None

def count_articles(text):
    pats = [r'(?m)^\s*Section\s+\d+', r'(?m)^\s*SECTION\s+\d+', r'(?m)^\s*Sec\.\s*\d+']
    return max((len(re.findall(p, text)) for p in pats), default=0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample-only', action='store_true')
    ap.add_argument('--max-seconds', type=int, default=7200)
    args = ap.parse_args()
    import pandas as pd
    remote = pd.read_parquet(os.path.join(WAVE13, 'dedupe', 'pw_remote.parquet'))
    have_urls = {norm_url(u) for u in remote['source_url'].astype(str)}
    have_ids = set(remote['id'].astype(str))
    have_titles = {norm(t) for t in remote['title'].astype(str)}
    files = enumerate_uploads()
    print('enumerated upload PDFs (unique, status 200):', len(files), flush=True)
    cands = []
    for nurl, (orig, ts) in sorted(files.items()):
        if nurl in have_urls:
            continue
        fn = nurl.split('/')[-1]
        stem = fn[:-4]
        pat = next((name for name, rx in PATTERNS if rx.search(fn)), None)
        if not pat:
            continue
        iid = slug_id(stem)
        if iid in have_ids:
            continue
        live = f"https://www.palaugov.pw{urllib.parse.urlparse(nurl).path if False else nurl[len('www.palaugov.pw'):]}"
        cands.append({'nurl': nurl, 'orig': orig, 'ts': ts, 'fn': fn, 'stem': stem,
                      'pattern': pat, 'id': iid, 'live_url': live})
    print('legal-pattern candidates not in repo:', len(cands), flush=True)
    json.dump(cands, open(os.path.join(WAVE13, 'stats', 'pw_candidates.json'), 'w'), indent=1)
    cache_dir = os.path.join(WAVE13, 'pdf_cache', 'pw'); os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(INST_DIR, exist_ok=True)
    ledger_path = os.path.join(WAVE13, 'stats', 'walk_pw.jsonl')
    ledger = {}
    if os.path.isfile(ledger_path):
        for line in open(ledger_path):
            try:
                e = json.loads(line); ledger[e['fn']] = e['disp']
            except Exception: pass
    lf = open(ledger_path, 'a')
    def mark(fn_, disp):
        ledger[fn_] = disp
        lf.write(json.dumps({'fn': fn_, 'disp': disp}) + '\n'); lf.flush()
    def process(c, sample=False):
        """Returns (disp, chars, marker_ok)."""
        dest = os.path.join(cache_dir, c['fn'])
        if not (os.path.isfile(dest) and is_pdf(dest)):
            n = stream_download(c['live_url'], dest, timeout=180)
            if not (n and is_pdf(dest)):
                n = stream_download(f"https://web.archive.org/web/{c['ts']}id_/{c['orig']}", dest, timeout=240)
                if not (n and is_pdf(dest)):
                    return 'fetch_fail', 0, False
        got = extract(dest)
        if got is None:
            return 'blocker_extract_fail', 0, False
        text, pages, meta = got
        text = text.strip()
        marker_ok = bool(MARKER.search(text[:4000])) and 'palau' in text[:4000].lower()
        if len(text) < 300:
            ocr_dir = os.path.join(WAVE13, 'ocr_pdfs', 'pw'); os.makedirs(ocr_dir, exist_ok=True)
            try: os.replace(dest, os.path.join(ocr_dir, c['fn']))
            except Exception: pass
            return 'short_text', len(text), marker_ok
        if sample:
            return 'sampled', len(text), marker_ok
        if not marker_ok:
            return 'content_reject', len(text), False
        title = ''
        if meta and len(meta.strip()) >= 15 and 'untitled' not in meta.lower():
            title = re.sub(r'\s+', ' ', meta).strip()[:240]
        if not title:
            for line in text.splitlines():
                line = re.sub(r'\s+', ' ', line).strip()
                if len(line) >= 18 and not re.fullmatch(r'[\d\s\.\-_/]+', line):
                    title = line[:240]; break
        if not title:
            title = re.sub(r'[-_]+', ' ', c['stem']).strip()[:240]
        if norm(title) in have_titles:
            return 'dup_title', len(text), marker_ok
        ym = re.search(r'\b(19|20)\d{2}\b', text[:2000]) or re.search(r'\b(19|20)\d{2}\b', c['fn'])
        doc_type = 'statute' if c['pattern'] in ('rppl', 'public_law') else \
                   ('executive_order' if c['pattern'] in ('executive_order', 'eo') else 'document')
        rec = {'id': c['id'], 'title': title, 'text': text,
               'source_url': c['live_url'], 'source_type': 'palaugov_pw',
               'jurisdiction': 'PW', 'country': 'Palau', 'language': 'en',
               'eli': None, 'date': f'{ym.group(0)}-01-01' if ym else None,
               'retrieved_at': TODAY + 'T00:00:00Z', 'license': LICENSE,
               'law_status': 'current', 'identifier': c['stem'],
               'official_identifier': c['stem'],
               'article_count': count_articles(text),
               'schema_version': 'collection_record.v1', 'record_type': 'law',
               'law_identifier': c['stem'], 'document_type': doc_type,
               'is_current': True, 'canonical_law_url': c['live_url'],
               'article_extraction_status': 'missing',
               'metadata': {'collector': 'wave13 palaugov harvest (palaugov.pw)',
                            'schema': 'collection_record.v1',
                            'source_host': 'www.palaugov.pw'}}
        with open(os.path.join(INST_DIR, c['id'] + '.json'), 'w') as f:
            json.dump(rec, f, ensure_ascii=False)
        have_titles.add(norm(title))
        try: os.unlink(dest)
        except Exception: pass
        return 'written', len(text), marker_ok
    stats = {'enumerated': len(files), 'candidates': len(cands)}
    if args.sample_only:
        verdicts = []
        for c in cands[:4]:
            disp, chars, mok = process(c, sample=True)
            verdicts.append({'fn': c['fn'], 'pattern': c['pattern'], 'disp': disp,
                             'chars': chars, 'marker_ok': mok})
            print('SAMPLE', verdicts[-1], flush=True)
        stats['sample'] = verdicts
        json.dump(stats, open(os.path.join(WAVE13, 'stats', 'pw_harvest.json'), 'w'), indent=1)
        return 0
    from collections import Counter
    cnt = Counter()
    t0 = time.time()
    for c in cands:
        if c['fn'] in ledger and ledger[c['fn']] in ('written', 'dup_title', 'short_text', 'content_reject', 'blocker_extract_fail'):
            cnt['ledger_skipped'] += 1; continue
        if time.time() - t0 > args.max_seconds:
            cnt['stopped_early'] += 1; break
        disp, chars, mok = process(c)
        cnt[disp] += 1
        mark(c['fn'], disp)
        print(c['fn'], disp, chars, flush=True)
    stats['outcomes'] = dict(cnt)
    json.dump(stats, open(os.path.join(WAVE13, 'stats', 'pw_harvest.json'), 'w'), indent=1)
    print(json.dumps(stats))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

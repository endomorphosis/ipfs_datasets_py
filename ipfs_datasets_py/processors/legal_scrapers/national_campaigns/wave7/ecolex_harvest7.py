"""Wave 6 ECOLEX->FAOLEX harvester.

Enumerates ECOLEX legislation records for one country (xcountry facet),
follows each record's full-text PDF (FAO legislation server / FAOLEX),
extracts text, dedupes against live-HF ids+titles (/tmp/wave7/{cc}_dedupe.json)
and local instruments, and writes instrument JSONs in the wave-5 format to
~/.ipfs_datasets/legal-corpora/{cc}/instruments/.

Usage: ecolex_harvest.py <cc> <ecolex_country_name> <jurisdiction> <default_lang>
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, re, sys, json, time, unicodedata, html as htmlmod
import requests

sys.path.insert(0, os.path.expanduser('~/workspace/wave5'))

def pdf_to_text(data):
    """Digital-only extraction (fitz -> pdfplumber -> pdftotext). No OCR:
    scanned-only PDFs return <300 chars and are counted as OCR-deferred."""
    import io, subprocess, tempfile
    text = ''
    try:
        import fitz
        doc = fitz.open(stream=data, filetype='pdf')
        text = '\n'.join(pg.get_text() for pg in doc)
        doc.close()
    except Exception:
        text = ''
    if len(text.strip()) >= 300:
        return text
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text = '\n'.join((pg.extract_text() or '') for pg in pdf.pages)
    except Exception:
        pass
    if len(text.strip()) >= 300:
        return text
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
    return text

INST_BASE = os.path.expanduser('~/.ipfs_datasets/legal-corpora')
TODAY = '2026-10-12'
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) legal-data-research/1.0'}
S = requests.Session(); S.headers.update(UA)

LANGMAP = {'english': 'en', 'french': 'fr', 'spanish': 'es', 'portuguese': 'pt',
           'arabic': 'ar', 'russian': 'ru', 'albanian': 'sq', 'serbian': 'sr',
           'dari': 'fa', 'pashto': 'ps', 'somali': 'so', 'korean': 'ko'}

def norm(t):
    t = unicodedata.normalize('NFKD', str(t or '')).lower()
    t = re.sub(r'[^a-z0-9\u0600-\u06FF\u0400-\u04FF\u4E00-\u9FFF]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

def count_articles(text):
    pats = [r'(?m)^\s*Article\s+\d+', r'(?m)^\s*ARTICLE\s+\d+',
            r'(?m)^\s*Art\.\s*\d+', r'(?m)^\s*Secci[oó]n\s+\d+',
            r'(?m)^\s*المادة\s+\d+', r'(?m)^\s*Neni\s+\d+']
    return max((len(re.findall(p, text)) for p in pats), default=0)

def get(url, timeout=60, binary=False):
    for attempt in range(3):
        try:
            r = S.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.content if binary else r.text
            if r.status_code in (404, 403):
                return None
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None

def main():
    cc, country_name, jurisdiction, default_lang = sys.argv[1:5]
    dedupe = json.load(open(f'/tmp/wave7/{cc}_dedupe.json'))
    hf_ids = {r['id'] for r in dedupe}
    hf_titles = {r['norm_title'] for r in dedupe if r['norm_title']}
    inst_dir = os.path.join(INST_BASE, cc, 'instruments')
    os.makedirs(inst_dir, exist_ok=True)
    local_ids = {f[:-5] for f in os.listdir(inst_dir) if f.endswith('.json')}
    stats = {'enumerated': 0, 'written': 0, 'dup_id': 0, 'dup_title': 0,
             'no_pdf': 0, 'short_text': 0, 'errors': 0, 'juris_mismatch': 0}
    seen_codes = set()

    page = 1
    while True:
        url = (f"https://www.ecolex.org/result/?type=legislation"
               f"&xcountry={requests.utils.quote(country_name)}&page={page}")
        htmltxt = get(url)
        if not htmltxt:
            break
        items = []
        for href, title_raw in re.findall(
                r'href="(/details/legislation/[^"]+)"[^>]*?title="([^"]*)"', htmltxt):
            fm = re.search(r'-lex-faoc(\d+)', href)
            items.append((href, fm.group(1) if fm else None, title_raw))
        juris = re.findall(r'sr-jurisdiction[^>]*>([^<]+)</span>', htmltxt)
        if not items:
            break
        for i, (path, num, title_raw) in enumerate(items):
            stats['enumerated'] += 1
            if i < len(juris) and htmlmod.unescape(juris[i]).strip() != country_name:
                stats['juris_mismatch'] += 1
                continue
            if num is not None:
                if num in seen_codes:
                    continue
                seen_codes.add(num)
            title = re.sub(r'\s+', ' ', htmlmod.unescape(title_raw)).strip()
            detail = get('https://www.ecolex.org' + path.split('?')[0])
            if not detail:
                stats['errors'] += 1
                continue
            if num is None:
                fm = re.search(r'LEX-FAOC(\d+)', detail)
                if not fm:
                    stats['no_pdf'] += 1
                    continue
                num = fm.group(1)
            pdfs = re.findall(r'href="(https?://(?:extwprlegs1\.fao\.org|faolex\.fao\.org)/docs/pdf/([^"]+\.pdf))"',
                              detail, re.I)
            if not pdfs:
                stats['no_pdf'] += 1
                continue
            pdf_url, pdf_file = pdfs[0]
            code = pdf_file[:-4]  # e.g. AFG184383
            iid = f"{cc}-faolex-{code.lower()}"
            if iid in hf_ids or iid in local_ids:
                stats['dup_id'] += 1
                continue
            if norm(title) and norm(title) in hf_titles:
                stats['dup_title'] += 1
                continue
            data = get(pdf_url, timeout=120, binary=True)
            if not data or data[:4] != b'%PDF':
                # fallback host
                alt = f"https://faolex.fao.org/docs/pdf/{pdf_file}"
                data = get(alt, timeout=120, binary=True) if alt != pdf_url else None
            if not data or data[:4] != b'%PDF':
                stats['errors'] += 1
                continue
            text = pdf_to_text(data).strip()
            if len(text) < 300:
                stats['short_text'] += 1
                try:
                    import fitz
                    _doc = fitz.open(stream=data, filetype='pdf')
                    _pages = _doc.page_count; _doc.close()
                except Exception:
                    _pages = None
                with open(f'/tmp/wave7/scanned_{cc}.jsonl', 'a') as _sf:
                    _sf.write(json.dumps({'cc': cc, 'iid': iid, 'title': title,
                        'pdf_url': pdf_url, 'pdf_file': pdf_file, 'pages': _pages,
                        'bytes': len(data), 'digital_chars': len(text)}) + '\n')
                if cc == 'bi':
                    try:
                        with open(f'/tmp/wave7/bi_scanned/{pdf_file}', 'wb') as _bf:
                            _bf.write(data)
                    except Exception:
                        pass
                continue
            lang = default_lang
            lm = re.search(r'Language:</[^>]+>\s*<[^>]+>([^<]+)', detail)
            if lm:
                lang = LANGMAP.get(lm.group(1).strip().lower(), default_lang)
            ym = re.search(r'(?:Date of text|Year)</[^>]+>\s*<[^>]+>\s*(\d{4})', detail)
            rec = {
                'id': iid, 'title': title, 'text': text,
                'source_url': pdf_url,
                'source_type': 'faolex-ecolex',
                'jurisdiction': jurisdiction, 'country': cc,
                'language': lang, 'eli': None,
                'date': ym.group(1) if ym else None,
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
        page += 1
        if page > 60:
            break
    print(json.dumps({'cc': cc, **stats}))
    with open(f'/tmp/wave7/ecolex_{cc}_stats.json', 'w') as f:
        json.dump(stats, f)

if __name__ == '__main__':
    main()

"""PH LGU ordinance/resolution/EO crawler (ph lane).
Templates: wordpress (WP REST API search + media + bounded HTML crawl), generic (bounded same-host HTML crawl;
covers custom/static, gov.ph GWT, laravel, nextjs SSR, wix). Output: staging/ph/PH/<place_key>.<batch>.jsonl.
Resumable: _state/done.jsonl lists finished places. Usage: ph_crawl.py [--places a,b] [--limit N] [--workers N]
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, re, json, time, hashlib, subprocess, tempfile, argparse, datetime, traceback
from urllib.parse import urljoin, urlparse, urldefrag
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline'))
import phnet
from schema import place_key, validate_file, validate_record
from bs4 import BeautifulSoup
ST = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/ph/_state'); OUT = os.environ.get('PH_OUT', '/workspace/world_law/staging/ph')
KW = re.compile(r'\b(ordinances?|resolutions?|executive\s+orders?|e\.?\s?o\.?\s+no|kautusan|sangguniang?\s+(bayan|panlalawigan|panlungsod)|legislati|SB\s+res|appropriation\s+ord|municipal\s+ord|tax\s+code|revenue\s+code|code\s+of\s+general)', re.I)
DOCKW = re.compile(r'\b(ordinance|resolution|executive[\s_-]*order|\bEO[\s_-]*(no|\d)|kautusan|revenue[\s_-]*code|tax[\s_-]*code|appropriation)', re.I)
BAD = re.compile(r'(bid|invitation|procurement|rfq|philgeps|vacanc|job|tourism|festival|wp-login|/feed|/tag/|/author/|facebook|twitter|youtube|instagram|mailto:|tel:|\.(jpg|jpeg|png|gif|zip|rar|mp4|docx?|xlsx?)$)', re.I)
NUM = re.compile(r'\b(ordinance|resolution|reso|executive\s+order|e\.?\s?o)[\s\-_.]*(?:no\.?|number|#)?[\s\-_.]*[:.]?\s*((?:\d{2,4}\s?[-–/]\s?)?\d{1,4}(?:\s?[-–/]\s?\d{1,4})*(?:[-–/]?[A-Z]\b)?)', re.I)
MON = 'january|february|march|april|may|june|july|august|september|october|november|december'
DATE = re.compile(r'(?:(%s)\.?\s+(\d{1,2}),?\s+(\d{4}))|(\d{4})-(\d{2})-(\d{2})' % MON, re.I)
MAXPAGES, MAXDOCS, MAXPDF = 120, int(os.environ.get('PH_MAXDOCS', '1500')), 25_000_000
now = lambda: datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
import threading
OCR_SEM = threading.Semaphore(int(os.environ.get('PH_OCR', '3'))); OCR_PAGES = int(os.environ.get('PH_OCR_PAGES', '3'))

def doctype(t):
    t = t.lower()
    if 'ordinance' in t or 'code' in t: return 'ordinance'
    if 'executive' in t or re.search(r'\beo\b', t): return 'decision'
    return 'decision'
def kind(t):
    t = t.lower()
    return 'ordinance' if 'ordinance' in t or 'code' in t else 'executive_order' if ('executive' in t or re.search(r'\beo\b', t)) else 'resolution'
def parse_num(t):
    m = NUM.search(t or '')
    if not m: return None
    w = re.sub(r'\s+', ' ', m.group(1)).title(); w = 'Executive Order' if w.replace('.', '').replace(' ', '').lower() == 'eo' else w
    w = 'Resolution' if w.lower() == 'reso' else w
    ser = re.match(r'[\s,]*(?:s\.?|series(?:\s+of)?)\s*(\d{4})', t[m.end():], re.I)
    if ser: return f"{w} No. {re.sub(r'\s*([-–/])\s*', r'\1', m.group(2)).replace('–', '-')} s. {ser.group(1)}"
    return f"{w} No. {re.sub(r'\s*([-–/])\s*', r'\1', m.group(2)).replace('–', '-')}"
def parse_date(t):
    m = DATE.search(t or '')
    if not m: return None
    if m.group(1):
        mo = MON.split('|').index(m.group(1).lower()) + 1; y = int(m.group(3))
        if 1946 <= y <= 2027: return f"{y:04d}-{mo:02d}-{int(m.group(2)):02d}"
    else:
        y = int(m.group(4))
        if 1946 <= y <= 2027 and 1 <= int(m.group(5)) <= 12: return f"{m.group(4)}-{m.group(5)}-{m.group(6)}"
def year_from(t):
    m = re.search(r'\b(19[5-9]\d|20[0-2]\d)\b', t or ''); return m.group(1) if m else None

def pdf_text(url, allow_ocr=True):
    r, pol = phnet.get(url, timeout=int(os.environ.get('PDF_TIMEOUT', '60')), stream=True)
    if r is None or r.status_code != 200: return None, pol, None
    data = b''
    try:
      for ch in r.iter_content(65536):
        data += ch
        if len(data) > MAXPDF: return None, pol, 'too_large'
    except Exception as e:
        return None, 'error:' + type(e).__name__, 'stream_error'
    if not data.startswith(b'%PDF'): return None, pol, 'not_pdf'
    with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
        f.write(data); f.flush()
        try: txt = subprocess.run(['pdftotext', '-layout', '-l', '60', f.name, '-'], capture_output=True, timeout=120).stdout.decode('utf-8', 'replace')
        except Exception: txt = ''
        npages = 0
        try:
            m = re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', f.name], capture_output=True, timeout=30).stdout.decode()); npages = int(m.group(1)) if m else 0
        except Exception: pass
        ocr = False
        if allow_ocr and OCR_PAGES > 0 and len(re.sub(r'\s', '', txt)) < 100 * max(1, min(npages, 3)):
            with OCR_SEM, tempfile.TemporaryDirectory() as td:
                try:
                    subprocess.run(['pdftoppm', '-r', '200', '-gray', '-l', str(OCR_PAGES), '-png', f.name, td + '/p'], timeout=300, capture_output=True)
                    parts = []
                    for img in sorted(os.listdir(td)):
                        parts.append(subprocess.run(['tesseract', td + '/' + img, '-', '-l', 'eng'], capture_output=True, timeout=180).stdout.decode('utf-8', 'replace'))
                    if parts: txt, ocr = '\n\f'.join(parts), True
                except Exception: pass
    return txt, pol, dict(sha1=hashlib.sha1(data).hexdigest(), pages=npages, ocr=ocr, bytes=len(data))

def page_text(soup):
    for s in soup(['script', 'style', 'nav', 'header', 'footer', 'form', 'noscript']): s.decompose()
    main = soup.find('article') or soup.find(class_=re.compile('entry-content|post-content|content')) or soup.body or soup
    return re.sub(r'\n\s*\n+', '\n\n', main.get_text('\n', strip=True))

class Site:
    def __init__(s, place, base, policy, tmpl):
        s.p, s.base, s.policy, s.tmpl = place, base, policy, tmpl
        s.host = urlparse(base).netloc.lower().removeprefix('www.')
        s.cands = {}   # url -> dict(title, context)
        s.pages_seen = set(); s.htmldocs = {}
    def same(s, u): return urlparse(u).netloc.lower().removeprefix('www.') == s.host
    def add(s, url, title, ctx, src):
        url = urldefrag(url)[0]
        if url in s.cands or BAD.search(url.split('?')[0]) and not url.lower().endswith('.pdf'): return
        s.cands[url] = dict(title=re.sub(r'\s+', ' ', title or '').strip()[:300], ctx=ctx[:300], src=src)

    def wp(s):
        api = s.base.rstrip('/') + '/wp-json/wp/v2/'
        for term in ('ordinance', 'resolution', 'executive order'):
            for page in range(1, 6):
                r, _ = phnet.get(api + f'media?search={term.replace(" ", "+")}&per_page=100&page={page}', timeout=30)
                if r is None or r.status_code != 200: break
                try: js = r.json()
                except Exception: break
                if not isinstance(js, list) or not js: break
                for m in js:
                    u = m.get('source_url') or ''; t = (m.get('title') or {}).get('rendered', '')
                    if u.lower().endswith('.pdf') and DOCKW.search(t + ' ' + u): s.add(u, BeautifulSoup(t, 'html.parser').get_text(), m.get('date', ''), 'wp_media')
                if len(js) < 100: break
            r, _ = phnet.get(api + f'search?search={term.replace(" ", "+")}&per_page=50', timeout=30)
            if r is not None and r.status_code == 200:
                try:
                    for it in r.json(): s.crawl_q.append(it.get('url'))
                except Exception: pass

    def crawl(s):
        q = [s.base] + getattr(s, 'crawl_q', []); depth = {s.base: 0}
        for u in s.crawl_q: depth[u] = 1
        while q and len(s.pages_seen) < MAXPAGES and len(s.cands) < MAXDOCS:
            u = q.pop(0)
            if not u or u in s.pages_seen or not s.same(u): continue
            s.pages_seen.add(u)
            r, pol = phnet.get(u, timeout=30)
            if r is None or r.status_code != 200 or 'html' not in r.headers.get('content-type', ''): continue
            soup = BeautifulSoup(r.text[:2_000_000], 'html.parser')
            ptitle = (soup.title.get_text() if soup.title else '')
            # the page itself may be an ordinance (HTML text)
            h1 = soup.find(['h1', 'h2']); h1t = h1.get_text(' ', strip=True) if h1 else ptitle
            if depth[u] > 0 and NUM.search(h1t) and DOCKW.search(h1t):
                s.htmldocs[u] = dict(title=h1t, soup=soup)
            for a in soup.find_all('a', href=True):
                href = urljoin(r.url, a['href'].strip()); t = a.get_text(' ', strip=True)
                if len(t) < 6 or t.lower() in ('download', 'view', 'here', 'click here', 'pdf'):
                    par = a.find_parent(['tr', 'li', 'p', 'figure', 'div'])
                    if par: t = (par.get_text(' ', strip=True)[:250] or t)
                if not href.startswith('http'): continue
                path = urlparse(href).path.lower()
                if path.endswith('.pdf') or 'drive.google.com/file' in href:
                    if DOCKW.search(t + ' ' + href) or KW.search(ptitle) or KW.search(h1t):
                        s.add(href, t or os.path.basename(path), ptitle, 'html_link')
                elif s.same(href) and href not in depth and not BAD.search(href):
                    if KW.search(t + ' ' + href) or depth[u] == 0 or depth[u] == 1 and re.search(r'(legislat|sanggunian|transparen|issuance|document|download|governance|government|council|full.disclosure|offices?|elective|official)', t + href, re.I):
                        depth[href] = depth[u] + 1
                        if depth[href] <= 3: q.append(href)

    def records(s):
        pid = s.p['place_id']; recs = []
        clean = lambda v: None if v is None or (isinstance(v, float) and v != v) else v
        s.p = {k: clean(v) for k, v in s.p.items()}
        base = dict(place_id=pid, country_code='PH', source_platform='ph_lgu_' + s.tmpl, language='en', consolidated=False,
                    place_name=s.p.get('place_name'), qid=s.p.get('qid'), iso_3166_2=s.p.get('iso_3166_2'),
                    admin_level=s.p.get('admin_level'), platform='ph_lgu_' + s.tmpl, platform_place_id=s.host,
                    source_official=s.host.endswith('.gov.ph'), source_org=s.host)
        ocr_left = int(os.environ.get('PH_OCR_CAP', '15'))
        for u, c in list(s.cands.items()):
            if 'drive.google.com' in u:  # not fetched (third-party host); metadata-only
                txt, pol, sha = None, s.policy, None
            else:
                txt, pol, sha = pdf_text(u, ocr_left > 0)
                if isinstance(sha, dict) and sha['ocr']: ocr_left -= 1
                if pol in ('robots_disallowed',): continue
            title = c['title'] if len(c['title']) > 6 else os.path.basename(urlparse(u).path)
            blob = title + ' ' + os.path.basename(urlparse(u).path).replace('-', ' ').replace('_', ' ') + ' ' + (txt or '')[:3000]
            if not DOCKW.search(blob): continue
            if txt is not None and not DOCKW.search((txt or '')[:6000]) and not DOCKW.search(title):
                continue
            lead = re.match(r'\s*((?:19|20)\d{2}-\d{1,4})\b', title)
            num = parse_num(title) or (f"{kind(title).replace('_', ' ').title()} No. {lead.group(1)}" if lead else None) or parse_num(os.path.basename(urlparse(u).path).replace('_', ' ').replace('-', ' - ')) or parse_num((txt or '')[:3000])
            d = parse_date((txt or '')[:4000])
            r = dict(base, doc_id='u' + hashlib.sha1(u.encode()).hexdigest()[:16], source_url=u, doc_type=doctype(num or title),
                     title_native=title, number=num, content_format='pdf_text', retrieved_at=now(),
                     source_policy=pol if not str(pol).startswith('error') else s.policy, ph_doc_kind=kind(num or title),
                     discovered_via=c['src'], context=c['ctx'], pdf=sha if isinstance(sha, dict) else None)
            if c['src'] == 'wp_media': r['wp_upload_date'] = c['ctx'][:10]
            if d: r['adopted_date'] = d
            elif year_from(num or title): r['adopted_date'] = year_from(num or title)
            if txt and len(txt.strip()) > 200:
                r['text'] = txt
                if isinstance(sha, dict) and sha['ocr']:
                    r['text_note'] = 'ocr_tesseract_eng'
                    if sha['pages'] > OCR_PAGES: r['content_complete'] = False; r['text_note'] += f'_first{OCR_PAGES}of{sha["pages"]}pages'
            else: r['content_complete'] = False; r['text_note'] = ('scanned_no_ocr' if txt is not None else ('google_drive_not_fetched' if 'drive.google' in u else str(sha or pol)))
            recs.append(r)
        for u, c in s.htmldocs.items():
            txt = page_text(c['soup'])
            if len(txt) < 300: continue
            num = parse_num(c['title'])
            r = dict(base, doc_id='u' + hashlib.sha1(u.encode()).hexdigest()[:16], source_url=u, doc_type=doctype(c['title']),
                     title_native=c['title'][:300], number=num, content_format='html', text=txt, retrieved_at=now(),
                     source_policy=s.policy, ph_doc_kind=kind(c['title']), discovered_via='html_page')
            d = parse_date(txt[:3000]) or year_from(num or '')
            if d: r['adopted_date'] = d
            recs.append(r)
        return recs

def run_place(p):
    t0 = time.time(); res = dict(place_id=p['place_id'], name=p.get('place_name'))
    try:
        r, pol = phnet.resolve_base(p['urls'][0])
        if r is None: return dict(res, status='unreachable', why=pol)
        if r.status_code != 200: return dict(res, status='unreachable', why=f'http{r.status_code}')
        h = r.text.lower(); tmpl = 'wordpress' if ('wp-content' in h or 'wp-json' in h) else 'generic'
        base = f"{urlparse(r.url).scheme}://{urlparse(r.url).netloc}/"
        s = Site(p, base, pol, tmpl); s.crawl_q = []
        if tmpl == 'wordpress': s.wp()
        s.crawl()
        recs = s.records()
        res.update(template=tmpl, base=base, pages=len(s.pages_seen), cands=len(s.cands), docs=len(recs),
                   with_text=sum(1 for x in recs if x.get('text')), secs=round(time.time() - t0))
        bad = [(x['doc_id'], e) for x in recs for e in [validate_record(x)] if e]
        res['invalid'] = len(bad); res['invalid_ex'] = bad[:2]
        recs = [x for x in recs if not validate_record(x)]
        if recs:
            pk = place_key(p['place_id']); batch = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            final = f"{OUT}/PH/{pk}.{batch}.jsonl"; tmp = final + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                for x in recs: f.write(json.dumps(x, ensure_ascii=False) + '\n')
                f.flush(); os.fsync(f.fileno())
            os.rename(tmp, final); res['file'] = final
        return dict(res, status='ok')
    except Exception as e:
        return dict(res, status='error', why=repr(e)[:300], tb=traceback.format_exc()[-800:])

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--places'); ap.add_argument('--limit', type=int); ap.add_argument('--workers', type=int, default=12)
    ap.add_argument('--done', default=ST + '/done.jsonl'); a = ap.parse_args()
    P = [json.loads(l) for l in open(os.environ.get('PH_PLACES', ST + '/places.jsonl'))]; P = [p for p in P if p['urls']]
    if a.places: want = set(a.places.split(',')); P = [p for p in P if p['place_id'] in want]
    done = set()
    if os.path.exists(a.done): done = {json.loads(l)['place_id'] for l in open(a.done)}
    P = [p for p in P if p['place_id'] not in done][:a.limit]
    print(now(), 'places to do', len(P), 'already done', len(done), flush=True)
    from concurrent.futures import as_completed
    with ThreadPoolExecutor(a.workers) as ex, open(a.done, 'a') as df:
        for fut in as_completed([ex.submit(run_place, p) for p in P]):
            res = fut.result()
            res.pop('tb', None) if res['status'] == 'ok' else None
            df.write(json.dumps(res, ensure_ascii=False) + '\n'); df.flush()
            print(now(), json.dumps(res, ensure_ascii=False), flush=True)
    print(now(), 'FINISHED', flush=True)

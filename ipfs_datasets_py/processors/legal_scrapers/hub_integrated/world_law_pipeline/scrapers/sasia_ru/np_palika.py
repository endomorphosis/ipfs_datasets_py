"""Nepal local-level (MoFAGA uniform Drupal) palika sites: /ne/rajpatra-section (local gazette, all rows)
and /ne/act-law-directives (filtered to legal instruments). PDFs -> pdftotext; Preeti legacy font -> Unicode
via vendored npttf2utf; <200 chars -> OCR queue. Respects robots.txt + Crawl-delay (>=10s). No proxies."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, re, sys, json, time, hashlib, shutil, subprocess, threading, argparse, datetime, html as H
import urllib.parse as up, urllib.robotparser as rp, requests, unicodedata
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline')); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor'))
import warnings; warnings.filterwarnings('ignore')
from schema import validate_record, validate_file, place_key
from npttf2utf import FontMapper
import npttf2utf
import np_match as _nm
NPP = _nm.load()
FM = FontMapper(os.path.join(os.path.dirname(npttf2utf.__file__), 'map.json'))
B = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru'); OUT = B + '/NP'; WORK = B + '/_np'; OCR = B + '/_ocr/np_palika_notext.jsonl'
UA = 'world-law-research-bot/1.0 (municipal law archive research)'
for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','all_proxy'): os.environ.pop(k, None)
LAW = re.compile(r'ऐन|नियमावली|नियम|कार्यविधि|निर्देशिका|मापदण्ड|आदेश|राजपत्र|विनियम|संहिता|नीति|Act\b|Rules?\b|Procedure|Directive|Guideline|Regulation', re.I)
lock = threading.Lock()
def log(*a):
    with lock: print(datetime.datetime.now().strftime('%H:%M:%S'), *a, flush=True)
def disk_ok(): return shutil.disk_usage('/workspace').free > 35e9
def devr(s):
    s = [c for c in s if not c.isspace()]
    return sum('\u0900' <= c <= '\u097f' for c in s) / max(1, len(s))
COMMON = set('र को का की मा ले छ छन् गर्ने गरी तथा सम्बन्धी यो यस वा भएको हुने नगरपालिका गाउँपालिका ऐन वडा लागि अनुसार बमोजिम सक्नेछ हुनेछ दफा नियम कार्यविधि परिच्छेद प्रदेश नेपाल सरकार'.split())
def ne_ok(t):
    toks = re.findall(r'[\u0900-\u097f]+', t)
    if len(toks) < 30: return False
    return sum(x in COMMON for x in toks) / len(toks) >= 0.05 and len(set(toks)) / len(toks) >= 0.1
def en_ok(t):
    toks = re.findall(r'[A-Za-z]+', t.lower())
    return len(toks) >= 50 and sum(x in ('the','of','and','to','in','shall','be','or','by','for') for x in toks) / len(toks) >= 0.08
def to_text(pdf):
    try: t = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True, timeout=180).stdout
    except subprocess.TimeoutExpired: return '', 'timeout'
    t = re.sub(r'[ \t]+\n', '\n', t).strip(); n = len(re.sub(r'\s', '', t))
    if n < 200: return t, 'notext'
    if devr(t) > 0.3:
        t = unicodedata.normalize('NFC', t)
        return (t, 'unicode') if ne_ok(t) else (t, 'bad_text_layer')
    asc = sum(c.isascii() for c in t if not c.isspace()) / max(1, n)
    if asc > 0.9:
        try: c = FM.map_to_unicode(t, from_font='Preeti', unescape_html_input=False, escape_html_output=False)
        except Exception: c = ''
        c = unicodedata.normalize('NFC', c)
        if devr(c) > 0.5 and ne_ok(c): return c, 'preeti'
        if en_ok(t): return t, 'english'
    return t, 'bad_text_layer'
class Host:
    def __init__(s, base):
        s.base = base.rstrip('/'); s.S = requests.Session(); s.S.headers['User-Agent'] = UA; s.S.trust_env = False
        s.rp = rp.RobotFileParser(); s.delay = 10; s.last = 0
        r = s.S.get(s.base + '/robots.txt', timeout=30)
        if r.status_code == 200: s.rp.parse(r.text.splitlines()); s.delay = max(10, s.rp.crawl_delay(UA) or 10); s.policy = 'robots_allowed_rfc9309'
        elif 400 <= r.status_code < 500: s.rp.parse([]); s.policy = 'robots_404_allow_rfc9309'
        else: raise RuntimeError(f'robots_unreachable {r.status_code}')
    def get(s, url, **kw):
        if not s.rp.can_fetch(UA, url): raise PermissionError('robots_disallowed ' + url)
        w = s.last + s.delay - time.time()
        if w > 0: time.sleep(w)
        try: return s.S.get(url, timeout=kw.pop('timeout', 60), **kw)
        finally: s.last = time.time()
def core(n): return re.sub(r'\s*(उप-?महानगरपालिका|महानगरपालिका|गाउँपालिका|गाउंपालिका|नगरपालिका|गाउँ पालिका)\s*', '', n or '').strip()
def rows(page):
    """Robust to table/grid/list templates: attach every PDF link to the nearest preceding /ne/content/ node link."""
    nodes = [(m.start(), H.unescape(m.group(1)), m.group(2)) for m in re.finditer(r'<a href="((?:https?://[^/"]+)?/(?:ne|en)/(?:content|node)/[^"#?]+)"[^>]*>(.*?)</a>', page, re.S)]
    out = {}
    for m in re.finditer(r'href="([^"]+\.pdf)"(?: type="application/pdf(?:; length=(\d+))?")?', page, re.I):
        prev = [n for n in nodes if n[0] < m.start() and m.start() - n[0] < 4000]
        if not prev: continue
        pos, node, title = prev[-1]
        node = re.sub(r'^https?://[^/]+', '', node)
        t = re.sub(r'\s+', ' ', H.unescape(re.sub('<[^>]+>', '', title))).strip()
        if not t: continue
        seg = page[pos:m.start() + 600]
        d = re.search(r'(\d\d)/(\d\d)/(\d{4}) - \d\d:\d\d', seg)
        x = out.setdefault(node, {'node': node, 'title': t, 'pdfs': [], 'published': f'{d.group(3)}-{d.group(1)}-{d.group(2)}' if d else None})
        u = H.unescape(m.group(1))
        if u not in [q for q, _ in x['pdfs']]: x['pdfs'].append((u, int(m.group(2) or 0)))
    return list(out.values())
def scrape(p, cap):
    pid = p['qid'] if p['qid'].startswith('wd:') else 'wd:' + p['qid']; pk = place_key(pid)
    h = Host(p['site']); home = h.get(h.base + '/ne').text
    name = re.sub(r'\s+', ' ', H.unescape(re.search(r'<title>(.*?)</title>', home, re.S).group(1)))
    if not p.get('verified'):
        import np_match; m = np_match.match(name, NPP)
        if not (len(m) == 1 and m[0]['qid'] == pid): return {'place_key': pk, 'status': 'name_mismatch', 'site_title': name, 'wd_ne': p['ne'], 'matched': [x['qid'] for x in m]}
    if False:
        return {'place_key': pk, 'status': 'name_mismatch', 'site_title': name, 'wd_ne': p['ne']}
    items = {}
    for sec, filt in (('rajpatra-section', False), ('act-law-directives', True)):
        for pg in range(0, 30):
            r = h.get(f'{h.base}/ne/{sec}' + (f'?page={pg}' if pg else ''))
            if r.status_code != 200: break
            got = list(rows(r.text)); new = 0
            for x in got:
                if filt and not LAW.search(x['title']): continue
                if x['node'] not in items and x['pdfs']: items[x['node']] = {**x, 'section': sec}; new += 1
            if not new or 'pager-next' not in r.text: break
    recs, ocr, stats = [], [], {}
    for x in list(items.values())[:cap]:
        if not disk_ok(): log('DISK LOW stop'); break
        texts, how = [], []
        for u, n in x['pdfs'][:3]:
            u = up.quote(u, safe=':/%?=&')
            if n > 40e6: how.append('toolarge'); continue
            tmp = f'{WORK}/{hashlib.sha1(u.encode()).hexdigest()}.pdf'
            try:
                r = h.get(u, stream=True, timeout=120)
                if r.status_code != 200: how.append(f'http{r.status_code}'); continue
                with open(tmp, 'wb') as f:
                    for c in r.iter_content(1 << 16): f.write(c)
                t, k = to_text(tmp)
            except Exception as e: how.append(type(e).__name__); continue
            finally:
                if os.path.exists(tmp): os.remove(tmp)
            how.append(k)
            if k in ('notext', 'timeout', 'bad_text_layer'): ocr.append({'source_url': u, 'doc_page_url': h.base + x['node'], 'place_id': pid, 'place_key': pk, 'country': 'NP', 'language': 'ne', 'script': 'Deva', 'source': 'np_palika', 'title': x['title'], 'reason': k})
            else: texts.append(t)
        for k in how: stats[k] = stats.get(k, 0) + 1
        if not texts: continue
        dt = 'ordinance' if re.search(r'ऐन|Act\b', x['title']) and not re.search(r'नियमावली|कार्यविधि|निर्देशिका', x['title']) else ('gazette_act' if x['section'] == 'rajpatra-section' and not re.search(r'नियमावली|कार्यविधि|निर्देशिका|मापदण्ड|नियम', x['title']) else 'regulation')
        rec = {'place_id': pid, 'country_code': 'NP', 'doc_id': 'npgov:' + up.urlsplit(h.base).hostname + ':' + hashlib.sha1(x['node'].encode()).hexdigest()[:16],
               'source_platform': 'np_mofaga_palika', 'source_url': h.base + up.quote(x['node'], safe='/%'), 'original_url': up.quote(x['pdfs'][0][0], safe=':/%?=&'),
               'doc_type': dt, 'language': 'en' if how and all(k == 'english' for k in how if k in ('english','unicode','preeti')) else 'ne', 'content_format': 'pdf_text', 'consolidated': False, 'title_native': x['title'],
               'published_date': x['published'], 'text': '\n\n'.join(texts), 'retrieved_at': datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
               'source_official': True, 'source_org': name, 'source_policy': h.policy, 'text_extraction': '+'.join(sorted(set(how))),
               'section': x['section'], 'place_name': p['en'], 'qid': pid[3:], 'admin_level': 'municipality', 'platform': 'np_mofaga_palika'}
        e = validate_record(rec)
        if e: log('INVALID', pk, e); continue
        recs.append(rec)
    if ocr:
        with lock, open(OCR, 'a') as f:
            for o in ocr: f.write(json.dumps(o, ensure_ascii=False) + '\n')
    out = None
    if recs:
        ts = datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ'); os.makedirs(OUT, exist_ok=True)
        fin = f'{OUT}/{pk}.npgov{ts}.jsonl'; tmp = f'{OUT}/.tmp.{pk}.npgov{ts}.jsonl'
        with open(tmp, 'w') as f:
            for r in recs: f.write(json.dumps(r, ensure_ascii=False) + '\n')
            f.flush(); os.fsync(f.fileno())
        v = validate_file(tmp, expect_place_key=pk)
        if not v['ok'] or v['bad_rows']: os.remove(tmp); return {'place_key': pk, 'status': 'validation_failed', 'errors': str(v['errors'][:3])}
        os.rename(tmp, fin); out = fin
    return {'place_key': pk, 'status': 'ok', 'host': h.base, 'listed': len(items), 'staged': len(recs), 'ocr': len(ocr), 'extraction': stats, 'file': out}
if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('places'); ap.add_argument('--cap', type=int, default=80); ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--done', default=WORK + '/np_done.jsonl'); a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    done = {json.loads(l)['place_key'] for l in open(a.done)} if os.path.exists(a.done) else set()
    P = [json.loads(l) for l in open(a.places)]; P = [p for p in P if place_key(p['qid']) not in done]
    from concurrent.futures import ThreadPoolExecutor
    def run(p):
        if not disk_ok(): return
        try: res = scrape(p, a.cap)
        except Exception as e: res = {'place_key': place_key(p['qid']), 'status': 'error', 'host': p['site'], 'error': f'{type(e).__name__}: {e}'[:200]}
        log(json.dumps(res, ensure_ascii=False))
        with lock, open(a.done, 'a') as f: f.write(json.dumps(res, ensure_ascii=False) + '\n')
    with ThreadPoolExecutor(a.workers) as ex: list(ex.map(run, P))
    log('finished')

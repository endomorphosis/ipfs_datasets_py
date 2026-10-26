"""Crawler for regency/city JDIH portals (jdih.<x>.go.id). The portals share the JDIHN layout: product listings
(perda/perbup/perwali/keputusan) with pagination -> detail pages -> PDF. Does NOT touch peraturan.bpk.go.id.
Skips docs whose (jenis, nomor, tahun) already exists for the place in the asia_latam BPK output.
Output staging/id_jdih/ID/<place_key>.<UTC>.jsonl; checkpoint _state/done.jsonl (or --done)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, re, json, time, hashlib, subprocess, tempfile, argparse, datetime, glob, gzip, collections, traceback
from urllib.parse import urljoin, urlparse, urldefrag
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/ph')); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline'))
import phnet
from schema import place_key, validate_record
from bs4 import BeautifulSoup
ST = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/id_jdih/_state'); OUT = os.environ.get('IDJ_OUT', '/workspace/world_law/staging/id_jdih')
MAXPAGES = int(os.environ.get('IDJ_MAXPAGES', '600')); MAXDOCS = int(os.environ.get('IDJ_MAXDOCS', '4000')); MAXPDF = 30_000_000
FETCH_PDF = os.environ.get('IDJ_PDF', '1') == '1'
now = lambda: datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
JENIS = [('peraturan daerah', 'perda', 'regulation'), ('perda', 'perda', 'regulation'),
         ('peraturan bupati', 'perbup', 'regulation'), ('perbup', 'perbup', 'regulation'),
         ('peraturan walikota', 'perwali', 'regulation'), ('peraturan wali kota', 'perwali', 'regulation'), ('perwali', 'perwali', 'regulation'), ('perwal', 'perwali', 'regulation'),
         ('keputusan bupati', 'kepbup', 'decision'), ('keputusan walikota', 'kepwal', 'decision'), ('keputusan wali kota', 'kepwal', 'decision'),
         ('instruksi bupati', 'inbup', 'decision'), ('instruksi walikota', 'inwal', 'decision'), ('surat edaran', 'se', 'decision'),
         ('keputusan dprd', 'kepdprd', 'decision'), ('peraturan dprd', 'perdprd', 'regulation')]
NUMTAH = re.compile(r'(?:nomor|no\.?)\s*[:.]?\s*([0-9][0-9A-Za-z./\-]*)\s*(?:tahun|th\.?)\s*((?:19|20)\d\d)', re.I)
FOLLOW = re.compile(r'(hukum|peraturan|perda|perbup|perwal|perwali|keputusan|kepbup|instruksi|produk|dokumen|regulasi|katalog|search|cari|jenis|kategori|page=|/page/|\?p=|halaman=|offset=|start=|/\d+/?$)', re.I)
SKIP = re.compile(r'(berita|isiberita|galeri|gallery|video|foto|artikel|login|register|kontak|contact|survey|survei|statistik|agenda|pengumuman|facebook|twitter|instagram|youtube|wa\.me|mailto:|\.(jpg|jpeg|png|gif|zip|rar|mp4|docx?|xlsx?|pptx?)$)', re.I)
MON = {'januari': 1, 'februari': 2, 'maret': 3, 'april': 4, 'mei': 5, 'juni': 6, 'juli': 7, 'agustus': 8, 'september': 9, 'oktober': 10, 'november': 11, 'desember': 12}
DATE = re.compile(r'\b(\d{1,2})\s+(%s)\s+((?:19|20)\d\d)\b' % '|'.join(MON), re.I)

def jenis(t):
    tl = ' ' + re.sub(r'\s+', ' ', t.lower()) + ' '
    for k, code, dt in JENIS:
        if re.search(r'\b' + k + r'\b', tl): return code, dt
    return None, None
def meta(t):
    j, dt = jenis(t); m = NUMTAH.search(t)
    return j, dt, (m.group(1).strip('.-/') if m else None), (m.group(2) if m else None)
def nkey(j, n, y): return f"{j}|{re.sub(r'^0+', '', n.lower())}|{y}" if j and n and y else None

_bpk = None
def bpk_index():
    global _bpk
    if _bpk is not None: return _bpk
    _bpk = collections.defaultdict(set)
    for d in ((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/processed/asia_latam/ID'), (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/asia_latam/ID')):
        for f in glob.glob(d + '/*.jsonl*'):
            try:
                op = gzip.open if f.endswith('.gz') else open
                for l in op(f, 'rt'):
                    r = json.loads(l); j, _, n, y = meta(r.get('title_native') or '')
                    k = nkey(j, n, y)
                    if k: _bpk[r['place_id']].add(k)
            except Exception: pass
    return _bpk

def pdf_text(url):
    r, pol = phnet.get(url, timeout=int(os.environ.get('PDF_TIMEOUT', '60')), stream=True)
    if r is None or r.status_code != 200: return None, pol, dict(status=getattr(r, 'status_code', pol))
    data = b''
    try:
      for ch in r.iter_content(65536):
        data += ch
        if len(data) > MAXPDF: return None, pol, dict(status='too_large')
    except Exception as e:
        return None, 'error:' + type(e).__name__, dict(status='stream_error')
    if not data.startswith(b'%PDF'): return None, pol, dict(status='not_pdf')
    with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
        f.write(data); f.flush()
        try: txt = subprocess.run(['pdftotext', '-layout', '-l', '80', f.name, '-'], capture_output=True, timeout=120).stdout.decode('utf-8', 'replace')
        except Exception: txt = ''
    return txt, pol, dict(sha1=hashlib.sha1(data).hexdigest(), bytes=len(data))

class Site:
    def __init__(s, p, base, pol):
        s.p, s.base, s.pol = p, base, pol; s.host = urlparse(base).netloc.lower()
        s.cands = {}; s.seen = set()
    def same(s, u): return urlparse(u).netloc.lower().removeprefix('www.') == s.host.removeprefix('www.')
    def crawl(s):
        q = collections.deque([s.base]); depth = {s.base: 0}
        while q and len(s.seen) < MAXPAGES and len(s.cands) < MAXDOCS:
            u = q.popleft()
            if u in s.seen: continue
            s.seen.add(u)
            r, _ = phnet.get(u, timeout=40)
            if r is None or r.status_code != 200 or 'html' not in r.headers.get('content-type', ''): continue
            soup = BeautifulSoup(r.text[:3_000_000], 'html.parser')
            for a in soup.find_all('a', href=True):
                href = urldefrag(urljoin(r.url, a['href'].strip()))[0]
                if not href.startswith('http') or not s.same(href): continue
                t = a.get_text(' ', strip=True); path = urlparse(href).path.lower()
                ctx = t
                if len(t) < 25:
                    par = a.find_parent(['tr', 'li', 'div', 'article', 'td'])
                    if par: ctx = par.get_text(' ', strip=True)[:500]
                if path.endswith('.pdf') or re.search(r'/(download|unduh|file|lampiran)[/?]', path + '?'):
                    j, _, n, y = meta(ctx)
                    if j or NUMTAH.search(ctx) or '/peraturan' in u.lower() or 'hukum' in u.lower():
                        if href not in s.cands: s.cands[href] = dict(ctx=ctx, page=u)
                elif href not in depth and not SKIP.search(href) and FOLLOW.search(href + ' ' + t) and depth[u] < 6:
                    depth[href] = depth[u] + 1; q.append(href)
    def records(s):
        p = s.p; pid = p['place_id']; bk = bpk_index().get(pid, set()); recs = []; dup = 0; seen_sha = set()
        base = dict(place_id=pid, country_code='ID', source_platform='id_jdih_daerah', language='id', consolidated=False,
                    place_name=p.get('place_name'), qid=p.get('qid'), admin_level=p.get('admin_level'), platform='id_jdih_daerah',
                    platform_place_id=s.host, source_official=True, source_org=s.host, kemendagri_code=p.get('kemendagri'))
        for u, c in s.cands.items():
            j, dt, n, y = meta(c['ctx'])
            txt, pol, info = (pdf_text(u) if FETCH_PDF else (None, s.pol, {}))
            if pol == 'robots_disallowed': continue
            head = re.sub(r'\s+', ' ', (txt or '')[:4000])
            if txt and (not j or not n):
                j2, dt2, n2, y2 = meta(head[:1500])
                if j2 and (not j or j2 == j): j, dt, n, y = j2, dt2, n2, y2
            if not j: continue
            if txt and not jenis(head[:1500])[0] and not jenis(c['ctx'])[0]: continue
            k = nkey(j, n, y)
            if k and k in bk: dup += 1; continue
            if info.get('sha1') in seen_sha: continue
            seen_sha.add(info.get('sha1'))
            title = re.sub(r'\s+', ' ', c['ctx'])[:400]
            m = re.search(r'((?:PERATURAN|KEPUTUSAN|INSTRUKSI|SURAT EDARAN)\b.{5,120}?NOMOR.{1,40}?TAHUN\s*\d{4}\s*TENTANG\s.{5,200}?)(?:\s(?:DENGAN RAHMAT|BUPATI\s|WALI ?KOTA\s|Menimbang)|$)', head, re.I)
            if m:
                title = m.group(1).strip(); j3, dt3, n3, y3 = meta(title)
                if j3 and n3: j, dt, n, y = j3, dt3, n3, y3
            elif not NUMTAH.search(title) and head.strip(): title = head[:250].strip()
            if len(title) < 6: title = os.path.basename(urlparse(u).path)[:200] or u
            k = nkey(j, n, y)
            if k and k in bk: dup += 1; continue
            r = dict(base, doc_id='u' + hashlib.sha1(u.encode()).hexdigest()[:16], source_url=u, doc_type=dt, title_native=title,
                     number=(f"Nomor {n} Tahun {y}" if n and y else None), id_jenis=j, id_norm_key=k, content_format='pdf_text',
                     retrieved_at=now(), source_policy=s.pol, listing_page=c['page'], pdf=info or None)
            if y: r['adopted_date'] = y
            m = DATE.search((txt or '')[:6000])
            if m and y and m.group(3) == y: r['adopted_date'] = f"{y}-{MON[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
            if txt and len(txt.strip()) > 200: r['text'] = txt
            else: r['content_complete'] = False; r['text_note'] = 'scanned_or_unfetched_pdf'
            recs.append(r)
        return recs, dup

def run_place(p, probe):
    t0 = time.time(); res = dict(place_id=p['place_id'], name=p['place_name'])
    try:
        if not probe or not probe.get('ok'): return dict(res, status='unreachable', why='probe')
        s = Site(p, probe['base'], probe.get('policy')); s.crawl(); recs, dup = s.records()
        bad = [(x['doc_id'], e) for x in recs for e in [validate_record(x)] if e]
        recs = [x for x in recs if not validate_record(x)]
        res.update(base=s.base, pages=len(s.seen), cands=len(s.cands), docs=len(recs), with_text=sum(1 for x in recs if x.get('text')),
                   bpk_dupes_skipped=dup, invalid=len(bad), invalid_ex=bad[:2], secs=round(time.time() - t0))
        if recs:
            pk = place_key(p['place_id']); final = f"{OUT}/ID/{pk}.{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
            with open(final + '.tmp', 'w', encoding='utf-8') as f:
                for x in recs: f.write(json.dumps(x, ensure_ascii=False) + '\n')
                f.flush(); os.fsync(f.fileno())
            os.rename(final + '.tmp', final); res['file'] = final
        return dict(res, status='ok')
    except Exception as e:
        return dict(res, status='error', why=repr(e)[:300], tb=traceback.format_exc()[-600:])

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--places'); ap.add_argument('--workers', type=int, default=10); ap.add_argument('--done', default=ST + '/done.jsonl')
    a = ap.parse_args()
    P = [json.loads(l) for l in open(ST + '/places.jsonl')]
    PR = {json.loads(l)['place_id']: json.loads(l) for l in open(ST + '/probe.jsonl')}
    P = [p for p in P if p['place_id'] in PR]
    if a.places: w = set(a.places.split(',')); P = [p for p in P if p['place_id'] in w]
    done = {json.loads(l)['place_id'] for l in open(a.done)} if os.path.exists(a.done) else set()
    P = [p for p in P if p['place_id'] not in done]
    print(now(), 'todo', len(P), 'done', len(done), 'bpk places indexed', len(bpk_index()), flush=True)
    with ThreadPoolExecutor(a.workers) as ex, open(a.done, 'a') as df:
        for fu in as_completed([ex.submit(run_place, p, PR.get(p['place_id'])) for p in P]):
            r = fu.result(); df.write(json.dumps(r, ensure_ascii=False) + '\n'); df.flush(); print(now(), json.dumps(r, ensure_ascii=False)[:400], flush=True)
    print(now(), 'FINISHED', flush=True)

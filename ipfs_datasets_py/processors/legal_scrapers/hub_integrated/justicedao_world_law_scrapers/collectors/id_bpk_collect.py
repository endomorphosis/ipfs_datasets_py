#!/usr/bin/env python3
"""DRAFT - ID (Indonesia) regional regulations collector for peraturan.bpk.go.id (JDIH BPK).
STATUS: draft written during the CoS-approved PROBE (2026-10-04). DO NOT RUN `full` WITHOUT A CoS GO.

Modes
  selftest                 offline: parse cached probe detail pages + PDFs, print parsed rows (no network)
  sample N [--seed S]      fetch N random regional regulations (detail + PDFs) - probe-scale only
  full --cos-go TOKEN      full sitemap-driven run; refuses unless TOKEN matches id_bpk/COS_GO_FULL (file written by CoS/parent)
  ocr [--workers W]        offline: OCR (tesseract ind+eng, 300 dpi) every cached PDF whose text layer is poor
  build OUTDIR             offline: build laws.parquet + articles.parquet (national hub schema) from caches

Source / gate (evidence in {_CORPORA}/id_bpk/robots + /terms):
  robots.txt disallows only /Admin/ /Identity/ /Account/ /Manage/ /health /Error, no Crawl-delay;
  footer: access 'secara gratis dan tanpa syarat'; UU 28/2014 Pasal 42: peraturan perundang-undangan not subject to copyright.
Guards: single process, >=2.0 s between request starts (raised to any Crawl-delay), honest UA, host-locked, no redirects off-host;
  RSS > 300 MB -> clean stop; MemAvailable <= 3700 MB -> self-TERM; 3 consecutive 403/429/503 -> stop; backoff 5s..300s on 5xx/520/conn errors;
  SIGTERM -> finish current regulation and exit; resume-safe (gz caches + done-ledger); state file: merges idp_* keys + collectors only.
Enumeration: year sitemaps (/sitemap.xml -> per-year) -> /Details/<id>/<slug>; slug regex classifies level/type/region (see probe).
Jurisdiction: ID-<BPS prov code> (e.g. ID-33 Jawa Tengah) / ID-<prov>-<kab/kota 2-digit> (e.g. ID-33-01 Kab. Cilacap, ID-33-74 Kota Semarang);
  map in id_bpk/ref/region_codes.json (557/557 region slugs mapped; codes = BPS kode wilayah, pre-2022 list + Papua 93-96). Pusat docs -> 'ID'.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, re, json, gzip, time, signal, random, html, hashlib, subprocess, datetime, resource
B = '{_CORPORA}/id_bpk'; HOST = 'peraturan.bpk.go.id'; BASE = f'https://{HOST}'
STATE = '/workspace/logs/soft_lean/HOLD_AT_PIN.state'
UA = 'legal-corpora-id-collector/1.0 (research corpus of official Indonesian regulations; polite single-stream; contact via huggingface.co/endomorphosis)'
DELAY = 2.0; RSS_MB = 300; MEMAVAIL_MB = 3700
KEEP_PDF = os.environ.get('IDB_KEEP_PDF') == '1'; OCRQ_GB = float(os.environ.get('IDB_OCRQ_GB', '8'))  # pause fetching when pending-OCR PDFs exceed this
LICENSE = ('Public domain in Indonesia: UU No. 28/2014 tentang Hak Cipta, Pasal 42 - peraturan perundang-undangan are not subject to copyright. '
           'Source JDIH BPK (peraturan.bpk.go.id), access stated as free and unconditional (\'secara gratis dan tanpa syarat\'); site disclaimer covers accuracy only.')
LAW_COLS = ['id', 'title', 'text', 'source_url', 'source_type', 'jurisdiction', 'country', 'language', 'eli', 'date', 'date_issued', 'retrieved_at',
            'license', 'law_status', 'identifier', 'official_identifier', 'article_count', 'json_path', 'metadata_json']
ART_COLS = ['law_id', 'id', 'title', 'text', 'source_url', 'document_number', 'article_number', 'record_type', 'metadata_json']
SLUG_RE = re.compile(r'^(?P<type>perda|perbup|perwali|perwal|pergub|qanun|perkada|[a-z]+)-(?P<lvl>prov|kab|kota)-(?P<region>.+?)-no-(?P<no>[^/]+?)-tahun-(?P<year>\d{4})')
BULAN = {m: i + 1 for i, m in enumerate(['januari', 'februari', 'maret', 'april', 'mei', 'juni', 'juli', 'agustus', 'september', 'oktober', 'november', 'desember'])}
STOP = False
def _sig(*a):
    global STOP; STOP = True
signal.signal(signal.SIGTERM, _sig)
def log(*a): print(time.strftime('%H:%M:%S'), *a, flush=True)
def memavail():
    return int(open('/proc/meminfo').read().split('MemAvailable:')[1].split()[0]) // 1024
def rss():
    for l in open('/proc/self/status'):
        if l.startswith('VmRSS'): return int(l.split()[1]) // 1024
    return 0
def state_merge(upd, collectors_delta=0):
    """Re-read then merge only idp_* keys (+ optional collectors delta). Never touches mode / other namespaces."""
    s = json.load(open(STATE))
    for k, v in upd.items():
        assert k.startswith('idp_'), k
        s[k] = v
    if collectors_delta: s['collectors'] = max(0, int(s.get('collectors', 0)) + collectors_delta)
    tmp = STATE + '.idp.tmp'; json.dump(s, open(tmp, 'w'), indent=1); os.replace(tmp, STATE)
# ---------------- network ----------------
class Net:
    def __init__(self):
        import requests
        self.s = requests.Session(); self.s.headers['User-Agent'] = UA; self.last = 0; self.bad = 0; self.n = 0
    def get(self, path):
        url = path if path.startswith('http') else BASE + path
        assert url.startswith(BASE + '/'), 'off-host refused'
        back = 5
        while True:
            w = DELAY - (time.time() - self.last)
            if w > 0: time.sleep(w)
            self.last = time.time(); self.n += 1
            try:
                r = self.s.get(url, timeout=(20, 180), allow_redirects=False)
            except Exception as e:
                log('ERR', url, repr(e)[:150]); time.sleep(back); back = min(back * 2, 300)
                if back >= 300: return None, None
                continue
            if r.status_code in (403, 429, 503):
                self.bad += 1
                if self.bad >= 3: raise SystemExit(f'STOP 3 consecutive {r.status_code}')
                time.sleep(back); back = min(back * 2, 300); continue
            self.bad = 0
            if r.status_code >= 500 and back < 300:
                log('5xx', r.status_code, url); time.sleep(back); back = min(back * 2, 300); continue
            return r.status_code, r.content
# ---------------- parsing ----------------
FIELDS = ['Tipe Dokumen', 'Judul', 'T.E.U.', 'Nomor', 'Bentuk', 'Bentuk Singkat', 'Tahun', 'Tempat Penetapan', 'Tanggal Penetapan', 'Tanggal Pengundangan',
          'Tanggal Berlaku', 'Sumber', 'Subjek', 'Status', 'Bahasa', 'Lokasi', 'Bidang']
def parse_detail(s):
    t = re.sub(r'<script.*?</script>|<style.*?</style>', '', s, flags=re.S)
    lines = [x.strip() for x in html.unescape(re.sub(r'<[^>]+>', '\n', t)).split('\n') if x.strip()]
    meta = {}
    if 'METADATA' in lines:
        i0 = lines.index('METADATA')
        for k in FIELDS:
            if k in lines[i0:i0 + 80]:
                j = lines.index(k, i0); meta[k] = lines[j + 1]
    # status relations (Mengubah / Diubah dengan / Mencabut / Dicabut dengan ...) and abstract, best effort
    rel = {}
    for k in ['Mengubah', 'Diubah dengan', 'Mencabut', 'Dicabut dengan', 'Dicabut sebagian dengan', 'Mencabut sebagian', 'Ditetapkan dengan', 'Menetapkan']:
        if k in lines:
            j = lines.index(k); rel[k] = lines[j + 1:j + 4]
    meta['_relations'] = rel
    if 'ABSTRAK' in lines:
        j = lines.index('ABSTRAK'); meta['_abstrak'] = ' '.join(lines[j + 1:j + 12])[:3000]
    dls = list(dict.fromkeys(re.findall(r'href="(/Download/[^"]+)"', s)))
    return meta, dls
def iso_date(s):
    if not s: return None
    m = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', s)
    if m and m.group(2).lower() in BULAN: return f'{m.group(3)}-{BULAN[m.group(2).lower()]:02d}-{int(m.group(1)):02d}'
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)
    return m.group(0) if m else None
ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10}
def _lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1): cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
_NUMFIX = str.maketrans({'l': '1', 'I': '1', '|': '1', 'O': '0', 'o': '0', 'S': '5', 'B': '8'})
def heading_lines(text):
    """Candidate 'Pasal <n>' heading lines (short standalone lines). Tolerates OCR noise: 'Pasal4', 'Pasa1 2', 'Paaa12', 'PASAL 3', 'Pasal l'."""
    out = []; pos = 0
    for line in text.split('\n'):
        c = re.sub(r'^[^\w]+|[^\w]+$', '', re.sub(r'\s+', '', line))
        if 5 <= len(c) <= 12 and c[0] in 'Pp' and not re.search(r'[a-z]{6,}', c[1:]):
            out.append((pos, c))
        pos += len(line) + 1
    return out
def _match_n(c, n):
    """Does compact line c read as 'Pasal<n>' (optionally with a letter suffix)? returns suffix or None."""
    for suf in ('', 'A', 'B', 'C', 'D'):
        for num in (str(n),):
            tail = num + suf
            cc = c[:len(c) - len(suf)] if suf and c.endswith(suf) else (c if not suf else None)
            if cc is None: continue
            fixed = cc[:-len(num)] + cc[-len(num):].translate(_NUMFIX) if len(cc) > len(num) else cc
            if fixed.endswith(num):
                pre = fixed[:-len(num)]
                if _lev(pre.lower(), 'pasal') <= 2: return suf
    return None
def split_pasal(text):
    """Pasal-level split guided by the document's own numbering.
    - Amending regulations (standalone 'Pasal I' and 'Pasal II'): split on Roman headings only; quoted amended Pasal stay inside Pasal I.
    - Otherwise walk candidate heading lines and accept 'Pasal n' only for n in last+1..last+3 (gap <=2 tolerated = headings lost by OCR),
      or 'Pasal nA' inserted articles. Cross-references inside sentences are never candidates (not standalone short lines).
    Returns list of dict(num, record_type, text) and attaches gaps via split_pasal.last_gaps."""
    cands = heading_lines(text); heads = []; gaps = []
    ro = [(p, c) for p, c in cands if re.fullmatch(r'(?:Pasal|PASAL)([IVX]{1,4})', c)]
    rnums = [ROMAN.get(re.fullmatch(r'(?:Pasal|PASAL)([IVX]{1,4})', c).group(1)) for p, c in ro]
    if 1 in rnums and 2 in rnums:
        exp = 1
        for (p, c), r in zip(ro, rnums):
            if r == exp: heads.append((p, re.fullmatch(r'(?:Pasal|PASAL)([IVX]{1,4})', c).group(1), 'pasal_amending')); exp += 1
    else:
        last = 0
        for p, c in cands:
            hit = None
            for n in range(last + 1, last + 4):
                suf = _match_n(c, n)
                if suf == '':
                    hit = (n, ''); break
            if hit is None and last:
                suf = _match_n(c, last)
                if suf: hit = (last, suf)
            if hit:
                n, suf = hit
                if n > last + 1: gaps.extend(range(last + 1, n))
                heads.append((p, f'{n}{suf}', 'article')); last = n
    out = []
    for i, (pos, num, rt) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        body = text[pos:end]
        if i + 1 == len(heads):  # cut closing formula / signature block from the last Pasal
            m = re.search(r'\n\s*(Ditetapkan di|Diundangkan di)', body)
            if m: body = body[:m.start()]
        out.append(dict(num=num, record_type=rt, text=re.sub(r'[ \t]+', ' ', body).strip()))
    split_pasal.last_gaps = gaps
    return out
def text_quality(text, pages):
    nonws = len(re.sub(r'\s', '', text)); toks = text.split()
    alpha = [t for t in toks if re.fullmatch(r'[A-Za-z]{2,}', t.strip('.,;:()"\''))]
    return dict(chars=nonws, chars_per_page=round(nonws / max(pages, 1), 1), alpha_ratio=round(len(alpha) / max(len(toks), 1), 3))
def needs_ocr(q):  # calibrated on the probe sample (see handcheck_prerun.md)
    return q['chars_per_page'] < 300 or q['alpha_ratio'] < 0.45
# ---------------- jurisdiction ----------------
_RC = None
def jurisdiction(slug):
    global _RC
    if _RC is None: _RC = json.load(open(f'{B}/ref/region_codes.json'))['map']
    m = SLUG_RE.match(slug)
    if not m: return 'ID', None
    v = _RC.get(f"{m.group('lvl')}:{m.group('region')}")
    return (v['jurisdiction'], v) if v else ('ID', None)
# ---------------- cache ----------------
def cpath(kind, key, ext):
    d = f'{B}/raw/{kind}/{str(key)[-2:]}'; os.makedirs(d, exist_ok=True); return f'{d}/{key}{ext}'
def fetch_one(net, did, slug):
    hp = cpath('detail', did, '.html.gz')
    if not os.path.exists(hp):
        st, body = net.get(f'/Details/{did}/{slug}')
        if st != 200 or not body: return dict(id=did, status=f'detail_http_{st}')
        with gzip.open(hp + '.tmp', 'wb') as f: f.write(body)
        os.replace(hp + '.tmp', hp)
    s = gzip.open(hp).read().decode('utf-8', 'replace'); meta, dls = parse_detail(s)
    files = []
    for dl in dls:
        fid = dl.split('/')[2]; pp = cpath('pdf', fid, '.pdf')
        if not os.path.exists(pp) and not os.path.exists(cpath('text', fid, '.json')):
            st, body = net.get(dl)
            if st != 200 or not body or body[:5] != b'%PDF-': files.append(dict(fileid=fid, url=BASE + dl, status=f'pdf_http_{st}')); continue
            open(pp + '.tmp', 'wb').write(body); os.replace(pp + '.tmp', pp)
        tp = cpath('text', fid, '.txt.gz')
        if os.path.exists(pp):
            sz = os.path.getsize(pp); sha = hashlib.sha256(open(pp, 'rb').read()).hexdigest(); pages = pdf_pages(pp); t = pdf_text(pp); q = text_quality(t, pages)
            with gzip.open(tp + '.tmp', 'wt') as f: f.write(t)
            os.replace(tp + '.tmp', tp)
            ocr = needs_ocr(q)
            json.dump(dict(bytes=sz, sha256=sha, pages=pages, quality=q, needs_ocr=ocr), open(cpath('text', fid, '.json'), 'w'))
            if not ocr and not KEEP_PDF: os.remove(pp)   # disk: full PDF set ~1.1-1.2 TB, box has ~40 GB free -> keep only OCR queue
        info = json.load(open(cpath('text', fid, '.json')))
        files.append(dict(fileid=fid, url=BASE + dl, status='ok', **info))
    return dict(id=did, slug=slug, status='ok' if any(f['status'] == 'ok' for f in files) else ('no_pdf_listed' if not dls else 'pdf_failed'),
                meta=meta, files=files, retrieved_at=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
def ocrq_gb():
    tot = 0
    for root, _, fs in os.walk(f'{B}/raw/pdf'):
        for f in fs: tot += os.path.getsize(os.path.join(root, f))
    return tot / 1e9
def enumerate_targets(include_pusat=False):
    L = json.load(open(f'{B}/index/sitemap_details_classified.json'))
    return [(d['id'], d['slug']) for d in L if include_pusat or d.get('lvl') in ('prov', 'kab', 'kota')]
def run(targets, tag):
    led = f'{B}/ledger_{tag}.jsonl'; done = set()
    if os.path.exists(led):
        for l in open(led):
            try: done.add(json.loads(l)['id'])
            except Exception: pass
    net = Net(); out = open(led, 'a'); n = 0; t0 = time.time()
    state_merge(dict(idp_status=f'COLLECTING_{tag.upper()}', idp_pid=os.getpid(), idp_ts=time.strftime('%Y-%m-%dT%H:%M:%S%z')), collectors_delta=+1)
    end = 'DONE'
    try:
        for did, slug in targets:
            if did in done: continue
            if STOP: end = 'TERMINATED_BY_SIGNAL'; break
            if memavail() <= MEMAVAIL_MB: end = 'MEMSHED'; log('MemAvailable', memavail(), '-> self-TERM'); break
            if rss() > RSS_MB: end = 'RSS_LIMIT'; break
            if n % 200 == 0 and ocrq_gb() > OCRQ_GB: end = 'OCR_QUEUE_FULL'; log('OCR queue', ocrq_gb(), 'GB -> stop; run ocr mode then resume'); break
            rec = fetch_one(net, did, slug); out.write(json.dumps(rec, ensure_ascii=False) + '\n'); out.flush(); n += 1
            if n % 50 == 0:
                log(f'{n} done, {net.n} req, {net.n / (time.time() - t0):.2f} req/s, rss {rss()}MB')
                state_merge(dict(idp_progress=n, idp_last_id=did, idp_ts=time.strftime('%Y-%m-%dT%H:%M:%S%z')))
    except SystemExit as e:
        end = 'STOP_403_429_503'; log(e)
    finally:
        state_merge(dict(idp_status=f'HOLD_{tag.upper()}_{end}', idp_pid=None, idp_progress=n, idp_ts=time.strftime('%Y-%m-%dT%H:%M:%S%z')), collectors_delta=-1)
    log('end', end, n)
# ---------------- text / OCR / build (offline) ----------------
def pdf_pages(p):
    m = re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', p], capture_output=True, text=True).stdout); return int(m.group(1)) if m else 0
def pdf_text(p):
    return subprocess.run(['pdftotext', '-layout', p, '-'], capture_output=True, text=True, timeout=600).stdout
def _tess(im):
    return subprocess.run(['tesseract', im, '-', '-l', 'ind+eng'], capture_output=True, text=True, env=dict(os.environ, OMP_THREAD_LIMIT='1')).stdout
def _ocr_page(p, pg, d):
    """Render page at 300 dpi (long side capped 3508 px) and OCR; if that yields <80 chars (seen on phone-scanner PDFs with oversized
    page boxes, e.g. 'Scanned by TapScanner'), fall back to OCR of the largest embedded native image of that page."""
    subprocess.run(['pdftoppm', '-f', str(pg), '-l', str(pg), '-r', '300', '-scale-to', '3508', '-gray', '-png', p, f'{d}/r{pg}'], check=True)
    ims = [f for f in os.listdir(d) if f.startswith(f'r{pg}-') or f == f'r{pg}.png']
    t = _tess(os.path.join(d, ims[0])) if ims else ''
    for f in ims: os.remove(os.path.join(d, f))
    if len(re.sub(r'\s', '', t)) < 80:
        subprocess.run(['pdfimages', '-f', str(pg), '-l', str(pg), '-png', p, f'{d}/n{pg}'], check=True)
        nat = sorted((os.path.join(d, f) for f in os.listdir(d) if f.startswith(f'n{pg}-')), key=os.path.getsize)
        if nat:
            t2 = _tess(nat[-1])
            if len(t2.strip()) > len(t.strip()): t = t2
        for f in nat: os.remove(f)
    return t
def ocr_pdf(p, out_txt, workers=2):
    import tempfile
    from concurrent.futures import ThreadPoolExecutor
    d = tempfile.mkdtemp(prefix='idocr_', dir='/workspace/tmp'); n = pdf_pages(p)
    with ThreadPoolExecutor(workers) as ex: texts = list(ex.map(lambda pg: _ocr_page(p, pg, d), range(1, n + 1)))
    os.rmdir(d); open(out_txt, 'w').write('\n\f'.join(texts))
    return texts
def doc_text(fileid):
    ot = cpath('ocr', fileid, '.txt')
    info = json.load(open(cpath('text', fileid, '.json'))); pages = info['pages']
    if os.path.exists(ot): return open(ot).read(), 'ocr_tesseract_ind+eng_300dpi', pages
    t = gzip.open(cpath('text', fileid, '.txt.gz'), 'rt').read()
    return t, ('pdf_text_layer' if not info['needs_ocr'] else 'pdf_text_layer_poor_needs_ocr'), pages
def ocr_mode(workers):
    for l in open(f'{B}/ledger_full.jsonl'):
        r = json.loads(l)
        for f in r.get('files', []):
            if f['status'] != 'ok': continue
            pp = cpath('pdf', f['fileid'], '.pdf'); ot = cpath('ocr', f['fileid'], '.txt')
            if os.path.exists(ot) or not os.path.exists(pp) or not f.get('needs_ocr'): continue
            if memavail() <= MEMAVAIL_MB: log('MemAvailable low -> stop OCR'); return
            ocr_pdf(pp, ot, workers)
            if not KEEP_PDF: os.remove(pp)
def build_rows(r):
    meta = r.get('meta', {}); law_id = f"ID-BPK-{r['id']}"; jur, reg = jurisdiction(r['slug'])
    texts, methods, pages = [], [], 0
    for f in r.get('files', []):
        if f['status'] != 'ok': continue
        t, m, pg = doc_text(f['fileid']); texts.append(t); methods.append(m); pages += pg
    text = '\n\n'.join(texts).strip(); arts = split_pasal(texts[0] if texts else ''); gaps = getattr(split_pasal, 'last_gaps', [])
    bs = meta.get('Bentuk Singkat') or ''; teu = meta.get('T.E.U.') or ''
    region_name = re.sub(r'^Indonesia,\s*', '', teu)
    ident = f"{bs} {region_name} No. {meta.get('Nomor', '')} Tahun {meta.get('Tahun', '')}".strip()
    md = dict(source='JDIH BPK peraturan.bpk.go.id', detail_id=r['id'], slug=r['slug'], bpk_metadata=meta, files=r.get('files'), text_methods=methods,
              pages=pages, pasal_gaps=gaps, region=reg, jurisdiction_scheme='ID-<BPS prov>[-<BPS kab/kota>]')
    status = (meta.get('Status') or '').lower()
    law = dict(id=law_id, title=meta.get('Judul'), text=text, source_url=f"{BASE}/Details/{r['id']}/{r['slug']}", source_type='regional_legislation' if jur != 'ID' else 'national_legislation',
               jurisdiction=jur, country='Indonesia', language='id', eli=None, date=iso_date(meta.get('Tanggal Berlaku')), date_issued=iso_date(meta.get('Tanggal Penetapan')),
               retrieved_at=r.get('retrieved_at'), license=LICENSE, law_status='current' if status == 'berlaku' else ('repealed' if 'tidak' in status else status or None),
               identifier=law_id, official_identifier=ident, article_count=len(arts), json_path=None, metadata_json=json.dumps(md, ensure_ascii=False))
    src = r['files'][0]['url'] if r.get('files') else law['source_url']
    arows = [dict(law_id=law_id, id=f"{law_id}-pasal-{a['num']}", title=f"Pasal {a['num']}", text=a['text'], source_url=src, document_number=f"Pasal {a['num']}",
                  article_number=a['num'], record_type=a['record_type'], metadata_json=json.dumps(dict(law_identifier=law_id, ordinal=i + 1, text_method=methods[0] if methods else None, pasal_gaps=gaps)))
             for i, a in enumerate(arts)]
    return law, arows
def build(outdir):
    import pyarrow as pa, pyarrow.parquet as pq
    os.makedirs(f'{outdir}/data', exist_ok=True); laws, arts = [], []
    for l in open(f'{B}/ledger_full.jsonl'):
        r = json.loads(l)
        if r.get('status') != 'ok': continue
        a, b = build_rows(r); laws.append(a); arts.extend(b)
    ls = pa.schema([(c, pa.int32() if c == 'article_count' else pa.string()) for c in LAW_COLS]); as_ = pa.schema([(c, pa.string()) for c in ART_COLS])
    pq.write_table(pa.Table.from_pylist(laws, schema=ls), f'{outdir}/data/laws.parquet'); pq.write_table(pa.Table.from_pylist(arts, schema=as_), f'{outdir}/data/articles.parquet')
    log('built', len(laws), 'laws', len(arts), 'articles')
    import pa_exit_guard; pa_exit_guard.release()  # exit guard (pa_exit_guard): Tables were temporaries; gc before returning
def selftest():
    import glob
    for hp in sorted(glob.glob(f'{B}/probe/detail_*.html'))[:10]:
        did = re.search(r'detail_(\d+)', hp).group(1); s = open(hp, encoding='utf-8', errors='replace').read(); meta, dls = parse_detail(s)
        pdf = f'{B}/pdf/{did}.pdf'; arts = []
        if os.path.exists(pdf) and open(pdf, 'rb').read(5) == b'%PDF-':
            tp = f'{B}/handcheck_text/{did}.txt'; arts = split_pasal(open(tp).read() if os.path.exists(tp) else pdf_text(pdf))
        print(did, meta.get('Bentuk Singkat'), meta.get('T.E.U.'), meta.get('Nomor'), meta.get('Tahun'), meta.get('Status'), len(dls), 'pasal', len(arts), [a['num'] for a in arts][:8])
if __name__ == '__main__' and not (len(sys.argv) > 1 and sys.argv[1] == 'drive'):
    a = sys.argv[1:]
    if not a: print(__doc__); sys.exit(1)
    if a[0] == 'selftest': selftest()
    elif a[0] == 'sample':
        n = int(a[1]); seed = int(a[a.index('--seed') + 1]) if '--seed' in a else 1
        assert n <= 200, 'sample mode is probe-scale only (<=200)'
        t = enumerate_targets(); random.Random(seed).shuffle(t); run(t[:n], 'sample')
    elif a[0] == 'full':
        tok = a[a.index('--cos-go') + 1] if '--cos-go' in a else None; gf = f'{B}/COS_GO_FULL'
        if not tok or not os.path.exists(gf) or open(gf).read().strip() != tok: sys.exit('REFUSED: full run needs a CoS GO (id_bpk/COS_GO_FULL token)')
        run(enumerate_targets('--include-pusat' in a), 'full')
    elif a[0] == 'ocr': ocr_mode(int(a[a.index('--workers') + 1]) if '--workers' in a else 2)
    elif a[0] == 'build': import pa_exit_guard; pa_exit_guard.run_guarded(build, a[1])  # exit guard (pa_exit_guard): real exit code via os._exit
    else: print(__doc__); sys.exit(1)

# =====================================================================================================================
# DRIVER (CoS LIMITED GO 2026-10-04 16:41 PT): phase 1 metadata-only over regional detail pages -> phase 2 tranche 1 PDF+text
# (CoS 20:13 PT: ID-34 DI Yogyakarta + ID-51 Bali + ID-75 Gorontalo only; ID-33 later after CoS review). Stops after tranche 1.
#   python3 id_bpk_collect.py drive --cos-go TOKEN [--phase1-only] [--pause-for-cz]
# Resume: phase 1 cursor id_bpk/phase1/cursor.json (next target index), ledger phase1/meta.jsonl; phase 2 cursor tranche1/cursor.json, ledger tranche1/docs.jsonl.
# SIGTERM -> finish current record, write cursor, exit. --pause-for-cz: status PHASE1_PAUSED_FOR_CZ_T1 on SIGTERM exit (cursor kept).
# =====================================================================================================================
import threading as _th
sys.path.insert(0, '/workspace/scripts')
import slot2_common as S2
P1 = f'{B}/phase1'; T1 = f'{B}/tranche1'
T1_PROVINCES = ('34', '51', '75')   # DI Yogyakarta, Bali, Gorontalo (CoS 2026-10-04 20:13 PT)
_CURS = {}
def _go_ok(tok):
    gf = f'{B}/COS_GO_FULL'
    return bool(tok) and os.path.exists(gf) and open(gf).readline().strip() == tok
def _now(): return time.strftime('%Y-%m-%dT%H:%M:%S%z')
def _eta(rem_s): return time.strftime('%Y-%m-%d %H:%M %Z', time.localtime(time.time() + rem_s))
def _tail_ids(path, n=50):
    if not os.path.exists(path): return set()
    with open(path, 'rb') as f:
        f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 200000)); lines = f.read().decode('utf-8', 'replace').splitlines()[-n:]
    out = set()
    for l in lines:
        try: out.add(json.loads(l)['id'])
        except Exception: pass
    return out
def phase1(net, total_hint):
    os.makedirs(P1, exist_ok=True); curf = f'{P1}/cursor.json'; led = f'{P1}/meta.jsonl'
    cur = json.load(open(curf)) if os.path.exists(curf) else dict(next_idx=0, done=0, errors=0)
    _CURS['p1'] = (curf, cur)
    if cur.get('complete'): log('phase 1 already complete'); return True
    tail = _tail_ids(led); out = open(led, 'a'); t0 = time.time(); n0 = cur['done']; req0 = net.n
    log(f"PHASE1 start/resume at idx {cur['next_idx']} (done {cur['done']}), total {total_hint}")
    S2.state_merge('idp_', dict(idp_status='PHASE1_LIVE', idp_phase='PHASE1', idp_p1_total=total_hint, idp_p1_cursor=cur['next_idx'], idp_p1_done=cur['done'], idp_ts=_now()))
    with open(f'{B}/index/regional_targets.tsv') as tf:
        for line in tf:
            idx, did, slug, lvl, typ, region, jur = line.rstrip('\n').split('\t'); idx = int(idx)
            if idx < cur['next_idx']: continue
            if S2.STOP.is_set(): return False
            if did in tail:   # written before a crash but cursor not advanced
                cur['next_idx'] = idx + 1; cur['done'] += 1; continue
            st, body, _ = net.get(f'/Details/{did}/{slug}')
            rec = dict(i=idx, id=did, slug=slug, lvl=lvl, type=typ, region=region, jurisdiction=jur, http=st, retrieved_at=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
            if st == 200 and body:
                hp = cpath('detail', did, '.html.gz'); gzip.open(hp, 'wb').write(body)
                meta, dls = parse_detail(body.decode('utf-8', 'replace')); rec['meta'] = meta; rec['downloads'] = dls
            else:
                cur['errors'] = cur.get('errors', 0) + 1
            out.write(json.dumps(rec, ensure_ascii=False) + '\n'); out.flush()
            cur['next_idx'] = idx + 1; cur['done'] += 1
            if cur['done'] % 25 == 0:
                json.dump(cur, open(curf + '.tmp', 'w')); os.replace(curf + '.tmp', curf)
            if cur['done'] % 200 == 0:
                el = time.time() - t0; rate = (cur['done'] - n0) / max(el, 1); rem = (total_hint - cur['done']) / max(rate, 1e-6)
                log(f"P1 {cur['done']}/{total_hint} idx {idx} rate {rate:.3f} docs/s {(net.n - req0) / max(el, 1):.3f} req/s codes {net.codes} rss {S2.rss_mb()}MB mem {S2.memavail()}MB eta {_eta(rem)}")
                S2.state_merge('idp_', dict(idp_status='PHASE1_LIVE', idp_p1_done=cur['done'], idp_p1_cursor=cur['next_idx'], idp_p1_errors=cur.get('errors', 0),
                                            idp_p1_rate_docs_s=round(rate, 3), idp_p1_eta_pt=_eta(rem), idp_http_codes={str(k): v for k, v in net.codes.items()}, idp_ts=_now()))
    cur['complete'] = True; json.dump(cur, open(curf + '.tmp', 'w')); os.replace(curf + '.tmp', curf)
    S2.state_merge('idp_', dict(idp_status='PHASE1_DONE', idp_p1_done=cur['done'], idp_p1_cursor=cur['next_idx'], idp_p1_complete_pt=time.strftime('%Y-%m-%d %H:%M %Z'), idp_ts=_now()))
    return True
def _save_cursor1(net=None):
    pass
def tranche1_select():
    os.makedirs(T1, exist_ok=True); selp = f'{T1}/selection.jsonl'
    if os.path.exists(selp) and os.path.exists(f'{T1}/selection_summary.json'):
        old = json.load(open(f'{T1}/selection_summary.json'))
        if tuple(old.get('provinces', [])) == T1_PROVINCES: return old
        log('selection built for', old.get('provinces'), '!= T1_PROVINCES', T1_PROVINCES, '-> rebuilding'); os.replace(selp, selp + '.superseded')
    import collections
    cnt = collections.Counter(); seen = set()
    for l in open(f'{P1}/meta.jsonl'):
        r = json.loads(l)
        if r['id'] in seen: continue
        seen.add(r['id']); cnt[r['jurisdiction'].split('-')[1] if '-' in r['jurisdiction'] else 'ID'] += 1
    provs = list(T1_PROVINCES)   # CoS 2026-10-04 20:13 PT: fixed set, NO auto-add of ID-33 (Jawa Tengah = later tranche after CoS review)
    n = 0; seen = set()
    with open(selp, 'w') as f:
        for l in open(f'{P1}/meta.jsonl'):
            r = json.loads(l)
            if r['id'] in seen or r.get('http') != 200: continue
            p = r['jurisdiction'].split('-')[1] if '-' in r['jurisdiction'] else 'ID'
            if p in provs:
                seen.add(r['id']); n += 1
                f.write(json.dumps(dict(id=r['id'], slug=r['slug'], jurisdiction=r['jurisdiction'], downloads=r.get('downloads', [])), ensure_ascii=False) + '\n')
    summ = dict(provinces=provs, counts_phase1={p: cnt[p] for p in provs}, selected_docs=n, rule='CoS 2026-10-04 20:13 PT: tranche 1 = ID-34 DI Yogyakarta + ID-51 Bali + ID-75 Gorontalo only; ID-33 later after CoS review', ts=_now())
    json.dump(summ, open(f'{T1}/selection_summary.json', 'w'), indent=1); return summ
_IDDIC = None
def id_dict_ratio(text, max_unique=3000):
    global _IDDIC
    if _IDDIC is None:
        from spylls.hunspell import Dictionary
        _IDDIC = Dictionary.from_files('/usr/share/hunspell/id_ID')
    import collections
    c = collections.Counter(w.lower() for w in re.findall(r'[A-Za-z]{2,}', text)); top = c.most_common(max_unique); tot = sum(n for _, n in top)
    good = 0
    for w, k in top:
        try:
            if _IDDIC.lookup(w): good += k
        except Exception: pass
    return round(good / max(tot, 1), 4)
def phase2(net, ocr):
    summ = tranche1_select(); log('TRANCHE1 selection', summ)
    curf = f'{T1}/cursor.json'; led = f'{T1}/docs.jsonl'; skipf = f'{T1}/skipped_over1000pages.jsonl'
    QD = f'{B}/raw/ocrq'; TD = f'{B}/raw/text'; os.makedirs(QD, exist_ok=True); os.makedirs(TD, exist_ok=True)
    cur = json.load(open(curf)) if os.path.exists(curf) else dict(next_idx=0, done=0)
    _CURS['p2'] = (curf, cur)
    tail = _tail_ids(led); out = open(led, 'a'); t0 = time.time(); n0 = cur['done']; total = summ['selected_docs']
    S2.state_merge('idp_', dict(idp_status='PHASE2_TRANCHE1_LIVE', idp_phase='PHASE2', idp_t1_provinces=summ['provinces'], idp_t1_total=total, idp_t1_done=cur['done'], idp_ts=_now()))
    with open(f'{T1}/selection.jsonl') as sf:
        for idx, l in enumerate(sf):
            if idx < cur['next_idx']: continue
            if S2.STOP.is_set(): return False
            r = json.loads(l)
            if r['id'] in tail: cur['next_idx'] = idx + 1; continue
            while S2.dir_gb(QD) > OCRQ_GB:   # OCR backlog cap
                if S2.STOP.is_set(): return False
                S2.state_merge('idp_', dict(idp_status='PHASE2_PAUSED_OCR_BACKLOG', idp_ts=_now())); time.sleep(60)
            files = []
            for dl in r['downloads']:
                fid = dl.split('/')[2]; tp = f'{TD}/{fid}.txt.gz'; info = f'{TD}/{fid}.json'
                if os.path.exists(info): files.append(dict(json.load(open(info)), fileid=fid, url=BASE + dl)); continue
                st, body, hdr = net.get(dl)
                if st != 200 or not body or body[:5] != b'%PDF-':
                    files.append(dict(fileid=fid, url=BASE + dl, status=f'pdf_http_{st}')); continue
                tmp = f'{B}/raw/{fid}.pdf.part'; open(tmp, 'wb').write(body); body = None
                pages = S2.pdf_pages(tmp); sz = os.path.getsize(tmp); sha = hashlib.sha256(open(tmp, 'rb').read()).hexdigest()
                if pages > 1000:
                    os.remove(tmp); open(skipf, 'a').write(json.dumps(dict(id=r['id'], fileid=fid, url=BASE + dl, pages=pages, bytes=sz, ts=_now())) + '\n')
                    d = dict(status='skipped_over_1000_pages', pages=pages, bytes=sz, sha256=sha)
                else:
                    t = subprocess.run(['pdftotext', '-layout', tmp, '-'], capture_output=True, text=True, timeout=900).stdout
                    q = text_quality(t, pages); q['dict_ratio'] = id_dict_ratio(t) if q['chars'] else 0.0
                    ocr_need = needs_ocr(q) or q['dict_ratio'] < 0.75
                    with gzip.open(tp, 'wt') as f: f.write(t)
                    if ocr_need: os.replace(tmp, f'{QD}/{fid}.pdf')
                    else: os.remove(tmp)
                    d = dict(status='ok', pages=pages, bytes=sz, sha256=sha, layer_quality=q, needs_ocr=ocr_need)
                json.dump(d, open(info, 'w')); files.append(dict(d, fileid=fid, url=BASE + dl))
            out.write(json.dumps(dict(id=r['id'], slug=r['slug'], jurisdiction=r['jurisdiction'], files=files, retrieved_at=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')), ensure_ascii=False) + '\n'); out.flush()
            cur['next_idx'] = idx + 1; cur['done'] += 1
            if cur['done'] % 10 == 0: json.dump(cur, open(curf + '.tmp', 'w')); os.replace(curf + '.tmp', curf)
            if cur['done'] % 100 == 0:
                el = time.time() - t0; rate = (cur['done'] - n0) / max(el, 1); rem = (total - cur['done']) / max(rate, 1e-6)
                log(f"P2 {cur['done']}/{total} rate {rate:.3f} docs/s codes {net.codes} ocrq {S2.dir_gb(QD):.2f}GB ocr_done {ocr.done_n} rss {S2.rss_mb()}MB mem {S2.memavail()}MB eta {_eta(rem)}")
                S2.state_merge('idp_', dict(idp_status='PHASE2_TRANCHE1_LIVE', idp_t1_done=cur['done'], idp_t1_cursor=cur['next_idx'], idp_t1_rate_docs_s=round(rate, 3), idp_t1_eta_pt=_eta(rem),
                                            idp_t1_ocr_queue_gb=round(S2.dir_gb(QD), 2), idp_t1_ocr_done=ocr.done_n, idp_http_codes={str(k): v for k, v in net.codes.items()}, idp_ts=_now()))
    json.dump(dict(cur, complete=True), open(curf + '.tmp', 'w')); os.replace(curf + '.tmp', curf)
    log('P2 fetch complete; draining OCR queue'); ocr.finish.set()
    while not ocr.idle.is_set() or ocr.pending():
        if S2.STOP.is_set(): return False
        S2.state_merge('idp_', dict(idp_status='PHASE2_OCR_DRAIN', idp_t1_ocr_queue_gb=round(S2.dir_gb(QD), 2), idp_t1_ocr_done=ocr.done_n, idp_ts=_now())); time.sleep(60)
    return True
def drive(argv):
    tok = argv[argv.index('--cos-go') + 1] if '--cos-go' in argv else None
    if not _go_ok(tok): sys.exit('REFUSED: drive needs the CoS GO token (id_bpk/COS_GO_FULL)')
    S2.install_signals(); os.makedirs('/workspace/tmp', exist_ok=True)
    pause_for_cz = '--pause-for-cz' in argv
    guard = S2.Guard('idp_', status_cb=lambda s: S2.state_merge('idp_', dict(idp_pause=s, idp_ts=_now())))
    if S2.memavail() < S2.MEM_PAUSE: sys.exit(f'REFUSED: MemAvailable {S2.memavail()} MB < 4500 at launch')
    net = S2.Net(BASE, UA, guard, delay=DELAY)
    total = sum(1 for _ in open(f'{B}/index/regional_targets.tsv'))
    S2.state_merge('idp_', dict(idp_status='PHASE1_LIVE', idp_pid=os.getpid(), idp_log=os.environ.get('IDP_LOG'), idp_started_pt=time.strftime('%Y-%m-%d %H:%M %Z'),
                                idp_collectors_bumped=True, idp_ts=_now()), collectors_delta=+1)
    end = 'UNKNOWN'; ocr = None
    try:
        ok = phase1(net, total)
        if not ok: end = 'PHASE1_PAUSED_FOR_CZ_T1' if pause_for_cz else 'PHASE1_STOPPED_BY_SIGNAL'
        elif '--phase1-only' in argv: end = 'PHASE1_DONE_HOLD'
        else:
            ocr = S2.OCRWorker(f'{B}/raw/ocrq', f'{B}/raw/ocr', 'ind+eng', guard, workers=2); ocr.start()
            ok = phase2(net, ocr)
            end = 'HOLD_TRANCHE1_DONE_AWAIT_COS' if ok else 'PHASE2_STOPPED_BY_SIGNAL'
    except S2.HostBlocked as e: end = 'STOP_3x403_429_503'; log(e)
    except S2.MemShed as e: end = 'MEMSHED'; log(e)
    except S2.Stopped: end = 'PHASE1_PAUSED_FOR_CZ_T1' if pause_for_cz else 'STOPPED_BY_SIGNAL'
    except Exception as e:
        import traceback; traceback.print_exc(); end = f'ERROR_{type(e).__name__}'
    finally:
        S2.STOP.set()
        for k, (cf, c) in _CURS.items():
            json.dump(c, open(cf + '.tmp', 'w')); os.replace(cf + '.tmp', cf); log('cursor saved', k, c)
        S2.state_merge('idp_', dict(idp_status=end, idp_pid=None, idp_collectors_bumped=False, idp_requests_this_run=net.n,
                                    idp_http_codes={str(k): v for k, v in net.codes.items()}, idp_exit_pt=time.strftime('%Y-%m-%d %H:%M %Z'), idp_ts=_now()), collectors_delta=-1)
        log('DRIVER EXIT', end, 'requests', net.n, net.codes)
if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == 'drive':
    drive(sys.argv[2:])

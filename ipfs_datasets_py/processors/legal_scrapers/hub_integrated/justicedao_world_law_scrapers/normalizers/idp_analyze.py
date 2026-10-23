#!/usr/bin/env python3
"""Offline analysis of ID BPK probe sample. Modes:
  layer     : text-layer survey of all sampled PDFs -> id_bpk/index/sample_layer.json
  handcheck : 20-doc hand check (OCR ind+eng where needed) -> id_bpk/handcheck_prerun.json/.md"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, re, subprocess, os, sys, time, statistics, collections, tempfile, glob
B = '{_CORPORA}/id_bpk'
def pdfinfo(p):
    r = subprocess.run(['pdfinfo', p], capture_output=True, text=True, timeout=60).stdout
    m = re.search(r'Pages:\s+(\d+)', r); pr = re.search(r'Producer:\s+(.*)', r); cr = re.search(r'Creator:\s+(.*)', r)
    return dict(pages=int(m.group(1)) if m else 0, producer=pr.group(1).strip() if pr else '', creator=cr.group(1).strip() if cr else '')
def pdftext(p):
    return subprocess.run(['pdftotext', '-layout', p, '-'], capture_output=True, text=True, timeout=300).stdout
_D = None; _cache = {}
def dic():
    global _D
    if _D is None:
        from spylls.hunspell import Dictionary
        _D = Dictionary.from_files('/usr/share/hunspell/id_ID')
    return _D
EN = None
def en_words():
    global EN
    if EN is None: EN = {w.strip().lower() for w in open('/usr/share/dict/american-english', errors='ignore')}
    return EN
def word_ok(w):
    lw = w.lower()
    if lw in _cache: return _cache[lw]
    ok = False
    try: ok = dic().lookup(lw) or dic().lookup(w)
    except Exception: ok = False
    _cache[lw] = ok; return ok
def quality(text, pages):
    toks = text.split()
    alpha = [re.sub(r'^[\W_]+|[\W_]+$', '', t) for t in toks]
    alpha = [a for a in alpha if re.fullmatch(r'[A-Za-z]{2,}', a or '')]
    uniq = collections.Counter(a.lower() for a in alpha)
    good = sum(c for w, c in uniq.items() if word_ok(w) or w in en_words())
    def garbage(t):
        if not re.search(r'[A-Za-z0-9]', t): return len(t) > 2
        core = re.sub(r'^[\W_]+|[\W_]+$', '', t)
        if not core: return False
        bad = len(re.findall(r'[^A-Za-z0-9.,;:()\'"/%\-]', core))
        if bad / len(core) > 0.3: return True
        if re.fullmatch(r'[A-Za-z]{5,}', core) and not re.search(r'[aeiouAEIOU]', core): return True
        if re.search(r'[a-z][A-Z][a-z]', core) and len(core) > 4: return True
        return False
    g = sum(1 for t in toks if garbage(t))
    nonws = len(re.sub(r'\s', '', text))
    return dict(chars=nonws, chars_per_page=round(nonws / max(pages, 1), 1), tokens=len(toks), alpha_tokens=len(alpha),
                dict_ratio=round(good / max(len(alpha), 1), 4), garbage_ratio=round(g / max(len(toks), 1), 4))
ROMAN = {'I':1,'II':2,'III':3,'IV':4,'V':5,'VI':6,'VII':7,'VIII':8,'IX':9,'X':10}
def pasal_stats(text):
    nums, rom = [], []
    for line in text.split('\n'):
        s = line.strip()
        m = re.fullmatch(r'P\s?a\s?s\s?a\s?l\s+(\d{1,3})\s*[A-Z]?', s)
        if m: nums.append(int(m.group(1))); continue
        m = re.fullmatch(r'PASAL\s+(\d{1,3})', s)
        if m: nums.append(int(m.group(1))); continue
        m = re.fullmatch(r'(?:Pasal|PASAL)\s+([IVX]{1,4})', s)
        if m and m.group(1) in ROMAN: rom.append(ROMAN[m.group(1)])
    # main sequence: greedy increasing sequence starting at 1 (quoted amended Pasal inside Pasal I break monotonicity)
    seq, exp = [], 1
    for n in nums:
        if n == exp: seq.append(n); exp += 1
    mx = max(nums) if nums else 0
    missing = sorted(set(range(1, mx + 1)) - set(nums)) if mx and mx < 400 else []
    return dict(pasal_headings=len(nums), pasal_max=mx, pasal_main_seq=len(seq), pasal_missing=missing[:30], pasal_missing_n=len(missing),
                pasal_roman=len(rom), pasal_roman_max=max(rom) if rom else 0)
def endings(text):
    t = re.sub(r'\s+', ' ', text).lower()
    return dict(has_ditetapkan='ditetapkan di' in t, has_diundangkan='diundangkan di' in t or 'diundangkan' in t,
                has_mulai_berlaku='mulai berlaku' in t, has_lembaran_berita=bool(re.search(r'(lembaran|berita) daerah', t)),
                has_menimbang='menimbang' in t, has_memutuskan='memutuskan' in t or 'menetapkan' in t)
def is_pdf(p):
    try: return open(p, 'rb').read(5) == b'%PDF-'
    except Exception: return False
def classify(q, pages, fonts_ok):
    if q['chars_per_page'] >= 300 and q['dict_ratio'] >= 0.6: return 'text_layer'
    if q['chars_per_page'] < 50: return 'scan'
    return 'mixed_or_poor_text'
def fonts(p):
    r = subprocess.run(['pdffonts', p], capture_output=True, text=True, timeout=60).stdout.strip().split('\n')
    return max(len(r) - 2, 0)
def recs():
    return [json.loads(l) for l in open(f'{B}/index/sample.jsonl')]
def layer():
    out = []
    for r in recs():
        p = f"{B}/pdf/{r['id']}.pdf"
        e = dict(id=r['id'], slug=r['slug'], lvl=r['lvl'], type=r['type'], region=r['region'], year=r.get('meta', {}).get('Tahun'),
                 detail_http=r.get('detail_http'), pdf_http=r.get('pdf_http'), n_downloads=len(r.get('downloads', [])), pdf_bytes=r.get('pdf_bytes'))
        if r.get('pdf_http') == '200' and is_pdf(p):
            pi = pdfinfo(p); t = pdftext(p); q = quality(t, pi['pages']); nf = fonts(p)
            im = subprocess.run(['pdfimages', '-list', p], capture_output=True, text=True, timeout=120).stdout.strip().split('\n')[2:]
            e['images'] = len(im); e['images_per_page'] = round(len(im) / max(pi['pages'], 1), 2)
            e['embedded_ocr_suspect'] = bool(e['images_per_page'] >= 0.9 and q['chars_per_page'] >= 50)
            e.update(pi); e.update(q); e['fonts'] = nf; e['layer'] = classify(q, pi['pages'], nf)
        else:
            e['layer'] = 'no_pdf' if not r.get('downloads') else 'pdf_fetch_failed'
        out.append(e); print(e['id'], e['type'], e.get('year'), e.get('pages'), e.get('chars_per_page'), e.get('dict_ratio'), e['layer'], flush=True)
    json.dump(out, open(f'{B}/index/sample_layer.json', 'w'), indent=1, ensure_ascii=False)
def ocr(p, pages, maxpages=80, workers=2):
    d = tempfile.mkdtemp(prefix='idpocr_', dir='/workspace/tmp' if os.path.isdir('/workspace/tmp') else None)
    n = min(pages, maxpages); t0 = time.time()
    subprocess.run(['pdftoppm', '-r', '300', '-scale-to', '3508', '-gray', '-png', '-l', str(n), p, f'{d}/pg'], check=True, timeout=3600)  # cap long side at A4@300dpi (some scans have oversized page boxes)
    imgs = sorted(glob.glob(f'{d}/pg*.png'))
    procs, texts = [], {}
    def start(i, im):
        return subprocess.Popen(['tesseract', im, '-', '-l', 'ind+eng', '--psm', '3'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=dict(os.environ, OMP_THREAD_LIMIT='1'))
    q = list(enumerate(imgs)); running = []
    while q or running:
        while q and len(running) < workers: i, im = q.pop(0); running.append((i, start(i, im)))
        i, pr = running.pop(0); texts[i] = pr.communicate()[0]
    for im in imgs: os.remove(im)
    os.rmdir(d)
    return '\n\f'.join(texts[i] for i in sorted(texts)), n, round(time.time() - t0, 1)
def handcheck():
    L = {e['id']: e for e in json.load(open(f'{B}/index/sample_layer.json'))}
    sel = json.load(open(f'{B}/index/handcheck_selection.json'))
    res = json.load(open(f'{B}/handcheck_prerun.json')) if os.path.exists(f'{B}/handcheck_prerun.json') else []
    have = {e['id'] for e in res}
    for did in sel:
        if did in have: continue
        e = dict(L[did]); p = f"{B}/pdf/{did}.pdf"; r = [x for x in recs() if x['id'] == did][0]
        e['title'] = r.get('meta', {}).get('Judul'); e['teu'] = r.get('meta', {}).get('T.E.U.'); e['status'] = r.get('meta', {}).get('Status'); e['nomor'] = r.get('meta', {}).get('Nomor'); e['pdf_url'] = r.get('pdf_url')
        tl = pdftext(p); e['text_layer'] = quality(tl, e['pages'])
        if e['layer'] == 'text_layer':
            e['method'] = 'pdf_text_layer'; text = tl
        else:
            text, n, secs = ocr(p, e['pages']); e['method'] = 'ocr_tesseract_ind+eng_300dpi'; e['ocr_pages'] = n; e['ocr_secs'] = secs
            e['ocr_secs_per_page_wall'] = round(secs / max(n, 1), 2); e['ocr_truncated_at_maxpages'] = n < e['pages']
        os.makedirs(f'{B}/handcheck_text', exist_ok=True); open(f'{B}/handcheck_text/{did}.txt', 'w').write(text)
        e['final'] = quality(text, e.get('ocr_pages', e['pages'])); e.update(pasal_stats(text)); e.update(endings(text))
        e['empty'] = e['final']['chars'] < 200
        e['truncated_suspect'] = not (e['has_ditetapkan'] or e['has_diundangkan']) or (e['pasal_max'] > 0 and e['pasal_main_seq'] < e['pasal_max'] * 0.8 and e['pasal_roman'] == 0)
        f = e['final']
        e['verdict'] = 'PASS' if (not e['empty'] and f['dict_ratio'] >= 0.75 and f['garbage_ratio'] <= 0.08 and (e['pasal_main_seq'] >= 1 or e['pasal_roman'] >= 1) and not e['truncated_suspect']) else ('WARN' if not e['empty'] else 'FAIL')
        res.append(e); print(did, e['type'], e['year'], e['method'], f, e['pasal_main_seq'], e['pasal_max'], e['pasal_roman'], e['verdict'], flush=True)
        json.dump(res, open(f'{B}/handcheck_prerun.json', 'w'), indent=1, ensure_ascii=False)
if __name__ == '__main__' and sys.argv[1] in ('layer', 'handcheck'):
    {'layer': layer, 'handcheck': handcheck}[sys.argv[1]]()
# ---- rescore (offline): Pasal stats with the collector's OCR-tolerant splitter + embedded-OCR vs tesseract comparison + report ----
def _collector():
    import importlib.util
    sp = importlib.util.spec_from_file_location('idc', '/workspace/scripts/id_bpk_collect.py'); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
def own_last_number(C, text):
    """Highest Pasal number used by the document as a clean standalone heading ('Pasal <n>' / 'PASAL <n>', any order)."""
    best = 0
    for p, c in C.heading_lines(text):
        m = re.fullmatch(r'(?i:pasal)(\d{1,3})[A-D]?', c)
        if m and int(m.group(1)) <= 400: best = max(best, int(m.group(1)))
    return best
def rescore():
    C = _collector(); res = json.load(open(f'{B}/handcheck_prerun.json'))
    for e in res:
        text = open(f"{B}/handcheck_text/{e['id']}.txt").read()
        arts = C.split_pasal(text); gaps = C.split_pasal.last_gaps
        e['split_articles'] = len(arts); e['split_record_type'] = arts[0]['record_type'] if arts else None
        e['split_first'] = arts[0]['num'] if arts else None; e['split_last'] = arts[-1]['num'] if arts else None; e['split_gaps'] = gaps
        e['own_last_number'] = len([a for a in arts if a['record_type'] == 'pasal_amending']) if arts and arts[0]['record_type'] == 'pasal_amending' else own_last_number(C, text)
        lastn = int(re.match(r'\d+', e['split_last']).group(0)) if arts and arts[0]['record_type'] == 'article' else len(arts)
        e['numbering_consistent'] = bool(arts) and lastn == e['own_last_number'] and not gaps
        e['empty_articles'] = sum(1 for a in arts if len(a['text']) < 25)
        f = e['final']
        e['truncated_suspect'] = not (e['has_ditetapkan'] or e['has_diundangkan'] or e['has_lembaran_berita'])
        issues = []
        if e['empty']: issues.append('empty')
        if f['dict_ratio'] < 0.80: issues.append(f"dict_ratio {f['dict_ratio']}")
        if f['garbage_ratio'] > 0.05: issues.append(f"garbage {f['garbage_ratio']}")
        if not arts: issues.append('no_pasal_split')
        if gaps: issues.append(f'pasal_gaps {gaps}')
        if arts and lastn != e['own_last_number']: issues.append(f"split_last {lastn} != own_last {e['own_last_number']}")
        if e['truncated_suspect']: issues.append('no closing formula (truncated?)')
        e['issues'] = issues
        e['verdict'] = 'FAIL' if (e['empty'] or not arts or f['dict_ratio'] < 0.6) else ('PASS' if not issues else 'WARN')
        # embedded OCR layer vs fresh tesseract on first 3 pages
        if e['method'] == 'pdf_text_layer' and e.get('embedded_ocr_suspect') and 'cmp' not in e:
            p = f"{B}/pdf/{e['id']}.pdf"; n = min(3, e['pages'])
            tl = subprocess.run(['pdftotext', '-layout', '-f', '1', '-l', str(n), p, '-'], capture_output=True, text=True).stdout
            d = tempfile.mkdtemp(dir='/workspace/tmp'); subprocess.run(['pdftoppm', '-r', '300', '-gray', '-png', '-l', str(n), p, f'{d}/pg'], check=True)
            t0 = time.time(); ot = ''
            for im in sorted(glob.glob(f'{d}/pg*.png')):
                ot += subprocess.run(['tesseract', im, '-', '-l', 'ind+eng'], capture_output=True, text=True, env=dict(os.environ, OMP_THREAD_LIMIT='1')).stdout; os.remove(im)
            os.rmdir(d)
            e['cmp'] = dict(pages=n, embedded=quality(tl, n), tesseract=quality(ot, n), tesseract_secs_per_page_1thread=round((time.time() - t0) / n, 2))
        print(e['id'], e['verdict'], e['split_articles'], e['own_last_number'], gaps, e['issues'], e.get('cmp', {}).get('embedded', {}).get('dict_ratio'), e.get('cmp', {}).get('tesseract', {}).get('dict_ratio'), flush=True)
    json.dump(res, open(f'{B}/handcheck_prerun.json', 'w'), indent=1, ensure_ascii=False)
if __name__ == '__main__' and sys.argv[1] == 'rescore': rescore()

"""WIPO Lex harvester (reconstructed 2026-09-17 after VM reboot).
Usage: python wipolex_harvest.py sz st ly
Skips WIPO IDs already present locally.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, re, html, json, glob, time
sys.path.insert(0, os.path.expanduser('~/workspace/wave5'))
sys.path.insert(0, '/tmp/wave5')
from lib import write_instrument, pdf_to_text
import requests

S = requests.Session()
S.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'})

JURIS = {'af': 'Afghanistan', 'so': 'Somalia', 'vu': 'Vanuatu', 'gm': 'Gambia',
         'kp': 'North Korea', 'bi': 'Burundi', 'gq': 'Equatorial Guinea',
         'ss': 'South Sudan', 'sr': 'Suriname', 'nu': 'Niue', 'er': 'Eritrea',
         'sd': 'Sudan', 'ls': 'Lesotho', 'pg': 'Papua New Guinea'}
ISO2 = {'af': 'AF', 'so': 'SO', 'vu': 'VU', 'gm': 'GM', 'kp': 'KP',
        'bi': 'BI', 'gq': 'GQ', 'ss': 'SS', 'sr': 'SR', 'nu': 'NU',
        'er': 'ER', 'sd': 'SD', 'ls': 'LS', 'pg': 'PG'}

def existing_wipo_ids(cc):
    ids = set()
    d = os.path.expanduser(f'~/.ipfs_datasets/legal-corpora/{cc}/instruments')
    for f in glob.glob(os.path.join(d, '*.json')):
        try:
            r = json.load(open(f))
            oid = r.get('official_identifier') or ''
            m = re.search(r'WIPO-LEX-(\d+)', oid)
            if m:
                ids.add(m.group(1))
        except Exception:
            pass
    return ids

def profile_ids(iso2):
    r = S.get(f'https://www.wipo.int/wipolex/en/members/profile/{iso2}', timeout=60)
    r.raise_for_status()
    return re.findall(r'/legislation/details/(\d+)', r.text)

def parse_detail(wid):
    url = f'https://www.wipo.int/wipolex/en/legislation/details/{wid}'
    r = S.get(url, timeout=60)
    r.raise_for_status()
    t = r.text
    m = re.search(r'<h1[^>]*>(.*?)</h1>', t, re.S)
    raw = html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip() if m else f'WIPO Lex record {wid}'
    title = re.sub(r'\s+', ' ', raw)
    pdfs = re.findall(r'href="(https://wipolex-res\.wipo\.int/edocs/lexdocs/laws/[a-z]{2}/[^"]+?\.pdf[^"]*)"', t)
    pdfs = [html.unescape(p).replace('&#x3D;', '=').replace('&amp;', '&') for p in pdfs]
    # language from first pdf path
    lang = 'en'
    if pdfs:
        lm = re.search(r'/laws/([a-z]{2})/', pdfs[0])
        if lm:
            lang = lm.group(1)
    # date: Adopted: ... or Year of Version
    date = None
    m2 = re.search(r'Adopted:\s*([A-Z][a-z]+ \d{1,2}, \d{4})', t)
    if m2:
        try:
            from datetime import datetime
            date = datetime.strptime(m2.group(1), '%B %d, %Y').date().isoformat()
        except Exception:
            pass
    if not date:
        m3 = re.search(r'Year of (?:Version|Adoption):\s*(\d{4})', t)
        if m3:
            date = f'{m3.group(1)}-01-01'
    # type
    stype = 'statute'
    if re.search(r'Constitution', title, re.I):
        stype = 'constitution'
    return title, pdfs, lang, date, stype

def main():
    for cc in sys.argv[1:]:
        done = existing_wipo_ids(cc)
        ids = profile_ids(ISO2[cc])
        print(f'===== {cc} ===== ({len(ids)} records, {len(done)} already have)')
        added = 0
        for wid in ids:
            if wid in done:
                continue
            try:
                title, pdfs, lang, date, stype = parse_detail(wid)
            except Exception as e:
                print(f'{cc} {wid} detail-fail {e}', flush=True)
                continue
            text = ''
            src = ''
            for pu in pdfs:
                try:
                    pr = S.get(pu, timeout=120)
                    if pr.status_code == 200 and pr.content[:4] == b'%PDF':
                        text = pdf_to_text(pr.content)
                        src = pu.split('?')[0]
                        if len(text.strip()) >= 300:
                            break
                except Exception:
                    continue
            p, s = write_instrument(cc, 'wipolex', title, text,
                                    f'https://www.wipo.int/wipolex/en/legislation/details/{wid}',
                                    stype, JURIS[cc], lang, date,
                                    f'WIPO-LEX-{wid}', law_status='in-force')
            print(f'{cc} {wid} {s} {title[:55]} ({lang})', flush=True)
            if s == 'ok':
                added += 1
            time.sleep(1)
        print(f'{cc}: WIPO added={added}', flush=True)

if __name__ == '__main__':
    main()

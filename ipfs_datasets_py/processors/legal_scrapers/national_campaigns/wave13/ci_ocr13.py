"""Wave 13 CI douanes OCR — the scanned origin-rules décrets.

Wave 11 downloads of these douanes.ci PDFs truncated at exactly 1 MiB
through this egress; wave 12 proved complete Wayback captures exist
(wave12/stats/ci_douanes_retry.json) but streamed them in memory and
discarded the bytes. This pass re-fetches STREAMED TO DISK (never held
in memory) and OCRs page-wise with per-page checkpoints
(ocr13_engine). An instrument is saved ONLY when every page has been
attempted and the text clears the quality bar + the wave-11 legal
marker filter; partial OCR stays banked in ocr_work for a future wave.

Targets:
 A. decret 2019-829 (32 pp) — snapshot 20240807093009 (proven complete)
 B. annexe decret 2019-829 (240 pp) — snapshot 20230805024939 (proven)
 C. decret 2023-1080 — ONE attempt: largest CDX snapshot, streamed;
    proceeds only if the assembled file parses completely.

Instruments use the wave-11 douanes scheme (source_type
'wayback-official-ci', ids ci-wayback-douanes-<slug>).
Stats: wave13/stats/ci_ocr13.json.
Usage: ci_ocr13.py [A|B|C ...]   (default: A C B)
"""
import json, os, re, sys, time
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common13 import WAVE13
from ocr13_engine import ocr_pdf_pages, quality

INST_DIR = os.path.expanduser('~/.ipfs_datasets/legal-corpora/ci/instruments')
S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) legal-data-research/1.0'})
TODAY = time.strftime('%Y-%m-%d', time.gmtime())
LEGAL_MARKERS = re.compile(r"(loi\s+n|décret|decret|arrêté|arrete|ordonnance|constitution|"
                           r"journal officiel|code\s+(électoral|electoral|civil|pénal|penal|"
                           r"de\s|des\s|du\s)|république de côte d'ivoire|republique de cote d'ivoire|"
                           r"assemblée nationale|assemblee nationale)", re.I)

TARGETS = {
    'A': {'url': 'http://www.douanes.ci/sites/default/files/decret_num_2019-829_du_09_octobre_2019_sur_les_regles_d_origines.pdf',
          'ts': '20240807093009',
          'iid': 'ci-wayback-douanes-decret-num-2019-829-du-09-octobre-2019-sur-les-regles-d-origines'},
    'B': {'url': 'http://www.douanes.ci/sites/default/files/annexe_decret_ndeg2019-829_du_09_octobre_2019_sur_les_regles_1.pdf',
          'ts': '20230805024939',
          'iid': 'ci-wayback-douanes-annexe-decret-ndeg2019-829-du-09-octobre-2019-sur-les-regles-1'},
    'C': {'url': 'https://www.douanes.ci/sites/default/files/decret_ndeg_2023-1080_du_28_decembre_2023.pdf',
          'ts': None,  # largest snapshot chosen in the single attempt
          'iid': 'ci-wayback-douanes-decret-ndeg-2023-1080-du-28-decembre-2023'},
}

def stream_to_disk(url, dest, timeout=900):
    try:
        with S.get(url, timeout=timeout, stream=True) as r:
            if r.status_code != 200:
                return None
            n = 0
            with open(dest, 'wb') as f:
                for ch in r.iter_content(1 << 16):
                    n += len(ch)
                    f.write(ch)
            return n
    except Exception:
        return None

def count_articles(text):
    pats = [r'(?m)^\s*Article\s+\d+', r'(?m)^\s*ARTICLE\s+\d+', r'(?m)^\s*Art\.\s*\d+']
    return max((len(re.findall(p, text)) for p in pats), default=0)

def derive_title(text):
    for line in text.splitlines():
        line = re.sub(r'\s+', ' ', line).strip()
        if len(line) >= 18 and not re.fullmatch(r'[\d\s\.\-_/]+', line):
            return line[:240]
    return 'Untitled document (OCR)'

def main():
    order = sys.argv[1:] or ['A', 'C', 'B']
    stats_path = os.path.join(WAVE13, 'stats', 'ci_ocr13.json')
    stats = json.load(open(stats_path)) if os.path.isfile(stats_path) else {'items': {}}
    cache_dir = os.path.join(WAVE13, 'pdf_cache', 'ci'); os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(INST_DIR, exist_ok=True)
    for key in order:
        t = TARGETS[key]
        iid = t['iid']
        if os.path.isfile(os.path.join(INST_DIR, iid + '.json')):
            stats['items'][key] = {'iid': iid, 'outcome': 'already_instrument'}
            json.dump(stats, open(stats_path, 'w'), indent=1)
            print(key, 'already instrument', flush=True)
            continue
        dest = os.path.join(cache_dir, iid + '.pdf')
        rec = {'iid': iid, 'url': t['url']}
        if not (os.path.isfile(dest) and os.path.getsize(dest) > 1_100_000):
            ts = t['ts']
            if key == 'C':
                api = ('https://web.archive.org/cdx/search/cdx?url=' + t['url'] +
                       '&output=json&fl=timestamp,length,statuscode,digest')
                try:
                    r = S.get(api, timeout=120)
                    rows = [row for row in r.json()[1:] if row[2] == '200'] if r.status_code == 200 else []
                except Exception:
                    rows = []
                if not rows:
                    rec['outcome'] = 'no_snapshot_found_single_attempt'
                    stats['items'][key] = rec
                    json.dump(stats, open(stats_path, 'w'), indent=1)
                    print(key, rec['outcome'], flush=True)
                    continue
                rows.sort(key=lambda s: int(s[1] or 0), reverse=True)
                ts = rows[0][0]
                rec['chosen_ts'] = ts
                rec['snapshot_length'] = rows[0][1]
            n = stream_to_disk(f"https://web.archive.org/web/{ts}id_/{t['url']}", dest)
            rec['fetched_bytes'] = n
            if not n:
                rec['outcome'] = 'fetch_failed'
                stats['items'][key] = rec
                json.dump(stats, open(stats_path, 'w'), indent=1)
                print(key, 'fetch failed', flush=True)
                continue
        try:
            import fitz
            doc = fitz.open(dest); rec['pages'] = len(doc); doc.close()
        except Exception as e:
            rec['outcome'] = f'unparseable: {type(e).__name__}'
            stats['items'][key] = rec
            json.dump(stats, open(stats_path, 'w'), indent=1)
            print(key, rec['outcome'], flush=True)
            continue
        text, npages, attempted = ocr_pdf_pages(dest, f"ci__{iid[-40:]}", 'fra')
        rec.update({'pages': npages, 'pages_attempted': attempted})
        ok, metrics = quality(text, 'fra')
        rec.update(metrics)
        marker = bool(LEGAL_MARKERS.search(text[:6000]))
        rec['legal_marker'] = marker
        if ok and marker and attempted == npages:
            ym = re.search(r'\b(19|20)\d{2}\b', text[:1500])
            r2 = {'id': iid, 'title': derive_title(text), 'text': text, 'source_url': t['url'],
                  'source_type': 'wayback-official-ci', 'jurisdiction': "Côte d'Ivoire",
                  'country': 'ci', 'language': 'fr', 'eli': None,
                  'date': ym.group(0) if ym else None,
                  'retrieved_at': TODAY + 'T00:00:00Z', 'license': 'public-domain',
                  'law_status': 'unknown', 'identifier': iid, 'official_identifier': '',
                  'article_count': count_articles(text)}
            json.dump(r2, open(os.path.join(INST_DIR, iid + '.json'), 'w'), ensure_ascii=False)
            rec['outcome'] = 'recovered'
        elif attempted < npages:
            rec['outcome'] = 'partial_ocr_banked_not_staged'
        else:
            rec['outcome'] = 'quality_or_marker_reject'
        stats['items'][key] = rec
        json.dump(stats, open(stats_path, 'w'), indent=1)
        print(key, rec['outcome'], {k: rec.get(k) for k in ('pages', 'chars', 'legal_marker')}, flush=True)
    print(json.dumps(stats, indent=1))

if __name__ == '__main__':
    main()

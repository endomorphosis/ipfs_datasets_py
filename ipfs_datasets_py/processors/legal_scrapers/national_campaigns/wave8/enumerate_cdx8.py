"""Wave 8 CDX enumeration only (no PDF fetch). Builds stats/cdx_cache_{cc}.json.
Never caches an empty result (wave7 GM false dead-end guard)."""
import json, os, re, sys, time
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common8 import WAVE8
PREFIX = {'vu': 'van', 'bi': 'bur', 'af': 'afg', 'gm': 'gam', 'gq': 'eqg',
          'so': 'som', 'ss': 'ssd', 'sr': 'sur', 'nu': 'niu', 'er': 'eri',
          'sd': 'sud', 'ls': 'les', 'pg': 'png'}
S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) legal-data-research/1.0'})
for cc in sys.argv[1:]:
    prefix = PREFIX[cc]
    cache = os.path.join(WAVE8, 'stats', f'cdx_cache_{cc}.json')
    if os.path.isfile(cache) and len(json.load(open(cache))) > 0:
        print(cc, 'cached', len(json.load(open(cache)))); continue
    found = {}
    for host in ('faolex.fao.org', 'extwprlegs1.fao.org'):
        url = (f"https://web.archive.org/cdx/search/cdx?url={host}/docs/pdf/{prefix}*"
               f"&output=json&limit=5000&collapse=urlkey&fl=original,timestamp")
        for attempt in range(3):
            try:
                r = S.get(url, timeout=100)
                if r.status_code == 200 and r.text.strip().startswith('['):
                    for orig, ts in r.json()[1:]:
                        fn = orig.split('/')[-1].split('?')[0]
                        if re.fullmatch(rf"{prefix}\d+[a-z0-9]*\.pdf", fn.lower()):
                            found.setdefault(fn.lower(), (orig, ts))
                    break
            except Exception as e:
                print(cc, host, 'attempt', attempt, type(e).__name__)
            time.sleep(3 * (attempt + 1))
    print(cc, 'enumerated', len(found))
    if found:
        json.dump(found, open(cache, 'w'))
    else:
        print(cc, 'EMPTY - not cached')

#!/usr/bin/env python3
"""DE NW+BB fresh discovery pass (CoS GO 2026-10-25 10:20 PT). Collect+stage only, no publish.
Discovery pages fetched fresh under kind disc_20261025 (law pages: cache never refetched). Uses de_sub_collect Site (UA, robots, max(CD,2s), 3-strike incl 503, mem guard)."""
import sys, re, json, time, shutil
sys.path.insert(0, '/workspace/scripts')
import de_sub_collect as D
from de_sub_collect import Site, log, RAW, PROBE, StrikeStop, k, memavail
TAG = 'disc_20261025'; B = D.B; res = {}
out = B / f'fresh_discovery_{time.strftime("%Y%m%dT%H%M%S")}.json'
def save(): json.dump(res, open(out, 'w'), indent=1)
def nw():
    s = Site('NW'); r = res['NW'] = dict(stats=s.stats)
    try:
        idx = s.get('https://recht.nrw.de/sitemap.xml', 'sitemap_index', TAG) or ''
        sms = re.findall(r'<loc>\s*([^<]+?)\s*</loc>', idx)
        pages = [u for u in sms if 'sitemap' in u] or [f'https://recht.nrw.de/sitemap/page/{i}/sitemap.xml' for i in range(1, 48)]
        urls = set(u for u in sms if 'sitemap' not in u)
        for i, p in enumerate(pages):
            t = s.get(p, 'sm_' + k(p), TAG)
            if t: urls |= set(x.strip() for x in re.findall(r'<loc>\s*([^<]+?)\s*</loc>', t))
        old = set(l.strip() for l in open(PROBE / 'nw_urls.txt'))
        lawrx = re.compile(r'https://recht\.nrw\.de/lrgv/(gesetz|rechtsverordnung)/\d{8}-')
        new = sorted(u for u in urls - old if lawrx.match(u))
        r.update(sitemaps=len(pages), sitemap_urls=len(urls), new_law_urls_discovered=len(new)); save()
        (PROBE / f'nw_urls_new_{TAG}.txt').write_text('\n'.join(new) + '\n')
        log('NW discovery sitemaps', len(pages), 'urls', len(urls), 'new law urls', len(new))
        if new:
            shutil.copy(PROBE / 'nw_urls.txt', PROBE / f'nw_urls.txt.bak_{TAG}')
            with open(PROBE / 'nw_urls.txt', 'a') as f: f.write('\n'.join(new) + '\n')
            ok0 = s.stats['ok']; D.run_nwsup(s); r['new_fetched'] = s.stats['ok'] - ok0
        r['done'] = True
    except StrikeStop: r['strike_stop'] = True; log('NW strike stop')
    save()
def bb():
    s = Site('BB'); r = res['BB'] = dict(stats=s.stats)
    try:
        ch = s.get('https://bravors.brandenburg.de/de/vorschriften_fundstellennachweis_gesetzte_und_verordnungen_chronologisch', 'chrono', TAG) or open(PROBE / 'bb_chrono.html', encoding='utf-8').read()
        years = sorted(set(re.findall(r'href="(/de/vorschriften_fundstellennachweis_gesetzte_und_verordnungen_chronologisch/year/\d+)"', ch)))
        old = json.load(open(RAW / 'BB' / 'bb_links.json')); olds = set(old); new = []
        for y in years:
            t = s.get('https://bravors.brandenburg.de' + y, 'year_' + y.rsplit('/', 1)[1], TAG)
            if t is None: continue
            for h in re.findall(r'href="(/(?:gesetze|verordnungen)/[^"#?]+)"', t):
                if h not in olds and h not in new: new.append(h)
        r.update(years=len(years), new_law_urls_discovered=len(new)); save()
        json.dump(new, open(RAW / 'BB' / f'bb_links_new_{TAG}.json', 'w'))
        log('BB discovery years', len(years), 'new', len(new))
        if new: shutil.copy(RAW / 'BB' / 'bb_links.json', RAW / 'BB' / f'bb_links.json.bak_{TAG}'); json.dump(old + new, open(RAW / 'BB' / 'bb_links.json', 'w'))
        ok0 = s.stats['ok']
        for n, h in enumerate(new, 1):
            if s.blocked: break
            s.get('https://bravors.brandenburg.de' + h, h.strip('/').replace('/', '__'), 'law')
            r['new_fetched'] = s.stats['ok'] - ok0
            if n % 10 == 0: log('BB new progress', n, len(new), s.stats, 'mem', memavail()); save()
        r['done'] = True
    except StrikeStop: r['strike_stop'] = True; log('BB strike stop')
    save()
log('START fresh discovery NW,BB pid', D.os.getpid(), 'result', out); D.markers()
nw(); bb(); log('FRESH DISCOVERY DONE', json.dumps(res)); 
sys.exit(4 if any(v.get('strike_stop') for v in res.values()) else 0)

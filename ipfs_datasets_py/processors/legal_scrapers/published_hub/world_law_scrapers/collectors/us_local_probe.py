#!/usr/bin/env python3
"""One-shot polite probe (<=10 requests): robots.txt + homepage for 5 sampled seeds; records platform hints + code links (vendor vs self-hosted). No guard loop needed (10 reqs)."""
import json, random, re, sys, time, requests
sys.path.insert(0, '/workspace/scripts')
import us_local_collect as U
class G0:
    def check(s): pass
sd = U.load_seeds(); random.seed(20261020)
pick = random.sample([s for s in sd if s['family'] == 'county' and s['seed_class'] == 'self_hosted_gov'], 2) + \
       random.sample([s for s in sd if s['family'] == 'county' and s['seed_class'] == 'unknown_selfhosted'], 1) + \
       random.sample([s for s in sd if s['family'] == 'municipal' and s['seed_class'] == 'self_hosted_gov'], 1) + \
       random.sample([s for s in sd if s['family'] == 'municipal' and s['seed_class'] == 'unknown_selfhosted'], 1)
ss = requests.Session(); ss.headers['User-Agent'] = U.UA; S = U.Sched(G0(), ss, {}); out = []
for s in pick:
    u = s['entry_url']; S.robots(u); H_ = S.host(U.host_of(u)); r, fin, dis = S.get(u, U.site_key(s['host'])) if not H_.held else ((('HELD', H_.held)), u, False)
    rec = dict(jurisdiction=s['jurisdiction'], state=s['state_code'], family=s['family'], seed_class=s['seed_class'], url=u, robots_rules=len(H_.rules or []), crawl_delay=H_.cd, robots_disallowed_home=dis)
    if isinstance(r, tuple): rec['result'] = list(map(str, r))
    else:
        h = r.text[:2_000_000] if r.status_code == 200 else ''; rec['http'] = r.status_code; r.close()
        rec['platform'] = [n for n, rx in [('civicplus', r'DocumentCenter|civicplus'), ('wordpress', r'wp-content'), ('granicus', r'granicus'), ('revize', r'revize'), ('drupal', r'Drupal'), ('joomla', r'joomla'), ('squarespace', r'squarespace'), ('wix', r'wix\.com')] if re.search(rx, h, re.I)]
        L = U.links(h, fin); rec['code_links'] = [dict(url=x, text=t, cls=U.classify_host(U.host_of(x))) for x, t in L][:12]
    out.append(rec)
json.dump(dict(at=U.now_pt(), requests=S.st['req'], stats=S.st, probes=out), open(f'{U.B}/probes/probe_20261020.json', 'w'), indent=1)
print(json.dumps(dict(requests=S.st['req'], probes=[{k: v for k, v in p.items()} for p in out]), indent=1)[:6000])

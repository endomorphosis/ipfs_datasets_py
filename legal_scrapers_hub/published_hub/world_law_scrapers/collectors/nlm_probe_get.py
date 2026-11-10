#!/usr/bin/env python3
"""Polite single-request probe helper for the KOOP repository only. >=2.2s between requests (shared ts file).
Saves body+headers under nl_municipal/probe/. Does not follow redirects (prints Location). Usage: nlm_probe_get.py URL [name]"""
import sys, os, time, json, requests, re
HOST = 'repository.officiele-overheidspublicaties.nl'
UA = 'legal-corpora-nl-municipal/1.0 (research corpus of official Dutch decentral regulations from the CC0 KOOP repository; polite; contact via huggingface.co/endomorphosis)'
TS = '/workspace/legal-corpora/nl_municipal/probe/.last_req'; P = '/workspace/legal-corpora/nl_municipal/probe'
for url in sys.argv[1:]:
    assert url.startswith(f'https://{HOST}/'), 'off-host refused'
    try: last = float(open(TS).read())
    except Exception: last = 0
    w = 2.2 - (time.time() - last)
    if w > 0: time.sleep(w)
    open(TS, 'w').write(str(time.time()))
    r = requests.get(url, headers={'User-Agent': UA}, timeout=(20, 120), allow_redirects=False)
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', url.split(HOST + '/', 1)[1])[:150] or 'root'
    open(f'{P}/{name}', 'wb').write(r.content)
    open(f'{P}/{name}.headers', 'w').write(f'GET {url}\nHTTP {r.status_code}\n' + json.dumps(dict(r.headers), indent=1))
    print(r.status_code, url, 'len', len(r.content), 'ctype', r.headers.get('content-type'), 'loc', r.headers.get('location'), '->', name, flush=True)

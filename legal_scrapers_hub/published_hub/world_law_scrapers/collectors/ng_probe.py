#!/usr/bin/env python3
"""Polite probe helper for NG gov hosts. Per-host >=2.5s; saves body+headers to probe/; robots to robots/."""
import sys, time, json, re, os, hashlib
from urllib.parse import urlparse
import requests
B='/workspace/legal-corpora/ng_expand'
UA='legal-corpora-ng-expand/1.0 (research corpus of official Nigerian federal legislation; polite; robots.txt obeyed; contact via huggingface.co/endomorphosis)'
S=requests.Session(); S.headers['User-Agent']=UA
LAST={}; BAD={}
ALLOWED=re.compile(r'(^|\.)gov\.ng$')
def get(url, save=True, stream_limit=None, **kw):
    h=urlparse(url).netloc
    assert ALLOWED.search(h.split(':')[0]), 'non-gov host refused '+h
    if BAD.get(h,0)>=3: raise SystemExit(f'host {h} stopped after 3x403/429/503')
    w=2.5-(time.time()-LAST.get(h,0))
    if w>0: time.sleep(w)
    LAST[h]=time.time()
    try: r=S.get(url, timeout=(20,90), allow_redirects=True, **kw)
    except Exception as e:
        print('ERR',url,repr(e)[:200]); return None
    if r.status_code in (403,429,503): BAD[h]=BAD.get(h,0)+1
    else: BAD[h]=0
    for x in r.history:
        assert ALLOWED.search(urlparse(x.headers.get('location','') or h).netloc.split(':')[0] or h), 'off-gov redirect'
    if not ALLOWED.search(urlparse(r.url).netloc.split(':')[0]): print('OFF-GOV final url, discarding', r.url); return None
    if save:
        fn=re.sub(r'[^A-Za-z0-9._-]+','_',url.split('://',1)[1])[:150]
        open(f'{B}/probe/{fn}','wb').write(r.content)
        open(f'{B}/probe/{fn}.headers','w').write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} GET {url}\nfinal {r.url}\nHTTP {r.status_code}\n"+''.join(f'{k}: {v}\n' for k,v in r.headers.items()))
    print(time.strftime('%H:%M:%S'), r.status_code, len(r.content), r.headers.get('content-type',''), url, '->'+r.url if r.url!=url else '')
    return r
def robots(host):
    r=get(f'https://{host}/robots.txt', save=False)
    st=None if r is None else r.status_code
    body=b'' if r is None else r.content
    open(f'{B}/robots/{host}_robots.txt','wb').write(body)
    open(f'{B}/robots/{host}_robots.txt.headers','w').write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} HTTP {st} final {getattr(r,'url',None)} ctype {getattr(r,'headers',{}).get('content-type') if r is not None else None}\n")
    return st, body

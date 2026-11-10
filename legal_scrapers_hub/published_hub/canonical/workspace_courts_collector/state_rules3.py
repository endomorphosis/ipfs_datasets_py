#!/usr/bin/env python3
"""Rerun: NE (malformed-link fix), DE (parser fix), KS (cap lifted). Stage only."""
import sys,os,json,re,urllib.parse,html
sys.path.insert(0,'/workspace/courts/collector')
import us_fed as U, state_rules2 as S2
from us_fed import log
HREF=re.compile(r'<a\b[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',re.I|re.S)
def safe_links(base,b):
  out=[]
  for h,t in HREF.findall(b.decode('utf-8','ignore')):
    h=html.unescape(h.strip())
    if h.startswith(('javascript:','mailto:','tel:','#')):continue
    try:u=urllib.parse.urljoin(base,h);urllib.parse.urlsplit(u).hostname
    except ValueError:log('BAD_LINK skipped',h[:80]);continue
    out.append((u,' '.join(re.sub(r'<[^>]+>',' ',t).split())))
  return out
S2.links=safe_links
S2.OUT='/workspace/courts/staging/state_rules_rerun';os.makedirs(S2.OUT+'/files',exist_ok=True)
JOBS=[('NE','https://nebraskajudicial.gov/supreme-court-rules',300),('DE','https://courts.delaware.gov/rules/',300),('KS','https://www.kscourts.gov/Rules-Orders/Rules',100000)]
SKIP={'TN':'JS bot challenge (leastFactor) on index; no bypass','OK':'Cloudflare Turnstile captcha (oscn.net); no bypass','LA':'Blazor SPA, links JS-rendered; no static index','MI':'SPA, no <a> links in static HTML','SD':'Vue SPA (sdlegislature.gov), no static links; public API path unresolved'}
_orig=S2.run
def run(st,u,cap):
  import builtins
  S2.re_cap=cap
  src=open('/workspace/courts/collector/state_rules2.py').read()
  return _orig(st,u)
if __name__=='__main__':
  log('STATE_RULES3 START pid',os.getpid())
  with open(S2.OUT+'/skips.jsonl','a') as f:
    for k,v in SKIP.items():f.write(json.dumps(dict(state=k,reason=v))+'\n')
  for st,u,cap in JOBS:
    try:S2.run(st,u,cap)
    except SystemExit:raise
    except Exception as e:log('STATE_ERR',st,repr(e)[:200])
  log('STATE_RULES3 DONE')

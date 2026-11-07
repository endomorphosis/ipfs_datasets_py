"""helpers for per-page rule crawlers: every page is fetched through rules_common.cached (robots-aware, 2 s/host delay, Wayback fallback) and parsed from the cache"""
import re,json,hashlib,os
from rules_common import *
from rules_build import html_text
def page(url,key):
    b,u,pol=cached(url,key)
    if b is None: return None
    meta=json.load(open(RAW+"/"+key+".meta"))
    return {"bytes":b,"url":u,"pol":pol,"fetched":meta["fetched"],"sha":hashlib.sha256(b).hexdigest(),"key":key}
def links(html,pat):
    return re.findall(pat,html if isinstance(html,str) else html.decode("utf-8","replace"))

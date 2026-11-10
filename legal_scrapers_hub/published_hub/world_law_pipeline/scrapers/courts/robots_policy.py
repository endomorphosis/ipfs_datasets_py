"""RFC 9309-style robots check. 4xx robots.txt => allow (robots_absent); 5xx/unreachable => 'robots_unreachable'.
IGNORE_ROBOTS (env, default "1", per owner Benjamin Barber 2026-11-01): a disallow is returned as
'robots_disallowed_ignored_per_owner' so callers proceed; set IGNORE_ROBOTS=0 to restore 'robots_disallowed' (skip).
Crawl delay: use crawl_delay(url) -> site Crawl-delay or 10 s. AI-training opt-out hosts are always refused."""
import os,time,urllib.request,urllib.robotparser,urllib.parse
UA="Mozilla/5.0 (compatible; world_courts-research/0.1)"
IGNORE_ROBOTS=os.environ.get("IGNORE_ROBOTS","1")!="0"
OPTOUT=("tanzlii.org","ulii.org","justice.lk","assemblee-nationale.mg")
_c={};_last={}
def _base(url):
    p=urllib.parse.urlsplit(url);return f"{p.scheme}://{p.netloc}",p.netloc.lower()
def optout(url):
    h=_base(url)[1];return any(h==d or h.endswith("."+d) for d in OPTOUT)
def _load(url):
    base,_=_base(url)
    if base not in _c:
        try:
            r=urllib.request.urlopen(urllib.request.Request(base+"/robots.txt",headers={"User-Agent":UA}),timeout=20)
            rp=urllib.robotparser.RobotFileParser();rp.parse(r.read().decode("utf-8","replace").splitlines());_c[base]=("ok",rp)
        except urllib.error.HTTPError as e:
            _c[base]=("absent",None) if 400<=e.code<500 else ("unreachable",None)
        except Exception: _c[base]=("unreachable",None)
    return _c[base]
def crawl_delay(url,minimum=None):
    st,rp=_load(url);cd=None
    if rp is not None:
        try: cd=rp.crawl_delay(UA)
        except Exception: cd=None
    d=float(cd) if cd else 10.0
    return max(d,minimum or 0)
def wait(url):
    """sleep so per-host spacing >= crawl_delay(url)."""
    h=_base(url)[1];d=crawl_delay(url);t=time.time()-_last.get(h,0)
    if t<d: time.sleep(d-t)
    _last[h]=time.time()
def policy(url):
    if optout(url): return "robots_disallowed"  # ai-train opt-out: always skip
    st,rp=_load(url)
    if st=="absent": return "robots_absent_allowed"
    if st=="unreachable": return "robots_unreachable"
    if rp.can_fetch(UA,url): return "robots_allowed"
    return "robots_disallowed_ignored_per_owner" if IGNORE_ROBOTS else "robots_disallowed"

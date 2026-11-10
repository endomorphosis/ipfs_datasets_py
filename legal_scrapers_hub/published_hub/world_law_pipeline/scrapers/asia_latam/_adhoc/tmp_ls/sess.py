import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, re, time, requests
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/asia_latam'))
from common.rfc9309 import Robots
UA="JusticeDAO-WorldLaw/1.0 (+https://github.com/endomorphosis/ipfs_datasets_py; municipal law research crawler; polite)"
def vs(html):
    m=re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]*)"',html) or re.search(r'value="([^"]*)"[^>]*name="javax\.faces\.ViewState"',html)
    return m.group(1) if m else None
class Sess:
    def __init__(self, host):
        self.host=host; self.s=requests.Session(); self.s.headers['User-Agent']=UA; self.t=0
        self.base=f"https://{host}/HAS-Shohin/page/"
    def _wait(self):
        d=time.time()-self.t
        if d<1.05: time.sleep(1.05-d)
        self.t=time.time()
    def get(self,u):
        self._wait(); return self.s.get(u,timeout=60)
    def post(self,u,data):
        self._wait(); return self.s.post(u,data=data,timeout=60)
    def start(self):
        r=self.get(self.base+"SJSrbLogin.jsf"); v=vs(r.text)
        r2=self.post(self.base+"SJSrbLogin.jsf",{"frm01_SUBMIT":"1","javax.faces.ViewState":v,"frm01:_idcl":"yougo","frm01_link_hidden_":"yougo"})
        return r2
P_LIST="SJReikiList.jsf"
def taikei_session(host):
    s=Sess(host); r=s.start(); v=vs(r.text)
    A=re.search(r"'containerId':'([^']+)'",r.text).group(1)
    r2=s.post(s.base+P_LIST,{"AJAXREQUEST":A,"form-tab_SUBMIT":"1","appl-id":"SJ0010","javax.faces.ViewState":v,"struct":"struct"})
    s.A=A; s.v=vs(r2.text) or v
    return s, r2.text
def honmon(s, outputid, maxpages=200):
    U=f"https://{s.host}/HAS-Shohin/action/get-honmon-info"
    out=[]; page=1; npages=1
    while page<=npages and page<=maxpages:
        base={"executeId":"1","async":"true","perPage":"100","id":"honmon","matchstyle":"","quoteFunction":"quoteFunction","currentPage":str(page),"pagingType":"1","outputid":outputid,"wait-time":"0"}
        first=True; chunks=[]
        for _ in range(60):
            d=dict(base); 
            if first: d["reset"]="true"
            s._wait(); r=s.s.post(U,data=d,timeout=60,allow_redirects=False); first=False
            if r.status_code!=200: raise IOError(f'honmon HTTP {r.status_code} {r.headers.get("location")}')
            chunks.append(r.text)
            if '<span id="eod"' in r.text: break
        h="".join(chunks)
        m=re.search(r'id="page-count"[^>]*value="(\d+)"',h); npages=int(m.group(1)) if m else npages
        out.append(h); page+=1
    return out, npages

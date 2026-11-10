"""Discover candidate roster pages (2-level link crawl from judiciary home). Output for hand review."""
import re,json,sys,time,html,urllib.request,urllib.parse
sys.path.insert(0,"..");sys.path.insert(0,".")
from us_state_judiciaries import STATES
from robots_policy import policy,UA
def get(u):
    try: return urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=20).read(2_000_000).decode("utf-8","replace")
    except Exception: return ""
def links(h,base):
    for u,t in re.findall(r'href="([^"#]+)"[^>]*>(.*?)</a>',h,re.S|re.I):
        t=html.unescape(re.sub(r'<[^>]+>',' ',t)).strip()
        try: yield urllib.parse.urljoin(base,html.unescape(u)),t
        except ValueError: pass
L1=re.compile(r'supreme|appeal|appellate|commonwealth court|superior court|about the court|our courts|courts',re.I)
R=re.compile(r'justices|judges|meet the|biograph|members of the court',re.I)
out={}
for st,(home,_) in STATES.items():
    if len(sys.argv)>1 and st not in sys.argv[1:]: continue
    h=get(home);dom=urllib.parse.urlsplit(home).netloc.split(".")[-2];c={}
    l1=[(u,t) for u,t in links(h,home) if dom in urllib.parse.urlsplit(u).netloc]
    for u,t in l1:
        if R.search(t+" "+u): c[u]=t
    for u,t in [x for x in l1 if L1.search(x[1])][:12]:
        if policy(u)=="robots_disallowed": continue
        time.sleep(1)
        for u2,t2 in links(get(u),u):
            if dom in urllib.parse.urlsplit(u2).netloc and R.search(t2+" "+u2) and not re.search(r'\.(pdf|docx?)$|news|press|retired|former|history|vacanc|nominat|application|election|evaluation',u2+t2,re.I): c[u2]=t2
    out[st]=c;print(st,len(c),file=sys.stderr)
    json.dump(out,open("/workspace/world_courts/data/us/roster_candidates.json","w"),indent=0)

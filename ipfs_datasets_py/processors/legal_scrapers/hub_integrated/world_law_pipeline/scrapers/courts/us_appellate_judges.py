"""Public roster of state supreme & intermediate appellate judges from official judiciary sites.
Discovers roster pages from the judiciary home page (link text: justices/judges of supreme/appeals), extracts
'Chief Justice X', 'Justice X', 'Judge X', 'Presiding Judge X' names. Official titles only; no personal data."""
import re,json,sys,time,datetime,urllib.request,urllib.parse,html
from us_state_judiciaries import STATES
from robots_policy import policy,UA
LINK=re.compile(r'href="([^"#]+)"[^>]*>(.*?)</a>',re.S|re.I)
KEY=re.compile(r'(justices|meet the (court|justices|judges)|supreme court|court of appeals?|appellate court|commonwealth court|superior court judges|court of criminal appeals)',re.I)
NAME=re.compile(r"\b(Chief Justice|Associate Justice|Justice|Presiding Judge|Chief Judge|Judge)\s+((?:[A-Z][a-zA-Z.'\-]+|[A-Z]\.)(?:\s+(?:[A-Z][a-zA-Z.'\-]+|[A-Z]\.|de|van|von|Mc[A-Z]\w+)){1,3}(?:,?\s+(?:Jr|Sr|II|III|IV)\.?)?)")
STOP={"Court","Courts","Supreme","Appeals","Building","Center","Award","Nominating","Commission","Program","Fellowship","Conference","District","Circuit","County","Retirement","Swearing","Office","Opinion","Opinions","Library","Biography","Investiture","Room","Council","Portrait"}
def get(u):
    r=urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=25)
    return r.read(3_000_000).decode("utf-8","replace")
def text(h): return html.unescape(re.sub(r'<[^>]+>',' ',re.sub(r'(?is)<(script|style).*?</\1>',' ',h)))
def run(out,states=None):
    f=open(out,"w");summ={}
    for st,(home,_) in STATES.items():
        if states and st not in states: continue
        now=datetime.datetime.utcnow().isoformat()+"Z";seen={};pages=[]
        try: h=get(home)
        except Exception as e: summ[st]=f"home_err {e}"[:80];continue
        cands=[]
        for u,t in LINK.findall(h):
            t=text(t).strip()
            if KEY.search(t) or re.search(r'justices|/judges|meet-the',u,re.I): cands.append(urllib.parse.urljoin(home,html.unescape(u)))
        cands=list(dict.fromkeys(c for c in cands if urllib.parse.urlsplit(c).netloc.endswith(urllib.parse.urlsplit(home).netloc.split('.',1)[-1])))[:6]
        for u in [home]+cands:
            pol=policy(u)
            if pol=="robots_disallowed": continue
            try: h2=h if u==home else get(u);time.sleep(2)
            except Exception: continue
            for title,name in NAME.findall(text(h2)):
                name=re.sub(r'\s+',' ',name).strip(" ,")
                if set(name.split())&STOP or len(name)<5: continue
                k=name.lower()
                if k not in seen:
                    court="supreme" if "Justice" in title else "appellate_or_other"
                    seen[k]={"judge_id":f"US-{st}:{re.sub(r'[^a-z]+','-',k)}","name":name,"title":title,"court_level_guess":court,"court_id":None,"subdivision":f"US-{st}","source_url":u,"site_policy":pol,"retrieved_at":now,"extraction":"regex_title_name","needs_review":True}
        for v in seen.values(): f.write(json.dumps(v)+"\n")
        f.flush();summ[st]=len(seen);print(st,len(seen),file=sys.stderr)
    print(json.dumps(summ))
if __name__=="__main__": run(sys.argv[1],sys.argv[2:] or None)

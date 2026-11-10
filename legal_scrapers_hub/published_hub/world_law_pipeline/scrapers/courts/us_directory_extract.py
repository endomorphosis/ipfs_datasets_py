"""Generic courthouse extractor for state court directory pages.
Fetches each state's directory page + up to N same-host child pages (county/court/location links),
extracts US street addresses ("... City, ST 12345") with the nearest preceding court-ish heading as name.
Uses Wayback (web.archive.org id_ snapshots) when live is 403/blocked or robots disallows."""
import re,json,sys,time,datetime,html,urllib.request,urllib.parse
from us_state_judiciaries import STATES
from robots_policy import policy,UA
MAXCHILD=int(__import__("os").environ.get("MAXCHILD","60"))
ADDR=re.compile(r"(\d{1,6}[A-Za-z]?\s+[A-Z0-9][\w .'#,-]{2,60}?)\s*(?:,|\n)\s*(?:(?:Suite|Ste\.?|Room|Rm\.?|Floor)[^\n,]{0,20}\s*,?\s*)?([A-Z][A-Za-z .'-]{1,30}),?\s+([A-Z]{2}|[A-Z][a-z]+)\s+(\d{5})(?:-\d{4})?")
COURTNAME=re.compile(r"[^\n]{0,80}(Court|Courthouse|Justice Center|Judicial Center|Clerk|Magistrate|Probate|Tribunal)[^\n]{0,60}")
def fetch(u):
    return urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=30).read(4_000_000).decode("utf-8","replace")
def wayback(u):
    try:
        j=json.load(urllib.request.urlopen("https://archive.org/wayback/available?url="+urllib.parse.quote(u,safe=""),timeout=30))
        s=j["archived_snapshots"]["closest"];ts=s["timestamp"]
        return fetch(f"https://web.archive.org/web/{ts}id_/{u}"),f"https://web.archive.org/web/{ts}/{u}"
    except Exception: return None,None
def get(u):
    try: return _get(u)
    except Exception: return None,None,'error'
def _get(u):
    pol=policy(u)
    if pol!="robots_disallowed":
        try: return fetch(u),u,pol
        except Exception: pass
    h,src=wayback(u);time.sleep(2)
    return h,src,(pol if pol=="robots_disallowed" else pol+"+live_blocked")+"|archive_wayback" if h else (None,None,pol)
def sj(b,x):
    try: return urllib.parse.urljoin(b,x)
    except ValueError: return ''
def totext(h):
    h=re.sub(r'(?is)<(script|style|noscript).*?</\1>',' ',h);h=re.sub(r'(?i)<br\s*/?>|</(p|div|li|h\d|tr|td|address)>','\n',h)
    t=html.unescape(re.sub(r'<[^>]+>',' ',h));return re.sub(r'[ \t\xa0]+',' ',re.sub(r'\n\s*\n+','\n',t))
def extract(t,st):
    out=[];lines=t.split("\n")
    for m in ADDR.finditer(t):
        if m.group(3) not in (st,) and len(m.group(3))!=2 and not m.group(3).lower().startswith(STNAME[st].lower()[:4]): continue
        before=t[max(0,m.start()-400):m.start()];names=COURTNAME.findall(before)
        nm=[x for x in re.findall(r"[^\n]{0,80}(?:Court|Courthouse|Justice Center|Judicial Center|Clerk|Magistrate|Probate)[^\n]{0,60}",before)]
        out.append({"name":(nm[-1].strip() if nm else None),"street":m.group(1).strip(" ,"),"city":m.group(2).strip(),"state":st,"postcode":m.group(4)})
    return out
STNAME={}
def run(out,states=None):
    f=open(out,"w");summ={}
    src=[json.loads(l) for l in open("/workspace/world_courts/data/us/us_state_judiciaries.jsonl")]
    names={"AL":"Alabama"}
    for r in src:
        st=r["subdivision"][3:]
        if states and st not in states: continue
        STNAME[st]=st
        global ADDR
        now=datetime.datetime.utcnow().isoformat()+"Z";recs={};d=r["directory_url"]
        h,u,pol=get(d)
        if not h: summ[st]="unfetched";print(st,"unfetched",file=sys.stderr);continue
        pages=[(h,u,pol)];host=urllib.parse.urlsplit(d).netloc
        kids=[sj(d,html.unescape(x)) for x,t in re.findall(r'href="([^"#]+)"[^>]*>(.*?)</a>',h,re.S) if re.search(r'count|court|locat|district|circuit|parish|director',x+t,re.I)]
        kids=[k for k in dict.fromkeys(kids) if urllib.parse.urlsplit(k).netloc==host and not re.search(r'\.(pdf|docx?|xlsx?|jpg|png)$',k,re.I)][:MAXCHILD]
        for k in kids:
            time.sleep(2);hh,uu,pp=get(k)
            if hh: pages.append((hh,uu,pp))
        for hh,uu,pp in pages:
            for a in extract(totext(hh),st):
                key=(a["street"].lower(),a["postcode"])
                if key in recs: continue
                recs[key]={"court_id":None,"name":a["name"],"level":None,"court_system":"state","country_code":"US","subdivision":f"US-{st}","jurisdiction":None,"parent_court_id":None,
                  "address":{"street":a["street"],"city":a["city"],"postcode":a["postcode"],"region":st,"country":"US"},"geo":None,"place_ids":[],
                  "source_url":uu,"source_kind":"official" if "web.archive.org" not in uu else "archive","site_policy":pp,"retrieved_at":now}
        for v in recs.values(): f.write(json.dumps(v)+"\n")
        f.flush();summ[st]=len(recs);print(st,len(pages),len(recs),file=sys.stderr)
    print(json.dumps(summ))
if __name__=="__main__": run(sys.argv[1],sys.argv[2:] or None)

"""Parse the hand-entered roster pages (rosters/us_roster_pages.json). Per-state mode:
 - title_name (default): 'Chief Justice|Justice|Judge|Presiding Judge X Y' within main text; plus judge-profile links whose anchor text is a name
 - caps_name_title: 'NAME NAME, Chief Justice|Justice' (e.g. GA)
Live fetch first; Wayback snapshot if 403/robots-disallowed. Writes data/us/us_judges.jsonl."""
import re,os,sys,json,time,html,datetime,urllib.request,urllib.parse
HERE=os.path.dirname(os.path.abspath(__file__));sys.path.insert(0,os.path.dirname(HERE))
from robots_policy import policy,UA
CFG=json.load(open(HERE+"/us_roster_pages.json"))
TITLE=r"(Chief Justice|Associate Justice|Presiding Justice|Justice|Chief Judge|Presiding Judge|Judge)"
NM=r"((?:[A-Z][a-zA-Z'\u00C0-\u017F\-]+|[A-Z]\.)(?:\s+(?:[A-Z][a-zA-Z'\u00C0-\u017F\-]+|[A-Z]\.|[A-Z]\.[A-Z]\.|de|van|von)){1,3}(?:,?\s+(?:Jr|Sr|II|III|IV)\.?)?)"
STOP=set("Place Justice Judge Chief Associate Presiding Calendar Docket Webcast Grant Administration Court Courts Supreme Appeals Building Center Award Commission Program District Circuit County Office Opinion Opinions Library Biography Bio Read More View Profile Click Learn Position Name Open Back Chambers The And Of Home Staff Directory Retired Senior Former Emeritus Elected Appointed Term Seat Division Section Panel Contact Email Phone Initiatives Directives Self Service Access Orders Rules State Judicial Conduct Selection Vacancy News".split())
def fetch(u):
    return urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=30).read(3_000_000).decode("utf-8","replace")
def get(u):
    pol=policy(u)
    if pol!="robots_disallowed":
        try: return fetch(u),u,pol
        except Exception: pass
    try:
        s=json.load(urllib.request.urlopen("https://archive.org/wayback/available?url="+urllib.parse.quote(u,safe=""),timeout=30))["archived_snapshots"]["closest"]
        return fetch(f"https://web.archive.org/web/{s['timestamp']}id_/{u}"),f"https://web.archive.org/web/{s['timestamp']}/{u}",pol+"|archive_wayback"
    except Exception: return None,None,pol
def main_text(h,whole=False):
    h=re.sub(r'(?is)<(script|style|nav|header|footer|noscript)\b.*?</\1>',' ',h)
    m=None if whole else re.search(r'(?is)<main\b.*?</main>',h);h=m.group(0) if m else h
    h=re.sub(r'(?i)<br\s*/?>|</(p|div|li|h\d|tr|td|a|span|strong)>','\n',h)
    return re.sub(r'[ \t\xa0]+',' ',html.unescape(re.sub(r'<[^>]+>',' ',h)))
def clean(n):
    t=n.split()
    while t and t[-1].strip(".,") in STOP: t.pop()
    return " ".join(t) if len(t)>=2 and not set(x.strip(".,") for x in t)&STOP else None
def parse(h,mode,base=None):
    t=main_text(h,mode=='whole');out=[]
    if base:
        bp=urllib.parse.urlsplit(base).path.rstrip('/').rsplit('/',1)[0]
        for u,a in re.findall(r'href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',h,re.S|re.I):
            a=re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',a))).strip()
            try: p=urllib.parse.urlsplit(urllib.parse.urljoin(base,u)).path
            except ValueError: continue
            if p.startswith(bp) and len(p)>len(bp)+3 and re.fullmatch(r"(?:(Chief Justice|Associate Justice|Presiding Justice|Justice|Chief Judge|Presiding Judge|Judge)\s+)?"+NM,a):
                m=re.fullmatch(r"(?:(Chief Justice|Associate Justice|Presiding Justice|Justice|Chief Judge|Presiding Judge|Judge)\s+)?(.*)",a);nm2=m.group(2)
                if m.group(1) or nm2.split()[-1].lower().strip(".,") in p.lower(): out.append((m.group(1) or "",nm2))
    if mode=="caps_name_title":
        for n,ti in re.findall(r"([A-Z][A-Z.'\- ]{4,40}),\s*(Chief Justice|Presiding Justice|Justice)",t):
            out.append((ti," ".join(w.capitalize() if len(w)>2 else w for w in n.split())))
    for ti,n in re.findall(TITLE+r"\s+"+NM,t):
        out.append((ti,n))
    if not out and mode!='whole':
        return parse(h,'whole',base)
    res={}
    for ti,n in out:
        n=clean(re.sub(r'\s+',' ',n).strip(" ,"))
        if n: res.setdefault(n.lower(),(ti,n))
    return list(res.values())
def run(out,states=None):
    now=datetime.datetime.now(datetime.UTC).isoformat();rows=[];summ={}
    for st,c in CFG.items():
        if states and st not in states: continue
        n0=len(rows)
        if not c["pages"]: summ[st]="no_roster_page";continue
        for court,u in c["pages"]:
            h,src,pol=get(u);time.sleep(2)
            if not h: summ[st]=f"unfetched:{pol}";continue
            for ti,n in parse(h,c.get("mode","title_name"),u):
                lvl="supreme" if court=="supreme" else ("appellate" if court=="appellate" else court)
                rows.append({"judge_id":f"US-{st}:{lvl}:{re.sub(r'[^a-z]+','-',n.lower()).strip('-')}","name":n,"title":ti,"court_level":lvl,
                  "court_id":f"US-{st}-{lvl}","subdivision":f"US-{st}","roster_url":u,"source_url":src,"site_policy":pol,
                  "retrieved_at":now,"extraction":"roster_parser:"+c.get("mode","title_name"),"needs_review":True})
        summ.setdefault(st,len(rows)-n0)
    seen={};ded=[]
    for r in rows:
        k=(r["subdivision"],r["court_level"],r["name"].split()[-1].lower(),r["name"].split()[0].lower())
        if k in seen:
            o=seen[k]
            if not o["title"] and r["title"]: o["title"]=r["title"]
            continue
        seen[k]=r;ded.append(r)
    with open(out,"w") as f:
        for r in ded: f.write(json.dumps(r,ensure_ascii=False)+"\n")
    print(json.dumps(summ));print("total",len(ded))
if __name__=="__main__": run(sys.argv[1],sys.argv[2:] or None)

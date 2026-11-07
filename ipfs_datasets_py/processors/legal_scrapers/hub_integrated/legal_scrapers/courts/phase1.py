import csv,json,os,re,time,asyncio,datetime,urllib.parse as up,urllib.robotparser as rp,subprocess,hashlib
import requests,certifi
from bs4 import BeautifulSoup
from ipfs_datasets_py.web_archiving.wayback_machine_engine import get_wayback_content
UA="endomorphosis-world-laws-courts/0.1 (+https://github.com/endomorphosis; polite research bot)"
OUT="data/phase1"; LOG=f"{OUT}/progress.log"; ST=f"{OUT}/progress.json"
SKIP=("canlii.org","austlii.edu.au","law.cornell.edu","ecourts.gov.in")
KW={"judge":r"judge|justice|judiciary|bench|bio|members|magistrat|juges|richter|jueces|ministros","form":r"\bforms?\b|formul|formular","rule":r"rules?|procedure|practice.?direction|reglement|verfahrens|reglamento","court":r"locat|contact|address|court.?finder|directory|find.?a.?court|courthouse|visit"}
S=requests.Session();S.headers["User-Agent"]=UA;S.verify=certifi.where()
last=[0.0]
def log(m):
  open(LOG,"a").write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {m}\n");print(m,flush=True)
def res():
  ma=int(open("/proc/meminfo").read().split("MemAvailable:")[1].split()[0])/1048576
  st=os.statvfs("/workspace");df=st.f_bavail*st.f_frsize/2**30;return ma,df
def gate():
  ma,df=res()
  if ma<4.5 or df<23: log(f"STOP resource gate MemAvail={ma:.1f}Gi free={df:.1f}G");raise SystemExit(3)
def wait():
  d=time.time()-last[0]
  if d<2.2: time.sleep(2.2-d)
  last[0]=time.time()
def fetch(url,mode):
  wait()
  if mode=="wayback":
    r=asyncio.run(get_wayback_content(url))
    if r.get("status")!="success": return None,None
    c=r["content"]; c=c.decode("utf-8","replace") if isinstance(c,bytes) else c
    return c,r.get("wayback_url")
  r=S.get(url,timeout=25)
  if r.status_code!=200 or "html" not in r.headers.get("content-type",""): return None,None
  return r.text,url
def classify(t):
  return [k for k,p in KW.items() if re.search(p,t,re.I)]
def main():
  os.makedirs(OUT,exist_ok=True)
  rb=json.load(open("robots_results.json"))["results"]
  done=json.load(open(ST)) if os.path.exists(ST) else {}
  rows=[r for r in csv.DictReader(open("sources.csv")) if r["level"] in("federal","national") or r["jurisdiction"].startswith("IN-")]
  log(f"START {len(rows)} national sources; {len(done)} already done; res={res()}")
  for r in rows:
    url=r["url"];h=up.urlsplit(url);base=f"{h.scheme}://{h.netloc}";key=r["source_name"]
    if key in done: continue
    gate()
    if any(s in h.netloc for s in SKIP): done[key]={"status":"skipped (policy skip list)"};json.dump(done,open(ST,"w"),indent=1);log(f"SKIP {key}");continue
    rs=rb.get(base,"")
    mode="wayback" if ("403" in rs or "non-robots" in rs) else "live"
    robots=None
    if mode=="live":
      robots=rp.RobotFileParser();
      try:
        wait();t=S.get(base+"/robots.txt",timeout=20);robots.parse(t.text.splitlines() if t.status_code==200 else [])
      except requests.exceptions.SSLError: mode="wayback";log(f"TLS fail w/ certifi {base} -> wayback")
      except Exception as e: mode="wayback";log(f"robots err {base} {type(e).__name__} -> wayback")
    fn=f"{OUT}/{re.sub(r'[^A-Za-z0-9]+','_',key)[:80]}.jsonl";cnt={};f=open(fn,"a")
    today=datetime.date.today().isoformat();seen=set()
    def emit(rec):
      k=hashlib.sha1(json.dumps(rec,sort_keys=True).encode()).hexdigest()
      if k in seen: return
      seen.add(k);rec.update(jurisdiction=r["jurisdiction"],source_name=key,retrieval_date=today,retrieval_mode=mode,license="see TERMS.md");f.write(json.dumps(rec,ensure_ascii=False)+"\n");cnt[rec["type"]]=cnt.get(rec["type"],0)+1
    queue=[url];pages=0;errs=[]
    while queue and pages<10:
      u=queue.pop(0)
      if mode=="live" and robots and not robots.can_fetch(UA,u): errs.append("robots-disallow "+u);continue
      try: html,src=fetch(u,mode)
      except requests.exceptions.SSLError as e: errs.append("TLS");
      except Exception as e: errs.append(type(e).__name__);html=None
      else: pass
      if not locals().get("html"): continue
      pages+=1;soup=BeautifulSoup(html,"lxml");ptype=classify(u+" "+(soup.title.string if soup.title and soup.title.string else ""))
      for a in soup.find_all("a",href=True):
        txt=" ".join(a.get_text(" ").split())[:200];href=up.urljoin(u,a["href"])
        if href.startswith("https://web.archive.org/web/"): href=re.sub(r"^https://web\.archive\.org/web/\d+[a-z_]*/","",href)
        hu=up.urlsplit(href)
        if hu.scheme not in("http","https"): continue
        c=classify(txt+" "+hu.path)
        isdoc=re.search(r"\.(pdf|docx?|rtf|odt)$",hu.path,re.I)
        if "form" in c and (isdoc or "form" in txt.lower()): emit({"type":"form","title":txt,"file_url":href,"file_format":(isdoc.group(1).lower() if isdoc else "html"),"found_on":src})
        elif "rule" in c and len(txt)>3: emit({"type":"rule","title":txt,"url":href,"found_on":src})
        if hu.netloc==h.netloc and c and pages+len(queue)<10 and href not in queue and href!=u and not isdoc: queue.append(href)
      text=soup.get_text("\n")
      if "judge" in ptype or "judge" in classify(u):
        for line in text.split("\n"):
          l=" ".join(line.split())
          if 6<len(l)<90 and re.match(r"^(The\s+)?(Hon'?ble|Honourable|Hon\.|Chief Justice|Justice|Judge|Mr\.? Justice|Mrs\.? Justice|Ms\.? Justice|Lord|Lady|Dame|Sir)\b",l): emit({"type":"judge","full_name":l,"roster_url":src})
      for ad in soup.find_all("address"): emit({"type":"court","name":r["source_name"],"address":" ".join(ad.get_text(" ").split())[:300],"found_on":src})
      if "court" in ptype:
        for line in text.split("\n"):
          l=" ".join(line.split())
          if 12<len(l)<160 and re.search(r"\d",l) and re.search(r"\b(street|st\.|road|rd\.|avenue|ave|marg|lane|place|square|building|house|strasse|straße|rue|calle|via|plein|PO Box|\b[A-Z]{1,2}\d{1,2} ?\d[A-Z]{2}\b|\b\d{5,6}\b)",l,re.I): emit({"type":"court","name":r["source_name"],"address":l,"found_on":src})
      ma,df=res()
      if ma<4.5 or df<23: f.close();log(f"STOP mid-source {key} MemAvail={ma:.1f} free={df:.1f}");raise SystemExit(3)
    f.close();done[key]={"status":"ok" if pages else "failed","mode":mode,"pages":pages,"counts":cnt,"errors":errs[:5],"file":fn}
    json.dump(done,open(ST,"w"),indent=1);ma,df=res();log(f"DONE {key} mode={mode} pages={pages} {cnt} errs={len(errs)} mem={ma:.1f}Gi disk={df:.1f}G")
  log("FINISHED")
main()

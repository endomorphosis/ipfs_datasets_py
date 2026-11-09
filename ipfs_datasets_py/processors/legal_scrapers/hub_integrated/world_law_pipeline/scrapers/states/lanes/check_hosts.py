import csv,re,time,json,sys,requests,urllib.parse as up
from datetime import datetime,timezone
UA="Mozilla/5.0 (compatible; world-laws-research/0.1; polite robots/terms check)"
rows=list(csv.DictReader(open("sources.csv")))
hosts=[]
for r in rows:
  for h in re.findall(r"(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})",r["official_source_urls"]):
    if h not in hosts: hosts.append(h)
out="checks/results.jsonl"
done=set()
try: done={json.loads(l)["host"] for l in open(out)}
except FileNotFoundError: pass
s=requests.Session(); s.headers["User-Agent"]=UA
last=[0]
def get(u):
  w=2.2-(time.time()-last[0])
  if w>0: time.sleep(w)
  try:
    r=s.get(u,timeout=25,allow_redirects=True); return r
  except Exception as e: return e
  finally: last[0]=time.time()
def chal(r): 
  t=r.text[:5000].lower() if hasattr(r,"text") else ""
  return r.status_code in (403,429,503) and ("cloudflare" in t or "captcha" in t or "cf-chl" in t or "challenge" in t) or "captcha" in t[:3000]
KW=re.compile(r"(terms[ -_]?of[ -_]?(use|service)|terms|copyright|disclaimer|legal[ -_]?notice|conditions|policies|privacy)",re.I)
for h in hosts:
  if h in done: continue
  rec={"host":h,"checked_at":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
  r=get(f"https://{h}/robots.txt")
  if isinstance(r,Exception): rec["robots"]="error: "+str(r)[:150]
  else:
    rec["robots_http"]=r.status_code; rec["robots_final"]=r.url
    if chal(r): rec["robots"]="challenge"
    elif r.status_code==200 and "<html" not in r.text[:500].lower(): rec["robots_txt"]=r.text[:4000]; rec["robots"]="present"
    else: rec["robots"]=f"none({r.status_code})"
  if rec["robots"]!="challenge":
    r=get(f"https://{h}/")
    if isinstance(r,Exception): rec["home"]="error: "+str(r)[:150]
    elif chal(r): rec["home"]="challenge"
    else:
      rec["home"]=r.status_code; rec["home_final"]=r.url
      links=re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>',r.text,re.S|re.I)
      cands=[(up.urljoin(r.url,u),re.sub("<[^>]+>","",t).strip()) for u,t in links if KW.search(u) or KW.search(re.sub("<[^>]+>","",t))]
      pri=[c for c in cands if re.search("terms|copyright|disclaimer|legal|conditions",c[0]+c[1],re.I)] or cands
      if pri:
        tu=pri[0][0]; rec["terms_url"]=tu
        t=get(tu)
        if not isinstance(t,Exception) and not chal(t):
          txt=re.sub(r"\s+"," ",re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>"," ",t.text,flags=re.S|re.I))
          sents=re.findall(r"[^.]{0,250}(?:copyright|reproduc|automated|robot|scrap|crawl|commercial|permission|license|licence|public domain|prohibit|may not|bulk|creative commons)[^.]{0,250}\.",txt,re.I)
          rec["terms_snips"]=sents[:8]
        elif not isinstance(t,Exception): rec["terms_url_status"]="challenge"
  open(out,"a").write(json.dumps(rec)+"\n"); print(h,rec.get("robots"),rec.get("home"),rec.get("terms_url"),flush=True)
print("DONE")

import csv,time,urllib.request,urllib.parse,json,datetime
rows=list(csv.DictReader(open("sources.csv")));out={}
for r in rows:
  h=urllib.parse.urlsplit(r["url"]); base=f"{h.scheme}://{h.netloc}"
  if base in out: continue
  try:
    req=urllib.request.Request(base+"/robots.txt",headers={"User-Agent":"endomorphosis-world-laws-research/0.1 (phase0 robots check)"})
    with urllib.request.urlopen(req,timeout=15) as x: b=x.read(20000).decode("utf-8","replace"); st=x.status
    low=b.lower()
    if "cloudflare" in low or "captcha" in low or "<html" in low[:200]: s="non-robots response (possible WAF/HTML)"
    else:
      lines=[l.strip().lower() for l in b.splitlines()]; ua=None;dis=False
      for l in lines:
        if l.startswith("user-agent:"): ua=l.split(":",1)[1].strip()
        elif ua=="*" and l.replace(" ","")=="disallow:/": dis=True
      s="200; Disallow: / for *" if dis else "200; allows * (path limits may apply)"
      cd=[l for l in lines if l.startswith("crawl-delay")]
      if cd: s+="; "+cd[0]
  except urllib.error.HTTPError as e: s=f"HTTP {e.code}"+(" (blocked/WAF)" if e.code in (403,429,503) else " (no robots.txt)" if e.code==404 else "")
  except Exception as e: s="error: "+type(e).__name__+" "+str(e)[:60]
  out[base]=s; print(base,s,flush=True); time.sleep(2.5)
json.dump({"checked":datetime.date.today().isoformat(),"results":out},open("robots_results.json","w"),indent=1)

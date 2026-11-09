import csv,json,re,urllib.robotparser as rp
UA="world-laws-research"
R={}
for l in open("checks/results.jsonl"):
  r=json.loads(l); R[r["host"]]=r
FIX={"www.legis.state.pa.us":"www.palegis.us","leg.mt.gov":"www.legmt.gov","cnmilaw.org":"cnmilaw.gov","new.asbar.org":"asbar.org"}
OVR={ # manual terms summaries (from fetched pages + known terms)
"AR":"Code hosted by LexisNexis; Lexis ToS prohibits automated/bulk access. (arkleg robots: allowed for *, disallow / only for named bots).",
"GA":"O.C.G.A. official site via LexisNexis (Lexis ToS restrictive); PRO v. Georgia (2020): annotated code not copyrightable.",
"MS":"Code via LexisNexis (ToS restrictive); legislature.ms.gov TLS chain fails verification.",
"TN":"Code via LexisNexis (ToS restrictive); tn.gov returns 403 to scripted clients.",
"UT":"Disclaimer: no use for commercial purposes/commercial gain without permission; crawl-delay 10.",
"MA":"Terms & Conditions: photo/video reuse requires consent; text of laws not restricted.",
"IA":"Disclaimer page; Iowa Code copyright claimed by State of Iowa (check before redistribution).",
"NM":"NMOneSource (NM Compilation Commission) claims copyright – RESTRICTED (robots: / disallowed only for named bots).",
"VI":"Only via Justia/Lexis; Justia Cloudflare challenge on robots; official code is Lexis-licensed – RESTRICTED.",
"QLD":"CC BY 4.0 (copyright page).","NT":"Copyright owned by NT; Terms of Use page (reproduction policy applies).",
"ON":"Ontario terms of use; e-Laws reproducible with attribution (Crown copyright).",
"AB":"Alberta King's Printer: copyright; reproduction permission rules; robots disallows /.",
"NB":"King's Printer disclaimer & copyright notice applies.","NL":"Copyright statement: reproductions should acknowledge source.",
"BC":"BC Laws: robots disallows / for crawlers; use CiviX API (King's Printer licence).",
"OH":"Disclaimer only; no reuse restriction found.","SC":"Disclaimer: unofficial, copyright SC Legislative Council; robots allows *.",
"NC":"Disclaimer: photos may be copyrighted; statutes no restriction found.","DC":"Prefer github.com/DCCouncil/law-xml (CC0).",
}
rows=list(csv.DictReader(open("sources.csv")))
newcols=["robots_status","terms_summary","terms_url","checked_at"]
fixes=[]
for row in rows:
  u=row["official_source_urls"]
  for a,b in FIX.items():
    if a in u: u=u.replace(a,b); fixes.append((row["code"] or row["subdivision"],a,b))
  if row["code"]=="OR" and row["country"]=="US": pass
  row["official_source_urls"]=u
  hosts=[h for h in re.findall(r"((?:[a-z0-9-]+\.)+(?:gov|us|org|com|ca|au|in|net|edu)(?:\.[a-z]{2})?)\b",u)]
  inv={v:k for k,v in FIX.items()}
  st=[];tu=[];ts=[];ca=[]
  for h in hosts:
    r=R.get(h) or R.get(inv.get(h,""))
    if not r: st.append(f"{h}: not checked"); continue
    ca.append(r["checked_at"]); rob=r.get("robots","")
    if "challenge" in (rob,r.get("home")): s="challenge"
    elif rob.startswith("error"): s="blocked(TLS/conn error: "+("cert verify failed" if "CertVerif" in rob else "SSL EOF/conn reset")+")"
    elif rob.startswith("none(403)") or r.get("home")==403: s="blocked(403)"
    elif rob=="present":
      p=rp.RobotFileParser(); p.parse(r["robots_txt"].splitlines())
      m=re.search(r"https?://"+re.escape(h)+r"(/[^ ;()]*)?",u); path=(m.group(1) if m and m.group(1) else "/")
      ok=p.can_fetch(UA,f"https://{h}{path}"); cd=p.crawl_delay(UA)
      s=("allowed" if ok else f"disallowed({path})")+(f";crawl-delay={cd}" if cd else "")
    else: s="no robots.txt (allowed)"
    st.append(f"{h}: {s}")
    if r.get("terms_url"): tu.append(r["terms_url"])
    if r.get("terms_snips"): ts.append(re.sub(r"\s+"," ",r["terms_snips"][0])[:200])
  row["robots_status"]=" | ".join(st)
  row["terms_url"]=" | ".join(tu)
  row["terms_summary"]=OVR.get(row["code"]) or (" ".join(ts) if ts else "no terms page found on homepage")
  if row["country"]=="IN": row["terms_summary"]="India Code: 403 to scripted client (robots+home); GoI content; needs browser-like access or archives"
  row["checked_at"]=min(ca) if ca else ""
f=list(rows[0].keys())
w=csv.DictWriter(open("sources.csv","w",newline=""),fieldnames=f); w.writeheader(); w.writerows(rows)
json.dump(fixes,open("checks/url_fixes.json","w"))
from collections import Counter
c=Counter()
for row in rows:
  s=row["robots_status"]
  c["challenge" if "challenge" in s else "blocked" if "blocked" in s else "restricted" if "disallowed" in s or "RESTRICT" in row["terms_summary"]+row["terms_robots_notes"] else "ok"]+=1
print(c); print(fixes)
for row in rows:
  if row["country"]!="IN" or row["subdivision"]=="Delhi": print(row["country"],row["code"],"::",row["robots_status"][:150])

import re,html as _h
from page_crawl import *
B="https://legacy.utcourts.gov/rules/"
J={"classes":["district"]};S_={"classes":["supreme"]};ALL={"classes":["supreme","district","justice"]}
TYPES=[("urcp","Utah Rules of Civil Procedure","URCP","civil_procedure",J),
 ("urcrp","Utah Rules of Criminal Procedure","URCRP","criminal_procedure",J),
 ("urap","Utah Rules of Appellate Procedure","URAP","civil_and_criminal_procedure",S_),
 ("urjp","Utah Rules of Juvenile Procedure","URJP","civil_and_criminal_procedure",J),
 ("srpe","Utah Rules of Small Claims Procedure","USCP","civil_procedure",J),
 ("adr","Utah Rules of Court-Annexed Alternative Dispute Resolution","UADR","civil_procedure",J),
 ("ure","Utah Rules of Evidence","URE","evidence",ALL),
 ("urbcp","Utah Rules of Business and Chancery Court Procedure","URBCP","civil_procedure",J),
 ("ucja","Utah Code of Judicial Administration","UCJA","local_court_rules",ALL)]
def make(typ):
    def f():
        ix=page(B+typ+".php",f"ut_{typ}_index.html")
        ls=re.findall(r'href="(view\.php\?type=%s&(?:amp;)?rule=([^"&]+))"[^>]*>([^<]{2,200})<'%typ,ix["bytes"].decode("utf-8","replace"))
        seen=set();out=[]
        for href,num,label in ls:
            num=_h.unescape(num)
            if num in seen: continue
            seen.add(num)
            pg=page(B+_h.unescape(href),f"ut_{typ}_{re.sub(r'[^A-Za-z0-9.-]','_',num)}.html")
            if not pg: continue
            t=html_text(pg["bytes"]);lines=t.split("\n")
            i=next((k for k,l in enumerate(lines) if re.match(r"^Rule\s*%s\b"%re.escape(num),l) or re.match(r"^(?:Rule|Section|Article)\s+\S+",l)),None)
            if i is None: continue
            head=lines[i];m=re.match(r"^(?:Rule|Section|Article)\s*(\S+?)\.?\s+(.*)$",head)
            title=(m.group(2) if m else head).strip().rstrip(".")
            body=[l for l in lines[i+1:] if not re.match(r"^Rule printed on|^Back to |^Next Rule|^<< Previous|^Go to https",l)]
            body="\n".join(body).strip()
            if re.match(r"^Effective:",body): pass
            if re.search(r"\[?(?:Repealed|Reserved|Abrogated)",title,re.I) and len(body)<120: continue
            if len(body)<20: continue
            out.append({"num":num,"title":title,"body":body,**{k:pg[k] for k in ("url","pol","fetched","sha","key")}})
        return out
    f.__name__="pages_"+typ;return f
for t,*_ in TYPES: globals()["pages_"+t]=make(t)
SETS=[(None,n,a,fam,"statewide",sc,{"pages":"pages_"+t}) for t,n,a,fam,sc in TYPES]

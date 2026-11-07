import re,html as _h,os,subprocess
from page_crawl import *
B="https://www.courts.wa.gov/court_rules/"
J={"classes":["district"]};S_={"classes":["supreme"]};ALL={"classes":["supreme","district","justice"]};LJ={"classes":["justice"]}
SETLIST=[("sup","AR","Washington Superior Court Administrative Rules","local_court_rules",J),
 ("sup","CCR","Washington Superior Court Civil Commitment Rules","civil_procedure",J),
 ("sup","CR","Washington Superior Court Civil Rules","civil_procedure",J),
 ("sup","SCCAR","Washington Superior Court Civil Arbitration Rules","civil_procedure",J),
 ("sup","SPR","Washington Superior Court Special Proceedings Rules","civil_procedure",J),
 ("sup","GALR","Washington Superior Court Guardian ad Litem Rules","civil_procedure",J),
 ("sup","CrR","Washington Superior Court Criminal Rules","criminal_procedure",J),
 ("sup","SPRC","Washington Superior Court Special Proceedings Rules - Criminal","criminal_procedure",J),
 ("sup","JuCR","Washington Juvenile Court Rules","civil_and_criminal_procedure",J),
 ("app","RAP","Washington Rules of Appellate Procedure","civil_and_criminal_procedure",S_),
 ("clj","ARLJ","Washington Administrative Rules for Courts of Limited Jurisdiction","local_court_rules",LJ),
 ("clj","RALJ","Washington Rules for Appeal of Decisions of Courts of Limited Jurisdiction","civil_and_criminal_procedure",LJ),
 ("clj","CRLJ","Washington Civil Rules for Courts of Limited Jurisdiction","civil_procedure",LJ),
 ("clj","CrRLJ","Washington Criminal Rules for Courts of Limited Jurisdiction","criminal_procedure",LJ),
 ("clj","IRLJ","Washington Infraction Rules for Courts of Limited Jurisdiction","civil_procedure",LJ),
 ("ga","GR","Washington General Rules","local_court_rules",ALL),
 ("ga","ER","Washington Rules of Evidence","evidence",ALL),
 ("ga","BJAR","Washington Board for Judicial Administration Rules","local_court_rules",ALL),
 ("ga","JISCR","Washington Judicial Information System Committee Rules","local_court_rules",ALL),
 ("aca","SCAR","Washington Rules for Appellate Court Administration (SCAR)","local_court_rules",S_)]
def num_from(fn):
    m=re.match(r"[A-Za-z]+_[A-Za-z ]+?_(\w+)_(\w+)_(\w+)\.pdf$",fn) or re.match(r"[A-Za-z]+_(?:[A-Za-z]+)_([^_]+)_([^_]+)_([^_]+)\.pdf$",fn)
    return None
def parse_num(fn,setname):
    base=fn.rsplit("/",1)[-1][:-4];parts=base.split("_")
    # PREFIX_SET_a_b_c ; SET may contain underscores? take the last three parts
    p=parts[-3:]
    out=[]
    for i,x in enumerate(p):
        if x.isdigit():
            v=str(int(x))
            if i>0 and x=="00": break
            out.append(v)
        else:
            if x.strip("0")=="" : break
            out.append(x)
    return ".".join(out) if out else None
def make(group,sset):
    def f():
        lp=page(B+f"?fa=court_rules.list&group={group}&set={sset}",f"wa_{group}_{sset}_list.html")
        t=lp["bytes"].decode("utf-8","replace")
        items=re.findall(r'href="([^"]+\.pdf)"[^>]*>(.*?)</a>',t,re.S)
        out=[];seen=set()
        for h,label in items:
            if f"/{sset}/" not in h and f"/{sset.replace(' ','%20')}/" not in h: continue
            n=parse_num(_h.unescape(h),sset)
            if not n or n in seen: continue
            seen.add(n)
            url=B+_h.unescape(h) if not h.startswith("http") else h
            url=re.sub(r"/court_rules/\.\./","/",url) if "court_rules/../" in url else url
            url=url.replace("/court_rules/../court_rules/","/court_rules/")
            title=re.sub(r"\s+"," ",re.sub(r"<[^>]+>","",_h.unescape(label))).strip()
            pg=page(url,f"wa_{group}_{sset}_{n}.pdf")
            if not pg: continue
            os.makedirs(PDFDIR+"/WA",exist_ok=True);pp=f"{PDFDIR}/WA/{pg['sha']}.pdf"
            if not os.path.exists(pp): open(pp,"wb").write(pg["bytes"])
            txt=norm(subprocess.run(["pdftotext",pp,"-"],capture_output=True,text=True).stdout)
            lines=txt.split("\n");n_=0
            while lines and n_<5 and (re.match(r"^(?:RULE|Rule)?\s*[A-Za-z]*\s*\d[\w.\-]*$",lines[0].strip()) or (len(lines[0])<110 and lines[0].upper()==lines[0] and re.search(r"[A-Z]",lines[0]))): lines.pop(0);n_+=1
            body="\n".join(lines).strip()
            if re.match(r"^\[?(?:Reserved|Repealed|Rescinded|Abrogated)",title,re.I) and len(body)<80: continue
            if len(body)<20: continue
            out.append({"num":n,"title":title,"body":body,"url":pg["url"],"pol":pg["pol"],"fetched":pg["fetched"],"sha":pg["sha"],"pdf_path":f"rules/pdf/WA/{pg['sha']}.pdf","pdf_sha256":pg["sha"],"key":pg["key"]})
        return out
    f.__name__=f"pages_{group}_{sset}";return f
for g,s_,*_ in SETLIST: globals()[f"pages_{g}_{s_}"]=make(g,s_)
SETS=[(None,n,a,fam,"statewide",sc,{"pages":f"pages_{g}_{a}"}) for g,a,n,fam,sc in [(g,s_,n,fam,sc) for g,s_,n,fam,sc in SETLIST]]

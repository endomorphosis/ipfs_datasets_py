import re,html as _h,os,subprocess
from page_crawl import *
J={"classes":["district"]};S_={"classes":["supreme"]}
SETLIST=[("CivilProcedure","cv","Alabama Rules of Civil Procedure","ARCP","civil_procedure",J),("AppellateProcedure","ap","Alabama Rules of Appellate Procedure","ARAP","appellate_procedure",S_)]
def make(libpage,pre,abbr):
    def f():
        lp=page(f"https://judicial.alabama.gov/library/{libpage}",f"al_{pre}_list.html")
        t=lp["bytes"].decode("utf-8","replace")
        items=re.findall(r'href="([^"]*?/library/rules/%s([0-9A-Za-z_]+)\.pdf)"[^>]*>(.*?)</a>'%pre,t,re.S|re.I)
        labs={}
        order=[]
        for h,n,label in items:
            lab=re.sub(r"\s+"," ",re.sub(r"<[^>]+>","",_h.unescape(label))).strip()
            n=n.upper()
            if n not in labs: labs[n]=[];order.append((n,h))
            labs[n].append(lab)
        out=[]
        for n,h in order:
            url=_h.unescape(h) if h.startswith("http") else "https://judicial.alabama.gov"+_h.unescape(h)
            L=[x for x in labs[n] if x]
            title=next((x for x in L if not re.match(r"^Rules?\s+[\w.\-–]+\.?$",x)),"").rstrip(".")
            if re.match(r"^(?:Omitted|Repealed|Reserved|\[Omitted\])",title,re.I): continue
            pg=page(url,f"al_{pre}_{n.upper()}.pdf")
            if not pg or pg["bytes"][:4]!=b"%PDF": continue
            os.makedirs(PDFDIR+"/AL",exist_ok=True);pp=f"{PDFDIR}/AL/{pg['sha']}.pdf"
            if not os.path.exists(pp): open(pp,"wb").write(pg["bytes"])
            txt=norm(subprocess.run(["pdftotext",pp,"-"],capture_output=True,text=True).stdout)
            lines=[l for l in txt.split("\n")]
            while lines and (not lines[0].strip() or re.match(r"^Alabama Rules of|^Rule\s+"+re.escape(n)+r"\.?\s*$",lines[0].strip(),re.I) or lines[0].strip().rstrip(".")==title or re.match(r"^[IVX]+\.\s+[A-Z]",lines[0].strip())): lines.pop(0)
            body="\n".join(lines).strip()
            if len(body)<20 or ("COMMENT" in n) or (n.startswith("APPX") and len(body)<120): continue
            num=re.sub(r"_(?=[A-Za-z])","",re.sub(r"_(?=\d)",".",n)).upper()
            out.append({"num":num,"title":title,"body":body,"url":pg["url"],"pol":pg["pol"],"fetched":pg["fetched"],"sha":pg["sha"],"pdf_path":f"rules/pdf/AL/{pg['sha']}.pdf","pdf_sha256":pg["sha"],"key":pg["key"]})
        return out
    f.__name__=f"pages_{abbr}";return f
for lp,pre,n,a,fam,sc in SETLIST: globals()[f"pages_{a}"]=make(lp,pre,a)
SETS=[(None,n,a,fam,"statewide",sc,{"pages":f"pages_{a}"}) for lp,pre,n,a,fam,sc in SETLIST]

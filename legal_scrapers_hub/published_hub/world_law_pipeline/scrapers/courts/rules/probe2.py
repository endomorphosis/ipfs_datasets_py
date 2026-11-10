import sys,re,json,hashlib
from rules_common import *
from rules_build import *
def probe(k,u,head=None,caps=False):
    b,url,pol=cached(u,"probe2_"+k+".pdf")
    if not b: print(k,"FAIL");return
    p=f"{RAW}/probe2_{k}.pdf";t=re.sub(r"\n\d{1,3}(?=\n)","",pdf_text(p));open(f"{RAW}/probe2_{k}.txt","w").write(t)
    r=extract(t,re.compile(head,re.M) if head else HEAD,caps)
    print(k,pol,len(b),len(t),qa(r),[x["num"] for x in r][:12])
if __name__=="__main__":
    for a in sys.argv[1:]:
        k,u=a.split("=",1);probe(k,u)

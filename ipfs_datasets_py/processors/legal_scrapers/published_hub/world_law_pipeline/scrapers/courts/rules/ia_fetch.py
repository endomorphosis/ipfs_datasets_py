import json
from rules_common import *
u="https://www.legis.iowa.gov/docs/ACO/CR/LINC/02-27-2026.chapter.%d.pdf"
out={}
for n in range(1,70):
    try:
        b,url,pol=cached(u%n,f"ia_ch{n}.pdf")
    except Exception as e:
        print(n,"err",e);continue
    if not b: print(n,"none");continue
    t=pdf_text(f"{RAW}/ia_ch{n}.pdf");out[n]=t[:200].replace("\n"," / ");print(n,len(b),out[n][:120],flush=True)
json.dump(out,open(f"{RAW}/ia_manifest.json","w"))

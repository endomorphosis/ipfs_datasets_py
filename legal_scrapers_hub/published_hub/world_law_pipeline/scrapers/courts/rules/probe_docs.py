import sys,re,hashlib,os,json
from rules_common import *
DOCS={
 "HI_HRCP":"https://www.courts.state.hi.us/wp-content/uploads/2024/09/hrcp_ada.htm",
 "HI_HRPP":"https://www.courts.state.hi.us/wp-content/uploads/2024/12/hrpp.htm",
 "WY_CIV":"https://www.wyocourts.gov/app/uploads/2025/01/WY_Civ_Proc_Rules_Feb26.pdf",
 "WY_CRIM":"https://www.wyocourts.gov/app/uploads/2025/01/Wyoming-Rules-of-Criminal-Procedure.pdf",
 "ME_CRIM":"https://www.courts.maine.gov/rules/text/mru_crim_p_only_2025-05-01.pdf",
 "TX_CIV":"https://www.txcourts.gov/media/1462465/texas-rules-of-civil-procedure-march-1-2026.pdf",
 "GA_USC":"https://www.gasupreme.us/wp-content/uploads/2024/01/UNIFORM-STATE-COURT-RULES-2024_01_18.pdf",
 "GA_USUP":"https://www.gasupreme.us/wp-content/uploads/2026/03/UNIFORM-SUPERIOR-COURT-RULES-2026_03_19.pdf",
 "MS_CIV":"https://www.firstcircuitcourt.ms.gov/sites/firstcircuitcourt/files/files/rules_of_civil_procedure%206-26-18.pdf",
 "NC_GRP":"https://www.nccourts.gov/assets/inline-files/General%20Rules%20of%20Practice%20for%20the%20Superior%20and%20District%20Courts%20-%206%20August%202025.pdf",
 "AK_CIV":"https://courts.alaska.gov/rules/docs/civ.pdf",
}
for k,u in DOCS.items():
    if len(sys.argv)>1 and k not in sys.argv[1:]: continue
    ext="pdf" if u.endswith(".pdf") else "html"
    b,eu,pol=cached(u,f"probe_{k}.{ext}")
    if not b: print(k,"FAILED",pol);continue
    if ext=="pdf":
        open(f"{RAW}/probe_{k}.pdf","wb").write(b);t=pdf_text(f"{RAW}/probe_{k}.pdf")
    else: t=html_text(b)
    open(f"{RAW}/probe_{k}.txt","w").write(t)
    heads=re.findall(r"(?m)^(?:Rule|RULE)\s+[\d.]+[A-Za-z]?\.?.{0,40}",t)
    print(k,pol,len(b),len(t),len(heads),heads[:3])

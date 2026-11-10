import json,os
_ok=json.load(open(os.path.dirname(os.path.abspath(__file__))+"/pa_ok.json"))
_ok["231"]=sorted(set(_ok["231"]+[200]))
T={"231":("Pennsylvania Rules of Civil Procedure and Orphans' Court Rules (231 Pa. Code)","PA231","civil_procedure",{"classes":["district"]}),
"234":("Pennsylvania Rules of Criminal Procedure (234 Pa. Code)","PA234","criminal_procedure",{"classes":["district","justice"]}),
"225":("Pennsylvania Rules of Evidence (225 Pa. Code)","PA225","evidence",{"classes":["supreme","district","justice"]}),
"210":("Pennsylvania Rules of Appellate Procedure and Appellate Court Operating Procedures (210 Pa. Code)","PA210","appellate_procedure",{"classes":["supreme"]}),
"237":("Pennsylvania Rules of Juvenile Court Procedure (237 Pa. Code)","PA237","juvenile_procedure",{"classes":["district"]}),
"246":("Pennsylvania Rules of Conduct, Office Standards and Civil Procedure for Magisterial District Judges (246 Pa. Code)","PA246","civil_procedure",{"classes":["justice"]}),
"201":("Pennsylvania Rules of Judicial Administration (201 Pa. Code)","PA201","court_administration",{"classes":["supreme","district","justice"]})}
O={"kind":"pdf","head":r"^Rule\s+(?P<num>\d+(?:\.\d+)?(?:-\d+)?(?:\.\d+)?[A-Za-z]?)\.[ ]*(?P<rest>.*)$","titlewrap":True,"dropempty":True,"longestdup":True,"dropbracket":True,"dropdots":True,"droptitlebr":True}
SETS=[]
for t,(nm,ab,fam,sc) in T.items():
    for ch in sorted(_ok.get(t,[])):
        SETS.append((f"https://www.pacodeandbulletin.gov/secure/pacode/data/{int(t):03d}/chapter{ch}/{int(t):03d}_{ch:04d}.pdf",f"{nm}, Chapter {ch}",f"{ab}C{ch}",fam,"statewide",sc,dict(O)))

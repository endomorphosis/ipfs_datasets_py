B="https://courts.ca.gov/system/files?file=file/"
J={"classes":["district"]};S_={"classes":["supreme"]};ALL={"classes":["supreme","district","justice"]}
HEAD=r"^Rule\s+(?P<num>\d+\.\d+(?:\.\d+)?)\.[ ]*(?P<rest>.*)$"
def s(f,name,abbr,fam,sc):
    return (B+f,name,abbr,fam,"statewide",sc,{"kind":"pdf","head":HEAD,"titlewrap":True,"dropempty":True,"longestdup":True,"dropbracket":True})
SETS=[
 s("roc-title-1.pdf","California Rules of Court, Title 1: Rules Applicable to All Courts","CRC1","local_court_rules",ALL),
 s("roc-title-2.pdf","California Rules of Court, Title 2: Trial Court Rules","CRC2","local_court_rules",J),
 s("roc-title-3_3.pdf","California Rules of Court, Title 3: Civil Rules","CRC3","civil_procedure",J),
 s("roc-title-4.pdf","California Rules of Court, Title 4: Criminal Rules","CRC4","criminal_procedure",J),
 s("roc-title-5_3.pdf","California Rules of Court, Title 5: Family and Juvenile Rules","CRC5","civil_procedure",J),
 s("roc-title-7.pdf","California Rules of Court, Title 7: Probate Rules and Mental Health Rules","CRC7","civil_procedure",J),
 s("roc-title-8_0.pdf","California Rules of Court, Title 8: Appellate Rules","CRC8","civil_and_criminal_procedure",S_),
 s("roc-title-9_0.pdf","California Rules of Court, Title 9: Rules on Law Practice, Attorneys, and Judges","CRC9","local_court_rules",ALL),
 s("roc-title-10_1.pdf","California Rules of Court, Title 10: Judicial Administration Rules","CRC10","local_court_rules",ALL),
]

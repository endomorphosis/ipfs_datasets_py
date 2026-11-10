M="https://courts.ms.gov/research/rules/msrulesofcourt/"
J={"classes":["district"]};S_={"classes":["supreme"]};ALL={"classes":["supreme","district","justice"]};JC={"classes":["justice"]}
BARE=r"^(?:RULE|Rule)\s+(?P<num>\d+(?:\.\d+)?[A-Za-z]?)\.?[ ]*(?P<rest>(?:[A-Z][A-Z0-9 ,;:'’&\-()/]{3,})?)$"
def s(f,name,abbr,fam,sc,extra=None):
    o={"kind":"pdf","titlewrap":True,"dropempty":True,"longestdup":True,"dropbracket":True};o.update(extra or {})
    return (M+f,name,abbr,fam,"statewide",sc,o)
SETS=[s("2026-07-01 Rules of Civil Procedure with Advisory Committee Notes (with Forms 6-8 attached).pdf","Mississippi Rules of Civil Procedure","MSRCP","civil_procedure",J),
 s("Rules of Criminal Procedure Post-070123.pdf","Mississippi Rules of Criminal Procedure","MSRCRP","criminal_procedure",J,{"head":r"^Rule\s+(?P<num>\d+\.\d+)(?:\.[ ]+|[ ]+)(?P<rest>[A-Z].*)$"}),
 s("2025-04-07 Restyled Rules of Evidence.pdf","Mississippi Rules of Evidence","MSRE","evidence",ALL),
 s("Rules of Appellate Procedure Current.pdf","Mississippi Rules of Appellate Procedure","MSRAP","civil_and_criminal_procedure",S_),
 s("UCRCCC Post-070117.pdf","Uniform Civil Rules of Circuit and County Court Practice","MSUCRCCC","local_court_rules",J,{"head":BARE}),
 s("uniform_chancery_rules.pdf","Uniform Chancery Court Rules","MSUCHR","local_court_rules",J,{"head":BARE}),
 s("uniform_rules_yc_practice.pdf","Uniform Rules of Youth Court Practice","MSURYC","civil_and_criminal_procedure",J,{"head":BARE}),
]

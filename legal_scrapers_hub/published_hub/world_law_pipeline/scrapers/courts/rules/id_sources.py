"""Idaho court rules: official full-text HTML pages at isc.idaho.gov/rules-procedure/<set> (robots allowed). Seed: Chief of Staff inbox."""
B="https://isc.idaho.gov/rules-procedure/"
S_={"classes":["supreme"]};D_={"classes":["district"]};J_={"classes":["district","justice"]};ALL={"classes":["supreme","district","justice"]}
HD=r"^\s*Idaho [A-Za-z ,()&.'-]*?Rules?(?: of [A-Za-z ]+?)? (?P<num>\d{1,3}(?:\.\d+)*[A-Za-z]?(?:\([a-z0-9]+\))?)\.[ ]+(?P<rest>[A-Z][^\n]{1,160})$"
O={"kind":"html","head":HD,"dropempty":True,"longestdup":True,"dropbracket":True,"titlewrap":False}
R=[("iar","Idaho Appellate Rules","IAR","appellate_procedure",S_),("icar","Idaho Court Administrative Rules","ICAR","court_administration",ALL),
("icr","Idaho Criminal Rules","ICR","criminal_procedure",J_),("iir","Idaho Infraction Rules","IIR","criminal_procedure",J_),("ijr","Idaho Juvenile Rules","IJR","juvenile_procedure",J_),
("imcr","Idaho Misdemeanor Criminal Rules","IMCR","criminal_procedure",J_),("ircp","Idaho Rules of Civil Procedure","IRCP","civil_procedure",J_),
("ire","Idaho Rules of Evidence","IRE","evidence",ALL),("irefs","Idaho Rules for Electronic Filing and Service","IREFS","civil_and_criminal_procedure",ALL),
("irfl","Idaho Rules of Family Law Procedure","IRFLP","family_procedure",J_),("irsca","Idaho Rules for Small Claims Actions","IRSCA","civil_procedure",J_),
("irtc","Idaho Rules for Treatment Courts","IRTC","specialized_courts",J_)]
HD2=r"^(?P<num>\d{1,3}(?:\.\d+)*[A-Z]?)(?P<rest>[A-Z][a-z][^\n]{1,150})$"
ALT={"IAR","IIR","IMCR","IRE"}
SETS=[(B+f,n,a,fam,"statewide",c,dict(O,head=HD2) if a in ALT else dict(O)) for f,n,a,fam,c in R]

B="https://rules.incourts.gov/pdf/PDF%20-%20"
CL={"s":{"classes":["supreme"]},"d":{"classes":["district"]},"a":{"classes":["supreme","district","justice"]}}
O={"kind":"pdf","titlewrap":True,"dropempty":True,"longestdup":True,"dropbracket":True,"stripeff":True}
R=[("Trial/trial","Indiana Rules of Trial Procedure","INTR","civil_procedure","d"),
("Appellate/appellate","Indiana Rules of Appellate Procedure","INAP","appellate_procedure","s"),
("Criminal/criminal","Indiana Rules of Criminal Procedure","INCRP","criminal_procedure","d"),
("Evidence/evidence","Indiana Rules of Evidence","INEV","evidence","a"),
("Tax/tax","Indiana Tax Court Rules","INTAX","civil_procedure","s"),
("Admin/admin","Indiana Rules for Administration of the Courts","INADM","court_administration","a"),
("ADR/adr","Indiana Rules for Alternative Dispute Resolution","INADR","civil_procedure","d")]
SETS=[(B+f+".pdf",n,a,fam,"statewide",CL[c],dict(O)) for f,n,a,fam,c in R]

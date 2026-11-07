B="https://courts.alaska.gov/rules/docs/"
J={"classes":["district"]};S_={"classes":["supreme"]};ALL={"classes":["supreme","district","justice"]}
def s(f,name,abbr,fam,sc,extra=None):
    o={"kind":"pdf","pdfmode":"raw","titlewrap":True,"dropempty":True,"longestdup":True,"dropbracket":True};o.update(extra or {})
    return (B+f,name,abbr,fam,"statewide",sc,o)
SETS=[s("civ.pdf","Alaska Rules of Civil Procedure","AKRCIV","civil_procedure",J),
 s("crpro.pdf","Alaska Rules of Criminal Procedure","AKRCRIM","criminal_procedure",J),
 s("app.pdf","Alaska Rules of Appellate Procedure","AKRAP","civil_and_criminal_procedure",S_),
 s("dciv.pdf","Alaska District Court Rules of Civil Procedure","AKDCIV","civil_procedure",J),
 s("prob.pdf","Alaska Probate Rules","AKPROB","civil_procedure",J),
 s("ev.pdf","Alaska Rules of Evidence","AKEV","evidence",ALL),
 s("cina.pdf","Alaska Child in Need of Aid Rules","AKCINA","civil_procedure",J),
 s("del.pdf","Alaska Delinquency Rules","AKDEL","criminal_procedure",J),
 s("mo.pdf","Alaska Minor Offense Rules","AKMO","criminal_procedure",J),
 s("adop.pdf","Alaska Adoption Rules","AKADOP","civil_procedure",J),
 s("adm.pdf","Alaska Rules of Administration","AKADM","local_court_rules",ALL)]

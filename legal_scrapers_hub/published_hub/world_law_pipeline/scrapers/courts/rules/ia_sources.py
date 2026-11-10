U="https://www.legis.iowa.gov/docs/ACO/CR/LINC/02-27-2026.chapter.%d.pdf"
J={"classes":["district"]};S={"classes":["supreme"]};ALL={"classes":["supreme","district","justice"]}
HEAD=r"^Rule\s+(?P<num>\d+\.\d+)(?:\.[ ]+|[ ]+)(?P<rest>[A-Z].*)$"
NOISE=r"^(?:Ch \d+, p\.\s?[\dxvilc]+|(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{4}|[A-Z][A-Z ,&\-]{5,60})$"
def s(n,name,abbr,fam,sc,opts=None):
    o={"kind":"pdf","head":HEAD,"noise":NOISE,"mergedup":True};o.update(opts or {})
    return (U%n,name,abbr,fam,"statewide",sc,o)
SETS=[
 s(1,"Iowa Rules of Civil Procedure","IARCP","civil_procedure",J),
 s(2,"Iowa Rules of Criminal Procedure","IARCRP","criminal_procedure",J),
 s(4,"Iowa Protective and No Contact Orders","IAPROT","civil_procedure",J),
 s(5,"Iowa Rules of Evidence","IAEVID","evidence",ALL),
 s(6,"Iowa Rules of Appellate Procedure","IARAP","civil_and_criminal_procedure",S),
 s(7,"Iowa Rules of Probate Procedure","IARPP","civil_procedure",J),
 s(8,"Iowa Rules of Juvenile Procedure","IARJP","civil_and_criminal_procedure",J),
 s(9,"Iowa Child Support Guidelines","IACSG","civil_procedure",J),
 s(12,"Iowa Rules for Involuntary Hospitalization of Persons with Mental Illness","IAMH","civil_procedure",J),
 s(13,"Iowa Rules for Involuntary Commitment or Treatment of Persons with Substance Use Disorders","IASUD","civil_procedure",J),
 s(14,"Iowa Rules of Electronic Search Warrant Procedure","IAESW","criminal_procedure",J),
 s(15,"Iowa Rules of Remote Procedure","IARRP","civil_and_criminal_procedure",ALL),
 s(16,"Iowa Rules of Electronic Procedure","IAREP","civil_and_criminal_procedure",ALL),
 s(20,"Iowa Court Records Rules","IACR","civil_and_criminal_procedure",ALL),
 s(21,"Iowa Organization and Procedures of Appellate Courts","IAAPPC","local_court_rules",S),
 s(22,"Iowa Judicial Administration Rules","IAJA","local_court_rules",ALL),
 s(23,"Iowa Time Standards for Case Processing","IATS","local_court_rules",J),
 s(25,"Iowa Rules for Expanded News Media Coverage","IANM","local_court_rules",ALL),
 s(26,"Iowa Rules for Installment Payment Plans and Court Collection Activities","IACC","local_court_rules",J),
]

W="https://www.courts.ri.gov/"
J={"classes":["district"]};S_={"classes":["supreme"]};ALL={"classes":["supreme","district","justice"]}
DASH=r"^(?:Rule\s+)?(?P<num>\d{1,3}(?:\.\d+)?[A-Za-z]?)\.[ ]+(?P<rest>[A-Z][^—–\n]{2,150}?)\.?[ ]*[—–][ ]*"
def s(p,name,abbr,fam,sc,extra=None):
    o={"kind":"pdf","titlewrap":True,"dropempty":True,"longestdup":True,"dropbracket":True};o.update(extra or {})
    return (W+p,name,abbr,fam,"statewide",sc,o)
SETS=[s("Courts/superiorcourt/Documents/SuperiorCourtRulesOfCivilProcedure.pdf","Rhode Island Superior Court Rules of Civil Procedure","RISCCIV","civil_procedure",J,{"head":DASH}),
 s("Courts/superiorcourt/Documents/SuperiorCourtRulesOfCriminalProcedure.pdf","Rhode Island Superior Court Rules of Criminal Procedure","RISCCRIM","criminal_procedure",J,{"head":DASH}),
 s("Courts/superiorcourt/Documents/SuperiorCourtRulesOfPractice.pdf","Rhode Island Superior Court Rules of Practice","RISCPRAC","local_court_rules",J),
 s("Courts/superiorcourt/Documents/SuperiorCourtRulesGoverningArbitrationOfCivilActions.pdf","Rhode Island Superior Court Rules Governing Arbitration of Civil Actions","RISCARB","civil_procedure",J),
 s("Legal-Resources/Documents/RulesOfEvidence.pdf","Rhode Island Rules of Evidence","RIEV","evidence",ALL),
 s("Courts/SupremeCourt/Documents/Supreme-Rules-Article1.pdf","Rhode Island Supreme Court Rules, Article I (Appellate Procedure)","RISCTART1","civil_and_criminal_procedure",S_),
 s("Courts/SupremeCourt/Documents/Supreme-Rules-Article9.pdf","Rhode Island Supreme Court Rules, Article IX (Review of General Magistrate Orders)","RISCTART9","civil_procedure",ALL),
 s("Courts/SupremeCourt/Documents/Supreme-Rules-Article10.pdf","Rhode Island Supreme Court Rules, Article X (Electronic Filing)","RISCTART10","civil_and_criminal_procedure",ALL),
 s("Courts/districtcourt/Documents/District_Civil_Rules.pdf","Rhode Island District Court Civil Rules","RIDCCIV","civil_procedure",J,{"head":DASH}),
 s("Courts/districtcourt/Documents/District_Rules_of_Criminal_Procedure.pdf","Rhode Island District Court Rules of Criminal Procedure","RIDCCRIM","criminal_procedure",J,{"head":DASH}),
 s("Courts/districtcourt/Documents/District_Rules_of_Small_Claims_Procedure.pdf","Rhode Island District Court Rules of Small Claims Procedure","RIDCSC","civil_procedure",J,{"head":DASH}),
 s("Courts/familycourt/Documents/RulesOfCriminalProcedure.pdf","Rhode Island Family Court Rules of Criminal Procedure","RIFCCRIM","criminal_procedure",J,{"head":DASH}),
 s("Courts/familycourt/Documents/RulesOfDomesticRelationsProcedure.pdf","Rhode Island Family Court Rules of Domestic Relations Procedure","RIFCDR","civil_procedure",J,{"head":DASH}),
 s("Courts/familycourt/Documents/RulesOfPractice.pdf","Rhode Island Family Court Rules of Practice","RIFCPRAC","local_court_rules",J,{"head":DASH}),
 s("Courts/familycourt/Documents/RulesForJuvenileProceedings.pdf","Rhode Island Family Court Rules of Juvenile Proceedings","RIFCJUV","civil_and_criminal_procedure",J,{"head":DASH})]

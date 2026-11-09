U="https://www.wyocourts.gov/app/uploads/"
SETS_RAW=[
("2025/01/WY-Rules-of-Civ.-Procedure-Eff.-9-21-26.pdf","Wyoming Rules of Civil Procedure","WRCP","civil_procedure","district"),
("2026/06/WRCrP-with-bond-schedule.pdf","Wyoming Rules of Criminal Procedure","WRCrP","criminal_procedure","statewide"),
("2025/01/WRAP-eff-Dec-1.pdf","Wyoming Rules of Appellate Procedure","WRAP","appellate_procedure","appellate"),
("2025/01/WYOMING-RULES-OF-EVIDENCE-1.pdf","Wyoming Rules of Evidence","WRE","evidence","statewide"),
("2025/01/WY-Rules-of-Civil-Procedure-for-Circuit-Courts-1.pdf","Wyoming Rules of Civil Procedure for Circuit Courts","WRCPC","civil_procedure","circuit"),
("2025/01/RULES-OF-PROCEDURE-FOR-JUVENILE-August-2020-1.pdf","Rules of Procedure for Juvenile Courts","WRJUV","juvenile_procedure","juvenile"),
("2026/06/Uniform-Rules-for-District-Courts-of-Wyomingeff-August-2026.pdf","Uniform Rules for District Courts","WURDC","local_rules","district"),
("2025/01/UNIFORM_RULES_FOR_THE_CIRCUIT_COURTS_OF_WYOMING-1.pdf","Uniform Rules for the Circuit Courts","WURCC","local_rules","circuit"),
("2025/01/WY-Rules-of-Civ.-Procedure-for-Chancery-Ct.-Eff.-9-21-26.pdf","Wyoming Rules of Civil Procedure for the Chancery Court","WRCPCH","civil_procedure","chancery"),
("2026/06/Uniform-Rules-for-Chancery-Court-eff-August-2026.pdf","Uniform Rules for Chancery Court","WURCH","local_rules","chancery"),
("2025/01/Wyoming-Rules-and-Forms-Governing-Small-Claims-Cases-1.pdf","Rules Governing Small Claims Cases","WRSC","small_claims","circuit"),
("2025/01/Wyo-Rules-for-Electronic-Filing-Service-eff.-Sept-2026.pdf","Wyoming Rules for Electronic Filing and Service","WREFS","efiling","statewide"),
("2025/01/Rules-of-the-Supreme-Court-of-Wyoming-May-2022-1.pdf","Rules of the Supreme Court of Wyoming","WRSCT","court_administration","supreme"),
]
CL={"supreme":{"classes":["supreme"]},"appellate":{"classes":["supreme"]},"district":{"classes":["district"]},"circuit":{"classes":["district","justice"]},"chancery":{"classes":["district"]},"juvenile":{"classes":["district"]},"statewide":{"classes":["supreme","district","justice"]}}
OPTS={"kind":"pdf","titlewrap":True,"dropempty":True,"longestdup":True,"dropbracket":True}
SETS=[(U+f,n,a,fam,"statewide",CL[sc],dict(OPTS)) for f,n,a,fam,sc in SETS_RAW]

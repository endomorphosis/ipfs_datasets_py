B="https://www-media.floridabar.org/uploads/"
CL={"s":{"classes":["supreme"]},"d":{"classes":["district"]},"a":{"classes":["supreme","district","justice"]}}
H=r"^\s*RULE\s+(?P<num>\d+\.\d+)\.?[ ]*(?P<rest>(?:[A-Z][^.\n]{2,}?)?)\s*$"
O={"kind":"pdf","head":H,"titlewrap":True,"capswrap":True,"toctitles":True,"dropempty":True,"longestdup":True,"dropbracket":True}
R=[("2026/10/Civil-Procedure-Rules-10-01-26-1.pdf","Florida Rules of Civil Procedure","FRCP","civil_procedure","d"),
("2026/08/2027_01-JULY-Florida-Rules-of-General-Practice-and-Judicial-Administration-7-1-2026.pdf","Florida Rules of General Practice and Judicial Administration","FRGPJA","court_administration","a"),
("2026/10/2027_04-Oct-Criminal-Procedure-Rules-10-1-2026.pdf","Florida Rules of Criminal Procedure","FRCrP","criminal_procedure","d"),
("2024/01/Rules-Civil-Procedure-Involuntary-Commitment-Sexually-Violent-Predators1-1-2024.pdf","Florida Rules of Civil Procedure for Involuntary Commitment of Sexually Violent Predators","FRSVP","civil_procedure","d"),
("2026/10/Probate-Rules-10-15-26-1.pdf","Florida Probate Rules","FPR","probate","d"),
("2026/07/2026_7-JAN-Traffic-Court-Rules-01-01-2026.pdf","Florida Traffic Court Rules","FTCR","traffic","d"),
("2026/08/2026_01-JUL-Small-Claims-Rules-7-1-2026-1.pdf","Florida Small Claims Rules","FSCR","small_claims","d"),
("2026/09/2027_04-OCT-Florida-Rules-of-Juvenile-Procedure-10-1-2026.pdf","Florida Rules of Juvenile Procedure","FRJP","juvenile_procedure","d"),
("2026/10/Appellate-Court-Rules-10-01-26.pdf","Florida Rules of Appellate Procedure","FRAP","appellate_procedure","a"),
("2026/09/2027_04-OCT-Family-Law-Rules-of-Procedure-10-1-2026.pdf","Florida Family Law Rules of Procedure","FFLRP","family_procedure","d")]
SETS=[(B+f,n,a,fam,"statewide",CL[c],dict(O)) for f,n,a,fam,c in R]

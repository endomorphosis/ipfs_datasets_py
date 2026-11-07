ALL={"classes":["supreme","district","justice"]}
HEAD=r"^Sec\.\s+(?P<num>\d+[A-Za-z]?-\d+[A-Za-z]?(?:\.\d+)?)\.?[ ]*(?P<rest>.*)$"
SETS=[
 ("https://jud.ct.gov/Publications/PracticeBook/PB.pdf","Connecticut Practice Book (Superior Court Rules and Rules of Appellate Procedure)","CTPB","civil_and_criminal_procedure","statewide",ALL,
  {"kind":"pdf","head":HEAD,"titlewrap":True,"dropempty":True,"dropbracket":True,"longestdup":True,"cut_before":r"^Sec\. 1-1\.\s*$"}),
]

D={"classes":["district"]};S={"classes":["supreme"]};ALL={"classes":["supreme","district","justice"]}
SETS=[
 ("https://www.txcourts.gov/media/1462465/texas-rules-of-civil-procedure-march-1-2026.pdf","Texas Rules of Civil Procedure","TRCP","civil_procedure","statewide",D,{"kind":"pdf","capsfilter":True,"dropempty":True,"cut_before":r"^RULE 1\. OBJECTIVE OF RULES\s*$"}),
 ("https://www.txcourts.gov/media/1463134/texas-rules-of-appellate-procedure-02062026.pdf","Texas Rules of Appellate Procedure","TRAP","civil_and_criminal_procedure","statewide",S,{"kind":"pdf","pdfmode":"raw","head":r"^Rule\s+(?P<num>\d{1,2})\.[ ]*(?P<rest>[A-Z].*)$","titlewrap":True,"dropempty":True,"cut_before":r"^Rule 1\. Scope of Rule; Local"}),
 ("https://www.txcourts.gov/media/1463074/texas-rules-of-evidence-updated-with-amendments-effective-07022026.pdf","Texas Rules of Evidence","TRE","evidence","statewide",ALL,{"kind":"pdf","titlewrap":True,"dropempty":True}),
]

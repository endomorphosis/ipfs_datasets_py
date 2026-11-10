ALL={"classes":["supreme","district","justice"]}
HEAD=r"^(?:RULE|Rule)\s+(?P<num>\d+[A-Z]?:\d+(?:\.\d+)?[A-Za-z]?)(?:\.[ ]*|[ ]+(?=[A-Z][A-Z0-9 ,;:'’“”&\-()/]{3,}$)|(?=$))(?P<rest>.*)$"
SETS=[
 ("https://www.vacourts.gov/courts/scv/rulesofcourt.pdf","Rules of the Supreme Court of Virginia","VASCR","civil_and_criminal_procedure","statewide",ALL,{"kind":"pdf","head":HEAD,"dropempty":True,"cut_before":r"^Rule 1:1\.? "}),
]

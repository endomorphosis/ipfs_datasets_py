ALL={"classes":["supreme","district","justice"]}
BARE=r"^(?:RULE|Rule)\s+(?P<num>\d+(?:\.\d+)?[A-Za-z]?)\.?[ ]*(?P<rest>(?:[A-Z][A-Z0-9 ,;:'’&\-()/]{3,})?)$"
SETS=[("https://kscourts.gov/KSCourts/media/KsCourts/Rules/2026-RuleBook.pdf","Kansas Supreme Court Rules","KSSCR","civil_and_criminal_procedure","statewide",ALL,{"kind":"pdf","head":BARE,"titlewrap":True,"dropempty":True,"longestdup":True,"dropbracket":True})]

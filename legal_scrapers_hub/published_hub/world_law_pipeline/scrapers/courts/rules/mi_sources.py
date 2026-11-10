ALL={"classes":["supreme","district","justice"]}
SETS=[("https://www.courts.michigan.gov/siteassets/rules-instructions-administrative-orders/michigan-court-rules/michigan-court-rules.pdf","Michigan Court Rules","MCR","civil_and_criminal_procedure","statewide",ALL,
 {"kind":"pdf","head":r"^Rule\s+(?P<num>\d+\.\d+)(?:\.[ ]*|[ ]+)(?P<rest>[A-Z].*)$","titlewrap":True,"dropempty":True,"longestdup":True,"dropbracket":True,"cut_before":r"^Rule 1\.101 Title; Citation\s*$"})]

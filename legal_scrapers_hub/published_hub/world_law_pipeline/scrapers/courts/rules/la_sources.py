D=r"^Rule\s+(?P<num>\d+\.\d+)\s*(?P<rest>(?:[A-Z][A-Z0-9 ,;:'’&\-()/]{3,})?)$"
S=r"^RULE\s+(?P<num>[IVXL]+)\.\s*(?P<rest>[A-Z].*)$"
O={"kind":"pdf","titlewrap":True,"capswrap":True,"dropempty":True,"longestdup":True,"dropbracket":True}
SETS=[("https://www.lasc.org/rules/dist.ct/finalrules.pdf","Rules for Louisiana District Courts, Juvenile Courts and Family Law Proceedings","LADCR","local_court_rules","statewide",{"classes":["district"]},dict(O,head=D)),
("https://www.lasc.org/rules/orders/2025/Rules_I-XII_XIV_and_XLII.pdf","Louisiana Supreme Court Rules (Rules I-XII, XIV, XLII)","LASCR","court_rules","statewide",{"classes":["supreme","district","justice"]},dict(O,head=S))]

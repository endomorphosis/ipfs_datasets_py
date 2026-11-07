ALL={"classes":["supreme","district","justice"]}
H=r"^\s*SCR\s+(?P<num>\d+\.\d+[A-Za-z]?)\s+(?P<rest>[A-Z].*)$"
CH=[10, 11, 12, 13, 14, 21, 22, 23, 30, 31, 32, 33, 35, 40, 50, 60, 61, 62, 63, 68, 70, 71, 72, 73, 74, 75, 80, 81, 82, 98]
SETS=[(f"https://www.wicourts.gov/sc/rules/chap{n}.pdf",f"Wisconsin Supreme Court Rules, Chapter {n}",f"SCR{n}","court_rules","statewide",({"classes":["supreme"]} if n in (10,11,12,13,14,21,22,23,30,31,32,33,35,36,40,50) else ALL),{"kind":"pdf","head":H,"dropempty":True,"longestdup":True,"dropbracket":True}) for n in CH]

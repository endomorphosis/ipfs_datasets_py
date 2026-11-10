import json,os
P=json.load(open(os.path.dirname(os.path.abspath(__file__))+"/ny_parts.json"))
H=r"^Section\s+(?P<num>\d+\.\d+(?:-[a-z]+)?)\s+(?!to\s\d)(?P<rest>[A-Za-z\[].*)$"
NM={200:"Part 200: Uniform Rules for the New York State Trial Courts - Rules Applicable to All Courts (Criminal)",202:"Part 202: Uniform Civil Rules for the Supreme Court and the County Court",205:"Part 205: Uniform Rules for the Family Court"}
ALL={"classes":["district","justice"]}
SETS=[(f"https://www.nycourts.gov/rules/{sec}/{n}.shtml",f"New York Uniform Rules for the Trial Courts, {NM.get(n,'Part '+str(n))}",f"NYPART{n}","local_court_rules","statewide",({"classes":["district"]} if n!=200 else ALL),{"head":H,"dropempty":True,"longestdup":True,"dropbracket":True,"droptitlebr":True,"dropdots":True}) for n,sec in P]

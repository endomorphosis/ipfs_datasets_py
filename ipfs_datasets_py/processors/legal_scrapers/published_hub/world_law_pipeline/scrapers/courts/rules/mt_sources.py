U="https://courts.mt.gov/external/rules/"
CL={"s":{"classes":["supreme"]},"d":{"classes":["district"]},"j":{"classes":["justice"]},"a":{"classes":["supreme","district","justice"]}}
O={"kind":"pdf","titlewrap":True,"dropempty":True,"longestdup":True,"dropbracket":True}
R=[("civ_proc","Montana Rules of Civil Procedure","MRCP","civil_procedure","d"),
("mtr_app_pro","Montana Rules of Appellate Procedure","MRAP","appellate_procedure","s"),
("mtr_evid","Montana Rules of Evidence","MRE","evidence","a"),
("jp_cty_rules_civ_pro","Montana Justice and City Court Rules of Civil Procedure","MJCRCP","civil_procedure","j"),
("unif_rules_jp_cty","Montana Uniform Rules of the Justice and City Courts","MURJC","local_rules","j"),
("muni_crt_rules_dc_app","Montana Uniform Municipal Court Rules of Appeal to District Court","MMCRA","appellate_procedure","d")]
SETS=[(U+f+".pdf",n,a,fam,"statewide",CL[c],dict(O)) for f,n,a,fam,c in R]

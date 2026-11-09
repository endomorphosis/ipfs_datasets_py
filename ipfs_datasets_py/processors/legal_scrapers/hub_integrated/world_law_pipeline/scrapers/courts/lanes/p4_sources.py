# Phase 4 source seeds: Americas + Oceania (see PLAN.md). (jurisdiction, level, name, url, data_types)
BR_STATES={"AC":"tjac","AL":"tjal","AP":"tjap","AM":"tjam","BA":"tjba","CE":"tjce","DF":"tjdft","ES":"tjes","GO":"tjgo","MA":"tjma","MT":"tjmt","MS":"tjms","MG":"tjmg","PA":"tjpa","PB":"tjpb","PR":"tjpr","PE":"tjpe","PI":"tjpi","RJ":"tjrj","RN":"tjrn","RS":"tjrs","RO":"tjro","RR":"tjrr","SC":"tjsc","SP":"tjsp","SE":"tjse","TO":"tjto"}
MX_STATES={"AGS":"poderjudicialags","BC":"pjbc","BCS":"tsjbcs","CAM":"poderjudicialcampeche","CHP":"poderjudicialchiapas","CHH":"stj","CMX":"poderjudicialcdmx","COA":"pjecz","COL":"stjcolima","DUR":"tsjdgo","MEX":"pjedomex","GTO":"poderjudicial-gto","GRO":"tsj-guerrero","HGO":"pjhidalgo","JAL":"stjjalisco","MIC":"poderjudicialmichoacan","MOR":"tsjmorelos","NAY":"tsjnay","NLE":"pjenl","OAX":"tribunaloax","PUE":"htsjpuebla","QRO":"tsjqro","ROO":"tsjqroo","SLP":"stjslp","SIN":"stjsin","SON":"stjsonora","TAB":"tsj-tabasco","TAM":"pjetam","TLA":"tsjtlaxcala","VER":"pjeveracruz","YUC":"poderjudicialyucatan","ZAC":"tsjzac"}
DT_ALL="locations;judges;forms;rules"
S=[]
# 1. Oklahoma
S+=[("US-OK","state","Oklahoma oklahomacourts.gov","https://oklahomacourts.gov/","locations;judges;forms;rules"),
    ("US-OK","local","Oklahoma OSCN court locations (Wayback)","https://www.oscn.net/applications/oscn/","locations;rules;forms")]
# 2. Brazil
S+=[("BR","national","Brazil STF","https://portal.stf.jus.br/",DT_ALL),("BR","national","Brazil STJ","https://www.stj.jus.br/",DT_ALL),("BR","national","Brazil TST","https://www.tst.jus.br/",DT_ALL),
    ("BR","national","Brazil TSE","https://www.tse.jus.br/",DT_ALL),("BR","national","Brazil STM","https://www.stm.jus.br/",DT_ALL),("BR","national","Brazil CNJ court lists","https://www.cnj.jus.br/",DT_ALL)]
S+=[("BR","national",f"Brazil TRF{i}",f"https://www.trf{i}.jus.br/",DT_ALL) for i in range(1,7)]
S+=[(f"BR-{uf}","state",f"Brazil {h.upper()} (Tribunal de Justica {uf})",f"https://www.{h}.jus.br/",DT_ALL) for uf,h in BR_STATES.items()]
# 3. Mexico
S+=[("MX","national","Mexico SCJN","https://www.scjn.gob.mx/",DT_ALL),("MX","national","Mexico CJF / federal circuits","https://www.cjf.gob.mx/",DT_ALL),
    ("MX","national","Mexico Poder Judicial de la Federacion","https://www.pjf.gob.mx/",DT_ALL),("MX","national","Mexico TEPJF","https://www.te.gob.mx/",DT_ALL)]
S+=[(f"MX-{k}","state",f"Mexico Poder Judicial {k}",f"https://www.{h}.gob.mx/",DT_ALL) for k,h in MX_STATES.items()]
# 4. Other LatAm / Caribbean
L=[("AR","Argentina CSJN","https://www.csjn.gov.ar/"),("AR","Argentina PJN","https://www.pjn.gov.ar/"),("CL","Chile Poder Judicial","https://www.pjud.cl/"),("CL","Chile Corte Suprema","https://www.pjud.cl/corte-suprema"),
 ("CO","Colombia Rama Judicial","https://www.ramajudicial.gov.co/"),("CO","Colombia Corte Suprema","https://www.cortesuprema.gov.co/"),("CO","Colombia Corte Constitucional","https://www.corteconstitucional.gov.co/"),("CO","Colombia Consejo de Estado","https://www.consejodeestado.gov.co/"),
 ("PE","Peru Poder Judicial","https://www.pj.gob.pe/"),("PE","Peru Tribunal Constitucional","https://www.tc.gob.pe/"),("UY","Uruguay Poder Judicial","https://www.poderjudicial.gub.uy/"),("PY","Paraguay Poder Judicial","https://www.pj.gov.py/"),
 ("BO","Bolivia Tribunal Supremo","https://www.tsj.bo/"),("EC","Ecuador Funcion Judicial","https://www.funcionjudicial.gob.ec/"),("VE","Venezuela TSJ","http://www.tsj.gob.ve/"),("CR","Costa Rica Poder Judicial","https://www.poder-judicial.go.cr/"),
 ("PA","Panama Organo Judicial","https://www.organojudicial.gob.pa/"),("GT","Guatemala Organismo Judicial","https://www.oj.gob.gt/"),("SV","El Salvador CSJ","https://www.csj.gob.sv/"),("HN","Honduras Poder Judicial","https://www.poderjudicial.gob.hn/"),
 ("NI","Nicaragua Poder Judicial","https://www.poderjudicial.gob.ni/"),("DO","Dominican Republic Poder Judicial","https://www.poderjudicial.gob.do/"),("CU","Cuba Tribunal Supremo Popular","https://www.tsp.gob.cu/"),
 ("INT","Inter-American Court of Human Rights","https://www.corteidh.or.cr/"),("INT","Caribbean Court of Justice","https://ccj.org/"),("INT","Eastern Caribbean Supreme Court","https://www.eccourts.org/"),
 ("JM","Jamaica Courts","https://www.courtsja.gov.jm/"),("TT","Trinidad and Tobago Judiciary","https://www.ttlawcourts.org/"),("BB","Barbados Judiciary","https://www.barbadoslawcourts.gov.bb/"),("BS","Bahamas Judiciary","https://www.bahamasjudiciary.com/"),
 ("BZ","Belize Judiciary","https://www.belizejudiciary.org/"),("GY","Guyana Judiciary","https://www.judiciary.gy/"),("SR","Suriname Hof van Justitie","https://www.rechtspraak.sr/"),("KY","Cayman Islands Judicial","https://www.judicial.ky/"),("BM","Bermuda Judiciary","https://www.court.gov.bm/")]
S+=[(j,"national",n,u,DT_ALL) for j,n,u in L]
# 5. Pacific
P=[("FJ","Fiji Judiciary","https://www.judiciary.gov.fj/"),("PG","Papua New Guinea Judiciary","https://www.pngjudiciary.gov.pg/"),("WS","Samoa Judiciary","https://www.judiciary.ws/"),("TO","Tonga Judiciary","https://www.judiciary.gov.to/"),
 ("VU","Vanuatu Judiciary","https://www.judiciary.gov.vu/"),("SB","Solomon Islands Judiciary","https://www.courts.gov.sb/"),("KI","Kiribati Judiciary","https://www.judiciary.gov.ki/"),("PW","Palau Judiciary","https://www.palaujudiciary.net/"),
 ("FM","FSM Supreme Court","https://www.fsmsupremecourt.org/"),("MH","Marshall Islands Judiciary","https://www.rmicourts.org/"),("CK","Cook Islands Ministry of Justice","https://www.justice.gov.ck/"),("NR","Nauru Judiciary","https://www.naurugov.nr/"),
 ("TV","Tuvalu Judiciary","https://www.tuvalu.tv/"),("PACLII","PacLII (metadata only if terms allow)","https://www.paclii.org/")]
S+=[(j,"national",n,u,DT_ALL) for j,n,u in P]

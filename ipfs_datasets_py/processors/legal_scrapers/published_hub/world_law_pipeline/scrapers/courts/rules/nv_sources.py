B="https://www.leg.state.nv.us/Division/Legal/LawLibrary/CourtRules/"
CLARK="32003";WASHOE="32031"
DIST={"First":["32510","32029"],"Second":[WASHOE],"Third":["32019"],"Fourth":["32007"],"Fifth":["32009","32023"],"Sixth":["32013"],"Seventh":["32011","32017","32033"],"Eighth":[CLARK],"Ninth":["32005"],"Tenth":["32001"],"Eleventh":["32015","32021","32027"]}
D={"classes":["district"]};J={"classes":["justice"]};S={"classes":["supreme"]};ALL={"classes":["supreme","district","justice"]}
SETS=[
 ("NRCP.html","Nevada Rules of Civil Procedure","NRCP","civil_procedure","statewide",D),
 ("NRCrP.html","Nevada Rules of Criminal Practice","NRCrP","criminal_procedure","statewide",D),
 ("NSTR.html","Nevada Short Trial Rules","NSTR","civil_procedure","statewide",D),
 ("NATR.html","Nevada Alternate Trial Rules","NATR","civil_procedure","statewide",D),
 ("RGADR.html","Rules Governing Alternative Dispute Resolution","RGADR","civil_procedure","statewide",D),
 ("FMR.html","Foreclosure Mediation Rules","FMR","civil_procedure","statewide",D),
 ("Guardianship.html","Statewide Rules for Guardianship","SRG","civil_procedure","statewide",D),
 ("NEFCR.html","Nevada Electronic Filing and Conversion Rules","NEFCR","civil_and_criminal_procedure","statewide",ALL),
 ("DCR.html","Rules of the District Court of the State of Nevada","DCR","civil_and_criminal_procedure","statewide",D),
 ("JCRCP.html","Justice Court Rules of Civil Procedure","JCRCP","civil_procedure","statewide",J),
 ("Civil_Traffic_Infractions.html","Justice and Municipal Court Rules for Civil Traffic Infractions","JMCRCTI","civil_procedure","statewide",{"classes":["justice","municipal"]}),
 ("NRAP.html","Nevada Rules of Appellate Procedure","NRAP","civil_and_criminal_procedure","statewide",S),
 ("SCR.html","Supreme Court Rules (Parts I-V)","SCR","civil_and_criminal_procedure","statewide",S),
 ("SCR_RGSRCR.html","Rules Governing Sealing and Redacting Court Records","SRCR","civil_and_criminal_procedure","statewide",ALL),
 ("SCR_AudTranEquip.html","Rules Governing Appearance by Audiovisual Transmission Equipment","AVTE","civil_and_criminal_procedure","statewide",ALL),
 ("SCR_Fees.html","Rules Governing the Collection of Fees and Charges","SCRFEES","civil_and_criminal_procedure","statewide",ALL),
 ("SCR_REE.html","Rules Pertaining to Exhibits Marked and/or Admitted Into Evidence","REE","civil_and_criminal_procedure","statewide",ALL),
 ("PCD.html","Policy for Handling Filed, Lodged, and Presumptively Confidential Documents","PCD","civil_and_criminal_procedure","statewide",ALL),
 ("NRAD.html","Nevada Rules on the Administrative Docket","NRAD","civil_and_criminal_procedure","statewide",S,{"head":r"^Section\s+(?P<num>\d+)\.[ ]*(?P<rest>.*)$","dropshort":False}),
 ("SecondDCR_Crim.html","Criminal Rules of Practice for the Second Judicial District Court","2JDC-CR","local_court_rules","local",{"classes":["district"],"fips":DIST["Second"],"name_re":"second judicial|washoe"}),
]
for n in ["First","Second","Third","Fourth","Seventh","Eighth","Ninth","Tenth","Eleventh"]:
    SETS.append((f"{n}DCR.html",f"Rules of Practice for the {n} Judicial District Court of the State of Nevada",{"First":"1JDCR","Second":"2JDCR","Third":"3JDCR","Fourth":"4JDCR","Seventh":"7JDCR","Eighth":"EDCR","Ninth":"9JDCR","Tenth":"10JDCR","Eleventh":"11JDCR"}[n],"local_court_rules","local",{"classes":["district"],"fips":DIST[n],"name_re":f"{n.lower()} judicial"}))
SETS+=[
 ("JCR_Henderson.html","Local Rules of Practice for the Justice Court of Henderson Township","HJCR","local_court_rules","local",{"classes":["justice"],"fips":[CLARK],"name_re":"henderson"}),
 ("JCR_LVTownship.html","Justice Court of Las Vegas Township - Justice Court Rules of Las Vegas Township","LVJCR-T","local_court_rules","local",{"classes":["justice"],"fips":[CLARK],"name_re":"las vegas|regional justice center"}),
 ("JCR_LV.html","Justice Court of Las Vegas Township - Las Vegas Justice Court Local Rules of Practice","LVJCR","local_court_rules","local",{"classes":["justice"],"fips":[CLARK],"name_re":"las vegas|regional justice center"}),
 ("JCR_NLV.html","Local Rules of Practice for the Justice Court of North Las Vegas Township","NLVJCR","local_court_rules","local",{"classes":["justice"],"fips":[CLARK],"name_re":"north las vegas"}),
 ("JCR_Pahrump.html","Local Rules of Practice for the Justice Court of Pahrump Township","PJCR","local_court_rules","local",{"classes":["justice"],"fips":["32023"],"name_re":"pahrump"}),
 ("JCR_Reno.html","Local Rules of Practice for the Justice Court of Reno Township","RJCR","local_court_rules","local",{"classes":["justice"],"fips":[WASHOE],"name_re":"reno|washoe"}),
 ("JCR_Rural.html","Local Rules of Practice for the Rural Justice Courts in the State of Nevada","RURJCR","local_court_rules","local",{"classes":["justice"],"fips_exclude":[CLARK,WASHOE,"32023"]}),
]

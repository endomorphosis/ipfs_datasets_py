import csv
S="ipfs_datasets_py_fresh/.../legal_scrapers/state_scrapers/"
R="repo-scraper"
us=[("AL","Alabama","https://alison.legislature.state.al.us/code-of-alabama","GraphQL API","alabama.py (+_section,_constitution)","",1),
("AK","Alaska","https://www.akleg.gov/basis/statutes.asp","HTML","alaska.py","",1),
("AZ","Arizona","https://www.azleg.gov/arstitle/","HTML","arizona.py","",1),
("AR","Arkansas","https://arkleg.state.ar.us (code hosted by LexisNexis)","Lexis HTML/JS","arkansas.py, arkansas_lexis.py","RESTRICTIVE: LexisNexis public-access ToS (no bulk/automated); official code copyright claims",3),
("CA","California","https://leginfo.legislature.ca.gov/faces/codes.xhtml; bulk: downloads.leginfo.legislature.ca.gov","HTML + bulk zip","california.py, california_bulk.py","bulk download preferred",1),
("CO","Colorado","https://leg.colorado.gov/colorado-revised-statutes","PDF/HTML (C.R.S. Lexis-hosted online)","colorado.py, colorado_title.py","RESTRICTIVE-ish: C.R.S. copyright by State; Lexis-hosted browse ToS",2),
("CT","Connecticut","https://www.cga.ct.gov/current/pub/titles.htm","HTML","connecticut.py, connecticut_chapter.py","",1),
("DE","Delaware","https://delcode.delaware.gov","HTML","delaware.py, delaware_chapter.py","",1),
("FL","Florida","http://www.leg.state.fl.us/statutes/","HTML","florida.py, florida_chapter.py","",1),
("GA","Georgia","https://www.legis.ga.gov (O.C.G.A. via LexisNexis)","Lexis HTML/JS","georgia.py, georgia_lexis.py, georgia_archive.py","RESTRICTIVE: Lexis ToS; note Georgia v. Public.Resource.Org (2020) annotations not copyrightable",3),
("HI","Hawaii","https://www.capitol.hawaii.gov/hrscurrent/","HTML","hawaii.py, hawaii_section.py","",1),
("ID","Idaho","https://legislature.idaho.gov/statutesrules/idstat/","HTML","idaho.py, idaho_section.py","",1),
("IL","Illinois","https://www.ilga.gov/legislation/ilcs/ilcs.asp","HTML + bulk","illinois.py, illinois_bulk.py","",1),
("IN","Indiana","https://iga.in.gov/laws/2026/ic/titles/","JSON/PDF","indiana.py, indiana_bulk.py","",1),
("IA","Iowa","https://www.legis.iowa.gov/law/iowaCode","XML/PDF","iowa.py, iowa_chapter_xml.py","",1),
("KS","Kansas","https://www.kslegislature.gov/li/statute/","HTML","kansas.py, kansas_section.py","",1),
("KY","Kentucky","https://apps.legislature.ky.gov/law/statutes/","PDF per section","kentucky.py, kentucky_section.py","",2),
("LA","Louisiana","https://legis.la.gov/legis/LawSearch.aspx","HTML","louisiana.py, louisiana_law.py","",2),
("ME","Maine","https://legislature.maine.gov/statutes/","HTML","maine.py, maine_section.py","",1),
("MD","Maryland","https://mgaleg.maryland.gov/mgawebsite/Laws/Statutes","HTML","maryland.py, maryland_section.py","",1),
("MA","Massachusetts","https://malegislature.gov/Laws/GeneralLaws","HTML","massachusetts.py, massachusetts_section.py","",1),
("MI","Michigan","https://legislature.mi.gov","HTML/XML","michigan.py, michigan_chapter_xml.py","",1),
("MN","Minnesota","https://www.revisor.mn.gov/statutes/","HTML","minnesota.py, minnesota_section.py","",1),
("MS","Mississippi","http://www.legislature.ms.gov (code via LexisNexis)","Lexis HTML/JS","mississippi.py, mississippi_lexis.py","RESTRICTIVE: Lexis ToS",3),
("MO","Missouri","https://revisor.mo.gov/main/Home.aspx","HTML","missouri.py, missouri_chapter.py","",1),
("MT","Montana","https://leg.mt.gov/bills/mca/","HTML","montana.py, montana_section.py","",1),
("NE","Nebraska","https://nebraskalegislature.gov/laws/browse-chapters.php","HTML","nebraska.py, nebraska_section.py","",1),
("NV","Nevada","https://www.leg.state.nv.us/NRS/","HTML","nevada.py, nevada_chapter.py","",1),
("NH","New Hampshire","https://gc.nh.gov/rsa/html/NHTOC.htm","HTML","new_hampshire.py, new_hampshire_section.py","",1),
("NJ","New Jersey","https://lis.njleg.state.nj.us (bulk statutes)","HTML + bulk","new_jersey.py, new_jersey_bulk.py","",1),
("NM","New Mexico","https://nmonesource.com (NMOneSource)","HTML","new_mexico.py, new_mexico_chapter.py","CHECK: NMOneSource ToS (Compilation Commission copyright)",2),
("NY","New York","https://legislation.nysenate.gov (OpenLegislation API)","JSON API (free key)","new_york.py, new_york_openleg.py, new_york_law_pdf.py","API key required; NYS Senate ToS",1),
("NC","North Carolina","https://www.ncleg.gov/Laws/GeneralStatutes","HTML/PDF","north_carolina.py, north_carolina_chapter.py","",1),
("ND","North Dakota","https://www.ndlegis.gov/general-information/north-dakota-century-code","PDF","north_dakota.py, north_dakota_chapter.py","",1),
("OH","Ohio","https://codes.ohio.gov","HTML","ohio.py, ohio_chapter.py","",1),
("OK","Oklahoma","https://www.oklegislature.gov/osstatuestitle.html (OSCN)","HTML/RTF","oklahoma.py, oklahoma_title.py","",2),
("OR","Oregon","https://www.oregonlegislature.gov/bills_laws/Pages/ORS.aspx","HTML","oregon.py, oregon_chapter.py (+admin rules, session laws)","ORS copyright claim by Legislative Counsel (case law contested)",2),
("PA","Pennsylvania","https://www.legis.state.pa.us (Consolidated Statutes)","HTML","pennsylvania.py, pennsylvania_title.py","Unconsolidated statutes incomplete",2),
("RI","Rhode Island","https://webserver.rilegislature.gov/Statutes/","HTML","rhode_island.py, rhode_island_section.py","",1),
("SC","South Carolina","https://www.scstatehouse.gov/code/statmast.php","HTML","south_carolina.py, south_carolina_chapter.py","Site notice: unofficial, copyright SC Legislative Council",1),
("SD","South Dakota","https://sdlegislature.gov/Statutes","JSON API/HTML","south_dakota.py, south_dakota_title.py","",1),
("TN","Tennessee","https://www.tn.gov/tga/statutes.html (Lexis)","Lexis HTML/JS","tennessee.py, tennessee_lexis.py","RESTRICTIVE: Lexis ToS",3),
("TX","Texas","https://statutes.capitol.texas.gov/","HTML + bulk zip","texas.py, texas_chapter.py","bulk zip preferred",1),
("UT","Utah","https://le.utah.gov/xcode/","XML","utah.py, utah_title_xml.py","",1),
("VT","Vermont","https://legislature.vermont.gov/statutes/","HTML","vermont.py, vermont_section.py","",1),
("VA","Virginia","https://law.lis.virginia.gov","HTML/CSV/API","virginia.py, virginia_csv.py, virginia_section.py","",1),
("WA","Washington","https://app.leg.wa.gov/RCW/","HTML","washington.py, washington_section.py","",1),
("WV","West Virginia","https://code.wvlegislature.gov","HTML","west_virginia.py, west_virginia_dump.py","",1),
("WI","Wisconsin","https://docs.legis.wisconsin.gov/statutes","HTML/PDF","wisconsin.py, wisconsin_chapter.py","",1),
("WY","Wyoming","https://www.wyoleg.gov/statutes/compress/","zip/PDF","wyoming.py, wyoming_title.py","",1),
("DC","District of Columbia","https://code.dccouncil.gov (github.com/DCCouncil/law-xml)","XML on GitHub","district_of_columbia.py, district_of_columbia_xml.py","CC0/public domain; best source",1),
("PR","Puerto Rico","https://bvirtualogp.pr.gov","PDF/HTML","puerto_rico.py, puerto_rico_ogp.py","Spanish",2),
("GU","Guam","https://www.guamcourts.org/CompilerofLaws/","PDF","none (generic.py)","",3),
("VI","US Virgin Islands","https://law.justia.com/codes/virgin-islands/ (no free official)","HTML","none","RESTRICTIVE: official code LexisNexis; Justia ToS",4),
("MP","Northern Mariana Islands","https://cnmilaw.org","HTML/PDF","none","",3),
("AS","American Samoa","https://new.asbar.org/code-annotated/","HTML","none","",3)]
ca=[("ON","Ontario","https://www.ontario.ca/laws","HTML/API","none","Open Government Licence–Ontario; Crown copyright",1),
("QC","Quebec","https://www.legisquebec.gouv.qc.ca","HTML/XML (fr/en)","none","Reproduction permitted non-commercial; check",1),
("BC","British Columbia","https://www.bclaws.gov.bc.ca (CiviX API)","XML API","none","King's Printer licence (free reuse)",1),
("AB","Alberta","https://kings-printer.alberta.ca","PDF/HTML","none","King's Printer copyright; check",2),
("MB","Manitoba","https://web2.gov.mb.ca/laws/","HTML/PDF","none","",2),
("SK","Saskatchewan","https://publications.saskatchewan.ca","PDF","none","",2),
("NS","Nova Scotia","https://nslegislature.ca/legc/","HTML","none","",2),
("NB","New Brunswick","https://laws.gnb.ca","HTML (fr/en)","none","",2),
("NL","Newfoundland and Labrador","https://www.assembly.nl.ca/legislation/","HTML","none","",2),
("PE","Prince Edward Island","https://www.princeedwardisland.ca/en/legislation","PDF","none","",2),
("YT","Yukon","https://laws.yukon.ca","PDF/HTML","none","",3),
("NT","Northwest Territories","https://www.justice.gov.nt.ca/en/legislation/","PDF","none","",3),
("NU","Nunavut","https://www.nunavutlegislation.ca","PDF","none","",3)]
au=[("NSW","New South Wales","https://legislation.nsw.gov.au","HTML/XML/API","none","CC BY 4.0",1),
("VIC","Victoria","https://www.legislation.vic.gov.au","HTML/Word/PDF","none","CC BY 4.0",1),
("QLD","Queensland","https://www.legislation.qld.gov.au","HTML/XML","none","CC BY 4.0",1),
("WA","Western Australia","https://www.legislation.wa.gov.au","HTML/PDF","none","Crown copyright; check",1),
("SA","South Australia","https://www.legislation.sa.gov.au","HTML/RTF/PDF","none","CC BY 4.0",1),
("TAS","Tasmania","https://www.legislation.tas.gov.au","HTML/XML","none","CC BY 4.0",1),
("ACT","Australian Capital Territory","https://www.legislation.act.gov.au","HTML/PDF/RTF","none","CC BY 4.0",1),
("NT","Northern Territory","https://legislation.nt.gov.au","HTML/PDF","none","",2)]
inst="Andhra Pradesh,Arunachal Pradesh,Assam,Bihar,Chhattisgarh,Goa,Gujarat,Haryana,Himachal Pradesh,Jharkhand,Karnataka,Kerala,Madhya Pradesh,Maharashtra,Manipur,Meghalaya,Mizoram,Nagaland,Odisha,Punjab,Rajasthan,Sikkim,Tamil Nadu,Telangana,Tripura,Uttar Pradesh,Uttarakhand,West Bengal".split(",")
ut="Andaman and Nicobar Islands,Chandigarh,Dadra and Nagar Haveli and Daman and Diu,Delhi,Jammu and Kashmir,Ladakh,Lakshadweep,Puducherry".split(",")
hi={"Maharashtra","Karnataka","Tamil Nadu","Kerala","Delhi","Gujarat","Uttar Pradesh","West Bengal","Telangana"}
rows=[]
for c,n,u,f,s,t,p in us: rows.append(["US",c,n,"state/territory",u,f,s,t,p])
for c,n,u,f,s,t,p in ca: rows.append(["CA",c,n,"province/territory",u,f,s,t,p])
for c,n,u,f,s,t,p in au: rows.append(["AU",c,n,"state/territory",u,f,s,t,p])
for n in inst+ut:
  rows.append(["IN","",n,"state" if n in inst else "union territory","https://www.indiacode.nic.in (State Acts section); plus state law dept / gazette sites","HTML + PDF (DSpace)","none","India Code: GoI content, reuse w/ attribution; heavy PDFs; check robots",1 if n in hi else 2])
w=csv.writer(open("sources.csv","w",newline=""))
w.writerow(["country","code","subdivision","type","official_source_urls","format_access","ipfs_datasets_py_scraper","terms_robots_notes","priority"])
w.writerows(rows); print(len(rows))

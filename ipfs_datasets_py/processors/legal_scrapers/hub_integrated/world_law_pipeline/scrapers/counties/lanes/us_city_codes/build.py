# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
_CITY = _ipfs_Path(_ipfs_os.environ.get("US_CITY_CODES_ROOT", str(_LEGAL_WS / "us_city_codes")))
import json,csv,collections
c=json.load(open(str(_CITY/'raw'/'cand_seed.json'))); t=json.load(open(str(_CITY/'raw'/'covered_table2.json')))
cur=[
('District of Columbia (DC Code)','DC','state_equivalent','https://github.com/DCCouncil/law-xml','official_github (CC0 XML)','yes (City of Washington DC in AML; verify it is the DC Code)','no','Official Council repo, CC0; code.dccouncil.gov robots has ai-train=no signal but the CC0 repo is the cleaner source'),
('New York City (Admin Code)','NY','city','http://files.amlegal.com/pdffiles/NewYorkCity/Admin/XML.zip','amlegal bulk XML (public file)','yes (City of New York in AML)','partial','Public bulk XML ZIP per BetaNYC repo; AmLegal robots ai-train=no; alt: https://github.com/BetaNYC/nyc-charter-laws-rules; use only as freshness cross-check'),
('San Diego (Municipal Code)','CA','city','https://www.sandiego.gov/city-clerk/officialdocs/municipal-code','official_city_site (chapter pages/PDF) + municode.sandiego.gov viewer','yes (City of San Diego in AML)','no (check robots)','Official City Clerk source; alt to refresh/verify AML copy'),
('Portland (City Code)','OR','city','https://www.portland.gov/code','official_city_site (HTML)','yes (City of Portland in AML)','no (check robots)','Official Council Clerk HTML by title; printable full-title versions; alt/freshness source'),
('Honolulu (Revised Ordinances)','HI','consolidated_city_county','https://www.honolulu.gov/ocs/revised-ordinances-of-honolulu/','official_city_site (HTML/PDF)','yes (City and County of Honolulu in AML)','no (check robots)','Hard copy is authoritative; AmLegal also hosts; alt source'),
('Massachusetts cities and towns (directory)','MA','state_hosted_directory','https://www.mass.gov/law-library/massachusetts-city-town-ordinances-and-bylaws','state_directory (Trial Court Law Libraries)','partial (177 MA places in AML of ~351)','no (check robots)','Alphabetical pages A-C ... T-Z link to each town bylaw/ordinance; use to find remaining MA towns'),
('Massachusetts AG Municipal Law Unit (approved by-laws)','MA','state_hosted_collection','https://massago.hylandcloud.com/231publicaccess/MLU.html','state_collection (decision lookup)','no','unknown (public-access app; do not bulk without review)','Approved/disapproved town by-law decisions by town; amendments rather than full codes'),
('Alaska municipalities (Municipal Code Library)','AK','state_hosted_directory','https://www.commerce.alaska.gov/web/dcra/LocalGovernmentResourceDesk/MunicipalCodeLibrary','state_directory (DCRA)','partial (35 AK places in AML)','no (check robots)','Links to codes for boroughs/cities; informational; AML covers 35 of ~165 AKML members'),
('Texas city codes directory','TX','directory','https://tarlton.law.utexas.edu/texas-web-resources/local-laws-city-codes','university_law_library_directory','partial (724 TX places in AML)','no (check robots)','Pointer list; Sterling Codifiers / Franklin Legal / Municode TX many small cities'),
('Library of Congress municipal codes guide','US','directory','https://guides.loc.gov/municipal-codes/current-municipal-codes','federal_library_directory','n/a','no (check robots)','Pointer list of current municipal code hosts'),
('Washington cities (MRSC city code directory)','WA','directory','https://mrsc.org/research-tools/washington-city-and-town-profiles','directory','n/a','yes: robots.txt Disallow / for generic agents; not scraped','Use manually only; not used to build candidates'),
('Platform: encodeplus.com (Quality Code/Encode+)','US','platform','https://www.encodeplus.com/','encodeplus','partial','no: robots only blocks wp-admin/cgi-bin','Open robots; need customer list from sitemap (sitemap_index.xml) to enumerate jurisdictions'),
('Platform: municipalcodeonline.com (CivicPlus)','US','platform','https://municipalcodeonline.com/','civicplus_municipalcodeonline','partial (13+ in AML)','not verified (connection errors earlier)','Per-city subdomains; AML already has a collector; ready_unscraped includes Sigurd UT'),
('Platform: municipal.codes / codepublishing.com','US','platform','https://municipal.codes/','municipal.codes (Code Publishing/General Code)','partial (209 of 223 deferred already migrated to eCode360)','partial: robots ai-train=no; codepublishing.com robots disallows search/PDF','Being migrated to eCode360; low value for new scraping'),
('Platform: qcode.us / franklinlegal.net','US','platform','https://www.qcode.us/','qcode.us / franklin_legal','no','yes: Cloudflare 301 on robots.txt','Do not attempt; note as gated'),
]
rows=[]
for r in cur: rows.append(dict(zip(['jurisdiction','state','type','source_url','platform','already_covered','gated','notes'],r)))
new=[o for o in c if o['already_covered']=='no' and o['type']!='cdp_statistical']
cov=[o for o in c if o['already_covered']!='no']
cdp=[o for o in c if o['type']=='cdp_statistical']
def k(o): return (0 if o['platform'] not in('official_site','unknown') else 1 if o['source_url'] else 2, o['state'] or 'ZZ', o['jurisdiction'])
rows+=sorted(new,key=k)+sorted(cov,key=k)+cdp
with open('sources_candidates.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['jurisdiction','state','type','source_url','platform','already_covered','gated','notes']); w.writeheader(); w.writerows(rows)
print(len(rows),len(new),len(cov))
nm=[o for o in new if o['type']=='municipality']; nc=[o for o in new if o['type']=='county']
print('munis',len(nm),'with url',sum(1 for o in nm if o['source_url']),'with url+state',sum(1 for o in nm if o['source_url'] and o['state']),'ready',sum(1 for o in nm if 'code host known' in o['notes']))
print('counties',len(nc),'with url',sum(1 for o in nc if o['source_url']))
print('new states',collections.Counter(o['state'] for o in new if o['state']).most_common(12))
tc=collections.Counter(x['type'] for x in t); print(tc)
print('county-type in AML',tc['county'])
print(collections.Counter(x['state'] for x in t).most_common(8))
# platform of covered
print(collections.Counter(x['publisher'][:30] for x in t if x['origin']!='unknown').most_common(8))

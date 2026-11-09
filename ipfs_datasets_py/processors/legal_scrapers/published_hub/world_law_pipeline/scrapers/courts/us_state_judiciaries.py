"""Seed list of US state (+DC) judiciary sites and court directory/locator pages."""
import json,sys
STATES={
"AL":("https://judicial.alabama.gov","https://judicial.alabama.gov/"),
"AK":("https://courts.alaska.gov","https://courts.alaska.gov/courtdir/index.htm"),
"AZ":("https://www.azcourts.gov","https://www.azcourts.gov/AZ-Courts/Court-Directory"),
"AR":("https://www.arcourts.gov","https://www.arcourts.gov/directories"),
"CA":("https://courts.ca.gov","https://courts.ca.gov/find-my-court"),
"CO":("https://www.coloradojudicial.gov","https://www.coloradojudicial.gov/trial-courts-county"),
"CT":("https://www.jud.ct.gov","https://www.jud.ct.gov/directory/directory/location/default.htm"),
"DE":("https://courts.delaware.gov","https://courts.delaware.gov/locations/"),
"DC":("https://www.dccourts.gov","https://www.dccourts.gov/about/locations"),
"FL":("https://www.flcourts.gov","https://www.flcourts.gov/Florida-Courts/Trial-Courts-Circuit"),
"GA":("https://georgiacourts.gov","https://georgiacourts.gov/"),
"HI":("https://www.courts.state.hi.us","https://www.courts.state.hi.us/"),
"ID":("https://isc.idaho.gov","https://isc.idaho.gov/"),
"IL":("https://www.illinoiscourts.gov","https://www.illinoiscourts.gov/courts-directory/interactive-map/by-court-type"),
"IN":("https://www.in.gov/courts","https://www.in.gov/courts/directory"),
"IA":("https://www.iowacourts.gov","https://www.iowacourts.gov/iowa-courts/district-court/"),
"KS":("https://www.kscourts.gov","https://directory-kard.kscourts.gov/"),
"KY":("https://www.kycourts.gov","https://www.kycourts.gov/Courts/County-Information/Pages/default.aspx"),
"LA":("https://www.lasc.org","https://www.lasc.org/District_Courts"),
"ME":("https://www.courts.maine.gov","https://www.courts.maine.gov/courts/find-by-town.html"),
"MD":("https://www.mdcourts.gov","https://www.mdcourts.gov/courtsdirectory"),
"MA":("https://www.mass.gov/orgs/massachusetts-court-system","https://www.mass.gov/orgs/massachusetts-court-system/locations"),
"MI":("https://www.courts.michigan.gov","https://www.courts.michigan.gov/courts/trial-courts/"),
"MN":("https://mncourts.gov","https://mncourts.gov/Find-Courts.aspx"),
"MS":("https://courts.ms.gov","https://courts.ms.gov/trialcourts/trialcourts.php"),
"MO":("https://www.courts.mo.gov","https://www.courts.mo.gov/page.jsp?id=321"),
"MT":("https://courts.mt.gov","https://courts.mt.gov/courts/dcourt/"),
"NE":("https://supremecourt.nebraska.gov","https://supremecourt.nebraska.gov/directories/district-court-contacts"),
"NV":("https://nvcourts.gov","https://nvcourts.gov/find_a_court/"),
"NH":("https://www.courts.nh.gov","https://www.courts.nh.gov/court-locations"),
"NJ":("https://www.njcourts.gov","https://www.njcourts.gov/courts/vicinages"),
"NM":("https://www.nmcourts.gov","https://www.nmcourts.gov/courts/"),
"NY":("https://ww2.nycourts.gov","https://ww2.nycourts.gov/courts/index.shtml"),
"NC":("https://www.nccourts.gov","https://www.nccourts.gov/locations"),
"ND":("https://www.ndcourts.gov","https://www.ndcourts.gov/district-court"),
"OH":("https://www.supremecourt.ohio.gov","https://www.supremecourt.ohio.gov/courts/judicial-system/ohio-trial-courts/"),
"OK":("https://www.oscn.net","https://www.oscn.net/courts/"),
"OR":("https://www.courts.oregon.gov","https://www.courts.oregon.gov/courts/Pages/default.aspx"),
"PA":("https://www.pacourts.us","https://www.pacourts.us/courts/courts-of-common-pleas"),
"RI":("https://www.courts.ri.gov","https://www.courts.ri.gov/Courts/Pages/default.aspx"),
"SC":("https://www.sccourts.org","https://www.sccourts.org/courts/courthouse-search/"),
"SD":("https://ujs.sd.gov","https://ujs.sd.gov/court-finder/"),
"TN":("https://www.tncourts.gov","https://www.tncourts.gov/courts/circuit-criminal-chancery-courts"),
"TX":("https://www.txcourts.gov","https://www.txcourts.gov/judicial-directory/"),
"UT":("https://www.utcourts.gov","https://www.utcourts.gov/en/about/miscellaneous/directory.html"),
"VT":("https://www.vermontjudiciary.org","https://www.vermontjudiciary.org/court-locations"),
"VA":("https://www.vacourts.gov","https://www.vacourts.gov/courts/home.html"),
"WA":("https://www.courts.wa.gov","https://www.courts.wa.gov/court_dir/"),
"WV":("https://www.courtswv.gov","https://www.courtswv.gov/public-resources/court-information-county/county-map"),
"WI":("https://www.wicourts.gov","https://www.wicourts.gov/contact/index.htm"),
"WY":("https://www.wyocourts.gov","https://www.wyocourts.gov/find-a-court/"),
}
if __name__=="__main__":
    import urllib.request,urllib.robotparser,datetime,time
    out=open(sys.argv[1] if len(sys.argv)>1 else "us_state_judiciaries.jsonl","w")
    for st,(home,dirurl) in STATES.items():
        row={"subdivision":f"US-{st}","home_url":home,"directory_url":dirurl}
        for k,u in (("home",home),("directory",dirurl)):
            try:
                r=urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0 (world_courts research)"}),timeout=20);row[k+"_status"]=r.status
            except Exception as e: row[k+"_status"]=getattr(e,"code",str(e)[:60])
            time.sleep(1)
        from robots_policy import policy
        row["site_policy"]=policy(dirurl)
        row["retrieved_at"]=datetime.datetime.utcnow().isoformat()+"Z"
        out.write(json.dumps(row)+"\n");out.flush()

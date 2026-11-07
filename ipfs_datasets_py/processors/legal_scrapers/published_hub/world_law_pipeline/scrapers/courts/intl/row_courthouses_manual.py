"""Courthouses for territories/micro-states where OSM amenity=courthouse and Wikidata return nothing: official court pages (contact/venue notices) geocoded with Nominatim (OSM, ODbL) or taken from an OSM object.
All rows need_review=true with the evidence in record_note. Usage: row_courthouses_manual.py CC.. """
import sys, json, os
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_courthouses import *
from row_common import nearest_city
from row_courthouses4 import postfilter  # noqa (ensures module path)
O = "open_license:ODbL"; OFF = "robots_unknown:official_page_search_excerpt"
def E(cc, key, name, tier, lat, lon, street, city, note, url, pol, geosrc, phone=None, local=None):
    return dict(cc=cc, key=key, name=name, tier=tier, lat=lat, lon=lon, street=street, city=city, note=note, url=url, pol=pol, geosrc=geosrc, phone=phone, local=local)
D = [
 E("CK", "ministry-of-justice-avarua", "High Court / Court House (Ministry of Justice Building), Avarua", "high-court", -21.2072356, -159.7751023, "Ara Tapu", "Avarua", "Official notices place the High Court at the Court House / Ministry of Justice Building, Avarua; position is the OSM object way/207000164", "https://www.justice.gov.ck/elementor-11/", O, "osm", "+682 29 410"),
 E("AI", "high-court-registry-the-valley", "High Court Registry and Magistrate's Court, The Valley", "high-court", 18.2109233, -63.052703, "Parliamentary Drive", "The Valley", "Official address 'Parliamentary Drive, The Valley' (gov.ai, eccourts.org); coordinates are the street centroid from Nominatim", "https://www.eccourts.org/anguilla-dir", OFF, "nominatim_street", "+1 264 497 2377"),
 E("NR", "nauru-courts-yaren", "Nauru Courts (Supreme Court and District Court), Yaren", "supreme-court", -0.5471064, 166.9163479, None, "Yaren", "Official contact address 'Nauru Courts, Yaren District'; coordinates are the Yaren district centroid (Nominatim)", "https://naurujudiciary.com/contact-us/", OFF, "nominatim_district", "+674 557 3133"),
 E("SM", "tribunale-borgo-maggiore", "Tribunale della Repubblica di San Marino", "lower-court", 43.9451387, 12.4538612, "Via 28 Luglio 194", "Borgo Maggiore", "Official address Via 28 Luglio 194, 47893 Borgo Maggiore (tribunale.sm); geocoded with Nominatim", "https://www.tribunale.sm/pub1/TribunaleSM/il-tribunale.html", OFF, "nominatim_address", "+378 0549 882614", "Tribunale della Repubblica di San Marino"),
 E("TC", "supreme-magistrate-grand-turk", "Supreme Court / Magistrate's Court, Grand Turk", "high-court", 21.4616863, -71.1460161, "Pond Street", "Cockburn Town", "Official address Pond Street, Grand Turk (judicial.tc); coordinates are the street position from Nominatim", "https://judicial.tc/contact", OFF, "nominatim_street", "+1 649 338 3972"),
 E("TC", "supreme-providenciales", "Supreme Court, Providenciales", "high-court", 21.7821286, -72.1968205, "1288 Leeward Highway", "Providenciales", "Official address 1288 Leeward Highway (judicial.tc); coordinates are the street position from Nominatim", "https://judicial.tc/contact", OFF, "nominatim_street", "+1 649 338 4904"),
 E("TC", "magistrate-providenciales", "Magistrate's Court, Providenciales", "lower-court", 21.7752555, -72.2593074, "Old Airport Road", "Providenciales", "Official address Old Airport Road (judicial.tc); coordinates are the street position from Nominatim", "https://judicial.tc/contact", OFF, "nominatim_street", "+1 649 338 4900"),
 E("TV", "court-house-funafuti", "Court House (High Court and Magistrates' Courts), Funafuti", "high-court", -8.515473, 179.199277, None, "Funafuti", "High Court of Tuvalu sits in Funafuti; Magistrates' sittings are directed to the Old PWD Complex at Vaiaku (LN 6/2007). Coordinates from a third-party place directory", "https://www.paclii.org/tv/courts.html", "robots_unknown:search_excerpt", "directory"),
 E("NU", "high-court-fonuakula", "High Court of Niue (Public Service Building, Fonuakula, Alofi)", "high-court", -19.0726394, -169.928621, None, "Alofi", "High Court sits in the Niue Public Service Building, Fonuakula, Alofi (gov.nu notices); coordinates are the OSM building 'Fale Gahua Fakatufono' (Government Building)", "https://gov.nu/notice-board/department-of-justice-lands-survey-community-services", OFF, "nominatim_building"),
 E("IO", "magistrates-court-diego-garcia", "Magistrate's Court, Diego Garcia", "lower-court", -7.3383584, 72.4718155, None, "Diego Garcia", "Courts Ordinance 1983: the Magistrate's Court sits on Diego Garcia in buildings designated by the Chief Justice; no fixed building published, position is the island centroid", "https://www.biot.gov.io/wp-content/uploads/The-Courts-Ord-1983-B.1.pdf", OFF, "island_centroid"),
 E("KY", "court-house-george-town", "Court House, George Town (Grand Court)", "high-court", 19.2959228, -81.3817104, "Albert Panton Street", "George Town", "OSM building way/171506992 'Court House' found by Nominatim (no amenity=courthouse tag)", "https://www.openstreetmap.org/way/171506992", O, "osm"),
 E("MS", "court-brades", "Court, Government Headquarters Road, Brades", "high-court", 16.7925269, -62.2103422, "Government Headquarters Road", "Brades", "OSM node/4100879691 'Court' (office=government) found by Nominatim; court tier assumed", "https://www.openstreetmap.org/node/4100879691", O, "osm"),
]
def build(cc):
    f = f"{ROOT}/data/{cc.lower()}/{cc.lower()}_courthouses.jsonl"
    rows = [json.loads(l) for l in open(f)]; rows = [r for r in rows if r["record_type"] == "court_body"]
    for e in [x for x in D if x["cc"] == cc]:
        c = nearest_city(e["lat"], e["lon"], cc)
        r = rec(court_id=f"{cc.lower()}-{e['key']}", name=e["name"], name_local=e["local"], country_code=cc, subdivision=(f"{cc}-{c[3]}" if c else cc), address={"street": e["street"], "city": e["city"], "postcode": None, "region": None, "country": cc},
                geo={"lat": e["lat"], "lon": e["lon"]}, phone=e["phone"], website=None, source_url=e["url"], source_kind="osm" if e["geosrc"] == "osm" else "official_page", site_policy=e["pol"], license="ODbL-1.0" if e["geosrc"] == "osm" else "facts from the official court page; position geocoded with Nominatim (ODbL) or a place directory", geo_source=e["geosrc"], retrieved_at=NOW())
        r["parent_court_id"] = f"{cc.lower()}-{e['tier']}"; r["court_system"] = "national"; r["needs_review"] = True; r["record_note"] = e["note"]; r["level"] = "trial"
        rows.append(r)
    assign_places(rows, cc); finish(cc, rows)
if __name__ == "__main__":
    for cc in sys.argv[1:]: build(cc)

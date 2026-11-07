"""rules_court_crosswalk for the EU phase: rule set -> court_body ids (hierarchy nodes) it governs, plus links from each member state to the endomorphosis ipfs_<country>_laws dataset (legislation text lives there; not duplicated here)."""
import sys, json, glob, collections
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
from eu_courthouses import EU, CN
LAWS = {cc: f"endomorphosis/ipfs_{n.lower()}_laws" for cc, n in CN.items()}
LAWS["CZ"] = "endomorphosis/ipfs_czechia_laws"
FAM = {  # rule_set_id -> families (court_system) of bodies the set governs
 "de-zpo": ["ordinary"], "de-famfg": ["ordinary"], "de-stpo": ["ordinary"], "de-jgg": ["ordinary"], "de-owig": ["ordinary"], "de-rpflg": ["ordinary"], "de-inso": ["ordinary"], "de-gvg": ["ordinary", "administrative", "labour", "social", "fiscal"],
 "de-vwgo": ["administrative"], "de-arbgg": ["labour"], "de-sgg": ["social"], "de-fgo": ["fiscal"], "de-bverfgg": ["constitutional"],
 "es-lec": ["ordinary", "commercial"], "es-lecrim": ["ordinary"], "es-lopj": ["ordinary", "administrative", "labour", "social", "commercial"], "es-lrjca": ["administrative"], "es-lrjs": ["labour", "social"], "es-lotc": ["constitutional"],
 "pl-kpc": ["ordinary", "labour", "commercial"], "pl-kpk": ["ordinary"], "pl-kpw": ["ordinary"], "pl-kpa": ["administrative"], "pl-ppsa": ["administrative"],
 "fr-cpc": ["ordinary", "commercial", "labour", "social"], "fr-cpp": ["ordinary"], "fr-cja": ["administrative"], "fr-coj": ["ordinary", "commercial", "labour", "social"], "fr-cpcexec": ["ordinary", "commercial"],
 "se-rb": ["ordinary", "commercial"], "se-fpl": ["administrative"], "se-domstolsarenden": ["ordinary", "administrative"], "se-arbetstvister": ["labour"], "se-allm-fd": ["administrative"],
 "be-gw-v-vi": ["ordinary", "commercial", "labour"], "pt-cpc": ["ordinary", "commercial", "labour"], "pt-cpp": ["ordinary"],
 "dk-rpl": ["ordinary", "commercial"], "fi-ok": ["ordinary"], "fi-halpl": ["administrative"], "fi-ork": ["ordinary"], "fi-ulosotto": ["ordinary"],
 "ro-cpp": ["ordinary"], "ro-cpc": ["ordinary", "commercial", "labour"], "sk-csp": ["ordinary", "commercial"], "sk-tp": ["ordinary"], "sk-ssp": ["administrative"],
 "hr-zpp": ["ordinary", "commercial"], "hr-zkp": ["ordinary"], "si-zpp": ["ordinary", "commercial", "labour"], "si-zkp": ["ordinary"],
 "ee-tsms": ["ordinary", "commercial"], "ee-krms": ["ordinary"], "ee-hkms": ["administrative"], "lv-cpl": ["ordinary", "commercial"], "lv-kpl": ["ordinary"], "lv-apl": ["administrative"],
 "mt-cocp": ["ordinary", "commercial", "labour"], "mt-crimproc": ["ordinary"], "cy-cpl": ["ordinary"], "cy-courts": ["ordinary", "commercial", "labour", "administrative"],
 "ie-rsc": ["ordinary"], "ie-dcr": ["ordinary"], "ie-ccr": ["ordinary"],
 "nl-rv": ["ordinary", "commercial"], "nl-sv": ["ordinary"], "nl-awb": ["administrative"], "nl-fw": ["ordinary", "commercial"]}
TIER = {"ie-dcr": ["limited"], "ie-ccr": ["general"], "ie-rsc": ["general", "appellate", "supreme"]}
def bodies(cc):
    return [json.loads(l) for l in open(f"{ROOT}/data/{cc.lower()}/{cc.lower()}_courthouses.jsonl") if '"court_body"' in l] if os.path.exists(f"{ROOT}/data/{cc.lower()}/{cc.lower()}_courthouses.jsonl") else []
def main():
    eu_bodies = {cc: bodies(cc) for cc in EU}
    for cc in ("de", "es", "pl", "nl", "fr", "se", "be", "pt", "ie", "dk", "fi", "ro", "sk", "hr", "si", "ee", "lv", "mt", "cy"):
        fn = f"{ROOT}/data/{cc}/{cc}_rules.jsonl"
        if not os.path.exists(fn): continue
        rs = {}
        for l in open(fn):
            r = json.loads(l); rs.setdefault(r["rule_set_id"], r)
        xw = []
        for sid, r in rs.items():
            for b in eu_bodies[cc.upper()]:
                if b["court_system"] in FAM.get(sid, []) and (sid not in TIER or b.get("tier") in TIER[sid]):
                    xw.append(dict(rule_set_id=sid, rule_set=r["rule_set"], court_id=b["court_id"], jurisdiction=cc.upper(), basis="procedural code governs this court family/tier (national hierarchy node)", source_url=r["source_url"], linked_rows="new", upstream_laws_dataset=LAWS[cc.upper()]))
        wjl(f"{ROOT}/data/{cc}/{cc}_rules_crosswalk.jsonl", xw); print(cc, len(xw))
    # EU instruments -> CJEU / member-state ordinary civil bodies
    rs = {}
    for l in open(f"{ROOT}/data/eu/eu_rules.jsonl"):
        r = json.loads(l); rs.setdefault(r["rule_set_id"], r)
    xw = []
    for sid, r in rs.items():
        if sid == "eu-cjeu-rop": cts = ["eu-cjeu", "eu-cjeu-court-of-justice"]
        elif sid == "eu-gc-rop": cts = ["eu-cjeu-general-court"]
        else:
            cts = [b["court_id"] for cc in EU for b in eu_bodies[cc] if b["court_system"] in ("ordinary", "commercial")]
        for c in cts:
            xw.append(dict(rule_set_id=sid, rule_set=r["rule_set"], court_id=c, jurisdiction="EU", basis=("court's own rules of procedure" if sid.endswith("rop") else "EU instrument applied by national civil/commercial courts (applicability varies, e.g. Denmark opt-out, Ireland opt-in)"),
                           source_url=r["source_url"], linked_rows="new", upstream_laws_dataset="endomorphosis/ipfs_eu_laws"))
    wjl(f"{ROOT}/data/eu/eu_rules_crosswalk.jsonl", xw); print("eu", len(xw))
    wjl(f"{ROOT}/data/eu/eu_laws_dataset_links.jsonl", [dict(country_code=cc, dataset=d, scope="national legislation incl. procedural codes (not duplicated in world_courts)") for cc, d in {**LAWS, "EU": "endomorphosis/ipfs_eu_laws"}.items()])
if __name__ == "__main__": main()

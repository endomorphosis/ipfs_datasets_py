"""NZ tranche 1 — candidate council website bases.

The pilot registry (jurisdictions.jsonl) carries names/codes only, so
this table supplies candidate base URLs per council (best-known official
domains; the campaign probe verifies each live via robots.txt before
any document is fetched — a wrong candidate simply fails the probe and
is recorded). Pilot-known bases are marked; the rest are candidates.
"""

# code -> [candidate base URLs, tried in order]
SITES = {
    "001": ["https://www.fndc.govt.nz"],
    "002": ["https://www.wdc.govt.nz"],                      # pilot: 403
    "003": ["https://www.kaipara.govt.nz"],
    "011": ["https://www.tcdc.govt.nz"],
    "012": ["https://www.hauraki-dc.govt.nz"],
    "013": ["https://www.waikatodistrict.govt.nz"],
    "015": ["https://www.mpdc.govt.nz"],
    "016": ["https://hamilton.govt.nz"],                     # pilot: done
    "017": ["https://www.waipadc.govt.nz"],
    "018": ["https://www.otodc.govt.nz"],
    "019": ["https://www.southwaikato.govt.nz"],
    "020": ["https://www.waitomo.govt.nz"],
    "021": ["https://www.taupo.govt.nz"],
    "022": ["https://www.westernbay.govt.nz"],
    "023": ["https://www.tauranga.govt.nz"],                 # pilot: done
    "024": ["https://www.rotorualakescouncil.nz"],           # pilot: 202 WAF
    "025": ["https://www.whakatane.govt.nz"],
    "026": ["https://www.kaweraudc.govt.nz"],
    "027": ["https://www.odc.govt.nz"],
    "028": ["https://www.gdc.govt.nz"],
    "029": ["https://www.wairoadc.govt.nz"],
    "030": ["https://www.hastingsdc.govt.nz"],               # pilot: transfer stall
    "031": ["https://www.napier.govt.nz"],
    "032": ["https://www.chbdc.govt.nz"],
    "033": ["https://www.npdc.govt.nz", "https://www.newplymouthnz.com"],  # pilot: glacial
    "034": ["https://www.stratford.govt.nz"],
    "035": ["https://www.southtaranaki.com"],
    "036": ["https://www.ruapehudc.govt.nz"],
    "037": ["https://www.whanganui.govt.nz"],
    "038": ["https://www.rangitikei.govt.nz"],
    "039": ["https://www.mdc.govt.nz"],
    "040": ["https://www.pncc.govt.nz"],                     # pilot: 403
    "041": ["https://www.tararuadc.govt.nz"],
    "042": ["https://www.horowhenua.govt.nz"],
    "043": ["https://www.kapiticoast.govt.nz"],              # pilot: JS library
    "044": ["https://poriruacity.govt.nz"],
    "045": ["https://www.upperhuttcity.com"],
    "046": ["https://www.huttcity.govt.nz"],                 # pilot: 403 WAF
    "047": ["https://wellington.govt.nz"],                   # pilot: live timeout; Wayback
    "048": ["https://www.mstn.govt.nz"],
    "049": ["https://www.cdc.govt.nz"],
    "050": ["https://www.swdc.govt.nz"],
    "051": ["https://www.tasman.govt.nz"],
    "052": ["https://www.nelson.govt.nz"],                   # pilot: 202 WAF
    "053": ["https://www.marlborough.govt.nz"],
    "054": ["https://www.kaikoura.govt.nz"],
    "055": ["https://www.bullerdc.govt.nz"],
    "056": ["https://www.greydc.govt.nz"],
    "057": ["https://www.westlanddc.govt.nz"],
    "058": ["https://www.hurunui.govt.nz"],
    "059": ["https://www.waimakariri.govt.nz"],
    "060": ["https://ccc.govt.nz"],                          # pilot: Incapsula
    "062": ["https://www.selwyn.govt.nz"],                   # pilot: robots timeout + 403
    "063": ["https://www.ashburtondc.govt.nz"],
    "064": ["https://www.timaru.govt.nz"],
    "065": ["https://www.mackenzie.govt.nz"],
    "066": ["https://www.waimatedc.govt.nz"],
    "067": ["https://www.cic.govt.nz"],
    "068": ["https://www.waitaki.govt.nz"],
    "069": ["https://www.codc.govt.nz"],
    "070": ["https://www.qldc.govt.nz"],
    "071": ["https://www.dunedin.govt.nz"],                  # pilot: 403 WAF
    "072": ["https://www.cluthadc.govt.nz"],
    "073": ["https://www.southlanddc.govt.nz"],
    "074": ["https://www.goredc.govt.nz"],
    "075": ["https://www.icc.govt.nz"],                      # pilot: 202 WAF
    "076": ["https://www.aucklandcouncil.govt.nz"],          # pilot: 406
    # regional councils
    "RBOP": ["https://www.boprc.govt.nz"],
    "RCAN": ["https://www.ecan.govt.nz"],
    "RHKB": ["https://www.hbrc.govt.nz"],
    "RMWT": ["https://www.horizons.govt.nz"],
    "RNTL": ["https://www.nrc.govt.nz"],
    "ROTA": ["https://www.orc.govt.nz"],
    "RSTL": ["https://www.es.govt.nz"],
    "RTKI": ["https://www.trc.govt.nz"],
    "RWGN": ["https://www.gw.govt.nz"],
    "RWKO": ["https://www.waikatoregion.govt.nz"],
    "RWTC": ["https://www.wcrc.govt.nz"],
}

DONE = {"016", "023"}
# pilot-documented live-hostile set -> Wayback-first group (b)
WAYBACK_FIRST = ["047", "002", "024", "030", "033", "040", "046",
                 "052", "060", "062", "071", "075", "076"]
JS_GROUP = ["043"]

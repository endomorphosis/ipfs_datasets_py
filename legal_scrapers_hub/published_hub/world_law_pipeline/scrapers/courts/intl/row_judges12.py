"""Gap pass (2026-10-30): FR Conseil d'État (VP, section du contentieux president/adjoints, 10 chamber presidents), DE federal supreme courts leadership (BGH BAG BFH BSG BVerwG),
IT Corte costituzionale full bench + Corte di cassazione Presidente aggiunto and section presidents (official PDFs). Public names and titles only; needs_review=true.
Usage: row_judges12.py CC.. -> data/<cc>/<cc>_judges.jsonl (merged by judge_id)"""
import sys, json, os
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_judges7 import *
OFF = "robots_unknown:official_site_via_search_excerpt"
def fr():
    ce = "https://www.conseil-etat.fr/qui-sommes-nous/le-conseil-d-etat/organisation/la-section-du-contentieux"
    r = A("FR", "administrative-supreme", [("Marc Guillaume", "Vice-président du Conseil d'État (depuis le 21 mai 2026)", "chief")], "https://www.conseil-etat.fr/", "https://www.conseil-etat.fr/qui-sommes-nous/le-conseil-d-etat/organisation/le-vice-president-du-conseil-d-etat", "Conseil d'État vice-president page", pol=OFF)
    p = [("Christine Maugüé", "Présidente de la section du contentieux (depuis le 9 août 2026)", "chamber_president")] + [(x, "Président(e) adjoint(e) de la section du contentieux", "chamber_president") for x in ["Jacques-Henri Stahl", "Pierre Collin", "Denis Piveteau"]]
    ch = ["Gaëlle Dumortier", "Alain Seban", "Stéphane Verclytte", "Anne Courrèges", "Jean-Philippe Mochon", "Isabelle de Silva", "Olivier Japiot", "Emilie Bokdam-Tognetti", "Anne Egerszegi", "Bertrand Dacosta"]
    p += [(x, f"Président(e) de la {i + 1}{'re' if i == 0 else 'e'} chambre de la section du contentieux", "chamber_president") for i, x in enumerate(ch)]
    return r + A("FR", "administrative-supreme", p, "https://www.conseil-etat.fr/", ce, "Conseil d'État section du contentieux organigramme (chamber presidents; rapporteurs publics not included)", pol=OFF)
def de():
    S = [("bgh", "Karin Angerer", "Präsidentin des Bundesgerichtshofs (seit 1. September 2026)", "https://www.bundesgerichtshof.de/DE/DasGericht/Praesidenten/praesidenten_node.html"),
         ("bag", "Inken Gallner", "Präsidentin des Bundesarbeitsgerichts", "https://www.bundesarbeitsgericht.de/presse/konferenz-der-praesidentinnen-und-praesidenten-der-obersten-gerichtshoefe-des-bundes-in-erfurt-und-weimar/"),
         ("bag", "Heinrich Kiel", "Vizepräsident des Bundesarbeitsgerichts", "https://www.bundesarbeitsgericht.de/presse/konferenz-der-praesidentinnen-und-praesidenten-der-obersten-gerichtshoefe-des-bundes-in-erfurt-und-weimar/"),
         ("bfh", "Hans-Josef Thesling", "Präsident des Bundesfinanzhofs (seit 25.01.2022)", "https://www.bundesfinanzhof.de/de/gericht/organisation/praesident-und-vizepraesident/"),
         ("bfh", "Meinhard Wittwer", "Vizepräsident des Bundesfinanzhofs (seit 21.11.2022)", "https://www.bundesfinanzhof.de/de/gericht/organisation/praesident-und-vizepraesident/"),
         ("bsg", "Christine Fuchsloch", "Präsidentin des Bundessozialgerichts (seit 1. März 2024)", "https://www.bsg.bund.de/DE/Gericht/Praesidentin_Vizepraesident/praesidentin_vizepraesident_node.html"),
         ("bsg", "Andreas Heinz", "Vizepräsident des Bundessozialgerichts (seit 24. August 2023)", "https://www.bsg.bund.de/DE/Gericht/Praesidentin_Vizepraesident/praesidentin_vizepraesident_node.html"),
         ("bverwg", "Andreas Korbmacher", "Präsident des Bundesverwaltungsgerichts", "https://www.bundesarbeitsgericht.de/presse/konferenz-der-praesidentinnen-und-praesidenten-der-obersten-gerichtshoefe-des-bundes-in-erfurt-und-weimar/")]
    out = []
    for c, n, t, u in S: out += A("DE", f"federal-{c}", [(n, t, "chief" if t.startswith("Präsident") else "associate")], u, u, "Official court leadership page / press release (BGH vice-president post vacant since 31 Aug 2026)", pol=OFF)
    return out
def it():
    cc_ = "https://www.cortecostituzionale.it/scheda-pronuncia/2026/168"
    g = ["Stefano Petitti", "Angelo Buscema", "Emanuela Navarretta", "Maria Rosaria San Giorgio", "Filippo Patroni Griffi", "Marco D'Alberti", "Giovanni Pitruzzella", "Antonella Sciarrone Alibrandi", "Massimo Luciani", "Maria Alessandra Sandulli", "Roberto Nicola Cassinelli", "Francesco Saverio Marini"]
    r = A("IT", "ordinary-supreme", [(x, "Giudice costituzionale", "associate") for x in g], "https://www.cortecostituzionale.it/contenuti/istituzioni/organi-della-corte", cc_, "Corte costituzionale bench as listed in Ordinanza 168/2026 (5 Oct 2026); mapped to the national apex body row like earlier IT rows; Viganò becomes President 14 Nov 2026", pol=OFF)
    B_ = "https://www.cortedicassazione.it/resources/cms/documents/"
    r += A("IT", "cassazione", [("Stefano Mogini", "Presidente aggiunto della Corte di cassazione (dall'11 dicembre 2025); Sezioni Unite penali", "associate")], "https://www.cortedicassazione.it/it/organizzazione_delle_attivita.page", B_ + "Presidenti_SU_penale.pdf", "Corte di cassazione organisation page / SU penali presidents PDF", pol=OFF)
    su = ["Gastone Andreazza", "Monica Boni", "Ercole Aprile", "Andrea Montagni", "Sergio Beltrani", "Luca Pistorelli"]
    r += A("IT", "cassazione", [(x, "Presidente titolare di sezione penale (Sezioni Unite penali)", "chamber_president") for x in su], B_ + "Presidenti_SU_penale.pdf", B_ + "Presidenti_SU_penale.pdf", "Corte di cassazione: presidenti titolari, Sezioni Unite penali", pol=OFF)
    ps = ["Rosa Pezzullo", "Luca Ramacci", "Salvatore Dovere", "Giuseppe Santalucia", "Andrea Pellegrino", "Gaetano De Amicis", "Angelo Caputo"]
    r += A("IT", "cassazione", [(x, "Presidente di sezione (Sezioni Unite penali)", "chamber_president") for x in ps], B_ + "Presidenti_SU_penale.pdf", B_ + "Presidenti_SU_penale.pdf", "Corte di cassazione: presidenti di sezione, Sezioni Unite penali", pol=OFF)
    r += A("IT", "cassazione", [(x, "Presidente di sezione, Prima sezione civile", "chamber_president") for x in ["Massimo Ferro", "Enrico Scoditti", "Mauro Di Marzio", "Alberto Giusti", "Guido Mercolino", "Francesco Terrusi"]], B_ + "Presidenti_1_civile.pdf", B_ + "Presidenti_1_civile.pdf", "Corte di cassazione: presidenti, Prima sezione civile", pol=OFF)
    r += A("IT", "cassazione", [(x, "Presidente di sezione, Prima sezione penale", "chamber_president") for x in ["Filippo Casa", "Giacomo Rocchi", "Giuseppe De Marzo"]], B_ + "Presidenti_1_penale_1.pdf", B_ + "Presidenti_1_penale_1.pdf", "Corte di cassazione: presidenti, Prima sezione penale (Santalucia listed above)", pol=OFF)
    return r
B = dict(FR=fr, DE=de, IT=it)
if __name__ == "__main__":
    for cc in sys.argv[1:]:
        rows = B[cc](); p = f"/workspace/world_courts/data/{cc.lower()}/{cc.lower()}_judges.jsonl"
        old = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
        seen = {r["judge_id"]: r for r in old}; n0 = len(seen)
        for r in rows: seen[r["judge_id"]] = r
        with open(p, "w") as f:
            for r in seen.values(): f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(cc, "built", len(rows), "total", len(seen), "added", len(seen) - n0)

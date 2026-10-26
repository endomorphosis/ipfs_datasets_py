"""Shared SPARQL client + constants for the Belgium/Flanders campaign.

LBLOD Centrale Vindplaats endpoint; robots.txt fully permissive
(User-agent: * / Disallow: empty). Self-imposed politeness delay + retries.
"""
import time

import requests

EP = "https://centrale-vindplaats.lblod.info/sparql"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) world-municipal-law-campaign/0.1",
      "Accept": "application/sparql-results+json"}

PFX = """PREFIX besluit: <http://data.vlaanderen.be/ns/besluit#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX eli: <http://data.europa.eu/eli/ontology#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX generiek: <https://data.vlaanderen.be/ns/generiek#>
PREFIX dct: <http://purl.org/dc/terms/>
"""

GEMEENTE_CLASS = "http://data.vlaanderen.be/id/concept/BestuurseenheidClassificatieCode/5ab0e9b8a3b2ca7c5e000001"
TYPE_BASE = "https://data.vlaanderen.be/id/concept/BesluitType/"

# Reglement-scope BesluitTypes (labels fetched live from the endpoint, 2026-10-12)
REG_TYPES = {
    "67378dd0-5413-474b-8996-d992ef81637a": "Reglementen en verordeningen",
    "ba5922c9-cfad-4b2e-b203-36479219ba56": "Retributiereglement",
    "e8afe7c5-9640-4db8-8f74-3f023bec3241": "Politiereglement",
    "256bd04a-b74b-4f2a-8f5d-14dda4765af9": "Tijdelijke politieverordening (op het wegverkeer)",
    "7d95fd2e-3cc9-4a4c-a58e-0fbc408c2f9b": "Aanvullend reglement op het wegverkeer (gewestwegen)",
    "4d8f678a-6fa4-4d5f-a2a1-80974e43bf34": "Aanvullend reglement op het wegverkeer (gemeentewegen)",
    "fb92601a-d189-4482-9922-ab0efc6bc935": "Gebruikersreglement",
    "a8486fa3-6375-494d-aa48-e34289b87d5b": "Huishoudelijk reglement",
    "e8aee49e-8762-4db2-acfe-2d5dd3c37619": "Reglement Onderwijs",
    "4673d472-8dbc-4cea-b3ab-f92df3807eb3": "Personeelsreglement",
    "fb21d14b-734b-48f4-bd4e-888163fd08e8": "Rechtspositieregeling (RPR)",
    "5ee63f84-2fa0-4758-8820-99dca2bdce7c": "Delegatiereglement",
    "25deb453-ae3e-4d40-8027-36cdb48ab738": "Deontologische Code",
    "4c22ef0a-f808-41dd-9c9f-2aff17fd851f": "Contantbelasting",
    "8597e056-b96d-4213-ad4c-37338f2aaf35": "Kohierbelasting",
    "b2d0734d-13d0-44b4-9af8-1722933c5288": "Aanvullende belasting of opcentiem",
    "d7060f97-c417-474c-abc6-ef006cb61f41": "Subsidie, premie, erkenning"
}


def bindings_map(bindings):
    return [{k: v["value"] for k, v in b.items()} for b in bindings]


class SparqlClient:
    """POST-based client with backoff (GET URLs overflow on big VALUES)."""

    def __init__(self, delay=1.0, timeout=300):
        self.delay = delay
        self.timeout = timeout
        self.n_requests = 0
        self.fetch_seconds = 0.0
        self.s = requests.Session()
        self.s.headers.update(UA)

    def query(self, sparql):
        last = None
        for attempt in range(6):
            t0 = time.time()
            try:
                r = self.s.post(EP, data={"query": sparql,
                                          "format": "application/sparql-results+json"},
                                timeout=self.timeout)
                self.n_requests += 1
                self.fetch_seconds += time.time() - t0
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                if self.delay:
                    time.sleep(self.delay)
                return r.json()["results"]["bindings"], time.time() - t0
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(min(60, 5 * 2 ** attempt))
        raise last

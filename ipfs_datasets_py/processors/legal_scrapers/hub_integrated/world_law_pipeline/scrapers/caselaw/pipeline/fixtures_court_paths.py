"""Fixtures for the matched / ambiguous / unmatched / unnamed court paths (no network, no courts dataset needed)."""
import json
import caselaw_schema as cs
from court_matcher import CourtMatcher

rows = [dict(entity_key="wc1e:court:" + "a" * 24, country_iso="NL", admin1=None, name="Hoge Raad", website="https://www.hogeraad.nl/x"),
        dict(entity_key="wc1e:court:" + "b" * 24, country_iso="NL", admin1=None, name="Hoge Raad", website=None),   # same group, higher key
        dict(entity_key="wc1e:court:" + "c" * 24, country_iso="NL", admin1=None, name="Rechtbank Noord Holland", website="https://www.rb.example.nl/a"),
        dict(entity_key="wc1e:court:" + "d" * 24, country_iso="NL", admin1=None, name="Rechtbank Noord Nederland", website="https://rb.example.nl/b")]
m = CourtMatcher(rows)
r = m.match("NL", "Hoge Raad", source_name="t", discriminator="HR")
assert r["court_match_status"] == "matched" and r["court_entity_key"] == "wc1e:court:" + "a" * 24 and r["court_key_provisional"] is None
assert r["meta"]["court_entity_key_candidates"] == ["wc1e:court:" + "a" * 24, "wc1e:court:" + "b" * 24]
r = m.match("NL", "hoge  raad.", source_name="t", discriminator="HR"); assert r["court_match_status"] == "matched"      # normalisation
r = m.match("NL", "Rechtbank Elders", website="https://rb.example.nl/zzz", source_name="t", discriminator="X")  # shared host => ambiguous
assert r["court_match_status"] == "ambiguous" and r["court_entity_key"] is None and r["court_key_provisional"].startswith("wcc1:NL:-:"), r
u1 = m.match("NL", "Gerechtshof Elders", source_name="t", discriminator="X"); assert u1["court_match_status"] == "unmatched" and u1["court_key_provisional"]
n1 = m.match("NL", None, source_name="t", discriminator="RBA"); n2 = m.match("NL", None, source_name="t", discriminator="RBB")
n3 = m.match("NL", "", source_name="t2", discriminator="RBA")
assert n1["court_match_status"] == n2["court_match_status"] == "unmatched"
assert len({n1["court_key_provisional"], n2["court_key_provisional"], n3["court_key_provisional"]}) == 3, "unnamed courts must not collide"
assert None not in {k[2] for k in m.unmatched}
print("court path fixtures ok", m.stats)

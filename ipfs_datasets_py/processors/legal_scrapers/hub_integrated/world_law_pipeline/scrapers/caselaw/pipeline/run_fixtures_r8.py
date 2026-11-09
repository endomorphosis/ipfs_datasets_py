"""Fixture test runner (r8). Local only; runs under plain `python3` AND the venv (the robots gate import in cl_common is guarded). Exit 0 = every fixture gave EXACTLY its expected result.
usage: run_fixtures_r8.py [--write [--run-dir DIR]]
DEFAULT = NO-WRITE: nothing is created, appended or deleted anywhere (the add_pair checks use SourceOut(dry=True); rejections are kept in memory and asserted).
--write (or --run-dir DIR, which implies it) additionally runs the add_pair checks against a real run dir UNDER $IPFS_DATASETS_LEGAL_WORKSPACE (default testdata_r8/_runs/<timestamp>, never /tmp; kept, nothing is deleted)
and asserts that rejected_rows.jsonl there holds exactly the expected rejections. The real out/ is never touched in either mode.
1) testdata_r8/*.parquet + expected.json: validate_caselaw_table must return exactly the expected message list ("errors": [] = clean). Substring matches are NOT accepted.
2) rule tests (apply_r8 on in-memory copies: TG nav strip, _nodate dates, BGE heading + anchored date, 12-31, ARGVP publication year, AR O-series heading date, zero-date flag, body_type order incl. CEDH, not_decision, e-mail v2): nothing is written.
3) add_pair behaviour (dry by default, see above)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys, json, time, copy, os
import pyarrow.parquet as pq
import caselaw_schema as cs
import r6_rules as R
import cl_common
FX = (str(_LEGAL_WS) + "/case_law/pipeline/testdata_r8")
WRITE = "--write" in sys.argv or "--run-dir" in sys.argv
RUN = sys.argv[sys.argv.index("--run-dir") + 1] if "--run-dir" in sys.argv else (f"{FX}/_runs/{time.strftime('%Y%m%d_%H%M%S')}" if WRITE else (str(_LEGAL_WS) + "/no_write_mode_nonexistent"))
assert RUN.startswith((str(_LEGAL_WS) + "/")), ("run dir must be under " + str(_LEGAL_WS) + " (not /tmp)")
exp = json.load(open(f"{FX}/expected.json")); bad = []
for k, e in exp.items():
    pr = cs.validate_caselaw_table(pq.read_table(f"{FX}/{k}.parquet"), e["kind"]); good = pr == e["errors"]
    print(("PASS" if good else "FAIL"), k, "" if good else f"got {pr} want {e['errors']}"); bad += [] if good else [k]
d0 = pq.read_table(f"{FX}/d_ok.parquet").to_pylist()[0]; o0 = pq.read_table(f"{FX}/o_ok.parquet").to_pylist()[0]
def pair(**kw):
    dd, oo = copy.deepcopy(d0), copy.deepcopy(o0); dd.update(kw.get("d", {})); oo.update(kw.get("o", {}))
    for r in (dd, oo): r["metadata_json"] = json.loads(r["metadata_json"])
    return dd, oo
def check(name, got, want):
    ok = got == want; print(("PASS" if ok else "FAIL"), name, "" if ok else f"got {got!r} want {want!r}"); bad.extend([] if ok else [name])
# --- body_type_for (pure function)
CH = "ch_entscheidsuche"
for nm, want in (("Appenzell Ausserrhoden Sammlung ARGVP", "collection"), ("Thurgau Obergericht Rechenschaftsbericht", "collection"), ("Graubünden Praxis des Kantonsgerichts PVG", "collection"),
                 ("OG", "court"), ("Verwaltung", "administrative_authority"), ("2. Abteilung", "court"), ("Appenzell Ausserrhoden Obergericht 1. Abteilung", "court"),
                 ("St.Gallen Kantonale Aufsichtsbehörde für Schuldbetreibung und Konkurs", "court"), ("Neuchâtel Autorité de surveillance LP", "court"),
                 ("Aargau Entscheide Grundbuch und Notariat", None), ("Bern Verwaltungsbehörden Direktion für Inneres und Justiz, Grundbuchämter", "administrative_authority"),
                 ("Zürich Andere Behörden und Gerichte", None), ("Cour européenne des droits de l'homme CEDH", "court"), ("CEDH Commission", "court"),
                 ("Bern Regierungsrat", "executive_body"), ("Vaud Commission de recours", "commission_or_regulator")):
    check(f"body_type_for {nm!r}", R.body_type_for(CH, nm), want)
check("body_type_for non-CH is court", R.body_type_for("nl_rechtspraak", "Raad van State"), "court")
# --- apply_r7 rules
T = "Urtheil\n\nBundesgericht\n\nvom 29. Oktober 1875\n\n" + "Das Gericht erwägt. " * 30
dd, oo = pair(d={"source_record_id": "CH_BGB_001_BGE-1-I-143", "decision_date": "1875-01-01", "decision_year": 1875, "docket_number": "BGE 1 I 143"}, o={"text": T, "text_sha256": cs.text_sha256(T)}); dd["text_sha256"] = oo["text_sha256"]
R.apply_r8(dd, oo); check("BGE heading date recovered", (dd["decision_date"], dd["decision_year"], "date_precision" in dd["metadata_json"]), ("1875-10-29", 1875, False))
dd, oo = pair(d={"source_record_id": "CH_BGB_001_BGE-1-I-143", "decision_date": "1875-01-01", "decision_year": 1875}, o={"text": "Urtheil\n\n" + "x " * 400, "text_sha256": cs.text_sha256("Urtheil\n\n" + "x " * 400)}); dd["text_sha256"] = oo["text_sha256"]
R.apply_r8(dd, oo); check("BGE without heading date -> year", (dd["decision_date"], dd["metadata_json"]["date_precision"]), ("1875", "year"))
for sid, dock, want in (("AR_KG_005_ARGVP-1988-3044_nodate", "ARGVP 1988 3044", (None, None, None)), ("AR_OG_003_O3V-25-2_nodate", "O3V-25-2", (None, None, None)),
                        ("AR_OG_001_O1Z-15-13-ARGVP-2018_nodate", "O1Z-15-13 ARGVP 2018 3732", (None, None, None))):
    dd, oo = pair(d={"source_record_id": sid, "docket_number": dock, "decision_date": "2021-01-01", "decision_year": 2021}); R.apply_r8(dd, oo)
    check(f"nodate {dock}", (dd["decision_date"], dd["decision_year"], dd["metadata_json"].get("date_precision")), want)
    check(f"nodate {dock} flagged", (dd["metadata_json"]["date_placeholder"]["source_default"], dd["metadata_json"]["date_placeholder"]["original_decision_date"]), (True, "2021-01-01"))
dd, oo = pair(d={"source_record_id": "AG_VB_002_AGVE-2002-155_2002-12-31", "decision_date": "2002-12-31", "decision_year": 2002}); R.apply_r8(dd, oo)
check("12-31 not in text -> year", (dd["decision_date"], dd["metadata_json"]["date_precision"]), ("2002", "year"))
T2 = "Entscheid vom 31. Dezember 2024. " + "x " * 200
dd, oo = pair(d={"source_record_id": "TA_DZK_001_CD-2024-DO-1_2024-12-31", "decision_date": "2024-12-31", "decision_year": 2024}, o={"text": T2, "text_sha256": cs.text_sha256(T2)}); dd["text_sha256"] = oo["text_sha256"]; R.apply_r8(dd, oo)
check("12-31 stated in text -> kept", dd["decision_date"], "2024-12-31")
body = "Gewinnsteuer. " + "Das Obergericht erwägt, dass die Beschwerde unbegründet ist. " * 8; body = body.strip()
T3 = "Skip to main content\nMain navigation\nTVR 2008\nTVR 2008 Nr. 21\n\n" + body + "\n\nObergericht\nVerwaltungsgericht\n\nCopyright Kanton Thurgau\nPowered by Scroll Sites & Atlassian Confluence\n"
dd, oo = pair(d={"source_record_id": "TG_OG_001_TVR-2008-Nr--21_2008-09-10"}, o={"text": T3, "text_sha256": cs.text_sha256(T3)}); dd["text_sha256"] = oo["text_sha256"]; R.apply_r8(dd, oo)
check("TG nav stripped + rehashed", (oo["text"] == body, oo["text_sha256"] == cs.text_sha256(body), dd["text_sha256"] == oo["text_sha256"], "boilerplate_stripped" in dd["metadata_json"]), (True, True, True, True))
t_before = oo["text"]; R.apply_r8(dd, oo); check("apply_r8 idempotent", oo["text"], t_before)
dd, oo = pair(d={"source_record_id": "ZH_SOBE_001_undefined_1998-08-10", "court_name_raw": "Zürich Andere Behörden und Gerichte"}); R.apply_r8(dd, oo)
check("not_decision flagged, body_type NULL", (dd["body_type"], "not_decision" in dd["metadata_json"]), (None, True))
for em, want in (("Mail anna @ example.org bitte", True), ("Mail Müller@büro.ch bitte", True), ("Mail a.b＠x.ch bitte", True), ("Mail [e-mail adres] @gmail.com bitte", False), ("ticker @ ct7 +34", False)):
    t_ = em + " " + "x " * 20; dd, oo = pair(o={"text": t_, "text_sha256": cs.text_sha256(t_)}); dd["text_sha256"] = oo["text_sha256"]; R.apply_r8(dd, oo)
    check(f"email v2 {em!r}", ("[email redacted]" in oo["text"], dd["text_sha256"] == oo["text_sha256"]), (want, True))
# --- r8 date rules
AROG = "Appenzell Ausserrhoden"
def head(kind, d_, extra=""): return f"Beschwerdef\u00fchrer A. vertreten durch RA AA. Vorinstanz IV-Stelle {AROG} {extra} Obergericht {AROG} 3. Abteilung {kind} vom {d_} Mitwirkende Obergerichtspr\u00e4sident W. Kobler " + "x " * 300
for sid, dock, txt, want in (
        ("AR_OG_003_O3V-22-22_nodate", "O3V-22-22", head("Urteil", "30. Mai 2023"), ("2023-05-30", 2023, None)),
        ("AR_OG_002_O2V-19-30_nodate", "O2V-19-30", head("Zirkular -Beschluss", "18. M\u00e4rz 2020"), ("2020-03-18", 2020, None)),
        ("AR_OG_003_O3V-18-19_nodate", "O3V-18-19", head("Urteil", "21. Mai 2019", "Die Beschwerde hat dieses mit Entscheiddatum vom 21. April 2020 abgewiesen."), ("2019-05-21", 2019, None)),
        ("AR_OG_003_O3V-22-22_nodate", "O3V-22-22", head("Urteil", "30. Mai 2031"), (None, None, None)),        # year outside filing year .. +3: not accepted
        ("AR_OG_003_O3V-22-22_nodate", "O3V-22-22", "Gegenstand Rente. Verf\u00fcgung vom 14. September 2022 Obergericht " + "x " * 400, (None, None, None)),   # no Urteil/Beschluss anchor
        ("AR_OG_001_O1Z-15-13-ARGVP-2018_nodate", "O1Z-15-13 ARGVP 2018 3732", "Seite 1/4 AR GVP 30/2018, Nr. 3732 " + "x " * 400, (None, None, None))):
    dd, oo = pair(d={"source_record_id": sid, "docket_number": dock, "decision_date": "2021-01-01", "decision_year": 2021}, o={"text": txt, "text_sha256": cs.text_sha256(txt)}); dd["text_sha256"] = oo["text_sha256"]; R.apply_r8(dd, oo)
    ph = dd["metadata_json"]["date_placeholder"]
    check(f"AR heading date {dock} {txt[-12:].strip()[:8]!r}", (dd["decision_date"], dd["decision_year"], dd["metadata_json"].get("date_precision")), want)
    check(f"AR heading date {dock} flag consistent", (bool(ph.get("date_unknown")), "recovered_from_text" in ph, ph.get("source_default")), (want[0] is None, want[0] is not None, True))
for sid, dock, yr in (("AR_KG_005_ARGVP-1988-1015_nodate", "ARGVP 1988 1015", 1988), ("AR_KG_005_ARGVP-2016-1554_nodate", "ARGVP 2016 1554", 2016)):
    dd, oo = pair(d={"source_record_id": sid, "docket_number": dock, "decision_date": "2021-01-01", "decision_year": 2021}); R.apply_r8(dd, oo); md_ = dd["metadata_json"]
    check(f"ARGVP {dock}: decision year NULL, publication_year kept", (dd["decision_date"], dd["decision_year"], md_.get("publication_year"), md_["date_placeholder"].get("date_unknown"), md_["date_placeholder"].get("year_basis"), "date_precision" in md_), (None, None, yr, True, "publication_volume_year", False))
dd, oo = pair(d={"source_record_id": "AR_OG_008_ERV-20-50-ARGVP-2020_nodate", "docket_number": "ERV-20-50 ARGVP 2020 3780", "decision_date": "2021-01-01", "decision_year": 2021}); R.apply_r8(dd, oo)
check("non-ARGVP-prefixed docket keeps docket year (r7 behaviour)", (dd["decision_date"], dd["decision_year"]), ("2020", 2020))
dd, oo = pair(d={"source_record_id": "GR_KG_001_PKG-1998-45_0000-00-00", "docket_number": "PKG 1998 45", "decision_date": None, "decision_year": None}); R.apply_r8(dd, oo); ph = dd["metadata_json"]["date_placeholder"]
check("zero date flagged date_unknown, year not guessed", (dd["decision_date"], dd["decision_year"], ph["evidence"], ph["date_unknown"]), (None, None, "source_id_zero_date", True))
PAD = "Organisation judiciaire. " + "x " * 420   # pushes the judgment date beyond the 700-char heading window of the r7 rule
T4 = PAD + "Extrait de l'arret de la Cour de cassation penale\ndu 9 juin 1908 dans la cause Engel.\n\n" + "L'art. 232 LP. " * 40
T5 = "Assemblee des creanciers le 25 juin 1906. " + "x " * 420 + "Arret du 20 novembre 1906, dans la cause X. " + "y " * 50
for sid, txt, want in (("CH_BGB_001_BGE-34-I-386", T4, ("1908-06-09", 1908, None)), ("CH_BGB_001_BGE-32-I-800", T5, ("1906-11-20", 1906, None)),
                       ("CH_BGB_001_BGE-34-I-386", PAD + "Reunion le 25 juin 1908 des creanciers. " + "x " * 300, ("1908", 1908, "year")),    # unanchored date: never taken
                       ("CH_BGB_001_BGE-34-I-386", T4.replace("1908", "1907"), ("1908", 1908, "year"))):                                  # year differs from the id year
    dd, oo = pair(d={"source_record_id": sid, "decision_date": sid[-4:].replace("386", "1908").replace("800", "1906")[-4:] + "-01-01", "decision_year": int(want[1])}, o={"text": txt, "text_sha256": cs.text_sha256(txt)}); dd["text_sha256"] = oo["text_sha256"]; R.apply_r8(dd, oo)
    check(f"BGE anchored date {sid[-9:]} {txt[:12]!r}", (dd["decision_date"], dd["decision_year"], dd["metadata_json"].get("date_precision")), want)
# --- add_pair (dry by default: nothing written; --write: real run dir under $IPFS_DATASETS_LEGAL_WORKSPACE)
cl_common.OUT = RUN
w = cl_common.SourceOut("ch_entscheidsuche", max_rows=10, dry=not WRITE)
T_ = json.loads(d0["metadata_json"])["terms"]
dd, oo = pair(); check("add_pair clean pair accepted", w.add_pair(dd, oo), True)
dd, oo = pair(); dd["metadata_json"]["terms"] = dict(T_, pending_legal_review=True); oo["metadata_json"]["terms"] = dict(T_, pending_legal_review=False); check("add_pair pending mismatch rejected", w.add_pair(dd, oo), False)
dd, oo = pair(o={"text": "Mail an max.muster@example.ch bitte " + o0["text"], "text_sha256": "x"}); dd["text_sha256"] = "x"
check("add_pair email redacted + flagged", (w.add_pair(dd, oo), "[email redacted]" in oo["text"], "personal_contact" in dd["sensitivity_flags"], dd["text_sha256"] == oo["text_sha256"]), (True, True, True, True))
dd, oo = pair(d={"docket_number": "undefined", "court_name_raw": d0["court_name_raw"] + "  "}); check("add_pair labels normalised", (w.add_pair(dd, oo), dd["docket_number"], dd["court_name_raw"] == d0["court_name_raw"]), (True, None, True))
dd, oo = pair(d={"restricted_ai_training": False}, o={"restricted_ai_training": False}); check("add_pair pending true + unrestricted rejected", w.add_pair(dd, oo), False)
nrej = len(w.rejected_log) if not WRITE else sum(1 for _ in open(f"{RUN}/ch_entscheidsuche/rejected_rows.jsonl"))
check("add_pair rejections recorded (2 expected)", nrej, 2)
if not WRITE: check("no-write mode created nothing", os.path.exists(RUN), False)
print("mode:", "WRITE run dir " + RUN if WRITE else "NO-WRITE (nothing created)"); print("FAILED:" if bad else "ALL PASSED", bad); sys.exit(1 if bad else 0)

"""Builds testdata_r8 (r8)/*.parquet from the first CH rows already on disk (local only). Fixtures are (re)generated, never deleted."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import glob, json, pyarrow.parquet as pq
import caselaw_schema as cs
OUT = (str(_LEGAL_WS) + "/case_law/out/ch_entscheidsuche"); FX = (str(_LEGAL_WS) + "/case_law/pipeline/testdata_r8")
d = next(r for r in pq.read_table(sorted(glob.glob(f"{OUT}/decision/part-*.parquet"))[1]).to_pylist() if r["body_type"] == "court" and r["docket_number"])
o = next(r for r in pq.read_table(sorted(glob.glob(f"{OUT}/opinion/part-*.parquet"))[1]).to_pylist() if r["decision_id"] == d["id"])
def meta(r, **kw): m = json.loads(r["metadata_json"]); m.update(kw); return m
T = d and json.loads(d["metadata_json"])["terms"]
EXACT = {
 "d_docket_undefined": [
  "docket_number: 1 values not normalised (leading/trailing/multiple whitespace, control chars) or a placeholder (undefined/null/n/a ...); use clean_label"
 ],
 "d_docket_whitespace": [
  "docket_number: 1 values not normalised (leading/trailing/multiple whitespace, control chars) or a placeholder (undefined/null/n/a ...); use clean_label"
 ],
 "d_court_whitespace": [
  "court_name_raw: 1 values not normalised (leading/trailing/multiple whitespace, control chars) or a placeholder (undefined/null/n/a ...); use clean_label"
 ],
 "d_unknown_licence_unrestricted": [
  "1 rows: terms.pending_legal_review=true requires restricted_ai_training=true until review is done",
  "1 rows: licence_class unknown requires restricted_ai_training=true"
 ],
 "d_pending_top_level": [
  "1 rows: pending_legal_review must sit only under metadata_json.terms (found elsewhere in metadata)"
 ],
 "d_pending_not_bool": [
  "1 rows: metadata_json.terms.pending_legal_review must be a boolean"
 ],
 "d_pending_true_unrestricted": [
  "1 rows: terms.pending_legal_review=true requires restricted_ai_training=true until review is done"
 ],
 "d_body_type_bad": [
  "body_type not in ('court', 'executive_body', 'administrative_authority', 'commission_or_regulator', 'collection')"
 ],
 "d_year_precision_bad": [
  "1 rows: metadata_json.date_precision must be year/month/day and match the shape of decision_date",
  "decision_year != decision_date year"
 ],
 "d_case_name_against": [
  "canonical_key: 1 values look like they carry a case name (A v. B); use a citation-only form"
 ],
 "d_flag_unknown": [
  "sensitivity_flags values not in ('criminal', 'family', 'juvenile', 'immigration', 'mental_health', 'tax', 'personal_contact') (no sealed flag: sealed records are never ingested)"
 ],
 "o_email_unredacted": [
  "1 opinions contain an unredacted e-mail address (replace with '[email redacted]')"
 ],
 "o_email_claim_without_token": [
  "1 opinions claim emails_redacted but contain no '[email redacted]'"
 ],
 "d_not_decision_with_body_type": [
  "1 rows: metadata_json.not_decision must be an object with a non-empty reason, and the row's body_type must be NULL"
 ],
 "d_date_null_without_flag": [
  "1 rows: metadata_json.date_placeholder malformed (evidence in ('source_id_year_only', 'source_id_nodate', 'source_id_no_date_and_no_1_january_in_text', 'source_id_dec31_not_in_text', 'source_id_zero_date'); recovered_from_text needs a full date and no date_precision; NULL date needs date_unknown and NULL year)"
 ],
 "d_date_evidence_unknown": [
  "1 rows: metadata_json.date_placeholder malformed (evidence in ('source_id_year_only', 'source_id_nodate', 'source_id_no_date_and_no_1_january_in_text', 'source_id_dec31_not_in_text', 'source_id_zero_date'); recovered_from_text needs a full date and no date_precision; NULL date needs date_unknown and NULL year)"
 ],
 "d_date_recovered_with_precision": [
  "1 rows: metadata_json.date_placeholder malformed (evidence in ('source_id_year_only', 'source_id_nodate', 'source_id_no_date_and_no_1_january_in_text', 'source_id_dec31_not_in_text', 'source_id_zero_date'); recovered_from_text needs a full date and no date_precision; NULL date needs date_unknown and NULL year)"
 ],
 "o_email_spaced_unredacted": [
  "1 opinions contain an unredacted e-mail address (replace with '[email redacted]')"
 ],
 "o_email_unicode_unredacted": [
  "1 opinions contain an unredacted e-mail address (replace with '[email redacted]')"
 ]
}
cases = {   # name -> (kind, row, expected)  expected: "ok" or "fail:<substring>"
 "d_ok": ("decision", d, "ok"), "o_ok": ("opinion", o, "ok"),
 "d_docket_undefined": ("decision", dict(d, docket_number="undefined"), EXACT['d_docket_undefined']),
 "d_docket_whitespace": ("decision", dict(d, docket_number=d["docket_number"] + "  X"), EXACT['d_docket_whitespace']),
 "d_court_whitespace": ("decision", dict(d, court_name_raw=" " + d["court_name_raw"]), EXACT['d_court_whitespace']),
 "d_unknown_licence_unrestricted": ("decision", dict(d, licence_class="unknown", restricted_ai_training=False), EXACT['d_unknown_licence_unrestricted']),
 "d_pending_top_level": ("decision", dict(d, metadata_json=dict(meta(d), pending_legal_review=True)), EXACT['d_pending_top_level']),
 "d_pending_not_bool": ("decision", dict(d, metadata_json=meta(d, terms=dict(T, pending_legal_review="yes"))), EXACT['d_pending_not_bool']),
 "d_pending_true_unrestricted": ("decision", dict(d, restricted_ai_training=False, metadata_json=meta(d, terms=dict(T, pending_legal_review=True))), EXACT['d_pending_true_unrestricted']),
 "d_body_type_bad": ("decision", dict(d, body_type="tribunal"), EXACT['d_body_type_bad']),
 "d_body_type_executive": ("decision", dict(d, body_type="executive_body"), "ok"),
 "d_year_precision_bad": ("decision", dict(d, decision_date="2020-01-01", metadata_json=meta(d, date_precision="year")), EXACT['d_year_precision_bad']),
 "d_year_precision_ok": ("decision", dict(d, decision_date="2020", decision_year=2020, metadata_json=meta(d, date_precision="year")), "ok"),
 "d_case_name_against": ("decision", dict(d, canonical_key="Smith against Jones"), EXACT['d_case_name_against']),
 "d_case_name_bge_v_ok": ("decision", dict(d, canonical_key="BGE 116 V 182"), "ok"),
 "d_flag_personal_contact": ("decision", dict(d, sensitivity_flags=["personal_contact"]), "ok"),
 "d_flag_unknown": ("decision", dict(d, sensitivity_flags=["email"]), EXACT['d_flag_unknown']),
 "o_email_unredacted": ("opinion", dict(o, text="write to a@b.ch", text_sha256=cs.text_sha256("write to a@b.ch")), EXACT['o_email_unredacted']),
 "o_email_claim_without_token": ("opinion", dict(o, metadata_json=meta(o, contact_redaction={"emails_redacted": 1})), EXACT['o_email_claim_without_token']),
}
PH = {"evidence": "source_id_nodate", "original_decision_date": "2021-01-01", "year_unverified": True, "rule": "date_r7"}
cases.update({
 "d_not_decision_ok": ("decision", dict(d, body_type=None, metadata_json=meta(d, not_decision={"reason": "guideline", "rule": "r7_manual_review"})), "ok"),
 "d_not_decision_with_body_type": ("decision", dict(d, metadata_json=meta(d, not_decision={"reason": "guideline"})), EXACT['d_not_decision_with_body_type']),
 "d_date_null_ok": ("decision", dict(d, decision_date=None, decision_year=None, metadata_json=meta(d, date_placeholder=dict(PH, date_unknown=True))), "ok"),
 "d_date_null_without_flag": ("decision", dict(d, decision_date=None, decision_year=None, metadata_json=meta(d, date_placeholder=PH)), EXACT['d_date_null_without_flag']),
 "d_date_evidence_unknown": ("decision", dict(d, metadata_json=meta(d, date_placeholder=dict(PH, evidence="made_up"))), EXACT['d_date_evidence_unknown']),
 "d_date_recovered_ok": ("decision", dict(d, decision_date="2020-04-06", decision_year=2020, metadata_json=meta(d, date_placeholder=dict(PH, evidence="source_id_year_only", original_decision_date="2020-01-01", recovered_from_text={"snippet": "vom 6. April 2020"}))), "ok"),
 "d_date_recovered_with_precision": ("decision", dict(d, decision_date="2020", decision_year=2020, metadata_json=meta(d, date_precision="year", date_placeholder=dict(PH, evidence="source_id_year_only", original_decision_date="2020-01-01", recovered_from_text={"snippet": "vom 6. April 2020"}))), EXACT['d_date_recovered_with_precision']),
 "d_date_null_no_placeholder": ("decision", dict(d, decision_date=None, decision_year=None), ["1 rows: decision_date is NULL without metadata_json.date_placeholder.date_unknown=true (a NULL date must be flagged)"]),
 "d_date_zero_flagged_ok": ("decision", dict(d, decision_date=None, decision_year=None, metadata_json=meta(d, date_placeholder={"evidence": "source_id_zero_date", "original_decision_date": "0000-00-00", "date_unknown": True, "rule": "date_r8"})), "ok"),
 "d_publication_year_ok": ("decision", dict(d, decision_date=None, decision_year=None, metadata_json=meta(d, publication_year=2016, date_placeholder={"evidence": "source_id_nodate", "original_decision_date": "2016", "year_basis": "publication_volume_year", "date_unknown": True, "rule": "date_r8"})), "ok"),
 "d_publication_year_with_date": ("decision", dict(d, metadata_json=meta(d, publication_year=2016)), ["1 rows: metadata_json.publication_year must be an integer 1800-2100 and decision_date must be NULL"]),
 "d_publication_year_bad": ("decision", dict(d, decision_date=None, decision_year=None, metadata_json=meta(d, publication_year="2016", date_placeholder=dict(PH, date_unknown=True))), ["1 rows: metadata_json.publication_year must be an integer 1800-2100 and decision_date must be NULL"]),
 "d_party_key_beschwerdegegner": ("decision", dict(d, metadata_json=meta(d, beschwerdegegner="X")), ["litigant-name keys in metadata_json: ['beschwerdegegner']"]),
 "d_party_key_convenuti": ("decision", dict(d, metadata_json=meta(d, convenuti="X")), ["litigant-name keys in metadata_json: ['convenuti']"]),
 "d_party_key_resistance_ok": ("decision", dict(d, metadata_json=meta(d, resistance_level="x")), "ok"),
 "o_email_spaced_unredacted": ("opinion", dict(o, text="write to anna @ example.org", text_sha256=cs.text_sha256("write to anna @ example.org")), EXACT['o_email_spaced_unredacted']),
 "o_email_unicode_unredacted": ("opinion", dict(o, text="write to M\u00fcller@b\u00fcro.ch", text_sha256=cs.text_sha256("write to M\u00fcller@b\u00fcro.ch")), EXACT['o_email_unicode_unredacted']),
 "o_email_placeholder_ok": ("opinion", dict(o, text="account [e-mail adres] @gmail.com and @ [naam]", text_sha256=cs.text_sha256("account [e-mail adres] @gmail.com and @ [naam]")), "ok"),
})

exp = {}
import pyarrow as pa
for k, (kind, r, e) in cases.items():
    r = dict(r)
    if isinstance(r.get("metadata_json"), dict): r["metadata_json"] = json.dumps(r["metadata_json"], ensure_ascii=False)
    t = cs.cast_rows([r], kind)
    if k.startswith("d_party_key_") and "ok" not in k:   # cast_rows drops party keys: re-insert the raw metadata so the validator sees them
        t = t.set_column(t.schema.get_field_index("metadata_json"), "metadata_json", pa.array([r["metadata_json"]], pa.string()))
    errs = [] if e == "ok" else e
    got = cs.validate_caselaw_table(t, kind)
    assert got == errs, (k, got, errs)   # generator self-check: the hand-written exact expectation must hold
    pq.write_table(t, f"{FX}/{k}.parquet"); exp[k] = {"kind": kind, "errors": errs}
json.dump(exp, open(f"{FX}/expected.json", "w"), indent=1, ensure_ascii=False); print(len(exp), "fixtures")

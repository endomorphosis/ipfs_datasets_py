"""Synthetic official-format fixtures test custody, never statutory authority."""
import ast
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as owner
from ipfs_datasets_py.logic.autoformal import legal_span_cache_intake as intake
from ipfs_datasets_py.logic.autoformal import legal_span_provenance as provenance

RAW = ('<html><head><meta charset="utf-8"></head><body><h3 class="section-head">§1. Example</h3>'
       '<p class="statutory-body">(a) Café aaa duty.</p><p class="source-credit">Source credit.</p>'
       '<h4>Editorial Notes</h4><p class="note">aaa note.</p></body></html>').encode()


def document_input(raw=RAW, *, legal_id="usc:us:10:1", edition=2024):
    title,section=legal_id.split(":")[-2:]
    package=f"USCODE-{edition}-title{title}"; granule=package+"-chap1-sec"+section
    url=f"https://www.govinfo.gov/content/pkg/{package}/html/{granule}.htm"
    descriptor={"schema":owner.DESCRIPTOR_SCHEMA,"legal_id":legal_id,"edition":edition,"package_id":package,
        "granule_id":granule,"url":url,"retrieved_at":"2026-10-13T12:00:00Z",
        "raw_sha256":hashlib.sha256(raw).hexdigest(),"raw_bytes":len(raw),
        "http_provenance":{"requested_url":url,"final_url":url,"status_code":200,
            "content_type":"text/html; charset=UTF-8","etag":None,"last_modified":None}}
    return {"descriptor":descriptor,"raw_bytes":raw,"expected_descriptor_sha256":owner.acquisition_descriptor_sha256(descriptor),
        "expected_raw_sha256":descriptor["raw_sha256"],"expected_raw_bytes":len(raw)}


def document_arguments(item):
    return {key:value for key,value in item.items() if key!="raw_bytes"}


def inputs(tmp_path, texts=("Café",), *, legal_ids=None, documents=None, rows=None):
    source=tmp_path/"authored.py"
    source.write_text("def demonstration_spans():\n    rows = (('authored', 'usc:us:10:1', 'Café'),)\n    return rows\n")
    raw=source.read_bytes();fn=ast.parse(raw).body[0]
    pins=[{"source_id":"synthetic-authored","path":str(source),"source_sha256":hashlib.sha256(raw).hexdigest(),
        "function_name":"demonstration_spans","function_ast_sha256":hashlib.sha256(ast.dump(fn,include_attributes=False).encode()).hexdigest(),
        "projection_profile":provenance.PROJECTION_PROFILE}]
    catalog=provenance.catalog_from_sources(pins)
    cache={"repository":"fixture/span-cache","revision":"a"*40,"artifact_sha256":"b"*64}
    if rows is None:
        legal_ids=legal_ids or ["usc:us:10:1"]*len(texts)
        rows=[{"source_span_id":"observed-"+str(n),"legal_id":legal,"source_text":text,
            "source_sha256":hashlib.sha256(text.encode()).hexdigest(),"unknown":{"keep":[1,1,None]}}
            for n,(text,legal) in enumerate(zip(texts,legal_ids))]
    trusted={"cache_identity":cache,"expected_row_sha256s":[intake.row_sha256(r) for r in rows],
        "expected_record_sha256s":[intake.record_sha256(r,ordinal=n,cache_identity=cache) for n,r in enumerate(rows)],
        "demonstration_catalog":catalog,"expected_catalog_sha256":provenance.catalog_sha256(catalog),
        "expected_catalog_source_pins":pins}
    report=provenance.reconcile_span_provenance(rows,**trusted)
    docs=[document_input()] if documents is None else documents
    return report,rows,{"provenance_inputs":trusted,"expected_provenance_report_sha256":provenance.provenance_report_sha256(report),
        "document_inputs":docs,"expected_document_population_sha256":owner.document_population_sha256(docs)}


def test_document_full_extraction_notes_and_view_replay_are_lossless():
    item=document_input(); report=owner.prepare_official_document(item["raw_bytes"],**document_arguments(item))
    assert report["status"]=="comparison_document_extracted" and report["raw_body_verified"]
    assert report["document"]["document_text"]=="(a) Café aaa duty.\nSource credit.\naaa note."
    assert [p["kind"] for p in report["document"]["paragraphs"]]==["codified_body","source_credit","notes_or_other"]
    assert report["document"]["paragraphs"][2]["note_headings"]==["Editorial Notes"]
    assert report["normalized_view"]["utf8_bytes"]>report["normalized_view"]["unicode_code_points"]
    assert all(value is False for value in report["authority"].values())
    assert owner.validate_official_document(report,item["raw_bytes"],expected_report_sha256=owner.document_report_sha256(report),
        **document_arguments(item))==report


def test_strict_official_link_request_records_redirect_without_assigning_producer_edition():
    item=document_input(); item["descriptor"]["http_provenance"]["requested_url"]="https://www.govinfo.gov/link/uscode/10/1?year=2024"
    item["expected_descriptor_sha256"]=owner.acquisition_descriptor_sha256(item["descriptor"])
    report=owner.prepare_official_document(item["raw_bytes"],**document_arguments(item))
    assert report["status"]=="comparison_document_extracted"
    assert report["authority"]["producer_edition_correspondence_verified"] is False
    assert "comparison_only" in report["edition_scope"]


@pytest.mark.parametrize("damage",["descriptor_pin","body_pin","size_pin","body_bytes","oversize"])
def test_external_pins_cannot_be_replaced_by_same_payload_self_seals(damage):
    item=document_input()
    if damage=="descriptor_pin":item["expected_descriptor_sha256"]="0"*64
    elif damage=="body_pin":item["expected_raw_sha256"]="0"*64
    elif damage=="size_pin":item["expected_raw_bytes"]+=1
    elif damage=="body_bytes":item["raw_bytes"]+=b"x"
    else:item["expected_raw_bytes"]=owner.MAX_HTML_BYTES+1
    with pytest.raises(owner.OfficialSourceCustodyError):
        owner.prepare_official_document(item["raw_bytes"],**document_arguments(item))


@pytest.mark.parametrize("damage",["host","query","edition","package","granule","request_host","request_year","final_url","status","content_type","naive_time","unknown_field"])
def test_descriptor_identity_and_http_observations_require_closed_official_profile(damage):
    item=document_input();d=item["descriptor"];http=d["http_provenance"]
    if damage=="host":d["url"]=d["url"].replace("www.govinfo.gov","www.govinfo.gov.invalid")
    elif damage=="query":d["url"]+="?year=2024"
    elif damage=="edition":d["edition"]=2023
    elif damage=="package":d["package_id"]="USCODE-2024-title11"
    elif damage=="granule":d["granule_id"]+="-alias"
    elif damage=="request_host":http["requested_url"]="https://example.com/"
    elif damage=="request_year":http["requested_url"]="https://www.govinfo.gov/link/uscode/10/1?year=2023"
    elif damage=="final_url":http["final_url"]+="?redirect=1"
    elif damage=="status":http["status_code"]=True
    elif damage=="content_type":http["content_type"]="application/json"
    elif damage=="naive_time":d["retrieved_at"]="2026-10-13T12:00:00"
    else:d["accepted"]=True
    with pytest.raises(owner.OfficialSourceCustodyError):owner.acquisition_descriptor_sha256(d)


@pytest.mark.parametrize("case",["missing","unsupported_section","rejected_extraction"])
def test_unavailable_or_unsupported_documents_remain_explicit(case):
    item=document_input(legal_id="usc:us:16:410oo-2") if case=="unsupported_section" else document_input(b"<html>Not a codified section</html>") if case=="rejected_extraction" else document_input()
    if case=="missing":item["raw_bytes"]=None
    report=owner.prepare_official_document(item["raw_bytes"],**document_arguments(item))
    assert report["document"] is None and report["normalized_view"] is None and report["issues"]
    assert report["status"]=={"missing":"raw_comparison_document_missing","unsupported_section":"unsupported_section_identity_profile",
        "rejected_extraction":"comparison_extraction_rejected"}[case]


def test_complete_inventory_retains_overlaps_unicode_and_body_note_coverage(tmp_path):
    prov,rows,args=inputs(tmp_path,texts=("aa","Café","duty.\nSource","absent text"))
    report=owner.prepare_source_occurrence_inventory(prov,rows,**args)
    assert report["row_count"]==4 and len(report["documents"])==1
    assert report["expected_record_sha256s"]==[r["record_sha256"] for r in prov["rows"]]
    first,second,cross,zero=report["rows"]
    assert first["exact_occurrence_count"]==4 and first["status"]=="multiple_exact_comparison_occurrences_unselected"
    overlaps=first["comparison_documents"][0]["occurrences"]
    assert overlaps[1]["selector"]["char_start"]==overlaps[0]["selector"]["char_start"]+1
    assert overlaps[0]["selector"]["utf8_byte_start"]>overlaps[0]["selector"]["char_start"]
    assert overlaps[2]["paragraph_coverage"]["paragraph_kind_counts"]=={"notes_or_other":1}
    assert second["exact_occurrence_count"]==1 and second["selected_occurrence"] is None
    assert second["status"]=="single_exact_comparison_occurrence_unselected"
    coverage=cross["comparison_documents"][0]["occurrences"][0]["paragraph_coverage"]
    assert coverage["paragraph_kind_counts"]=={"codified_body":1,"source_credit":1}
    assert coverage["interparagraph_separator_codepoints"]==1
    assert zero["status"]=="zero_exact_comparison_occurrences"
    assert all(r["governing_source_binding"] is None and all(v is False for v in r["authority"].values()) for r in report["rows"])
    assert owner.validate_source_occurrence_inventory(report,prov,rows,
        expected_report_sha256=owner.source_occurrence_inventory_sha256(report),**args)==report


def test_all_comparison_editions_are_retained_without_unique_document_choice(tmp_path):
    docs=[document_input(),document_input(edition=2023)]
    prov,rows,args=inputs(tmp_path,documents=docs)
    report=owner.prepare_source_occurrence_inventory(prov,rows,**args)
    row,=report["rows"]
    assert len(row["comparison_documents"])==2 and row["exact_occurrence_count"]==2
    assert row["status"]=="multiple_exact_comparison_occurrences_unselected" and row["selected_occurrence"] is None


def test_missing_documents_and_unmatched_identities_preserve_every_physical_row(tmp_path):
    prov,rows,args=inputs(tmp_path,texts=("Café","Café","Café"),legal_ids=("usc:us:10:1","usc:us:10",""),documents=[])
    report=owner.prepare_source_occurrence_inventory(prov,rows,**args)
    assert report["row_count"]==3 and len(report["expected_record_sha256s"])==3
    assert all(r["status"]=="comparison_document_missing" for r in report["rows"])


def test_unsupported_section_identity_survives_complete_inventory(tmp_path):
    docs=[document_input(legal_id="usc:us:16:410oo-2")]
    prov,rows,args=inputs(tmp_path,legal_ids=("usc:us:16:410oo-2",),documents=docs)
    report=owner.prepare_source_occurrence_inventory(prov,rows,**args)
    row,=report["rows"]
    assert row["status"]=="comparison_inventory_incomplete_document_unavailable_or_unsupported"
    assert row["comparison_documents"][0]["document_status"]=="unsupported_section_identity_profile"


@pytest.mark.parametrize("damage",["document_population_pin","provenance_pin","drop_document","drop_row","reorder_rows"])
def test_independently_pinned_complete_input_populations_cannot_be_resealed(tmp_path,damage):
    prov,rows,args=inputs(tmp_path,texts=("Café","aaa"))
    if damage=="document_population_pin":args["expected_document_population_sha256"]="0"*64
    elif damage=="provenance_pin":args["expected_provenance_report_sha256"]="0"*64
    elif damage=="drop_document":args["document_inputs"]=[]
    elif damage=="drop_row":rows.pop()
    else:rows.reverse()
    with pytest.raises(ValueError):owner.prepare_source_occurrence_inventory(prov,rows,**args)


@pytest.mark.parametrize("damage",["selected_occurrence","coverage","authority","drop_row","view"])
def test_output_tampering_fails_full_regeneration_even_with_new_report_digest(tmp_path,damage):
    prov,rows,args=inputs(tmp_path,texts=("Café","aaa"))
    report=owner.prepare_source_occurrence_inventory(prov,rows,**args)
    if damage=="selected_occurrence":report["rows"][0]["selected_occurrence"]={"invented":True}
    elif damage=="coverage":report["rows"][0]["comparison_documents"][0]["occurrences"][0]["paragraph_coverage"]["paragraphs"]=[]
    elif damage=="authority":report["authority"]["legal_review_verified"]=True
    elif damage=="drop_row":report["rows"].pop()
    else:report["documents"][0]["normalized_view"]["view_id"]="invented"
    with pytest.raises(owner.OfficialSourceCustodyError,match="complete independent replay"):
        owner.validate_source_occurrence_inventory(report,prov,rows,
            expected_report_sha256=owner.source_occurrence_inventory_sha256(report),**args)


def test_all_overlaps_or_cross_document_bound_refused_without_partial_report(tmp_path):
    prov,rows,args=inputs(tmp_path,texts=("aa",))
    with pytest.raises(ValueError,match="occurrence bound"):
        owner.prepare_source_occurrence_inventory(prov,rows,max_occurrences=1,**args)


def test_missing_one_comparison_body_never_reports_complete_zero_or_single_match(tmp_path):
    docs=[document_input(),document_input(edition=2023)];docs[1]["raw_bytes"]=None
    prov,rows,args=inputs(tmp_path,documents=docs)
    report=owner.prepare_source_occurrence_inventory(prov,rows,**args)
    row,=report["rows"]
    assert row["exact_occurrence_count"]==1 and row["status"]=="comparison_inventory_incomplete_document_unavailable_or_unsupported"
    assert row["selected_occurrence"] is None


@pytest.mark.parametrize("case",["duplicate","too_many"])
def test_document_population_limits_are_complete_and_finite(case):
    docs=[document_input(),document_input()] if case=="duplicate" else [document_input(edition=2000+n) for n in range(11)]
    with pytest.raises(owner.OfficialSourceCustodyError):owner.document_population_sha256(docs)


def test_cumulative_inventory_budget_stops_before_building_all_row_occurrences(tmp_path,monkeypatch):
    prov,rows,args=inputs(tmp_path,texts=("Café",)*12)
    calls=[]; original=owner.contexts.exact_view_occurrences
    def observed(*args,**kwargs):
        calls.append(True)
        return original(*args,**kwargs)
    monkeypatch.setattr(owner.contexts,"exact_view_occurrences",observed)
    monkeypatch.setattr(owner,"MAX_REPORT_BYTES",16000)
    with pytest.raises(owner.OfficialSourceCustodyError,match="byte bound"):
        owner.prepare_source_occurrence_inventory(prov,rows,**args)
    assert 0<len(calls)<len(rows)

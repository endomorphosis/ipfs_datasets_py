"""New comparison coordinates never select or authenticate producer source."""
import ast
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as acquisitions
from ipfs_datasets_py.logic.autoformal import legal_official_document_views as views
from ipfs_datasets_py.logic.autoformal import legal_source_view_inventory as owner
from ipfs_datasets_py.logic.autoformal import legal_span_cache_intake as intake
from ipfs_datasets_py.logic.autoformal import legal_span_provenance as provenance
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as legacy

RAW = ('<html><head><meta charset="utf-8"></head><body>'
       '<h3 class="section-head">§1. Example</h3><h2>HEADER_SENTINEL</h2>'
       '<!-- field-start:statute --><p class="statutory-body">(a) Café aaa duty.</p><!-- field-end:statute -->'
       '<table><tr><th>Column</th><td>TABLE_SENTINEL</td></tr></table>'
       '<!-- field-start:notes --><h4>Editorial Notes</h4><p class="note">NOTES_SENTINEL aaa.</p><!-- field-end:notes -->'
       '</body></html>').encode()


def document_input(raw=RAW, *, edition=2024, legal_id="usc:us:10:1", missing=False):
    title,section=legal_id.split(":")[-2:];package=f"USCODE-{edition}-title{title}";granule=package+"-chap1-sec"+section
    url=f"https://www.govinfo.gov/content/pkg/{package}/html/{granule}.htm"
    descriptor={"schema":acquisitions.DESCRIPTOR_SCHEMA,"legal_id":legal_id,"edition":edition,
        "package_id":package,"granule_id":granule,"url":url,"retrieved_at":"2026-10-13T12:00:00Z",
        "raw_sha256":hashlib.sha256(raw).hexdigest(),"raw_bytes":len(raw),
        "http_provenance":{"requested_url":url,"final_url":url,"status_code":200,
            "content_type":"text/html; charset=UTF-8","etag":None,"last_modified":None}}
    trusted={"descriptor":descriptor,"expected_descriptor_sha256":acquisitions.acquisition_descriptor_sha256(descriptor),
        "expected_raw_sha256":descriptor["raw_sha256"],"expected_raw_bytes":len(raw)}
    body=None if missing else raw
    report=views.prepare_official_document_view(body,**trusted)
    return {**trusted,"raw_bytes":body,"view_report":report,
            "expected_view_report_sha256":views.document_view_report_sha256(report)}


def inputs(tmp_path, texts=("Café",), *, docs=None, legal_ids=None, rows=None):
    source=tmp_path/"authored.py";source.write_text("def demonstration_spans():\n    rows = (('authored', 'usc:us:10:1', 'Café'),)\n    return rows\n")
    raw=source.read_bytes();fn=ast.parse(raw).body[0]
    pins=[{"source_id":"synthetic-authored","path":str(source),"source_sha256":hashlib.sha256(raw).hexdigest(),
        "function_name":"demonstration_spans","function_ast_sha256":hashlib.sha256(ast.dump(fn,include_attributes=False).encode()).hexdigest(),
        "projection_profile":provenance.PROJECTION_PROFILE}]
    catalog=provenance.catalog_from_sources(pins);cache={"repository":"fixture/span-cache","revision":"a"*40,"artifact_sha256":"b"*64}
    if rows is None:
        legal_ids=legal_ids or ["usc:us:10:1"]*len(texts)
        rows=[{"source_span_id":"observed-"+str(i),"legal_id":legal,"source_text":text,
            "source_sha256":hashlib.sha256(text.encode()).hexdigest(),"unknown":[None,1,1]}
            for i,(text,legal) in enumerate(zip(texts,legal_ids))]
    trusted={"cache_identity":cache,"expected_row_sha256s":[intake.row_sha256(r) for r in rows],
        "expected_record_sha256s":[intake.record_sha256(r,ordinal=i,cache_identity=cache) for i,r in enumerate(rows)],
        "demonstration_catalog":catalog,"expected_catalog_sha256":provenance.catalog_sha256(catalog),"expected_catalog_source_pins":pins}
    report=provenance.reconcile_span_provenance(rows,**trusted)
    docs=[document_input()] if docs is None else docs
    return report,rows,{"provenance_inputs":trusted,"expected_provenance_report_sha256":provenance.provenance_report_sha256(report),
        "document_inputs":docs,"expected_document_population_sha256":owner.view_document_population_sha256(docs)}


def test_complete_physical_inventory_includes_header_table_notes_and_body_regions(tmp_path):
    prov,rows,args=inputs(tmp_path,texts=("HEADER_SENTINEL","TABLE_SENTINEL","NOTES_SENTINEL","Café","absent"))
    report=owner.prepare_source_view_inventory(prov,rows,**args)
    assert report["row_count"]==5 and len(report["documents"])==1
    assert report["expected_record_sha256s"]==[r["record_sha256"] for r in prov["rows"]]
    assert report["expected_row_sha256s"]==[r["raw_row_sha256"] for r in prov["rows"]]
    assert report["documents"][0]==args["document_inputs"][0]["view_report"]
    for result in report["rows"][:4]:
        assert result["exact_occurrence_count"]==1
        assert result["status"]=="single_exact_comparison_view_occurrence_unselected"
        candidate,=result["comparison_documents"];occurrence,=candidate["occurrences"]
        assert occurrence["selector"]["text"]==result["source_identity"]["source_text"]
        assert occurrence["region_intersections"]
        assert candidate["view_report_sha256"]==args["document_inputs"][0]["expected_view_report_sha256"]
        assert candidate["document_report_schema"]==report["documents"][0]["schema"]
    assert "table_coordinates" in json.dumps(report["rows"][1]["comparison_documents"][0]["occurrences"][0]["region_intersections"])
    assert report["rows"][4]["status"]=="zero_exact_comparison_view_occurrences"
    assert all(r["selected_occurrence"] is None and r["governing_source_binding"] is None for r in report["rows"])
    assert all(v is False for r in report["rows"] for v in r["authority"].values())
    assert owner.validate_source_view_inventory(report,prov,rows,
        expected_report_sha256=owner.source_view_inventory_sha256(report),**args)==report


def test_overlapping_occurrences_and_unicode_byte_coordinates_stay_exact(tmp_path):
    prov,rows,args=inputs(tmp_path,texts=("aa",))
    result=owner.prepare_source_view_inventory(prov,rows,**args)["rows"][0]
    assert result["exact_occurrence_count"]==4
    matches=result["comparison_documents"][0]["occurrences"]
    first,second=matches[:2]
    assert second["selector"]["char_start"]==first["selector"]["char_start"]+1
    assert first["selector"]["utf8_byte_start"]>first["selector"]["char_start"]
    assert result["status"]=="multiple_exact_comparison_view_occurrences_unselected" and result["selected_occurrence"] is None


def test_new_view_selectors_cannot_pass_legacy_statutory_source_binding(tmp_path):
    prov,rows,args=inputs(tmp_path)
    report=owner.prepare_source_view_inventory(prov,rows,**args)
    selector=report["rows"][0]["comparison_documents"][0]["occurrences"][0]["selector"]
    descriptor=args["document_inputs"][0]["descriptor"]
    old=legacy.extract_document(RAW,url=descriptor["url"],edition=2024,legal_id="usc:us:10:1")
    with pytest.raises(ValueError):legacy.validate_source_selector(selector,old,RAW)
    assert report["legacy_selector_conversion_performed"] is False


def test_repeated_physical_rows_are_never_collapsed_to_one_source_occurrence(tmp_path):
    raw={"source_span_id":"same","legal_id":"usc:us:10:1","source_text":"Café"}
    prov,rows,args=inputs(tmp_path,rows=[raw,deepcopy(raw)])
    report=owner.prepare_source_view_inventory(prov,rows,**args)
    assert len(report["rows"])==2 and len(set(report["expected_record_sha256s"]))==2
    assert report["rows"][0]["raw_row_sha256"]==report["rows"][1]["raw_row_sha256"]
    assert all(r["exact_occurrence_count"]==1 and r["selected_occurrence"] is None for r in report["rows"])


def test_all_independently_selected_comparison_editions_survive_without_first_choice(tmp_path):
    prov,rows,args=inputs(tmp_path,docs=[document_input(),document_input(edition=2023)])
    report=owner.prepare_source_view_inventory(prov,rows,**args);row,=report["rows"]
    assert len(row["comparison_documents"])==2 and row["exact_occurrence_count"]==2
    assert row["status"]=="multiple_exact_comparison_view_occurrences_unselected"
    assert report["producer_source_correspondence_inferred"] is False


@pytest.mark.parametrize("case",["none","missing_body","mismatched_legal_id"])
def test_missing_comparisons_preserve_explicit_complete_rows(tmp_path,case):
    docs=[] if case=="none" else [document_input(missing=True)] if case=="missing_body" else [document_input(legal_id="usc:us:10:2")]
    prov,rows,args=inputs(tmp_path,texts=("Café","HEADER_SENTINEL"),docs=docs)
    report=owner.prepare_source_view_inventory(prov,rows,**args)
    assert report["row_count"]==2 and report["population_complete"]
    assert all(r["selected_occurrence"] is None for r in report["rows"])
    expected="comparison_view_inventory_incomplete_document_unavailable" if case=="missing_body" else "comparison_view_document_missing"
    assert all(r["status"]==expected for r in report["rows"])


@pytest.mark.parametrize("damage",["view_pin","view_selfseal_only","descriptor_pin","raw_bytes","document_drop","provenance_pin","row_drop","row_reorder"])
def test_independent_full_view_provenance_and_complete_population_pins_are_required(tmp_path,damage):
    prov,rows,args=inputs(tmp_path,texts=("Café","HEADER_SENTINEL"))
    item=args["document_inputs"][0]
    if damage=="view_pin":item["expected_view_report_sha256"]="0"*64
    elif damage=="view_selfseal_only":item["expected_view_report_sha256"]=item["view_report"]["document_report_sha256"]
    elif damage=="descriptor_pin":item["expected_descriptor_sha256"]="0"*64
    elif damage=="raw_bytes":item["raw_bytes"]+=b"changed"
    elif damage=="document_drop":args["document_inputs"]=[]
    elif damage=="provenance_pin":args["expected_provenance_report_sha256"]="0"*64
    elif damage=="row_drop":rows.pop()
    else:rows.reverse()
    with pytest.raises(ValueError):owner.prepare_source_view_inventory(prov,rows,**args)


def test_resealed_view_tampering_still_requires_exact_raw_byte_regeneration(tmp_path):
    prov,rows,args=inputs(tmp_path)
    item=args["document_inputs"][0];item["view_report"]["document"]["document_text"]="invented source"
    item["expected_view_report_sha256"]=views.document_view_report_sha256(item["view_report"])
    args["expected_document_population_sha256"]=owner.view_document_population_sha256(args["document_inputs"])
    with pytest.raises(ValueError):owner.prepare_source_view_inventory(prov,rows,**args)


@pytest.mark.parametrize("damage",["occurrence_drop","region_drop","select_single","authority","row_drop","view_edition"])
def test_resealed_output_changes_fail_complete_independent_inventory_replay(tmp_path,damage):
    prov,rows,args=inputs(tmp_path,texts=("Café","aa"))
    report=owner.prepare_source_view_inventory(prov,rows,**args)
    occurrence=report["rows"][0]["comparison_documents"][0]["occurrences"][0]
    if damage=="occurrence_drop":report["rows"][0]["comparison_documents"][0]["occurrences"]=[]
    elif damage=="region_drop":occurrence["region_intersections"]=[]
    elif damage=="select_single":report["rows"][0]["selected_occurrence"]=deepcopy(occurrence["selector"])
    elif damage=="authority":report["authority"]["producer_original_edition_verified"]=True
    elif damage=="row_drop":report["rows"].pop()
    else:report["documents"][0]["descriptor"]["edition"]=2023
    with pytest.raises(owner.SourceViewInventoryError,match="complete independent regeneration"):
        owner.validate_source_view_inventory(report,prov,rows,expected_report_sha256=owner.source_view_inventory_sha256(report),**args)


@pytest.mark.parametrize("case",["duplicate","excess","unknown"])
def test_closed_finite_document_population_refuses_extra_or_duplicate_inputs(case):
    docs=[document_input(),document_input()] if case=="duplicate" else [document_input(edition=2000+n) for n in range(11)] if case=="excess" else [document_input()]
    if case=="unknown":docs[0]["governing_source_binding"]="invented"
    with pytest.raises(owner.SourceViewInventoryError):owner.view_document_population_sha256(docs)


def test_occurrence_bound_refuses_partial_cross_document_inventory(tmp_path):
    prov,rows,args=inputs(tmp_path,texts=("aa",))
    with pytest.raises(ValueError):owner.prepare_source_view_inventory(prov,rows,max_occurrences=1,**args)


def test_cumulative_inventory_budget_aborts_before_all_physical_rows(tmp_path,monkeypatch):
    prov,rows,args=inputs(tmp_path,texts=("Café",)*12)
    sample=owner.prepare_source_view_inventory(prov,rows,**args)
    ceiling=len(owner._wire(sample["documents"][0]))+len(owner._wire(sample["document_population"]))+len(owner._wire(sample["rows"][0]))*3+4096
    calls=[];original=views.exact_view_occurrences
    def observed(*args,**kwargs):
        calls.append(True);return original(*args,**kwargs)
    monkeypatch.setattr(views,"exact_view_occurrences",observed);monkeypatch.setattr(owner,"MAX_REPORT_BYTES",ceiling)
    with pytest.raises(owner.SourceViewInventoryError,match="byte bound"):
        owner.prepare_source_view_inventory(prov,rows,**args)
    assert 0<len(calls)<len(rows)


def test_aggregate_input_reports_are_bounded_before_copying_population(tmp_path,monkeypatch):
    prov,rows,args=inputs(tmp_path,docs=[document_input(),document_input(edition=2023)])
    sizes=[len(owner._wire(item["view_report"]))+len(owner._wire(item["descriptor"]))+1
           for item in args["document_inputs"]]
    monkeypatch.setattr(owner,"MAX_REPORT_BYTES",max(sizes)+128)
    def deny_copy(value):
        pytest.fail("oversized aggregate document inputs must be refused before snapshot copy")
    monkeypatch.setattr(owner,"deepcopy",deny_copy)
    with pytest.raises(owner.SourceViewInventoryError,match="input byte bound exceeded before snapshot"):
        owner.prepare_source_view_inventory(prov,rows,**args)

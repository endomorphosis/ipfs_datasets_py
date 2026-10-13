"""Synthetic transport fixtures grant no legal or production source authority."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_primary_graph_manifest as manifests
from ipfs_datasets_py.logic.autoformal import legal_primary_graph_reconstruction as reconstruction
from ipfs_datasets_py.logic.autoformal import legal_primary_section_index as owner


def identity(text):
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def node(key, kind="section", legal_id="usc:us:10:1", **more):
    return {"family":"graph_nodes", "entry_cid":identity(key), "node_type":kind,
            "legal_id":legal_id, "label":"Café identical labels", "node_key":key, **more}


def edge(key="edge", source="section", target="package", **more):
    return {"family":"graph_edges", "entry_cid":identity(key), "edge_type":"HAS_SOURCE",
            "source_entry_cid":identity(source), "target_entry_cid":identity(target), **more}


def fixture(tmp_path, *, nodes=None, edges=None):
    root = tmp_path / "snapshot"; root.mkdir()
    nodes = nodes if nodes is not None else [node("section", unknown={"retained":[1,"é",1],"admitted":True}),
        node("package", "source_package", None, source_cid="producer declaration only")]
    edges = edges if edges is not None else [edge()]
    descriptors = []
    for family, rows in (("graph_edges",edges),("graph_nodes",nodes)):
        wrapped = []
        for body in rows:
            raw = json.dumps(body,ensure_ascii=False,indent=2)
            wrapped.append({"entry_cid":body.get("entry_cid") or "", "legal_id":body.get("legal_id") or "",
                "family":family,"record_json":raw,"record_sha256":hashlib.sha256(raw.encode()).hexdigest()})
        relative = "data/graph/" + ("nodes" if family == "graph_nodes" else "edges") + "/part-000000.parquet"
        path = root / relative; path.parent.mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist(wrapped,schema=pa.schema([(k,pa.string()) for k in manifests.FIELDS])),path,row_group_size=1)
        descriptors.append({"family":family,"first_key":None,"last_key":None,"media_type":"application/vnd.apache.parquet",
            "relative_path":relative,"row_count":len(rows),"schema_id":"uscode-graph-node/v1" if family=="graph_nodes" else "uscode-graph-edge/v1",
            "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"size_bytes":path.stat().st_size})
    manifest = {"schema_version":"uscode-sparse-graphrag-release-schema-v2","hf_release_schema_version":"uscode-hf-release/v1",
        "release_profile":"publicus-ir-graphrag/v2","dataset_repo_id":"fixture/primary","release_point":"us/pl/119/102",
        "release_root_cid":identity("root"),"source_revision":"b"*40,"graph_ontology_version":"uscode-legal-graph-ontology/v1",
        "producer":"uscode_hf_release.py","artifacts":descriptors}
    manifest["manifest_digest"] = manifests.digest(manifest)
    raw = json.dumps(manifest).encode()
    selected = manifests.select_primary_graph_manifest(raw,expected_manifest_sha256=hashlib.sha256(raw).hexdigest(),
        repository="fixture/primary",revision="a"*40,expected_release_identity={k:manifest[k] for k in manifests.RELEASE_FIELDS},
        expected_graph_population={"graph_nodes":{"files":1,"rows":len(nodes)},"graph_edges":{"files":1,"rows":len(edges)}})
    path = tmp_path / "candidate.jsonl"
    report = reconstruction.reconstruct_to_jsonl(selected,root,path,expected_selection_sha256=selected["selection_sha256"])
    args = {"reconstruction_report":report,"expected_candidate_sha256":report["candidate_sha256"],
            "expected_reconstruction_sha256":report["reconstruction_sha256"]}
    return path,args


def test_exact_lookup_preserves_full_original_rows_and_distinct_identities(tmp_path):
    path,args = fixture(tmp_path)
    original = [json.loads(x) for x in path.read_bytes().splitlines()][1:]
    with owner.PrimarySectionIndex(path,**args) as index:
        result = index.lookup_sections("usc:us:10:1")
        assert index.guard() and result["index_sha256"] == index.index_sha256
        assert index.primary_identity["revision"] == "a"*40
        assert index.primary_identity["source_revision"] == "b"*40
        section, = result["sections"]
        assert section["issues"] == [] and result["issues"] == []
        package, = section["source_packages"]
        assert section["entry_cid"] == identity("section") != package["entry_cid"] == identity("package")
        assert section["section_observation"] == original[1]
        assert package["source_package_observation"] == original[2]
        assert package["has_source_observations"] == section["has_source_observations"] == original[:1]
        assert section["section_observation"]["original_body"]["unknown"]["admitted"] is True
        assert all(value is False for value in result["authority"].values())
        assert index.receipt["all_original_candidate_rows_retained"] is True
        assert index.receipt["rows"] == 3
        receipt = index.receipt; receipt["rows"] = 0
        assert index.receipt["rows"] == 3
        temporary = index._db_path.parent
    assert not temporary.exists()
    with pytest.raises(owner.PrimarySectionIndexError,match="active guarded"):
        index.lookup_sections("usc:us:10:1")


@pytest.mark.parametrize("legal_id", ["10 USC 1","usc:us:010:1","USC:US:10:1"," usc:us:10:1","usc:us:10:1 "])
def test_literal_lookup_never_normalizes_aliases_or_whitespace(tmp_path,legal_id):
    path,args = fixture(tmp_path)
    with owner.PrimarySectionIndex(path,**args) as index:
        result = index.lookup_sections(legal_id)
        assert result["sections"] == [] and result["issues"] == [{"code":"literal_section_not_unique","candidate_count":0}]


@pytest.mark.parametrize("damage",["two_sections","duplicate","conflict","missing_target","wrong_kind","reversed","duplicate_edge","duplicate_package","conflicting_edge","unresolved"])
def test_ambiguity_missing_surplus_and_quarantine_are_retained(tmp_path,damage):
    nodes = [node("section"),node("package","source_package",None)]
    edges = [edge()]
    if damage == "two_sections": nodes.append(node("other"))
    elif damage == "duplicate": nodes.append(deepcopy(nodes[0]))
    elif damage == "conflict": nodes.append(node("section",label="different body"))
    elif damage == "missing_target": edges=[edge(target="absent")]
    elif damage == "wrong_kind": nodes[1]["node_type"]="release_point"
    elif damage == "reversed": edges=[edge(source="package",target="section")]
    elif damage == "duplicate_edge": edges.append(deepcopy(edges[0]))
    elif damage == "duplicate_package": nodes.append(deepcopy(nodes[1]))
    elif damage == "conflicting_edge": edges.append(edge(target="section"))
    else: nodes[0].pop("entry_cid")
    path,args = fixture(tmp_path,nodes=nodes,edges=edges)
    with owner.PrimarySectionIndex(path,**args) as index:
        result=index.lookup_sections("usc:us:10:1")
        assert index.receipt["rows"]==len(nodes)+len(edges)
        if damage in ("two_sections","duplicate","conflict"):
            assert len(result["sections"])==2 and result["issues"]
        section=result["sections"][0]
        if damage=="duplicate_edge":
            assert len(section["has_source_observations"])==2 and len(section["source_packages"])==1
            assert len(section["source_packages"][0]["has_source_observations"])==2
            assert "has_source_transport_quarantined" in {x["code"] for x in section["issues"]}
        elif damage=="duplicate_package":
            assert len(section["source_packages"])==2
            assert "source_package_transport_quarantined" in {x["code"] for x in section["issues"]}
        elif damage=="conflicting_edge":
            assert len(section["source_packages"])==1 and len(section["has_source_observations"])==2
            assert "has_source_transport_quarantined" in {x["code"] for x in section["issues"]}
        elif damage=="wrong_kind":
            assert section["source_packages"]==[] and len(section["other_source_targets"])==1
        elif damage in ("missing_target","reversed","unresolved"):
            assert section["source_packages"]==[] and section["issues"]
            if damage=="reversed": assert len(section["incoming_has_source_observations"])==1
        if damage in ("duplicate","conflict","unresolved"): assert section["issues"]


def test_index_receipt_determinism_excludes_local_path_and_database_bytes(tmp_path):
    path,args=fixture(tmp_path)
    with owner.PrimarySectionIndex(path,**args) as index: first=index.receipt
    other=tmp_path/"relocated.jsonl"; other.write_bytes(path.read_bytes())
    with owner.PrimarySectionIndex(other,**args) as index: second=index.receipt
    assert first==second
    assert str(tmp_path) not in json.dumps(first)


@pytest.mark.parametrize("damage",["report_pin","candidate_pin","resealed_report","shrink","authority","custody","row_seal","noncanonical"])
def test_independent_pins_complete_population_and_per_row_contracts(tmp_path,damage):
    path,args=fixture(tmp_path)
    if damage=="report_pin": args["expected_reconstruction_sha256"]="0"*64
    elif damage=="candidate_pin": args["expected_candidate_sha256"]="0"*64
    elif damage=="resealed_report":
        args["reconstruction_report"]["rows"]-=1
        args["reconstruction_report"]["reconstruction_sha256"]=owner._digest({k:v for k,v in args["reconstruction_report"].items() if k!="reconstruction_sha256"})
    else:
        values=[json.loads(x) for x in path.read_bytes().splitlines()]
        if damage=="shrink": values.pop()
        elif damage=="authority": values[1]["authority"]["admitted"]=True
        elif damage=="custody": values[1]["custody"]["revision"]="c"*40
        else: values[1]["candidate_row_sha256"]="0"*64
        raw=b"".join(owner._wire(x)+b"\n" for x in values)
        if damage=="noncanonical": raw=raw.replace(b'"schema":',b'"schema" :',1)
        path.write_bytes(raw)
        # Adversarial caller can supply a new transport hash, but not bypass
        # ordered row/authority/custody/census checks with a recomputed report.
        report=args["reconstruction_report"]; report["candidate_bytes"]=len(raw); report["candidate_sha256"]=hashlib.sha256(raw).hexdigest()
        report["reconstruction_sha256"]=owner._digest({k:v for k,v in report.items() if k!="reconstruction_sha256"})
        args["expected_candidate_sha256"]=report["candidate_sha256"]; args["expected_reconstruction_sha256"]=report["reconstruction_sha256"]
    with pytest.raises((owner.PrimarySectionIndexError,manifests.PrimaryGraphManifestError)):
        with owner.PrimarySectionIndex(path,**args): pass


@pytest.mark.parametrize("limit,value",[("max_rows",1),("max_candidate_bytes",32),("max_line_bytes",32),("max_index_bytes",16384)])
def test_build_resource_limits_fail_without_partial_index(tmp_path,limit,value):
    path,args=fixture(tmp_path)
    with pytest.raises(owner.PrimarySectionIndexError):
        with owner.PrimarySectionIndex(path,**args,limits={limit:value}): pass


@pytest.mark.parametrize("limit,value",[("max_lookup_rows",2),("max_lookup_bytes",512)])
def test_complete_lookup_bounds_refuse_truncation(tmp_path,limit,value):
    path,args=fixture(tmp_path)
    with owner.PrimarySectionIndex(path,**args,limits={limit:value}) as index:
        with pytest.raises(owner.PrimarySectionIndexError,match="lookup.*bound"):
            index.lookup_sections("usc:us:10:1")


@pytest.mark.parametrize("damage",["symlink","hardlink","replace","inplace","database_replace"])
def test_source_and_scratch_custody_are_guarded_before_and_after_queries(tmp_path,damage):
    path,args=fixture(tmp_path)
    if damage=="symlink":
        alias=tmp_path/"alias.jsonl"; alias.symlink_to(path); path=alias
    elif damage=="hardlink":
        alias=tmp_path/"alias.jsonl"; alias.hardlink_to(path)
    if damage in ("symlink","hardlink"):
        with pytest.raises(owner.PrimarySectionIndexError):
            with owner.PrimarySectionIndex(path,**args): pass
        return
    with pytest.raises(owner.PrimarySectionIndexError):
        with owner.PrimarySectionIndex(path,**args) as index:
            if damage=="replace":
                other=tmp_path/"other.jsonl"; other.write_bytes(path.read_bytes()); other.replace(path)
            elif damage=="inplace":
                with path.open("r+b") as stream: stream.write(b" ")
            else:
                other=tmp_path/"other.sqlite"; other.write_bytes(index._db_path.read_bytes()); other.replace(index._db_path)
                foreign=index._db_path
            index.guard()
    if damage=="database_replace":
        assert foreign.exists()  # Custody failure never deletes a replacement.
        foreign.unlink(); foreign.parent.rmdir()


def test_lookup_queries_use_population_independent_exact_indexes(tmp_path):
    path,args=fixture(tmp_path)
    with owner.PrimarySectionIndex(path,**args) as index:
        for sql,args_ in (("SELECT payload FROM rows WHERE family='graph_nodes' AND kind='section' AND legal_id=? ORDER BY ordinal",("usc:us:10:1",)),
                          ("SELECT payload FROM rows WHERE family='graph_nodes' AND entry=? ORDER BY ordinal",(identity("package"),)),
                          ("SELECT payload FROM rows WHERE family='graph_edges' AND kind='HAS_SOURCE' AND src=? ORDER BY ordinal",(identity("section"),))):
            plan=index._db.execute("EXPLAIN QUERY PLAN "+sql,args_).fetchall()
            assert any("SEARCH rows USING INDEX" in row[3] for row in plan)


def test_query_only_cannot_be_disabled_without_failing_public_guard(tmp_path):
    path,args=fixture(tmp_path)
    with pytest.raises(owner.PrimarySectionIndexError,match="query-only"):
        with owner.PrimarySectionIndex(path,**args) as index:
            index._db.execute("PRAGMA query_only=OFF")
            index.lookup_sections("usc:us:10:1")


@pytest.mark.parametrize("target",["receipt","primary_identity"])
def test_retained_metadata_cannot_redirect_identity_with_old_receipt_digest(tmp_path,target):
    path,args=fixture(tmp_path)
    with pytest.raises(owner.PrimarySectionIndexError,match="metadata differs"):
        with owner.PrimarySectionIndex(path,**args) as index:
            if target=="receipt": index._receipt["rows"]=0
            else: index._primary_identity["revision"]="c"*40
            index.lookup_sections("usc:us:10:1")


def test_scratch_directory_open_failure_never_uses_cwd_or_masks_original_error(tmp_path,monkeypatch):
    path,args=fixture(tmp_path)
    foreign=tmp_path/"sections.sqlite"; foreign.write_bytes(b"foreign cwd file")
    monkeypatch.chdir(tmp_path)
    original_open=owner.os.open
    def fail_directory_open(path,flags,*args,**kwargs):
        if flags & owner.os.O_DIRECTORY:
            raise OSError("synthetic scratch directory open failure")
        return original_open(path,flags,*args,**kwargs)
    monkeypatch.setattr(owner.os,"open",fail_directory_open)
    index=owner.PrimarySectionIndex(path,**args)
    with pytest.raises(OSError,match="synthetic scratch directory open failure"):
        index.__enter__()
    assert foreign.read_bytes()==b"foreign cwd file"
    assert index._stream is None and index._db is None and index._scratch_fd is None


def test_producer_package_and_release_point_roles_preserve_all_witnesses(tmp_path):
    release=node("release","release_point",None,node_key="release_point:us/pl/119/102",label="us/pl/119/102")
    nodes=[node("section"),node("package","source_package",None),release]
    # The published wrapper omits producer payload.role. Recognition uses only
    # exact target kind and the independently pinned manifest identity.
    edges=[edge(),edge("release-edge",target="release"),edge("second-release-witness",target="release")]
    path,args=fixture(tmp_path,nodes=nodes,edges=edges)
    with owner.PrimarySectionIndex(path,**args) as index:
        result=index.lookup_sections("usc:us:10:1"); section,=result["sections"]
        assert section["issues"]==[] and section["other_source_targets"]==[]
        assert len(section["source_packages"])==1 and len(section["has_source_observations"])==3
        point,=section["release_points"]
        assert point["release_point_observation"]["original_body"]==release
        assert point["entry_cid"]==identity("release")
        assert len(point["has_source_observations"])==2
        assert index.primary_identity["release_point"]=="us/pl/119/102"
        census=index.receipt["has_source_relationship_census"]
        assert census["all_declared_has_source_rows"]==3
        assert census["typed_section_to_source_package_rows"]==1
        assert census["recognized_section_release_point_rows"]==2
        assert census["non_source_package_directed_relationship_rows"]==2
        assert census["other_or_unresolved_directed_relationship_rows"]==0
        assert index.receipt["lookup_profile"].endswith("/v2")
        assert all(value is False for value in result["authority"].values())


@pytest.mark.parametrize("damage",["label","node_key","missing_label","missing_key","alias_label","different_release","duplicate_node","selfloop","wrong_kind"])
def test_release_point_requires_exact_manifest_identity_and_unique_typed_target(tmp_path,damage):
    release=node("release","release_point",None,node_key="release_point:us/pl/119/102",label="us/pl/119/102")
    nodes=[node("section"),node("package","source_package",None),release]
    edges=[edge(),edge("release-edge",target="release")]
    if damage=="label": release["label"]="arbitrary label"
    elif damage=="node_key": release["node_key"]="arbitrary key"
    elif damage=="missing_label": release.pop("label")
    elif damage=="missing_key": release.pop("node_key")
    elif damage=="alias_label": release["label"]=" us/pl/119/102 "
    elif damage=="different_release": release.update(label="us/pl/118/45",node_key="release_point:us/pl/118/45")
    elif damage=="duplicate_node": nodes.append(deepcopy(release))
    elif damage=="selfloop": edges[1]=edge("release-edge",target="section")
    else: release["node_type"]="code"
    path,args=fixture(tmp_path,nodes=nodes,edges=edges)
    with owner.PrimarySectionIndex(path,**args) as index:
        section,=index.lookup_sections("usc:us:10:1")["sections"]
        assert section["release_points"]==[] and section["other_source_targets"]
        assert len(section["has_source_observations"])==2 and section["issues"]
        census=index.receipt["has_source_relationship_census"]
        assert census["recognized_section_release_point_rows"]==0
        assert census["other_or_unresolved_directed_relationship_rows"]==1


def test_quarantined_release_edge_retains_point_and_all_relationship_blockers(tmp_path):
    release=node("release","release_point",None,node_key="release_point:us/pl/119/102",label="us/pl/119/102")
    witness=edge("release-edge",target="release")
    path,args=fixture(tmp_path,nodes=[node("section"),node("package","source_package",None),release],
                      edges=[edge(),witness,deepcopy(witness)])
    with owner.PrimarySectionIndex(path,**args) as index:
        section,=index.lookup_sections("usc:us:10:1")["sections"]
        assert len(section["release_points"])==1 and len(section["release_points"][0]["has_source_observations"])==2
        assert sum(issue["code"]=="has_source_transport_quarantined" for issue in section["issues"])==2

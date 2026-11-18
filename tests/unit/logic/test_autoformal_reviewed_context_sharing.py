"""Bounded lossless context data transport; no model execution permission."""
import pytest
from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker


def _complete_three_example_context_for_sharing():
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as fixtures
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    helper, options, populations, _, _ = fixtures._rich_v3_heldout_case()
    training = options["reviewed_training_context"]
    for row in training["retrieval_rows"]:
        row["retrieved_ids"] = [record["id"] for record in populations["train"]]
    payload = structured._consume_reviewed_contexts(**training,
        expected_query_rows_sha256=structured.reviewed_context_inputs_sha256(training["query_rows"]),
        expected_retrieval_rows_sha256=structured.reviewed_context_inputs_sha256(training["retrieval_rows"]),
        consumer=lambda value:value,heldout_evaluation=options["binding"].receipt()["heldout_evaluation"],_admission_version="v3")
    context = {"profile":worker.REVIEWED_GENERATION_CONTEXT_PROFILE,"mode":"rich_full_ast", "permitted":[],
        "retrieved":[{"id":row["id"],"content":row} for row in payload["rows"][0]["examples"]]}
    return context,populations


def test_shared_context_preserves_complete_reviewed_three_example_component():
    context,populations = _complete_three_example_context_for_sharing()
    raw = inputs._reviewed_wire(context)
    assert len(raw)>worker.REVIEWED_GENERATION_CONTEXT_MAX_BYTES
    packed = inputs.pack_reviewed_context_json_v1(context)
    assert len(inputs._reviewed_wire(packed))<=worker.REVIEWED_GENERATION_CONTEXT_MAX_BYTES
    restored = inputs.unpack_reviewed_context_json_v1(packed)
    assert inputs._reviewed_wire(restored)==raw
    assert len(restored["retrieved"])==3
    assert {row["id"] for row in restored["retrieved"]}=={row["id"] for row in populations["train"]}
    for record in restored["retrieved"]:
        original = next(row for row in populations["train"] if row["id"]==record["id"])
        assert record["content"]["canonical_ir"]==original["canonical_ir"]
        assert record["content"]["source_text"]==original["source_text"]


def test_shared_context_roundtrip_preserves_scalar_types_order_and_detached_occurrences():
    common={"roles":["clerk","supervisor"],"scope":{"deadline":"calendar days","exception":None},
        "source":"Café \u00e9 and e\u0301", "values":[1,1.0,-0.0,True,False,None]}
    context={"a":common,"b":common,"ordered":["O","P","F"]}
    packed=inputs.pack_reviewed_context_json_v1(context)
    assert packed==inputs.pack_reviewed_context_json_v1(context)
    restored=inputs.unpack_reviewed_context_json_v1(packed)
    assert inputs._reviewed_wire(restored)==inputs._reviewed_wire(context)
    assert restored["a"] is not restored["b"]
    assert type(restored["a"]["values"][0]) is int and type(restored["a"]["values"][1]) is float
    restored["a"]["roles"][0]="changed"
    assert restored["b"]["roles"][0]==context["a"]["roles"][0]=="clerk"


@pytest.mark.parametrize("damage",["boolean-root","cycle","forward-reference","duplicate-key","unreachable-node","duplicate-value"])
def test_shared_context_refuses_malformed_or_noncanonical_reference_tables(damage):
    import copy
    packed=copy.deepcopy(inputs.pack_reviewed_context_json_v1({"a":"a","b":["a"]}))
    root=packed["root"]
    if damage=="boolean-root":packed["root"]=False
    elif damage=="cycle":packed["nodes"][root]=["array",root]
    elif damage=="forward-reference":packed["nodes"][0]=["array",root]
    elif damage=="duplicate-key":packed["nodes"][root]=["object",0,0,0,0]
    elif damage=="unreachable-node":packed["nodes"].append("unused")
    else:packed.update(nodes=["a","a",["object",0,1]],root=2)
    with pytest.raises(ValueError):inputs.unpack_reviewed_context_json_v1(packed)


def test_shared_context_rejects_expansion_bomb_before_materializing_tree():
    packed={"schema":inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA,"nodes":[None],"root":24}
    packed["nodes"] += [["array",index-1,index-1] for index in range(1,25)]
    with pytest.raises(ValueError,match="expanded"):
        inputs.unpack_reviewed_context_json_v1(packed)


@pytest.mark.parametrize("kind",["encoded","logical"])
def test_shared_context_refuses_complete_overbudget_data_without_truncation(kind):
    value={"complete":"x"*(20000 if kind=="encoded" else 262145)}
    before=inputs._reviewed_wire(value)
    with pytest.raises(ValueError):inputs.pack_reviewed_context_json_v1(value)
    assert inputs._reviewed_wire(value)==before


def test_shared_context_data_codec_does_not_enable_existing_decoder_profile():
    packed=inputs.pack_reviewed_context_json_v1({"permitted":[],"retrieved":[]})
    source={"profile":worker.REVIEWED_GENERATION_CONTEXT_SOURCE_PROFILE,"source_text":"Source only.",
        "governing_context":{},"source_binding":{},"selection_context":{},"context":packed}
    with pytest.raises(worker.TrainingJobValidationError,match="context DATA profile"):
        worker._reviewed_generation_context_wire(source,set())



def _shared_wire_source(context):
    return {"profile":"reviewed-source-with-shared-training-context/v1",
        "source_text":"Source only.","governing_context":{},"source_binding":{},
        "selection_context":{},"context":inputs.pack_reviewed_context_json_v1(context)}


def test_shared_generation_wire_transports_all_three_reviewed_examples():
    context,populations=_complete_three_example_context_for_sharing()
    data={key:context[key] for key in ("permitted","retrieved")}
    source=_shared_wire_source(data)
    raw=worker._reviewed_generation_context_wire(source,{"heldout-query"})
    assert raw==inputs._reviewed_wire(source["context"]).decode("utf-8")
    assert inputs.unpack_reviewed_context_json_v1(inputs._reviewed_json(raw.encode("utf-8")))==data
    assert len(data["retrieved"])==3
    assert len(raw.encode("utf-8"))<=worker.REVIEWED_GENERATION_CONTEXT_MAX_BYTES


@pytest.mark.parametrize("damage",["target-field","query-id","duplicate-id","extra-key","empty","malformed-table","legacy-profile"])
def test_shared_generation_wire_screens_expanded_context_before_use(damage):
    data={"permitted":[],"retrieved":[{"id":"training-example","content":{"source_text":"Complete source","ordered_roles":["actor","recipient"]}}]}
    if damage=="target-field":data["retrieved"][0]["content"]["nested"]={"gold_target":"forbidden"}
    elif damage=="query-id":data["retrieved"][0]["content"]["nested"]=["heldout-query"]
    elif damage=="duplicate-id":data["permitted"]=list(data["retrieved"])
    elif damage=="extra-key":data["unexpected"]=True
    elif damage=="empty":data["retrieved"]=[]
    source=_shared_wire_source(data)
    if damage=="malformed-table":source["context"]["root"]=False
    elif damage=="legacy-profile":source["profile"]=worker.REVIEWED_GENERATION_CONTEXT_SOURCE_PROFILE
    with pytest.raises(worker.TrainingJobValidationError):
        worker._reviewed_generation_context_wire(source,{"heldout-query"})


def test_shorttag_context_preserves_typed_scalars_order_unicode_and_v1_domain():
    value={"one":{"roles":["actor","recipient"],"values":[1,1.0,True,False,None,-0.0],"source":"Café e\u0301"}}
    value["two"]=value["one"]
    packed=inputs.pack_reviewed_context_json_v2(value)
    assert packed["schema"]==inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2
    assert all(type(node[0]) is int and node[0] in (0,1) for node in packed["nodes"] if type(node) is list)
    restored=inputs.unpack_reviewed_context_json_v2(packed)
    assert inputs._reviewed_wire(restored)==inputs._reviewed_wire(value)
    assert restored["one"] is not restored["two"]
    with pytest.raises(ValueError):inputs.unpack_reviewed_context_json_v1(packed)
    with pytest.raises(ValueError):inputs.unpack_reviewed_context_json_v2(inputs.pack_reviewed_context_json_v1(value))


def test_shorttag_context_keeps_complete_reviewed_component():
    context,populations=_complete_three_example_context_for_sharing()
    packed=inputs.pack_reviewed_context_json_v2(context)
    assert inputs._reviewed_wire(inputs.unpack_reviewed_context_json_v2(packed))==inputs._reviewed_wire(context)
    assert len(inputs.unpack_reviewed_context_json_v2(packed)["retrieved"])==len(populations["train"])==3


@pytest.mark.parametrize("damage",["boolean-tag","float-tag","text-tag","unknown-tag","boolean-reference","cycle","forward-reference","duplicate-key","unreachable-node","duplicate-value","boolean-root"])
def test_shorttag_context_reuses_closed_canonical_reference_validation(damage):
    import copy
    packed=copy.deepcopy(inputs.pack_reviewed_context_json_v2({"a":"a","b":["a"]}));root=packed["root"]
    if damage=="boolean-tag":packed["nodes"][root][0]=False
    elif damage=="float-tag":packed["nodes"][root][0]=0.0
    elif damage=="text-tag":packed["nodes"][root][0]="object"
    elif damage=="unknown-tag":packed["nodes"][root][0]=2
    elif damage=="boolean-reference":packed["nodes"][root][1]=True
    elif damage=="cycle":packed["nodes"][root]=[1,root]
    elif damage=="forward-reference":packed["nodes"][0]=[1,root]
    elif damage=="duplicate-key":packed["nodes"][root]=[0,0,0,0,0]
    elif damage=="unreachable-node":packed["nodes"].append("unused")
    elif damage=="boolean-root":packed["root"]=False
    else:packed.update(nodes=["a","a",[0,0,1]],root=2)
    with pytest.raises(ValueError):inputs.unpack_reviewed_context_json_v2(packed)


@pytest.mark.parametrize("kind",["encoded","logical","expansion"])
def test_shorttag_context_does_not_broaden_existing_byte_or_expansion_bounds(kind):
    if kind=="expansion":
        packed={"schema":inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2,"nodes":[None]+[[1,i-1,i-1] for i in range(1,25)],"root":24}
        with pytest.raises(ValueError,match="expanded"):inputs.unpack_reviewed_context_json_v2(packed)
    else:
        value={"complete":"x"*(20000 if kind=="encoded" else 262145)}
        with pytest.raises(ValueError):inputs.pack_reviewed_context_json_v2(value)


@pytest.mark.parametrize("operation",["pack","unpack"])
def test_shorttag_context_closing_fence_separates_boolean_numeric_mutation(monkeypatch,operation):
    if operation=="pack":
        value={"value":1};original=inputs.pack_reviewed_context_json_v1
        def mutate(offered):
            result=original(offered);value["value"]=True;return result
        monkeypatch.setattr(inputs,"pack_reviewed_context_json_v1",mutate)
        with pytest.raises(ValueError,match="changed"):inputs.pack_reviewed_context_json_v2(value)
    else:
        value=inputs.pack_reviewed_context_json_v2({"value":1});original=inputs.unpack_reviewed_context_json_v1
        def mutate(offered):
            result=original(offered);value["root"]=True;return result
        monkeypatch.setattr(inputs,"unpack_reviewed_context_json_v1",mutate)
        with pytest.raises(ValueError,match="changed"):inputs.unpack_reviewed_context_json_v2(value)


@pytest.mark.parametrize("damage",[None,"target-field","query-id","duplicate-id","extra-key","empty","malformed-table","v1-profile","v1-codec"])
def test_shorttag_generation_wire_retains_expanded_leakage_and_version_guards(damage):
    data={"permitted":[],"retrieved":[{"id":"training-example","content":{"source_text":"Complete source","ordered_roles":["actor","recipient"]}}]}
    if damage=="target-field":data["retrieved"][0]["content"]["nested"]={"gold_target":"forbidden"}
    elif damage=="query-id":data["retrieved"][0]["content"]["nested"]=["heldout-query"]
    elif damage=="duplicate-id":data["permitted"]=list(data["retrieved"])
    elif damage=="extra-key":data["unexpected"]=True
    elif damage=="empty":data["retrieved"]=[]
    source=_shared_wire_source(data);source["profile"]=worker.REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V2
    source["context"]=inputs.pack_reviewed_context_json_v2(data)
    if damage=="malformed-table":source["context"]["root"]=False
    elif damage=="v1-profile":source["profile"]=worker.REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE
    elif damage=="v1-codec":source["context"]=inputs.pack_reviewed_context_json_v1(data)
    if damage is None:
        assert worker._reviewed_generation_context_wire(source,{"heldout-query"})==inputs._reviewed_wire(source["context"]).decode()
    else:
        with pytest.raises(worker.TrainingJobValidationError):worker._reviewed_generation_context_wire(source,{"heldout-query"})

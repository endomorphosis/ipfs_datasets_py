"""Bounded lossless context data transport; no model execution permission."""
import pytest
from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker


def test_keylayout_context_preserves_exact_types_order_empty_layouts_and_detached_values():
    shared = {"roles": ["actor", "recipient"], "values": [1, 1.0, True, False, None, -0.0],
              "source": "Café e\u0301", "empty": {}}
    value = {"a": shared, "b": shared, "ordered": ["must", "may", "forbidden"]}
    before = inputs._reviewed_wire(value)
    packed = inputs.pack_reviewed_context_json_v3(value)
    assert packed["schema"] == inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V3
    assert packed == inputs.pack_reviewed_context_json_v3(value)
    restored = inputs.unpack_reviewed_context_json_v3(packed)
    assert inputs._reviewed_wire(restored) == before
    assert restored["a"] is not restored["b"]
    restored["a"]["roles"][0] = "changed"
    assert restored["b"]["roles"][0] == "actor"
    assert inputs._reviewed_wire(value) == before


@pytest.mark.parametrize("value", [None, True, 1, 1.0, -0.0, "é", [], {}])
def test_keylayout_context_accepts_scalar_array_and_empty_object_roots(value):
    packed = inputs.pack_reviewed_context_json_v3(value)
    assert inputs._reviewed_wire(inputs.unpack_reviewed_context_json_v3(packed)) == inputs._reviewed_wire(value)


def test_keylayout_context_matches_independent_literal_first_use_layout_order():
    expected = dict(schema="reviewed-lossless-shared-context/v3", layouts=[[1], [5], [0, 4]],
        nodes=["a", "x", 1, [0, 0, 2], "b", "y", 2, [0, 1, 6], [0, 2, 3, 7]], root=8)
    value = {"a": {"x": 1}, "b": {"y": 2}}
    assert inputs._reviewed_wire(inputs.pack_reviewed_context_json_v3(value)) == inputs._reviewed_wire(expected)
    assert inputs._reviewed_wire(inputs.unpack_reviewed_context_json_v3(expected)) == inputs._reviewed_wire(value)


def test_keylayout_context_rejects_semantically_identical_remapped_layout_permutation():
    value = {"a": {"x": 1}, "b": {"y": 2}}
    packed = inputs.pack_reviewed_context_json_v3(value)
    packed["layouts"].reverse()
    count = len(packed["layouts"])
    reconstructed = []
    for node in packed["nodes"]:
        if type(node) is list and node[0] == 0:
            node[1] = count-1-node[1]
            keys = packed["layouts"][node[1]]
            reconstructed.append([0, *[ref for pair in zip(keys, node[2:], strict=True) for ref in pair]])
        else:
            reconstructed.append(node)
    v2 = dict(schema=inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2,
              nodes=reconstructed, root=packed["root"])
    assert inputs._reviewed_wire(inputs.unpack_reviewed_context_json_v2(v2)) == inputs._reviewed_wire(value)
    with pytest.raises(ValueError, match="canonical reachable"):
        inputs.unpack_reviewed_context_json_v3(packed)


@pytest.mark.parametrize("damage", ["boolean-tag", "float-tag", "unknown-tag", "boolean-layout",
    "negative-layout", "unknown-layout", "missing-layout", "wrong-arity", "boolean-key",
    "non-string-key", "repeated-key", "reversed-keys", "unreachable-layout", "duplicate-layout",
    "boolean-value-reference", "cycle", "boolean-root", "extra-field"])
def test_keylayout_context_rejects_noncanonical_layout_and_reference_tables(damage):
    import copy
    packed = copy.deepcopy(inputs.pack_reviewed_context_json_v3({"a": "a", "b": ["a"]}))
    root = packed["root"]; node = packed["nodes"][root]; layout = packed["layouts"][node[1]]
    if damage == "boolean-tag": node[0] = False
    elif damage == "float-tag": node[0] = 0.0
    elif damage == "unknown-tag": node[0] = 2
    elif damage == "boolean-layout": node[1] = True
    elif damage == "negative-layout": node[1] = -1
    elif damage == "unknown-layout": node[1] = len(packed["layouts"])
    elif damage == "missing-layout": packed["layouts"] = []
    elif damage == "wrong-arity": node.append(0)
    elif damage == "boolean-key": layout[0] = False
    elif damage == "non-string-key": layout[0] = root
    elif damage == "repeated-key": layout[1] = layout[0]
    elif damage == "reversed-keys": layout.reverse()
    elif damage == "unreachable-layout": packed["layouts"].append([])
    elif damage == "duplicate-layout": packed["layouts"].append(list(layout))
    elif damage == "boolean-value-reference": node[2] = True
    elif damage == "cycle": node[2] = root
    elif damage == "boolean-root": packed["root"] = False
    else: packed["extra"] = True
    with pytest.raises(ValueError): inputs.unpack_reviewed_context_json_v3(packed)


def test_keylayout_context_preserves_array_scalar_node_ids_and_both_wire_bounds():
    value = [{"actor": "clerk", "recipient": "agency", "sequence": [i, None]} for i in range(20)]
    old = inputs.pack_reviewed_context_json_v2(value)
    new = inputs.pack_reviewed_context_json_v3(value)
    assert new["root"] == old["root"] and len(new["nodes"]) == len(old["nodes"])
    reconstructed = []
    for previous, offered in zip(old["nodes"], new["nodes"], strict=True):
        if type(previous) is list and previous[0] == 0:
            keys = new["layouts"][offered[1]]
            rebuilt = [0, *[ref for pair in zip(keys, offered[2:], strict=True) for ref in pair]]
            assert rebuilt == previous
            reconstructed.append(rebuilt)
        else:
            assert inputs._reviewed_wire(previous) == inputs._reviewed_wire(offered)
            reconstructed.append(offered)
    assert inputs._reviewed_wire(dict(schema=inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2,
        nodes=reconstructed, root=new["root"])) == inputs._reviewed_wire(old)
    assert len(inputs._reviewed_wire(new)) < len(inputs._reviewed_wire(old)) <= 16384


def test_keylayout_context_keeps_every_complete_example_in_all_three_aggregate_queries():
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as fixtures
    _, options, _ = fixtures._aggregate_v4_heldout_case()
    assert len(options["rows"]) == 3
    for query in options["rows"]:
        context = dict(permitted=[], retrieved=options["retrieved_examples"][query["id"]])
        before = inputs._reviewed_wire(context)
        packed = inputs.pack_reviewed_context_json_v3(context)
        restored = inputs.unpack_reviewed_context_json_v3(packed)
        assert inputs._reviewed_wire(restored) == before
        assert len(restored["retrieved"]) == len(context["retrieved"])
        assert len(inputs._reviewed_wire(packed)) < len(inputs._reviewed_wire(inputs.pack_reviewed_context_json_v2(context)))
        assert inputs._reviewed_wire(context) == before


def test_keylayout_context_rejects_small_v3_with_oversized_reconstructed_v2():
    value = [{f"key-{j:02}": i if j == 0 else None for j in range(40)} for i in range(120)]
    graph = inputs._reviewed_shared_context_json_graph(value)
    layouts, seen, nodes = [], {}, []
    for original in graph["nodes"]:
        if type(original) is list and original[0] == "object":
            keys = tuple(original[1::2])
            if keys not in seen: seen[keys] = len(layouts); layouts.append(list(keys))
            nodes.append([0, seen[keys], *original[2::2]])
        elif type(original) is list: nodes.append([1, *original[1:]])
        else: nodes.append(original)
    packed = dict(schema=inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V3,
                  layouts=layouts, nodes=nodes, root=graph["root"])
    assert len(inputs._reviewed_wire(packed)) <= 16384
    with pytest.raises(ValueError, match="reconstructed v2"): inputs.unpack_reviewed_context_json_v3(packed)
    with pytest.raises(ValueError, match="encoded byte bound"): inputs.pack_reviewed_context_json_v3(value)


@pytest.mark.parametrize("kind", ["expanded", "depth", "nodes", "layouts", "encoded"])
def test_keylayout_context_keeps_existing_expansion_depth_population_and_wire_bounds(kind):
    packed = dict(schema=inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V3, layouts=[], nodes=[None], root=0)
    if kind == "expanded": packed.update(nodes=[None]+[[1, i-1, i-1] for i in range(1, 25)], root=24)
    elif kind == "depth": packed.update(nodes=[None]+[[1, i-1] for i in range(1, 67)], root=66)
    elif kind == "nodes": packed.update(nodes=[0]*4097, root=4096)
    elif kind == "layouts": packed["layouts"] = [[] for _ in range(4097)]
    else: packed["nodes"] = ["x"*20000]
    with pytest.raises(ValueError): inputs.unpack_reviewed_context_json_v3(packed)


@pytest.mark.parametrize("version", [1, 2])
def test_keylayout_context_is_explicitly_separate_from_previous_codec_domains(version):
    old_pack = getattr(inputs, f"pack_reviewed_context_json_v{version}")
    old_unpack = getattr(inputs, f"unpack_reviewed_context_json_v{version}")
    with pytest.raises(ValueError): inputs.unpack_reviewed_context_json_v3(old_pack({"a": 1}))
    with pytest.raises(ValueError): old_unpack(inputs.pack_reviewed_context_json_v3({"a": 1}))


@pytest.mark.parametrize("operation", ["pack", "unpack"])
def test_keylayout_context_closing_fence_rejects_input_type_mutation(monkeypatch, operation):
    if operation == "pack":
        value = {"value": 1}; previous = inputs.pack_reviewed_context_json_v2
        def mutate(offered):
            result = previous(offered); value["value"] = True; return result
        monkeypatch.setattr(inputs, "pack_reviewed_context_json_v2", mutate)
        with pytest.raises(ValueError, match="changed"): inputs.pack_reviewed_context_json_v3(value)
    else:
        value = inputs.pack_reviewed_context_json_v3({"value": 1}); previous = inputs.unpack_reviewed_context_json_v2
        def mutate(offered):
            result = previous(offered); value["root"] = True; return result
        monkeypatch.setattr(inputs, "unpack_reviewed_context_json_v2", mutate)
        with pytest.raises(ValueError, match="changed"): inputs.unpack_reviewed_context_json_v3(value)


@pytest.mark.parametrize("damage", [None, "target-field", "query-id", "duplicate-id", "old-profile", "old-codec"])
def test_keylayout_generation_wire_requires_explicit_profile_and_keeps_expanded_screening(damage):
    data = dict(permitted=[], retrieved=[dict(id="TRAIN", content=dict(source_text="Complete source", roles=["actor", "recipient"]))])
    if damage == "target-field": data["retrieved"][0]["content"]["gold_target"] = "forbidden"
    elif damage == "query-id": data["retrieved"][0]["content"]["roles"].append("heldout-query")
    elif damage == "duplicate-id": data["permitted"] = list(data["retrieved"])
    source = _shared_wire_source(data)
    source["profile"] = worker.REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V3
    source["context"] = inputs.pack_reviewed_context_json_v3(data)
    if damage == "old-profile": source["profile"] = worker.REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V2
    elif damage == "old-codec": source["context"] = inputs.pack_reviewed_context_json_v2(data)
    if damage is None:
        assert worker._reviewed_generation_context_wire(source, {"heldout-query"}) == inputs._reviewed_wire(source["context"]).decode()
    else:
        with pytest.raises(worker.TrainingJobValidationError): worker._reviewed_generation_context_wire(source, {"heldout-query"})


def test_keylayout_generation_inputs_reject_qwen_budget_optin_before_tokenizer_use():
    with pytest.raises(ValueError, match="unchanged default context budget"):
        inputs.prepare_reviewed_decoder_context_generation_inputs([], source_contexts={},
            expected_source_contexts_sha256="0"*64, expected_context_records_sha256="0"*64,
            tokenizer=None, max_source_tokens=65536, context_transport="shared_json_v3",
            context_budget_profile=worker.REVIEWED_QWEN2_CONTEXT_BUDGET_PROFILE)


@pytest.mark.parametrize("transport", ["shared_json_v2", "shared_json_v3"])
@pytest.mark.parametrize("v3_position", [0, 1])
def test_keylayout_direct_backend_refuses_larger_context_budget_before_native_or_model_access(
        monkeypatch, transport, v3_position):
    import builtins
    calls = []; native_gate = RuntimeError("existing v2 native gate reached")
    previous_import = builtins.__import__
    def no_native_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"torch", "transformers", "tokenizers"}:
            pytest.fail("DATA preflight imported a numerical library")
        return previous_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_native_import)
    backend = object.__new__(worker.TorchReviewedDecoderBackend)
    backend.max_sequence_tokens = 65536
    def native():
        calls.append("native"); raise native_gate
    backend._torch = native
    data = dict(permitted=[], retrieved=[dict(id="TRAIN", content=dict(source_text="Complete source"))])
    records = []
    for position in range(2):
        version = 3 if transport == "shared_json_v3" and position == v3_position else 2
        source = _shared_wire_source(data)
        source["profile"] = getattr(worker, f"REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V{version}")
        source["context"] = getattr(inputs, f"pack_reviewed_context_json_v{version}")(data)
        records.append(dict(id=f"query-{position}", unit_id=f"unit-{position}",
            source_wire=inputs._reviewed_wire(source).decode(), source_token_ids=[257, 1, 0]))
    options = dict(max_output_tokens=4, execution_guard=lambda: calls.append("guard"),
        conditioning_profile="qwen2-chatml-complete-legal-ir/v1",
        context_budget_profile=worker.REVIEWED_QWEN2_CONTEXT_BUDGET_PROFILE)
    if transport == "shared_json_v3":
        with pytest.raises(worker.TrainingJobValidationError, match="unchanged default context budget"):
            backend.generate_batch(records, **options)
        assert calls == ["guard"]
    else:
        with pytest.raises(RuntimeError) as caught: backend.generate_batch(records, **options)
        assert caught.value is native_gate and calls == ["guard", "native"]


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

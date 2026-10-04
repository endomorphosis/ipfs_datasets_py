"""Synthetic source-binding tests; these do not establish semantic fidelity."""
from copy import deepcopy
import hashlib
import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_context as subject
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core


def fixtures(dimension=8):
    cache = [dict(id=f"cached-{i}", source_text=text, input=[float(j == i) for j in range(dimension)])
        for i, text in enumerate(["Agency α files.", "Officer acts.", "Board retains.", "Clerk delivers."])]
    train = [dict(id="train", source_text=cache[0]["source_text"]+"\n\n"+cache[1]["source_text"])]
    validation = [dict(id="validation", source_text=cache[2]["source_text"]+"\n\n"+cache[3]["source_text"])]
    contexts = dict(train=subject.build_source_contexts(train, cache), validation=subject.build_source_contexts(validation, cache))
    return train, validation, cache, contexts


def transform(dimension=8):
    return dict(mode="none", mean=[0.]*dimension, scale=1., origin="training_only")


@pytest.mark.parametrize("dimension", [8,384,768])
def test_exact_source_join_unicode_offsets_and_source_only_receipt(dimension):
    train, validation, cache, contexts = fixtures(dimension)
    report = subject.validate_training_contexts(train, validation, contexts)
    assert report["training_clause_inventory"][0]["id"] == "clause:"+hashlib.sha256(cache[0]["source_text"].encode()).hexdigest()
    segment = contexts["train"]["train"]["segments"][0]
    assert segment["byte_end"] > segment["char_end"]
    assert report["reference_labels_accessed"] is False and not report["admitted"]
    assert [r["input"] for r in subject.unique_training_clauses(train, validation, contexts)] == [r["input"] for r in cache[:2]]


def test_training_labels_and_paragraph_vectors_never_read():
    train, validation, _, contexts = fixtures()
    for row in train+validation:
        row.update(target_ids=object(), input=object(), reference_count=object())
    subject.validate_training_contexts(train, validation, contexts)
    assert subject.batch_source_context(torch, train, contexts["train"], transform())["vectors"].shape == (1,8,8)


@pytest.mark.parametrize("mutation", ["hash","embedding","offset","booloffset","text","vector","field","mask","width"])
def test_descriptor_mutations_fail(mutation):
    train, _, _, contexts = fixtures(); value = contexts["train"]["train"]; segment = value["segments"][0]
    if mutation == "hash": value["source_sha256"] = "a"*64
    elif mutation == "embedding": segment["embedding_sha256"] = "a"*64
    elif mutation == "offset": segment["byte_end"] += 1
    elif mutation == "booloffset": segment["char_start"] = False
    elif mutation == "text": segment["source_text"] += "x"
    elif mutation == "vector": segment["vector"][0] = float("nan")
    elif mutation == "field": segment["target"] = {}
    elif mutation == "mask": value["mask"] = [True]
    else: segment["vector"].pop()
    with pytest.raises(ValueError): subject.validate_contexts(train, contexts["train"])


@pytest.mark.parametrize("mutation", ["labels","missing","duplicate","unnormalized","many","empty","mixed"])
def test_builder_rejects_bad_or_label_bearing_sources(mutation):
    train, _, cache, _ = fixtures()
    if mutation == "labels": cache[0]["target_ids"] = [1,2]
    elif mutation == "missing": train[0]["source_text"] += "x"
    elif mutation == "duplicate": cache.append(deepcopy(cache[0]))
    elif mutation == "unnormalized": cache[0]["input"][0] = 2.
    elif mutation == "many": train[0]["source_text"] = "\n\n".join([cache[0]["source_text"]]*9)
    elif mutation == "empty": train[0]["source_text"] += "\n\n"
    else: cache[1]["input"] = [1.]+[0.]*383
    with pytest.raises(ValueError): subject.build_source_contexts(train, cache)


def test_builder_rejects_source_target_and_does_not_mutate_or_alias():
    train, _, cache, _ = fixtures(); before = deepcopy((train,cache))
    result = subject.build_source_contexts(train,cache)
    result["train"]["segments"][0]["vector"][0] = 0.
    assert (train,cache) == before
    train[0]["target_ids"] = [1,2]
    with pytest.raises(ValueError): subject.build_source_contexts(train,cache)


def test_first_occurrence_dedup_and_same_source_conflicting_vector_rejected():
    train, validation, cache, contexts = fixtures()
    train.append(dict(id="second",source_text=cache[1]["source_text"]+"\n\n"+cache[0]["source_text"]))
    contexts["train"] = subject.build_source_contexts(train,cache)
    assert len(subject.unique_training_clauses(train,validation,contexts)) == 2
    segment = contexts["train"]["second"]["segments"][0]
    segment["vector"] = cache[2]["input"]; segment["embedding_sha256"] = core.digest(segment["vector"])
    with pytest.raises(ValueError): subject.validate_training_contexts(train,validation,contexts)


@pytest.mark.parametrize("kind", ["text","normalized","vector","id"])
def test_split_overlap_rejected(kind):
    train, validation, cache, contexts = fixtures()
    if kind == "id": validation[0]["id"] = "train"
    elif kind in ("text","normalized"):
        cache[2]["source_text"] = cache[0]["source_text"] if kind == "text" else cache[0]["source_text"].upper()
        validation[0]["source_text"] = cache[2]["source_text"]+"\n\n"+cache[3]["source_text"]
    else: cache[2]["input"] = cache[0]["input"]
    contexts["validation"] = subject.build_source_contexts(validation,cache[2:])
    with pytest.raises(ValueError): subject.validate_training_contexts(train,validation,contexts)


def test_batch_applies_transform_then_zero_padding_and_accepts_subset():
    train, _, cache, contexts = fixtures()
    second = dict(id="second",source_text=cache[2]["source_text"])
    contexts["train"].update(subject.build_source_contexts([second],cache))
    t = dict(mode="center_rms",mean=[.5]*8,scale=2.,origin="training_only")
    packet = subject.batch_source_context(torch,train,contexts["train"],t)
    assert set(packet) == {"vectors","mask"}
    assert packet["vectors"].dtype == torch.float32 and packet["mask"].dtype == torch.bool
    assert torch.equal(packet["vectors"][0,0],(torch.tensor(cache[0]["input"])-.5)/2)
    assert not packet["vectors"][0,2:].any() and packet["mask"].tolist() == [[True,True]+[False]*6]


def test_rebind_reorders_only_existing_source_and_recalculates_all_offsets():
    train, _, _, contexts = fixtures(); old = deepcopy(contexts["train"]["train"])
    row, descriptor = subject.rebind_context(old,row_id="recipient",order=[1,0])
    assert descriptor["segments"][0]["vector"] == old["segments"][1]["vector"]
    subject.validate_context(row,descriptor)
    assert old == contexts["train"]["train"]
    with pytest.raises(ValueError): subject.rebind_context(old,row_id="x",order=[0,0])


def test_published_cache_binding_authenticates_used_subset():
    train, _, cache, contexts = fixtures()
    mappings = [dict(id="train",segments=[dict(id=cache[i]["id"],source_sha256=s["source_sha256"],embedding_sha256=s["embedding_sha256"])
        for i,s in enumerate(contexts["train"]["train"]["segments"])])]
    inventory = dict(schema="source-clause-cache-prerequisite-inventory/v1",passed=True,complete=True,findings=[],
        paragraph_source_mappings={"train":mappings})
    assert subject.validate_published_cache(cache,inventory,split="train")["used_clauses"] == 2
    cache[0]["input"] = cache[3]["input"]
    with pytest.raises(ValueError): subject.validate_published_cache(cache,inventory,split="train")


def test_authenticated_prepare_wrapper_preserves_labels_outside_context():
    train, validation, cache, contexts = fixtures()
    mappings = {}
    for split,rows,cache_part in (("train",train,cache[:2]),("validation",validation,cache[2:])):
        mappings[split] = [dict(id=rows[0]["id"],segments=[dict(id=cached["id"],source_sha256=segment["source_sha256"],
            embedding_sha256=segment["embedding_sha256"]) for cached,segment in
            zip(cache_part,contexts[split][rows[0]["id"]]["segments"])])]
    inventory = dict(schema="source-clause-cache-prerequisite-inventory/v1",passed=True,complete=True,findings=[],
        paragraph_source_mappings=mappings)
    for row in train+validation: row.update(target_ids=object(),input=object())
    caches = dict(train=cache[:2],validation=cache[2:])
    actual = subject.prepare_source_contexts(train,validation,cache_rows=caches,clause_inventory=inventory)
    assert actual == contexts
    inventory["paragraph_source_mappings"]["validation"][0]["segments"][0]["source_sha256"]="f"*64
    with pytest.raises(ValueError): subject.prepare_source_contexts(train,validation,cache_rows=caches,clause_inventory=inventory)


def test_batch_rejects_wrong_transform_and_missing_context():
    train,_,_,contexts=fixtures()
    with pytest.raises(ValueError):subject.batch_source_context(torch,train,{},transform())
    t=transform();t["mean"][0]=1
    with pytest.raises(ValueError):subject.batch_source_context(torch,train,contexts["train"],t)
    with pytest.raises(ValueError):subject.validate_contexts(train,{})

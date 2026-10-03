"""Synthetic augmentation contracts, not local encoder/training evidence."""
from copy import deepcopy
import math
import random

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import order_training_augmentation as subject
from .test_order_source_diagnostic import corpus as authored_corpus


@pytest.fixture
def inputs(authored_corpus):
    paragraphs, curriculum, codec = authored_corpus
    preparation = subject.order.build_order_variants(paragraphs, curriculum, codec=codec)
    native = []
    for i, row in enumerate(preparation["rows"]):
        vector = [0.]*384; vector[i] = 1.
        tokens = [101] + [1000+slot for slot in row["order_diagnostic"]["permutation"]] + [102]
        native.append(dict(input_id=row["id"], status="embedded", vector=vector,
            tokens=dict(input_ids=tokens, attention_mask=[1]*len(tokens), token_type_ids=[0]*len(tokens))))
    observations = dict(main=native, repeat_batch8=deepcopy(native[:48]), repeat_batch4=deepcopy(native[:48]))
    embeddings = dict(schema="order-source-embedding-observations/v1", observations_count=204,
        observations=observations, vectors_sha256={k:subject.digest(v) for k,v in observations.items()},
        producer=dict(model_id="thenlper/gte-small", revision="17e1f347d17fe144873b1201da91788898c639cd",
            dimension=384, encoder_context_tokens=512, normalized=True, dtype="float32", device="cpu", cpu_threads=1,
            downloads_performed=False, actual_forward_tokens_checked=True, encoder_context_changed=False))
    train = [dict(id=row["id"], source_text=row["source_text"], target_ids=row["target_ids"], input=native[i]["vector"])
        for i,row in enumerate(paragraphs["train"])]
    validation = [dict(id=row["id"], source_text=row["source_text"], target_ids=row["target_ids"], input=native[i]["vector"])
        for i,row in enumerate(paragraphs["validation"])]
    references = [dict(id=row["id"], source_text=row["source_text"], source_sha256=row["source_sha256"],
        target=deepcopy(row["target"]), clause_count=row["clause_count"]) for row in paragraphs["train"]]
    return dict(training_rows=train, validation_rows=validation, training_references=references,
        preparation=preparation, embedding_observations=embeddings, codec=codec)


def resign_preparation(inputs):
    p=inputs["preparation"]
    p["preparation_sha256"]=subject.digest({k:v for k,v in p.items() if k!="preparation_sha256"})


def resign_embeddings(inputs):
    e=inputs["embedding_observations"]
    e["vectors_sha256"]={k:subject.digest(v) for k,v in e["observations"].items()}


def test_preparation_is_immutable_and_original_first_exact(inputs):
    before=deepcopy(inputs); rng=random.getstate(); selector=subject.prepare(**inputs)
    assert inputs==before and random.getstate()==rng
    assert selector.effective_rows[:48]==inputs["training_rows"]
    assert selector.effective_references[:48]==inputs["training_references"]
    assert len(selector.effective_rows)==len(selector.effective_references)==108
    snapshot=selector.snapshot()
    assert snapshot["draw_rows"]==snapshot["draw_batches"]==0
    assert snapshot["aliases_excluded"]==12
    assert snapshot["normalization_fit_rows"]==snapshot["count_sampler_rows"]=="unchanged original48"
    assert not any(snapshot[key] for key in subject.FALSE)


def test_parent_local_unique_cycle_preserves_batch_and_complete_target_budgets(inputs):
    selector=subject.prepare(**inputs); train=inputs["training_rows"]
    a,b,c,d=[selector.select(train) for _ in range(4)]
    assert a==train
    assert d[:12]==train[:12] and b[:12]==train[:12] and c[:12]==train[:12]
    for parent,second,third,fourth in zip(train[12:24],b[12:24],c[12:24],d[12:24]):
        assert second==fourth and second["id"]!=parent["id"] and third==parent
    for parent,second,third,fourth in zip(train[24:],b[24:],c[24:],d[24:]):
        assert len({parent["id"],second["id"],third["id"]})==3 and fourth==parent
    assert all(len(original["target_ids"])==len(changed["target_ids"])
        for batch in (a,b,c,d) for original,changed in zip(train,batch))
    assert selector.snapshot()["draw_rows"]==192
    assert all(n==4 for n in selector.snapshot()["parent_occurrence_counts"].values())
    assert sum(selector.snapshot()["variant_draw_counts"].values())==192
    assert selector.snapshot()["draw_counts_are_not_committed_optimizer_exposure"]


def test_independent_counters_and_returned_data_cannot_mutate_selector(inputs):
    one,two=subject.prepare(**inputs),subject.prepare(**inputs)
    parent=inputs["training_rows"][24]; other=inputs["training_rows"][25]
    assert one.select([parent])==[parent]
    assert one.select([other])==two.select([other])==[other]
    assert one.select([parent])[0]["id"]!=parent["id"]
    assert two.select([parent])==[parent]
    rows=one.effective_rows; refs=one.effective_references;snap=one.snapshot()
    rows[0]["input"][0]=99; refs[0]["target"]["rules"][0]["actor"]="changed"
    snap["variant_ids_by_parent"][parent["id"]].clear()
    assert one.effective_rows[0]==inputs["training_rows"][0]
    assert one.effective_references[0]==inputs["training_references"][0]
    assert one.snapshot()["variant_ids_by_parent"][parent["id"]]


@pytest.mark.parametrize("case",["duplicate","unknown","mutated","empty","effective"])
def test_bad_batch_is_atomic(inputs,case):
    selector=subject.prepare(**inputs); before=selector.snapshot();parent=inputs["training_rows"][12]
    if case=="duplicate": batch=[parent,parent]
    elif case=="unknown": batch=[{**parent,"id":"unknown"}]
    elif case=="mutated": batch=[{**parent,"source_text":"changed"}]
    elif case=="empty":batch=[]
    else:batch=[selector.effective_rows[48]]
    with pytest.raises(ValueError):selector.select(batch)
    assert selector.snapshot()==before


@pytest.mark.parametrize("mutation",[
    lambda x:x["training_rows"].pop(),
    lambda x:x["validation_rows"].pop(),
    lambda x:x["validation_rows"][0].update(id=x["training_rows"][0]["id"]),
    lambda x:x["training_rows"][0]["input"].__setitem__(0,0.),
    lambda x:x["training_references"][0].update(source_sha256="0"*64),
    lambda x:x["training_references"][0]["target"]["rules"][0].update(actor="changed"),
    lambda x:x["preparation"]["rows"][48].update(source_text="changed"),
    lambda x:x["preparation"]["rows"][48]["target"]["rules"][0].update(actor="changed"),
    lambda x:x["preparation"]["rows"][48]["components"][0].update(char_start=1),
    lambda x:x["preparation"]["rows"][48]["order_diagnostic"].update(permutation=[0,1]),
    lambda x:x["preparation"]["rows"][48]["order_diagnostic"].update(inverse_permutation=[0,1]),
    lambda x:x["preparation"]["aliases"].pop(),
    lambda x:x["preparation"]["requests"].pop(),
    lambda x:x["preparation"]["pairs"].pop(),
    lambda x:x["preparation"]["original_ids"].reverse(),
    lambda x:x["preparation"].update(training_only=False),
    lambda x:x["preparation"]["rows"][48].update(qualified=True),
])
def test_semantically_invalid_cohort_or_variant_refused_even_if_digest_resigned(inputs,mutation):
    mutation(inputs);resign_preparation(inputs)
    with pytest.raises(ValueError): subject.prepare(**inputs)


@pytest.mark.parametrize("mutation",[
    lambda x:x["producer"].update(encoder_context_tokens=1024),
    lambda x:x["producer"].update(downloads_performed=True),
    lambda x:x["producer"].update(dtype="float64"),
    lambda x:x.update(observations_count=108),
    lambda x:x["observations"]["main"].reverse(),
    lambda x:x["observations"]["main"][48].update(status="token_limit_exceeded"),
    lambda x:x["observations"]["main"][48]["vector"].__setitem__(0,math.inf),
    lambda x:x["observations"]["main"][48]["vector"].__setitem__(0,.1),
    lambda x:x["observations"]["main"][48]["tokens"]["input_ids"].__setitem__(0,0),
    lambda x:x["observations"]["main"][48]["tokens"]["input_ids"].__setitem__(1,2000),
    lambda x:x["observations"]["main"][48]["tokens"]["attention_mask"].__setitem__(0,0),
    lambda x:x["observations"]["main"][48]["tokens"]["token_type_ids"].__setitem__(0,1),
])
def test_false_native_embedding_or_token_receipts_refused(inputs,mutation):
    mutation(inputs["embedding_observations"])
    # Nonfinite JSON cannot be resigned; reject its old digest first.
    try:resign_embeddings(inputs)
    except ValueError:pass
    with pytest.raises(ValueError):subject.prepare(**inputs)


def test_original_vectors_cannot_be_swapped_behind_valid_normalization(inputs):
    e=inputs["embedding_observations"]
    e["observations"]["main"][0]["vector"]=deepcopy(e["observations"]["main"][1]["vector"])
    resign_embeddings(inputs)
    with pytest.raises(ValueError,match="cached input"): subject.prepare(**inputs)


def test_cycle_is_independent_of_batch_order_and_python_rng(inputs):
    a,b=subject.prepare(**inputs),subject.prepare(**inputs)
    first=inputs["training_rows"][12:28];r=random.getstate()
    for _ in range(3):
        x={row["id"]:out["id"] for row,out in zip(first,a.select(first))}
        rev=list(reversed(first));y={row["id"]:out["id"] for row,out in zip(rev,b.select(rev))}
        assert x==y
    assert random.getstate()==r
    assert a.snapshot()["parent_occurrence_counts"]==b.snapshot()["parent_occurrence_counts"]
    assert a.snapshot()["selection_sequence_sha256"]!=b.snapshot()["selection_sequence_sha256"]


@pytest.mark.parametrize("transform",[str.upper,lambda text:" \t ".join(text.split())])
def test_changed_order_cannot_bypass_inherited_normalized_source_exclusion(inputs,transform):
    changed=inputs["preparation"]["rows"][48]["source_text"]
    inputs["validation_rows"][0]["source_text"]=transform(changed)
    with pytest.raises(ValueError,match="normalized source"):
        subject.prepare(**inputs)

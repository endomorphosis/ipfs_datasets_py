"""Matched source-only inputs for private 8D/384D/768D decoder comparisons.

No targets, sparse teacher reconstruction or dimension conversion enter this
owner. Existing cached representations retain their native producer identities.
Only missing native768 sources execute an encoder, with a stricter 512-token
admission and exact pretokenized-source checks at every actual forward call.
"""
from copy import deepcopy
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import stat
import sys
import time

from . import clause_source_context as clauses
from . import decoder_distillation_experiment as core

SCHEMA = "matched-dimension-source-inputs/v1"
PLAN_SCHEMA = "matched-dimension-source-plan/v1"
BOUNDED_SCHEMA = "bounded-native768-source-production/v1"
MAX_TOKENS = 512
MAX_SECONDS = 600
FALSE = dict(admitted=False, qualified=False, formalized=False, roundtrip_ok=False,
    proof_authority=False, source_semantics_verified=False, training_executed=False,
    teacher_checkpoint_loaded=False, target_access=False, downloads_performed=False,
    encoder_context_increased=False)
_require = core._require


def _sha(raw): return hashlib.sha256(raw).hexdigest()
def _text_sha(text): return _sha(text.encode("utf-8"))
def _file_pin(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=_sha(path.read_bytes()), bytes=path.stat().st_size)


def _read_report(path, expected):
    _require(type(expected) is str and core._SHA.fullmatch(expected), "exact native report SHA256 required")
    path = Path(path).absolute(); before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_size <= 64*1024**2, "bounded regular native report required")
    raw = path.read_bytes(); after = path.lstat()
    identity = lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    _require(identity(before)==identity(after) and len(raw)==before.st_size and _sha(raw)==expected,
        "native production report bytes changed or differ")
    return json.loads(raw),dict(path=str(path.resolve()),sha256=expected,bytes=len(raw))


def _unit(vector, dimension):
    core._vector(vector,dimension)
    _require(abs(math.fsum(float(v)*float(v) for v in vector)-1.) <= 1e-4,
        "native normalized vector required; no normalization repair allowed")


def _sources(paragraph_rows, contexts):
    _require(type(paragraph_rows) is dict and set(paragraph_rows)=={"train","validation"}, "closed paragraph source splits required")
    for rows in paragraph_rows.values():
        _require(type(rows) is list and 1<=len(rows)<=4096, "bounded paragraph source rows required")
        for row in rows:
            _require(type(row) is dict and set(row)=={"id","source_text","input"}, "closed source-only paragraph rows required")
            clauses._source(row); _unit(row["input"],384)
    binding=clauses.validate_training_contexts(paragraph_rows["train"],paragraph_rows["validation"],contexts)
    _require(binding["training"]["dimension"]==384, "original clause contexts must be native384")
    cache={}; sources=[]; observed={}; groups={}; aliases=[]
    for split in ("train","validation"):
        cache[split]=[];clause_seen=set()
        def add(text,role,original_id):
            sha=_text_sha(text);identity="source:"+sha
            if sha in observed:
                _require(observed[sha]==text and groups[sha]==split, "source text collision or split overlap")
            else:
                observed[sha]=text;groups[sha]=split;sources.append(dict(id=identity,source_text=text))
            aliases.append(dict(split=split,role=role,original_id=original_id,source_id=identity,source_sha256=sha))
        for row in paragraph_rows[split]:add(row["source_text"],"paragraph",row["id"])
        for row in paragraph_rows[split]:
            for segment in contexts[split][row["id"]]["segments"]:
                sha=segment["source_sha256"]
                if sha not in clause_seen:
                    clause_seen.add(sha)
                    cache[split].append(dict(id="clause:"+sha,source_text=segment["source_text"],input=deepcopy(segment["vector"])))
                    add(segment["source_text"],"clause","clause:"+sha)
    normalized={}
    for row in sources:
        value=" ".join(row["source_text"].casefold().split())
        _require(value not in normalized or normalized[value]==row["id"], "different exact texts have duplicate normalized source")
        normalized[value]=row["id"]
    _require(len(sources)<=4096 and sum(len(r["source_text"].encode()) for r in sources)<=16*1024**2,
        "bounded unique source inventory required")
    return sources,aliases,cache,binding


def _native_index(report):
    from . import source_embeddings_768_complete as complete
    reference=complete.reference
    _require(type(report) is dict and report.get("schema")==complete.SCHEMA and report.get("status")=="completed"
        and report.get("profile_id")==reference.PROFILE_ID and report.get("model_inference_executed") is True
        and report.get("runtime_compatibility_verified") is True and report.get("download_executed") is False
        and report.get("training_executed") is False and report.get("proof_authority") is False,
        "completed authenticated native768 producer required")
    _require(report.get("implementation")==complete._implementation(), "native768 producer implementation differs")
    assets=report.get("assets",{})
    _require(assets.get("status")=="available" and assets.get("profile_id")==reference.PROFILE_ID
        and type(assets.get("manifest_sha256")) is str and core._SHA.fullmatch(assets["manifest_sha256"]),
        "native768 asset identity differs")
    execution=report.get("execution_profile",{})
    _require(execution.get("device")=="cpu" and execution.get("dtype")=="float32" and execution.get("pooling")=="cls"
        and execution.get("normalization")=="l2" and execution.get("padding_side")=="right"
        and execution.get("max_tokens_including_special_tokens")==reference.MAX_TOKENS,
        "historical native768 production profile differs")
    rows=report.get("receipts")
    _require(type(rows) is list and 1<=len(rows)<=4096 and report.get("receipt_count")==len(rows), "complete native768 receipt inventory required")
    result={};ids=set()
    for receipt in rows:
        _require(type(receipt) is dict and receipt.get("schema")==reference.RECEIPT_SCHEMA
            and receipt.get("profile_id")==reference.PROFILE_ID and receipt.get("dimension")==768
            and receipt.get("asset_manifest_sha256")==assets["manifest_sha256"] and receipt.get("truncated") is False
            and receipt.get("normalized") is True and type(receipt.get("source_sha256")) is str
            and core._SHA.fullmatch(receipt["source_sha256"]) and type(receipt.get("id")) is str
            and receipt["id"] not in ids and type(receipt.get("token_count_including_special_tokens")) is int
            and 1<=receipt["token_count_including_special_tokens"]<=MAX_TOKENS
            and type(receipt.get("token_input_sha256")) is str and core._SHA.fullmatch(receipt["token_input_sha256"]),
            "cached native receipt source, profile or512-token admission differs")
        _unit(receipt.get("embedding"),768);ids.add(receipt["id"])
        sha=receipt["source_sha256"]
        if sha in result:
            _require(result[sha]["embedding"]==receipt["embedding"] and
                result[sha]["token_input_sha256"]==receipt["token_input_sha256"], "ambiguous cached native source")
        else: result[sha]=deepcopy(receipt)
    return result


def plan_sources(paragraph_rows, clause_contexts384, native768_report, *, expected_native_report_sha256):
    """Plan exact-source reuse; native768_report is a hash-pinned local JSON path."""
    sources,aliases,cache,binding=_sources(paragraph_rows,clause_contexts384)
    report,pin=_read_report(native768_report,expected_native_report_sha256)
    index=_native_index(report)
    cached={};missing=[]
    for row in sources:
        sha=_text_sha(row["source_text"])
        if sha in index:cached[row["id"]]=index[sha]
        else:missing.append(deepcopy(row))
    result=dict(schema=PLAN_SCHEMA,source_rows=sources,source_aliases=aliases,paragraph_rows384=deepcopy(paragraph_rows),
        clause_cache384=cache,clause_contexts384=deepcopy(clause_contexts384),context_binding384=binding,
        native768_report=pin,native768_profile_id=report["profile_id"],native768_assets=deepcopy(report["assets"]),
        cached768=cached,missing768_rows=missing,historical8_source_rows=deepcopy(sources),
        paragraph_counts={k:len(v) for k,v in paragraph_rows.items()},clause_counts={k:len(v) for k,v in cache.items()},
        unique_sources=len(sources),cached768_sources=len(cached),missing768_sources=len(missing),
        cache_admission_token_limit=MAX_TOKENS,historical_native768_profile_token_limit=8192,
        cached_profile_relabelled=False,paragraph_and_clause384_views_preserved=True,
        source_selection="exact_text_sha256; original_sources_not_targets",**FALSE)
    result["plan_sha256"]=core.digest(result)
    return result


def _plan(plan):
    _require(type(plan) is dict and plan.get("schema")==PLAN_SCHEMA
        and plan.get("plan_sha256")==core.digest({k:v for k,v in plan.items() if k!="plan_sha256"})
        and all(plan.get(k) is False for k in FALSE), "authenticated immutable source plan required")
    sources,aliases,cache,binding=_sources(plan["paragraph_rows384"],plan["clause_contexts384"])
    _require(sources==plan["source_rows"]==plan["historical8_source_rows"] and aliases==plan["source_aliases"]
        and cache==plan["clause_cache384"] and binding==plan["context_binding384"], "source plan preparation differs")
    report,pin=_read_report(plan["native768_report"]["path"],plan["native768_report"]["sha256"])
    index=_native_index(report)
    cached={r["id"]:index[_text_sha(r["source_text"])] for r in sources if _text_sha(r["source_text"]) in index}
    missing=[r for r in sources if r["id"] not in cached]
    _require(pin==plan["native768_report"] and cached==plan["cached768"] and missing==plan["missing768_rows"]
        and report["assets"]==plan["native768_assets"] and report["profile_id"]==plan["native768_profile_id"]
        and plan["cache_admission_token_limit"]==MAX_TOKENS and plan["historical_native768_profile_token_limit"]==8192,
        "source plan native reuse differs")
    _require(plan.get("unique_sources")==len(sources) and plan.get("cached768_sources")==len(cached)
        and plan.get("missing768_sources")==len(missing)
        and plan.get("paragraph_counts")=={k:len(v) for k,v in plan["paragraph_rows384"].items()}
        and plan.get("clause_counts")=={k:len(v) for k,v in cache.items()}
        and plan.get("cached_profile_relabelled") is False
        and plan.get("paragraph_and_clause384_views_preserved") is True,
        "source plan inventory or provenance differs")
    return sources


def produce_historical8(plan):
    """Run only the preserved blank-English feature producer, never teacher weights."""
    from . import legal_native_conditioning as historical
    sources=_plan(plan); started=time.monotonic()
    bundle=historical.historical_features(sources,backend="historical_blank_en")
    rows=historical.stage_rows(bundle,stage=historical.HISTORICAL_STAGE,sources=sources)
    _require(len(rows)==len(sources), "incomplete historical8 source coverage")
    for row in rows:_unit(row["vector"],8)
    return dict(schema="matched-historical8-source-production/v1",plan_sha256=plan["plan_sha256"],bundle=bundle,
        validated_rows=rows,elapsed_seconds=time.monotonic()-started,representation="historical_linguistic_feature_hash8",
        legacy_sparse_reconstruction_used=False,neural_semantic_embeddings=False,**FALSE)


def _deadline(deadline):
    if time.monotonic()>=deadline:raise TimeoutError("bounded native768 source preparation deadline")


def _guarded_model(torch, model, token_rows, source_rows, batch_size, deadline, events):
    """Local proxy checking exact scheduled IDs/masks at both complete and bare calls."""
    schedule=[("complete",[0]),("encoder",[0])]+[("complete",list(range(i,min(i+batch_size,len(token_rows)))))
        for i in range(0,len(token_rows),batch_size)]
    cursor=[0]
    class Guard:
        def __init__(self,wrapped,role):self.wrapped=wrapped;self.role=role
        @property
        def training(self):return self.wrapped.training
        @property
        def new(self):return Guard(self.wrapped.new,"encoder")
        def __call__(self,**inputs):
            _deadline(deadline)
            _require(cursor[0]<len(schedule),"unexpected native768 forward")
            role,indices=schedule[cursor[0]]
            _require(role==self.role and set(inputs)=={"input_ids","attention_mask"},"native768 forward path/input keys differ")
            ids,mask=inputs["input_ids"],inputs["attention_mask"]
            width=max(len(token_rows[i]["input_ids"]) for i in indices)
            _require(1<=width<=MAX_TOKENS and isinstance(ids,torch.Tensor) and isinstance(mask,torch.Tensor)
                and ids.dtype==torch.long and mask.dtype==torch.long and ids.device.type==mask.device.type=="cpu"
                and tuple(ids.shape)==tuple(mask.shape)==(len(indices),width), "actual native768 forward exceeds512 or shape/dtype differs")
            active=[]
            for position,index in enumerate(indices):
                expected=token_rows[index]["input_ids"]
                _require(mask[position].tolist()==[1]*len(expected)+[0]*(width-len(expected))
                    and ids[position][mask[position].bool()].tolist()==expected,
                    "actual native768 forward tokens differ from complete source")
                active.append(dict(id=source_rows[index]["id"],source_sha256=_text_sha(source_rows[index]["source_text"]),
                    active_token_count=len(expected),token_input_sha256=_sha(core._raw(expected))))
            output=self.wrapped(**inputs)
            _deadline(deadline)
            events.append(dict(index=cursor[0],path=role,batch_size=len(indices),padded_width=width,sources=active,
                input_ids=ids.tolist(),attention_mask=mask.tolist(),actual_forward_checked=True))
            cursor[0]+=1
            return output
    return Guard(model,"complete"),schedule,cursor


def validate_forward_observations(report):
    """Replay all saved token bindings; no model execution or authority is implied."""
    rows=report.get("source_rows"); tokens=report.get("token_rows"); events=report.get("forward_observations")
    batch=report.get("execution_profile",{}).get("batch_size")
    _require(type(rows) is list and rows and type(tokens) is list and len(rows)==len(tokens)
        and type(batch) is int and 1<=batch<=16 and type(events) is list,
        "complete bounded forward observation inventory required")
    for row,token in zip(rows,tokens):
        _require(type(row) is dict and set(row)=={"id","source_text"}
            and row["id"]=="source:"+_text_sha(row["source_text"]), "source-derived forward ID required")
        ids=token.get("input_ids") if type(token) is dict else None
        _require(type(token) is dict and set(token)=={"input_ids","attention_mask"}
            and type(ids) is list and 1<=len(ids)<=MAX_TOKENS
            and all(type(value) is int and value>=0 for value in ids)
            and token["attention_mask"]==[1]*len(ids), "complete bounded token inputs required")
    schedule=[("complete",[0]),("encoder",[0])]+[("complete",list(range(i,min(i+batch,len(tokens)))))
        for i in range(0,len(tokens),batch)]
    _require(len(events)==len(schedule), "actual forward observations are incomplete")
    for number,(event,(role,indices)) in enumerate(zip(events,schedule)):
        width=max(len(tokens[i]["input_ids"]) for i in indices)
        _require(type(event) is dict and set(event)=={"index","path","batch_size","padded_width","sources",
            "input_ids","attention_mask","actual_forward_checked"}
            and type(event["index"]) is int and event["index"]==number and event["path"]==role
            and type(event["batch_size"]) is int and event["batch_size"]==len(indices)
            and type(event["padded_width"]) is int and event["padded_width"]==width
            and event["actual_forward_checked"] is True
            and type(event["input_ids"]) is list and type(event["attention_mask"]) is list
            and len(event["input_ids"])==len(event["attention_mask"])==len(indices),
            "actual forward schedule or geometry differs")
        expected_sources=[]
        for position,index in enumerate(indices):
            ids=event["input_ids"][position];mask=event["attention_mask"][position];expected=tokens[index]["input_ids"]
            _require(type(ids) is list and len(ids)==width and all(type(value) is int and value>=0 for value in ids)
                and type(mask) is list and all(type(value) is int for value in mask)
                and mask==[1]*len(expected)+[0]*(width-len(expected)) and ids[:len(expected)]==expected,
                "saved actual forward tokens differ from complete source")
            expected_sources.append(dict(id=rows[index]["id"],source_sha256=_text_sha(rows[index]["source_text"]),
                active_token_count=len(expected),token_input_sha256=_sha(core._raw(expected))))
        _require(event["sources"]==expected_sources, "forward source identity or token digest differs")
    return dict(forward_count=len(events),sample_forward_observations=sum(e["batch_size"] for e in events),
        maximum_forward_width=max(e["padded_width"] for e in events),token_limit=MAX_TOKENS,
        complete_and_bare_encoder_checked=True,**FALSE)


def produce_missing768(plan, *, manifest_path, expected_manifest_sha256, model_directory, code_directory,
                       batch_size=4, max_seconds=MAX_SECONDS):
    """Locally encode only missing complete sources under a stricter512-token gate."""
    from . import source_embeddings_768_complete as complete
    reference=complete.reference
    _plan(plan)
    _require(type(batch_size) is int and 1<=batch_size<=16 and type(max_seconds) in (int,float)
        and math.isfinite(max_seconds) and 0<max_seconds<=MAX_SECONDS,"bounded native768 execution policy required")
    started=time.monotonic();deadline=started+max_seconds;rows=deepcopy(plan["missing768_rows"])
    _require(rows,"no missing native768 sources; use explicit no-execution result")
    reference._source_rows(rows)
    pins=complete._implementation();owner=_file_pin(__file__)
    arguments=dict(expected_sha256=expected_manifest_sha256,model_directory=model_directory,code_directory=code_directory)
    assets=reference._PROFILE.inspect_local_assets(manifest_path,**arguments)
    _require(assets==plan["native768_assets"],"local native768 assets differ from reused cache")
    _deadline(deadline)
    torch,tokenizer,model,loading=complete._load_backend(assets)
    _deadline(deadline)
    _require(tokenizer.padding_side=="right","right-padded native768 tokenizer required")
    token_rows=reference._tokenize(rows,tokenizer,model.config.vocab_size)
    _require(all(len(row["input_ids"])<=MAX_TOKENS for row in token_rows),
        "source exceeds unchanged512-token experiment limit before any model forward")
    _require(reference._PROFILE.inspect_local_assets(manifest_path,**arguments)==assets,"native768 assets changed after load")
    events=[];guard,schedule,cursor=_guarded_model(torch,model,token_rows,rows,batch_size,deadline,events)
    verification=complete._verify_dense_path(torch,guard,tokenizer,token_rows[0])
    vectors=reference._vectors(torch,guard,tokenizer,token_rows,batch_size)
    _require(len(vectors)==len(rows) and cursor[0]==len(schedule),"incomplete guarded native768 execution")
    _require(reference._PROFILE.inspect_local_assets(manifest_path,**arguments)==assets
        and complete._implementation()==pins and _file_pin(__file__)==owner,"native768 producer/assets changed during forward")
    _deadline(deadline)
    receipts=[]
    for row,tokens,vector in zip(rows,token_rows,vectors):
        _unit(vector,768)
        receipts.append(dict(schema=reference.RECEIPT_SCHEMA,id=row["id"],source_sha256=_text_sha(row["source_text"]),
            profile_id=reference.PROFILE_ID,dimension=768,embedding=vector,
            token_count_including_special_tokens=len(tokens["input_ids"]),token_input_sha256=reference._digest(tokens["input_ids"]),
            truncated=False,normalized=True,asset_manifest_sha256=assets["manifest_sha256"]))
    result=dict(schema=BOUNDED_SCHEMA,plan_sha256=plan["plan_sha256"],status="completed",receipt_count=len(receipts),
        receipts=receipts,source_rows=rows,token_rows=token_rows,forward_observations=events,
        assets=assets,implementation=pins,bounded_owner=owner,complete_checkpoint_loading=loading,
        dense_path_verification=verification,native_profile_id=reference.PROFILE_ID,
        historical_profile_token_limit=reference.MAX_TOKENS,experiment_token_limit=MAX_TOKENS,
        all_actual_forward_tokens_checked=True,cached_profile_relabelled=False,
        execution_profile=dict(batch_size=batch_size,device="cpu",dtype="float32",pooling="cls",normalization="l2",
            padding_side="right",attention_implementation="eager",max_tokens_including_special_tokens=MAX_TOKENS,
            max_seconds=max_seconds,deadline_cooperative=True),
        runtime_versions=dict(python=sys.version.split()[0],**{name:importlib.metadata.version(name)
            for name in ("torch","transformers","tokenizers","safetensors")}),
        elapsed_seconds=time.monotonic()-started,encoder_executed=True,**FALSE)
    result["forward_validation"]=validate_forward_observations(result)
    return result


def assemble_inputs(plan, historical8_report, missing768_report):
    """Assemble source-only splits; the caller attaches unchanged reference targets later."""
    from . import legal_native_conditioning as historical
    from . import source_embeddings_768_complete as complete
    sources=_plan(plan)
    _require(type(historical8_report) is dict and historical8_report.get("schema")=="matched-historical8-source-production/v1"
        and historical8_report.get("plan_sha256")==plan["plan_sha256"]
        and all(historical8_report.get(k) is False for k in FALSE),"matched historical8 producer required")
    rows8=historical.stage_rows(historical8_report["bundle"],stage=historical.HISTORICAL_STAGE,sources=sources)
    _require(rows8==historical8_report["validated_rows"],"historical8 validated rows differ")
    vectors8={row["id"]:row["vector"] for row in rows8}
    vectors768={identity:receipt["embedding"] for identity,receipt in plan["cached768"].items()}
    _require(type(missing768_report) is dict and missing768_report.get("schema")==BOUNDED_SCHEMA
        and missing768_report.get("plan_sha256")==plan["plan_sha256"] and missing768_report.get("status")=="completed"
        and missing768_report.get("source_rows")==plan["missing768_rows"]
        and missing768_report.get("assets")==plan["native768_assets"]
        and missing768_report.get("experiment_token_limit")==MAX_TOKENS
        and missing768_report.get("historical_profile_token_limit")==8192
        and missing768_report.get("all_actual_forward_tokens_checked") is True
        and all(missing768_report.get(k) is False for k in FALSE),"matched bounded native768 production required")
    _require(missing768_report.get("implementation")==complete._implementation()
        and missing768_report.get("bounded_owner")==_file_pin(__file__)
        and missing768_report.get("native_profile_id")==complete.PROFILE_ID
        and missing768_report.get("cached_profile_relabelled") is False,
        "bounded native768 implementation or profile differs")
    _require(missing768_report.get("forward_validation")==validate_forward_observations(missing768_report),
        "bounded native768 actual forward validation differs")
    receipts=missing768_report.get("receipts")
    _require(type(receipts) is list and len(receipts)==len(plan["missing768_rows"])
        and missing768_report.get("receipt_count")==len(receipts),"complete missing768 receipts required")
    tokens=missing768_report.get("token_rows")
    _require(type(tokens) is list and len(tokens)==len(receipts),"complete admitted token inputs required")
    for row,receipt,token in zip(plan["missing768_rows"],receipts,tokens):
        _require(receipt.get("schema")==complete.reference.RECEIPT_SCHEMA
            and receipt.get("id")==row["id"] and receipt.get("source_sha256")==_text_sha(row["source_text"])
            and receipt.get("dimension")==768 and receipt.get("profile_id")==complete.PROFILE_ID
            and receipt.get("asset_manifest_sha256")==plan["native768_assets"]["manifest_sha256"]
            and receipt.get("truncated") is False and receipt.get("normalized") is True
            and receipt.get("token_count_including_special_tokens")==len(token["input_ids"])
            and 1<=len(token["input_ids"])<=MAX_TOKENS
            and token["attention_mask"]==[1]*len(token["input_ids"])
            and receipt.get("token_input_sha256")==complete.reference._digest(token["input_ids"]),
            "missing native768 source/token binding differs")
        _unit(receipt["embedding"],768);vectors768[row["id"]]=receipt["embedding"]
    _require(set(vectors8)==set(vectors768)=={row["id"] for row in sources},"exact matched source coverage required")
    dimensions={}
    for dimension in (8,384,768):
        vectors=vectors8 if dimension==8 else vectors768
        splitrows={};cache={}
        for split in ("train","validation"):
            def convert(row):
                vector=row["input"] if dimension==384 else vectors["source:"+_text_sha(row["source_text"])]
                _unit(vector,dimension)
                return dict(id=row["id"],source_text=row["source_text"],input=deepcopy(vector))
            splitrows[split]=[convert(row) for row in plan["paragraph_rows384"][split]]
            cache[split]=[convert(row) for row in plan["clause_cache384"][split]]
        contexts={split:clauses.build_source_contexts([{k:r[k] for k in ("id","source_text")} for r in splitrows[split]],cache[split])
            for split in ("train","validation")}
        binding=clauses.validate_training_contexts(splitrows["train"],splitrows["validation"],contexts)
        representation={8:dict(kind="historical_linguistic_feature_hash",dimension=8,
                producer_schema=historical8_report["bundle"]["schema"],profile_id="legacy-linguistic-features-8d/v1",
                semantic_embedding=False,teacher_checkpoint_reconstruction=False),
            384:dict(kind="native_gte_small_semantic_embedding",dimension=384,
                producer_schema="preserved_original_clause_context_inputs",profile_id=None,
                profile_evidence_scope="caller-authenticated original384 artifact closure; no encoder re-execution",
                context_binding_sha256=core.digest(plan["context_binding384"]),
                semantic_embedding=True,paragraph_and_clause_views_preserved=True),
            768:dict(kind="native_gte_multilingual_semantic_embedding",dimension=768,
                producer_schema=BOUNDED_SCHEMA,profile_id=complete.PROFILE_ID,semantic_embedding=True,
                historical_profile_token_limit=8192,experiment_admission_token_limit=MAX_TOKENS,
                cached_profile_relabelled=False)}[dimension]
        dimensions[str(dimension)]={**splitrows,"clause_cache":cache,"source_contexts":contexts,
            "context_binding":binding,"representation":representation}
    result=dict(schema=SCHEMA,complete=True,plan_sha256=plan["plan_sha256"],dimensions=dimensions,
        historical8_production_sha256=core.digest(historical8_report),bounded768_production_sha256=core.digest(missing768_report),
        native768_cached_report=deepcopy(plan["native768_report"]),source_aliases=deepcopy(plan["source_aliases"]),
        representation_kinds={"8":"historical_linguistic_feature_hash","384":"native_gte_small_semantic_embedding",
            "768":"native_gte_multilingual_semantic_embedding"},
        original384_paragraph_and_clause_views_preserved=True,targets_attached=False,**FALSE)
    result["inputs_sha256"]=core.digest(result)
    return result

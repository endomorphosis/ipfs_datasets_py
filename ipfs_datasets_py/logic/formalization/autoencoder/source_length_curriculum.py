"""Lossless, dependency-free source-length curriculum planning.

Token receipts and component targets are externally supplied declarations. This
owner checks their consistency and immutable partition/coverage bindings, not
encoder execution, target semantics, learning, or proof authority.
"""
from copy import deepcopy
import hashlib
import json
import re

SCHEMA = "source-length-curriculum/v1"
DEFAULT_SOURCE_BINS = (16, 32, 64, 128, 256, 512)
TOKENIZER_FIELDS = {"profile_id", "sha256", "encoder_context_tokens"}
TOKEN_RECEIPT_FIELDS = {"source_sha256", "tokenizer_sha256", "tokenizer_profile_id",
    "encoder_context_tokens", "token_count", "forward_token_count", "truncated", "padded"}
COMPONENT_FIELDS = {"id", "group_id", "split", "source_text", "source_sha256", "target_sha256", "start_char", "end_char"}
ROW_FIELDS = {"id", "group_id", "split", "source_text", "source_sha256", "components",
    "source_tokens", "target_ids", "codec_sha256", "target_component_ids", "target_status"}
FALSE = {name: False for name in ("training_executed", "encoder_executed", "numerical_model_loaded",
    "source_semantics_verified", "native_validation_executed", "qualified", "admitted",
    "proof_authority", "convergence_proven", "fresh_holdout", "targets_truncated", "encoder_context_changed")}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition, message):
    if not condition: raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",", ":"),
        ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _paragraph_target_digest(value):
    # The authored paragraph producer and its original target artifacts use
    # escaped JSON, independently of this planner's own UTF-8 manifest format.
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",", ":"),
        ensure_ascii=True,allow_nan=False).encode()).hexdigest()


def _source_sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == fields, "closed " + label + " required")


def _name(value):
    return type(value) is str and 0 < len(value) <= 512 and value.strip() == value and value.isprintable()


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _inspect(row, tokenizer, output_limit, largest_bin):
    _closed(row,ROW_FIELDS,"curriculum row")
    _require(_name(row["id"]) and _name(row["group_id"]) and row["split"] in ("train","validation","test"),
        "bounded row identity and explicit split required")
    text=row["source_text"]
    _require(type(text) is str and text.strip() and len(text.encode()) <= 131072, "bounded complete source text required")
    _require(_sha(row["source_sha256"]) and _sha(row["codec_sha256"]), "source and codec digests required")
    reasons=[]
    if _source_sha(text) != row["source_sha256"]: reasons.append("source_hash_mismatch")
    receipt=row["source_tokens"]
    count=None
    if receipt is None:
        reasons.append("source_token_receipt_missing")
    else:
        _closed(receipt,TOKEN_RECEIPT_FIELDS,"source token receipt")
        _require(type(receipt["token_count"]) is int and 1 <= receipt["token_count"] <= 65536
            and type(receipt["forward_token_count"]) is int and 0 <= receipt["forward_token_count"] <= 65536
            and type(receipt["truncated"]) is bool and type(receipt["padded"]) is bool,
            "bounded explicit source token accounting required")
        count=receipt["token_count"]
        if (receipt["source_sha256"] != row["source_sha256"] or receipt["tokenizer_sha256"] != tokenizer["sha256"]
            or receipt["tokenizer_profile_id"] != tokenizer["profile_id"]
            or type(receipt["encoder_context_tokens"]) is not int
            or receipt["encoder_context_tokens"] != tokenizer["encoder_context_tokens"]):
            reasons.append("source_token_provenance_mismatch")
        if receipt["truncated"] or receipt["forward_token_count"] != count:
            reasons.append("source_forward_truncated_or_incomplete")
        if receipt["padded"]: reasons.append("artificial_source_padding_forbidden")
        if count > tokenizer["encoder_context_tokens"]: reasons.append("source_exceeds_fixed_encoder_context")
        if count > largest_bin: reasons.append("source_exceeds_largest_curriculum_bin")
    ids=row["target_ids"]
    _require(type(ids) is list and 3 <= len(ids) <= 16384 and all(type(i) is int and 0 <= i <= 65535 for i in ids),
        "complete original target IDs required")
    if ids[0] != 1 or ids[-1] != 2 or any(i < 3 for i in ids[1:-1]): reasons.append("target_not_complete_bos_content_eos")
    if len(ids) > output_limit: reasons.append("complete_target_exceeds_output_limit")
    _require(row["target_status"] in ("ready","unsupported"), "explicit target codec status required")
    if row["target_status"] != "ready": reasons.append("target_codec_unsupported")
    components=row["components"]
    _require(type(components) is list and 1 <= len(components) <= 128, "bounded original component inventory required")
    component_ids=[];cursor=0
    for component in components:
        _closed(component,COMPONENT_FIELDS,"source component")
        _require(all(_name(component[k]) for k in ("id","group_id")) and component["split"] in ("train","validation","test")
            and _sha(component["source_sha256"]) and _sha(component["target_sha256"]), "original component identity required")
        _require(type(component["source_text"]) is str and component["source_text"].strip(), "original component text required")
        start,end=component["start_char"],component["end_char"]
        _require(type(start) is int and type(end) is int, "exact component character selectors required")
        component_ids.append(component["id"])
        if component["split"] != row["split"]: reasons.append("component_split_mismatch")
        if not 0 <= start < end <= len(text) or start < cursor:
            reasons.append("component_boundary_invalid");continue
        if text[cursor:start].strip(): reasons.append("uncovered_source_text")
        if text[start:end] != component["source_text"] or _source_sha(component["source_text"]) != component["source_sha256"]:
            reasons.append("component_source_mismatch")
        cursor=end
    if text[cursor:].strip(): reasons.append("uncovered_source_text")
    if len(set(component_ids)) != len(component_ids): reasons.append("duplicate_component")
    if type(row["target_component_ids"]) is not list or row["target_component_ids"] != component_ids:
        reasons.append("complete_ordered_component_targets_missing")
    return count,sorted(set(reasons))


def prepare_curriculum(rows, *, tokenizer, source_bins=DEFAULT_SOURCE_BINS, output_limit,
                       expected_codec_sha256, expected_rows_sha256):
    """Plan cumulative source bins while keeping the output ceiling independent.

    ``padded`` means artificial source padding, not masked tensor batch padding.
    Token counts include required special tokens; forward counts exclude masked
    batch padding. An existing fixed tokenizer/context and an external immutable
    row manifest are mandatory. This API never creates epochs or model updates.
    """
    rows,tokenizer=deepcopy((rows,tokenizer))
    _require(type(rows) is list and 1 <= len(rows) <= 4096, "bounded nonempty curriculum rows required")
    _require(len(json.dumps([rows,tokenizer],allow_nan=False).encode()) <= 32*1024*1024, "curriculum inputs exceed byte bound")
    _closed(tokenizer,TOKENIZER_FIELDS,"fixed tokenizer")
    _require(_name(tokenizer["profile_id"]) and _sha(tokenizer["sha256"])
        and type(tokenizer["encoder_context_tokens"]) is int and 1 <= tokenizer["encoder_context_tokens"] <= 8192,
        "fixed tokenizer identity and context required")
    _require(_sha(expected_codec_sha256) and _sha(expected_rows_sha256) and digest(rows)==expected_rows_sha256,
        "immutable original rows or codec binding differs")
    _require(type(source_bins) in (list,tuple) and 1 <= len(source_bins) <= 16
        and all(type(v) is int and 1 <= v <= 8192 for v in source_bins)
        and list(source_bins)==sorted(set(source_bins)), "increasing unique source bins required")
    _require(type(output_limit) is int and 4 <= output_limit <= 1024, "explicit bounded new-generation output ceiling required")
    observations=[];seen=set();indexes={};component_bindings={}
    for row in rows:
        count,reasons=_inspect(row,tokenizer,output_limit,source_bins[-1])
        _require(row["id"] not in seen,"duplicate curriculum row ID");seen.add(row["id"])
        if row["codec_sha256"] != expected_codec_sha256: reasons.append("target_codec_mismatch")
        observations.append(dict(id=row["id"],group_id=row["group_id"],split=row["split"],source_tokens=count,
            target_tokens_including_bos_eos=len(row["target_ids"]),component_ids=[c["id"] for c in row["components"]],
            reasons=reasons))
        identities=[("group",row["group_id"]),("source",row["source_sha256"]),
            ("normalized_source",_source_sha(" ".join(row["source_text"].casefold().split())))]
        for component in row["components"]:
            binding={k:component[k] for k in ("id","group_id","split","source_sha256","target_sha256")}
            component_bindings.setdefault(component["id"],[]).append((len(observations)-1,digest(binding)))
            identities.extend((("component_id",component["id"]),("group",component["group_id"]),
                ("source",component["source_sha256"]),
                ("normalized_source",_source_sha(" ".join(component["source_text"].casefold().split())))))
        for identity in identities: indexes.setdefault(identity,[]).append((len(observations)-1,row["split"]))
    for entries in component_bindings.values():
        if len({binding for _,binding in entries}) > 1:
            for index,_ in entries: observations[index]["reasons"].append("component_identity_conflict")
    for identity,entries in indexes.items():
        if len({split for _,split in entries}) > 1:
            for index,_ in entries: observations[index]["reasons"].append("cross_split_"+identity[0]+"_leakage")
    for row in observations:
        row["reasons"]=sorted(set(row["reasons"]))
        row["status"]="blocked" if row["reasons"] else "ready"
    stages=[]
    previous=set()
    for limit in source_bins:
        eligible=[r for r in observations if r["status"]=="ready" and r["source_tokens"] <= limit]
        train=[r["id"] for r in eligible if r["split"]=="train"]
        validation=[r["id"] for r in eligible if r["split"]=="validation"]
        newly_added=[identity for identity in train if identity not in previous]
        stages.append(dict(stage_id="source_le_"+str(limit),max_source_tokens=limit,
            training_ids=train,validation_ids=validation,new_training_ids=newly_added,
            status="ready" if newly_added else "unchanged" if train else "empty",has_new_training_rows=bool(newly_added),
            epochs_executed=0,training_executed=False))
        previous.update(train)
    ready=[r for r in observations if r["status"]=="ready"]
    ready_train=[r["id"] for r in ready if r["split"]=="train"]
    ready_validation=[r["id"] for r in ready if r["split"]=="validation"]
    _require(set(stages[-1]["training_ids"])==set(ready_train),"final stage lost a ready training pair")
    report=dict(schema=SCHEMA,scope="planning_only_not_encoder_authentication_or_convergence",
        tokenizer=tokenizer,source_bins=list(source_bins),output_limit=output_limit,output_count_includes_bos_eos=True,
        expected_rows_sha256=expected_rows_sha256,codec_sha256=expected_codec_sha256,rows=observations,stages=stages,
        selected_row_count=len(rows),ready_row_count=len(ready),blocked_row_count=len(rows)-len(ready),
        training_row_count=sum(r["split"]=="train" for r in observations),
        validation_row_count=sum(r["split"]=="validation" for r in observations),
        fixed_all_length_validation_ids=ready_validation,final_training_ids=ready_train,
        ready=len(ready)==len(rows) and bool(ready_train) and bool(ready_validation),
        source_and_output_lengths_are_distinct=True,test_used_for_fit_or_selection=False,
        requires_optimizer_continuity_between_stages=True,**FALSE)
    report["plan_sha256"]=digest(report)
    return report


def validate_curriculum(plan,rows,**options):
    expected=prepare_curriculum(rows,**options)
    _require(type(plan) is dict and digest(plan)==digest(expected),"curriculum differs from immutable original rows")
    return deepcopy(expected)


def paragraph_rows(rows, *, tokenizer_sha256, tokenizer_profile_id, encoder_context_tokens, codec_sha256):
    """Project pinned authored paragraphs plus captured embedding inputs to plans.

    This adapter neither executes nor authenticates an encoder. ``embedded``
    records must contain its captured, unpadded forward IDs. The caller preserves
    the complete original paragraph/embedding artifacts and producer pins.
    """
    _require(type(rows) is list and 1 <= len(rows) <= 4096, "bounded authored paragraphs required")
    _require(_sha(tokenizer_sha256) and _sha(codec_sha256) and _name(tokenizer_profile_id)
        and type(encoder_context_tokens) is int and 1 <= encoder_context_tokens <= 8192,"fixed adapter tokenizer and codec required")
    result=[]
    for original in rows:
        _require(type(original) is dict and type(original.get("components")) is list
            and type(original.get("source_text")) is str, "complete authored paragraph required")
        text=original["source_text"]
        _require(original.get("source_sha256")==_source_sha(text) and original.get("codec_sha256")==codec_sha256,
            "original paragraph source or codec differs")
        target=original.get("target")
        _require(type(target) is dict and set(target)=={"rules"} and type(target["rules"]) is list
            and len(target["rules"])==len(original["components"])
            and original.get("target_sha256")==_paragraph_target_digest(target),"complete ordered authored rule target required")
        components=[]
        for position,(component,rule) in enumerate(zip(original["components"],target["rules"])):
            start,end=component["char_start"],component["char_end"]
            _require(type(start) is int and type(end) is int and 0 <= start < end <= len(text)
                and component.get("position")==position,"original paragraph selectors differ")
            _require(component.get("byte_start")==len(text[:start].encode())
                and component.get("byte_end")==len(text[:end].encode()),"original paragraph UTF-8 selectors differ")
            if "original_metadata" in component:
                _require(type(component["original_metadata"]) is dict
                    and component["original_metadata"].get("split")==component["split"],"original component split metadata differs")
            excerpt=text[start:end]
            _require(component["source_sha256"]==_source_sha(excerpt)
                and component["target_sha256"]==_paragraph_target_digest({"rules":[rule]}),"original component source or full target differs")
            components.append(dict(id=component["id"],group_id=component["group_id"],split=component["split"],
                source_text=excerpt,source_sha256=component["source_sha256"],target_sha256=component["target_sha256"],
                start_char=start,end_char=end))
        embedding=original.get("embedding_result")
        receipt=None
        if embedding is not None:
            _require(type(embedding) is dict and embedding.get("input_id")==original["id"],"embedding source ID differs")
            if embedding.get("status") in ("embedded","token_limit_exceeded"):
                tokens=embedding.get("tokens")
                _require(type(tokens) is dict and type(tokens.get("input_ids")) is list
                    and 1 <= len(tokens["input_ids"]) <= 65536
                    and all(type(v) is int and v >= 0 for v in tokens["input_ids"])
                    and type(tokens.get("attention_mask")) is list
                    and len(tokens["attention_mask"])==len(tokens["input_ids"])
                    and all(type(v) is int and v==1 for v in tokens["attention_mask"]),
                    "captured complete unpadded tokenizer inputs required")
                count=len(tokens["input_ids"])
                receipt=dict(source_sha256=original["source_sha256"],tokenizer_sha256=tokenizer_sha256,
                    tokenizer_profile_id=tokenizer_profile_id,encoder_context_tokens=encoder_context_tokens,
                    token_count=count,forward_token_count=count if embedding["status"]=="embedded" else 0,
                    truncated=False,padded=False)
        result.append(dict(id=original["id"],group_id=original["group_id"],split=original["split"],
            source_text=text,source_sha256=original["source_sha256"],components=components,
            source_tokens=receipt,target_ids=deepcopy(original["target_ids"]),codec_sha256=codec_sha256,
            target_component_ids=deepcopy(original["target_component_ids"]),target_status="ready"))
    return result

"""Derive the source-only F16 candidate from the pinned F15 implementation.

No model imports, checkpoint parsing, resource operations or training.
Independent qualification remains required before numerical execution.
"""
import ast
import hashlib
import os
from pathlib import Path

F = Path(__file__).resolve().parent
PACKAGE = F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer'
parent = PACKAGE / 'legal_span_actor_refinement.py'
raw = parent.read_bytes()
assert len(raw) == 56952
assert hashlib.sha256(raw).hexdigest() == 'a6b004330c0b0be63182e5931d9d77654ae0a3144526113fc9bd3075a121642e'
text = raw.decode()
for old, new in (
    ('actor-refinement', 'actor-context-ranking'),
    ('actor_refinement', 'actor_context_ranking'),
    ('ActorRefinement', 'ActorContextRanking'),
    ('SOURCE_CONDITIONS_PRESENCE', 'SOURCE_ACTOR_REFINEMENT'),
    ('source_conditions_presence', 'source_actor_refinement'),
    ('actor-context-ranking-ce', 'actor-context-ranking-hinge'),
    ('N11', 'F15'),
    ('34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd',
     'f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4'),
    ('b3b6fdb2eeb7653265930660d3a4eaae7b1a93db22b09e71a2276367c1b156a9',
     'a1bb3158f19c7b619b7d15ee7ba4887046cc7d22eebecad7b04e8a8111ac3d42'),
):
    assert old in text
    text = text.replace(old, new)

def replace_once(old, new):
    global text
    assert text.count(old) == 1, old
    text = text.replace(old, new)

replace_once('from . import legal_span_actor_features as features',
             'from . import legal_span_actor_features as features\nfrom . import legal_span_actor_refinement as refinement')
replace_once('MODEL_PARAMETER_NAMES = conditions.MODEL_PARAMETER_NAMES',
             'MODEL_PARAMETER_NAMES = refinement.MODEL_PARAMETER_NAMES')
replace_once('closed actor refinement CE objective required',
             'closed actor context ranking hinge objective required')
replace_once('HEAD_PARAMETER_NAMES = features.HEAD_PARAMETER_NAMES',
             'SOURCE_FROZEN36_SHA256 = "6d367a28a38e7244fddcd60ec0db137f3c534c0363fb993fe7b28678d2261507"\nHEAD_PARAMETER_NAMES = features.HEAD_PARAMETER_NAMES')
replace_once('targeted._policy(seed,actor_ranking_enabled=False,',
             'targeted._policy(seed,actor_ranking_enabled=True,')
replace_once('"trained_conditions_parent":conditions._implementation(),',
             '"trained_actor_refinement_parent":refinement._implementation(),\n        "trained_conditions_parent":conditions._implementation(),')
replace_once('"actor_adapter_source_state_map": _source_state_map(),\n        "model_state": state,',
             '"actor_adapter_source_state_map": _source_state_map(),\n        "model_source_state_map": {name:name for name in MODEL_PARAMETER_NAMES},\n        "model_state": state,')
replace_once('"actor_training_count", "actor_adapter_source_state_map", "model_state",',
             '"actor_training_count", "actor_adapter_source_state_map", "model_source_state_map", "model_state",')
replace_once('"actor_adapter_source_state_map": _source_state_map(),\n        "source_frozen36_state_sha256":',
             '"actor_adapter_source_state_map": _source_state_map(),\n        "model_source_state_map": {name:name for name in MODEL_PARAMETER_NAMES},\n        "source_frozen36_state_sha256":')
replace_once('"actor_adapter_source_state_map": checkpoint["actor_adapter_source_state_map"],',
             '"actor_adapter_source_state_map": checkpoint["actor_adapter_source_state_map"],\n        "model_source_state_map": checkpoint["model_source_state_map"],')

def function(name, replacement):
    global text
    matches = [n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(matches) == 1
    node = matches[0]
    lines = text.splitlines(keepends=True)
    text = ''.join(lines[:node.lineno - 1]) + replacement.rstrip() + '\n' + ''.join(lines[node.end_lineno:])

function('_source', '''def _source(source):
    refinement._validated(source)
    frozen = checkpoint_digest({name:source["model_state"][name] for name in BASE_PARAMETER_NAMES})
    _require(checkpoint_digest(source)==SOURCE_ACTOR_REFINEMENT_SHA256
        and checkpoint_digest(source["model_state"])==SOURCE_ACTOR_REFINEMENT_MODEL_SHA256
        and source["progress"]["optimizer_steps"]==32
        and source["source_frozen36_state_sha256"]==frozen==SOURCE_FROZEN36_SHA256,
        "exact completed F15 actor-refinement checkpoint and frozen36 required")
    return source''')
function('_model', '''def _model(torch, config):
    # Reuse the qualified differentiable actor route and frozen full8 conditions.
    return refinement._model(torch, config)''')
function('_loss', '''def _loss(torch, output, records, indices, policy):
    _validate_policy(policy)
    _require(0 < len(records) == len(indices) <= 12
        and all(type(index) is int and 0 <= index < 168 for index in indices),
        "complete bounded actor training membership required")
    total, base_details = targeted._loss(torch, lambda *_: output, records, policy["objective_policy"])
    rows = []
    for index, record in zip(indices, records, strict=True):
        count, gold, others, domain = targeted._actor_record(record)
        rows.append({"id":record["id"], "training_index":index,
            "source_sha256":hashlib.sha256(record["source_text"].encode()).hexdigest(),
            "token_count":count, "actor_gold_coordinates":list(gold), "actor_present":True,
            "present_gold_nonactor_coordinates":{role:list(v) for role,v in others.items()},
            "compatible_wrong_domain_sha256":checkpoint_digest(domain),
            "compatible_wrong_candidate_count":len(domain)})
    return total, {"base_objective":base_details, "total_loss":float(total.detach()),
        "batch_denominator":len(rows), "rows":rows,
        "evaluation_references_used":False, "teacher_forcing":True}''')
function('_validate_objective_entry', '''def _validate_objective_entry(entry, batch, policy):
    _validate_policy(policy)
    _require(type(entry) is dict and set(entry)=={"optimizer_step","indices","ids","details"}
        and all(entry[k]==batch[k] for k in ("optimizer_step","indices","ids")),
        "actor ranking objective/batch join differs")
    d=entry["details"]
    _require(type(d) is dict and set(d)=={"base_objective","total_loss","batch_denominator","rows",
        "evaluation_references_used","teacher_forcing"}
        and d["evaluation_references_used"] is False and d["teacher_forcing"] is True,
        "closed actor ranking diagnostics required")
    targeted._validate_objective_diagnostics(d["base_objective"])
    _require(d["base_objective"]["actor_hinge_applied"] is policy["objective_policy"]["actor_ranking_enabled"] is True,
        "actor context ranking must enable the retained filtered hinge")
    _require(type(d["rows"]) is list and type(d["batch_denominator"]) is int
        and 0 < d["batch_denominator"] == len(entry["indices"]) == len(entry["ids"]) == len(d["rows"]) <= 12,
        "actor full batch denominator differs")
    base_rows=d["base_objective"]["rows"]
    _require(len(base_rows)==len(d["rows"]), "actor target/base objective row count differs")
    fields={"id","training_index","source_sha256","token_count","actor_gold_coordinates","actor_present",
        "present_gold_nonactor_coordinates","compatible_wrong_domain_sha256","compatible_wrong_candidate_count"}
    for index,identifier,row,base_row in zip(entry["indices"],entry["ids"],d["rows"],base_rows,strict=True):
        _require(type(row) is dict and set(row)==fields and row["id"]==identifier
            and type(index) is int and 0 <= index < 168 and row["training_index"]==index
            and row["actor_present"] is True and type(row["token_count"]) is int and 1 <= row["token_count"] <= 128
            and type(row["source_sha256"]) is str and span._SHA.fullmatch(row["source_sha256"]),
            "authenticated actor ranking membership required")
        gold=targeted._span_coordinates(row["actor_gold_coordinates"],row["token_count"])
        domain=targeted._actor_domain(row["token_count"],gold,row["present_gold_nonactor_coordinates"])
        _require(type(row["compatible_wrong_candidate_count"]) is int
            and row["compatible_wrong_candidate_count"]==len(domain)
            and row["compatible_wrong_domain_sha256"]==checkpoint_digest(domain),
            "complete teacher-forced actor domain identity differs")
        _require(base_row["id"]==identifier and base_row["token_count"]==row["token_count"]
            and _raw(base_row["gold_coordinates"])==_raw(row["actor_gold_coordinates"])
            and all(_raw(base_row[k])==_raw(row[k]) for k in ("source_sha256",
                "present_gold_nonactor_coordinates","compatible_wrong_domain_sha256","compatible_wrong_candidate_count")),
            "actor target/base objective source and filtered-domain join differs")
    _require(type(d["total_loss"]) in (int,float) and math.isfinite(d["total_loss"])
        and d["total_loss"]==d["base_objective"]["total_loss"]==batch["loss"],
        "unchanged targeted main plus ranking scalar differs")''')
tree = ast.parse(text)
doc = ast.get_docstring(tree)
assert doc is not None
start, end = tree.body[0].lineno, tree.body[0].end_lineno
lines = text.splitlines(keepends=True)
text = ''.join(lines[:start-1]) + '''"""Six-tensor actor-context continuation from the exact trained F15 model.

All 42 tensors are copied; 36 nonactor tensors and all learned conditions rows
remain frozen. Reuse the exact differentiable F15 factory and targeted main
normalization, adding its filtered actor hinge at weight0.25 and margin1.
This source candidate has not yet passed independent numerical qualification.
"""
''' + ''.join(lines[end:])
ast.parse(text)
out = PACKAGE / 'legal_span_actor_context_ranking.py'
fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
with os.fdopen(fd, 'wb') as stream:
    stream.write(text.encode()); stream.flush(); os.fsync(stream.fileno())
print({'path':str(out), 'bytes':len(text.encode()), 'sha256':hashlib.sha256(text.encode()).hexdigest()})

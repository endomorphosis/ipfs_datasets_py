"""Versioned authored compact training with the existing persistent-source GRU.

This profile inherits a v1 initial head, never a relabeled trained v2/CP128
checkpoint. Both conditioning modes have the same fourteen parameters and fresh
named Adam. Input-space names are caller declarations, not encoder provenance.
Callers retain responsibility for source leases and numerical resource admission.
"""
from __future__ import annotations

import hashlib
import importlib
import math
from pathlib import Path
import time

from . import legal_compact_content_training_v2 as base

SCHEMA = "legal-compact-content-persistent-checkpoint/v1"
PROFILE = "authored-compact-persistent-384/v1"
REPORT_SCHEMA = "legal-compact-content-persistent-training/v1"
SCORE_SCHEMA = "legal-compact-content-persistent-score/v1"
ARCHITECTURE = "projected-source-token-embedding-residual-gru/v1"
MODES = ("every_step", "first_step")
MAX_CHECKPOINT_BYTES = base.MAX_CHECKPOINT_BYTES
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_DEPENDENCIES = {
    "legal_compact_content_training_v2.py": "3ff34b8094a8bb19315741a03873c95f7d809654b35717fd4cee97e074fd2b59",
    "decoder_distillation_experiment.py": "76252ad397492762d4fc41915afd1051a93a11b74994655326fe56fa722e3b61",
    "decoder_distillation_experiment_v2.py": "0352c392a518c9ea6ff215c32e5ddd6345d776e2bb32f22fd137b5e34d93c6c6",
}
_AUTHORITY = dict(base._AUTHORITY)
_LIMITATIONS = [
    "Authored engineering fixtures only; no statutory meaning or training/evaluation gold is admitted.",
    "Source text is hashed, not encoded;384 vectors and their source-space identity are caller-supplied unverified declarations.",
    "A zero adapter preserves the donor function; this alone establishes no learned persistent source use.",
    "The fourteen-tensor architecture requires fresh named Adam; legacy trained checkpoints and their moments are not donors.",
    "First-step and every-step modes share parameter capacity, but their checkpoints and resume contracts remain distinct.",
    "Teacher-forced loss, prefix scores and fixture resume are not autonomous statutory accuracy or Lean qualification.",
    "Source hashes and runtime declarations do not attest third-party binary or cached-bytecode equivalence.",
]
_need = base._need


def _pins():
    _need(Path(base.__file__).absolute() == _SELF_PATH.with_name("legal_compact_content_training_v2.py"),
          "canonical compact training dependency required")
    return [base._source(_SELF_PATH, _SELF_SHA), *[
        base._source(_SELF_PATH.with_name(name), sha) for name, sha in _DEPENDENCIES.items()]]


def _implementation():
    return {"persistent_training_sha256": _SELF_SHA, "direct_owners": dict(_DEPENDENCIES)}


def _operation(original, work, *, as_bytes=False):
    pins = _pins()
    persistent = importlib.import_module(__package__ + ".decoder_distillation_experiment_v2")
    _need(Path(persistent.__file__).absolute() == _SELF_PATH.with_name("decoder_distillation_experiment_v2.py"),
          "canonical persistent model dependency required")
    failure = None
    try:
        _need(_pins() == pins, "persistent source changed during import")
        return base._operation(original, lambda data, head, loaded:
                               work(data, head, loaded, persistent), as_bytes=as_bytes)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _need(_pins() == pins, "persistent source changed during operation")
        except BaseException as error:
            if failure is not None:
                raise error from failure
            raise


def _identity(mode, space):
    _need(type(mode) is str and mode in MODES, "explicit persistent conditioning mode required")
    _need(type(space) is str and 0 < len(space) <= 256 and bool(space.strip())
          and "\x00" not in space, "nonempty caller-declared unverified source-space identity required")


def _shapes(config, head):
    return {**{"body." + name: shape for name, shape in head._shapes(config).items()},
            "source_to_embedding.weight": (config["token_embedding_dim"], 384)}


def _state(value, config, head):
    shapes = _shapes(config, head)
    _need(type(value) is dict and set(value) == set(shapes), "exact fourteen persistent tensors required")
    head._state({name: value["body."+name] for name in head._shapes(config)}, config)
    adapter = value["source_to_embedding.weight"]
    _need(type(adapter) is list and len(adapter) == config["token_embedding_dim"], "adapter embedding width differs")
    for row in adapter:
        _need(type(row) is list and len(row) == 384, "adapter input width differs")
        _need(all(type(v) is float and head._f32(v).hex() == v.hex() for v in row),
              "adapter requires exact finite exported float32 values")


def _initial_state(initial):
    return {**{"body."+name: value for name, value in initial["model_state"].items()},
            "source_to_embedding.weight": [[0.0]*384 for _ in range(initial["config"]["token_embedding_dim"])]}


def _policy(value, lr, head):
    _need(type(value) is dict and type(value.get("defaults")) is dict, "declared named Adam policy required")
    defaults = dict(lr=lr, betas=[0.9, 0.999], eps=1e-8, weight_decay=0, amsgrad=False,
                    maximize=False, foreach=False, capturable=False, differentiable=False, fused=None)
    if "decoupled_weight_decay" in value["defaults"]:
        defaults["decoupled_weight_decay"] = False
    expected = dict(name="Adam", defaults=defaults, gradient_clip_l2=5.0, batch_size=1,
                    row_order="population_order_repeated", objective="compact_token_cross_entropy")
    _need(head._wire(value, 4096) == head._wire(expected, 4096), "persistent Adam policy differs")


def _checkpoint(offered, expected, mode, space, head, loaded):
    _identity(mode, space)
    base._hash(expected, "persistent checkpoint")
    value = head._copy(offered, MAX_CHECKPOINT_BYTES)
    _need(head._digest(value, MAX_CHECKPOINT_BYTES) == expected, "persistent checkpoint identity differs")
    fields = {"schema", "profile", "architecture", "input_dimension", "input_role", "conditioning_mode", "source_space",
        "codec", "codec_sha256", "max_total_ids", "config", "optimizer_config", "optimizer_policy", "parameter_order",
        "runtime", "implementation", "initial_checkpoint", "initial_checkpoint_sha256", "initial_donor_weights_sha256",
        "initial_persistent_weights_sha256", "model_state", "weights_sha256", "optimizer_state", "progress",
        "parent_checkpoint_sha256", "population_raw_utf8", "population_sha256", "population_count", "authority",
        "training_mask", "evaluation_gold_mask", "limitations"}
    _need(type(value) is dict and set(value) == fields, "closed persistent checkpoint required")
    _need(value["schema"] == SCHEMA and value["profile"] == PROFILE and value["architecture"] == ARCHITECTURE
          and type(value["input_dimension"]) is int and value["input_dimension"] == 384
          and value["input_role"] == "caller_supplied_unverified_conditioning_vector"
          and value["conditioning_mode"] == mode and value["source_space"] == space
          and type(value["max_total_ids"]) is int and value["max_total_ids"] == 512,
          "persistent profile, mode or source-space differs")
    _need(value["implementation"] == _implementation(), "persistent implementation pins differ")
    _need(head._wire(value["runtime"], 32768) == head._wire(base._runtime(head, loaded), 32768),
          "persistent runtime differs")
    initial = head._checkpoint(value["initial_checkpoint"], value["initial_checkpoint_sha256"])
    _need(head._wire(value["config"], 1024) == head._wire(initial["config"], 1024)
          and value["initial_donor_weights_sha256"] == initial["weights_sha256"]
          and initial["torch_version"] == value["runtime"]["torch_version"], "permanent initial donor differs")
    _, codec_sha = head._codec(loaded, value["codec"])
    _need(value["codec_sha256"] == initial["codec_sha256"] == codec_sha, "persistent codec differs")
    _need(value["initial_persistent_weights_sha256"] == head._digest(_initial_state(initial)),
          "permanent zero-adapter initialization differs")
    config = value["optimizer_config"]
    _need(type(config) is dict and set(config) == {"learning_rate"} and type(config["learning_rate"]) is float,
          "closed persistent optimizer configuration required")
    _policy(value["optimizer_policy"], base._learning_rate(config["learning_rate"]), head)
    _need(type(value["population_raw_utf8"]) is str, "retained exact population bytes required")
    population = base._population(value["population_raw_utf8"].encode(), value["population_sha256"], head)
    count, progress = len(population["rows"]), value["progress"]
    _need(type(value["population_count"]) is int and value["population_count"] == count, "population count differs")
    _need(type(progress) is dict and set(progress) == {"optimizer_steps", "epochs_completed", "row_cursor"}
          and all(type(v) is int for v in progress.values())
          and 0 <= progress["optimizer_steps"] <= base.MAX_TOTAL_STEPS
          and progress["epochs_completed"] == progress["optimizer_steps"] // count
          and progress["row_cursor"] == progress["optimizer_steps"] % count, "persistent row/epoch progress differs")
    _need(value["parameter_order"] == list(_shapes(value["config"], head)), "persistent parameter order differs")
    _state(value["model_state"], value["config"], head)
    _need(value["weights_sha256"] == head._digest(value["model_state"]), "persistent weights identity differs")
    moments = value["optimizer_state"]
    _need(type(moments) is dict and set(moments) == {"schema", "parameters"}
          and moments["schema"] == "adam-default-betas-eps/v1" and type(moments["parameters"]) is dict,
          "closed persistent named Adam required")
    parameters = moments["parameters"]
    _need(set(parameters) == (set(_shapes(value["config"], head)) if progress["optimizer_steps"] else set()),
          "fourteen-parameter Adam inventory differs")
    for state in parameters.values():
        _need(type(state) is dict and set(state) == {"step", "exp_avg", "exp_avg_sq"}
              and type(state["step"]) is int and state["step"] == progress["optimizer_steps"], "Adam step differs")
    if parameters:
        for field in ("exp_avg", "exp_avg_sq"):
            _state({name: row[field] for name, row in parameters.items()}, value["config"], head)
        def nonnegative(v):
            return all(nonnegative(c) for c in v) if type(v) is list else v >= 0
        _need(all(nonnegative(row["exp_avg_sq"]) for row in parameters.values()), "negative Adam second moment")
        base._hash(value["parent_checkpoint_sha256"], "persistent immediate parent")
    else:
        _need(value["parent_checkpoint_sha256"] is None
              and value["weights_sha256"] == value["initial_persistent_weights_sha256"], "zero-step state differs")
    _need(value["authority"] == _AUTHORITY and all(v is False for v in value["authority"].values())
          and type(value["training_mask"]) is int and value["training_mask"] == 0
          and type(value["evaluation_gold_mask"]) is int and value["evaluation_gold_mask"] == 0
          and value["limitations"] == _LIMITATIONS, "persistent engineering authority boundary differs")
    return value, population


def _restore(value, head, loaded, persistent, *, with_optimizer=False):
    torch, numerical = head._torch(loaded), loaded["modules"]["numerical"]
    rng = torch.get_rng_state().clone()
    try:
        body = head._model(value["initial_checkpoint"], loaded)
        model = persistent.bind_persistent_model(body, dimension=384, conditioning=value["conditioning_mode"])
        _need(list(model.state_dict()) == value["parameter_order"], "actual persistent tensor order differs")
        model.load_state_dict({name: numerical._tensor(value["model_state"][name], template, name)
                               for name, template in model.state_dict().items()}, strict=True)
        _need(head._digest({n: t.detach().tolist() for n,t in model.state_dict().items()}) == value["weights_sha256"],
              "persistent restore changed weights")
        if not with_optimizer:
            return model.eval()
        optimizer = numerical._optimizer(model, value["optimizer_config"])
        policy = base._optimizer_policy(optimizer, value["optimizer_config"]["learning_rate"])
        _need(head._wire(policy, 4096) == head._wire(value["optimizer_policy"], 4096), "live Adam policy differs")
        for name, parameter in model.named_parameters():
            state = value["optimizer_state"]["parameters"].get(name)
            if state is not None:
                optimizer.state[parameter] = dict(step=torch.tensor(float(state["step"]), dtype=torch.float32),
                    exp_avg=numerical._tensor(state["exp_avg"], parameter, name+".exp_avg"),
                    exp_avg_sq=numerical._tensor(state["exp_avg_sq"], parameter, name+".exp_avg_sq", nonnegative=True))
        weights, moments = numerical._pack(model, optimizer)
        _need(weights == value["model_state"] and moments == value["optimizer_state"], "persistent named restore differs")
        return model, optimizer
    finally:
        _need(torch.equal(rng, torch.get_rng_state()), "persistent restoration changed ambient CPU RNG")


def build_compact_content_persistent_v1(initial_checkpoint, population_raw, rows, *,
        expected_initial_checkpoint_sha256, expected_population_sha256, conditioning_mode, source_space, learning_rate=0.001):
    """Copy one validated v1 initialization; add a zero adapter and fresh Adam."""
    def work(data, head, loaded, persistent):
        _identity(data["conditioning_mode"], data["source_space"])
        initial = head._checkpoint(data["initial_checkpoint"], data["expected_initial_checkpoint_sha256"])
        _, codec_sha = head._codec(loaded, initial["codec"])
        _need(codec_sha == initial["codec_sha256"], "initial compact codec differs")
        population = base._population(data["population_raw"], data["expected_population_sha256"], head)
        base._rows(data["rows"], population, initial["codec"], codec_sha, head, loaded)
        lr = base._learning_rate(data["learning_rate"])
        model = persistent.bind_persistent_model(head._model(initial, loaded), dimension=384,
                                                  conditioning=data["conditioning_mode"])
        numerical = loaded["modules"]["numerical"]
        optimizer = numerical._optimizer(model, {"learning_rate":lr})
        weights, moments = numerical._pack(model, optimizer)
        value = dict(schema=SCHEMA, profile=PROFILE, architecture=ARCHITECTURE, input_dimension=384,
            input_role="caller_supplied_unverified_conditioning_vector", conditioning_mode=data["conditioning_mode"],
            source_space=data["source_space"], codec=initial["codec"], codec_sha256=codec_sha, max_total_ids=512,
            config=initial["config"], optimizer_config={"learning_rate":lr}, optimizer_policy=base._optimizer_policy(optimizer,lr),
            parameter_order=[n for n,_ in model.named_parameters()], runtime=base._runtime(head,loaded), implementation=_implementation(),
            initial_checkpoint=initial, initial_checkpoint_sha256=data["expected_initial_checkpoint_sha256"],
            initial_donor_weights_sha256=initial["weights_sha256"], initial_persistent_weights_sha256=head._digest(weights),
            model_state=weights, weights_sha256=head._digest(weights), optimizer_state=moments,
            progress=dict(optimizer_steps=0,epochs_completed=0,row_cursor=0), parent_checkpoint_sha256=None,
            population_raw_utf8=data["population_raw"].decode(), population_sha256=data["expected_population_sha256"],
            population_count=len(population["rows"]), authority=dict(_AUTHORITY), training_mask=0,evaluation_gold_mask=0,
            limitations=list(_LIMITATIONS))
        _checkpoint(value,head._digest(value,MAX_CHECKPOINT_BYTES),data["conditioning_mode"],data["source_space"],head,loaded)
        return value
    return _operation(dict(initial_checkpoint=initial_checkpoint,population_raw=population_raw,rows=rows,
        expected_initial_checkpoint_sha256=expected_initial_checkpoint_sha256,expected_population_sha256=expected_population_sha256,
        conditioning_mode=conditioning_mode,source_space=source_space,learning_rate=learning_rate),work)


def compact_content_persistent_sha256(checkpoint):
    """Bounded canonical identity without tensor allocation or semantic validation."""
    pins = _pins()
    result = base.compact_content_training_sha256(checkpoint)
    _need(_pins() == pins, "persistent source changed during hashing")
    return result


def compact_content_persistent_bytes_v1(checkpoint, *, expected_checkpoint_sha256):
    """Validate structural/runtime commitments and return canonical complete bytes."""
    def work(data,head,loaded,persistent):
        value=data["checkpoint"]
        _need(type(value) is dict,"closed persistent checkpoint required")
        value,_=_checkpoint(value,data["expected_checkpoint_sha256"],value.get("conditioning_mode"),value.get("source_space"),head,loaded)
        return head._wire(value,MAX_CHECKPOINT_BYTES)
    return _operation(dict(checkpoint=checkpoint,expected_checkpoint_sha256=expected_checkpoint_sha256),work,as_bytes=True)


def load_compact_content_persistent_v1(checkpoint_raw, *, expected_raw_sha256, expected_conditioning_mode, expected_source_space):
    """Reject duplicate/nonfinite JSON, wrong modes/spaces and malformed14tensor state."""
    def work(data,head,loaded,persistent):
        offered=base._parse(data["checkpoint_raw"],data["expected_raw_sha256"],MAX_CHECKPOINT_BYTES,"persistent checkpoint",head)
        value,_=_checkpoint(offered,head._digest(offered,MAX_CHECKPOINT_BYTES),data["expected_conditioning_mode"],data["expected_source_space"],head,loaded)
        return value
    return _operation(dict(checkpoint_raw=checkpoint_raw,expected_raw_sha256=expected_raw_sha256,
        expected_conditioning_mode=expected_conditioning_mode,expected_source_space=expected_source_space),work)


def train_compact_content_persistent_v1(checkpoint,population_raw,rows,*,expected_checkpoint_sha256,
        expected_population_sha256,expected_conditioning_mode,expected_source_space,max_optimizer_steps,max_seconds=60):
    """At most16 full537way CE updates; resume complete named Adam and row cursor."""
    started=time.monotonic()
    def work(data,head,loaded,persistent):
        _need(type(data["max_optimizer_steps"]) is int and 0<=data["max_optimizer_steps"]<=base.MAX_STEPS_PER_CALL,"step budget must be0..16")
        _need(type(data["max_seconds"]) in (int,float) and math.isfinite(data["max_seconds"]) and 0<=data["max_seconds"]<=300,"soft deadline must be0..300s")
        value,population=_checkpoint(data["checkpoint"],data["expected_checkpoint_sha256"],data["expected_conditioning_mode"],data["expected_source_space"],head,loaded)
        _need(data["expected_population_sha256"]==value["population_sha256"] and data["population_raw"]==value["population_raw_utf8"].encode(),"complete population bytes changed")
        prepared=base._rows(data["rows"],population,value["codec"],value["codec_sha256"],head,loaded)
        _need(value["progress"]["optimizer_steps"]+data["max_optimizer_steps"]<=base.MAX_TOTAL_STEPS,"total step budget exceeded")
        model,optimizer=_restore(value,head,loaded,persistent,with_optimizer=True)
        torch,numerical=head._torch(loaded),loaded["modules"]["numerical"]
        progress,history=dict(value["progress"]),[]
        projection=[p for n,p in model.named_parameters() if n.startswith("body.projection_")]
        adapter=model.source_to_embedding.weight
        max_adapter,max_projection=0.0,0.0
        stopped="optimizer_step_budget"
        for _ in range(data["max_optimizer_steps"]):
            if time.monotonic()>=started+data["max_seconds"]:
                stopped="deadline_before_batch"
                break
            row=prepared[progress["row_cursor"]]
            target=torch.tensor([row["target_ids"]],dtype=torch.long)
            model.train();optimizer.zero_grad(set_to_none=True)
            projected,logits=model(torch.tensor([row["conditioning"]],dtype=torch.float32),target[:,:-1])
            _need(list(logits.shape)==[1,len(row["target_ids"])-1,537] and list(projected.shape)==[1,384]
                  and bool(torch.isfinite(logits).all()) and bool(torch.isfinite(projected).all()),"invalid persistent teacher forcing output")
            loss=torch.nn.functional.cross_entropy(logits.reshape(-1,537),target[:,1:].reshape(-1),ignore_index=0)
            _need(bool(torch.isfinite(loss)),"nonfinite persistent CE")
            gradients=torch.autograd.grad(loss,projection,retain_graph=True)
            _need(all(bool(torch.isfinite(g).all()) for g in gradients),"nonfinite projection gradient")
            max_projection=max(max_projection,numerical._norm(gradients))
            loss.backward()
            _need(all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters()),"missing or nonfinite14parameter gradient")
            max_adapter=max(max_adapter,numerical._norm([adapter.grad]))
            torch.nn.utils.clip_grad_norm_(list(model.parameters()),5.0,error_if_nonfinite=True)
            optimizer.step()
            _need(all(bool(torch.isfinite(p).all()) for p in model.parameters())
                  and all(bool(torch.isfinite(v).all()) for s in optimizer.state.values() for v in s.values() if torch.is_tensor(v)),"nonfinite updated persistent state")
            progress["optimizer_steps"]+=1
            progress["epochs_completed"],progress["row_cursor"]=divmod(progress["optimizer_steps"],len(prepared))
            history.append(dict(step=progress["optimizer_steps"],row_id=row["id"],token_count=len(row["target_ids"])-1,token_cross_entropy=float(loss.detach())))
        weights,moments=numerical._pack(model,optimizer)
        result=head._copy(value,MAX_CHECKPOINT_BYTES)
        if history:
            result.update(model_state=weights,weights_sha256=head._digest(weights),optimizer_state=moments,progress=progress,parent_checkpoint_sha256=data["expected_checkpoint_sha256"])
        _checkpoint(result,head._digest(result,MAX_CHECKPOINT_BYTES),data["expected_conditioning_mode"],data["expected_source_space"],head,loaded)
        delta=numerical._norm([torch.tensor(weights["source_to_embedding.weight"],dtype=torch.float64)-torch.tensor(value["model_state"]["source_to_embedding.weight"],dtype=torch.float64)])
        report=dict(schema=REPORT_SCHEMA,profile=PROFILE,conditioning_mode=value["conditioning_mode"],source_space=value["source_space"],
            checkpoint_sha256=head._digest(result,MAX_CHECKPOINT_BYTES),parent_checkpoint_sha256=data["expected_checkpoint_sha256"],population_sha256=value["population_sha256"],
            optimizer_steps=len(history),training_executed=bool(history),progress=progress,batch_losses=history,stopped_reason=stopped,
            objective="compact_token_cross_entropy",teacher_forcing=True,adapter_update_l2=delta,adapter_gradient_norm_max=max_adapter,
            formula_projection_gradient_norm_max=max_projection,source_text_is_neural_input=False,heldout_evaluated=False,free_running_evaluated=False,
            elapsed_seconds=time.monotonic()-started,deadline_scope="soft before complete batches",authority=dict(_AUTHORITY),training_mask=0,evaluation_gold_mask=0,limitations=list(_LIMITATIONS))
        return dict(checkpoint=result,report=report)
    return _operation(dict(checkpoint=checkpoint,population_raw=population_raw,rows=rows,expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_population_sha256=expected_population_sha256,expected_conditioning_mode=expected_conditioning_mode,
        expected_source_space=expected_source_space,max_optimizer_steps=max_optimizer_steps,max_seconds=max_seconds),work)


def score_compact_content_persistent_v1(checkpoint,conditioning,prefix_ids,*,expected_checkpoint_sha256,
        expected_conditioning_mode,expected_source_space,incremental=False):
    """Model-only full537 prefix scores; no optimizer, selector, targets or generation."""
    def work(data,head,loaded,persistent):
        _need(type(data["incremental"]) is bool,"incremental must be a plain boolean")
        ids=data["prefix_ids"]
        _need(type(ids) is list and 1<=len(ids)<=511 and ids[0]==1
              and all(type(i) is int and 0<=i<537 for i in ids),"bounded BOS-first prefix required")
        vector=head._conditioning(data["conditioning"])
        value,_=_checkpoint(data["checkpoint"],data["expected_checkpoint_sha256"],data["expected_conditioning_mode"],data["expected_source_space"],head,loaded)
        model=_restore(value,head,loaded,persistent)
        torch=head._torch(loaded)
        with torch.no_grad():
            projected=model.project(torch.tensor([vector],dtype=torch.float32))
            state=model.start(projected)
            if data["incremental"]:
                rows=[]
                for token in ids:
                    logits,state=model.next_logits(torch.tensor([[token]],dtype=torch.long),state)
                    rows.extend(logits[0].tolist())
            else:
                logits,state=model.next_logits(torch.tensor([ids],dtype=torch.long),state)
                rows=logits[0].tolist()
        _need(len(rows)==len(ids) and all(len(row)==537 and all(math.isfinite(v) for v in row) for row in rows)
              and state[2].tolist()==[len(ids)],"persistent scoring output geometry differs")
        return dict(schema=SCORE_SCHEMA,checkpoint_sha256=data["expected_checkpoint_sha256"],conditioning_mode=value["conditioning_mode"],
            source_space=value["source_space"],prefix_ids=ids,logits=rows,positions_consumed=len(ids),incremental=data["incremental"],
            model_forwards=len(ids) if data["incremental"] else 1,optimizer_constructed=False,training_executed=False,generation_executed=False,
            authority=dict(_AUTHORITY),training_mask=0,evaluation_gold_mask=0,limitations=list(_LIMITATIONS))
    return _operation(dict(checkpoint=checkpoint,conditioning=conditioning,prefix_ids=prefix_ids,expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_conditioning_mode=expected_conditioning_mode,expected_source_space=expected_source_space,incremental=incremental),work)

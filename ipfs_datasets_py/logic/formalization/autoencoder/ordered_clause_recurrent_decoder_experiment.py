"""Private causal ordered-clause residual into the inherited recurrent decoder.

Clause position is derived from consumed lexical prefix tokens, never a reference
count. Source padding exposes actual clause availability; exhausted/invalid routes
supply zero without masking vocabulary logits or forcing closure. This is a new
experimental architecture, not a promoted autoformalization or Lean admission.
"""
from copy import deepcopy

from . import action_factorized_clause_decoder_experiment as action
from . import clause_source_decoder_experiment as clauses
from . import decoder_cardinality_experiment as cardinality
from . import decoder_distillation_experiment as core
from . import decoder_distillation_experiment_v2 as conditioning
from . import projected_source_decoder_experiment as projected_owner
from . import shared_slot_source_decoder_experiment as shared
from . import source_value_decoder_experiment as scalar_owner

SCHEMA = "ordered-clause-recurrent-source-decoder-development/v1"
VERSION = 1
MAX_RULES = clauses.MAX_RULES
FEATURE_WIDTH = 2*action.HIDDEN_WIDTH
EMBEDDING_WIDTH = 16
FALSE = dict(action.FALSE)
FORMULA = "GRU(embedding(token)+paragraph_residual+zero_initialized_linear(concat(non_action_tanh,action_tanh)[causal_completed_rules_after_token]))"
_require = core._require


def _scan_routes(token_rows, state_rows, tables):
    """Return after-token routes, grammar states, boundaries and scalar sites.

A route of -1 means no clause residual. This is the inherited lexical recognizer
with observational routes; quoted field names used as values cannot open a site.
Malformed prefixes remain invalid. No future token or source count is inspected.
"""
    ids, string_rank, field_index, modality = tables
    source_fields = {cardinality.FIELDS.index(name): i for i, name in enumerate(scalar_owner.SOURCE_FIELDS)}
    routes, final, boundaries, sites = [], [], [], []
    for batch, (tokens, original) in enumerate(zip(token_rows, state_rows)):
        phase, seen, pending, count, length, last = original
        row_routes = []
        for offset, token in enumerate(tokens):
            rank, field = string_rank[token], field_index[token]
            following = cardinality._INVALID
            if phase == 0 and token == 1: following = 1
            elif phase == 1 and token == ids["{"]: following = 2
            elif phase == 2 and token == ids['"rules"']: following = 3
            elif phase == 3 and token == ids[":"]: following = 4
            elif phase == 4 and token == ids["["]: following = 5
            elif phase in (5, 14) and token == ids["{"]: following, seen = 6, 0
            elif phase == 6 and field >= 0 and not seen & (1 << field):
                following, seen, pending = 7, seen | (1 << field), field
            elif phase == 7 and token == ids[":"]:
                following = 8
                if pending in source_fields and count < MAX_RULES:
                    sites.append((batch, offset, count, source_fields[pending]))
            elif phase == 8:
                if pending < 4 and rank > 0 and (pending != 0 or modality[token]): following = 9
                elif pending >= 4 and token == ids["["]: following, length, last = 10, 0, 0
            elif phase == 10 and token == ids["]"]: following = 9
            elif phase in (10, 12) and rank > last and rank > 0 and length < 4:
                following, length, last = 11, length+1, rank
            elif phase == 11 and token == ids[","]: following = 12
            elif phase == 11 and token == ids["]"]: following = 9
            elif phase == 9 and token == ids[","]: following = 6
            elif phase == 9 and seen == 127 and token == ids["}"]:
                following, count = 13, count+1
                if count < cardinality.MAX_RULES: boundaries.append((batch, offset, count))
            elif phase == 13 and token == ids[","]: following = 14
            elif phase == 13 and token == ids["]"]: following = 15
            elif phase == 15 and token == ids["}"]: following = 16
            elif phase == 16 and token == 2: following = 17
            elif phase == 17 and token == 0: following = 17
            phase = following
            row_routes.append(count if 1 <= phase <= 14 and count < MAX_RULES else -1)
        routes.append(row_routes)
        final.append([phase, seen, pending, count, length, last])
    return routes, final, boundaries, sites


def bind_ordered_clause_recurrent_model(model, *, codec):
    """Copy a checked factorized model and add 2,048 zero-initialized weights.

All old tensor names/body nesting survive. Initial logits match even a fitted
factorized donor, since only the new recurrent residual starts at zero. The
source encoders, normalization, scalar and count objectives are unchanged.
"""
    torch = core._torch()
    inherited = action.checked_specification(model, codec)
    dimension = model.dimension
    specification = conditioning._body_spec(model.body.body.body, dimension, torch)
    _require(specification["token_embedding_width"] == EMBEDDING_WIDTH,
        "ordered clause experiment requires the declared16-wide inherited embedding")
    size = specification["vocabulary_size"]
    tables = cardinality._tables(codec, size, torch)
    inherited_digest = core.tensor_digest(model)
    fixed = {name: tensor.detach().clone() for name, tensor in model.named_buffers()}
    fixed.update({name: parameter.detach().clone() for name, parameter in model.named_parameters()
        if name.startswith(("body.body.body.projection_down.", "body.body.body.projection_up."))})
    fixed["ordered_clause_recurrent_version"] = torch.tensor(VERSION, dtype=torch.long)
    parent_type = type(model)

    class OrderedClauseDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model.body)
            self.non_action_head = deepcopy(model.non_action_head)
            self.action_head = deepcopy(model.action_head)
            self.dimension = dimension
            self.training = model.training
            for name, tensor in model.named_buffers():
                if not name.startswith("body."): self.register_buffer(name, tensor.detach().clone())
            with torch.random.fork_rng(devices=[]):
                self.clause_to_embedding = torch.nn.Linear(FEATURE_WIDTH, EMBEDDING_WIDTH, bias=False, dtype=torch.float32)
            with torch.no_grad(): self.clause_to_embedding.weight.zero_()
            self.clause_to_embedding.train(model.training)
            self.register_buffer("ordered_clause_recurrent_version", fixed["ordered_clause_recurrent_version"].clone())
            for parameter in self.parameters(): parameter.grad = None

        def load_state_dict(self, state_dict, strict=True, assign=False):
            _require(strict is True and assign is False and hasattr(state_dict, "items"),
                "strict nonassigning ordered clause restoration required")
            current = self.state_dict()
            _require(set(state_dict) == set(current), "ordered clause restored state inventory differs")
            for name, expected in current.items():
                actual = state_dict[name]
                _require(isinstance(actual, torch.Tensor) and actual.device.type == "cpu"
                    and actual.dtype == expected.dtype and actual.shape == expected.shape
                    and (not actual.is_floating_point() or bool(torch.isfinite(actual).all())),
                    "ordered clause restored tensor geometry or finiteness differs: "+name)
            for name, expected in fixed.items():
                _require(torch.equal(state_dict[name], expected), "ordered clause frozen tensor differs: "+name)
            return super().load_state_dict(state_dict, strict=True, assign=False)

        project = parent_type.project
        count_logits = parent_type.count_logits
        clause_features = parent_type.clause_features
        source_action_features = parent_type.source_action_features
        action_features = parent_type.action_features
        _values = parent_type._values
        source_value_logits = parent_type.source_value_logits
        source_value_guidance_logits = parent_type.source_value_guidance_logits

        def source_recurrent_features(self, projected, *, source_context):
            features, mask = self.clause_features(projected, source_context=source_context)
            result = torch.cat((self.non_action_head.features(features), self.action_head.features(features)), dim=-1)
            result = result*mask[:, :, None]
            _require(bool(torch.isfinite(result).all()), "nonfinite ordered clause recurrent features")
            return result

        def start(self, projected, *, source_context):
            base = parent_type.start(self, projected, source_context=source_context)
            return (*base, self.source_recurrent_features(projected, source_context=source_context))

        def next_logits(self, tokens, state):
            _require(isinstance(tokens, torch.Tensor) and tokens.device.type == "cpu" and tokens.dtype == torch.long
                and tokens.ndim == 2 and 1 <= tokens.shape[0] <= 128 and 1 <= tokens.shape[1] <= 1023
                and bool((tokens >= 0).all()) and bool((tokens < size).all()), "bounded ordered prefix IDs required")
            _require(type(state) is tuple and len(state) == 7, "explicit recurrent/count/grammar/scalar/clause state required")
            hidden, source, position, counts, grammar, values, packet = state
            self.body.body._inputs(source)
            _require(len(source) == len(tokens) and isinstance(hidden, torch.Tensor) and hidden.dtype == torch.float32
                and hidden.device.type == "cpu" and tuple(hidden.shape) == (1,len(tokens),specification["hidden_width"])
                and bool(torch.isfinite(hidden).all()), "ordered recurrent state differs")
            _require(isinstance(position, torch.Tensor) and position.dtype == torch.long and position.device.type == "cpu"
                and tuple(position.shape) == (len(tokens),) and bool((position >= 0).all())
                and bool((position+tokens.shape[1] <= 1023).all()), "bounded prefix positions required")
            _require(bool((tokens[position == 0,0] == 1).all()), "initial ordered prefix must begin with BOS")
            for value, shape, label in ((counts,(len(tokens),cardinality.MAX_RULES),"count"),
                (values,(len(tokens),MAX_RULES,len(scalar_owner.SOURCE_FIELDS),size),"scalar"),
                (packet,(len(tokens),MAX_RULES,FEATURE_WIDTH),"clause")):
                _require(isinstance(value,torch.Tensor) and value.dtype==torch.float32 and value.device.type=="cpu"
                    and tuple(value.shape)==shape and bool(torch.isfinite(value).all()), "finite ordered "+label+" state required")
            _require(isinstance(grammar,torch.Tensor) and grammar.dtype==torch.long and grammar.device.type=="cpu"
                and tuple(grammar.shape)==(len(tokens),6) and bool((grammar>=0).all())
                and bool((grammar[:,0]<=cardinality._INVALID).all()) and bool((grammar[:,1]<=127).all())
                and bool((grammar[:,2]<=6).all()) and bool((grammar[:,3]<=1023).all())
                and bool((grammar[:,4]<=4).all()) and bool((grammar[:,5]<=size).all()), "bounded causal grammar required")
            routes, final, boundaries, sites = _scan_routes(tokens.tolist(),grammar.tolist(),tables)
            routes = torch.tensor(routes,dtype=torch.long)
            # Sentinel8 is separate from every real clause, including slot7.
            padded = torch.cat((packet,packet.new_zeros((len(tokens),1,FEATURE_WIDTH))),dim=1)
            indices = torch.where(routes>=0,routes,torch.full_like(routes,MAX_RULES))
            selected = padded.gather(1,indices.unsqueeze(-1).expand(-1,-1,FEATURE_WIDTH))
            persistent = self.body.body.source_to_embedding(source).unsqueeze(1)
            if inherited["base_architecture"]["inherited_architecture"]["conditioning"] == "first_step":
                first = position[:,None]+torch.arange(tokens.shape[1])[None,:] == 0
                persistent = persistent*first.unsqueeze(-1)
            raw = self.body.body.body
            recurrent_input = raw.target_embedding(tokens)+persistent+self.clause_to_embedding(selected)
            _require(bool(torch.isfinite(recurrent_input).all()), "nonfinite ordered recurrent input")
            outputs, updated = raw.decoder(recurrent_input,hidden)
            logits = raw.output(outputs)
            if inherited["guide_boundary"] and boundaries:
                locations=torch.tensor(boundaries,dtype=torch.long); batch,offset,completed=locations.unbind(1)
                correction=projected_owner.prior_centered_boundary_log_odds(counts[batch],completed,self.body.count_prior_logits)
                flat=batch*tokens.shape[1]+offset
                adjustment=logits.new_zeros(len(tokens)*tokens.shape[1]).scatter(0,flat,correction)
                closing=logits.new_zeros(size);closing[tables[0]["]"]]=1.
                logits=logits+adjustment.reshape(*tokens.shape,1)*closing
            if inherited["guidance"] and sites:
                locations=torch.tensor(sites,dtype=torch.long);batch,offset,slot,field=locations.unbind(1)
                flat=batch*tokens.shape[1]+offset
                residual=logits.new_zeros(len(tokens)*tokens.shape[1],size).index_add(0,flat,values[batch,slot,field])
                logits=logits+residual.reshape_as(logits)
            _require(bool(torch.isfinite(logits).all()) and bool(torch.isfinite(updated).all()),
                "nonfinite ordered output or recurrent state")
            return logits,(updated,source,position+tokens.shape[1],counts,torch.tensor(final,dtype=torch.long),values,packet)

        def forward(self, values, prefix, *, source_context):
            projected=self.project(values)
            logits,_=self.next_logits(prefix,self.start(projected,source_context=source_context))
            return projected,logits

        def describe(self):
            result=deepcopy(inherited)
            result.update(schema=SCHEMA,inherited_action_architecture=deepcopy(inherited),
                inherited_weights_sha256=inherited_digest,ordered_recurrent_formula=FORMULA,
                recurrent_feature_dimension=FEATURE_WIDTH,recurrent_embedding_width=EMBEDDING_WIDTH,
                recurrent_parameter_names=["clause_to_embedding.weight"],recurrent_parameter_count=FEATURE_WIDTH*EMBEDDING_WIDTH,
                added_recurrent_parameters=FEATURE_WIDTH*EMBEDDING_WIDTH,
                ordered_clause_recurrent_version=VERSION,initial_recurrent_residual_zero=True,
                initial_decoder_logits_unchanged=True,paired_fresh_initial_logits_exact=True,
                recurrent_path_changed=True,source_context_used_for_scalar_head_only=False,
                source_context_used_for_recurrence=True,source_clause_availability_used_for_recurrence=True,
                source_clause_count_used_for_stopping=True,source_clause_count_forces_stopping=False,
                source_clause_count_explicit_numeric_feature=False,
                clause_routing="completed_rule_count_after_each_consumed_token",
                recurrent_feature_order=["non_action","action"],
                invalid_or_exhausted_clause_route="zero_residual_no_forced_closure",
                post_array_close_clause_route="zero_residual",
                state_layout=["recurrent_hidden","projected_source","consumed_prefix_position",
                    "source_count_logits","causal_grammar_state","source_value_logits","source_clause_recurrent_features"],
                source_context_cached_on_module=False,encoder_context_changed=False,output_budget_changed=False)
            return result

    result=OrderedClauseDecoder()
    _require(core.tensor_digest(model)==inherited_digest,"caller factorized decoder changed")
    return result


def checked_specification(model, codec):
    """Validate this explicit new architecture without weakening old schemas."""
    torch=core._torch();core._model(model,torch);spec=model.describe()
    _require(spec.get("schema")==SCHEMA and spec.get("ordered_recurrent_formula")==FORMULA,
        "explicit ordered-clause architecture required")
    base=spec.get("inherited_action_architecture")
    _require(type(base) is dict and base.get("schema")==action.SCHEMA,"factorized predecessor receipt required")
    # A read-only factorized view authenticates unchanged modules and receipts.
    # Registering aliases in this temporary object does not mutate their owner.
    class FactorizedView(torch.nn.Module):
        def __init__(self):
            super().__init__();self.dimension=model.dimension
            for name in ("body","non_action_head","action_head"):self.add_module(name,getattr(model,name))
            for name in ("head_initialization_seed","clause_source_mean","clause_source_scale"):
                self.register_buffer(name,getattr(model,name))
        def project(self,x):return model.project(x)
        def start(self,*args,**kwargs):return model.start(*args,**kwargs)
        def next_logits(self,*args,**kwargs):return model.next_logits(*args,**kwargs)
        def describe(self):return deepcopy(base)
    action.checked_specification(FactorizedView(),codec)
    permitted={"schema","inherited_action_architecture","inherited_weights_sha256","ordered_recurrent_formula",
        "recurrent_feature_dimension","recurrent_embedding_width","recurrent_parameter_names","recurrent_parameter_count",
        "added_recurrent_parameters","ordered_clause_recurrent_version","initial_recurrent_residual_zero",
        "initial_decoder_logits_unchanged","paired_fresh_initial_logits_exact","recurrent_path_changed",
        "source_context_used_for_scalar_head_only","source_context_used_for_recurrence","source_clause_availability_used_for_recurrence",
        "source_clause_count_used_for_stopping","source_clause_count_forces_stopping","source_clause_count_explicit_numeric_feature",
        "clause_routing","recurrent_feature_order","invalid_or_exhausted_clause_route","post_array_close_clause_route","state_layout"}
    _require(set(spec)==set(base)|permitted and all(spec[k]==v for k,v in base.items() if k not in permitted),
        "ordered inherited specification changed")
    expected_parameters={"body."+name for name,_ in model.body.named_parameters()}|{
        head+"."+name for head in ("non_action_head","action_head") for name in action.HEAD_NAMES}|{"clause_to_embedding.weight"}
    _require(set(model._modules)=={"body","non_action_head","action_head","clause_to_embedding"}
        and set(model._buffers)=={"head_initialization_seed","clause_source_mean","clause_source_scale","ordered_clause_recurrent_version"}
        and set(dict(model.named_parameters()))==expected_parameters,"ordered outer state has unexpected parameters or buffers")
    layer=getattr(model,"clause_to_embedding",None);version=getattr(model,"ordered_clause_recurrent_version",None)
    _require(type(layer) is torch.nn.Linear and layer.bias is None and tuple(layer.weight.shape)==(EMBEDDING_WIDTH,FEATURE_WIDTH)
        and layer.weight.requires_grad,"ordered residual geometry or trainability differs")
    _require(isinstance(version,torch.Tensor) and version.dtype==torch.long and version.device.type=="cpu"
        and version.ndim==0 and int(version)==VERSION,"ordered version must be exact int64")
    expected={"recurrent_feature_dimension":FEATURE_WIDTH,"recurrent_embedding_width":EMBEDDING_WIDTH,
        "recurrent_parameter_names":["clause_to_embedding.weight"],"recurrent_parameter_count":FEATURE_WIDTH*EMBEDDING_WIDTH,
        "added_recurrent_parameters":FEATURE_WIDTH*EMBEDDING_WIDTH,"ordered_clause_recurrent_version":VERSION,
        "clause_routing":"completed_rule_count_after_each_consumed_token","recurrent_feature_order":["non_action","action"],
        "invalid_or_exhausted_clause_route":"zero_residual_no_forced_closure","post_array_close_clause_route":"zero_residual",
        "state_layout":["recurrent_hidden","projected_source","consumed_prefix_position","source_count_logits",
            "causal_grammar_state","source_value_logits","source_clause_recurrent_features"]}
    _require(all(spec.get(k)==v for k,v in expected.items()),"ordered routing/state specification differs")
    for name in ("initial_recurrent_residual_zero","initial_decoder_logits_unchanged","paired_fresh_initial_logits_exact",
        "recurrent_path_changed","source_context_used_for_recurrence","source_clause_availability_used_for_recurrence",
        "source_clause_count_used_for_stopping"):
        _require(spec.get(name) is True,"ordered source policy differs: "+name)
    for name in (*FALSE,"source_context_used_for_scalar_head_only","source_clause_count_forces_stopping",
        "source_clause_count_explicit_numeric_feature","source_context_cached_on_module","syntax_forced","closure_forced",
        "generation_reference_count_access","reference_documents_passed_to_generation","encoder_context_changed","output_budget_changed"):
        _require(spec.get(name) is False,"ordered authority/source policy differs: "+name)
    _require(core._SHA.fullmatch(spec.get("inherited_weights_sha256","")) is not None,"inherited tensor digest required")
    return deepcopy(spec)


def bind_residual_off_model(model):
    """Private inference control removing only the new recurrent clause residual."""
    torch=core._torch();core._model(model,torch)
    _require(model.describe().get("schema")==SCHEMA,"ordered clause model required")
    class ResidualOff(torch.nn.Module):
        def __init__(self):
            super().__init__();self.body=deepcopy(model);self.dimension=model.dimension
        def project(self,x):return self.body.project(x)
        def count_logits(self,x):return self.body.count_logits(x)
        def source_action_features(self,x,*,source_context):return self.body.source_action_features(x,source_context=source_context)
        def action_features(self,x,*,source_context):return self.source_action_features(x,source_context=source_context)
        def source_value_logits(self,x,*,source_context):return self.body.source_value_logits(x,source_context=source_context)
        def source_value_guidance_logits(self,x,*,source_context):return self.source_value_logits(x,source_context=source_context)
        def source_recurrent_features(self,x,*,source_context):
            return torch.zeros_like(self.body.source_recurrent_features(x,source_context=source_context))
        def start(self,x,*,source_context):
            state=self.body.start(x,source_context=source_context)
            return (*state[:6],torch.zeros_like(state[6]))
        def next_logits(self,tokens,state):return self.body.next_logits(tokens,state)
        def forward(self,x,prefix,*,source_context):
            projected=self.project(x);logits,_=self.next_logits(prefix,self.start(projected,source_context=source_context))
            return projected,logits
        def describe(self):
            return dict(schema="ordered-clause-recurrent-residual-off-control/v1",dimension=self.dimension,
                scalar_mode="raw",only_recurrent_clause_residual_zeroed=True,paragraph_scalar_count_paths_preserved=True,
                source_context_required=True,scope="development_ablation_only",**FALSE)
    return ResidualOff()


def bind_zero_condition_model(model):
    """Remove all source routes/mask; preserve established scalar/count bias priors."""
    torch=core._torch();core._model(model,torch)
    _require(model.describe().get("schema")==SCHEMA,"ordered clause model required")
    class ZeroCondition(torch.nn.Module):
        def __init__(self):
            super().__init__();self.body=deepcopy(model);self.dimension=model.dimension
        def project(self,x):return self.body.project(x)
        def _zero_features(self,x,source_context):
            self.body.body.body._inputs(x);clauses._context(torch,x,source_context,self.dimension)
            return x.new_zeros((len(x),MAX_RULES,self.dimension))
        def count_logits(self,x):
            self.body.body.body._inputs(x);return self.body.body._counts(torch.zeros_like(x))
        def source_action_features(self,x,*,source_context):return self.body.action_head.features(self._zero_features(x,source_context))
        def action_features(self,x,*,source_context):return self.source_action_features(x,source_context=source_context)
        def source_value_logits(self,x,*,source_context):return self.body._values(self._zero_features(x,source_context))
        def source_value_guidance_logits(self,x,*,source_context):return self.source_value_logits(x,source_context=source_context)
        def source_recurrent_features(self,x,*,source_context):
            self._zero_features(x,source_context);return x.new_zeros((len(x),MAX_RULES,FEATURE_WIDTH))
        def start(self,x,*,source_context):
            values=self.source_value_logits(x,source_context=source_context)
            hidden,source,position=self.body.body.body.start(x)
            return (torch.zeros_like(hidden),torch.zeros_like(source),position,self.count_logits(x),
                torch.zeros((len(x),6),dtype=torch.long),values,self.source_recurrent_features(x,source_context=source_context))
        def next_logits(self,tokens,state):return self.body.next_logits(tokens,state)
        def forward(self,x,prefix,*,source_context):
            projected=self.project(x);logits,_=self.next_logits(prefix,self.start(projected,source_context=source_context))
            return projected,logits
        def describe(self):
            return dict(schema="zero-ordered-clause-recurrent-control/v1",dimension=self.dimension,scalar_mode="raw",
                initial_hidden_zeroed=True,persistent_source_zeroed=True,normalized_count_source_zeroed=True,
                normalized_clause_features_zeroed=True,original_clause_mask_ignored=True,all_eight_bias_slots_retained=True,
                recurrent_clause_features_zeroed=True,action_and_non_action_bias_priors_retained=True,
                learned_head_biases_and_frozen_count_prior_retained=True,projection_preserved=True,
                prefix_and_parser_state_preserved=True,source_context_required=True,scope="development_ablation_only",**FALSE)
    return ZeroCondition()

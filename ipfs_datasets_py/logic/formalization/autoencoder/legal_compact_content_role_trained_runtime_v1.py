"""Model-only scoring for intact role-training checkpoints.

The role owner validates its own immutable basis, current state and lineage.
Only a separately named, target-free model view reaches the existing private
prepared numerical lifetime. No Adam or old checkpoint schema relabel occurs.
"""
from copy import deepcopy
import hashlib
import importlib
import json
import math
from pathlib import Path
import stat

SCHEMA = 'legal-role-trained-content-generation/v1'
SCORE_SCHEMA = 'legal-role-trained-content-scores/v1'
INSPECT_SCHEMA = 'legal-role-trained-content-inference-inspection/v1'
PROFILE = 'bounded-role-trained-compact384-model-only-inference/v1'
SERVING_SCHEMA = 'legal-role-model-serving-view/v1'
MAX_PREFIXES = 64
MAX_TOTAL_IDS = 512
MAX_CONTEXT_BYTES = 524288
MAX_REPORT_BYTES = 16 * 1024**2
AUTHORITY = dict.fromkeys(('accepted','admitted','source_encoder_authenticated',
    'source_semantics_verified','context_permission_verified','prefix_origin_verified',
    'heldout_accuracy','statutory_accuracy','graph_admission','Lean_admission','native_admission'),False)
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SPECS = (
    ('role','logic/formalization/autoencoder/legal_compact_content_role_training_v1.py',
     '7d1562aa7109dc9998fcf533357262a352e9a8c72425bf5d4c02537a9e0d685c'),
    ('prepared','logic/formalization/autoencoder/legal_compact_content_prepared_runtime_v3.py',
     'a7d7cedfa482537ac76a9ccf9a49a79f6108e89268b02ca3b355abcfe774ec1e'),
    ('scope','logic/formalization/autoencoder/legal_compact_content_scope_filter_v1.py',
     '7b77e5d71012f9394ec0eb9fa05a70310644a3ed5e334f8e91904354b6a187b9'),
)
_POLICY = 'lexically-bound-variable-predicate-arguments/v1'
_MODEL_FIELDS = ('runtime','config','codec','codec_sha256','parameter_order','model_state','weights_sha256')
_LIMITATIONS = (
    'The intact role checkpoint validator reads exposed basis targets and recomputes their inventories; numerical serving is target-free, not the entire validation operation.',
    'The model-only view has its own schema. Current role weights and lineage are never relabeled as a previous checkpoint schema.',
    'Only supplied conditioning and each supplied prefix enter the model; both remain caller observations, not authenticated source semantics.',
    'Weights, historical Adam and lineage are validated commitments; no historical training is independently replayed by this operation.',
    'Role weights remain training provenance. Inference does not reweight logits or perform a training objective.',
    'Every forward consumes its complete prefix. Splitting the same prefix list across calls does not establish incremental hidden-state caching or autoregressive quality.',
    'Local syntax and scoring do not establish faithful legal interpretation, reconstruction, graph admission or proof validity.',
    'Complete or blocked prefixes allocate no model and establish no verified live numerical runtime.',
    'Source, immutable state, runtime and RNG guards are bounded custody checks, not operating-system or arbitrary-bytecode attestation.',
)


class RoleTrainedRuntimeError(ValueError):
    """Role checkpoint, input, source or numerical custody contract failed."""


def _need(ok,message):
    if not ok:
        raise RoleTrainedRuntimeError(message)


def _source(path,expected):
    _need(path.is_absolute() and path.resolve(strict=True)==path,'unaliased canonical source required')
    before=path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<before.st_size<=131072,
          'bounded single-link source required')
    raw=path.read_bytes();after=path.lstat()
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)
    _need(identity(before)==identity(after) and len(raw)==before.st_size
          and hashlib.sha256(raw).hexdigest()==expected,'source bytes or identity changed')
    return dict(path=str(path),bytes=len(raw),sha256=expected),identity(after)


def _sources():
    root=None
    for ancestor in _SELF_PATH.parents:
        for candidate in (ancestor/'ipfs_datasets_py',ancestor/'external/ipfs_datasets/ipfs_datasets_py'):
            if (candidate/_SPECS[0][1]).is_file():
                root=candidate;break
        if root is not None:break
    _need(root is not None,'canonical role and prepared runtime owners unavailable')
    return root,[_source(_SELF_PATH,_SELF_SHA),*[_source(root/relative,pin) for _,relative,pin in _SPECS]]


def _operation(original,work):
    root,observed=_sources()
    owners,loaded,scope_owners,failure={},None,None,None
    def outer():
        _need(_sources()==(root,observed),'role inference source custody changed')
        for key,relative,_ in _SPECS:
            if key in owners:
                _need(type(owners[key].__file__) is str and Path(owners[key].__file__).absolute()==root/relative,
                      'role inference dependency origin changed')
        if loaded is not None:
            _need(owners['prepared']._sources()==loaded[:2],'prepared numerical source custody changed')
            for key,_,relative,_ in owners['prepared']._SOURCE_SPECS:
                if key is not None:
                    _need(Path(loaded[2][key].__file__).absolute()==root/relative,'prepared dependency origin changed')
        if scope_owners is not None:
            current=owners['scope']._owners()
            _need(current[0] is scope_owners[0] and current[1] is scope_owners[1]
                  and current[2]==scope_owners[2],'scope dependency custody changed')
    try:
        for key,relative,_ in _SPECS:
            module=importlib.import_module('ipfs_datasets_py.'+relative[:-3].replace('/','.'))
            _need(type(module.__file__) is str and Path(module.__file__).absolute()==root/relative,
                  'canonical role inference dependency required')
            owners[key]=module
        loaded=owners['prepared']._owners()
        scope_owners=owners['scope']._owners()
        _need(loaded[0]==root and scope_owners[0] is loaded[2]['selection']
              and scope_owners[1] is loaded[2]['tokens'] and owners['scope'].POLICY==_POLICY,
              'scope and numerical dependency identities disagree')
        with owners['role']._scope(original) as (data,modules,input_fence):
            role_root,role_owners,role_observed=owners['role']._owners()
            _need(role_root==root and all(modules[k] is m for k,m in role_owners.items()),
                  'role validation and inference dependency roots differ')
            custody_root,_,custody_observed=modules['custody']._owners()
            scope_sources=modules['scope_training']._sources()
            weighted_sources=modules['weighted']._sources()
            _need(custody_root==scope_sources[0]==weighted_sources[0]==root,'complete checkpoint source roots differ')
            pins={}
            descriptors=[row[0] for row in observed+loaded[1]+scope_sources[1]+weighted_sources[1]]
            descriptors += [row[0] for row in role_observed.values()]+[row[0] for row in custody_observed.values()]+scope_owners[2]
            for item in descriptors:
                _need(item['path'] not in pins or pins[item['path']]==item,'overlapping dependency pins disagree')
                pins[item['path']]=item
            def fence():
                input_fence();outer()
            fence()
            result=work(data,owners,modules,loaded,[pins[k] for k in sorted(pins)],scope_owners[2],fence)
            raw=owners['prepared']._wire(result,MAX_REPORT_BYTES)
            fence()
            return json.loads(raw)
    except BaseException as error:
        failure=error
        if isinstance(error,ValueError) and not isinstance(error,RoleTrainedRuntimeError):
            failure=RoleTrainedRuntimeError(str(error));raise failure from error
        raise
    finally:
        try:outer()
        except BaseException:
            if failure is None:raise
            BaseException.add_note(failure,'A closing role inference custody check also failed.')


def _checked(data,owners,modules,fence):
    value=owners['role']._validate(data['checkpoint'],data['expected_checkpoint_sha256'],
                                 data['expected_policy_sha256'],modules)
    fence()
    return value


def _identity(value,data):
    return dict(checkpoint_sha256=data['expected_checkpoint_sha256'],
        checkpoint_schema=value['schema'],checkpoint_profile=value['profile'],
        objective_policy_sha256=data['expected_policy_sha256'],
        objective_weighting=value['objective_policy']['weighting'],objective_kind='scope_conditional',
        basis_checkpoint_sha256=value['basis_checkpoint_sha256'],basis_policy_sha256=value['basis_policy_sha256'],
        role_inventories_sha256=value['role_inventories_sha256'],weights_sha256=value['weights_sha256'],
        codec_sha256=value['codec_sha256'],initial_weights_sha256=value['initial_weights_sha256'],
        initial_checkpoint_sha256=value['initial_checkpoint_sha256'],parent_checkpoint_sha256=value['parent_checkpoint_sha256'],
        progress=deepcopy(value['progress']),historical_optimizer_state_sha256=value['optimizer_state_sha256'],
        checkpoint_schema_conversion_performed=False)


def _serving(value,data):
    """Explicit target-free field projection, never an older checkpoint type."""
    view=dict(schema=SERVING_SCHEMA,**_identity(value,data))
    for key in _MODEL_FIELDS:view[key]=deepcopy(value[key])
    return view


def inspect(checkpoint,*,expected_checkpoint_sha256,expected_policy_sha256):
    """Validate the intact role type and expose model-view identity without allocation."""
    def work(data,owners,modules,loaded,pins,scope_pins,fence):
        value=_checked(data,owners,modules,fence)
        view=_serving(value,data);helper=owners['prepared']
        return dict(schema=INSPECT_SCHEMA,profile=PROFILE,**_identity(value,data),
            serving_view_schema=SERVING_SCHEMA,serving_view_sha256=helper._digest(view),
            serving_view_fields=sorted(view),serving_view_contains_training_targets=False,
            serving_view_contains_optimizer_state=False,checkpoint_inspection_count=1,
            model_restore_count=0,numerical_forward_count=0,model_executed=False,runtime_verified=False,
            training_executed=False,optimizer_constructed=False,optimizer_state_restored=False,
            target_access_for_checkpoint_validation=True,owner_pins=pins,scope_owner_pins=deepcopy(scope_pins),
            authority=dict(AUTHORITY),training_mask=0,evaluation_gold_mask=0,limitations=list(_LIMITATIONS))
    return _operation(dict(checkpoint=checkpoint,expected_checkpoint_sha256=expected_checkpoint_sha256,
                           expected_policy_sha256=expected_policy_sha256),work)


def _inputs(data,helper,role):
    role._sha(data['expected_context_sha256'],'context')
    _need(type(data['context_raw']) is bytes and 0<len(data['context_raw'])<=MAX_CONTEXT_BYTES
          and hashlib.sha256(data['context_raw']).hexdigest()==data['expected_context_sha256'],
          'independently pinned bounded context bytes required')
    _need(type(data['conditioning']) is list and len(data['conditioning'])==384
          and all(type(x) in (int,float) and math.isfinite(x) and abs(x)<=1e8 for x in data['conditioning']),
          'bounded plain384 conditioning vector required')
    prefixes=data['prefixes_ids']
    _need(type(prefixes) is list and 1<=len(prefixes)<=MAX_PREFIXES,'bounded nonempty prefix population required')
    _need(all(type(ids) is list and 1<=len(ids)<=MAX_TOTAL_IDS
              and all(type(x) is int and 0<=x<537 for x in ids) for ids in prefixes),
          'nonempty bounded token prefixes required')
    _need(type(data['prefix_origin']) is str and data['prefix_origin'] in helper.PREFIX_ORIGINS
          and (data['prefix_origin']!='bos_seed' or all(ids==[1] for ids in prefixes)),
          'declared prefix origin differs')
    _need(type(data['context_origin']) is str and data['context_origin'] in helper.CONTEXT_ORIGINS,
          'declared context origin differs')


def score_prefixes(checkpoint,conditioning,prefixes_ids,context_raw,*,expected_checkpoint_sha256,
                   expected_policy_sha256,expected_context_sha256,prefix_origin,context_origin):
    """Score up to64 supplied prefixes with one private immutable model lifetime.

    Each allowed prefix is a full-prefix forward. No token is selected, no
    hidden state is cached across forwards, and no session escapes this call.
    """
    original=dict(checkpoint=checkpoint,conditioning=conditioning,prefixes_ids=prefixes_ids,context_raw=context_raw,
        expected_checkpoint_sha256=expected_checkpoint_sha256,expected_policy_sha256=expected_policy_sha256,
        expected_context_sha256=expected_context_sha256,prefix_origin=prefix_origin,context_origin=context_origin)
    def work(data,owners,modules,loaded,pins,scope_pins,fence):
        helper,scope=owners['prepared'],owners['scope']
        _inputs(data,helper,owners['role']);value=_checked(data,owners,modules,fence)
        view=_serving(value,data);view_fingerprint=helper._fingerprint(view)
        view_sha=helper._digest(view)
        def serving_fence():
            fence()
            _need(helper._fingerprint(view)==view_fingerprint,'target-free serving view changed')
        options=dict(expected_context_sha256=data['expected_context_sha256'],codec=view['codec'],
                     expected_codec_sha256=view['codec_sha256'])
        token_paths={str(loaded[0]/'logic/formalization/autoencoder/legal_compact_content_tokens_v1.py'),
                     str(loaded[0]/'logic/autoformal/legal_compact_content_v1.py')}
        session,failure=None,None
        def guard():
            if session is None:serving_fence()
            else:session._guard()
        rows=[]
        try:
            for index,prefix in enumerate(data['prefixes_ids']):
                guard()
                report=scope.allowed_token_ids(prefix,data['context_raw'],**options)
                _need(report['schema']==scope.PREFIX_SCHEMA and report['policy']==_POLICY
                      and report['owner_pins']==scope_pins and report['offered_ids']==prefix
                      and report['context_raw_sha256']==data['expected_context_sha256']
                      and report['codec_sha256']==view['codec_sha256']
                      and report['authority'] and all(v is False for v in report['authority'].values())
                      and type(report['training_mask']) is type(report['evaluation_gold_mask']) is int
                      and report['training_mask']==report['evaluation_gold_mask']==0,'scope prefix producer differs')
                helper._producer_rows(report['baseline_prefix_report'],loaded,token_paths)
                _need(set(report['allowed_token_ids'])<=set(report['baseline_prefix_report']['allowed_token_ids']),
                      'scope policy expanded baseline choices')
                guard();allowed=bool(report['allowed_token_ids']);restored=False
                logits=shape=None
                if allowed:
                    if session is None:
                        session=helper._PreparedModel(view,data['conditioning'],loaded,serving_fence)
                        restored=True
                    guard();observed=session.forward(prefix);guard()
                    logits,shape=observed['logits'],observed['output_shape']
                    _need(observed['runtime']==view['runtime'] and shape==[1,len(prefix),537]
                          and observed['numeric_conditioning']==loaded[2]['legacy_head']._conditioning(data['conditioning'])
                          and type(logits) is list and len(logits)==537
                          and all(type(x) is float and math.isfinite(x) for x in logits),
                          'complete finite model-only score observation differs')
                rows.append(dict(prefix_index=index,prefix_ids=list(prefix),prefix_report=report,
                    status='scored' if allowed else 'no_forward',reason=None if allowed else (report['reason'] or report['status']),
                    allowed_token_ids=list(report['allowed_token_ids']),logits=logits,
                    logits_sha256=helper._digest(logits) if allowed else None,output_shape=shape,
                    numerical_forward_executed=allowed,model_restore_performed=restored,
                    prepared_model_reused=allowed and not restored,selection_performed=False))
                guard()
            count=sum(row['numerical_forward_executed'] for row in rows)
            result=dict(schema=SCORE_SCHEMA,profile=PROFILE,**_identity(value,data),
                serving_view_schema=SERVING_SCHEMA,serving_view_sha256=view_sha,serving_view_fields=sorted(view),
                serving_view_contains_training_targets=False,serving_view_contains_optimizer_state=False,
                scope_policy=_POLICY,scope_owner_pins=deepcopy(scope_pins),owner_pins=pins,
                conditioning=deepcopy(data['conditioning']),conditioning_sha256=helper._digest(data['conditioning']),
                context_raw_sha256=data['expected_context_sha256'],prefix_origin=data['prefix_origin'],context_origin=data['context_origin'],
                prefixes_ids=deepcopy(data['prefixes_ids']),scores=rows,
                model_restore_count=int(session is not None),numerical_forward_count=count,checkpoint_inspection_count=1,
                model_executed=bool(count),runtime_verified=bool(count),training_executed=False,
                optimizer_constructed=False,optimizer_state_restored=False,token_selection_performed=False,
                target_access_for_checkpoint_validation=True,
                supplied_prefix_target_access_declared=data['prefix_origin']=='target_derived_label',
                supplied_context_target_access_declared=data['context_origin']=='target_derived_label',
                actual_model_inputs=['conditioning_vector','supplied_prefix_ids'],
                settings=dict(max_prefixes=MAX_PREFIXES,max_total_ids=MAX_TOTAL_IDS,full_prefix_each_step=True,
                    cross_call_model_cache=False,incremental_hidden_state=False),
                authority=dict(AUTHORITY),training_mask=0,evaluation_gold_mask=0,limitations=list(_LIMITATIONS))
            guard();return result
        except BaseException as error:
            failure=error;raise
        finally:
            if session is not None:loaded[2]['legacy_head']._finish(failure,session.close)
    return _operation(original,work)


def score(checkpoint,conditioning,prefix_ids,context_raw,*,expected_checkpoint_sha256,
          expected_policy_sha256,expected_context_sha256,prefix_origin,context_origin):
    """Single-prefix convenience operation with the same bounded score report."""
    return score_prefixes(checkpoint,conditioning,[prefix_ids],context_raw,
        expected_checkpoint_sha256=expected_checkpoint_sha256,expected_policy_sha256=expected_policy_sha256,
        expected_context_sha256=expected_context_sha256,prefix_origin=prefix_origin,context_origin=context_origin)


def generate(checkpoint, conditioning, prefix_ids, context_raw, *, expected_checkpoint_sha256,
             expected_policy_sha256, expected_context_sha256, max_new_tokens, prefix_origin, context_origin):
    """Run at most64 scope-selected tokens with one target-free model-only restore."""
    original = dict(checkpoint=checkpoint, conditioning=conditioning, prefix_ids=prefix_ids,
        context_raw=context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_policy_sha256=expected_policy_sha256, expected_context_sha256=expected_context_sha256,
        max_new_tokens=max_new_tokens, prefix_origin=prefix_origin, context_origin=context_origin)
    def work(data, owners, modules, loaded, pins, scope_pins, fence):
        helper, scope = owners['prepared'], owners['scope']
        _need(type(data['max_new_tokens']) is int and 1 <= data['max_new_tokens'] <= 64,
              'new-token allowance must be a plain integer in 1..64')
        scoring_inputs = dict(data, prefixes_ids=[data['prefix_ids']])
        _inputs(scoring_inputs, helper, owners['role'])
        value = _checked(data, owners, modules, fence)
        view = _serving(value, data)
        view_fingerprint, view_sha = helper._fingerprint(view), helper._digest(view)
        def serving_fence():
            fence()
            _need(helper._fingerprint(view) == view_fingerprint, 'target-free serving view changed')
        tokens = loaded[2]["tokens"]
        root = loaded[0]
        token_paths = {str(root / "logic/formalization/autoencoder/legal_compact_content_tokens_v1.py"),
                       str(root / "logic/autoformal/legal_compact_content_v1.py")}
        options = dict(expected_context_sha256=data["expected_context_sha256"],
                       codec=value["codec"], expected_codec_sha256=value["codec_sha256"])
        current, emitted, trace = list(data["prefix_ids"]), [], []
        session, failure = None, None
        def guard():
            if session is None:
                serving_fence()
            else:
                session._guard()
        def scope_report(report, schema):
            _need(report["schema"] == schema and report["policy"] == _POLICY
                  and report["owner_pins"] == scope_pins
                  and report["authority"] and all(v is False for v in report["authority"].values())
                  and type(report["training_mask"]) is int and report["training_mask"] == 0
                  and type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0,
                  "scope producer identity or authority differs")
        def prefix_report(ids):
            guard()
            report = scope.allowed_token_ids(ids, data["context_raw"], **options)
            scope_report(report, scope.PREFIX_SCHEMA)
            helper._producer_rows(report["baseline_prefix_report"], loaded, token_paths)
            _need(set(report["allowed_token_ids"]) <= set(report["baseline_prefix_report"]["allowed_token_ids"]),
                  "scope policy expanded baseline choices")
            _need(report["offered_ids"] == ids and report["context_raw_sha256"] == data["expected_context_sha256"]
                  and report["codec_sha256"] == value["codec_sha256"], "public prefix binding differs")
            guard()
            return report
        try:
            final_prefix = prefix_report(current)
            status, reason = None, None
            if final_prefix["status"] == "complete":
                status, reason = "supplied_complete", "supplied_prefix_already_complete"
            elif not final_prefix["allowed_token_ids"]:
                status, reason = "blocked", final_prefix["reason"] or final_prefix["status"]
            else:
                while len(emitted) < data["max_new_tokens"]:
                    restored = session is None
                    if restored:
                        # This explicit new-schema view omits targets and Adam.
                        # It is not an old-schema checkpoint or authority grant.
                        session = helper._PreparedModel(view, data["conditioning"], loaded, serving_fence)
                    guard()
                    observed = session.forward(current)
                    logits = observed["logits"]
                    _need(observed["runtime"] == value["runtime"]
                          and observed["output_shape"] == [1, len(current), 537]
                          and type(logits) is list and len(logits) == 537
                          and all(type(x) is float and math.isfinite(x) for x in logits),
                          "actual complete scope-trained model output differs")
                    selected = scope.select_token(logits, current, data["context_raw"], **options)
                    scope_report(selected, scope.SELECTION_SCHEMA)
                    _need(selected["baseline_selection"]["prefix_report"] == final_prefix["baseline_prefix_report"],
                          "local baseline observation disagrees with prefix owner")
                    _need(selected["selection_performed"] is True and selected["prefix_report"] == final_prefix
                          and selected["offered_prefix_ids"] == current and selected["logits"] == logits
                          and selected["logits_sha256"] == helper._digest(logits)
                          and type(selected["selected_token_id"]) is int
                          and selected["selected_token_id"] in final_prefix["allowed_token_ids"]
                          and selected["next_prefix_ids"] == current + [selected["selected_token_id"]],
                          "public selected token disagrees with bound full537 output")
                    guard()
                    trace.append(dict(prefix_ids=list(current), logits=logits, logits_sha256=helper._digest(logits),
                        selection=selected, prefix_report=final_prefix, next_prefix_ids=list(selected["next_prefix_ids"]),
                        model_restore_performed=restored, prepared_model_reused=not restored,
                        output_shape=observed["output_shape"]))
                    emitted.append(selected["selected_token_id"])
                    current = list(selected["next_prefix_ids"])
                    final_prefix = prefix_report(current)
                    if final_prefix["status"] == "complete":
                        status, reason = "complete", None
                        break
                    if not final_prefix["allowed_token_ids"]:
                        status, reason = "blocked", final_prefix["reason"] or final_prefix["status"]
                        break
                else:
                    status, reason = "step_budget_exhausted", "max_new_tokens_reached"
            guard()
            decoded = tokens.decode_compact_content_tokens_v1(current, data["context_raw"], **options)
            helper._producer_rows(decoded, loaded, token_paths)
            _need(decoded["generated_ids"] == current and decoded["context_raw_sha256"] == data["expected_context_sha256"]
                  and decoded["codec_sha256"] == value["codec_sha256"]
                  and decoded["context_sha256"] == final_prefix["context_sha256"]
                  and ((status in ("complete", "supplied_complete")) == (decoded["status"] == "valid_candidate")),
                  "final public intake disagrees with generated prefix or terminal disposition")
            guard()
            return dict(schema=SCHEMA, profile=PROFILE,
                **_identity(value, data),
                serving_view_schema=SERVING_SCHEMA, serving_view_sha256=view_sha,
                serving_view_fields=sorted(view), serving_view_contains_training_targets=False,
                serving_view_contains_optimizer_state=False,
                scope_policy=_POLICY, scope_owner_pins=deepcopy(scope_pins),
                scope_filter_source=next(deepcopy(p) for p in scope_pins if p["path"].endswith(_SPECS[2][1])),
                checkpoint_training_grammar_unchanged=True,
                local_baseline_decisions_are_independent_trajectory=False,
                conditioning=deepcopy(data["conditioning"]), conditioning_sha256=helper._digest(data["conditioning"]),
                context_raw_sha256=data["expected_context_sha256"], context_sha256=decoded["context_sha256"],
                initial_prefix_ids=list(data["prefix_ids"]), generated_ids=current, selected_token_ids=emitted,
                prefix_origin=data["prefix_origin"], context_origin=data["context_origin"],
                trace=trace, model_restore_count=int(session is not None), numerical_forward_count=len(trace),
                checkpoint_inspection_count=1, status=status, reason=reason,
                final_prefix_report=final_prefix, final_decoding=decoded,
                settings=dict(max_new_tokens=data["max_new_tokens"], max_total_ids=MAX_TOTAL_IDS,
                    full_prefix_each_step=True, cross_call_model_cache=False, incremental_hidden_state=False),
                emitted_token_count=len(emitted), total_token_count=len(current),
                model_executed=bool(trace), runtime_verified=bool(trace), training_executed=False,
                optimizer_constructed=False, optimizer_state_restored=False,
                target_access_for_checkpoint_validation=True,
                supplied_prefix_target_access_declared=data["prefix_origin"] == "target_derived_label",
                supplied_context_target_access_declared=data["context_origin"] == "target_derived_label",
                actual_model_inputs=["conditioning_vector", "supplied_or_generated_prefix_ids"],
                authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0,
                owner_pins=pins, limitations=list(_LIMITATIONS) + [
                    "Generation uses the unchanged lexical scope selector and final typed decoder; no whole-prefix reconstruction quality is implied by a bounded continuation.",
                    "Old-selector comparisons along these refined prefixes are not an independently generated baseline trajectory."])
        except BaseException as error:
            failure = error
            raise
        finally:
            if session is not None:
                loaded[2]["legacy_head"]._finish(failure, session.close)
    return _operation(original, work)


__all__=['RoleTrainedRuntimeError','inspect','score','score_prefixes','generate']

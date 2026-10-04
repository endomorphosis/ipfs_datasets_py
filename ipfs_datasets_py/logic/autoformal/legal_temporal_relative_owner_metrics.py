"""Independent relative-position pointer metrics and prospective acceptance policy.

Surface distances carry no legal attachment interpretation. Calibration uses
only its declared reference split after checkpoint selection; zero observed
errors and support floors are design heuristics, not a safety guarantee.
"""
from __future__ import annotations
import math
import re
import struct
from . import legal_temporal_coupled_span_metrics as previous

CLASSES,SOURCE_KEYS,TARGET_KEYS=previous.CLASSES,previous.SOURCE_KEYS,previous.TARGET_KEYS
require,wire=previous.require,previous.wire
source_tokens,anchor_tokens,validate_target=previous.source_tokens,previous.anchor_tokens,previous.validate_target
types=previous.types
ARMS=('source_pointer','relative_position','relative_norm_contrast')
RELATIVE_FIELDS={'base_pointer_start_logits','base_pointer_end_logits','relative_start_logits','relative_end_logits','relative_enabled'}
PREDICTION_KEYS=previous.PREDICTION_KEYS|RELATIVE_FIELDS
GRID=(.8,.85,.9,.95,.975,.99)
CALIBRATION_PANELS=('calibration_lexical','calibration_structural')
TYPE_THRESHOLD=.8
POLICY_SCHEMA='legal-temporal-relative-owner-acceptance-policy/v1'
SUPPORT={'minimum_accepted_queries':48,'minimum_accepted_sources':24,'minimum_accepted_queries_per_panel':12}


def float32(value):
    require(type(value) in (int,float) and math.isfinite(value),'finite scalar required')
    return struct.unpack('!f',struct.pack('!f',float(value)))[0]


def source_features(source):
    """Twelve bounded features reconstructed solely from exact source tokens."""
    tokens,(a,b)=source_tokens(source);n=len(tokens);denominator=max(1,n-1);values=[]
    words=[t.group() for t in tokens]
    for i,word in enumerate(words):
        between=words[i+1:a] if i<a else words[b+1:i] if i>b else []
        gap=a-i if i<a else i-b if i>b else 0
        values.append([(i-a)/denominator,(i-b)/denominator,gap/denominator,
            float(i<a),float(i>b),float(a<=i<=b),
            min(between.count(';'),4)/4,min(sum(t in '.!?' for t in between),4)/4,
            min(between.count(','),4)/4,min(between.count(':'),4)/4,
            float(re.fullmatch(r'[^\w\s]',word) is not None),float(word==';')])
    return values


def check_relative_arrays(source,starts,ends,base_starts,base_ends,relative_starts,relative_ends,*,enabled):
    tokens,_=source_tokens(source);n=len(tokens)
    require(type(enabled) is bool,'declared relative switch required')
    for values in (starts,ends,base_starts,base_ends,relative_starts,relative_ends):
        previous.previous._logits(values,n)
        require(all(float32(v)==v for v in values),'serialized endpoint values must be exact float32')
    if not enabled:require(all(v==0. for values in (relative_starts,relative_ends) for v in values),'disabled relative residual must be zero')
    require(all(float32(x+y)==z for base,residual,actual in
        ((base_starts,relative_starts,starts),(base_ends,relative_ends,ends)) for x,y,z in zip(base,residual,actual)),
        'final endpoints differ from float32 base plus applied relative residual')
    return {'source_tokens':n,'relative_enabled':enabled,'source_features':source_features(source)}


def _checked_relative(source,row):
    require(type(row) is dict and set(row) in (previous.PREDICTION_KEYS,PREDICTION_KEYS),'closed relative or parent-coupled prediction required')
    if set(row)==PREDICTION_KEYS:
        require(row['interaction_enabled'] is True,'rank8 interaction remains enabled in all relative-study arms')
        check_relative_arrays(source,row['pointer_start_logits'],row['pointer_end_logits'],
            row['base_pointer_start_logits'],row['base_pointer_end_logits'],row['relative_start_logits'],row['relative_end_logits'],
            enabled=row['relative_enabled'])
    return {k:row[k] for k in previous.PREDICTION_KEYS}


def checked_prediction(source,row):
    return previous.checked_prediction(source,_checked_relative(source,row))


def score(sources,predictions,targets):
    require(type(sources) is list and type(predictions) is list and len(sources)==len(predictions),'complete pointer inventory required')
    by_id={s['id']:s for s in sources}
    stripped=[_checked_relative(by_id[p['id']],p) for p in predictions]
    return previous.score(sources,stripped,targets)


def training_oracle(sources,targets,logits,starts,ends,left,right,contrasts,*,arm,base_starts,base_ends,relative_starts,relative_ends):
    require(arm in ARMS,'declared relative owner arm required')
    require(all(type(v) is list and len(v)==len(sources) for v in
        (starts,ends,base_starts,base_ends,relative_starts,relative_ends)),'complete relative batch columns required')
    for i,source in enumerate(sources):
        check_relative_arrays(source,starts[i],ends[i],base_starts[i],base_ends[i],relative_starts[i],relative_ends[i],enabled=arm!='source_pointer')
        item=contrasts[source['id']]
        require(targets[source['id']]['label']=='norm' or item['negative_owner_spans']==[],
                'only determinate norm queries may receive other-action contrast supervision')
    value=previous.training_oracle(sources,targets,logits,starts,ends,left,right,contrasts,
                                  arm='joint_contrast' if arm=='relative_norm_contrast' else 'joint_span')
    return {**value,'objective':arm,'relative_enabled':arm!='source_pointer',
            'norm_count':sum(targets[s['id']]['label']=='norm' for s in sources),
            'type_head_frozen':True,'source_encoder_frozen':True}


def validate_policy(policy):
    require(type(policy) is dict and set(policy)=={'schema','mode','type_threshold','span_threshold','ambiguous_always_defer',
        'calibration_panel_names','support_requirements','zero_observed_errors_required','selection_rule','safety_guarantee'},'closed acceptance policy required')
    require(policy['schema']==POLICY_SCHEMA and policy['type_threshold']==TYPE_THRESHOLD and type(policy['type_threshold']) is float and
        policy['ambiguous_always_defer'] is True and policy['calibration_panel_names']==list(CALIBRATION_PANELS) and
        wire(policy['support_requirements'])==wire(SUPPORT) and policy['zero_observed_errors_required'] is True and
        policy['selection_rule']=='maximum_accepted_queries_then_higher_span_threshold' and policy['safety_guarantee'] is False,
        'prospective acceptance contract differs')
    require((policy['mode']=='accept_none' and policy['span_threshold'] is None) or
        (policy['mode']=='threshold' and type(policy['span_threshold']) is float and policy['span_threshold'] in GRID),
        'explicit defer-all or declared span grid required')
    return policy


def _policy(threshold):
    return validate_policy({'schema':POLICY_SCHEMA,'mode':'accept_none' if threshold is None else 'threshold',
        'type_threshold':TYPE_THRESHOLD,'span_threshold':threshold,'ambiguous_always_defer':True,
        'calibration_panel_names':list(CALIBRATION_PANELS),'support_requirements':dict(SUPPORT),
        'zero_observed_errors_required':True,'selection_rule':'maximum_accepted_queries_then_higher_span_threshold','safety_guarantee':False})


def acceptance(row,policy):
    validate_policy(policy)
    return (policy['mode']=='threshold' and row['predicted_label']!='ambiguous' and
        row['raw_owner_anchor_span'] is not None and row['type_confidence']>=policy['type_threshold'] and
        row['span_confidence'] is not None and row['span_confidence']>=policy['span_threshold'])


def policy_summary(scored,policy):
    validate_policy(policy);rows=[]
    for row in scored['rows']:
        accepted=acceptance(row,policy);correct=accepted and row['target']!='ambiguous' and row['joint_correct']
        require(not accepted or row['accepted_joint'] is True,'calibration cannot add a fixed-policy acceptance')
        reason=(None if accepted else 'calibration_accept_none' if policy['mode']=='accept_none' else
                row['joint_reason'] if not row['accepted_joint'] else 'below_calibrated_span_confidence')
        rows.append({**row,'fixed_accepted_joint':row['accepted_joint'],'fixed_accepted_joint_correct':row['accepted_joint_correct'],
                     'calibrated_accepted_joint':accepted,'calibrated_accepted_joint_correct':correct,'calibrated_joint_reason':reason})
    total=sum(r['calibrated_accepted_joint'] for r in rows);correct=sum(r['calibrated_accepted_joint_correct'] for r in rows)
    return {'policy':policy,'count':len(rows),'accepted_joint':total,'accepted_joint_correct':correct,'accepted_joint_errors':total-correct,
        'accepted_source_count':len({r['source_sha256'] for r in rows if r['calibrated_accepted_joint']}),
        'joint_coverage':total/len(rows),'selective_joint_error_rate':(total-correct)/total if total else None,
        'per_reference_class':{c:{'count':sum(r['target']==c for r in rows),
            'accepted_joint':sum(r['target']==c and r['calibrated_accepted_joint'] for r in rows),
            'accepted_joint_errors':sum(r['target']==c and r['calibrated_accepted_joint'] and not r['calibrated_accepted_joint_correct'] for r in rows)} for c in CLASSES},
        'raw_joint_correct':scored['joint_correct'],'raw_type_correct':scored['type_correct'],'raw_anchor_exact':scored['anchor_exact'],
        'statistical_safety_guarantee':False,'new_acceptances_beyond_fixed_policy':0,'rows':rows}


def apply_policy_score(sources,predictions,targets,policy):
    return policy_summary(score(sources,predictions,targets),policy)


def calibrate(sources_by_panel,predictions_by_panel,targets_by_panel):
    require(all(type(v) is dict and set(v)==set(CALIBRATION_PANELS) for v in
        (sources_by_panel,predictions_by_panel,targets_by_panel)),'both closed calibration panels required')
    scored={p:score(sources_by_panel[p],predictions_by_panel[p],targets_by_panel[p]) for p in CALIBRATION_PANELS}
    require(all(v['count']==144 for v in scored.values()),'two fixed144-query calibration denominators required')
    source_sets=[{s['source_sha256'] for s in sources_by_panel[p]} for p in CALIBRATION_PANELS]
    query_sets=[{s['id'] for s in sources_by_panel[p]} for p in CALIBRATION_PANELS]
    require(not source_sets[0]&source_sets[1] and not query_sets[0]&query_sets[1],'calibration panel source/query overlap')
    grid=[]
    for threshold in GRID:
        policy=_policy(threshold);values={p:policy_summary(scored[p],policy) for p in CALIBRATION_PANELS}
        accepted=sum(v['accepted_joint'] for v in values.values());errors=sum(v['accepted_joint_errors'] for v in values.values())
        sources=sum(v['accepted_source_count'] for v in values.values())
        constraints={'zero_observed_joint_errors':errors==0,'minimum_accepted_queries':accepted>=48,
                     'minimum_accepted_sources':sources>=24,'minimum_per_panel':all(v['accepted_joint']>=12 for v in values.values())}
        grid.append({'span_threshold':threshold,'accepted_joint':accepted,'accepted_joint_errors':errors,'accepted_source_count':sources,
            'panel_metrics':{p:{k:v for k,v in value.items() if k not in ('rows','policy')} for p,value in values.items()},
            'constraints':constraints,'eligible':all(constraints.values())})
    eligible=[r for r in grid if r['eligible']]
    selected=max(eligible,key=lambda r:(r['accepted_joint'],r['span_threshold'])) if eligible else None
    return {'schema':'legal-temporal-relative-owner-calibration/v1','policy':_policy(None if selected is None else selected['span_threshold']),
        'grid_results':grid,'calibration_queries':288,'selected_accepted_queries':0 if selected is None else selected['accepted_joint'],
        'explicit_defer_all_fallback':selected is None,'support_is_prospective_design_heuristic':True,'statistical_safety_guarantee':False,
        'checkpoint_selection_changed':False,'fresh_results_used':False}

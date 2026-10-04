"""Independent score and exact-coordinate checks for coupled owner pointers.

Low-rank factors are model outputs, never gold candidate inventories. Every
ordered query-disjoint token pair remains eligible. Reference alternatives are
used only by the explicit training-loss oracle, not by inference decoding.
"""
from __future__ import annotations
from collections import Counter
import math
import numpy as np
from . import legal_temporal_owner_pointer_metrics_v2 as previous
from . import legal_temporal_ownership_metrics as types

CLASSES, SOURCE_KEYS, TARGET_KEYS = previous.CLASSES, previous.SOURCE_KEYS, previous.TARGET_KEYS
THRESHOLD=.8
RANK=8
INTERACTION_SCALE=1/math.sqrt(RANK)
EXTRA_FIELDS={'pointer_start_factors','pointer_end_factors','interaction_scale','interaction_enabled'}
PREDICTION_KEYS=previous.PREDICTION_KEYS|EXTRA_FIELDS
ARMS=('endpoint','joint_span','joint_contrast')
require,wire=previous.require,previous.wire
source_tokens,anchor_tokens,validate_target=previous.source_tokens,previous.anchor_tokens,previous.validate_target
_endpoint_nll=previous._endpoint_nll


def _factors(values,n):
    require(type(values) is list and len(values)==n and all(type(row) is list and len(row)==RANK for row in values),
            'full source by rank8 factor matrix required')
    require(all(type(v) in (int,float) and math.isfinite(v) and abs(v)<=1e6 for row in values for v in row),
            'finite bounded factor values required')


def score_at(starts,ends,left,right,i,j,enabled):
    base=float(starts[i])+float(ends[j])
    return base+(math.fsum(float(left[i][k])*float(right[j][k]) for k in range(RANK))*INTERACTION_SCALE) if enabled else base


def pair_distribution(source,starts,ends,left=None,right=None,*,enabled=False,scale=0.):
    tokens,(a,b)=source_tokens(source);n=len(tokens)
    previous._logits(starts,n);previous._logits(ends,n)
    require(type(enabled) is bool and type(scale) in (int,float) and math.isfinite(scale),'declared finite interaction policy required')
    if left is None or right is None:
        require(left is None and right is None and enabled is False and scale==0.,'old pointer has no interaction factors')
    else:
        _factors(left,n);_factors(right,n)
        require(scale==INTERACTION_SCALE,'fixed rank8 interaction scale required')
    pairs=[(i,j) for lo,hi in ((0,a),(b+1,n)) for i in range(lo,hi) for j in range(i,hi)]
    if not pairs:return {'pairs':[],'scores':[],'best_pair':None,'span_confidence':None,'maximum':None,'log_scaled_partition':None,
                         'scalar_fallback':False,'rounding_bound':0.}
    base=np.asarray(starts,dtype=np.float64)[:,None]+np.asarray(ends,dtype=np.float64)[None,:]
    bound=0.
    if enabled:
        l=np.asarray(left,dtype=np.float64);r=np.asarray(right,dtype=np.float64)
        residual=np.zeros_like(base);absolute=np.zeros_like(base)
        for k in range(RANK):
            product=l[:,k,None]*r[None,:,k];residual+=product;absolute+=np.abs(product)
        matrix=base+residual*scale
        # Bound ordinary rank8 accumulation relative to correctly rounded fsum.
        # Large-factor rows use the scalar definition for every valid pair.
        bound=float(np.max(absolute))*np.finfo(np.float64).eps*32*scale
    else:matrix=base
    values=[float(matrix[i,j]) for i,j in pairs]
    fallback=bound>1e-11
    if fallback:
        values=[score_at(starts,ends,left,right,i,j,enabled) for i,j in pairs]
    elif enabled:
        maximum=max(values)
        for index,(i,j) in enumerate(pairs):
            if maximum-values[index]<=max(4*bound,4*math.ulp(maximum)):
                values[index]=score_at(starts,ends,left,right,i,j,enabled)
    best=max(range(len(values)),key=values.__getitem__);maximum=values[best]
    total=math.fsum(math.exp(v-maximum) for v in values)
    require(math.isfinite(total) and total>=1.,'finite normalized pair partition required')
    return {'pairs':pairs,'scores':values,'best_pair':pairs[best],'span_confidence':1/total,
            'maximum':maximum,'log_scaled_partition':math.log(total),'scalar_fallback':fallback,'rounding_bound':bound}


def pair_nll(table,pair):
    require(pair in table['pairs'],'reference pair absent from full syntactic inventory')
    return table['maximum']-table['scores'][table['pairs'].index(pair)]+table['log_scaled_partition']


def span_distribution(source,starts,ends,left=None,right=None,*,enabled=False,scale=0.):
    table=pair_distribution(source,starts,ends,left,right,enabled=enabled,scale=scale)
    tokens,_=source_tokens(source);pair=table['best_pair']
    return {'valid_span_count':len(table['pairs']),'raw_owner_token_span':None if pair is None else list(pair),
        'raw_owner_anchor_span':None if pair is None else {'char_start':tokens[pair[0]].start(),'char_end':tokens[pair[1]].end()},
        'span_confidence':table['span_confidence']}


def checked_prediction(source,row):
    require(type(row) is dict and set(row) in (previous.PREDICTION_KEYS,PREDICTION_KEYS),'closed old/new coupled prediction required')
    old=set(row)==previous.PREDICTION_KEYS
    result=types.checked_prediction(source,{k:row[k] for k in types.PREDICTION_KEYS})
    left=None if old else row['pointer_start_factors'];right=None if old else row['pointer_end_factors']
    enabled=False if old else row['interaction_enabled'];scale=0. if old else row['interaction_scale']
    table=pair_distribution(source,row['pointer_start_logits'],row['pointer_end_logits'],left,right,enabled=enabled,scale=scale)
    tokens,_=source_tokens(source);pair=table['best_pair']
    pointer={'valid_span_count':len(table['pairs']),'raw_owner_token_span':None if pair is None else list(pair),
        'raw_owner_anchor_span':None if pair is None else {'char_start':tokens[pair[0]].start(),'char_end':tokens[pair[1]].end()},
        'span_confidence':table['span_confidence']}
    for k in ('valid_span_count','raw_owner_token_span','raw_owner_anchor_span'):
        require(wire(row[k])==wire(pointer[k]),'coupled argmax/inventory/source coordinate differs')
    if pair is None:
        require(row['span_confidence'] is None,'empty span inventory has no probability');error=0.
    else:
        p=row['span_confidence'];require(type(p) in (int,float) and math.isfinite(p) and 0<=p<=1,'finite span probability required')
        error=abs(p-table['span_confidence']);require(error<=2e-10,'coupled normalized span probability differs')
    reason=('predicted_ambiguous' if result['label']=='ambiguous' else 'no_valid_owner_span' if pair is None else
        'below_fixed_type_confidence' if row['confidence']<THRESHOLD else
        'below_fixed_span_confidence' if row['span_confidence']<THRESHOLD else None)
    require(row['joint_status']==('accepted' if reason is None else 'deferred') and row['joint_reason']==reason and
        wire(row['proposed_owner_anchor_span'])==wire(pointer['raw_owner_anchor_span'] if reason is None else None),'fixed joint acceptance differs')
    return {'type':result,'pointer':pointer,'accepted_joint':reason is None,'span_probability_roundoff':error,'distribution':table}


def training_oracle(sources,targets,logits,starts,ends,left,right,contrasts,*,arm):
    """Pure float64 audit of stored TRAIN logits; never used for inference.

    Every contrast is source-bound supplied supervision. This routine validates
    coordinates; the independent corpus/group audit establishes that negatives
    are actual other annotated owners rather than mined semantic candidates.
    """
    require(arm in ARMS and type(sources) is list and 1<=len(sources)<=64,'bounded declared training arm/batch required')
    n=len(sources)
    require(all(type(x) is list and len(x)==n for x in (logits,starts,ends,left,right)) and
            type(targets) is dict and type(contrasts) is dict,'complete batched outputs and source-bound supervision required')
    type_losses=[];start_losses=[];end_losses=[];joint_losses=[];contrast_losses=[]
    counts=Counter();valid_masks=[];gold_intervals=[];negative_intervals=[];span_counts=[]
    for i,source in enumerate(sources):
        query_id=source['id'];require(query_id in targets and query_id in contrasts,'missing reference/contrast query')
        target=targets[query_id];gold=validate_target(source,target)
        tokens,(a,b)=source_tokens(source);valid=[j for j in range(len(tokens)) if j<a or j>b]
        mask=[j in valid for j in range(len(tokens))];valid_masks.append(mask);gold_intervals.append(gold)
        previous._logits(logits[i],4);label=CLASSES.index(target['label']);counts[target['label']]+=1
        type_losses.append(_endpoint_nll(logits[i],list(range(4)),label))
        table=pair_distribution(source,starts[i],ends[i],left[i],right[i],enabled=arm!='endpoint',scale=INTERACTION_SCALE)
        span_counts.append(len(table['pairs']))
        c=contrasts[query_id]
        require(type(c) is dict and set(c)=={'id','source_sha256','proposed_time_span','negative_owner_spans'} and
                c['id']==query_id and c['source_sha256']==source['source_sha256'] and
                wire(c['proposed_time_span'])==wire(source['proposed_time_span']) and
                type(c['negative_owner_spans']) is list,'closed contrast source/query binding differs')
        negatives=[anchor_tokens(source,v) for v in c['negative_owner_spans']]
        require(negatives==sorted(negatives) and len(negatives)==len({tuple(v) for v in negatives}) and all(v!=gold for v in negatives),
                'contrast must contain distinct non-gold owner spans')
        negative_intervals.append(negatives)
        if gold is None:
            require(not negatives,'ambiguous queries cannot assert one contrast gold')
            continue
        start_losses.append(_endpoint_nll(starts[i],valid,gold[0]));end_losses.append(_endpoint_nll(ends[i],valid,gold[1]))
        joint_losses.append(pair_nll(table,tuple(gold)))
        if negatives:
            candidates=[gold,*negatives]
            values=[score_at(starts[i],ends[i],left[i],right[i],u,v,arm!='endpoint') for u,v in candidates]
            maximum=max(values)
            contrast_losses.append(maximum-values[0]+math.log(math.fsum(math.exp(v-maximum) for v in values)))
    mean=lambda values:math.fsum(values)/len(values) if values else 0.
    type_ce,start_ce,end_ce,joint_ce,contrast_ce=map(mean,(type_losses,start_losses,end_losses,joint_losses,contrast_losses))
    loss=type_ce+(.5*(start_ce+end_ce) if arm=='endpoint' else .5*joint_ce)+(.25*contrast_ce if arm=='joint_contrast' else 0.)
    return {'type_ce':type_ce,'start_ce':start_ce,'end_ce':end_ce,'joint_ce':joint_ce,'contrast_ce':contrast_ce,'loss':loss,
        'query_count':n,'class_counts':[counts[c] for c in CLASSES],'unique_count':len(start_losses),
        'ambiguous_count':counts['ambiguous'],'contrast_count':len(contrast_losses),
        'endpoint_loss':type_ce+.5*(start_ce+end_ce),'pointer_loss_weight':.5,
        'contrast_negative_counts':[len(v) for v in negative_intervals],
        'contrast_negative_span_count':sum(len(v) for v in negative_intervals),
        'applied_contrast_weight':.25 if arm=='joint_contrast' else 0.,
        'interaction_enabled':arm!='endpoint','objective':arm,'selection_nll':type_ce+joint_ce,
        'endpoint_valid_counts':[sum(v) for v in valid_masks],'valid_token_masks':valid_masks,
        'valid_span_counts':span_counts,'gold_owner_token_spans':gold_intervals,'negative_owner_token_spans':negative_intervals}


def score(sources, predictions, targets):
    require(type(sources) is list and 1 <= len(sources) <= 4096 and type(predictions) is list and type(targets) is dict,
            'bounded complete owner evaluation required')
    by_source = {r['id']: r for r in sources}; by_prediction = {r['id']: r for r in predictions}
    require(len(by_source) == len(sources) == len(by_prediction) == len(predictions) == len(targets) and
            set(by_source) == set(by_prediction) == set(targets), 'complete unique owner query join required')
    rows = []; starts = []; ends = []; joints = []; observed = set(); counts = Counter(); max_span_error = 0.
    for source in sources:
        query_id = source['id']; target = targets[query_id]; prediction = by_prediction[query_id]
        reference_tokens = validate_target(source, target); result = checked_prediction(source, prediction)
        identity = (source['source_sha256'], source['proposed_time_span']['char_start'], source['proposed_time_span']['char_end'])
        require(identity not in observed, 'duplicate source/time occurrence'); observed.add(identity)
        ambiguous = target['label'] == 'ambiguous'; type_correct = result['type']['label'] == target['label']
        anchor_exact = None if ambiguous else wire(prediction['raw_owner_anchor_span']) == wire(target['owner_anchor_span'])
        joint_correct = type_correct if ambiguous else type_correct and anchor_exact
        accepted = result['accepted_joint']; accepted_correct = accepted and not ambiguous and joint_correct
        counts.update({'ambiguous_queries': ambiguous, 'unique_owner_queries': not ambiguous,
            'type_correct': type_correct, 'anchor_exact': anchor_exact is True, 'joint_correct': joint_correct,
            'unique_joint_correct': not ambiguous and joint_correct, 'ambiguous_type_correct': ambiguous and type_correct,
            'ambiguous_deferred': ambiguous and not accepted, 'accepted_joint': accepted,
            'accepted_joint_correct': accepted_correct, 'accepted_joint_errors': accepted and not accepted_correct,
            'ambiguous_joint_acceptances': ambiguous and accepted,
            'accepted_wrong_anchor_same_type': accepted and not ambiguous and type_correct and not anchor_exact,
            'determinate_deferred': not ambiguous and not accepted,
            'syntactic_reference_span_covered': not ambiguous})
        if not ambiguous:
            tokens, (a, b) = source_tokens(source); valid = [i for i in range(len(tokens)) if i < a or i > b]
            starts.append(_endpoint_nll(prediction['pointer_start_logits'], valid, reference_tokens[0]))
            ends.append(_endpoint_nll(prediction['pointer_end_logits'], valid, reference_tokens[1]))
            table = result['distribution']
            joints.append(pair_nll(table, tuple(reference_tokens)))
        max_span_error = max(max_span_error, result['span_probability_roundoff'])
        rows.append({'id': query_id, 'source_sha256': source['source_sha256'],
            'proposed_time_span': source['proposed_time_span'], 'target': target['label'],
            'target_owner_anchor_span': target['owner_anchor_span'], 'predicted_label': result['type']['label'],
            'raw_owner_anchor_span': prediction['raw_owner_anchor_span'],
            'proposed_owner_anchor_span': prediction['proposed_owner_anchor_span'],
            'type_correct': type_correct, 'anchor_exact': anchor_exact, 'joint_correct': joint_correct,
            'accepted_joint': accepted, 'accepted_joint_correct': accepted_correct,
            'joint_reason': prediction['joint_reason'], 'type_confidence': prediction['confidence'],
            'span_confidence': prediction['span_confidence'], 'valid_span_count': prediction['valid_span_count']})
    type_metrics = types.score(sources, [{k: p[k] for k in types.PREDICTION_KEYS} for p in predictions],
                              {k: v['label'] for k, v in targets.items()})
    mean_start = math.fsum(starts) / len(starts) if starts else 0.
    mean_end = math.fsum(ends) / len(ends) if ends else 0.
    mean_joint = math.fsum(joints) / len(joints) if joints else 0.
    return {'count': len(rows), **dict(counts), 'joint_accuracy': counts['joint_correct'] / len(rows),
        'joint_coverage': counts['accepted_joint'] / len(rows),
        'selective_joint_error_rate': counts['accepted_joint_errors'] / counts['accepted_joint'] if counts['accepted_joint'] else None,
        'mean_type_nll': type_metrics['mean_nll'], 'mean_start_nll_unique': mean_start,
        'mean_end_nll_unique': mean_end, 'endpoint_composite_nll': type_metrics['mean_nll'] + .5 * (mean_start + mean_end),
        'mean_joint_span_nll_unique': mean_joint, 'selection_nll': type_metrics['mean_nll'] + mean_joint,
        'type_metrics': {k: v for k, v in type_metrics.items() if k != 'rows'},
        'max_span_probability_roundoff': max_span_error, 'type_threshold': THRESHOLD, 'span_threshold': THRESHOLD,
        'candidate_scope': 'all ordered query-disjoint token spans; no semantic owner inventory claim',
        'owner_anchor_exact_match_measured': True, 'independent_legal_gold': False,
        'statutory_semantics_verified': False, 'formula_acceptance_authorized': False,
        'pipeline_promotion': False, 'rows': rows}

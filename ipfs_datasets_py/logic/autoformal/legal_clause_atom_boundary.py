"""Warm-started token-boundary rehearsal and original-parent preservation.

All arms inherit the same unqualified heading research checkpoint. Only its
1,057 residual parameters train. The original encoder, scope head and boundary
head are immutable; teacher outputs and authored role labels are TRAIN-only.
This module does not expand the declared flat-scope interpretation profile.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re

from . import legal_clause_heading_boundary as heading

boundary = heading.boundary
require, digest = heading.require, heading.digest
SCHEMA = 'legal-clause-atom-boundary-checkpoint/v1'
ARMS = ('continuation','atom_rehearsal','distill')
SEED = 1730
ADAPTER_CONFIG = deepcopy(heading.ADAPTER_CONFIG)
ADAPTER_PARAMETERS = heading.ADAPTER_PARAMETERS
TRAINABLE_COUNTS = {arm:1057 for arm in ARMS}
ATOM_WEIGHTS = {'continuation':0.,'atom_rehearsal':.5,'distill':.5}
TEACHER_WEIGHTS = {'continuation':0.,'atom_rehearsal':0.,'distill':.25}
ATOM_PROVENANCE = 'pinned_supported_train_atoms_and_inter_clause_endpoints/v1'
TEACHER_CONFIG = {'teacher':'immutable_original_boundary_parent', 'direction':'KL(parent||candidate)',
    'temperature':1., 'mask':'supported_valid_TRAIN_tokens_with_teacher_threshold_matching_gold',
    'threshold':'logit_greater_than_or_equal_to_zero_is_end',
    'reduction':'mean_of_available_gold_class_means', 'empty_class':'omit_from_class_average',
    'empty_all_classes':'differentiable_zero', 'positive_weight_applied_to_KL':False,
    'teacher_gradients_enabled':False, 'teacher_predictions_used_at_inference':False}


def implementation_sha():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def arm_config(arm):
    require(type(arm) is str and arm in ARMS, 'known atom boundary arm required')
    return {**heading.arm_config('rehearsal'),'atom_auxiliary_weight':ATOM_WEIGHTS[arm],
        'atom_auxiliary':'half_mean_inter_clause_end_BCE_plus_half_mean_interior_atom_BCE',
        'teacher_kl_weight':TEACHER_WEIGHTS[arm]}


def trainable_names(arm):
    arm_config(arm)
    return ADAPTER_PARAMETERS


def model(torch):
    """Use the exact already pinned residual graph, without new inference code."""
    return heading.model(torch)


def configure_trainable(network, arm):
    names = trainable_names(arm)
    for name,parameter in network.named_parameters():parameter.requires_grad_(name in names)
    parameters = [p for p in network.parameters() if p.requires_grad]
    require({n for n,p in network.named_parameters() if p.requires_grad} == names
        and sum(p.numel() for p in parameters) == 1057, 'complete1057 residual trainable inventory required')
    network.arm = arm;network.eval()
    return parameters


frozen_state = heading.frozen_state


def assert_frozen_state(parent_state, candidate_state):
    return heading.assert_frozen_state(frozen_state(parent_state),candidate_state)


def _restore_warm(torch, value):
    with torch.random.fork_rng(devices=[]): _,network = heading.restore(value)
    require(value['arm'] == 'rehearsal' and value['additional_optimizer_steps'] == 400
        and value['optimizer_steps'] == 1200 and value['parent_checkpoint']['optimizer_steps'] == 800,
        'exact rehearsal400 warm checkpoint over original800 parent required')
    return network


def build_checkpoint(parent_payload, *, arm, seed=SEED, training_manifest_sha256,
                     tuning_manifest_sha256, parent_file_sha256):
    import torch
    torch.set_num_threads(1)
    require(type(seed) is int and seed == SEED, 'fixed atom continuation seed1730 required')
    config = arm_config(arm)
    network = _restore_warm(torch,parent_payload)
    configure_trainable(network,arm)
    for name,value in (('training',training_manifest_sha256),('tuning',tuning_manifest_sha256),('warm file',parent_file_sha256)):
        heading._hash(value,name)
    state = heading._state(network);original = parent_payload['parent_checkpoint']
    require(state == parent_payload['model_state'], 'complete warm numerical state must be inherited exactly')
    return {'schema':SCHEMA,'profile':boundary.PROFILE,'implementation_sha256':implementation_sha(),
        'heading_implementation_sha256':heading.implementation_sha(),'boundary_implementation_sha256':boundary.implementation_sha(),
        'parent_checkpoint':deepcopy(parent_payload),'parent_checkpoint_sha256':digest(parent_payload),
        'parent_file_sha256':parent_file_sha256,'original_parent_checkpoint_sha256':digest(original),
        'original_parent_file_sha256':parent_payload['parent_file_sha256'],
        'arm':arm,'seed':seed,'adapter_config':deepcopy(ADAPTER_CONFIG),'training_config':config,
        'teacher_config':deepcopy(TEACHER_CONFIG),'model_state':state,'initial_model_state_sha256':digest(state),
        'frozen_parent_state_sha256':assert_frozen_state(original['model_state'],state),
        'trainable_parameters':sorted(trainable_names(arm)),'trainable_parameter_count':1057,
        'additional_optimizer_steps':0,'optimizer_steps':1200,'training_manifest_sha256':training_manifest_sha256,
        'tuning_manifest_sha256':tuning_manifest_sha256,'optimizer_resumption_supported':False,
        'source_text_only_numeric_input':True,'scope_logits_and_decoding_policy_unchanged':True,
        'warm_parent_is_unqualified_research_candidate':True,**boundary.FALSE}


def restore(value):
    import torch
    torch.set_num_threads(1)
    keys = {'schema','profile','implementation_sha256','heading_implementation_sha256','boundary_implementation_sha256',
        'parent_checkpoint','parent_checkpoint_sha256','parent_file_sha256','original_parent_checkpoint_sha256',
        'original_parent_file_sha256','arm','seed','adapter_config','training_config','teacher_config','model_state',
        'initial_model_state_sha256','frozen_parent_state_sha256','trainable_parameters','trainable_parameter_count',
        'additional_optimizer_steps','optimizer_steps','training_manifest_sha256','tuning_manifest_sha256',
        'optimizer_resumption_supported','source_text_only_numeric_input','scope_logits_and_decoding_policy_unchanged',
        'warm_parent_is_unqualified_research_candidate',*boundary.FALSE}
    require(type(value) is dict and set(value) == keys, 'closed atom boundary checkpoint required')
    require(value['schema'] == SCHEMA and value['profile'] == boundary.PROFILE
        and value['implementation_sha256'] == implementation_sha()
        and value['heading_implementation_sha256'] == heading.implementation_sha()
        and value['boundary_implementation_sha256'] == boundary.implementation_sha(), 'atom boundary producer or profile differs')
    arm=value['arm'];names=trainable_names(arm)
    require(value['adapter_config'] == ADAPTER_CONFIG and value['training_config'] == arm_config(arm)
        and value['teacher_config'] == TEACHER_CONFIG and value['optimizer_resumption_supported'] is False
        and value['source_text_only_numeric_input'] is True and value['scope_logits_and_decoding_policy_unchanged'] is True
        and value['warm_parent_is_unqualified_research_candidate'] is True
        and all(value[k] is False for k in boundary.FALSE), 'atom boundary inference, initialization or loss contract differs')
    require(type(value['seed']) is int and value['seed'] == SEED
        and value['trainable_parameters'] == sorted(names) and value['trainable_parameter_count'] == 1057,
        'fixed seed and residual trainable inventory required')
    for name in ('parent_checkpoint_sha256','parent_file_sha256','original_parent_checkpoint_sha256','original_parent_file_sha256',
        'initial_model_state_sha256','frozen_parent_state_sha256','training_manifest_sha256','tuning_manifest_sha256'):
        heading._hash(value[name],name)
    warm = value['parent_checkpoint'];network = _restore_warm(torch,warm);original = warm['parent_checkpoint']
    require(digest(warm) == value['parent_checkpoint_sha256'] and digest(original) == value['original_parent_checkpoint_sha256']
        and warm['parent_file_sha256'] == value['original_parent_file_sha256'], 'warm or original teacher lineage differs')
    require(value['initial_model_state_sha256'] == digest(warm['model_state']), 'warm initial complete state commitment differs')
    steps=value['additional_optimizer_steps']
    require(type(steps) is int and 0 <= steps <= 400 and type(value['optimizer_steps']) is int
        and value['optimizer_steps'] == 1200+steps, 'bounded additional and cumulative optimizer counters required')
    expected=network.state_dict()
    require(type(value['model_state']) is dict and set(value['model_state']) == set(expected), 'complete atom boundary state required')
    tensors={}
    for name,exemplar in expected.items():
        tensor=torch.tensor(value['model_state'][name],dtype=exemplar.dtype)
        require(tensor.shape == exemplar.shape and bool(torch.isfinite(tensor).all()), 'finite exact atom boundary tensor shape required')
        tensors[name]=tensor
    require(assert_frozen_state(original['model_state'],value['model_state']) == value['frozen_parent_state_sha256'],
        'original frozen encoder or head commitment differs')
    if steps == 0:require(value['model_state'] == warm['model_state'], 'zero-step complete state must equal warm predecessor')
    network.load_state_dict(tensors,strict=True);configure_trainable(network,arm)
    return torch,network


def checkpoint(network, *, initial_checkpoint, additional_steps):
    restore(initial_checkpoint)
    require(initial_checkpoint['additional_optimizer_steps'] == 0, 'immutable warm zero-step checkpoint required')
    require(getattr(network,'arm',None) == initial_checkpoint['arm']
        and {n for n,p in network.named_parameters() if p.requires_grad} == ADAPTER_PARAMETERS,
        'atom network arm or trainability changed')
    result=deepcopy(initial_checkpoint)
    result.update(model_state=heading._state(network),additional_optimizer_steps=additional_steps,optimizer_steps=1200+additional_steps)
    restore(result)
    return result


token_role_masks = heading.token_role_masks


def validate_atom_roles(row, record):
    """Reconstruct atom spans from exact copied fields within each occurrence."""
    keys={'candidate_id','source_sha256','inter_clause_end_token_indices',
        'atom_interior_negative_token_indices','atom_spans','provenance'}
    require(row.get('supported') is True and type(record) is dict and set(record) == keys,
        'closed atom role record for a supported TRAIN occurrence required')
    require(record['candidate_id'] == row['candidate_id']
        and record['source_sha256'] == row['source_sha256'] == boundary.text_sha(row['source_text'])
        and record['provenance'] == ATOM_PROVENANCE, 'atom roles must bind exact TRAIN source and provenance')
    source=row['source_text'];tokens=boundary.tokenize(source);clauses=row['clauses']
    require(type(clauses) is list and bool(clauses), 'supported source occurrences required')
    previous=0;ends=[];expected_spans=[]
    for clause in clauses:
        start,end=clause['char_start'],clause['char_end']
        require(type(start) is type(end) is int and previous <= start < end <= len(source),
            'bounded ordered source occurrence intervals required')
        previous=end;ends.append(end);rule=clause['rule']
        require(type(rule) is dict and type(rule.get('actor')) is str and bool(rule['actor']), 'exact copied actor string required')
        values=[('actor',rule['actor'])]
        for kind in ('temporal','exceptions'):
            atoms=rule.get(kind)
            require(type(atoms) is list and len(atoms) <= 1 and all(type(atom) is str and bool(atom) for atom in atoms),
                'zero or one exact copied '+kind+' atom required')
            values.extend((kind,atom) for atom in atoms)
        local=source[start:end]
        for kind,atom in values:
            matches=list(re.finditer(re.escape(atom),local))
            require(len(matches) == 1, 'each authored atom must have one exact match within its own clause occurrence')
            match=matches[0]
            expected_spans.append({'kind':kind,'char_start':start+match.start(),'char_end':start+match.end()})
    require(ends == sorted(set(ends)) and set(ends) <= {t['char_end'] for t in tokens}
        and ends[-1] == tokens[-1]['char_end'], 'complete exact ordered source-token endpoints required')
    expected_spans.sort(key=lambda s:(s['char_start'],s['char_end'],s['kind']))
    require(all(a['char_end'] <= b['char_start'] for a,b in zip(expected_spans,expected_spans[1:])),
        'distinct authored atom intervals must not overlap')
    actual_spans=record['atom_spans']
    require(type(actual_spans) is list and all(type(span) is dict and set(span) == {'kind','char_start','char_end'}
        and type(span['char_start']) is type(span['char_end']) is int for span in actual_spans)
        and actual_spans == expected_spans, 'atom intervals must equal exact source-copied canonical field occurrences')
    gold={index for index,token in enumerate(tokens) if token['char_end'] in ends}
    positive=sorted(index for index in gold if tokens[index]['char_end'] != ends[-1])
    negative=[index for index,token in enumerate(tokens) if index not in gold
        and any(span['char_start'] <= token['char_start'] < token['char_end'] <= span['char_end'] for span in expected_spans)]
    for key,expected in (('inter_clause_end_token_indices',positive),('atom_interior_negative_token_indices',negative)):
        actual=record[key]
        require(type(actual) is list and all(type(index) is int for index in actual) and actual == expected,
            'complete exact '+key+' required')
    return deepcopy(record)


def atom_role_masks(torch, rows, annotations):
    require(type(rows) is list and bool(rows), 'nonempty authored TRAIN batch required')
    if type(annotations) is list:
        require(all(type(record) is dict and type(record.get('candidate_id')) is str for record in annotations),
            'source-indexed atom annotations required')
        lookup={record['candidate_id']:record for record in annotations}
        require(len(lookup) == len(annotations), 'unique atom annotation identities required')
    else:
        require(type(annotations) is dict and all(type(key) is str and type(record) is dict
            and record.get('candidate_id') == key for key,record in annotations.items()), 'exact atom annotation lookup required')
        lookup=annotations
    width=max(len(boundary.tokenize(row['source_text'])) for row in rows)
    positive=torch.zeros((len(rows),width),dtype=torch.bool);negative=torch.zeros_like(positive)
    for index,row in enumerate(rows):
        require(type(row.get('supported')) is bool, 'authored boolean support label required')
        if not row['supported']:
            require(row['candidate_id'] not in lookup, 'unsupported documents cannot carry flat atom supervision')
            continue
        require(row['candidate_id'] in lookup, 'every supported TRAIN source requires atom annotation')
        record=validate_atom_roles(row,lookup[row['candidate_id']])
        positive[index,record['inter_clause_end_token_indices']]=True
        negative[index,record['atom_interior_negative_token_indices']]=True
    return positive,negative


def teacher_token_kl(torch, logits, labels, valid_mask, supported, *, teacher_logits):
    """Bernoulli KL on correct original-parent tokens, balanced by gold class."""
    require(logits.ndim == 2 and teacher_logits.shape == labels.shape == valid_mask.shape == logits.shape
        and supported.ndim == 1 and len(supported) == len(logits) and len(supported) > 0,
        'complete teacher token and document shapes required')
    require(logits.is_floating_point() and teacher_logits.is_floating_point()
        and logits.dtype == teacher_logits.dtype and logits.device == teacher_logits.device
        and bool(torch.isfinite(logits).all()) and bool(torch.isfinite(teacher_logits).all())
        and bool(torch.isfinite(labels).all()) and bool(((labels == 0) | (labels == 1)).all()),
        'same finite teacher/candidate logit dtype and binary labels required')
    require(valid_mask.dtype == torch.bool and supported.dtype in (torch.bool,torch.long)
        and bool(((supported == 0) | (supported == 1)).all()), 'boolean validity and binary support labels required')
    teacher=teacher_logits.detach()
    eligible=valid_mask & supported.bool()[:,None]
    correct=eligible & ((teacher >= 0.) == labels.bool())
    positive=correct & labels.bool();negative=correct & ~labels.bool()
    # Log-sigmoid stays finite for saturated probabilities and avoids log(0).
    t_end=torch.nn.functional.logsigmoid(teacher);t_not=torch.nn.functional.logsigmoid(-teacher)
    s_end=torch.nn.functional.logsigmoid(logits);s_not=torch.nn.functional.logsigmoid(-logits)
    token_kl=t_end.exp()*(t_end-s_end)+t_not.exp()*(t_not-s_not)
    counts=[int(positive.sum()),int(negative.sum())]
    sums=[token_kl[positive].sum(),token_kl[negative].sum()]
    means=[value/count if count else logits.sum()*0. for value,count in zip(sums,counts,strict=True)]
    available=sum(count > 0 for count in counts)
    kl=sum(means)/available if available else logits.sum()*0.
    require(bool(torch.isfinite(kl)), 'finite balanced teacher KL required')
    f=lambda value:float(value.detach())
    return kl,{'teacher_correct_count':sum(counts),'teacher_correct_positive_count':counts[0],
        'teacher_correct_negative_count':counts[1],'teacher_available_class_count':available,
        'teacher_positive_kl_sum':f(sums[0]),'teacher_negative_kl_sum':f(sums[1]),
        'teacher_positive_kl_mean':f(means[0]),'teacher_negative_kl_mean':f(means[1]),
        'teacher_kl':f(kl),'teacher_correct_mask':correct.tolist(),
        'teacher_positive_mask':positive.tolist(),'teacher_negative_mask':negative.tolist(),
        'teacher_token_logits':teacher.tolist(),'teacher_token_logits_sha256':digest(teacher.tolist()),
        'teacher_logits_detached':True,'teacher_kl_temperature':1.,'teacher_kl_positive_weighted':False,
        'teacher_class_average':'available_gold_classes','teacher_empty_mask':available == 0}


def objective_loss(torch, logits, labels, valid_mask, supported, positive_mask, negative_mask,
                   transition_mask, atom_mask, *, teacher_logits, arm):
    """Unchanged heading loss, optional atom rehearsal and optional teacher KL.

    All arms compute every component from the same tensors; only coefficients
    differ. The teacher must be evaluated by the caller from the original frozen
    checkpoint, under no_grad. This helper additionally detaches its logits.
    """
    config=arm_config(arm)
    common,parts=heading.objective_loss(torch,logits,labels,valid_mask,supported,positive_mask,negative_mask,arm='rehearsal')
    require(transition_mask.shape == atom_mask.shape == logits.shape
        and transition_mask.dtype == atom_mask.dtype == torch.bool, 'complete boolean atom role masks required')
    lengths=valid_mask.sum(dim=1)
    index=torch.arange(logits.shape[1],device=logits.device)[None,:]
    require(torch.equal(valid_mask,index < lengths[:,None]), 'contiguous complete source-token validity required')
    terminal=index == lengths[:,None]-1
    require(torch.equal(transition_mask,positive_mask & ~terminal), 'atom positives must be all inter-clause ends except final terminal')
    eligible=valid_mask & supported.bool()[:,None]
    require(not bool((atom_mask & (~eligible | labels.bool())).any()), 'interior atom negatives must be supported valid non-end tokens')
    require(bool(transition_mask.any()) and bool(atom_mask.any()), 'both transition and interior-atom classes required in every matched batch')
    positive_loss=torch.nn.functional.softplus(-logits[transition_mask])
    negative_loss=torch.nn.functional.softplus(logits[atom_mask])
    auxiliary=.5*(positive_loss.mean()+negative_loss.mean())
    weighted_atom=config['atom_auxiliary_weight']*auxiliary
    kl,teacher_parts=teacher_token_kl(torch,logits,labels,valid_mask,supported,teacher_logits=teacher_logits)
    weighted_teacher=config['teacher_kl_weight']*kl
    total=common+weighted_atom+weighted_teacher
    require(bool(torch.isfinite(total)), 'finite atom-boundary objective required')
    f=lambda value:float(value.detach())
    parts.update(heading_objective=f(common),atom_positive_count=int(transition_mask.sum()),atom_negative_count=int(atom_mask.sum()),
        atom_positive_bce_sum=f(positive_loss.sum()),atom_negative_bce_sum=f(negative_loss.sum()),
        atom_positive_bce_mean=f(positive_loss.mean()),atom_negative_bce_mean=f(negative_loss.mean()),
        balanced_atom_bce=f(auxiliary),atom_auxiliary_weight=config['atom_auxiliary_weight'],weighted_atom_bce=f(weighted_atom),
        transition_mask_sha256=digest(transition_mask.tolist()),atom_mask_sha256=digest(atom_mask.tolist()),
        **teacher_parts,teacher_kl_weight=config['teacher_kl_weight'],weighted_teacher_kl=f(weighted_teacher),total_loss=f(total))
    return total,parts


class AtomBoundaryDecoder(boundary.ClauseBoundaryDecoder):
    def __init__(self,value):
        self.torch,self.network=restore(value)
        self.checkpoint=deepcopy(value);self.checkpoint_sha256=digest(value)


def decoder(value):
    """Dispatch original, warm and new checkpoints through the same policy."""
    if value.get('schema') in (boundary.SCHEMA,heading.SCHEMA):return heading.decoder(value)
    return AtomBoundaryDecoder(value)

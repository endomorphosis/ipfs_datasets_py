"""Residual token-boundary learning with an immutable parent scope decision.

The complete parent encoder and its two heads remain frozen. A small residual
MLP changes token-end scores only; its zero output initialization reproduces the
parent exactly. Editorial annotations are authored TRAIN supervision and never
enter inference. Neither segmentation nor compilation proves legal fidelity.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re

from . import legal_clause_boundary_decoder as boundary

SCHEMA = 'legal-clause-heading-boundary-checkpoint/v1'
ARMS = ('control', 'rehearsal')
SEED = 1730
ADAPTER_CONFIG = {'token_state_size':64, 'hidden_size':16, 'activation':'tanh',
    'zero_initial_output':True, 'padding_residual_zero':True}
TRAINING_CONFIG = {'learning_rate':.004, 'positive_weight':12., 'gradient_clip_norm':5.,
    'optimizer':'fresh_Adam', 'optimizer_resumption_supported':False,
    'supervision':'supported_document_valid_tokens_only',
    'auxiliary':'half_mean_true_end_BCE_plus_half_mean_editorial_punctuation_BCE',
    'both_auxiliary_classes_required':True}
AUXILIARY_WEIGHTS = {'control':0., 'rehearsal':.5}
ADAPTER_PARAMETERS = frozenset(('boundary_hidden.weight','boundary_hidden.bias',
    'boundary_residual.weight','boundary_residual.bias'))
TRAINABLE_COUNTS = {'control':1057, 'rehearsal':1057}
ROLE_PROVENANCE = 'pinned_train_endpoints_and_optional_editorial_spans/v1'
require, digest = boundary.require, boundary.digest


def implementation_sha():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def arm_config(arm):
    require(type(arm) is str and arm in ARMS, 'known heading boundary arm required')
    return {**deepcopy(TRAINING_CONFIG), 'auxiliary_weight':AUXILIARY_WEIGHTS[arm]}


def trainable_names(arm):
    arm_config(arm)
    return ADAPTER_PARAMETERS


def model(torch):
    class HeadingBoundaryModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            parent = boundary.model(torch)
            self.embedding, self.encoder = parent.embedding, parent.encoder
            self.boundary, self.scope = parent.boundary, parent.scope
            self.boundary_hidden = torch.nn.Linear(64,16)
            self.boundary_residual = torch.nn.Linear(16,1)
            torch.nn.init.zeros_(self.boundary_residual.weight)
            torch.nn.init.zeros_(self.boundary_residual.bias)

        def train(self, mode=True):
            super().train(mode)
            self.embedding.eval(); self.encoder.eval(); self.boundary.eval(); self.scope.eval()
            return self

        def encode_frozen(self, ids, features, lengths):
            # Operation order and packed recurrent computation match the parent.
            with torch.no_grad():
                raw = torch.cat((self.embedding(ids),features),dim=-1)
                packed = torch.nn.utils.rnn.pack_padded_sequence(raw,lengths.cpu(),batch_first=True,enforce_sorted=False)
                values, hidden = self.encoder(packed)
                values, _ = torch.nn.utils.rnn.pad_packed_sequence(values,batch_first=True,total_length=ids.shape[1])
                final = torch.cat((hidden[-2],hidden[-1]),dim=-1)
            return values, final

        def forward(self, ids, features, lengths):
            values, final = self.encode_frozen(ids,features,lengths)
            with torch.no_grad():
                original = self.boundary(values).squeeze(-1)
                scope = self.scope(final)
            residual = self.boundary_residual(torch.tanh(self.boundary_hidden(values))).squeeze(-1)
            valid = torch.arange(ids.shape[1],device=ids.device)[None,:] < lengths.to(ids.device)[:,None]
            return original + residual.masked_fill(~valid,0.), scope
    return HeadingBoundaryModel()


def configure_trainable(network, arm):
    names = trainable_names(arm)
    for name, parameter in network.named_parameters(): parameter.requires_grad_(name in names)
    require({n for n,p in network.named_parameters() if p.requires_grad} == names,
        'complete residual boundary trainable inventory required')
    parameters = [p for p in network.parameters() if p.requires_grad]
    require(sum(p.numel() for p in parameters) == TRAINABLE_COUNTS[arm], 'residual boundary parameter count differs')
    network.arm = arm
    network.eval()
    return parameters


def frozen_state(state):
    return {name:value for name,value in state.items() if name not in ADAPTER_PARAMETERS}


def assert_frozen_state(parent_state, candidate_state):
    require(set(candidate_state) == set(parent_state) | ADAPTER_PARAMETERS, 'parent and boundary adapter tensor inventory differs')
    require(parent_state == frozen_state(candidate_state), 'frozen parent encoder, boundary or scope state changed')
    return digest(parent_state)


def _state(network):
    return {name:value.detach().cpu().tolist() for name,value in network.state_dict().items()}


def _initial(torch, parent, seed):
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        network = model(torch)
    loaded = network.state_dict()
    for name,value in parent['model_state'].items(): loaded[name] = torch.tensor(value,dtype=loaded[name].dtype)
    network.load_state_dict(loaded,strict=True)
    return network


def _hash(value, name):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None, name+' digest required')


def build_checkpoint(parent_payload, *, arm, seed=SEED, training_manifest_sha256,
                     tuning_manifest_sha256, parent_file_sha256):
    import torch
    torch.set_num_threads(1)
    with torch.random.fork_rng(devices=[]): boundary.restore(parent_payload)
    require(type(seed) is int and seed == SEED, 'fixed adapter initialization and sampler seed1730 required')
    config = arm_config(arm)
    for name,value in (('training',training_manifest_sha256),('tuning',tuning_manifest_sha256),('parent file',parent_file_sha256)):
        _hash(value,name)
    network = _initial(torch,parent_payload,seed)
    configure_trainable(network,arm)
    state = _state(network)
    return {'schema':SCHEMA,'profile':boundary.PROFILE,'implementation_sha256':implementation_sha(),
        'boundary_implementation_sha256':boundary.implementation_sha(),'parent_checkpoint':deepcopy(parent_payload),
        'parent_checkpoint_sha256':digest(parent_payload),'parent_file_sha256':parent_file_sha256,
        'arm':arm,'seed':seed,'adapter_config':deepcopy(ADAPTER_CONFIG),'training_config':config,'model_state':state,
        'initial_model_state_sha256':digest(state),'frozen_parent_state_sha256':assert_frozen_state(parent_payload['model_state'],state),
        'trainable_parameters':sorted(trainable_names(arm)),'trainable_parameter_count':TRAINABLE_COUNTS[arm],
        'additional_optimizer_steps':0,'optimizer_steps':parent_payload['optimizer_steps'],
        'training_manifest_sha256':training_manifest_sha256,'tuning_manifest_sha256':tuning_manifest_sha256,
        'optimizer_resumption_supported':False,'source_text_only_numeric_input':True,
        'scope_logits_and_decoding_policy_unchanged':True,**boundary.FALSE}


def restore(value):
    import torch
    torch.set_num_threads(1)
    keys = {'schema','profile','implementation_sha256','boundary_implementation_sha256','parent_checkpoint',
        'parent_checkpoint_sha256','parent_file_sha256','arm','seed','adapter_config','training_config','model_state',
        'initial_model_state_sha256','frozen_parent_state_sha256','trainable_parameters','trainable_parameter_count',
        'additional_optimizer_steps','optimizer_steps','training_manifest_sha256','tuning_manifest_sha256',
        'optimizer_resumption_supported','source_text_only_numeric_input','scope_logits_and_decoding_policy_unchanged',*boundary.FALSE}
    require(type(value) is dict and set(value) == keys, 'closed heading boundary checkpoint required')
    require(value['schema'] == SCHEMA and value['profile'] == boundary.PROFILE
        and value['implementation_sha256'] == implementation_sha()
        and value['boundary_implementation_sha256'] == boundary.implementation_sha(), 'heading boundary producer or profile differs')
    arm = value['arm']; names = trainable_names(arm)
    require(value['adapter_config'] == ADAPTER_CONFIG and value['training_config'] == arm_config(arm)
        and value['optimizer_resumption_supported'] is False and value['source_text_only_numeric_input'] is True
        and value['scope_logits_and_decoding_policy_unchanged'] is True
        and all(value[k] is False for k in boundary.FALSE), 'heading boundary inference or fitting contract differs')
    require(type(value['seed']) is int and value['seed'] == SEED, 'fixed heading boundary seed required')
    require(value['trainable_parameters'] == sorted(names) and value['trainable_parameter_count'] == TRAINABLE_COUNTS[arm],
        'declared heading trainable inventory differs')
    for name in ('parent_checkpoint_sha256','parent_file_sha256','initial_model_state_sha256',
                 'frozen_parent_state_sha256','training_manifest_sha256','tuning_manifest_sha256'): _hash(value[name],name)
    parent = value['parent_checkpoint']
    with torch.random.fork_rng(devices=[]): boundary.restore(parent)
    require(digest(parent) == value['parent_checkpoint_sha256'], 'immutable parent checkpoint digest differs')
    steps = value['additional_optimizer_steps']
    require(type(steps) is int and 0 <= steps <= 400 and type(value['optimizer_steps']) is int
        and value['optimizer_steps'] == parent['optimizer_steps']+steps, 'bounded cumulative and additional optimizer steps required')
    network = _initial(torch,parent,value['seed']); initial = _state(network)
    require(digest(initial) == value['initial_model_state_sha256'], 'complete initial boundary adapter state differs')
    expected = network.state_dict()
    require(type(value['model_state']) is dict and set(value['model_state']) == set(expected), 'complete boundary adapter tensor inventory required')
    tensors = {}
    for name,exemplar in expected.items():
        tensor = torch.tensor(value['model_state'][name],dtype=exemplar.dtype)
        require(tensor.shape == exemplar.shape and bool(torch.isfinite(tensor).all()), 'finite exact boundary adapter tensor shape required')
        tensors[name] = tensor
    require(assert_frozen_state(parent['model_state'],value['model_state']) == value['frozen_parent_state_sha256'],
        'frozen parent state commitment differs')
    if steps == 0: require(value['model_state'] == initial, 'zero-step model must equal exact parent plus initial boundary adapter')
    network.load_state_dict(tensors,strict=True)
    configure_trainable(network,arm)
    return torch,network


def checkpoint(network, *, initial_checkpoint, additional_steps):
    restore(initial_checkpoint)
    require(initial_checkpoint['additional_optimizer_steps'] == 0, 'immutable zero-step checkpoint required')
    require(getattr(network,'arm',None) == initial_checkpoint['arm'], 'network training arm differs')
    result = deepcopy(initial_checkpoint)
    result.update(model_state=_state(network),additional_optimizer_steps=additional_steps,
        optimizer_steps=initial_checkpoint['parent_checkpoint']['optimizer_steps']+additional_steps)
    restore(result)
    return result


def validate_token_roles(row, record):
    """Bind authored token roles to this exact supported source occurrence."""
    keys = {'candidate_id','source_sha256','true_end_token_indices',
        'editorial_hard_negative_token_indices','editorial_heading_spans','provenance'}
    require(row.get('supported') is True and type(record) is dict and set(record) == keys,
        'closed token role record for a supported TRAIN document required')
    require(record['candidate_id'] == row['candidate_id']
        and record['source_sha256'] == row['source_sha256'] == boundary.text_sha(row['source_text'])
        and record['provenance'] == ROLE_PROVENANCE, 'token roles must bind exact TRAIN source and provenance')
    tokens = boundary.tokenize(row['source_text'])
    require(type(row['clauses']) is list and bool(row['clauses']), 'supported occurrence endpoints required')
    ends = [clause['char_end'] for clause in row['clauses']]
    require(all(type(end) is int for end in ends) and ends == sorted(set(ends))
        and set(ends) <= {token['char_end'] for token in tokens}, 'ordered exact source token endpoints required')
    expected_positive = [index for index,token in enumerate(tokens) if token['char_end'] in ends]
    spans = record['editorial_heading_spans']
    require(type(spans) is list, 'authored editorial span list required')
    previous_end = 0
    for span in spans:
        require(type(span) is dict and set(span) == {'char_start','char_end'}
            and type(span['char_start']) is int and type(span['char_end']) is int
            and 0 <= previous_end <= span['char_start'] < span['char_end'] <= len(row['source_text']),
            'bounded ordered nonoverlapping editorial spans required')
        previous_end = span['char_end']
    expected_negative = [index for index,token in enumerate(tokens)
        if index not in expected_positive and re.fullmatch(r'[^\w\s]',token['text']) is not None
        and any(span['char_start'] <= token['char_start'] < token['char_end'] <= span['char_end'] for span in spans)]
    for field,expected in (('true_end_token_indices',expected_positive),('editorial_hard_negative_token_indices',expected_negative)):
        actual = record[field]
        require(type(actual) is list and all(type(index) is int for index in actual)
            and actual == expected, 'complete exact authored '+field+' required')
    return deepcopy(record)


def token_role_masks(torch, rows, annotations):
    """Return validated positive/negative masks; never invent unsupported ends."""
    require(type(rows) is list and bool(rows), 'nonempty authored TRAIN batch required')
    if type(annotations) is list:
        require(all(type(record) is dict and type(record.get('candidate_id')) is str for record in annotations),
            'source-indexed token annotation records required')
        lookup = {record['candidate_id']:record for record in annotations}
        require(len(lookup) == len(annotations), 'unique token annotation identities required')
    else:
        require(type(annotations) is dict and all(type(key) is str and type(record) is dict
            and record.get('candidate_id') == key for key,record in annotations.items()), 'exact token annotation lookup required')
        lookup = annotations
    width = max(len(boundary.tokenize(row['source_text'])) for row in rows)
    positive = torch.zeros((len(rows),width),dtype=torch.bool)
    negative = torch.zeros_like(positive)
    for index,row in enumerate(rows):
        require(type(row.get('supported')) is bool, 'authored boolean support label required')
        if not row['supported']:
            require(row['candidate_id'] not in lookup, 'unsupported documents cannot carry flat token supervision')
            continue
        require(row['candidate_id'] in lookup, 'every supported document requires a pinned token role record')
        record = validate_token_roles(row,lookup[row['candidate_id']])
        positive[index,record['true_end_token_indices']] = True
        negative[index,record['editorial_hard_negative_token_indices']] = True
    return positive,negative


def objective_loss(torch, logits, labels, valid_mask, supported, positive_mask, negative_mask, *, arm):
    """Supported-token BCE plus a separately balanced, authored-role auxiliary."""
    config = arm_config(arm)
    require(logits.ndim == 2 and labels.shape == logits.shape and valid_mask.shape == logits.shape
        and positive_mask.shape == logits.shape and negative_mask.shape == logits.shape
        and supported.ndim == 1 and len(supported) == len(logits) and len(supported) > 0,
        'complete token and document loss shapes required')
    require(logits.is_floating_point() and labels.is_floating_point() and bool(torch.isfinite(logits).all())
        and bool(torch.isfinite(labels).all()) and bool(((labels == 0) | (labels == 1)).all()), 'finite binary token labels required')
    require(valid_mask.dtype == positive_mask.dtype == negative_mask.dtype == torch.bool
        and supported.dtype in (torch.bool,torch.long) and bool(((supported == 0) | (supported == 1)).all()),
        'boolean token masks and binary scope labels required')
    eligible = valid_mask & supported.bool()[:,None]
    require(bool(eligible.any()), 'supported valid token supervision required')
    require(torch.equal(positive_mask,eligible & labels.bool()), 'auxiliary positives must be every supported true end')
    require(not bool((negative_mask & (~eligible | labels.bool())).any()), 'editorial negatives must be supported valid non-end tokens')
    require(bool(positive_mask.any()) and bool(negative_mask.any()), 'both auxiliary classes required in every matched batch')
    base = torch.nn.functional.binary_cross_entropy_with_logits(logits[eligible],labels[eligible].to(dtype=logits.dtype),
        pos_weight=logits.new_tensor(config['positive_weight']))
    positive_losses = torch.nn.functional.softplus(-logits[positive_mask])
    negative_losses = torch.nn.functional.softplus(logits[negative_mask])
    auxiliary = .5 * (positive_losses.mean()+negative_losses.mean())
    weighted = config['auxiliary_weight'] * auxiliary
    loss = base + weighted
    require(bool(torch.isfinite(loss)), 'finite boundary objective required')
    ordinary_negative = eligible & ~labels.bool()
    base_negative_sum = torch.nn.functional.softplus(logits[ordinary_negative]).sum()
    positive_sum, negative_sum = positive_losses.sum(), negative_losses.sum()
    f = lambda x:float(x.detach())
    return loss,{'supported_documents':int(supported.bool().sum()),'unsupported_documents':int((~supported.bool()).sum()),
        'eligible_token_count':int(eligible.sum()),'positive_token_count':int(positive_mask.sum()),
        'ordinary_negative_token_count':int(ordinary_negative.sum()),'positive_weight':config['positive_weight'],
        'base_positive_bce_sum':f(positive_sum),'base_negative_bce_sum':f(base_negative_sum),'base_bce':f(base),
        'auxiliary_positive_count':int(positive_mask.sum()),'auxiliary_negative_count':int(negative_mask.sum()),
        'auxiliary_positive_bce_sum':f(positive_sum),'auxiliary_negative_bce_sum':f(negative_sum),
        'auxiliary_positive_mean':f(positive_losses.mean()),'auxiliary_negative_mean':f(negative_losses.mean()),
        'balanced_auxiliary_bce':f(auxiliary),'auxiliary_weight':config['auxiliary_weight'],
        'weighted_auxiliary_bce':f(weighted),'total_loss':f(loss),
        'padding_token_count':int((~valid_mask).sum()),'excluded_unsupported_token_count':int((valid_mask & ~supported.bool()[:,None]).sum()),
        'eligible_mask_sha256':digest(eligible.tolist()),'positive_mask_sha256':digest(positive_mask.tolist()),
        'negative_mask_sha256':digest(negative_mask.tolist()),'unsupported_token_supervision':False}


class HeadingBoundaryDecoder(boundary.ClauseBoundaryDecoder):
    def __init__(self,value):
        self.torch,self.network = restore(value)
        self.checkpoint = deepcopy(value)
        self.checkpoint_sha256 = digest(value)


def decoder(value):
    """Keep the parent's source-only inference and explicit rejection policy."""
    return boundary.ClauseBoundaryDecoder(value) if value.get('schema') == boundary.SCHEMA else HeadingBoundaryDecoder(value)

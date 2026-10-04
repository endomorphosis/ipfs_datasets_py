"""Source-only scope readout over immutable learned boundary token states.

Both arms retain the exact parent final-state scope readout. The adapter adds a
zero-initialized residual from masked attention over frozen BiGRU token states.
Only scope parameters train; token boundaries and the declared decoding policy
remain unchanged. A scope prediction is not evidence of statutory independence.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import hashlib
import re

from . import legal_clause_boundary_decoder as boundary

SCHEMA = 'legal-clause-scope-adapter-checkpoint/v1'
ARMS = ('control', 'adapter')
SEED = 1730
ADAPTER_CONFIG = {'token_state_size': 64, 'attention_size': 16,
                  'padding_mask_before_softmax': True, 'zero_initial_residual': True}
TRAINING_CONFIG = {'learning_rate': .004, 'scope_class_weights': [3., 1.],
                   'gradient_clip_norm': 5., 'optimizer': 'fresh_Adam',
                   'optimizer_resumption_supported': False}
SCOPE_PARAMETERS = frozenset(('scope.weight', 'scope.bias'))
ADAPTER_PARAMETERS = frozenset(('attention_hidden.weight', 'attention_hidden.bias',
    'attention_score.weight', 'attention_score.bias', 'scope_residual.weight', 'scope_residual.bias'))
TRAINABLE_COUNTS = {'control': 130, 'adapter': 1317}
require, digest = boundary.require, boundary.digest


def implementation_sha():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def trainable_names(arm):
    require(arm in ARMS, 'known scope adapter arm required')
    return SCOPE_PARAMETERS | (ADAPTER_PARAMETERS if arm == 'adapter' else frozenset())


def model(torch):
    class ScopeAdapterModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            parent = boundary.model(torch)
            self.embedding, self.encoder = parent.embedding, parent.encoder
            self.boundary, self.scope = parent.boundary, parent.scope
            self.attention_hidden = torch.nn.Linear(64, 16)
            self.attention_score = torch.nn.Linear(16, 1)
            self.scope_residual = torch.nn.Linear(64, 2)
            torch.nn.init.zeros_(self.scope_residual.weight)
            torch.nn.init.zeros_(self.scope_residual.bias)

        def train(self, mode=True):
            super().train(mode)
            self.embedding.eval(); self.encoder.eval(); self.boundary.eval()
            return self

        def encode_frozen(self, ids, features, lengths):
            # Identical operations and packing to the immutable parent forward.
            with torch.no_grad():
                raw = torch.cat((self.embedding(ids), features), dim=-1)
                packed = torch.nn.utils.rnn.pack_padded_sequence(raw, lengths.cpu(), batch_first=True, enforce_sorted=False)
                values, hidden = self.encoder(packed)
                values, _ = torch.nn.utils.rnn.pad_packed_sequence(values, batch_first=True, total_length=ids.shape[1])
                final = torch.cat((hidden[-2], hidden[-1]), dim=-1)
            return values, final

        def attend(self, values, lengths):
            require(values.ndim == 3 and values.shape[-1] == 64 and lengths.ndim == 1
                and len(lengths) == len(values), 'bounded token-state attention shapes required')
            require(bool(((lengths > 0) & (lengths <= values.shape[1])).all()), 'nonempty valid attention lengths required')
            valid = torch.arange(values.shape[1], device=values.device)[None, :] < lengths.to(values.device)[:, None]
            logits = self.attention_score(torch.tanh(self.attention_hidden(values))).squeeze(-1)
            weights = torch.softmax(logits.masked_fill(~valid, float('-inf')), dim=-1)
            pooled = (weights.unsqueeze(-1) * values).sum(dim=1)
            return pooled, weights

        def forward(self, ids, features, lengths):
            values, final = self.encode_frozen(ids, features, lengths)
            token_logits = self.boundary(values).squeeze(-1)
            pooled, _ = self.attend(values, lengths)
            return token_logits, self.scope(final) + self.scope_residual(pooled)
    return ScopeAdapterModel()


def configure_trainable(network, arm):
    names = trainable_names(arm)
    for name, parameter in network.named_parameters(): parameter.requires_grad_(name in names)
    require({name for name, p in network.named_parameters() if p.requires_grad} == names,
            'complete scope trainable parameter inventory required')
    parameters = [p for p in network.parameters() if p.requires_grad]
    require(sum(p.numel() for p in parameters) == TRAINABLE_COUNTS[arm], 'scope trainable parameter count differs')
    network.arm = arm
    network.eval()
    return parameters


def frozen_state(state):
    return {name: value for name, value in state.items() if name not in SCOPE_PARAMETERS | ADAPTER_PARAMETERS}


def assert_frozen_state(parent_state, candidate_state):
    require(set(candidate_state) == set(parent_state) | ADAPTER_PARAMETERS, 'parent and adapter tensor inventory differs')
    require(frozen_state(parent_state) == frozen_state(candidate_state), 'frozen embedding/encoder/token-head state changed')
    return digest(frozen_state(candidate_state))


def _initial(torch, parent, seed):
    # Isolate initialization RNG from caller minibatch ordering and optimizer use.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        network = model(torch)
    loaded = network.state_dict()
    for name, value in parent['model_state'].items():
        loaded[name] = torch.tensor(value, dtype=loaded[name].dtype)
    network.load_state_dict(loaded, strict=True)
    return network


def _state(network):
    return {name: value.detach().cpu().tolist() for name, value in network.state_dict().items()}


def _hash(value, name):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None, name+' digest required')


def build_checkpoint(parent_payload, *, arm, seed=SEED, training_manifest_sha256,
                     tuning_manifest_sha256, parent_file_sha256):
    import torch
    torch.set_num_threads(1)
    with torch.random.fork_rng(devices=[]): boundary.restore(parent_payload)
    require(type(seed) is int and seed == SEED, 'fixed minibatch and adapter initialization seed1730 required')
    trainable_names(arm)
    for name, value in (('training', training_manifest_sha256), ('tuning', tuning_manifest_sha256),
                        ('raw parent file', parent_file_sha256)):_hash(value, name)
    network = _initial(torch, parent_payload, seed)
    configure_trainable(network, arm)
    state = _state(network)
    return {'schema': SCHEMA, 'profile': boundary.PROFILE, 'implementation_sha256': implementation_sha(),
        'boundary_implementation_sha256': boundary.implementation_sha(), 'parent_checkpoint': deepcopy(parent_payload),
        'parent_checkpoint_sha256': digest(parent_payload), 'parent_file_sha256': parent_file_sha256,
        'arm': arm, 'seed': seed, 'adapter_config': deepcopy(ADAPTER_CONFIG),
        'training_config': deepcopy(TRAINING_CONFIG), 'model_state': state,
        'initial_model_state_sha256': digest(state),
        'frozen_non_scope_state_sha256': assert_frozen_state(parent_payload['model_state'], state),
        'trainable_parameters': sorted(trainable_names(arm)), 'trainable_parameter_count': TRAINABLE_COUNTS[arm],
        'additional_optimizer_steps': 0, 'optimizer_steps': parent_payload['optimizer_steps'],
        'training_manifest_sha256': training_manifest_sha256, 'tuning_manifest_sha256': tuning_manifest_sha256,
        'optimizer_resumption_supported': False, 'source_text_only_numeric_input': True,
        'scope_threshold_and_surface_policy_unchanged': True, **boundary.FALSE}


def restore(value):
    import torch
    torch.set_num_threads(1)
    expected_keys = {'schema','profile','implementation_sha256','boundary_implementation_sha256','parent_checkpoint',
        'parent_checkpoint_sha256','parent_file_sha256','arm','seed','adapter_config','training_config','model_state',
        'initial_model_state_sha256','frozen_non_scope_state_sha256','trainable_parameters','trainable_parameter_count',
        'additional_optimizer_steps','optimizer_steps','training_manifest_sha256','tuning_manifest_sha256',
        'optimizer_resumption_supported','source_text_only_numeric_input','scope_threshold_and_surface_policy_unchanged',*boundary.FALSE}
    require(type(value) is dict and set(value) == expected_keys, 'closed scope adapter checkpoint required')
    require(value['schema'] == SCHEMA and value['profile'] == boundary.PROFILE
        and value['implementation_sha256'] == implementation_sha()
        and value['boundary_implementation_sha256'] == boundary.implementation_sha(), 'scope adapter producer or profile differs')
    require(value['adapter_config'] == ADAPTER_CONFIG and value['training_config'] == TRAINING_CONFIG
        and value['optimizer_resumption_supported'] is False and value['source_text_only_numeric_input'] is True
        and value['scope_threshold_and_surface_policy_unchanged'] is True
        and all(value[key] is False for key in boundary.FALSE), 'scope adapter inference or fitting contract differs')
    arm=value['arm'];names=trainable_names(arm)
    require(type(value['seed']) is int and value['seed'] == SEED, 'fixed scope adapter seed required')
    require(value['trainable_parameters'] == sorted(names) and value['trainable_parameter_count'] == TRAINABLE_COUNTS[arm],
            'declared trainable inventory differs')
    for name in ('parent_checkpoint_sha256','parent_file_sha256','initial_model_state_sha256',
                 'frozen_non_scope_state_sha256','training_manifest_sha256','tuning_manifest_sha256'):_hash(value[name], name)
    parent=value['parent_checkpoint']
    with torch.random.fork_rng(devices=[]): boundary.restore(parent)
    require(digest(parent) == value['parent_checkpoint_sha256'], 'immutable parent checkpoint digest differs')
    steps=value['additional_optimizer_steps']
    require(type(steps) is int and 0 <= steps <= 400 and type(value['optimizer_steps']) is int
        and value['optimizer_steps'] == parent['optimizer_steps'] + steps, 'bounded cumulative and additional optimizer steps required')
    network=_initial(torch,parent,value['seed']);initial=_state(network)
    require(digest(initial) == value['initial_model_state_sha256'], 'initial complete adapter state differs')
    exemplars=network.state_dict()
    require(type(value['model_state']) is dict and set(value['model_state']) == set(exemplars), 'complete scope adapter tensor inventory required')
    tensors={}
    for name,exemplar in exemplars.items():
        tensor=torch.tensor(value['model_state'][name],dtype=exemplar.dtype)
        require(tensor.shape == exemplar.shape and bool(torch.isfinite(tensor).all()), 'finite exact scope adapter tensor shape required')
        tensors[name]=tensor
    require(assert_frozen_state(parent['model_state'],value['model_state']) == value['frozen_non_scope_state_sha256'],
            'frozen state commitment differs')
    if arm == 'control':
        require(all(value['model_state'][name] == initial[name] for name in ADAPTER_PARAMETERS),
                'control adapter parameters must remain at initial zero-residual state')
    if steps == 0:require(value['model_state'] == initial, 'zero-step complete model must equal exact parent plus initial adapter')
    network.load_state_dict(tensors,strict=True)
    configure_trainable(network,arm)
    return torch,network


def checkpoint(network, *, initial_checkpoint, additional_steps):
    restore(initial_checkpoint)
    require(initial_checkpoint['additional_optimizer_steps'] == 0, 'immutable zero-step checkpoint required')
    require(getattr(network,'arm',None) == initial_checkpoint['arm'], 'network training arm differs')
    result=deepcopy(initial_checkpoint)
    result.update(model_state=_state(network),additional_optimizer_steps=additional_steps,
        optimizer_steps=initial_checkpoint['parent_checkpoint']['optimizer_steps']+additional_steps)
    restore(result)
    return result


def scope_loss(torch, logits, labels):
    require(logits.ndim == 2 and logits.shape[1] == 2 and labels.ndim == 1
        and len(labels) == len(logits) and len(labels) > 0, 'two-class nonempty scope logits required')
    require(labels.dtype == torch.long and bool(((labels == 0) | (labels == 1)).all()), 'binary integer scope labels required')
    weights=logits.new_tensor(TRAINING_CONFIG['scope_class_weights'])
    loss=torch.nn.functional.cross_entropy(logits,labels,weight=weights)
    require(bool(torch.isfinite(loss)), 'finite scope class-weighted loss required')
    nll=-torch.log_softmax(logits,dim=-1).gather(1,labels[:,None]).squeeze(1)
    counts=[int((labels==label).sum()) for label in (0,1)]
    sums=[float(nll[labels==label].sum().detach()) for label in (0,1)]
    return loss,{'unsupported_count':counts[0],'supported_count':counts[1],
        'unsupported_nll_sum':sums[0],'supported_nll_sum':sums[1],
        'weighted_denominator':3*counts[0]+counts[1],'cross_entropy':float(loss.detach())}


class ScopeAdapterDecoder(boundary.ClauseBoundaryDecoder):
    def __init__(self,value):
        self.torch,self.network=restore(value)
        self.checkpoint=deepcopy(value)
        self.checkpoint_sha256=digest(value)


def decoder(value):
    """Dispatch the retained old parent and new checkpoints without policy edits."""
    return boundary.ClauseBoundaryDecoder(value) if value.get('schema') == boundary.SCHEMA else ScopeAdapterDecoder(value)

"""Private two-bank auxiliary dispatch for the existing normative trainer.

Each renderer/exclusion profile prepares its own authentic 180-clause bank and
immutable tensor cache. Only sampling order is rebound, with prior receipts
retained. The original decoder/count streams, losses, optimizer and selector
remain owned by the inherited trainer. This owner acquires no resource lease,
encodes no source and grants no quality, semantic or proof admission.
"""
from collections import Counter
from copy import deepcopy
import functools
import math
import time
from types import ModuleType, SimpleNamespace

from scripts.ops.autoencoder.dual_bank_wording_replay import dual_bank_retention as retention

SCHEMA = 'dual-bank-wording-training-adapter/v1'
INVENTORY_SCHEMA = 'dual-bank-wording-source-inventory/v1'
BANK_SCHEMA = 'dual-bank-wording-prepared-banks/v1'
CACHE_SCHEMA = 'dual-bank-wording-tensor-caches/v1'
LOSS_SCHEMA = 'dual-bank-wording-modality-loss/v1'
FALSE = dict(qualified=False, admitted=False, proof_authority=False,
    source_semantics_verified=False, checkpoint_promoted=False, encoder_executed=False,
    native_vectors_revalidated=False, source_provenance_authenticated=False,
    execution_readiness_granted=False, normalization_fitted=False)
ROLES = retention.ROLES
_SLOTS = {'_model', '_data', '_vectors', '_mask', '_targets', '_orders', '_rows',
          '_fixed', '_versions', '_receipt', '_max_steps'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def wire(value):
    import json
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def detached(raw):
    import json
    return json.loads(raw)


def deadline_check(deadline):
    require(type(deadline) in (int, float) and math.isfinite(deadline), 'finite dual-bank deadline required')
    if time.monotonic() >= deadline:
        raise TimeoutError('dual-bank auxiliary deadline')


def build_source_inventory(inventories_by_role, pairing):
    require(type(inventories_by_role) is dict and set(inventories_by_role) == set(ROLES)
        and type(pairing) is dict and retention.hash64(pairing.get('pairing_sha256')),
        'two separate source envelopes and explicit pairing required')
    result = dict(schema=INVENTORY_SCHEMA, banks_by_role=deepcopy(inventories_by_role),
        pairing_sha256=pairing['pairing_sha256'], **FALSE)
    result['payload_sha256'] = retention.digest(result)
    return result


class _Banks:
    __slots__ = ('_owner_token', '_banks_bytes', '_schedule_bytes', '_inventory_bytes', '_codec_bytes', '_receipt_bytes')
    def __setattr__(self, name, value):
        raise AttributeError('prepared bank pair is immutable')
    @property
    def receipt(self):
        return detached(self._receipt_bytes)
    @property
    def schedule(self):
        return detached(self._schedule_bytes)
    @property
    def banks_by_role(self):
        return detached(self._banks_bytes)
    def items(self):
        # The inherited trainer exports metadata, never a fictitious 360-row bank.
        return self.receipt.items()


class _Caches:
    __slots__ = ('_owner_token', '_model', '_banks', '_caches', '_receipt_bytes', '_witnesses')
    def __setattr__(self, name, value):
        raise AttributeError('dual tensor cache is immutable')
    @property
    def receipt(self):
        return detached(self._receipt_bytes)
    @property
    def caches_by_role(self):
        return dict(self._caches)


def configure(*, helpers_by_role, pairing, original_rules, first_bank='control'):
    """Compose explicit private renderer profiles; do not mutate either helper."""
    require(type(helpers_by_role) is dict and set(helpers_by_role) == set(ROLES)
        and all(type(helper) is ModuleType for helper in helpers_by_role.values())
        and helpers_by_role['control'] is not helpers_by_role['balanced'],
        'two separate loaded private helper profiles required')
    require(first_bank in ROLES, 'explicit first bank required')
    owner_token = object()
    frozen_pairing, frozen_rules = wire(pairing), wire(original_rules)
    names = ('prepare_bank', 'estimate_training_work_bytes', 'prepare_tensor_cache', 'modality_loss', 'evaluate_bank')
    owners = dict(helpers_by_role)
    profile_constants = {role: {name:getattr(owners[role], name) for name in
        ('SCHEMA', 'CACHE_SCHEMA', 'LOSS_SCHEMA', 'STRATA')} for role in ROLES}
    functions = {role: {name: getattr(owners[role], name) for name in names} for role in ROLES}
    require(all(callable(value) for methods in functions.values() for value in methods.values()),
            'complete existing bank/cache/loss/readout interfaces required')
    classes = {role: owners[role].TensorCache for role in ROLES}
    require(all(set(cls.__slots__) == _SLOTS for cls in classes.values()), 'unchanged eleven-slot cache interface required')

    def owner_check():
        require(all(getattr(owners[role], name) is functions[role][name] for role in ROLES for name in names)
            and all(owners[role].TensorCache is classes[role] for role in ROLES)
            and all(getattr(owners[role], name) == value for role in ROLES
                    for name,value in profile_constants[role].items()), 'private helper binding changed')

    def prepare_bank(training_rows, validation_rows, *, source_inventory, codec, deadline, **kwargs):
        deadline_check(deadline); owner_check()
        require(type(source_inventory) is dict and set(source_inventory) ==
            {'schema', 'banks_by_role', 'pairing_sha256', 'payload_sha256'} | set(FALSE)
            and source_inventory['schema'] == INVENTORY_SCHEMA
            and all(source_inventory[name] is False for name in FALSE)
            and source_inventory['payload_sha256'] == retention.digest({k:v for k,v in source_inventory.items() if k != 'payload_sha256'})
            and source_inventory['pairing_sha256'] == detached(frozen_pairing)['pairing_sha256']
            and type(source_inventory['banks_by_role']) is dict and set(source_inventory['banks_by_role']) == set(ROLES),
            'closed separately bound dual source inventory required')
        before = wire(source_inventory)
        banks = {}
        for role in ROLES:
            banks[role] = functions[role]['prepare_bank'](training_rows, validation_rows, codec=codec,
                source_inventory=deepcopy(source_inventory['banks_by_role'][role]), deadline=deadline, **kwargs)
            require(type(banks[role]) is dict and type(banks[role].get('dimension')) is int
                and banks[role]['dimension'] == 384 and banks[role].get('codec_sha256') == retention.digest(codec),
                'separate native384 bank and matching codec required')
        schedule = retention.build_schedule(pairing=detached(frozen_pairing), banks_by_role=banks,
            original_rules=detached(frozen_rules), first_bank=first_bank)
        require(wire(source_inventory) == before, 'caller source inventory changed during preparation')
        receipt = dict(schema=BANK_SCHEMA, dimension=384, bank_count=2, rows_per_bank=180,
            pairing_sha256=source_inventory['pairing_sha256'], source_inventory_sha256=source_inventory['payload_sha256'],
            schedule_sha256=schedule['schedule_sha256'], codec_sha256=retention.digest(codec),
            bank_receipts={role:{k:v for k,v in banks[role].items() if k != 'rows'} for role in ROLES},
            decoder_rows_replaced=False, single_combined_bank_created=False, **FALSE)
        result = _Banks()
        for name, value in dict(_owner_token=owner_token, _banks_bytes=wire(banks), _schedule_bytes=wire(schedule),
            _inventory_bytes=before, _codec_bytes=wire(codec), _receipt_bytes=wire(receipt)).items():
            object.__setattr__(result, name, value)
        deadline_check(deadline); owner_check()
        return result

    def estimate_training_work_bytes(banks, *, max_optimizer_steps):
        require(type(banks) is _Banks and banks._owner_token is owner_token and type(max_optimizer_steps) is int and max_optimizer_steps == 170,
                'prepared bank pair and original170 step budget required')
        owner_check()
        # Conservatively retain each original cache's170-step workspace estimate.
        return sum(functions[role]['estimate_training_work_bytes'](bank, max_optimizer_steps=170)
            for role, bank in banks.banks_by_role.items()) + 2 * 1024 * 1024

    def prepare_tensor_cache(torch, model, banks, *, codec, input_transform, seed, deadline, max_optimizer_steps=170):
        deadline_check(deadline); owner_check()
        require(type(banks) is _Banks and banks._owner_token is owner_token and wire(codec) == banks._codec_bytes
            and type(seed) is int and seed == 1729 and type(max_optimizer_steps) is int and max_optimizer_steps == 170,
            'exact prepared banks/codec/seed170 cache budget required')
        schedule, members = banks.schedule, banks.banks_by_role
        caches = {}
        for role in ROLES:
            original = functions[role]['prepare_tensor_cache'](torch, model, members[role], codec=codec,
                input_transform=input_transform, seed=seed, deadline=deadline, max_optimizer_steps=170)
            require(type(original) is classes[role] and original._model is model and original._max_steps == 170
                and wire(original._receipt['bank_sha256']) == wire(members[role]['bank_sha256']),
                'authentic separate cache/model/bank binding required')
            orders = detached(frozen_pairing)['orders'][role]
            require(original._rows == tuple((r['id'], r['source_sha256'], r['modality'], r['template'])
                for r in members[role]['rows']), 'authentic source cache inventory differs')
            receipt = deepcopy(original._receipt)
            receipt.update(orders=deepcopy(orders), sampling='paired original-rule/template orders indexed by bank-local committed ordinal',
                pairing_sha256=detached(frozen_pairing)['pairing_sha256'], bank_role=role,
                original_cache_receipt=deepcopy(original._receipt), original_cache_receipt_sha256=retention.digest(original._receipt),
                original_cache_mutated=False, tensors_copied=False, model_copied=False)
            cache = classes[role]()
            for slot in classes[role].__slots__:
                value = receipt if slot == '_receipt' else tuple(tuple(order) for order in orders) if slot == '_orders' else getattr(original, slot)
                object.__setattr__(cache, slot, value)
            require(all(getattr(cache, slot) is getattr(original, slot) for slot in _SLOTS - {'_receipt', '_orders'}),
                    'existing model/tensor handle identity must be preserved')
            caches[role] = cache
        receipt = dict(schema=CACHE_SCHEMA, dimension=384, bank_count=2, rows_per_bank=180,
            schedule_sha256=schedule['schedule_sha256'], first_bank=schedule['first_bank'],
            proposed_schedule=deepcopy(schedule), max_global_committed_steps=170, max_committed_steps_per_bank=85,
            batch_size=6, full_vocabulary_size=32,
            loss_schema_by_role={role:profile_constants[role]['LOSS_SCHEMA'] for role in ROLES},
            bank_receipts={role:cache.receipt for role,cache in caches.items()},
            no_combined_tensor_bank=True, model_copied=False, **FALSE)
        result = _Caches()
        for name, value in dict(_owner_token=owner_token, _model=model, _banks=banks, _caches=caches, _receipt_bytes=wire(receipt),
            _witnesses={role:{slot:getattr(cache, slot) for slot in _SLOTS} for role,cache in caches.items()}).items():
            object.__setattr__(result, name, value)
        cache_check(result, model); deadline_check(deadline); owner_check()
        return result

    def cache_check(cache, model):
        owner_check()
        require(type(cache) is _Caches and cache._owner_token is owner_token and cache._model is model
            and type(cache._banks) is _Banks and cache._banks._owner_token is owner_token
            and wire(cache._banks.schedule) == wire(cache.receipt['proposed_schedule'])
            and type(cache._caches) is dict and set(cache._caches) == set(ROLES)
            and type(cache._witnesses) is dict and set(cache._witnesses) == set(ROLES),
            'matching private dual cache/model and exact two-bank membership required')
        for role in ROLES:
            selected, witness = cache._caches[role], cache._witnesses[role]
            require(type(selected) is classes[role] and all(getattr(selected, slot) is witness[slot]
                for slot in _SLOTS - {'_orders', '_rows', '_max_steps'})
                and wire(selected._orders) == wire(witness['_orders']) and wire(selected._rows) == wire(witness['_rows'])
                and type(selected._max_steps) is int and selected._max_steps == 170,
                'dual cache member handles/orders changed')
            require(wire(selected.receipt) == wire(cache.receipt['bank_receipts'][role]), 'dual cache member receipt changed')
            tensors = (selected._data, selected._vectors, selected._mask, selected._targets)
            require(tuple(t._version for t in tensors) == selected._versions and all(not t.requires_grad for t in tensors),
                    'detached bank tensors changed')
            current = dict(model.named_buffers()); current.update(dict(model.named_parameters()))
            require(all(current.get(name) is tensor and tensor._version == version for name,tensor,version in selected._fixed),
                    'frozen preprocessing/projection changed')

    def modality_loss(torch, model, cache, *, committed_step, deadline, requires_grad):
        deadline_check(deadline); cache_check(cache, model)
        require(type(committed_step) is int and 0 <= committed_step < 170 and type(requires_grad) is bool,
                'exact global committed ordinal and gradient mode required')
        draw = cache._banks.schedule['draws'][committed_step]
        role, local = draw['bank_role'], draw['bank_local_committed_step']
        selected = cache._caches[role]
        require([order[local % len(order)] for order in selected._orders] == draw['indices'],
                'bank-local order differs from paired draw')
        result = functions[role]['modality_loss'](torch, model, selected, committed_step=local,
                                                deadline=deadline, requires_grad=requires_grad)
        inner = result['receipt']
        require(type(inner) is dict and inner['schema'] == profile_constants[role]['LOSS_SCHEMA']
            and inner['gradient_enabled'] is requires_grad
            and wire(inner['strata']) == wire([dict(modality=m,template=t) for m,t in zip(draw['modalities'],draw['templates'])])
            and type(inner['committed_step']) is int and type(inner['committed_step']) is int and inner['committed_step'] == local
            and inner['bank_sha256'] == draw['selected_bank_sha256']
            and wire(inner['indices']) == wire(draw['indices']) and wire(inner['row_ids']) == wire(draw['row_ids'])
            and wire(inner['source_sha256']) == wire(draw['source_sha256'])
            and wire(inner['target_token_ids']) == wire(draw['target_token_ids']), 'authentic bank-local loss receipt differs')
        receipt = dict(schema=LOSS_SCHEMA, schedule_sha256=cache._banks.schedule['schedule_sha256'],
            global_committed_step=committed_step, bank_local_committed_step=local, bank_role=role,
            selected_bank_sha256=draw['selected_bank_sha256'], bank_local_loss_receipt=deepcopy(inner),
            mean_cross_entropy=inner['mean_cross_entropy'], correct=inner['correct'], batch_size=6,
            full_vocabulary_size=32, source_head_forward_calls=1, recurrent_forward_calls=0, count_forward_calls=0,
            gradient_enabled=requires_grad, optimizer_commit_observed=False, sampler_state_advanced=False, **FALSE)
        cache_check(cache, model); deadline_check(deadline)
        return dict(loss=result['loss'], receipt=receipt)

    def evaluate_bank(torch, model, cache, *, deadline):
        deadline_check(deadline); cache_check(cache, model)
        result = {role:functions[role]['evaluate_bank'](torch, model, selected, deadline=deadline)
                  for role,selected in cache._caches.items()}
        cache_check(cache, model); deadline_check(deadline)
        return dict(schema='dual-bank-wording-readout/v1', banks_by_role=result, **FALSE)

    helper = ModuleType(__name__ + '_private')
    helper.__dict__.update(prepare_bank=prepare_bank, estimate_training_work_bytes=estimate_training_work_bytes,
        prepare_tensor_cache=prepare_tensor_cache, modality_loss=modality_loss, evaluate_bank=evaluate_bank,
        schema=SCHEMA, pairing_sha256=detached(frozen_pairing)['pairing_sha256'],
        mixture=SimpleNamespace(authored=SimpleNamespace(TEMPLATES=tuple(template for role in ROLES
            for template in detached(frozen_pairing)['banks'][role]['templates']))))
    return helper


def reconcile_training_report(report):
    """Count actual trainer commits; prepared/forward observations are not commits."""
    require(type(report) is dict and type(report.get('committed_updates')) is list,
            'actual ordered inherited trainer commits required')
    result = deepcopy(report)
    auxiliary = result['paraphrase_modality_auxiliary']
    cache_receipt = auxiliary['cache_receipt']
    require(type(auxiliary.get('weight')) is float and auxiliary['weight'] in (0., .05),
            'exact original zero/positive auxiliary weight required')
    gradient_expected = auxiliary['weight'] > 0.
    if cache_receipt is None:
        require(not result['committed_updates'] and result.get('stopped_reason') == 'deadline_during_paraphrase_modality_preparation'
            and auxiliary.get('used_for_selection') is False and auxiliary.get('training_only') is True
            and all(type(auxiliary.get(name)) is int and auxiliary[name] == 0 for name in
                ('committed_updates', 'committed_clause_presentations', 'completed_forward_observations', 'forward_attempts',
                 'observed_clause_presentations', 'positively_supervised_clause_presentations'))
            and type(result.get('optimizer_steps')) is int and result['optimizer_steps'] == 0
            and auxiliary.get('uncommitted_observations') == [],
            'only an inherited zero-commit cache preparation timeout can lack caches')
        result['dual_bank_wording_replay'] = dict(schema='dual-bank-wording-committed-replay/v1',
            cache_prepared=False, unavailable_reason='inherited_tensor_cache_preparation_timeout',
            committed_updates=0, updates_per_bank={role:0 for role in ROLES},
            presentations_per_bank={role:0 for role in ROLES}, completed_schedule=False,
            postfit_retention_gate_required=True, default_checkpoint_selection_changed=False, **FALSE)
        return result
    require(cache_receipt['schema'] == CACHE_SCHEMA and type(cache_receipt['max_global_committed_steps']) is int
        and cache_receipt['max_global_committed_steps'] == 170
        and auxiliary.get('used_for_selection') is False and auxiliary.get('training_only') is True
        and all(cache_receipt.get(name) is False for name in FALSE),
            'actual dual tensor cache receipt required')
    schedule = cache_receipt['proposed_schedule']
    retention.validate_schedule(schedule)
    require(schedule['schedule_sha256'] == cache_receipt['schedule_sha256']
        and schedule['first_bank'] == cache_receipt['first_bank']
        and set(cache_receipt['bank_receipts']) == set(ROLES)
        and type(cache_receipt.get('loss_schema_by_role')) is dict
        and set(cache_receipt['loss_schema_by_role']) == set(ROLES)
        and all(type(name) is str and name for name in cache_receipt['loss_schema_by_role'].values())
        and all(cache_receipt['bank_receipts'][role]['bank_sha256'] == schedule['bank_sha256'][role]
            and cache_receipt['bank_receipts'][role]['bank_role'] == role
            and type(cache_receipt['bank_receipts'][role]['dimension']) is int
            and cache_receipt['bank_receipts'][role]['dimension'] == 384
            and all(cache_receipt['bank_receipts'][role].get(name) is False for name in
                ('admitted','qualified','proof_authority','lake_executed','formalized','roundtrip_ok',
                 'checkpoint_promoted','selection_performed','source_semantics_verified','encoder_executed','normalization_fitted'))
            for role in ROLES),
        'bound original proposed schedule and bank cache receipts required')
    ledger, updates, presentations, templates, modalities = [], Counter(), Counter(), Counter(), Counter()
    exposures = {role:Counter() for role in ROLES}
    for index, update in enumerate(result['committed_updates']):
        require(type(update['optimizer_step']) is int and update['optimizer_step'] == index + 1 and index < 170,
                'contiguous original optimizer commits required')
        observed = update['paraphrase_modality_auxiliary']; receipt = observed['receipt']
        require(type(observed['zero_based_committed_step']) is int and observed['zero_based_committed_step'] == index
            and receipt['schema'] == LOSS_SCHEMA and type(receipt['global_committed_step']) is int
            and receipt['global_committed_step'] == index and receipt['schedule_sha256'] == cache_receipt['schedule_sha256']
            and receipt.get('optimizer_commit_observed') is False and receipt.get('sampler_state_advanced') is False
            and all(receipt.get(name) is False for name in FALSE)
            and type(observed.get('weight')) is float and observed['weight'] == auxiliary['weight']
            and receipt.get('gradient_enabled') is gradient_expected,
            'actual auxiliary/global commit receipt differs')
        draw = schedule['draws'][index]
        role, local, inner = receipt['bank_role'], receipt['bank_local_committed_step'], receipt['bank_local_loss_receipt']
        require(role in ROLES and role == draw['bank_role'] and type(local) is int
            and local == draw['bank_local_committed_step'] == updates[role]
            and inner.get('schema') == cache_receipt['loss_schema_by_role'][role]
            and inner.get('gradient_enabled') is gradient_expected
            and type(inner['committed_step']) is int and inner['committed_step'] == local
            and receipt['selected_bank_sha256'] == inner['bank_sha256'] == draw['selected_bank_sha256']
            and all(inner.get(name) is False for name in ('admitted','qualified','proof_authority',
                'lake_executed','formalized','roundtrip_ok','checkpoint_promoted','selection_performed',
                'source_semantics_verified','historical_linguistic_teacher_modified','encoder_executed','normalization_fitted'))
            and inner.get('sampler_state_advanced') is False
            and wire(inner['row_ids']) == wire(draw['row_ids']) and wire(inner['indices']) == wire(draw['indices'])
            and wire(inner['source_sha256']) == wire(draw['source_sha256'])
            and wire(inner['target_token_ids']) == wire(draw['target_token_ids'])
            and wire(inner['strata']) == wire([dict(modality=m,template=t) for m,t in zip(draw['modalities'],draw['templates'])]),
            'separate bank-local committed receipt differs')
        updates[role] += 1; presentations[role] += 6
        exposures[role].update(inner['row_ids'])
        templates.update(item['template'] for item in inner['strata']); modalities.update(item['modality'] for item in inner['strata'])
        ledger.append(dict(global_committed_step=index, bank_role=role, bank_local_committed_step=local,
            bank_sha256=inner['bank_sha256'], bank_local_loss_receipt_sha256=retention.digest(inner), row_ids=deepcopy(inner['row_ids'])))
    require(type(auxiliary['committed_updates']) is int and auxiliary['committed_updates'] == len(ledger)
        and type(auxiliary['committed_clause_presentations']) is int and auxiliary['committed_clause_presentations'] == 6 * len(ledger),
            'inherited actual commit totals differ')
    auxiliary['inherited_single_bank_template_counts'] = dict(counts=auxiliary['committed_presentations_per_template'],
                                                            applicable_to_dual_bank=False)
    auxiliary['committed_presentations_per_template'] = dict(templates)
    auxiliary['committed_presentations_per_modality'] = dict(modalities)
    result['dual_bank_wording_replay'] = dict(schema='dual-bank-wording-committed-replay/v1',
        schedule_sha256=cache_receipt['schedule_sha256'], committed_updates=len(ledger),
        updates_per_bank={role:updates[role] for role in ROLES}, presentations_per_bank={role:presentations[role] for role in ROLES},
        per_source_exposures={role:dict(exposures[role]) for role in ROLES}, committed_draws=ledger,
        completed_schedule=len(ledger) == 170, observed_forwards_are_optimizer_commits=False,
        postfit_retention_gate_required=True, default_checkpoint_selection_changed=False,
        exposed_development_used_for_selection=False, **FALSE)
    return result


def configure_trainer(trainer, helper):
    """Isolate the relative helper import and reconcile the returned actual ledger."""
    from ipfs_datasets_py.logic.formalization.autoencoder import normative_wording_modality_auxiliary as normative
    require(type(helper) is ModuleType and getattr(helper, 'schema', None) == SCHEMA,
            'explicit configured dual-bank helper required')
    private = normative.configure_trainer(trainer, helper)
    train = private.train
    @functools.wraps(train)
    def wrapped(*args, **kwargs):
        result = train(*args, **kwargs)
        require(type(result) is dict and type(result.get('report')) is dict, 'original trainer result required')
        if 'paraphrase_modality_auxiliary' in result['report']:
            result['report'] = reconcile_training_report(result['report'])
        return result
    private.train = wrapped
    return private


__all__ = ['SCHEMA', 'INVENTORY_SCHEMA', 'BANK_SCHEMA', 'CACHE_SCHEMA', 'LOSS_SCHEMA',
           'build_source_inventory', 'configure', 'configure_trainer', 'reconcile_training_report']

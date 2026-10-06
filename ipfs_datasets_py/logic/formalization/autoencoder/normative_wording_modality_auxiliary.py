"""Private compatibility profiles for authenticated normative TRAIN clauses.

The existing mixture validator, detached tensor cache, six-stratum sampler and
full-vocabulary loss remain unchanged. Their function objects are rebound to a
private namespace with an explicit TRAIN renderer. Neither an imported module,
package attribute nor its default profile is replaced. This is reconstruction
supervision; it does not grant semantic qualification or Lake admission.
"""
from copy import deepcopy
from types import FunctionType, ModuleType, SimpleNamespace

SCHEMA = 'training-normative-wording-modality-bank/v1'
TEMPLATES = ('explicit_actor_status_v1', 'regulation_norm_operator_v1')
STRATA = tuple((m, t) for m in ('O', 'P', 'F') for t in TEMPLATES)
FUTURE_SOURCE_INVENTORY = 'prospective_development_sources'


def require(value, message):
    if not value:
        raise ValueError(message)


def private_module(owner, **overrides):
    """Clone only owner-local functions; their code and defaults are unchanged."""
    require(type(owner) is ModuleType, 'explicit loaded owner module required')
    result = ModuleType(owner.__name__ + '_private_normative_profile')
    result.__dict__.update(owner.__dict__)
    result.__dict__.update(overrides)
    for name, value in list(owner.__dict__.items()):
        if isinstance(value, FunctionType) and value.__globals__ is owner.__dict__:
            cloned = FunctionType(value.__code__, result.__dict__, value.__name__,
                value.__defaults__, value.__closure__)
            cloned.__kwdefaults__ = value.__kwdefaults__
            cloned.__annotations__ = dict(value.__annotations__)
            cloned.__dict__.update(value.__dict__)
            result.__dict__[name] = cloned
    result.__dict__.update(overrides)
    return result


def private_selector(selector, namespace):
    """Rebind the old mixture selector's methods to the same private renderer."""
    require(type(selector) is type and selector.__bases__ == (object,) and
        '__slots__' not in selector.__dict__, 'plain existing mixture selector required')
    attributes = {key: value for key,value in selector.__dict__.items()
        if key not in ('__dict__','__weakref__')}
    def bind(value):
        if not isinstance(value,FunctionType):
            return value
        cloned = FunctionType(value.__code__,namespace,value.__name__,value.__defaults__,value.__closure__)
        cloned.__kwdefaults__ = value.__kwdefaults__
        cloned.__annotations__ = dict(value.__annotations__)
        return cloned
    for key,value in list(attributes.items()):
        if isinstance(value,property):
            attributes[key] = property(bind(value.fget),bind(value.fset),bind(value.fdel),value.__doc__)
        else:
            attributes[key] = bind(value)
    return type(selector.__name__,selector.__bases__,attributes)


def configure(*, auxiliary_owner, mixture_owner, authored_owner):
    """Return one isolated renderer profile, preserving every default owner."""
    require(tuple(authored_owner.TEMPLATES) == TEMPLATES,
        'exact two normative TRAIN templates required')
    require(all(callable(getattr(authored_owner, name, None))
        for name in ('build', 'sentence')), 'authenticated TRAIN builder required')
    # The old mixture owner accepts the three-member paragraph corpus. The new
    # builder also publishes a separate clause census, checked by our wrapper.
    def paragraph_build(**kwargs):
        built = authored_owner.build(**kwargs)
        require(set(built) == {'source_rows', 'references', 'clause_references', 'receipt'},
            'complete normative TRAIN builder output required')
        return {key: built[key] for key in ('source_rows', 'references', 'receipt')}
    renderer = SimpleNamespace(**vars(authored_owner))
    renderer.build = paragraph_build
    mixture = private_module(mixture_owner, authored=renderer,
        PRIOR_DATASETS=set(authored_owner.REQUIRED_PRIOR_DATASETS) | {FUTURE_SOURCE_INVENTORY},
        SCHEMA='contextual-normative-wording-training-mixture/v1')
    mixture.Selector = private_selector(mixture_owner.Selector,mixture.__dict__)
    helper = private_module(auxiliary_owner, mixture=mixture, SCHEMA=SCHEMA,
        STRATA=STRATA, CACHE_SCHEMA='training-normative-wording-modality-cache/v1',
        LOSS_SCHEMA='training-normative-wording-modality-loss/v1')
    inherited_prepare = helper.prepare_bank

    def prepare_bank(training_rows, validation_rows, *, training_references,
            validation_references, source_contexts, codec, validate_rule,
            source_inventory, deadline):
        helper._deadline(deadline)
        require(type(source_inventory) is dict and
            source_inventory.get('payload_sha256') == helper.digest({k: v for k, v
                in source_inventory.items() if k != 'payload_sha256'}),
            'authenticated normative TRAIN envelope required')
        require(set(source_inventory) == set(mixture_owner.KEYS) | {'clause_training_references'},
            'closed normative TRAIN envelope required')
        prior = source_inventory['prior_sources_by_dataset']
        require(type(prior) is dict and set(prior) == mixture.PRIOR_DATASETS,
            'all thirteen named source-only exclusion inventories required')
        future = prior[FUTURE_SOURCE_INVENTORY]
        require(type(future) is list and len(future) == 60 and all(type(row) is dict
            and set(row) == {'id','source_text'} and type(row['id']) is str
            and 0 < len(row['id']) <= 512 and type(row['source_text']) is str
            and bool(row['source_text'].strip()) and len(row['source_text'].encode('utf-8')) <= 1048576
            and len(row['source_text'].split('\n\n')) == 1 for row in future),
            'closed sixty prospective source exclusions required; no labels')
        require(len({row['id'] for row in future}) == 60 and len({
            ' '.join(row['source_text'].casefold().split()) for row in future}) == 60,
            'unique prospective source exclusions required')
        corpus = source_inventory['corpus']
        rebuilt = authored_owner.build(training_bank=source_inventory['training_bank'],
            prior_sources_by_dataset=source_inventory['prior_sources_by_dataset'],
            codec=codec, sealed_recipe_sha256=corpus['receipt']['sealed_recipe_sha256'],
            validate_rule=validate_rule, seed=corpus['receipt']['seed'])
        require(corpus == {key: rebuilt[key] for key in ('source_rows', 'references', 'receipt')}
            and source_inventory['clause_training_references'] == rebuilt['clause_references'],
            'normative TRAIN derivations or clause census changed')
        normalized = {key: value for key, value in source_inventory.items()
            if key != 'clause_training_references'}
        normalized['payload_sha256'] = helper.digest({k: v for k, v in normalized.items()
            if k != 'payload_sha256'})
        bank = inherited_prepare(training_rows, validation_rows,
            training_references=training_references, validation_references=validation_references,
            source_contexts=source_contexts, codec=codec, validate_rule=validate_rule,
            source_inventory=normalized, deadline=deadline)
        clauses = {row['source_text']: row for row in rebuilt['clause_references']}
        require(len(clauses) == len(bank['rows']) == 180, 'complete unique180 TRAIN clauses required')
        for row in bank['rows']:
            ref = clauses[row['source_text']]
            require(ref['template'] == row['template'] and
                ref['target'] == {'rules': [row['target']]} and
                ref['parent_paragraph_id'] == row['parent_id'] and
                ref['source_sha256'] == row['source_sha256'],
                'native TRAIN clause/paragraph/target binding differs')
        bank.update(source_inventory_sha256=source_inventory['payload_sha256'],
            clause_training_references_sha256=helper.digest(rebuilt['clause_references']),
            compatibility_profile='private normative TRAIN renderer; unchanged full32V loss/cache/sampler',
            prospective_source_exclusions_sha256=helper.digest(future),
            prospective_reference_labels_supplied=False,
            helper_defaults_modified=False, package_aliases_modified=False)
        bank['bank_sha256'] = helper.digest({k: v for k, v in bank.items() if k != 'bank_sha256'})
        helper._deadline(deadline)
        return bank

    helper.prepare_bank = prepare_bank
    return helper


def configure_trainer(trainer, auxiliary_owner):
    """Intercept only this private trainer's explicit relative helper import."""
    namespace = trainer.__dict__.get('__builtins__')
    original = dict(namespace if type(namespace) is dict else vars(namespace))
    import_owner = original['__import__']
    package = trainer.__package__
    require(type(package) is str and package.endswith('.autoencoder'),
        'canonical autoencoder trainer package required')
    def private_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == '' and level == 1 and tuple(fromlist) == ('paraphrase_modality_auxiliary_training',):
            require(type(globals) is dict and globals.get('__package__') == package,
                'relative auxiliary import escaped private trainer package')
            return SimpleNamespace(paraphrase_modality_auxiliary_training=auxiliary_owner)
        return import_owner(name, globals, locals, fromlist, level)
    builtins = dict(original, __import__=private_import)
    return private_module(trainer, __builtins__=builtins)

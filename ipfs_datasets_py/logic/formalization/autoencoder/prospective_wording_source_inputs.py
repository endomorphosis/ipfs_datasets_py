"""Bounded native features for a sealed sixty-single-clause development panel.

The historical 48-paragraph producer contract stays intact. This owner validates
its own closed source shape, then uses the same native forwards and full saved
source/token/vector binding checks. Resource admission belongs to the caller.
"""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import time

from . import fresh_scalar_source_inputs as native
from . import clause_source_context as clauses

SCHEMA = 'prospective-wording-source-plan/v1'
REPORT = 'prospective-wording-source-production/v1'
INPUTS = 'prospective-wording-source-inputs/v1'
FALSE = dict(native.FALSE, fresh_holdout_claimed=False, lake_executed=False)
require, digest = native._require, native.digest


def source_plan(rows, *, expected_source_rows_sha256, sealed_recipe_sha256):
    require(type(rows) is list and len(rows) == 60, 'exact sixty source-only singles required')
    for value in (expected_source_rows_sha256, sealed_recipe_sha256):
        require(type(value) is str and native.authored._SHA.fullmatch(value), 'explicit source and recipe digests required')
    seen_ids, seen_text, inputs, aliases = set(), set(), [], []
    total_bytes = 0
    for row in rows:
        text, parts = native.authored._source(row)
        require(len(parts) == 1 and row['id'] not in seen_ids
            and native.authored._normal(text) not in seen_text, 'unique single-clause source required')
        seen_ids.add(row['id']); seen_text.add(native.authored._normal(text))
        total_bytes += len(text.encode())
        sha = native.authored.text_sha(text)
        identity = 'source:' + sha
        inputs.append(dict(id=identity, source_text=text))
        for role, slot in (('paragraph', None), ('clause', 0)):
            aliases.append(dict(paragraph_id=row['id'], role=role, slot=slot, source_id=identity, source_sha256=sha))
    require(total_bytes <= 1048576 and digest(rows) == expected_source_rows_sha256, 'bounded exact source inventory required')
    shape = dict(source_rows=deepcopy(rows), source_inputs=inputs, source_aliases=aliases,
        source_rows_sha256=expected_source_rows_sha256, sealed_comparison_sha256=sealed_recipe_sha256,
        unique_sources=60, paragraph_count=60, clause_occurrences=60, source_bytes=total_bytes,
        encoder_context_tokens=512)
    result = dict(schema=SCHEMA, role='prospective_development', shape_plan=shape,
        source_rows_sha256=expected_source_rows_sha256, sealed_recipe_sha256=sealed_recipe_sha256, **FALSE)
    result['plan_sha256'] = digest(result)
    return result


def _plan(plan):
    require(type(plan) is dict and plan.get('schema') == SCHEMA, 'prospective source plan required')
    shape = plan.get('shape_plan')
    require(type(shape) is dict, 'closed source shape required')
    expected = source_plan(shape.get('source_rows'), expected_source_rows_sha256=plan.get('source_rows_sha256'),
        sealed_recipe_sha256=plan.get('sealed_recipe_sha256'))
    require(plan == expected, 'prospective plan or aliases changed')
    return expected


def produce_width(plan, *, dimension, asset_config, source_artifact_directory=None, batch_size=4, max_seconds=600):
    require(type(dimension) is int and dimension in (384, 768), 'verified384/768 only; no fallback')
    require(type(batch_size) is int and batch_size == 4, 'fixed batch four required')
    require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 600,
        'bounded native preparation deadline required')
    native._asset_config(dimension, asset_config)
    require(dimension == 384 or source_artifact_directory is None, 'unused source directory forbidden')
    require(dimension != 384 or isinstance(source_artifact_directory, (str, Path))
        and Path(source_artifact_directory).is_absolute(), 'fresh absolute384 artifact directory required')
    owned = _plan(plan); started = time.monotonic(); deadline = started + max_seconds
    native._checkpoint(deadline)
    own_path = Path(__file__).resolve(); own_sha = hashlib.sha256(own_path.read_bytes()).hexdigest()
    producer = native._produce384 if dimension == 384 else native._produce768
    payload = producer(owned['shape_plan'], deepcopy(asset_config), source_artifact_directory, batch_size, deadline)
    native._checkpoint(deadline)
    result = dict(schema=REPORT, role='prospective_development', complete=True, dimension=dimension,
        plan_sha256=owned['plan_sha256'], source_rows_sha256=owned['source_rows_sha256'],
        sealed_recipe_sha256=owned['sealed_recipe_sha256'], asset_config=deepcopy(asset_config),
        producer_files=dict(payload['producer_files'], **{str(own_path):own_sha}),
        producer_pin_scope='named producers; caller freezes full import closure', vectors=payload['vectors'],
        native_production=payload['native_production'], source_artifact=payload['source_artifact'],
        representation=payload['representation'], receipt_count=60, encoder_executed=True,
        batch_size=batch_size, max_seconds=max_seconds, elapsed_seconds=time.monotonic()-started,
        deadline_cooperative=True, native_forward_interruptible=False, **FALSE)
    result['production_sha256'] = digest(result)
    validate_report(owned, result); native._checkpoint(deadline)
    return result


def validate_report(plan, report):
    owned = _plan(plan)
    require(type(report) is dict and report.get('schema') == REPORT
        and report.get('role') == 'prospective_development' and report.get('complete') is True
        and report.get('production_sha256') == digest({k:v for k,v in report.items() if k != 'production_sha256'})
        and report.get('plan_sha256') == owned['plan_sha256']
        and report.get('source_rows_sha256') == owned['source_rows_sha256']
        and report.get('sealed_recipe_sha256') == owned['sealed_recipe_sha256'], 'complete prospective production binding required')
    d = report.get('dimension')
    require(type(d) is int and d in (384,768) and report.get('encoder_executed') is True
        and all(report.get(k) is False for k in FALSE), 'prospective production authority or width differs')
    seconds = report.get('max_seconds')
    require(type(report.get('batch_size')) is int and report['batch_size'] == 4
        and type(seconds) in (int,float) and math.isfinite(seconds) and 0 < seconds <= 600,
        'fixed prospective native execution bounds required')
    representation = report.get('representation')
    require(type(representation) is dict and representation.get('dimension') == d
        and representation.get('semantic_embedding') is True and representation.get('device') == 'cpu'
        and representation.get('dtype') == 'float32' and representation.get('experiment_token_limit') == 512
        and representation.get('actual_forward_tokens_verified') is True,
        'actual bounded native representation required')
    if d == 384:
        from ....optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as runtime
        require(representation.get('kind') == 'native_gte_small_semantic_embedding'
            and representation.get('model_id') == 'thenlper/gte-small'
            and representation.get('revision') == runtime.PINNED_REVISION,
            'original native384 model profile required')
        execution = report.get('native_production',{}).get('execution',{})
        require(type(execution.get('batch_size')) is int and execution['batch_size'] == 4,
            'actual native384 batch must equal fixed four')
    else:
        from . import source_embeddings_768_complete as complete
        require(representation.get('kind') == 'native_gte_multilingual_semantic_embedding'
            and representation.get('profile_id') == complete.PROFILE_ID
            and representation.get('historical_profile_token_limit') == 8192
            and representation.get('cached_profile_relabelled') is False,
            'original native768 profile must remain explicitly bound')
        expected_execution = dict(batch_size=4, device='cpu', dtype='float32', pooling='cls',
            normalization='l2', max_tokens_including_special_tokens=512, attention_implementation='eager')
        require(report.get('native_production',{}).get('execution_profile') == expected_execution,
            'exact actual native768 execution profile required')
    native._asset_config(d, report['asset_config'])
    values = report.get('vectors')
    require(type(values) is list and len(values) == report.get('receipt_count') == 60, 'complete sixty native vectors required')
    for value, row in zip(values, owned['shape_plan']['source_inputs']):
        require(type(value) is dict and set(value) == {'id','source_sha256','vector','token_count','token_input_sha256'}
            and value['id'] == row['id'] and value['source_sha256'] == native.authored.text_sha(row['source_text']),
            'exact ordered native source identity required')
        native._vector(value['vector'], d)
        require(type(value['token_count']) is int and 1 <= value['token_count'] <= 512
            and type(value['token_input_sha256']) is str and native.authored._SHA.fullmatch(value['token_input_sha256']),
            'complete bounded token observations required')
    require(type(report.get('producer_files')) is dict and report['producer_files'], 'producer pins absent')
    native._unchanged(report['producer_files'])
    native._validate_native_binding(owned['shape_plan'], report)
    return d


def assemble(plan, report, *, dimension):
    owned = _plan(plan)
    require(type(dimension) is int and validate_report(owned, report) == dimension, 'explicit native width differs')
    lookup = {r['source_sha256']:r['vector'] for r in report['vectors']}
    require(len(lookup) == 60, 'complete unique source vector inventory required')
    rows = [dict(r, input=deepcopy(lookup[native.authored.text_sha(r['source_text'])]))
        for r in owned['shape_plan']['source_rows']]
    cache = [dict(id='clause:'+native.authored.text_sha(r['source_text']), source_text=r['source_text'], input=deepcopy(r['input'])) for r in rows]
    contexts = clauses.build_source_contexts(owned['shape_plan']['source_rows'], cache)
    require(clauses.validate_contexts(rows, contexts)['dimension'] == dimension, 'prospective source contexts differ')
    result = dict(schema=INPUTS, complete=True, role='prospective_development', dimension=dimension,
        rows=rows, clause_cache=cache, source_contexts=contexts, representation=deepcopy(report['representation']),
        production_sha256=report['production_sha256'], source_plan_sha256=owned['plan_sha256'],
        source_rows_sha256=owned['source_rows_sha256'], sealed_recipe_sha256=owned['sealed_recipe_sha256'], **FALSE)
    result['inputs_sha256'] = digest(result)
    return result

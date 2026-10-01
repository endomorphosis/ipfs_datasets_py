"""Real production learning, independent compositions and no target fallback."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_decoder as api
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_grammar as grammar
from ipfs_datasets_py.logic.formalization.autoencoder.security import codebase_autoencoder_transfer as transfer


def authored_formula_samples():
    """Independent generic capability controls; no benchmark source is consumed."""
    train = [
        'def read(value):\n    return value\n',
        'def integer(value):\n    return 17\n',
        'def literal(value):\n    return "safe"\n',
        'def add(value):\n    return value + 2\n',
        'def subtract(value):\n    return value - 2\n',
        'def multiply(value):\n    return value * 3\n',
        'def negative(value):\n    return -value\n',
        'def positive(value):\n    return +value\n',
        'def negate(value):\n    return not value\n',
        'def member(value):\n    return "z" in value\n',
        'def absent(value):\n    return "z" not in value\n',
        'def equal(value):\n    return value == 9\n',
        'def either(value, other):\n    return value or other\n',
        'def both(value, other):\n    return value and other\n',
        'def convert(value):\n    return str(value)\n',
        'def title(value):\n    return value.title()\n',
        'def lower(value):\n    return value.lower()\n',
        'def upper(value):\n    return value.upper()\n',
        'def fold(value):\n    return value.casefold()\n',
        'def replace(value):\n    return value.replace("a", "b")\n',
        'def local(value):\n    other = value + 4\n    return other\n',
        'def guard(value):\n    if "\\r" in value:\n        raise ValueError("invalid")\n    return value\n',
        'def chain(value):\n    return value.lower().upper()\n',
        'def combine(value, other):\n    return value + other * 3\n',
        'def clean(value):\n    value = str(value)\n    return value.lower()\n',
    ]
    validation = [
        'def compound(left, right):\n    temporary = left + right * 5\n    return -temporary\n',
        'def normalize(value):\n    return str(value).lower().replace("-", "_")\n',
        'def guarded(value):\n    if "\\r" in value or "\\n" in value:\n        raise ValueError("unsafe")\n    return value.upper()\n',
    ]
    test = [
        'def product(left, right):\n    return (left - 7) * (right + 2)\n',
        'def normalized(value):\n    return touni(value).title().replace("_", "-")\n',
        'def guarded(value):\n    if "\\r" in value or "\\n" in value or "\\x00" in value:\n        raise ValueError()\n    return value.casefold()\n',
    ]
    return [{"id": f"authored-{split}-{index}", "split": split, "source": source}
            for split, rows in (("train", train), ("validation", validation), ("test", test))
            for index, source in enumerate(rows)]


@pytest.fixture(scope="module")
def formula_checkpoint(tmp_path_factory):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import serialize_checkpoint
    root = tmp_path_factory.mktemp('formula-decoder')
    state = ModalAutoencoderTrainingState(feature_embedding_weights={
        'token:return': [0.03 * (i + 1) for i in range(8)],
        'token:value': [-0.02 * (i + 1) for i in range(8)],
        'token:raise': [0.01 * (i + 1) for i in range(8)],
        'law-specific:untransferred': [7.] * 8})
    raw = serialize_checkpoint(state, metadata={'fixture':'independently-authored-parent'})
    source = root / 'parent' / 'original-parent.json'
    source.parent.mkdir()
    source.write_bytes(raw)
    initializer = transfer.fork_legal_shared_weights(source_checkpoint=source,
        expected_sha256=hashlib.sha256(raw).hexdigest(), output=root/'fork'/'security-code-initializer')
    descriptor = api.train_security_formula_decoder(samples=authored_formula_samples(),
        weight_transfer=initializer, output=root/'security-formula-decoder')
    assert source.read_bytes() == raw
    return descriptor


def test_native_loss_trains_real_compositional_weights_and_independent_holdout(formula_checkpoint):
    loaded = api.load_security_formula_decoder(formula_checkpoint)
    training = loaded['training']
    assert training['initial_head_sha256'] != training['final_head_sha256']
    assert training['native_kernel_calls'] > 0 and any(x > 0 for x in training['gradient_norms'])
    assert training['training_losses'][-1] < training['training_losses'][0]
    assert training['metrics']['train']['exact_program_accuracy'] == 1
    assert training['metrics']['validation']['exact_program_accuracy'] == 1
    assert training['metrics']['test']['exact_program_accuracy'] == 1
    assert not training['heldout_used_for_fit'] and not training['teacher_whole_formula_lookup']
    assert loaded['weights']['lexical']['keys'] == ['token:raise','token:return','token:value']
    package_bytes = b''.join((Path(formula_checkpoint['output']) / name).read_bytes() for name in api.FILES)
    assert b'def ' not in package_bytes and b'law-specific:untransferred' not in package_bytes


def test_heldout_arithmetic_is_learned_then_native_checked_and_replayed(formula_checkpoint, monkeypatch):
    source = next(s['source'] for s in authored_formula_samples() if s['id']=='authored-test-0').encode()
    monkeypatch.setattr(api,'train_security_formula_decoder',lambda **kw: pytest.fail('inference trained'))
    report = api.decode_security_formula(source_bytes=source, checkpoint=formula_checkpoint, source_path='control.py')
    assert report['status'] == 'accepted', report
    assert report['learned_formula_count'] == 1 and report['native_artifact']
    assert report['validation']['source_AST_equivalent'] and report['validation']['native_lowering_complete']
    assert report['training_steps'] == report['provider_calls'] == report['solver_calls'] == 0
    assert report['proof_authority'] is report['security_specification_inferred'] is False
    assert api.validate_security_formula_decode(report, source_bytes=source,checkpoint=formula_checkpoint)==report


@pytest.mark.parametrize('disabled', [True, False])
def test_model_off_and_altered_weights_cannot_receive_deterministic_fallback(formula_checkpoint, disabled):
    source=b'def heldout(value):\n    return (value + 5) * (value - 8)\n'
    report=api.decode_security_formula(source_bytes=source,checkpoint=formula_checkpoint,source_path='control.py',
        model_enabled=not disabled,weight_ablation=None if disabled else 'zero_production_heads')
    assert report['status'] in {'rejected','unsupported'} and report['learned_formula_count']==0
    assert report['native_artifact'] is None and report['candidate'] is None


def test_headers_need_independent_reviewed_callee_context_after_learned_ast(formula_checkpoint):
    source=next(s['source'] for s in authored_formula_samples() if s['id']=='authored-test-1').encode()
    report=api.decode_security_formula(source_bytes=source,checkpoint=formula_checkpoint,source_path='control.py')
    assert report['status']=='candidate' and report['learned_formula_count']==0
    assert report['candidate'] and report['validation']['source_AST_equivalent']
    assert report['native_artifact'] is None
    assert {row['production'] for row in report['predicted_productions']} >= {'call','title','replace'}


def test_forged_loaded_weights_are_rejected_before_inference(formula_checkpoint):
    loaded=deepcopy(api.load_security_formula_decoder(formula_checkpoint))
    loaded['weights']['parameters'][3][0]+=100
    with pytest.raises(ValueError,match='cached decoder'):
        api.decode_security_formula(source_bytes=b'def f(value):\n    return value+1\n',checkpoint=formula_checkpoint,
            source_path='control.py',loaded=loaded)


@pytest.mark.parametrize('source', [b'def f(x=side_effect()):\n    return x\n',
    b'def f(x):\n    return secret_global\n',b'def f(x,x):\n    return x\n',b'def f(x):\n    return x / 0\n'])
def test_unsupported_sources_remain_frontiers(formula_checkpoint,source):
    report=api.decode_security_formula(source_bytes=source,checkpoint=formula_checkpoint,source_path='control.py')
    assert report['status']=='unsupported' and report['learned_formula_count']==0
    assert report['candidate'] is None and report['frontiers']


def test_source_span_features_do_not_contain_teacher_production_labels():
    parsed=grammar.parse_formula_source(b'def f(value):\n    return value+1\n')
    add=next(row for row in parsed['nodes'] if row['teacher_production']=='add')
    assert add['shell']=='+' and add['features'][grammar.SURFACE_TOKENS.index('+')]==1
    produced=[row['teacher_production'] for row in parsed['nodes']]
    raw,candidate=grammar.compose_candidate(parsed,produced)
    altered=list(produced);altered[produced.index('add')]='sub'
    with pytest.raises(ValueError,match='differs'):
        grammar.compose_candidate(parsed,altered)


def test_opaque_decorators_and_docstrings_are_preserved_not_formally_admitted(formula_checkpoint):
    source=b'@unreviewed_effect()\ndef f(value):\n    """Exact source documentation."""\n    return value+1\n'
    report=api.decode_security_formula(source_bytes=source,checkpoint=formula_checkpoint,source_path='control.py')
    assert report['status']=='candidate' and report['learned_formula_count']==0
    assert '@unreviewed_effect()' in report['candidate_source'] and 'Exact source documentation.' in report['candidate_source']
    assert report['candidate']['scaffolding']['semantic_status'].startswith('opaque')


def test_named_two_argument_call_scaffold_is_structural_not_source_execution():
    source=b'@api_view(["GET"])\ndef index(request):\n    """Render an authored page."""\n    return render(request, "index.html")\n'
    observed=grammar.parse_formula_source(source)
    output,tree=grammar.compose_candidate(observed,[row['teacher_production'] for row in observed['nodes']])
    assert tree['scaffolding']['decorators']==["api_view(['GET'])"]
    assert b'render(request' in output


def test_training_refuses_alpha_renamed_holdout_leakage(formula_checkpoint,tmp_path):
    # This is rejected before any gradient step, despite distinct source hashes.
    lexical=api.load_security_formula_decoder(formula_checkpoint)['weights']['lexical']
    parent=Path(formula_checkpoint['output']).parent/'fork'/'security-code-initializer'
    manifest_raw=(parent/'manifest.json').read_bytes()
    initializer=transfer._descriptor(parent,json.loads(manifest_raw),manifest_raw)
    examples=authored_formula_samples()
    examples.append({'id':'leak','split':'test','source':'def different(renamed):\n    return renamed + 99\n'})
    with pytest.raises(ValueError,match='cross-split'):
        api.train_security_formula_decoder(samples=examples,weight_transfer=initializer,output=tmp_path/'refused')
    assert not (tmp_path/'refused').exists()


@pytest.mark.parametrize('change',['raw_training_body','extra_tensor','wrong_shape','boolean_authority','nan_weight','symlink'])
def test_package_rejects_repinned_open_schemas_and_nonfinite_weights(formula_checkpoint,tmp_path,change):
    output=tmp_path/'tampered'
    shutil.copytree(formula_checkpoint['output'],output)
    descriptor={**formula_checkpoint,'output':str(output)}
    if change=='boolean_authority':
        descriptor['proof_authority']=0
    elif change=='symlink':
        target=tmp_path/'original-weights.json'
        (output/'weights.json').rename(target)
        (output/'weights.json').symlink_to(target)
    else:
        filename='training.json' if change=='raw_training_body' else 'weights.json'
        path=output/filename;value=json.loads(path.read_bytes())
        if change=='raw_training_body':value['raw_source']='def unapproved(): pass'
        elif change=='extra_tensor':value['parameters'].append([1.])
        elif change=='wrong_shape':value['parameters'][0].pop()
        else:value['parameters'][0][0][0]=float('nan')
        raw=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
        path.chmod(0o644);path.write_bytes(raw)
        manifest_path=output/'manifest.json';manifest=json.loads(manifest_path.read_bytes())
        manifest['files'][filename]={'sha256':api._sha(raw),'bytes':len(raw)}
        raw=api._json(manifest);manifest_path.chmod(0o644);manifest_path.write_bytes(raw)
        descriptor=api._descriptor(output,raw,manifest)
    with pytest.raises(ValueError):api.load_security_formula_decoder(descriptor)

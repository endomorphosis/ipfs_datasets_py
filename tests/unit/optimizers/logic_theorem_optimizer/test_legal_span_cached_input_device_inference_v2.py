"""CPU tensor controls for the separate request-local cached-row adapter."""
import ast
import copy
from pathlib import Path

import pytest


@pytest.fixture
def api():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_cached_input_device_inference
    return legal_span_cached_input_device_inference


@pytest.fixture
def torch():
    import torch
    assert torch.get_num_threads() == 1
    assert not torch.cuda.is_available()
    return torch


def cache(api, torch, dimension=768):
    text = "The contractor must retain the records."
    tokens = api._SPAN.tokenize_source(text)
    vector = [0.0] * dimension
    output = {"modality": torch.zeros((1, 3)), "presence": torch.zeros((1, 4, 2)),
              "start": torch.zeros((1, 6, len(tokens))), "end": torch.zeros((1, 6, len(tokens)))}
    obj = api._InputCachedOutput(torch, text=text, vector=vector, tokens=tokens,
                                output=output, enabled=True)
    return obj, text, vector, tokens, output


@pytest.mark.parametrize('dimension', [768, 4096])
def test_complete_cached_output_matches_original_and_uses_no_digest(api, torch, dimension):
    before = torch.random.get_rng_state()
    obj, text, vector, tokens, output = cache(api, torch, dimension)
    original = api._CACHE(torch, text=text, vector=vector, tokens=tokens, output=output, enabled=True)
    assert obj._binding_guard._canonical_bytes is None
    assert obj._binding_guard._use_fast_comparison is True
    tensors = api._BATCH(torch, [{"tokens": tokens, "latent": vector}])
    left, right = obj(*tensors), original(*tensors)
    assert set(left) == set(right) == set(output)
    assert all(torch.equal(left[name], right[name]) and
               torch.equal(torch.signbit(left[name]), torch.signbit(right[name])) for name in left)
    assert torch.equal(before, torch.random.get_rng_state())


@pytest.mark.parametrize('mutation', ['sign', 'tiny', 'type', 'length', 'text', 'tokens'])
def test_cached_binding_refuses_exact_mutations(api, torch, mutation):
    obj, text, vector, tokens, _ = cache(api, torch)
    if mutation == 'sign':
        vector[0] = -0.0
    elif mutation == 'tiny':
        vector[0] = 5e-324
    elif mutation == 'type':
        vector[0] = 0
    elif mutation == 'length':
        vector.pop()
    elif mutation == 'text':
        text = text.lower()
    else:
        obj._binding['tokens'][0]['byte_ids'][0] += 1
    with pytest.raises(ValueError):
        obj.bind(text, vector)


@pytest.mark.parametrize('name', ['modality', 'presence', 'start', 'end'])
def test_cached_numeric_output_mutation_still_refuses(api, torch, name):
    obj, _, vector, tokens, _ = cache(api, torch)
    obj._output[name].view(-1)[0] = -0.0
    with pytest.raises(ValueError, match='cached numerical outputs changed'):
        obj(*api._BATCH(torch, [{"tokens": tokens, "latent": vector}]))


def test_cached_input_tensor_mutation_and_second_use_refuse(api, torch):
    obj, _, vector, tokens, _ = cache(api, torch)
    tensors = api._BATCH(torch, [{"tokens": tokens, "latent": vector}])
    changed = tuple(value.clone() for value in tensors)
    changed[-1].view(-1)[0] = 1.0
    with pytest.raises(ValueError):
        obj(*changed)
    obj(*tensors)
    with pytest.raises(ValueError, match='gate/use'):
        obj(*tensors)


def test_caller_output_storage_is_not_retained(api, torch):
    obj, _, vector, tokens, output = cache(api, torch)
    for tensor in output.values():
        tensor.fill_(100)
    result = obj(*api._BATCH(torch, [{"tokens": tokens, "latent": vector}]))
    assert all(torch.count_nonzero(tensor).item() == 0 for tensor in result.values())


@pytest.mark.parametrize('target', ['guard', 'snapshot', 'binding_tuple'])
def test_guard_object_and_snapshot_substitution_refuse(api, torch, target):
    obj, text, vector, _, _ = cache(api, torch)
    if target == 'guard':
        obj._binding_guard = api._INPUT_GUARD(copy.deepcopy(obj._binding))
    elif target == 'snapshot':
        object.__setattr__(obj._binding_guard, '_reference',
                           api._INPUT_GUARD(copy.deepcopy(obj._binding))._reference)
    else:
        obj._guard_bindings = tuple(list(obj._guard_bindings))
    with pytest.raises(ValueError, match='guard|snapshot'):
        obj.bind(text, vector)


@pytest.mark.parametrize('target', ['paired_guard', 'paired_root'])
def test_independent_decode_anchor_refuses_coordinated_cache_replacement(api, torch, target):
    obj, _, _, _, _ = cache(api, torch)
    guard = obj._binding_guard
    local_binding = (guard, guard._reference, guard._canonical_bytes, guard._use_fast_comparison)
    new_guard = api._INPUT_GUARD(copy.deepcopy(obj._binding))
    if target == 'paired_guard':
        obj._binding_guard = new_guard
        guard = new_guard
    else:
        object.__setattr__(guard, '_reference', new_guard._reference)
    obj._guard_bindings = (guard, guard._reference, guard._canonical_bytes, guard._use_fast_comparison)
    obj._guard_bindings_identity = obj._guard_bindings
    # The cache's writable state is self-consistent, but the local decode anchor
    # still identifies the original object and snapshot.
    obj._check_guard()
    with pytest.raises(ValueError, match='independent local guard snapshot'):
        api._check_cache_snapshot(obj, local_binding)


@pytest.mark.parametrize('name', ['bind', '__call__', 'eval'])
def test_inherited_cache_method_replacement_refuses(api, monkeypatch, name):
    monkeypatch.setattr(api._CACHE, name, lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match='class or method'):
        api.inference_implementation()


@pytest.mark.parametrize('base_name', ['_BASE_768', '_BASE_4096'])
@pytest.mark.parametrize('name', ['_pure_check', '_description'])
def test_original_session_method_replacement_refuses(api, monkeypatch, base_name, name):
    monkeypatch.setattr(getattr(api, base_name), name, lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match='class or method'):
        api.inference_implementation()


def test_cached_call_keyword_default_mutation_refuses(api, monkeypatch):
    monkeypatch.setitem(api._CACHE_CALL.__kwdefaults__, 'enabled', False)
    with pytest.raises(ValueError, match='helper or alias|class or method'):
        api.inference_implementation()


@pytest.mark.parametrize('cls_name', ['InputCachedDeviceDimensionalSpanSession',
                                     'InputCachedDeviceLeanstral4096SpanSession'])
def test_private_session_method_replacement_refuses_before_model_access(api, cls_name):
    cls = getattr(api, cls_name)
    obj = cls.__new__(cls)
    obj._decision = lambda *args, **kwargs: None
    with pytest.raises(ValueError, match='method resolution'):
        obj._pure_check()


def test_descriptor_has_exact_experimental_scope(api):
    result = api.inference_implementation()
    assert result['change_scope'] == 'request_local_cached_row_binding_only_unused_digest'
    assert result['checkpoint_and_receipt_digests_retained'] is True
    assert result['inherited_numerical_cache_checks_retained'] is True
    for name in ('source_verification_success_cached', 'existing_selected_route_changed',
                 'performance_qualified', 'native_leanstral_outputs_qualified',
                 'production_qualified', 'proof_authority', 'execution_attestation'):
        assert result[name] is False


def test_cached_tensor_call_and_binding_checks_are_exact_inherited_methods(api):
    assert api._CACHE_BIND is api.batched._CachedOutput.bind
    assert api._CACHE_CALL is api.batched._CachedOutput.__call__
    assert api._DECODE is api.batched._DECODE_AT_IMPORT
    assert api._PURE_768 is api.native768.DeviceBitwiseDimensionalSpanSession._pure_check
    assert api._PURE_4096 is api.native4096.BitwiseDeviceLeanstral4096SpanSession._pure_check


def test_cached_constructor_tensor_body_matches_original(api):
    def body(path, class_name):
        module = ast.parse(Path(path).read_bytes())
        owner = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == class_name)
        return next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == '__init__').body
    old = body(api.batched.__file__, '_CachedOutput')
    new = body(api.__file__, '_InputCachedOutput')
    # Compare every original tensor/cache statement after the guard creation;
    # aliases only rename the unchanged bound original batch function.
    start_old = next(i for i, node in enumerate(old) if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Attribute) and target.attr == '_expected' for target in node.targets))
    start_new = next(i for i, node in enumerate(new) if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Attribute) and target.attr == '_expected' for target in node.targets))
    class Alias(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.copy_location(ast.Name(id='_BATCH' if node.id == '_BATCH_AT_IMPORT' else node.id, ctx=node.ctx), node)
    assert [ast.dump(Alias().visit(node), include_attributes=False) for node in old[start_old:]] == [
        ast.dump(node, include_attributes=False) for node in new[start_new:]]

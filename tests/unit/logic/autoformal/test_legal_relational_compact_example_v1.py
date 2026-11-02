"""Authored compact companions retain original source/byte-label boundaries."""
from copy import deepcopy
import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_relational_compact_example_v1 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_relational_compact_codec_v1 as compact


def _fixtures():
    path = Path(__file__).with_name("test_legal_relational_decoder_example_v1.py")
    spec = importlib.util.spec_from_file_location("_compact_example_original_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


examples = _fixtures()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def case(*, source_only=False, operator="P", request=None, value=None):
    """Return a complete authored original example and exact companion inputs."""
    value = examples.fixtures.case(source_only=source_only, operator=operator) if value is None else value
    join = examples.fixtures.prepare(value)
    replay_inputs = {"join_report": join, **examples.arguments(value, request=request)}
    original = examples.subject.prepare_relational_decoder_example_v1(**replay_inputs)
    codec = compact.build_relational_compact_codec_v1()
    return original, {"expected_original_example_sha256": examples.subject.relational_decoder_example_sha256(original),
        "original_replay_inputs": replay_inputs, "compact_codec": codec,
        "expected_compact_codec_sha256": compact.relational_compact_codec_sha256(codec)}


def prepare(original, kwargs):
    return subject.prepare_relational_compact_example_v1(original, **kwargs)


def replay(report, original, kwargs):
    return subject.validate_relational_compact_example_v1(report, original,
        expected_report_sha256=sha(wire(report)), **kwargs)


@pytest.fixture(scope="module")
def base():
    return case()


@pytest.fixture(scope="module")
def companion(base):
    return prepare(*deepcopy(base))


def assert_candidate_only(report):
    assert report["split"] == "unassigned"
    for field in ("training_mask", "evaluation_gold_mask"):
        assert type(report[field]) is int and report[field] == 0
    assert report["authority"] and all(flag is False for flag in report["authority"].values())


def test_public_cold_import_and_closed_report_hash_need_no_operation_owners(monkeypatch, companion):
    module = ModuleType("_cold_compact_example")
    module.__file__ = subject.__file__
    monkeypatch.setitem(sys.modules, module.__name__, module)
    original_import = builtins.__import__
    attempts = []
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"ipfs_datasets_py", "torch", "numpy", "transformers", "requests", "pyarrow", "duckdb"}:
            attempts.append(name)
            raise AssertionError("operation owner imported at pure companion boundary")
        return original_import(name, *args, **kwargs)
    source = Path(subject.__file__).read_bytes()
    with monkeypatch.context() as context:
        context.setattr(builtins, "__import__", guarded)
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        assert module.relational_compact_example_sha256(companion) == sha(wire(companion))
    assert attempts == []


def test_complete_replay_retains_original_byte_label_and_exact_source_compartment(base, companion):
    original, kwargs = deepcopy(base)
    before = deepcopy((original, kwargs))
    report = replay(companion, original, kwargs)
    assert report == companion
    assert report["original_example"] == original
    assert report["original_example_sha256"] == kwargs["expected_original_example_sha256"]
    assert set(report["model_input"]) == {"source_text", "context"}
    assert wire(report["model_input"]) == wire(original["model_input"])
    assert report["source_input_sha256"] == sha(wire(original["model_input"]))
    assert report["source_group_sha256"] == original["source_group_sha256"]
    for field in ("provenance", "source_identity", "embedding_reference", "codec_sha256", "label"):
        assert report["original_example"][field] == original[field]
    compact_label, byte = report["compact_label"], original["label"]["encoding"]
    encoded = compact_label["encoding"]
    assert compact_label["request_raw_sha256"] == original["label"]["request_raw_sha256"]
    assert compact_label["relational_report_sha256"] == original["label"]["relational_report_sha256"]
    for field in ("original_request", "canonical_request", "canonical_request_raw_utf8",
                  "relational_owner_report_sha256", "typed_expression_codec_sha256"):
        assert encoded[field] == byte[field]
    assert encoded["target_ids"] != byte["target_ids"]
    assert encoded["owner_codec_sha256"] == original["codec_sha256"]
    assert compact_label["encoding_sha256"] == compact.relational_compact_encoding_sha256(encoded)
    assert original["producer_pins"].items() <= report["producer_pins"].items()
    assert encoded["producer_pins"].items() <= report["producer_pins"].items()
    assert report["input_pins"]["original_example_request_sha256"] == kwargs["original_replay_inputs"]["expected_example_request_sha256"]
    assert (original, kwargs) == before
    assert_candidate_only(report)


def test_pending_original_never_encodes_or_manufactures_a_compact_label(monkeypatch):
    original, kwargs = case(source_only=True, request=examples.example_request(exposure="unknown"))
    monkeypatch.setattr(compact, "encode_relational_compact_target_v1", lambda *a, **k: pytest.fail("pending source encoded"))
    report = prepare(original, kwargs)
    assert replay(report, original, kwargs) == report
    assert report["status"] == "source_only_pending_target"
    assert report["compact_label"] is None and report["original_example"]["label"] is None
    assert report["original_example"] == original
    assert wire(report["model_input"]) == wire(original["model_input"])
    assert_candidate_only(report)


def test_alternative_target_and_ids_do_not_leak_into_input_or_create_independent_source_groups(base):
    first_original, first_kwargs = deepcopy(base)
    value = examples.fixtures.case(operator="O")
    value["join_request"]["component_id"] = "fixture:compact-alternative-component"
    value["join_request"]["alternative_id"] = "fixture:compact-alternative"
    second_original, second_kwargs = case(value=value)
    first, second = prepare(first_original, first_kwargs), prepare(second_original, second_kwargs)
    assert wire(first["model_input"]) == wire(second["model_input"])
    assert first["source_input_sha256"] == second["source_input_sha256"]
    assert first["source_group_sha256"] == second["source_group_sha256"]
    assert first["original_example"]["provenance"]["alternative_id"] != second["original_example"]["provenance"]["alternative_id"]
    assert first["compact_label"]["encoding"]["target_ids"] != second["compact_label"]["encoding"]["target_ids"]
    assert_candidate_only(first)
    assert_candidate_only(second)


@pytest.mark.parametrize("dimension", [8, 384, 768])
def test_embedding_declarations_stay_external_and_unverified(dimension, base):
    value = examples.fixtures.case()
    reference = examples.embedding_reference(value, dimension)
    original, kwargs = case(value=value, request=examples.example_request(reference))
    report = prepare(original, kwargs)
    assert report["original_example"]["embedding_reference"] == reference
    assert report["original_example"]["embedding_reference_declaration_only"] is True
    assert report["model_input"] == base[0]["model_input"]
    for field in ("embedding_payload_verified", "embedding_producer_verified", "embedding_source_independence_verified"):
        assert report["authority"][field] is False


@pytest.mark.parametrize("damage", ["original_pin", "compact_pin", "extra_replay", "missing_replay", "join_pin",
    "byte_codec_pin", "example_pin", "duplicate_json", "exposure", "request_extra", "raw_html", "partial_relational",
    "request_overflow", "codec_overflow", "depth_overflow"])
def test_bad_original_inputs_and_bounds_refuse_before_owner_import(base, damage, monkeypatch):
    original, kwargs = deepcopy(base)
    replay_inputs = kwargs["original_replay_inputs"]
    if damage == "original_pin": kwargs["expected_original_example_sha256"] = "0" * 64
    elif damage == "compact_pin": kwargs["expected_compact_codec_sha256"] = "0" * 64
    elif damage == "extra_replay": replay_inputs["compact_target"] = {}
    elif damage == "missing_replay": replay_inputs.pop("join_report")
    elif damage == "join_pin": replay_inputs["expected_join_report_sha256"] = "0" * 64
    elif damage == "byte_codec_pin": replay_inputs["expected_codec_sha256"] = "0" * 64
    elif damage == "example_pin": replay_inputs["expected_example_request_sha256"] = "0" * 64
    elif damage == "codec_overflow":
        kwargs["compact_codec"]["padding"] = "x" * (subject.MAX_CODEC_BYTES + 1)
        kwargs["expected_compact_codec_sha256"] = sha(wire(kwargs["compact_codec"]))
    elif damage == "depth_overflow":
        nested = None
        for _ in range(100): nested = [nested]
        original["model_input"]["context"] = nested
        kwargs["expected_original_example_sha256"] = sha(wire(original))
    elif damage in {"duplicate_json", "exposure", "request_extra", "request_overflow"}:
        request = examples.example_request()
        if damage == "exposure": request["exposure_status"] = "held_out"
        elif damage == "request_extra": request["target"] = original["label"]
        raw = b'{"schema":1,"schema":2}' if damage == "duplicate_json" else wire(request)
        if damage == "request_overflow": raw = b" " * (subject.MAX_REQUEST_BYTES + 1)
        replay_inputs.update(example_request_raw=raw, expected_example_request_sha256=sha(raw))
    elif damage == "raw_html": replay_inputs["join_replay_inputs"]["scope_replay_inputs"]["raw_html"] += b" "
    else: replay_inputs["join_replay_inputs"]["relational_request_raw"] = None
    monkeypatch.setattr(subject, "_owners", lambda: pytest.fail("owner imported before complete preflight"))
    with pytest.raises(ValueError): prepare(original, kwargs)


@pytest.mark.parametrize("damage", ["source", "target", "authority", "producer_path"])
def test_resealed_original_example_cannot_replace_full_original_replay(base, damage, monkeypatch):
    original, kwargs = deepcopy(base)
    if damage == "source": original["model_input"]["source_text"] += " invented"
    elif damage == "target": original["label"]["encoding"]["target_ids"][1] = 3 + ord("[")
    elif damage == "authority": original["authority"]["accepted"] = True
    else: original["producer_pins"]["/untrusted/not-a-producer.py"] = "0" * 64
    kwargs["expected_original_example_sha256"] = sha(wire(original))
    original_snapshot = subject._source_snapshot
    def checked(path):
        assert str(path) != "/untrusted/not-a-producer.py", "unreplayed input nominated a source read"
        return original_snapshot(path)
    monkeypatch.setattr(subject, "_source_snapshot", checked)
    with pytest.raises(ValueError): prepare(original, kwargs)


@pytest.mark.parametrize("damage", ["model_input", "compact_label", "original_label", "source_group", "mask", "authority", "replay_pin"])
def test_resealed_companion_cannot_change_compartments_or_promote_eligibility(base, companion, damage):
    original, kwargs = deepcopy(base)
    report = deepcopy(companion)
    if damage == "model_input": report["model_input"]["target"] = deepcopy(report["compact_label"])
    elif damage == "compact_label": report["compact_label"]["encoding"]["target_ids"][1] += 1
    elif damage == "original_label": report["original_example"]["label"] = None
    elif damage == "source_group": report["source_group_sha256"] = "0" * 64
    elif damage == "mask": report["evaluation_gold_mask"] = 1
    elif damage == "authority": report["authority"]["compact_checkpoint_qualified"] = True
    else: report["input_pins"]["original_replay_inputs_sha256"] = "0" * 64
    with pytest.raises(ValueError): replay(report, original, kwargs)


@pytest.mark.parametrize("phase,exception", [("example", RuntimeError("original failure")),
    ("compact", RuntimeError("compact failure")), ("compact", KeyboardInterrupt("cancelled"))])
def test_owner_errors_propagate_exactly_and_final_source_fence_runs(base, monkeypatch, phase, exception):
    original, kwargs = deepcopy(base)
    reads, fail_at = [], []
    snapshot = subject._source_snapshot
    def observed(path):
        reads.append(str(path))
        return snapshot(path)
    def failed(*args, **options):
        fail_at.append(len(reads))
        raise exception
    monkeypatch.setattr(subject, "_source_snapshot", observed)
    if phase == "example": monkeypatch.setattr(examples.subject, "validate_relational_decoder_example_v1", failed)
    else: monkeypatch.setattr(compact, "encode_relational_compact_target_v1", failed)
    with pytest.raises(type(exception)) as caught: prepare(original, kwargs)
    assert caught.value is exception
    assert fail_at and len(reads) > fail_at[0]
    assert str(Path(subject.__file__).absolute()) in reads[fail_at[0]:]


def test_cancellation_is_preserved_when_final_source_fence_also_fails(base, monkeypatch):
    original, kwargs = deepcopy(base)
    interrupted = KeyboardInterrupt("fixture cancellation")
    failed, final_reads = [False], []
    snapshot = subject._source_snapshot
    def observed(path):
        actual = snapshot(path)
        if failed[0]:
            final_reads.append(str(path))
            return ("0" * 64, actual[1])
        return actual
    def cancelled(*args, **options):
        failed[0] = True
        raise interrupted
    monkeypatch.setattr(subject, "_source_snapshot", observed)
    monkeypatch.setattr(compact, "encode_relational_compact_target_v1", cancelled)
    with pytest.raises(KeyboardInterrupt) as caught: prepare(original, kwargs)
    assert caught.value is interrupted and final_reads
    assert any("final source/input fence also failed" in note for note in caught.value.__notes__)


def test_owner_callback_mutation_of_original_inputs_is_refused(base, monkeypatch):
    original, kwargs = deepcopy(base)
    encode = compact.encode_relational_compact_target_v1
    def changed(*args, **options):
        result = encode(*args, **options)
        original["model_input"]["source_text"] += " mutation after validation"
        return result
    monkeypatch.setattr(compact, "encode_relational_compact_target_v1", changed)
    with pytest.raises(ValueError, match="inputs changed"):
        prepare(original, kwargs)


def test_compact_callback_cannot_replace_original_typed_identity_even_after_resealing(base, monkeypatch):
    original, kwargs = deepcopy(base)
    encode, validate = compact.encode_relational_compact_target_v1, compact.validate_relational_compact_encoding_v1
    def changed(*args, **options):
        report = encode(*args, **options)
        report["relational_owner_report_sha256"] = "0" * 64
        return report
    monkeypatch.setattr(compact, "encode_relational_compact_target_v1", changed)
    # The patched encoder also feeds the compact validator's regeneration.
    # Independently retained original byte-label identity must still disagree.
    monkeypatch.setattr(compact, "validate_relational_compact_encoding_v1", validate)
    with pytest.raises(ValueError): prepare(original, kwargs)


def test_source_to_compact_to_batch_preserves_source_separation_and_complete_population(tmp_path):
    """Authored end-to-end control: no model or actual statutory review."""
    import hashlib as hlib
    import importlib.util as iutil
    import json as js
    from pathlib import Path as P
    from copy import deepcopy as duplicate_value
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_relational_decoder_example_v1 as original_owner
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_relational_compact_example_v1 as companion_owner
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_relational_compact_codec_v1 as compact_owner
    from ipfs_datasets_py.logic.autoformal import legal_relational_batch_evaluation_v1 as batch_owner

    def raw(value):
        return js.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()

    def sha(value):
        return hlib.sha256(value).hexdigest()

    fixture_path = P(__file__).with_name('test_legal_relational_decoder_example_v1.py')
    spec = iutil.spec_from_file_location('_source_compact_batch_e2e_fixtures', fixture_path)
    fixtures = iutil.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    fixed_codec = compact_owner.build_relational_compact_codec_v1()
    fixed_sha = compact_owner.relational_compact_codec_sha256(fixed_codec)

    def example(inside_modal):
        value = fixtures.fixtures.case(inside_modal=inside_modal)
        joined = fixtures.fixtures.prepare(value)
        replay = {'join_report': joined, **fixtures.arguments(value)}
        original = original_owner.prepare_relational_decoder_example_v1(**replay)
        companion = companion_owner.prepare_relational_compact_example_v1(original,
            expected_original_example_sha256=original_owner.relational_decoder_example_sha256(original),
            original_replay_inputs=replay, compact_codec=fixed_codec,
            expected_compact_codec_sha256=fixed_sha)
        return value, original, companion

    left, original_left, compact_left = example(False)
    right, original_right, compact_right = example(True)
    assert compact_left['model_input'] == compact_right['model_input'] == original_left['model_input']
    assert compact_left['source_group_sha256'] == compact_right['source_group_sha256']
    assert compact_left['original_example'] == original_left
    assert compact_right['original_example'] == original_right
    assert set(compact_left['model_input']) == {'source_text', 'context'}
    ids_left = compact_left['compact_label']['encoding']['target_ids']
    ids_right = compact_right['compact_label']['encoding']['target_ids']
    assert ids_left != ids_right

    names = ['intact', 'rival', 'truncated', 'invalid_utf8', 'bad_frame', 'duplicate', 'missing', 'timeout']
    source = compact_left['model_input']
    population = {'schema': 'legal-relational-batch-population/v1', 'partition': 'authored-integration-controls',
        'selection_sha256': sha(b'eight authored output conditions, one fictional physical source'),
        'rows': [{'id': name, 'source_sha256': sha(source['source_text'].encode()),
                  'context_sha256': sha(raw(source['context']))} for name in names]}
    population_raw = raw(population)
    population_sha = sha(population_raw)
    source_rows = {row['id']: row for row in population['rows']}
    reference = left['relational_report']
    reference_raw = left['kwargs']['relational_request_raw']
    references = {'schema': 'legal-relational-batch-references/v1', 'population_sha256': population_sha,
        'rows': [{'id': name, 'status': 'available', 'request_utf8': reference_raw.decode(),
                  'request_sha256': sha(reference_raw), 'report': reference,
                  'report_sha256': left['kwargs']['expected_relational_report_sha256'], 'reason': None}
                 for name in names]}

    def observation(name, ids, *, status='generated'):
        return {**source_rows.get(name, {**source_rows['intact'], 'id': name}), 'status': status,
            'teacher_forcing': False, 'target_access': False, 'generated_ids': ids,
            'generated_ids_sha256': None if ids is None else sha(raw(ids)),
            'reason': None if status == 'generated' else 'Fictional declared timeout control'}

    rows = [observation('intact', ids_left), observation('rival', ids_right),
            observation('truncated', ids_left[:-1]), observation('invalid_utf8', [1, 258, 2]),
            observation('bad_frame', [9, 2]), observation('duplicate', ids_left),
            observation('duplicate', ids_right), observation('timeout', None, status='timeout'),
            observation('outside-selection', ids_left), observation(None, ids_left)]
    predictions = {'schema': 'legal-relational-compact-batch-predictions/v1',
        'codec': fixed_codec, 'codec_sha256': fixed_sha,
        'generation': {'kind': 'authored_control', 'population_sha256': population_sha,
            'latent_dimension': None, 'checkpoint_sha256': None, 'encoder_sha256': None,
            'settings_sha256': sha(b'authored codec outputs and explicit damage; no model'),
            'teacher_forcing': False, 'target_access': False}, 'rows': rows}
    originals = duplicate_value((population, references, predictions))
    references_raw, predictions_raw = raw(references), raw(predictions)
    pins = {'expected_population_sha256': population_sha, 'expected_references_sha256': sha(references_raw),
            'expected_predictions_sha256': sha(predictions_raw)}
    result = batch_owner.prepare_relational_compact_batch_evaluation_v1(
        population_raw, references_raw, predictions_raw, **pins)
    replayed = batch_owner.validate_relational_compact_batch_evaluation_v1(result,
        population_raw, references_raw, predictions_raw,
        expected_evaluation_sha256=batch_owner.relational_compact_batch_evaluation_sha256(result), **pins)
    assert replayed == result
    assert (population, references, predictions) == originals
    expected = {'intact': 'compared', 'rival': 'compared', 'truncated': 'incomplete',
                'invalid_utf8': 'invalid_utf8', 'bad_frame': 'invalid_frame',
                'duplicate': 'duplicate', 'missing': 'missing', 'timeout': 'timeout'}
    assert {row['id']: row['status'] for row in result['occurrences']} == expected
    assert sum(result['terminal_counts'].values()) == len(names) == 8
    assert result['coverage']['prediction_row_count'] == 10
    assert len(result['observation_ledger']) == 10
    assert result['coverage']['missing_ids'] == ['missing']
    assert result['coverage']['duplicate_ids'] == {'duplicate': [5, 6]}
    assert result['coverage']['unexpected_ids'] == {'outside-selection': [8]}
    assert result['coverage']['unidentifiable_indices'] == [9]
    ledger = result['observation_ledger']
    assert [row['index'] for row in ledger] == list(range(10))
    assert [row['raw_observation'] for row in ledger] == rows
    assert ledger[2]['compact_decoding']['status'] == 'incomplete'
    assert ledger[2]['compact_decoding']['framing']['eos_present'] is False
    assert ledger[3]['compact_decoding']['generated_transport_hex'] == 'ff'
    assert ledger[3]['compact_decoding']['reason'] == 'invalid_utf8'
    assert ledger[4]['compact_decoding']['reason'] == 'invalid_frame'
    assert ledger[5]['outcome'] == ledger[6]['outcome'] == 'duplicate'
    assert ledger[5]['compact_decoding']['canonical_request_sha256'] != ledger[6]['compact_decoding']['canonical_request_sha256']
    assert ledger[8]['outcome'] == 'unexpected'
    assert ledger[9]['outcome'] == 'unidentifiable'
    assert result['valid_typed_output'] == {'count': 2, 'total': 8, 'fraction': 0.25}
    assert result['full_selected_structure_diagnostics']['declared_structure_equal'] == {
        'matched': 1, 'total': 8, 'fraction': 0.125}
    assert result['comparable_pair_structure_diagnostics']['declared_structure_equal'] == {
        'matched': 1, 'total': 2, 'fraction': 0.5}
    assert not result['authority']['numerical_execution_authenticated']
    assert not any(result['authority'].values())
    assert result['training_mask'] == result['evaluation_gold_mask'] == 0
    assert compact_left['training_mask'] == compact_right['training_mask'] == 0
    evidence = {'schema': 'legal-ir-authored-compact-integration-fixture/v1',
        'origin': 'fictional source and deliberately authored/damaged codec outputs; no model predictions',
        'physical_fixture_source_groups': 1, 'norm_hypotheses': 2,
        'expected_occurrences': 8, 'submitted_observations': 10,
        'compact_examples': [compact_left, compact_right],
        'population_raw_utf8': population_raw.decode(),
        'references_raw_utf8': references_raw.decode(),
        'predictions_raw_utf8': predictions_raw.decode(),
        'batch_report': result, 'full_replay_equal': replayed == result,
        'model_forwards': 0, 'training_steps': 0, 'statutory_reviews': 0}
    (tmp_path / 'compact-integration.json').write_bytes(raw(evidence))

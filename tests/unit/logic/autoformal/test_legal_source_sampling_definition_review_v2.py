"""Join actual fictional source sampling and V2 review without adding authority.

Every success uses the real sampler, binding, candidate, context and dependency
owners. Six original byte inputs are frozen explicitly by this fixture before
review preparation. They are new test inputs, not historical statutory evidence.
No people, keys, review signatures, model calls or theorem execution are supplied.
"""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as review
from ipfs_datasets_py.logic.autoformal import (
    legal_source_sampling_definition_review_v2 as owner,
)


def _fixture(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BINDING = _fixture(
    "_correspondence_source_binding_fixture",
    "test_legal_source_sampling_definition_binding_v2.py",
)
_REVIEW = _fixture(
    "_correspondence_v2_context_fixture", "test_corpus_definition_review_v2.py"
)


def wire(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def transport(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8") + b"\n"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def source_case(family="fol", *, shape="opaque", split=False, edition=2024):
    case = (
        _BINDING.prepared_with_split_scope()
        if split else _BINDING.prepared(family=family, edition=edition)
    )
    case["request"]["family"] = family
    declaration = case["request"]["declaration"]
    if shape == "opaque":
        # One explicitly declared atom covers the WHOLE existing post-means
        # literal. This does not infer the Boolean interpretation of that text.
        literals = [
            declaration["body"]["operands"][0]["span"],
            declaration["body"]["operands"][1]["operands"][1]["operand"]["span"],
        ]
        start, end = literals[0]["char_start"], literals[-1]["char_end"]
        text = case["bundle"]["sampling_report"]["document_view_report"]["document"]["document_text"]
        declaration["body"] = {
            "op": "atom", "span": {"char_start": start, "char_end": end, "text": text[start:end]}
        }
    elif shape == "shared":
        atom = deepcopy(declaration["body"]["operands"][0])
        declaration["body"] = {"op": "any", "operands": [deepcopy(atom), deepcopy(atom)]}
    else:
        assert shape == "nested"
    case["request_raw"] = transport(case["request"])
    return case


def joined_case(family="fol", *, shape="opaque", split=False, edition=2024, responses=None):
    source = source_case(family, shape=shape, split=split, edition=edition)
    responses = [] if responses is None else responses(source)
    binding = _BINDING.prepare(source, responses=responses)
    sampling = source["bundle"]["sampling_report"]
    # The candidate commits the producer's compact report bytes. Formatting
    # those bytes later would change the graph, so preserve that exact report.
    original_inputs = {
        "candidate_raw": transport(binding["candidate"]),
        "report_raw": wire(binding["definition_report"]),
        "request_raw": source["request_raw"],
        "raw_html": source["raw"],
        "sampling_report_raw": transport(sampling),
        "descriptor_raw": transport(source["replay"]["descriptor"]),
    }
    pins = {
        "candidate_sha256": sha(original_inputs["candidate_raw"]),
        "candidate_cid": binding["candidate"]["record_cid"],
        "graph_cid": binding["candidate"]["graph"]["record_cid"],
        "request_sha256": sha(original_inputs["request_raw"]),
        "report_sha256": sha(original_inputs["report_raw"]),
        "raw_sha256": sha(original_inputs["raw_html"]),
        "raw_bytes": len(original_inputs["raw_html"]),
        "extracted_sha256": binding["candidate"]["source_version"]["extracted_view"]["sha256"],
        "sampling_report_sha256": sha(original_inputs["sampling_report_raw"]),
        "sampling_report_full_canonical_sha256": source["replay"]["expected_sampling_report_sha256"],
        "descriptor_sha256": sha(original_inputs["descriptor_raw"]),
        "descriptor_full_canonical_sha256": source["replay"]["expected_descriptor_sha256"],
    }
    review_case = {
        "record": binding["candidate"], "inputs": original_inputs, "pins": pins,
        "replay": {"sampling_report": sampling, **source["replay"]},
    }
    materialized = _REVIEW.materialize(review, review_case)
    args = {
        "expected_binding_sha256": digest(binding),
        "expected_subject_sha256": digest(materialized["subject"]),
        "binding_replay_inputs": {
            "request_raw": source["request_raw"],
            "bundle": source["bundle"],
            "responses": responses,
            "raw_html": source["raw"],
            "expected_request_sha256": sha(source["request_raw"]),
            "expected_bundle_sha256": digest(source["bundle"]),
            "expected_response_sha256s": [digest(row) for row in responses],
            "sampling_replay_inputs": source["replay"],
        },
        **materialized["arguments"],
        "dependency_manifest": materialized["manifest"],
        "expected_manifest_sha256": materialized["manifest"]["manifest_sha256"],
        "required_dependency_ids": materialized["preparation"]["expected_artifact_ids"],
    }
    return {
        "source": source, "binding": binding, "subject": materialized["subject"],
        "preparation": materialized["preparation"], "args": args,
        "original_bytes": dict(original_inputs),
    }


def prepare(case, *, binding=None, subject=None, **overrides):
    return owner.prepare_definition_review_correspondence_v2(
        case["binding"] if binding is None else binding,
        case["subject"] if subject is None else subject,
        **{**case["args"], **overrides},
    )


def validate(case, link, **overrides):
    return owner.validate_definition_review_correspondence_v2(
        link, case["binding"], case["subject"],
        expected_correspondence_sha256=digest(link),
        **{**case["args"], **overrides},
    )


def assert_unsigned(link):
    assert link["status"] == "unsigned_correspondence_only"
    assert link["view"] == "candidate"
    assert link["unsigned"] is True and link["assessment_created"] is False
    assert link["authority"] and all(value is False for value in link["authority"].values())
    assert type(link["training_mask"]) is int and link["training_mask"] == 0
    assert type(link["evaluation_gold_mask"]) is int and link["evaluation_gold_mask"] == 0


def assert_inputs_retained(case, before):
    assert case["args"]["candidate_inputs"] == case["original_bytes"]
    assert before == deepcopy((case["binding"], case["subject"], case["args"]))


@pytest.fixture(scope="module")
def base_case():
    return joined_case()


@pytest.fixture(scope="module")
def base_link(base_case):
    return prepare(base_case)


@pytest.fixture(scope="module")
def other_edition():
    return joined_case(edition=2023)


@pytest.mark.parametrize("family", ["fol", "tdfol"])
@pytest.mark.parametrize("shape,count", [("opaque", 6), ("nested", 8)])
def test_actual_source_candidate_and_review_subject_preserve_complete_populations(family, shape, count):
    case = joined_case(family, shape=shape)
    before = deepcopy((case["binding"], case["subject"], case["args"]))
    link = prepare(case)
    assert_unsigned(link)
    assert link["source_identity"] == case["binding"]["binding"]["source_identity"]
    assert link["selected_unit_roles"] == case["binding"]["binding"]["selected_unit_roles"]
    assert link["source_role_bindings"] == case["binding"]["binding"]["source_role_bindings"]
    assert link["required_subjects"] == case["binding"]["binding"]["required_subjects"]
    assert len(link["required_subjects"]) == 2
    assert link["population_subjects"] == case["binding"]["population"]["subjects"]
    assert link["population_counts"] == case["binding"]["population"]["counts"]
    assert link["population_subject_count"] == len(case["source"]["bundle"]["guides"])
    assert len(link["population_subjects"]) > len(link["required_subjects"])
    assert len(link["occurrence_context_links"]) == count
    assert link["expected_context_population"] == case["args"]["expected_context_population"]
    assert link["context_slot_ids"] == case["subject"]["context_slot_ids"]
    assert len(link["context_slot_ids"]) == count * 6
    for row, occurrence, packet in zip(
        link["occurrence_context_links"],
        case["binding"]["candidate"]["source_occurrences"],
        case["args"]["context_inputs"], strict=True,
    ):
        decoded_packet = json.loads(packet["packet_raw"])
        assert row["occurrence_ref"] == {
            "schema": occurrence["schema"], "record_cid": occurrence["record_cid"],
            "sha256": digest(occurrence),
        }
        assert row["packet_id"] == decoded_packet["packet_id"]
        assert row["packet_sha256"] == sha(packet["packet_raw"])
        assert row["packet_canonical_sha256"] == digest(decoded_packet)
        assert row["source_role_bindings"] == [
            role for role in case["binding"]["binding"]["source_role_bindings"]
            if role["source_occurrence_cid"] == occurrence["record_cid"]
        ]
    assert case["subject"]["graph_id"] == case["binding"]["candidate"]["graph"]["record_cid"]
    assert case["subject"]["native_binding"]["native_ast"] == case["binding"]["definition_report"]["native_ast"]
    assert owner.definition_review_correspondence_sha256(link) == digest(link)
    assert validate(case, link) == link
    assert_inputs_retained(case, before)


def test_original_transport_hashes_keep_their_separate_namespaces(base_case, base_link):
    case, link = base_case, base_link
    inputs, pins = case["args"]["candidate_inputs"], case["args"]["expected_candidate_pin"]
    for field in ("candidate_raw", "sampling_report_raw", "descriptor_raw"):
        assert sha(inputs[field]) != digest(json.loads(inputs[field]))
    assert link["original_input_pins"] == pins
    assert link["binding_input_pins"] == case["binding"]["binding"]["input_pins"]
    assert sha(inputs["report_raw"]) == case["binding"]["binding"]["definition_report_ref"]["sha256"]
    assert pins["candidate_sha256"] != case["binding"]["binding"]["candidate_ref"]["sha256"]
    assert validate(case, link) == link


def test_pretty_report_cannot_replace_the_exact_report_committed_by_this_graph(base_case):
    args = deepcopy(base_case["args"])
    original = args["candidate_inputs"]["report_raw"]
    pretty = transport(json.loads(original))
    assert json.loads(pretty) == json.loads(original) and sha(pretty) != sha(original)
    args["candidate_inputs"]["report_raw"] = pretty
    args["expected_candidate_pin"]["report_sha256"] = sha(pretty)
    with pytest.raises(ValueError):
        prepare(base_case, **args)


def test_shared_physical_geometry_keeps_both_explicit_roles():
    case = joined_case(shape="shared")
    link = prepare(case)
    roles = case["binding"]["binding"]["source_role_bindings"]
    bodies = [row for row in roles if row["role"].startswith("definition_body/")]
    assert len(bodies) == 2 and bodies[0]["source_occurrence_cid"] == bodies[1]["source_occurrence_cid"]
    joined = [row for row in link["occurrence_context_links"] if len(row["source_role_bindings"]) > 1]
    assert len(joined) == 1
    assert joined[0]["source_role_bindings"] == bodies
    assert len(link["occurrence_context_links"]) == 6
    assert_unsigned(link)


def test_split_required_parent_and_unrelated_parent_remain_in_their_own_populations():
    case = joined_case(split=True)
    link = prepare(case)
    required, unrelated = _BINDING.split_parent_guides(case["source"])
    assert len(link["required_subjects"]) == 3
    assert required["subject_ref"] in [row["subject_ref"] for row in link["required_subjects"]]
    assert unrelated["subject_ref"] not in [row["subject_ref"] for row in link["required_subjects"]]
    assert link["population_subjects"] == case["binding"]["population"]["subjects"]
    assert sum(row["subject_ref"]["kind"] == "withheld_context" for row in link["population_subjects"]) == 2
    rows = [role for item in link["occurrence_context_links"] for role in item["source_role_bindings"]]
    # This particular opaque split fixture has six distinct geometries in role
    # order. General shared-geometry integrity is asserted per occurrence above.
    assert rows == case["binding"]["binding"]["source_role_bindings"]
    for row in rows:
        assert unrelated["subject_ref"] not in row["subject_refs"]
        if row["role"] in {"scope_block", "scope_literal"}:
            assert required["subject_ref"] in row["subject_refs"]
    assert_unsigned(link)


@pytest.mark.parametrize("unsupported", [False, True])
def test_unsigned_source_response_state_cannot_create_review_authority(base_case, base_link, unsupported):
    case = joined_case(responses=lambda source: [
        _BINDING.response(source, guide, unsupported=unsupported)
        for guide in _BINDING.selected_guides(source)
    ])
    link = prepare(case)
    assert case["binding"]["candidate"] == base_case["binding"]["candidate"]
    assert case["subject"] == base_case["subject"]
    assert link["population_subjects"] != base_link["population_subjects"]
    assert link["required_subjects"] == case["binding"]["binding"]["required_subjects"]
    assert {row["state"] for row in link["required_subjects"]} == {
        "unsupported" if unsupported else "declarations_recorded"
    }
    assert_unsigned(link)
    assert validate(case, link) == link


@pytest.mark.parametrize("pin", ["expected_binding_sha256", "expected_subject_sha256", "expected_manifest_sha256"])
def test_wrong_independent_input_pin_refuses_before_a_link_is_returned(base_case, pin):
    with pytest.raises(ValueError):
        prepare(base_case, **{pin: sha((pin + "wrong").encode())})


def test_wrong_independent_correspondence_pin_refuses(base_case, base_link):
    with pytest.raises(ValueError):
        owner.validate_definition_review_correspondence_v2(
            base_link, base_case["binding"], base_case["subject"],
            expected_correspondence_sha256=sha(b"other-correspondence"), **base_case["args"],
        )


@pytest.mark.parametrize("mutation", [
    "extra_replay_field", "missing_replay_field", "extra_candidate_input",
    "wrong_input_type", "invalid_sha", "oversized_request", "oversized_html",
])
def test_closed_and_bounded_preflight_never_loads_operation_owners(base_case, mutation):
    args = deepcopy(base_case["args"])
    replay = args["binding_replay_inputs"]
    if mutation == "extra_replay_field":
        replay["caller_authority"] = True
    elif mutation == "missing_replay_field":
        replay.pop("sampling_replay_inputs")
    elif mutation == "extra_candidate_input":
        args["candidate_inputs"]["unbound_raw"] = b"extra"
    elif mutation == "wrong_input_type":
        args["candidate_inputs"]["raw_html"] = "text-is-not-original-bytes"
    elif mutation == "invalid_sha":
        args["expected_subject_sha256"] = "not-a-sha"
    elif mutation == "oversized_request":
        replay["request_raw"] = b" " * (1024 * 1024 + 1)
        replay["expected_request_sha256"] = sha(replay["request_raw"])
    else:
        replay["raw_html"] = b" " * 8_000_001
        replay["sampling_replay_inputs"]["expected_raw_bytes"] = len(replay["raw_html"])
        replay["sampling_replay_inputs"]["expected_raw_sha256"] = sha(replay["raw_html"])
    with patch.object(owner, "_owners", side_effect=AssertionError("operation owners reached before closed preflight")) as operation:
        with pytest.raises(ValueError):
            prepare(base_case, **args)
        operation.assert_not_called()


@pytest.mark.parametrize("mutation", ["authority", "population", "roles", "context", "source_identity"])
def test_resealing_tampered_correspondence_does_not_replace_independent_replay(base_case, base_link, mutation):
    offered = deepcopy(base_link)
    if mutation == "authority":
        offered["authority"]["source_semantics_verified"] = True
    elif mutation == "population":
        offered["population_subjects"].pop()
    elif mutation == "roles":
        offered["required_subjects"].reverse()
    elif mutation == "context":
        offered["context_slot_ids"].reverse()
    else:
        offered["source_identity"]["normalized_view_id"] += "-substituted"
    offered = _BINDING.reseal(offered)
    assert offered["record_cid"] != base_link["record_cid"]
    with pytest.raises(ValueError):
        validate(base_case, offered)


@pytest.mark.parametrize("replacement", ["candidate", "source", "subject", "population"])
def test_other_real_edition_cannot_be_mixed_into_this_join(base_case, other_edition, replacement):
    args = deepcopy(base_case["args"])
    subject = base_case["subject"]
    binding = base_case["binding"]
    if replacement == "candidate":
        args["candidate_inputs"] = other_edition["args"]["candidate_inputs"]
        args["expected_candidate_pin"] = other_edition["args"]["expected_candidate_pin"]
    elif replacement == "source":
        args["binding_replay_inputs"] = other_edition["args"]["binding_replay_inputs"]
    elif replacement == "subject":
        subject = other_edition["subject"]
        args["expected_subject_sha256"] = digest(subject)
        for field in ("dependency_manifest", "expected_manifest_sha256", "required_dependency_ids"):
            args[field] = other_edition["args"][field]
    else:
        binding = deepcopy(binding)
        binding["population"] = other_edition["binding"]["population"]
        args["expected_binding_sha256"] = digest(binding)
    with pytest.raises(ValueError):
        prepare(base_case, binding=binding, subject=subject, **args)


def test_another_valid_ast_over_the_same_source_cannot_replace_the_selected_candidate(base_case):
    other = joined_case(shape="nested")
    assert other["source"]["raw"] == base_case["source"]["raw"]
    assert other["binding"]["definition_report"]["native_ast"] != base_case["binding"]["definition_report"]["native_ast"]
    args = deepcopy(base_case["args"])
    for field in (
        "candidate_inputs", "expected_candidate_pin", "context_inputs",
        "expected_context_population", "dependency_manifest",
        "expected_manifest_sha256", "required_dependency_ids", "expected_subject_sha256",
    ):
        args[field] = other["args"][field]
    with pytest.raises(ValueError):
        prepare(base_case, subject=other["subject"], **args)


@pytest.mark.parametrize("mutation", ["missing", "reordered"])
def test_every_physical_context_is_required_in_its_original_order(base_case, mutation):
    args = deepcopy(base_case["args"])
    for field in ("context_inputs", "expected_context_population"):
        if mutation == "missing":
            args[field].pop()
        else:
            args[field].reverse()
    with pytest.raises(ValueError):
        prepare(base_case, **args)


@pytest.mark.parametrize("mutation", ["missing", "reordered"])
def test_exact_ordered_manifest_dependency_closure_cannot_be_shortened_or_reordered(base_case, mutation):
    ids = list(base_case["args"]["required_dependency_ids"])
    assert len(ids) > 1
    ids = ids[:-1] if mutation == "missing" else list(reversed(ids))
    with pytest.raises(ValueError):
        prepare(base_case, required_dependency_ids=ids)


COLD_REPLAY = r"""
import base64
import builtins
import hashlib
import importlib
import json
import os
import subprocess
import sys

prefixes = ('symai', 'torch', 'transformers', 'tensorflow')
def forbidden_name(name):
    return any(name == prefix or name.startswith(prefix + '.') for prefix in prefixes)
assert not any(forbidden_name(name) for name in sys.modules)
operation_attempts = []
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if forbidden_name(name):
        operation_attempts.append(name)
        raise AssertionError('optional runtime imported during correspondence replay: ' + name)
    return original_import(name, *args, **kwargs)
class OptionalGuard:
    def find_spec(self, fullname, path=None, target=None):
        if forbidden_name(fullname):
            operation_attempts.append(fullname)
            raise AssertionError('optional runtime lookup during correspondence replay: ' + fullname)
        return None
def forbidden_process(*args, **kwargs):
    operation_attempts.append('Popen')
    raise AssertionError('correspondence replay must not start a child')
write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
def audit(event, args):
    if event == 'open':
        _, mode, flags = args
        if ((isinstance(mode, str) and any(c in mode for c in 'wax+'))
                or (isinstance(flags, int) and flags & write_flags)):
            operation_attempts.append(event)
            raise AssertionError('cold correspondence replay must not write files')
    elif event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.rename', 'os.symlink',
                   'os.link', 'os.truncate', 'os.chmod', 'os.utime',
                   'subprocess.Popen', 'os.system', 'os.posix_spawn', 'socket.connect'}:
        operation_attempts.append(event)
        raise AssertionError('cold replay attempted an external operation: ' + event)
def decode(value):
    if type(value) is dict:
        if set(value) == {'__original_bytes_base64__'}:
            return base64.b64decode(value['__original_bytes_base64__'], validate=True)
        return {key: decode(item) for key, item in value.items()}
    if type(value) is list:
        return [decode(item) for item in value]
    return value
payload = decode(json.load(sys.stdin))
module_name = 'ipfs_datasets_py.logic.autoformal.legal_source_sampling_definition_review_v2'
assert module_name not in sys.modules
builtins.__import__ = guarded_import
sys.meta_path.insert(0, OptionalGuard())
subprocess.Popen = forbidden_process
sys.dont_write_bytecode = True
sys.addaudithook(audit)
owner = importlib.import_module(module_name)
checked = owner.validate_definition_review_correspondence_v2(
    payload['link'], payload['binding'], payload['subject'],
    expected_correspondence_sha256=payload['link_sha256'], **payload['args'],
)
assert checked == payload['link']
assert checked['unsigned'] is True and checked['assessment_created'] is False
assert all(value is False for value in checked['authority'].values())
assert checked['training_mask'] == checked['evaluation_gold_mask'] == 0
assert not operation_attempts, operation_attempts
assert not any(forbidden_name(name) for name in sys.modules)
print(json.dumps({
    'sha256': owner.definition_review_correspondence_sha256(checked),
    'contexts': len(checked['occurrence_context_links']),
    'source_subjects': len(checked['population_subjects']),
    'unsigned': checked['unsigned'],
}, sort_keys=True))
"""


def test_cold_public_replay_uses_only_json_and_explicit_original_bytes(base_case, base_link):
    def encode(value):
        if type(value) is bytes:
            return {"__original_bytes_base64__": base64.b64encode(value).decode("ascii")}
        if type(value) is dict:
            return {key: encode(item) for key, item in value.items()}
        if type(value) is list:
            return [encode(item) for item in value]
        return value

    before = deepcopy((base_case["binding"], base_case["subject"], base_case["args"]))
    payload = {
        "binding": base_case["binding"], "subject": base_case["subject"],
        "args": base_case["args"], "link": base_link, "link_sha256": digest(base_link),
    }
    root = Path(__file__).resolve().parents[4]
    environment = dict(os.environ)
    inherited = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(root) + (os.pathsep + inherited if inherited else "")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", "-c", COLD_REPLAY], input=wire(encode(payload)),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=root,
        env=environment, timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert json.loads(completed.stdout) == {
        "sha256": digest(base_link), "contexts": 6,
        "source_subjects": len(base_case["binding"]["population"]["subjects"]),
        "unsigned": True,
    }
    assert_inputs_retained(base_case, before)

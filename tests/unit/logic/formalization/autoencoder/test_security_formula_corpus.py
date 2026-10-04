"""Native Git/body/CodeUnit provenance through bounded source grammar samples."""
import base64
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_corpus as api
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_cve_source_context as context
from .test_security_cve_corpus import scenario  # noqa: F401
from .test_security_cve_source_context import source_case, _git, _tree  # noqa: F401


def recover(source_case, *, collision=False, unsupported=False):
    args, objects, calls, _ = source_case
    for split in api.SPLITS:
        url = "https://github.com/authored-fixture/" + split
        for fixed in (False, True):
            operator = "+" if collision else {"train": "+", "validation": "-", "test": "*"}[split]
            expression = "value.attr" if unsupported else f"value {operator} {2 if fixed else 1}"
            function_name = "shared" if collision == "body" else split + "_function"
            body = (f"# Complete independently authored {split} module\n"
                    "class Container:\n"
                    f"    def {function_name}(value):\n        return {expression}\n"
                    "\ndef unsupported(value='default'):\n    return value\n").encode()
            sha = _git("blob", body)
            objects[context.GitSourceRequest(url, "blobs", sha).key] = {
                "sha": sha, "encoding": "base64", "content": base64.b64encode(body).decode(), "size": len(body)}
            subtree, sub = _tree([{"path": "check.py", "mode": "100644", "type": "blob", "sha": sha}])
            objects[context.GitSourceRequest(url, "trees", subtree).key] = sub
            tree, root = _tree([{"path": "src", "mode": "040000", "type": "tree", "sha": subtree}])
            objects[context.GitSourceRequest(url, "trees", tree).key] = root
            revision = ("1" if fixed else "2") * 40
            objects[context.GitSourceRequest(url, "commits", revision).key]["tree"]["sha"] = tree
    receipt = context.recover_security_source_context(**args)
    return {"context": args["output"], "expected_manifest_sha256": receipt["manifest_sha256"]}, calls


def test_real_native_context_to_source_bound_decoder_samples(source_case):
    args, calls = recover(source_case)
    requests = len(calls)
    report = api.build_security_formula_corpus(**args)
    assert len(calls) == requests  # all decoder preparation is offline
    assert report["counts"]["file_entries"] == 6
    assert report["counts"]["functions_observed"] == 12
    assert report["counts"]["grammar_supported"] == report["counts"]["eligible_samples"] == 6
    assert report["counts"]["eligible_by_split"] == {"train": 2, "validation": 2, "test": 2}
    assert report["training_input_contract_satisfied"]
    assert report["counts"]["unsupported_functions"] == 6
    assert not report["cross_split_collisions"]
    assert report["same_split_duplicates"]  # fixed/parent literals differ but shape does not
    rows = {row["id"]: row for row in report["functions"]}
    for sample in report["samples"]:
        assert set(sample) == {"id", "split", "source", "source_sha256"}
        assert hashlib.sha256(sample["source"].encode()).hexdigest() == sample["source_sha256"]
        row = rows[sample["id"]]
        assert row["enclosing_scope"] == ["Container"]
        assert row["qualified_name"].startswith("Container.")
        assert row["code_unit_cid"] and row["source_context_cid"] and row["source_record_cid"]
        assert row["source_binding"]["normalized_body_sha256"] == sample["source_sha256"]
        assert not row["security_label_is_function_truth"]
        assert "cwe" not in sample["source"].lower()
    assert api.validate_security_formula_corpus(json.loads(json.dumps(report)), **args) == report
    assert all(report[name] == 0 for name in ("training_steps", "network_calls", "provider_calls"))
    assert not any(report[name] for name in ("heldout_evaluated", "heldout_semantic_claims",
        "source_semantics_verified", "proof_authority", "execution_authority", "learned_formula_generation"))


def test_cross_split_alpha_literal_collisions_keep_all_provenance_and_quarantine(source_case):
    args, _ = recover(source_case, collision=True)
    report = api.build_security_formula_corpus(**args)
    assert len(report["supported_samples"]) == 6 and report["samples"] == []
    assert report["counts"]["cross_split_collision_functions"] == 6
    assert report["cross_split_collisions"][0]["kind"] == "alpha_literal_shape"
    assert len(report["cross_split_collisions"][0]["sample_ids"]) == 6
    assert report["cross_split_collisions"][0]["splits"] == ["test", "train", "validation"]
    assert not report["training_input_contract_satisfied"]
    assert {sample["split"] for sample in report["supported_samples"]} == set(api.SPLITS)
    assert len(report["functions"]) == 12  # unsupported and colliding rows remain visible


def test_exact_function_bytes_cross_split_are_quarantined_even_when_files_differ(source_case):
    args, _ = recover(source_case, collision="body")
    report = api.build_security_formula_corpus(**args)
    assert report["samples"] == [] and len(report["supported_samples"]) == 6
    assert {row["kind"] for row in report["cross_split_collisions"]} == {"body", "alpha_literal_shape"}
    assert len({row["body_sha256"] for row in report["files"]}) == 6
    assert all(row["exclusion_reasons"] == ["cross_split_body_collision", "cross_split_alpha_literal_shape_collision"]
        for row in report["functions"] if row["grammar_status"] == "supported")


def test_no_supported_functions_remains_explicit_frontier(source_case):
    args, _ = recover(source_case, unsupported=True)
    report = api.build_security_formula_corpus(**args)
    assert report["samples"] == report["supported_samples"] == []
    assert report["counts"]["unsupported_functions"] == 12
    assert len([row for row in report["frontiers"] if row["kind"] == "function"]) == 12
    assert not report["training_input_contract_satisfied"]


def test_bound_accounts_for_omitted_functions_without_silent_drop(source_case):
    args, _ = recover(source_case)
    report = api.build_security_formula_corpus(**args, max_functions=1)
    assert report["counts"]["functions_observed"] == 12 and len(report["functions"]) == 12
    assert report["counts"]["grammar_supported"] == 1
    assert sum(row["unsupported_reason"] == "function_selection_bound_exceeded" for row in report["functions"]) == 11
    with pytest.raises(ValueError, match="bounded"):
        api.build_security_formula_corpus(**args, max_functions=True)


@pytest.mark.parametrize("mutation", ["source", "split", "authority", "bool_alias", "omission"])
def test_forged_samples_and_authority_cannot_pass_replay(source_case, mutation):
    args, _ = recover(source_case)
    report = api.build_security_formula_corpus(**args)
    if mutation == "source": report["samples"][0]["source"] += "\nraise RuntimeError()\n"
    elif mutation == "split": report["samples"][0]["split"] = "test"
    elif mutation == "authority": report["proof_authority"] = True
    elif mutation == "bool_alias": report["proof_authority"] = 0
    else: report["functions"].pop()
    with pytest.raises(ValueError, match="native grammar replay"):
        api.validate_security_formula_corpus(report, **args)


def test_corrupt_source_and_incorrect_span_fail_closed(source_case, monkeypatch):
    args, _ = recover(source_case)
    original = api._function_span
    def corrupt(raw, node):
        body, binding = original(raw, node)
        binding["line_byte_map"][0]["source_start_byte"] += 1
        return body, binding
    monkeypatch.setattr(api, "_function_span", corrupt)
    with pytest.raises(ValueError, match="byte map"):
        api.build_security_formula_corpus(**args)
    monkeypatch.setattr(api, "_function_span", original)
    loaded = context.load_security_source_context(args["context"], expected_manifest_sha256=args["expected_manifest_sha256"])
    (args["context"] / loaded["entries"][0]["body_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="source bytes"):
        api.build_security_formula_corpus(**args)

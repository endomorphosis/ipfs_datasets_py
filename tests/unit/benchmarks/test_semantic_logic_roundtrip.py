from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "benchmarks"
    / "bench_semantic_logic_roundtrip.py"
)
SPEC = importlib.util.spec_from_file_location(
    "bench_semantic_logic_roundtrip", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def _case() -> dict:
    return {
        "id": "test",
        "source_text": "Agency shall file notice unless emergency.",
        "allowed_atoms": {
            "actors": ["agency", "court"],
            "actions": ["file", "delete"],
            "objects": ["notice", "record"],
            "qualifiers": ["emergency", "within_10_days"],
        },
        "gold_ir": {
            "rules": [
                {
                    "modality": "O",
                    "actor": "agency",
                    "action": "file",
                    "object": "notice",
                    "conditions": [],
                    "exceptions": ["emergency"],
                    "temporal": [],
                }
            ]
        },
    }


def test_validate_and_compare_exact_semantic_ir() -> None:
    case = _case()
    ir = benchmark.validate_semantic_ir(case["gold_ir"], case)
    comparison = benchmark.compare_semantic_ir(ir, ir)

    assert comparison["exact_ir"] is True
    assert comparison["semantic_score"] == 1.0
    assert comparison["semantic_loss"] == 0.0
    assert comparison["facet_survival"] == {
        "modality": 1.0,
        "conditions": 1.0,
        "exceptions": 1.0,
        "temporal": 1.0,
    }


def test_compare_penalizes_consistently_wrong_round_trip() -> None:
    case = _case()
    wrong = {
        "rules": [
            {
                **case["gold_ir"]["rules"][0],
                "modality": "P",
                "exceptions": [],
            }
        ]
    }

    forward = benchmark.compare_semantic_ir(case["gold_ir"], wrong)
    cycle = benchmark.compare_semantic_ir(wrong, wrong)

    assert forward["semantic_score"] < 1.0
    assert cycle["semantic_score"] == 1.0
    assert forward["facet_survival"]["modality"] == 0.0
    assert forward["facet_survival"]["exceptions"] == 0.0


def test_maximum_weight_rule_matching_avoids_greedy_local_optimum() -> None:
    assignment = benchmark._maximum_weight_assignment(
        [[0.90, 0.80], [0.85, 0.0]]
    )

    assert assignment == [(0, 1), (1, 0)]
    assert sum(
        [[0.90, 0.80], [0.85, 0.0]][row][column]
        for row, column in assignment
    ) == pytest.approx(1.65)


def test_empty_ir_identity_is_explicitly_vacuous() -> None:
    comparison = benchmark.compare_semantic_ir(
        {"rules": []}, {"rules": []}
    )

    assert comparison["exact_ir"] is True
    assert comparison["nonvacuous"] is False
    assert comparison["exact_ir_nonvacuous"] is False
    assert comparison["semantic_score"] == 0.0


def test_aggregation_separates_execution_and_roundtrip_coverage() -> None:
    complete = {
        "status": "success",
        "l1": {"rules": [_case()["gold_ir"]["rules"][0]]},
        "l2": {"rules": [_case()["gold_ir"]["rules"][0]]},
        "forward_vs_gold": {"semantic_score": 1.0, "semantic_loss": 0.0},
        "cycle_l1_vs_l2": {"semantic_score": 1.0, "semantic_loss": 0.0},
        "end_to_end_vs_gold": {
            "semantic_score": 1.0,
            "semantic_loss": 0.0,
        },
        "timing": {"total_seconds": 1.0},
    }
    forward_only = {
        **complete,
        "l2": {"rules": []},
        "cycle_l1_vs_l2": {"semantic_score": 0.0, "semantic_loss": 1.0},
        "end_to_end_vs_gold": {
            "semantic_score": 0.0,
            "semantic_loss": 1.0,
        },
    }
    failed = {"status": "failed", "timing": {"total_seconds": 0.5}}

    aggregate = benchmark._aggregate_standard_arm(
        [complete, forward_only, failed]
    )

    assert aggregate["success_count"] == 2
    assert aggregate["forward_semantic_coverage_count"] == 2
    assert aggregate["full_roundtrip_coverage_count"] == 1
    assert aggregate["mean_forward_semantic_score"] == pytest.approx(2 / 3)
    assert aggregate["mean_cycle_semantic_score"] == pytest.approx(1 / 3)
    assert (
        aggregate["conditional_mean_forward_semantic_score"] == 1.0
    )


def test_validator_failure_is_persisted_on_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> dict:
        raise RuntimeError("validator unavailable")

    monkeypatch.setattr(benchmark, "attach_validators", fail)
    arm = {"status": "success", "l1": {"rules": []}, "l2": {"rules": []}}

    receipt = benchmark.attach_validators_safely(
        arm,
        case_id="case",
        arm_id="arm",
        lean_path="/missing/lean",
    )

    assert receipt["status"] == "failed"
    assert arm["validation"]["status"] == "failed"
    assert arm["validation"]["failure_type"] == "RuntimeError"


def test_validation_rejects_out_of_vocabulary_model_atoms() -> None:
    case = _case()
    candidate = {
        "rules": [
            {
                **case["gold_ir"]["rules"][0],
                "actor": "invented_actor",
            }
        ]
    }

    with pytest.raises(benchmark.BenchmarkError, match="outside"):
        benchmark.validate_semantic_ir(candidate, case)


def test_source_copy_metric_detects_exact_copy() -> None:
    source = (
        "The agency shall publish a notice describing the system of records "
        "within thirty calendar days after approval."
    )
    exact = benchmark.source_copy_metrics(source, source)
    unrelated = benchmark.source_copy_metrics(
        source, "A court may review a final order."
    )

    assert exact["exact_normalized_copy"] is True
    assert exact["copy_risk"] is True
    assert exact["shared_8gram_precision"] == 1.0
    assert unrelated["copy_risk"] is False
    assert unrelated["shared_8gram_count"] == 0


def test_fixture_has_five_complexity_strata_and_24_rules() -> None:
    cases = benchmark._load_cases(benchmark.DEFAULT_FIXTURE)

    assert len(cases) == 5
    assert sum(len(case["gold_ir"]["rules"]) for case in cases) == 24
    assert max(len(case["gold_ir"]["rules"]) for case in cases) == 12
    assert all(case["source_text_cid"].startswith("bafk") for case in cases)


def test_leanstral_encode_token_budget_never_reads_gold_ir() -> None:
    class GoldReadTrap(dict):
        def __getitem__(self, key: object) -> object:
            if key == "gold_ir":
                raise AssertionError("model request read hidden gold IR")
            return super().__getitem__(key)

    class RecordingClient:
        def __init__(self) -> None:
            self.max_tokens: list[int] = []

        def complete_json(self, **kwargs: object) -> object:
            self.max_tokens.append(int(kwargs["max_tokens"]))
            return benchmark.TimedResult(
                deepcopy(_case()["gold_ir"]),
                0.0,
                {"request_cid": "test-request"},
            )

    visible_case = GoldReadTrap(
        {
            key: deepcopy(value)
            for key, value in _case().items()
            if key != "gold_ir"
        }
    )
    client = RecordingClient()

    result = benchmark._leanstral_encode(
        client, visible_case, str(visible_case["source_text"])
    )

    assert result.value == _case()["gold_ir"]
    assert client.max_tokens == [
        benchmark._semantic_encode_max_tokens(
            str(visible_case["source_text"]),
            benchmark._semantic_schema_for_case(
                visible_case, str(visible_case["source_text"])
            ),
        )
    ]


def test_leanstral_encode_budget_is_invariant_to_gold_rule_count() -> None:
    source = str(_case()["source_text"])
    case_with_one_rule = _case()
    case_with_many_gold_rules = deepcopy(case_with_one_rule)
    case_with_many_gold_rules["gold_ir"]["rules"] *= 12

    first_schema = benchmark._semantic_schema_for_case(
        case_with_one_rule, source
    )
    second_schema = benchmark._semantic_schema_for_case(
        case_with_many_gold_rules, source
    )

    assert benchmark._semantic_encode_max_tokens(
        source, first_schema
    ) == benchmark._semantic_encode_max_tokens(source, second_schema)


def test_symai_reverse_is_source_withheld_strict_and_secret_safe() -> None:
    captured: dict[str, object] = {}

    def invoke(
        prompt: str, response_format: object
    ) -> tuple[str, dict[str, object]]:
        captured["prompt"] = prompt
        captured["response_format"] = response_format
        return (
            json.dumps(
                {
                    "text": (
                        "The agency shall file the notice unless there is "
                        "an emergency."
                    )
                }
            ),
            {
                "effective_provider_name": "ipfs_accelerate_py",
                "resolved_provider_name": "leanstral_local",
                "service_endpoint": "http://127.0.0.1:8080/v1",
                "api_key": "must-not-be-retained",
            },
        )

    case = _case()
    result = benchmark._symai_realize(
        case, case["gold_ir"], invoke=invoke
    )

    assert case["source_text"] not in str(captured["prompt"])
    assert '"actor":"agency"' in str(captured["prompt"])
    response_format = captured["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert result.value.startswith("The agency shall file")
    assert result.metadata["source_withheld"] is True
    assert "api_key" not in result.metadata["router_metadata"]
    assert (
        result.metadata["router_metadata"]["resolved_provider_name"]
        == "leanstral_local"
    )


def test_symai_reverse_rejects_nonexact_realization_contract() -> None:
    def invoke(
        prompt: str, response_format: object
    ) -> tuple[str, dict[str, object]]:
        del prompt, response_format
        return (
            '{"text":"The agency shall file.","explanation":"extra"}',
            {},
        )

    case = _case()
    with pytest.raises(
        benchmark.BenchmarkError,
        match="exactly one text string",
    ):
        benchmark._symai_realize(
            case, case["gold_ir"], invoke=invoke
        )


def test_symai_oracle_reverse_labels_mixed_recompiler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSymaiRunner:
        def realize(
            self,
            case: object,
            logic_ir: object,
            *,
            run_id: str,
        ) -> object:
            del case, logic_ir, run_id
            return benchmark.TimedResult(
                "The agency shall file the notice unless emergency.",
                0.25,
                {"request_cid": "symai-request"},
            )

    def fake_reencode(
        client: object,
        case: object,
        text: str,
        *,
        nlp: object | None = None,
    ) -> object:
        del client, text, nlp
        assert isinstance(case, dict)
        return benchmark.TimedResult(
            deepcopy(case["gold_ir"]),
            0.5,
            {"request_cid": "leanstral-request"},
        )

    monkeypatch.setattr(benchmark, "_leanstral_encode", fake_reencode)
    case = _case()
    result = benchmark.run_symai_oracle_reverse_cycle(
        case,
        FakeSymaiRunner(),
        object(),
        run_id="test-run",
    )

    assert result["status"] == "success"
    assert result["translator"] == (
        "symai_reverse_plus_leanstral_recompile"
    )
    assert result["oracle_l1"] is True
    assert result["pure_symai_roundtrip"] is False
    assert result["cycle_l1_vs_l2"]["semantic_score"] == 1.0
    assert [receipt["operation"] for receipt in result["receipts"]] == [
        "realize_via_symai",
        "reencode_via_direct_leanstral",
    ]

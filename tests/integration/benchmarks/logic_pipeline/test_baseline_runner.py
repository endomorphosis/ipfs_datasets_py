from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from benchmarks.logic_pipeline import runner
from benchmarks.logic_pipeline.contracts import (
    CacheMode,
    CaseResultRecord,
    OutcomeStatus,
    TELEMETRY_SCHEMA,
    canonical_json,
)


ROOT = Path(__file__).resolve().parents[4]


class _FakeModalIR:
    formulas = (object(),)

    def to_dict(self) -> dict[str, object]:
        return {"schema": "fake-modal-ir.v1", "formulas": [{"operator": "O"}]}


class _FakeCodec:
    def __init__(self, *, fail_case_id: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail_case_id = fail_case_id

    def encode(
        self,
        text: str,
        *,
        document_id: str,
        source: str,
    ) -> object:
        assert source == "logic_pipeline_benchmark"
        self.calls.append(document_id)
        if document_id == self.fail_case_id:
            raise RuntimeError("deliberate backend failure")
        return SimpleNamespace(
            encoding=SimpleNamespace(
                model_name="en_core_web_sm",
                used_fallback_model=True,
                tokens=("Every", "person"),
            ),
            metadata={"llm_call_count": 0},
            modal_ir=_FakeModalIR(),
            parser_name="spacy_modal_codec_v1",
            selected_frame="normative-rule",
        )


def _manifest() -> runner.FrozenBaselineManifest:
    return runner.load_baseline_manifest(
        ROOT / runner.DEFAULT_BASELINE_MANIFEST_PATH
    )


def test_frozen_manifest_binds_evidence_route_cases_and_source() -> None:
    manifest = _manifest()
    payload = manifest.to_dict()

    assert callable(runner.HSSLEV0404E6E)
    assert payload["evidence"] == runner.HSSLEV0404E6E()
    assert manifest.digest == runner.FROZEN_BASELINE_MANIFEST_SHA256
    assert payload["configuration"]["requested_variant_id"] == "A0"
    assert payload["configuration"]["effective_variant_id"] == "A0"
    assert payload["configuration"]["route"]["entrypoints"] == list(
        runner.CURRENT_ROUTE
    )
    assert payload["configuration"]["route"]["components_not_invoked"] == [
        "symai",
        "hammer",
        "leanstral",
    ]
    assert payload["source"]["repository_commit"] == (
        "2a1be00b1b76e6652c25d418752affbf0f85d176"
    )
    assert len(payload["source"]["submodules"]) == 10
    assert manifest.pilot_case_ids == tuple(
        f"pilot-p{index:02d}" for index in range(1, 11)
    )


def test_requested_and_effective_spacy_fallback_are_both_explicit() -> None:
    configuration = _manifest().to_dict()["configuration"]

    assert configuration["requested"]["spacy_model_name"] == "en_core_web_sm"
    assert configuration["effective"] == {
        "llm_call_count": 0,
        "parser_backend": "spacy",
        "spacy_effective_model": "spacy.blank:en",
        "spacy_mode": "blank_model",
        "spacy_pipeline": ["sentencizer"],
        "spacy_requested_model": "en_core_web_sm",
        "spacy_used_fallback_model": True,
        "spacy_version": "3.8.14",
    }
    assert _manifest().to_dict()["capability_snapshot"]["status"] == "degraded"


def test_cold_and_warm_contracts_are_distinct_and_frozen() -> None:
    contracts = _manifest().run_contracts

    assert tuple(contract.cache_mode for contract in contracts) == (
        CacheMode.COLD,
        CacheMode.WARM,
    )
    assert contracts[0].cache_namespace != contracts[1].cache_namespace
    assert all(contract.requested_variant_id == "A0" for contract in contracts)
    assert all(contract.effective_variant_id == "A0" for contract in contracts)
    assert all(not contract.tuning_permitted for contract in contracts)


def test_validate_only_cli_is_read_only_and_dependency_free() -> None:
    baseline_root = ROOT / runner.FROZEN_BASELINE_ROOT
    before = sorted(
        path.relative_to(baseline_root).as_posix()
        for path in baseline_root.rglob("*")
    )
    process = subprocess.run(
        [
            sys.executable,
            "benchmarks/logic_pipeline/runner.py",
            "--variant",
            "A0",
            "--split",
            "pilot",
            "--validate-only",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    after = sorted(
        path.relative_to(baseline_root).as_posix()
        for path in baseline_root.rglob("*")
    )

    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {
        "baseline_id": runner.BASELINE_ID,
        "baseline_manifest_sha256": runner.FROZEN_BASELINE_MANIFEST_SHA256,
        "cache_modes": ["cold", "warm"],
        "case_count": 10,
        "split": "pilot",
        "status": "valid",
        "variant_id": "A0",
    }
    assert before == after
    assert "ipfs_datasets_py" not in process.stderr


@pytest.mark.parametrize(
    ("variant", "split", "message"),
    [
        ("A1", "pilot", "only baseline variant A0"),
        ("A0", "development", "only the pilot split"),
    ],
)
def test_cli_rejects_nonbaseline_scope(
    variant: str, split: str, message: str
) -> None:
    process = subprocess.run(
        [
            sys.executable,
            "benchmarks/logic_pipeline/runner.py",
            "--variant",
            variant,
            "--split",
            split,
            "--validate-only",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert process.returncode == 2
    assert message in process.stderr


def test_manifest_tamper_and_noncanonical_bytes_fail_closed(
    tmp_path: Path,
) -> None:
    payload = _manifest().to_dict()
    payload["configuration"]["route"]["components_not_invoked"].remove("hammer")
    tampered = tmp_path / "tampered.json"
    tampered.write_text(canonical_json(payload) + "\n", encoding="utf-8")

    with pytest.raises(runner.BaselineValidationError):
        runner.load_baseline_manifest(tampered)

    original = _manifest().to_dict()
    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(runner.BaselineValidationError, match="not canonical"):
        runner.load_baseline_manifest(noncanonical)


def test_execution_emits_one_strict_result_per_case_and_cache_mode(
    tmp_path: Path,
) -> None:
    codec = _FakeCodec()
    summary = runner.execute_baseline(
        _manifest(),
        output_root=tmp_path,
        codec_factory=lambda: codec,
    )
    result_path = Path(str(summary["case_results_path"]))
    records = tuple(
        CaseResultRecord.from_dict(json.loads(line))
        for line in result_path.read_text(encoding="utf-8").splitlines()
    )

    assert len(records) == 20
    assert len({(record.case_id, record.cache_mode) for record in records}) == 20
    assert tuple(record.case_id for record in records[:10]) == (
        _manifest().pilot_case_ids
    )
    assert tuple(record.case_id for record in records[10:]) == (
        _manifest().pilot_case_ids
    )
    assert all(record.status is OutcomeStatus.NOT_VERIFIED for record in records)
    assert all(len(record.stages) == 1 for record in records)
    assert all(record.stages[0].stage.value == "compiler" for record in records)
    assert all(
        record.stages[0].telemetry.schema == TELEMETRY_SCHEMA
        and set(record.stages[0].telemetry.to_dict())
        == set(runner.TELEMETRY_FIELDS)
        for record in records
    )
    assert all(
        record.stages[0].data["spacy_used_fallback_model"] is True
        for record in records
    )
    assert summary["components_not_invoked"] == ["symai", "hammer", "leanstral"]
    assert codec.calls == [
        *list(_manifest().pilot_case_ids),
        *list(_manifest().pilot_case_ids),
    ]

    with pytest.raises(runner.BaselineValidationError, match="overwrite"):
        runner.execute_baseline(
            _manifest(),
            output_root=tmp_path,
            codec_factory=_FakeCodec,
        )


def test_backend_failure_is_retained_as_a_case_result(tmp_path: Path) -> None:
    codec = _FakeCodec(fail_case_id="pilot-p03")
    summary = runner.execute_baseline(
        _manifest(),
        output_root=tmp_path,
        codec_factory=lambda: codec,
        cache_modes=(CacheMode.COLD,),
    )
    records = [
        CaseResultRecord.from_dict(json.loads(line))
        for line in Path(str(summary["case_results_path"]))
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert len(records) == 10
    failed = next(record for record in records if record.case_id == "pilot-p03")
    assert failed.status is OutcomeStatus.INFRASTRUCTURE_FAILURE
    assert failed.failure_detail == "compiler adapter raised RuntimeError"
    assert {record.case_id for record in records} == set(
        _manifest().pilot_case_ids
    )

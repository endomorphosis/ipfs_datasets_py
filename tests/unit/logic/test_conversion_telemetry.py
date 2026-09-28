"""Conversion telemetry keeps scores, errors, and hyperparameters together."""

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal.conversion_telemetry import (
    TELEMETRY_COLUMNS,
    TELEMETRY_REPO_PATH,
    TELEMETRY_SCHEMA,
    conversion_telemetry_rows,
    default_hyperparameters,
    publish_conversion_telemetry,
    write_conversion_telemetry,
)
from ipfs_datasets_py.logic.autoformal.span_evidence import SpanEvidenceError


def _evidence() -> list[dict]:
    return [
        {
            "agrees": True,
            "compiler_reason": "",
            "compiler_status": "compiled",
            "cosine_similarity": 0.91,
            "cross_entropy_loss": 1.2,
            "formalized": False,
            "lake_ok": True,
            "lake_disposition": "duty",
            "legal_id": "usc:us:5:552",
            "reconstruction_loss": 0.08,
            "repair_error": "",
            "source_sha256": "abc",
            "source_span_id": "span-duty",
            "status": "sealed",
            "train": False,
        },
        {
            "agrees": False,
            "compiler_reason": "compiler_abstain:penalty",
            "compiler_status": "abstain",
            "cosine_similarity": 0.4,
            "cross_entropy_loss": 2.8,
            "formalized": False,
            "lake_ok": False,
            "lake_disposition": "unrendered",
            "legal_id": "usc:us:18:1001",
            "reconstruction_loss": 0.44,
            "repair_error": "penalty is not a duty",
            "source_sha256": "def",
            "source_span_id": "span-penalty",
            "status": "gap",
            "train": True,
        },
    ]


def test_span_and_run_rows_keep_losses_errors_and_hyperparameters():
    training = {
        "rounds": 2,
        "seed": 7,
        "history": [
            {"learning_rate": 0.35, "scores": {"cosine_similarity": 0.5, "cross_entropy_loss": 2.0, "reconstruction_loss": 0.3}},
            {"learning_rate": 0.175, "movement": "better", "scores": {"cosine_similarity": 0.8, "cross_entropy_loss": 1.4, "reconstruction_loss": 0.1}},
        ],
    }
    rows = conversion_telemetry_rows(_evidence(), training=training)
    assert rows[-1]["record_kind"] == "run"
    assert rows[-1]["schema_version"] == TELEMETRY_SCHEMA
    duty, penalty, run = rows
    assert duty["cosine_similarity"] == 0.91
    assert duty["cross_entropy_loss"] == 1.2
    assert duty["learning_rate"] == 0.175
    assert penalty["repair_error"] == "penalty is not a duty"
    assert penalty["compiler_reason"] == "compiler_abstain:penalty"
    assert penalty["train"] is True
    assert run["cosine_similarity"] == pytest.approx((0.91 + 0.4) / 2)
    assert run["cross_entropy_loss"] == pytest.approx((1.2 + 2.8) / 2)
    assert run["rounds"] == 2
    assert run["seed"] == 7
    params = json.loads(run["hyperparameters_json"])
    assert params["min_cosine_similarity"] == 0.72
    assert params["projection_max_update_families"] == 4
    assert params["temperature"] == 0
    assert json.loads(run["history_json"])[1]["movement"] == "better"
    assert json.loads(run["error_json"]) == {"gap_count": 1, "span_count": 2}
    assert all(row["admitted"] is False and row["formalized"] is False and row["wrote_compiler"] is False for row in rows)


def test_absent_scores_stay_null_and_unknown_hyperparameters_are_refused():
    rows = conversion_telemetry_rows([{"source_span_id": "span-1", "status": "gap", "agrees": False}])
    assert rows[0]["cosine_similarity"] is None
    assert rows[0]["cross_entropy_loss"] is None
    assert rows[1]["cosine_similarity"] is None
    with pytest.raises(SpanEvidenceError):
        default_hyperparameters(admitted=True)


def test_telemetry_parquet_is_not_the_sealed_cache_or_jsonl(tmp_path: Path):
    rows = conversion_telemetry_rows(_evidence())
    written = write_conversion_telemetry(rows, tmp_path / "conversion-telemetry.parquet")
    assert written["jsonl_written"] is False
    assert written["admitted"] is False
    assert not (tmp_path / "conversion-telemetry.jsonl").exists()
    table = pq.read_table(tmp_path / "conversion-telemetry.parquet")
    assert table.column_names == list(TELEMETRY_COLUMNS)
    assert table.num_rows == 3
    with pytest.raises(SpanEvidenceError):
        write_conversion_telemetry(rows, tmp_path / "sealed-spans.parquet")
    with pytest.raises(SpanEvidenceError):
        write_conversion_telemetry(rows, tmp_path / "resume-checkpoint.parquet")


def test_dry_run_publish_stays_on_the_span_cache_repository(tmp_path: Path):
    path = tmp_path / "conversion-telemetry.parquet"
    write_conversion_telemetry(conversion_telemetry_rows(_evidence()), path)
    dry = publish_conversion_telemetry(path, upload=False)
    assert dry["uploaded"] is False
    assert dry["repository_id"] == "justicedao/uscode-autoformal-span-cache"
    assert dry["path_in_repo"] == TELEMETRY_REPO_PATH
    assert dry["admitted"] is False

    class Api:
        def __init__(self) -> None:
            self.kwargs: dict = {}

        def create_repo(self, *args, **kwargs) -> None:
            del args, kwargs

        def upload_file(self, **kwargs):
            self.kwargs = kwargs
            return type("Commit", (), {"oid": "abc"})()

    api = Api()
    with pytest.raises(SpanEvidenceError):
        publish_conversion_telemetry(path, upload=True, path_in_repo="sealed-spans.parquet", api=api)
    receipt = publish_conversion_telemetry(
        path,
        upload=True,
        path_in_repo="autoformal/uscode/batches/tiny-1/conversion-telemetry.parquet",
        api=api,
    )
    assert receipt["uploaded"] is True
    assert receipt["formalized"] is False
    assert api.kwargs["repo_id"] == "justicedao/uscode-autoformal-span-cache"
    assert api.kwargs["repo_type"] == "dataset"
    assert api.kwargs["path_in_repo"].endswith("conversion-telemetry.parquet")
